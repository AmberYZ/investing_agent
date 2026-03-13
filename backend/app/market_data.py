"""
Market data for instruments (stocks/ETFs) via EODHD.
Returns price history and valuation (trailing PE, forward PE, PEG, earnings growth) for the frontend chart.
Uses in-memory cache (configurable TTL, default 2h) and light throttling.

Notes:
- EODHD uses ticker format SYMBOL.EXCHANGE (e.g., AAPL.US). We append .US for symbols without an exchange.
- Fundamentals: Valuation (TrailingPE, ForwardPE), Highlights (PEGRatio, QuarterlyEarningsGrowthYOY, etc.)
- Earnings: Earnings.History has quarterly epsActual; we build trailing 12M EPS from reported quarters.
- News: /api/news?s=TICKER returns list with title, link, date, sentiment.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

from sqlalchemy import text

from app.db import engine
from app.settings import settings

_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_ESTIMATES_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_EARNINGS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_last_request_time: float = 0.0
_lock = threading.Lock()

BASE_URL = "https://eodhd.com/api"


def _cache_ttl_seconds() -> int:
    return getattr(settings, "eodhd_cache_ttl_seconds", 7200)


def _min_seconds_between_requests() -> float:
    return getattr(settings, "eodhd_min_seconds_between_requests", 0.1)


def _to_eodhd_symbol(symbol: str) -> str:
    """Convert symbol (e.g. AAPL, SPY) to EODHD format (e.g. AAPL.US)."""
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    if "." in s:
        return s
    return f"{s}.US"


# ~21 trading days per month (252/year); use for bar count so "6 months" ≈ 6 calendar months
TRADING_DAYS_PER_MONTH = 21

# Technical indicator periods
SMA_PERIOD = 20
RSI_PERIOD = 20
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


def _sma(closes: list[float], period: int) -> list[float | None]:
    """SMA for each index; None for first (period-1) bars."""
    out: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        s = sum(closes[i - period + 1 : i + 1])
        out[i] = round(s / period, 4)
    return out


def _rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """RSI for each index; None until enough data."""
    out: list[float | None] = [None] * len(closes)
    for i in range(1, len(closes)):
        if i < period:
            continue
        gains, losses = 0.0, 0.0
        for j in range(i - period + 1, i + 1):
            ch = closes[j] - closes[j - 1]
            if ch > 0:
                gains += ch
            else:
                losses -= ch
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = round(100 - (100 / (1 + rs)), 2)
    return out


def _ema(values: list[float], period: int) -> list[float]:
    """EMA; first value is SMA of first period values."""
    out: list[float] = []
    k = 2.0 / (period + 1)
    for i, v in enumerate(values):
        if i < period - 1:
            out.append(v)
        elif i == period - 1:
            out.append(sum(values[:period]) / period)
        else:
            out.append(round(v * k + out[-1] * (1 - k), 4))
    return out


def _macd(
    closes: list[float], fast: int, slow: int, signal: int
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD line, signal line, histogram. None until enough data for slow EMA."""
    n = len(closes)
    macd_line: list[float | None] = [None] * n
    signal_line: list[float | None] = [None] * n
    hist: list[float | None] = [None] * n
    if n < slow:
        return macd_line, signal_line, hist
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    for i in range(slow - 1, n):
        macd_line[i] = round(ema_fast[i] - ema_slow[i], 4)
    macd_vals = [macd_line[i] for i in range(slow - 1, n) if macd_line[i] is not None]
    if len(macd_vals) < signal:
        return macd_line, signal_line, hist
    signal_ema = _ema(macd_vals, signal)
    for i in range(signal - 1, len(signal_ema)):
        idx = slow - 1 + i
        if idx < n:
            signal_line[idx] = round(signal_ema[i], 4)
    for i in range(n):
        if macd_line[i] is not None and signal_line[i] is not None:
            hist[i] = round(macd_line[i] - signal_line[i], 4)
    return macd_line, signal_line, hist


def _add_indicators(prices: list[dict[str, Any]]) -> None:
    """Mutate each price dict to add sma_20, rsi_14, macd_*, etc."""
    if not prices:
        return
    closes = [p["close"] for p in prices]
    sma = _sma(closes, SMA_PERIOD)
    rsi = _rsi(closes, RSI_PERIOD)
    macd_line, macd_signal, macd_hist = _macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    for i, p in enumerate(prices):
        p["sma_20"] = sma[i]
        p["rsi_14"] = rsi[i]
        p["macd_line"] = macd_line[i]
        p["macd_signal"] = macd_signal[i]
        p["macd_hist"] = macd_hist[i]


def _is_rate_limit_error(message: str) -> bool:
    msg = (message or "").lower()
    return "rate limit" in msg or "too many requests" in msg or "429" in msg or "try after" in msg


def _lookup_forward_pe_from_portfolio(symbol: str) -> float | None:
    """
    Fallback for forward P/E when missing from the data provider.

    Looks up price / prospective earnings from the valuations_rates_portfolio table
    (if present in the same database), keyed by symbol.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT price_prospective_earnings "
                    "FROM valuations_rates_portfolio "
                    "WHERE symbol = :symbol"
                ),
                {"symbol": sym},
            ).first()
        if not row:
            return None
        value = row[0]
        if value in (None, "", "None", "-"):
            return None
        return round(float(value), 2)
    except Exception:
        # Silently ignore if the table/column does not exist or value is invalid.
        return None


# Symbol search cache: key = normalized keywords, value = (cached_at, list[dict]); short TTL for typeahead
_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_SEARCH_CACHE_TTL = 300  # 5 minutes

# News cache: key = symbol, value = (cached_at, list[dict]); 1h TTL
_NEWS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_NEWS_CACHE_TTL = 3600  # 1 hour


def search_symbols(keywords: str) -> dict[str, Any]:
    """
    EODHD Search API: search by company name or ticker for typeahead when adding instruments.
    Returns {"matches": [...], "message": None or error string}.
    """
    global _last_request_time
    keywords = (keywords or "").strip()[:64]
    out: dict[str, Any] = {"matches": [], "message": None}
    if not keywords:
        return out

    api_key = (getattr(settings, "eodhd_api_key", "") or "").strip()
    if not api_key:
        out["message"] = "EODHD API key not set. Add EODHD_API_KEY to .env"
        return out

    cache_key = keywords.lower()
    now = time.monotonic()
    with _lock:
        if cache_key in _SEARCH_CACHE:
            cached_at, cached = _SEARCH_CACHE[cache_key]
            if now - cached_at < _SEARCH_CACHE_TTL:
                return {"matches": cached, "message": None}
            del _SEARCH_CACHE[cache_key]
        elapsed = now - _last_request_time
        if elapsed < _min_seconds_between_requests():
            time.sleep(_min_seconds_between_requests() - elapsed)
        _last_request_time = time.monotonic()

    try:
        import httpx
    except ImportError:
        out["message"] = "httpx not installed"
        return out

    try:
        url = f"{BASE_URL}/search/{keywords}"
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, params={"api_token": api_key, "fmt": "json", "limit": 25})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
        return out

    with _lock:
        _last_request_time = time.monotonic()

    if not isinstance(data, list):
        return out

    for i, row in enumerate(data[:25]):
        if not isinstance(row, dict):
            continue
        code = (row.get("Code") or "").strip()
        if not code:
            continue
        exchange = (row.get("Exchange") or "US").strip()
        # Store base symbol for US (e.g. AAPL); full Code.Exchange for others (e.g. AAPL.BA)
        symbol = code if (exchange and exchange.upper() == "US") else f"{code}.{exchange}"
        name = (row.get("Name") or "").strip() or None
        raw_type = (row.get("Type") or "").strip().lower()
        if "etf" in raw_type or "fund" in raw_type:
            type_ = "etf"
        elif raw_type:
            type_ = raw_type[:16]
        else:
            type_ = "stock"
        region = (row.get("Country") or "").strip() or None
        currency = (row.get("Currency") or "").strip() or None
        match_score = 1.0 - (i * 0.02) if i < 20 else 0.6
        out["matches"].append({
            "symbol": symbol,
            "name": name,
            "type": type_,
            "region": region,
            "currency": currency,
            "match_score": round(match_score, 4),
        })

    with _lock:
        if not out["message"]:
            _SEARCH_CACHE[cache_key] = (time.monotonic(), out["matches"])
    return out


def fetch_news_for_ticker(symbol: str, limit: int = 10) -> dict[str, Any]:
    """
    EODHD News API: fetch recent news for a ticker.
    Returns {"items": [{"title", "url", "time", "source", "sentiment"}], "message": None or error string}.
    """
    global _last_request_time
    symbol = (symbol or "").strip().upper()
    out: dict[str, Any] = {"items": [], "message": None}
    if not symbol:
        out["message"] = "Symbol required."
        return out

    api_key = (getattr(settings, "eodhd_api_key", "") or "").strip()
    if not api_key:
        out["message"] = "EODHD API key not set. Add EODHD_API_KEY to .env"
        return out

    eodhd_symbol = _to_eodhd_symbol(symbol)
    now = time.monotonic()
    with _lock:
        if symbol in _NEWS_CACHE:
            cached_at, cached = _NEWS_CACHE[symbol]
            if now - cached_at < _NEWS_CACHE_TTL:
                return {"items": cached, "message": None}
            del _NEWS_CACHE[symbol]
        elapsed = now - _last_request_time
        if elapsed < _min_seconds_between_requests():
            time.sleep(_min_seconds_between_requests() - elapsed)
        _last_request_time = time.monotonic()

    try:
        import httpx
    except ImportError:
        out["message"] = "httpx not installed"
        return out

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                f"{BASE_URL}/news",
                params={"s": eodhd_symbol, "api_token": api_key, "fmt": "json", "limit": min(limit, 50)},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
        return out

    with _lock:
        _last_request_time = time.monotonic()

    if not isinstance(data, list):
        return out

    items: list[dict[str, Any]] = []
    for entry in data[:limit]:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        url = (entry.get("link") or "").strip() or None
        time_pub = entry.get("date")
        time_str = str(time_pub)[:19] if time_pub else None
        source = None
        sent = entry.get("sentiment")
        sentiment = None
        if isinstance(sent, dict) and "polarity" in sent:
            try:
                p = float(sent["polarity"])
                if p > 0.1:
                    sentiment = "positive"
                elif p < -0.1:
                    sentiment = "negative"
                else:
                    sentiment = "neutral"
            except (TypeError, ValueError):
                pass
        items.append({
            "title": title,
            "url": url,
            "time": time_str,
            "source": source,
            "sentiment": sentiment,
        })

    with _lock:
        if not out["message"]:
            _NEWS_CACHE[symbol] = (time.monotonic(), items)
    return {"items": items, "message": None}


def compute_period_returns(prices: list[dict[str, Any]]) -> dict[str, float | None]:
    """
    Compute 1M, 3M, YTD, 6M % return from a sorted-by-date (asc) prices list.
    Each price must have "date" (YYYY-MM-DD) and "close".
    Returns dict with pct_1m, pct_3m, pct_ytd, pct_6m (None if insufficient data).
    """
    out: dict[str, float | None] = {"pct_1m": None, "pct_3m": None, "pct_ytd": None, "pct_6m": None}
    if not prices or len(prices) < 2:
        return out
    try:
        last_date = dt.datetime.strptime(prices[-1]["date"][:10], "%Y-%m-%d").date()
        last_close = float(prices[-1]["close"])
    except (KeyError, TypeError, ValueError):
        return out

    def _return_for_days(days_back: int) -> float | None:
        target = last_date - dt.timedelta(days=days_back)
        target_str = target.isoformat()
        start_close = None
        for p in prices:
            d = (p.get("date") or "")[:10]
            if d <= target_str:
                try:
                    start_close = float(p.get("close", 0))
                except (TypeError, ValueError):
                    pass
        if start_close is None or start_close <= 0:
            return None
        return round((last_close - start_close) / start_close * 100, 2)

    def _return_ytd() -> float | None:
        ytd_start = last_date.replace(month=1, day=1)
        target_str = ytd_start.isoformat()
        start_close = None
        for p in prices:
            d = (p.get("date") or "")[:10]
            if d <= target_str:
                try:
                    start_close = float(p.get("close", 0))
                except (TypeError, ValueError):
                    pass
        if start_close is None or start_close <= 0:
            return None
        return round((last_close - start_close) / start_close * 100, 2)

    out["pct_1m"] = _return_for_days(31)
    out["pct_3m"] = _return_for_days(92)
    out["pct_ytd"] = _return_ytd()
    out["pct_6m"] = _return_for_days(183)
    return out


def _fetch_one(symbol: str, months: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "symbol": symbol,
        "prices": [],
        "trailing_pe": None,
        "forward_pe": None,
        "peg_ratio": None,
        "ev_to_ebitda": None,
        "quarterly_earnings_growth_yoy": None,
        "quarterly_revenue_growth_yoy": None,
        "message": None,
    }
    api_key = (getattr(settings, "eodhd_api_key", "") or "").strip()
    if not api_key:
        out["message"] = "EODHD API key not set. Add EODHD_API_KEY to .env"
        return out

    try:
        import httpx
    except ImportError:
        out["message"] = "httpx not installed"
        return out

    eodhd_symbol = _to_eodhd_symbol(symbol)
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=months * 31)

    try:
        with httpx.Client(timeout=30.0) as client:
            # 1) EOD historical prices
            r_eod = client.get(
                f"{BASE_URL}/eod/{eodhd_symbol}",
                params={
                    "api_token": api_key,
                    "fmt": "json",
                    "from": start_date.isoformat(),
                    "to": end_date.isoformat(),
                },
            )
            r_eod.raise_for_status()
            data_eod = r_eod.json()

            if isinstance(data_eod, list):
                for day in data_eod:
                    if not isinstance(day, dict):
                        continue
                    try:
                        date_str = (day.get("date") or "")[:10]
                        # Use adjusted_close (split/dividend adjusted) when available for correct charts across splits
                        adj = day.get("adjusted_close")
                        close = float(adj) if adj not in (None, "", "-") else float(day.get("close", 0))
                        open_ = float(day.get("open", 0))
                        high = float(day.get("high", 0))
                        low = float(day.get("low", 0))
                        vol = int(float(day.get("volume", 0)))
                    except (TypeError, ValueError):
                        continue
                    out["prices"].append({
                        "date": date_str,
                        "open": round(open_, 4),
                        "high": round(high, 4),
                        "low": round(low, 4),
                        "close": round(close, 4),
                        "volume": vol,
                    })
                out["prices"].sort(key=lambda x: x["date"])
                _add_indicators(out["prices"])
            elif isinstance(data_eod, dict) and data_eod.get("errors"):
                out["message"] = str(data_eod.get("errors", "Unknown error"))

            # 2) Fundamentals for PE ratios and growth
            r_fund = client.get(
                f"{BASE_URL}/fundamentals/{eodhd_symbol}",
                params={"api_token": api_key, "fmt": "json"},
            )
            r_fund.raise_for_status()
            data_fund = r_fund.json()

            if isinstance(data_fund, dict):
                def _safe_float(obj: dict | None, *keys: str):
                    if not obj:
                        return None
                    for k in keys:
                        v = obj.get(k)
                        if v in (None, "", "None", "-"):
                            continue
                        try:
                            return round(float(v), 2)
                        except (TypeError, ValueError):
                            continue
                    return None

                def _safe_int(obj: dict | None, *keys: str):
                    if not obj:
                        return None
                    for k in keys:
                        v = obj.get(k)
                        if v in (None, "", "None", "-"):
                            continue
                        try:
                            return int(float(v))
                        except (TypeError, ValueError):
                            continue
                    return None

                val = data_fund.get("Valuation") or {}
                hl = data_fund.get("Highlights") or {}
                tech = data_fund.get("Technicals") or {}
                ar = data_fund.get("AnalystRatings") or {}
                # ETF-specific valuation growth block lives under ETF_Data.Valuations_Growth.
                etf = data_fund.get("ETF_Data") or {}
                vg = (etf.get("Valuations_Growth") if isinstance(etf, dict) else None) or data_fund.get("Valuations_Growth") or {}
                vrp = vg.get("Valuations_Rates_Portfolio") if isinstance(vg, dict) else {}
                out["trailing_pe"] = _safe_float(val, "TrailingPE") or _safe_float(hl, "PERatio")
                out["forward_pe"] = _safe_float(val, "ForwardPE")
                if out["forward_pe"] is None:
                    # For ETFs and other instruments where ForwardPE is often missing,
                    # first fall back to Valuations_Growth.Valuations_Rates_Portfolio["Price/Prospective Earnings"]
                    # from the same fundamentals payload, then (legacy) database table when available.
                    if isinstance(vrp, dict):
                        alt_forward = _safe_float(vrp, "Price/Prospective Earnings")
                        if alt_forward is not None:
                            out["forward_pe"] = alt_forward
                    if out["forward_pe"] is None:
                        alt_forward = _lookup_forward_pe_from_portfolio(symbol)
                        if alt_forward is not None:
                            out["forward_pe"] = alt_forward
                out["peg_ratio"] = _safe_float(hl, "PEGRatio")
                out["ev_to_ebitda"] = _safe_float(val, "EnterpriseValueEbitda")
                qeg = _safe_float(hl, "QuarterlyEarningsGrowthYOY")
                if qeg is not None and abs(qeg) <= 2:
                    out["quarterly_earnings_growth_yoy"] = round(qeg * 100, 1)
                else:
                    out["quarterly_earnings_growth_yoy"] = qeg
                qrg = _safe_float(hl, "QuarterlyRevenueGrowthYOY")
                if qrg is not None and abs(qrg) <= 2:
                    out["quarterly_revenue_growth_yoy"] = round(qrg * 100, 1)
                else:
                    out["quarterly_revenue_growth_yoy"] = qrg

                # Analyst ratings (TargetPrice, StrongBuy, Buy, Hold, Sell, StrongSell)
                out["analyst_target_price"] = _safe_float(ar, "TargetPrice")
                out["analyst_strong_buy"] = _safe_int(ar, "StrongBuy")
                out["analyst_buy"] = _safe_int(ar, "Buy")
                out["analyst_hold"] = _safe_int(ar, "Hold")
                out["analyst_sell"] = _safe_int(ar, "Sell")
                out["analyst_strong_sell"] = _safe_int(ar, "StrongSell")

                # Earnings.Trend: earningsEstimateGrowth for 0y (current FY) and +1y (next FY).
                # Trend is keyed by fiscal year-end date; multiple 0y/+1y exist (one per year).
                # Pick the forward-looking ones: smallest date >= today for each period.
                earnings = data_fund.get("Earnings") or {}
                trend = earnings.get("Trend") or {}
                if isinstance(trend, dict):
                    today_str = end_date.isoformat()
                    candidates_0y: list[tuple[str, float]] = []
                    candidates_1y: list[tuple[str, float]] = []
                    for date_str, entry in trend.items():
                        if not isinstance(entry, dict):
                            continue
                        period = entry.get("period")
                        growth = entry.get("earningsEstimateGrowth")
                        if growth is None or period is None:
                            continue
                        try:
                            g = float(growth)
                            if period == "0y" and (date_str or "") >= today_str:
                                candidates_0y.append((date_str, g))
                            elif period == "+1y" and (date_str or "") >= today_str:
                                candidates_1y.append((date_str, g))
                        except (TypeError, ValueError):
                            continue
                    # Use earliest future date (current/next FY)
                    eps_growth_0y = round(min(candidates_0y)[1] * 100, 1) if candidates_0y else None
                    eps_growth_1y = round(min(candidates_1y)[1] * 100, 1) if candidates_1y else None
                    out["eps_growth_0y_pct"] = eps_growth_0y
                    out["eps_growth_1y_pct"] = eps_growth_1y

                # Highlights.DilutedEpsTTM for trailing 12M EPS (USD)
                out["trailing_12m_eps"] = _safe_float(hl, "DilutedEpsTTM")

                # Valuation extras for analyst-style evaluation
                out["price_sales_ttm"] = _safe_float(val, "PriceSalesTTM")
                out["price_book_mrq"] = _safe_float(val, "PriceBookMRQ")
                out["enterprise_value_ebitda"] = _safe_float(val, "EnterpriseValueEbitda")
                out["week_52_high"] = _safe_float(tech, "52WeekHigh")
                out["week_52_low"] = _safe_float(tech, "52WeekLow")
                out["return_on_equity_ttm"] = _safe_float(hl, "ReturnOnEquityTTM")
                if out["return_on_equity_ttm"] is not None and abs(out["return_on_equity_ttm"]) <= 2:
                    out["return_on_equity_ttm"] = round(out["return_on_equity_ttm"] * 100, 1)
                out["operating_margin_ttm"] = _safe_float(hl, "OperatingMarginTTM")
                if out["operating_margin_ttm"] is not None and abs(out["operating_margin_ttm"]) <= 2:
                    out["operating_margin_ttm"] = round(out["operating_margin_ttm"] * 100, 1)
                out["profit_margin"] = _safe_float(hl, "ProfitMargin")
                if out["profit_margin"] is not None and abs(out["profit_margin"]) <= 2:
                    out["profit_margin"] = round(out["profit_margin"] * 100, 1)
    except httpx.HTTPStatusError as e:
        out["message"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
    return out


def get_earnings_estimates(symbol: str) -> dict[str, Any]:
    """
    Fetch next fiscal year EPS estimate from EODHD fundamentals (Highlights.EPSEstimateNextYear).
    EODHD does not provide revision counts; eps_revision_up_30d/eps_revision_down_30d remain None.
    """
    global _last_request_time
    symbol = (symbol or "").strip().upper()
    out: dict[str, Any] = {
        "next_fy_eps_estimate": None,
        "eps_revision_up_30d": None,
        "eps_revision_down_30d": None,
        "message": None,
    }
    if not symbol:
        out["message"] = "Symbol required."
        return out

    api_key = (getattr(settings, "eodhd_api_key", "") or "").strip()
    if not api_key:
        out["message"] = "EODHD API key not set."
        return out

    now = time.monotonic()
    with _lock:
        if symbol in _ESTIMATES_CACHE:
            cached_at, cached = _ESTIMATES_CACHE[symbol]
            if now - cached_at < _cache_ttl_seconds():
                return cached
            del _ESTIMATES_CACHE[symbol]
        elapsed = now - _last_request_time
        if elapsed < _min_seconds_between_requests():
            time.sleep(_min_seconds_between_requests() - elapsed)
        _last_request_time = time.monotonic()

    try:
        import httpx
    except ImportError:
        out["message"] = "httpx not installed"
        return out

    eodhd_symbol = _to_eodhd_symbol(symbol)
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                f"{BASE_URL}/fundamentals/{eodhd_symbol}",
                params={"api_token": api_key, "fmt": "json"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
        return out

    if isinstance(data, dict):
        hl = data.get("Highlights") or {}
        eps_next = hl.get("EPSEstimateNextYear")
        if eps_next not in (None, "", "-"):
            try:
                out["next_fy_eps_estimate"] = round(float(eps_next), 4)
            except (TypeError, ValueError):
                pass

    with _lock:
        _last_request_time = time.monotonic()
        if not _is_rate_limit_error(out.get("message") or ""):
            _ESTIMATES_CACHE[symbol] = (_last_request_time, out)
    return out


def get_earnings(symbol: str) -> dict[str, Any]:
    """
    Fetch reported earnings from EODHD fundamentals (Earnings.History).
    Returns trailing_12m_eps (sum of last 4 quarters) and quarterly_earnings list.
    """
    global _last_request_time
    symbol = (symbol or "").strip().upper()
    out: dict[str, Any] = {
        "trailing_12m_eps": None,
        "quarterly_earnings": [],
        "message": None,
    }
    if not symbol:
        out["message"] = "Symbol required."
        return out

    api_key = (getattr(settings, "eodhd_api_key", "") or "").strip()
    if not api_key:
        out["message"] = "EODHD API key not set."
        return out

    now = time.monotonic()
    with _lock:
        if symbol in _EARNINGS_CACHE:
            cached_at, cached = _EARNINGS_CACHE[symbol]
            if now - cached_at < _cache_ttl_seconds():
                return cached
            del _EARNINGS_CACHE[symbol]
        elapsed = now - _last_request_time
        if elapsed < _min_seconds_between_requests():
            time.sleep(_min_seconds_between_requests() - elapsed)
        _last_request_time = time.monotonic()

    try:
        import httpx
    except ImportError:
        out["message"] = "httpx not installed"
        return out

    eodhd_symbol = _to_eodhd_symbol(symbol)
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                f"{BASE_URL}/fundamentals/{eodhd_symbol}",
                params={"api_token": api_key, "fmt": "json"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
        return out

    if not isinstance(data, dict):
        with _lock:
            _last_request_time = time.monotonic()
            if not _is_rate_limit_error(out.get("message") or ""):
                _EARNINGS_CACHE[symbol] = (_last_request_time, out)
        return out

    earnings = data.get("Earnings") or {}
    history = earnings.get("History") or {}
    if not isinstance(history, dict):
        with _lock:
            _last_request_time = time.monotonic()
            if not _is_rate_limit_error(out.get("message") or ""):
                _EARNINGS_CACHE[symbol] = (_last_request_time, out)
        return out

    quarters = []
    for fiscal_date, q in history.items():
        if not isinstance(q, dict):
            continue
        eps = q.get("epsActual")
        if eps in (None, "", "-"):
            continue
        try:
            report_date = (q.get("reportDate") or fiscal_date or "")[:10]
            eps_val = float(eps)
            quarters.append({
                "reportedDate": report_date,
                "reportedEPS": eps_val,
                "fiscalDateEnding": (str(fiscal_date))[:10],
            })
        except (TypeError, ValueError):
            continue

    quarters.sort(key=lambda x: x["reportedDate"], reverse=True)
    out["quarterly_earnings"] = quarters
    if len(quarters) >= 4:
        out["trailing_12m_eps"] = round(sum(q["reportedEPS"] for q in quarters[:4]), 4)

    with _lock:
        _last_request_time = time.monotonic()
        if not _is_rate_limit_error(out.get("message") or ""):
            _EARNINGS_CACHE[symbol] = (_last_request_time, out)
    return out


def get_eps_growth(symbol: str) -> dict[str, Any]:
    """
    EPS growth % = (next fiscal year EPS estimate - trailing 12M EPS) / trailing 12M EPS * 100.
    """
    est = get_earnings_estimates(symbol)
    earn = get_earnings(symbol)
    out: dict[str, Any] = {
        "trailing_12m_eps": earn.get("trailing_12m_eps"),
        "eps_growth_pct": None,
        "message": None,
    }
    if earn.get("message"):
        out["message"] = earn["message"]
    elif est.get("message"):
        out["message"] = est["message"]

    next_fy = est.get("next_fy_eps_estimate")
    trail = earn.get("trailing_12m_eps")
    if trail is not None and trail > 0 and next_fy is not None:
        out["eps_growth_pct"] = round((next_fy - trail) / trail * 100, 1)
    return out


PE_PERCENTILE_LOOKBACK_MONTHS = 60


def get_historical_pe(symbol: str, months: int = 24) -> dict[str, Any]:
    """
    Build historical trailing P/E from EODHD prices and Earnings.History.
    Returns series (date, pe, close, trailing_12m_eps), current_pe, pe_percentile.
    """
    global _last_request_time
    symbol = (symbol or "").strip().upper()
    out: dict[str, Any] = {
        "symbol": symbol,
        "series": [],
        "current_pe": None,
        "pe_percentile": None,
        "message": None,
    }
    if not symbol:
        out["message"] = "Symbol required."
        return out

    api_key = (getattr(settings, "eodhd_api_key", "") or "").strip()
    if not api_key:
        out["message"] = "EODHD API key not set."
        return out

    prices_data = get_prices_and_valuation(symbol, months=PE_PERCENTILE_LOOKBACK_MONTHS)
    all_prices = prices_data.get("prices") or []
    earn = get_earnings(symbol)
    quarters = earn.get("quarterly_earnings") or []
    if not all_prices or not quarters:
        out["message"] = prices_data.get("message") or earn.get("message") or "No price or earnings data."
        return out

    q_sorted_by_date = sorted(quarters, key=lambda x: x["reportedDate"])
    full_series: list[dict[str, Any]] = []
    for p in all_prices:
        d = (p.get("date") or "")[:10]
        close = p.get("close")
        if not d or close is None or close <= 0:
            continue
        eligible = [q for q in q_sorted_by_date if q["reportedDate"] <= d]
        if len(eligible) < 4:
            continue
        trailing_4q = eligible[-4:]
        t12 = sum(x["reportedEPS"] for x in trailing_4q)
        if t12 <= 0:
            continue
        pe = round(close / t12, 2)
        full_series.append({"date": d, "close": close, "trailing_12m_eps": round(t12, 4), "pe": pe})
    if not full_series:
        out["message"] = "Could not build PE series (insufficient quarters vs price dates)."
        return out

    num_bars = months * TRADING_DAYS_PER_MONTH
    out["series"] = full_series[-num_bars:] if num_bars < len(full_series) else full_series
    current = full_series[-1]
    out["current_pe"] = current["pe"]
    pes_5y = [x["pe"] for x in full_series]
    n_below = sum(1 for pe in pes_5y if pe < current["pe"])
    out["pe_percentile"] = round(n_below / len(pes_5y) * 100, 1) if pes_5y else None
    return out


def get_prices_and_valuation(symbol: str, months: int = 6) -> dict[str, Any]:
    """
    Fetch OHLCV history and valuation for a ticker using EODHD.
    Cached; requests throttled.
    """
    global _last_request_time
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {
            "symbol": "",
            "prices": [],
            "trailing_pe": None,
            "forward_pe": None,
            "peg_ratio": None,
            "ev_to_ebitda": None,
            "message": "Symbol required.",
        }

    key = (symbol, months)
    now = time.monotonic()
    with _lock:
        if key in _CACHE:
            cached_at, result = _CACHE[key]
            # If the cached result has a non-null forward_pe, return it as usual.
            # If forward_pe is missing/null (e.g. older cache before ETF fallback was added),
            # treat the entry as stale so we refetch once and populate forward_pe.
            if isinstance(result, dict) and result.get("forward_pe") is not None:
                if now - cached_at < _cache_ttl_seconds():
                    return result
            # Stale or expired: drop from cache and proceed to live fetch.
            del _CACHE[key]

        elapsed = now - _last_request_time
        if elapsed < _min_seconds_between_requests():
            time.sleep(_min_seconds_between_requests() - elapsed)
        _last_request_time = time.monotonic()

    out = _fetch_one(symbol, months)

    with _lock:
        _last_request_time = time.monotonic()
        if not _is_rate_limit_error(out.get("message") or ""):
            _CACHE[key] = (_last_request_time, out)
        elif key in _CACHE:
            cached_at, cached = _CACHE[key]
            return cached

    if _is_rate_limit_error(out.get("message") or ""):
        time.sleep(15)
        with _lock:
            if key in _CACHE:
                cached_at, result = _CACHE[key]
                return result
        out2 = _fetch_one(symbol, months)
        with _lock:
            _last_request_time = time.monotonic()
            if not _is_rate_limit_error(out2.get("message") or ""):
                _CACHE[key] = (_last_request_time, out2)
                return out2
        return out2

    return out
