"""
Market data for instruments (stocks/ETFs) via Alpha Vantage.
Returns price history and valuation (trailing PE, forward PE, PEG, earnings growth) for the frontend chart.
Uses in-memory cache (configurable TTL, default 2h) and light throttling (configurable; default 1s between requests for 75/min limit).

Notes:
- Forward PE and PEG: Alpha Vantage OVERVIEW does provide ForwardPE and PEGRatio (see demo response).
  They often appear as "-" or empty for non-US symbols, small caps, or when analyst estimates are missing.
  We only parse overview when the response contains "Symbol" (so rate-limit/error responses are skipped).
- PE percentile vs 5-year history: built from EARNINGS + daily prices; percentile is computed relative to
  the past 5 years (not just the chart range). Chart series is still trimmed to the requested range.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

from app.settings import settings

_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_ESTIMATES_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_EARNINGS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_last_request_time: float = 0.0
_lock = threading.Lock()


def _cache_ttl_seconds() -> int:
    return getattr(settings, "alpha_vantage_cache_ttl_seconds", 7200)


def _min_seconds_between_requests() -> float:
    return getattr(settings, "alpha_vantage_min_seconds_between_requests", 1.0)

BASE_URL = "https://www.alphavantage.co/query"

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


def _macd(closes: list[float], fast: int, slow: int, signal: int) -> tuple[list[float | None], list[float | None], list[float | None]]:
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
    return "rate limit" in msg or "too many requests" in msg or "429" in msg or "try after" in msg or "premium" in msg


# Symbol search cache: key = normalized keywords, value = (cached_at, list[dict]); short TTL for typeahead
_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_SEARCH_CACHE_TTL = 300  # 5 minutes


def search_symbols(keywords: str) -> dict[str, Any]:
    """
    Alpha Vantage SYMBOL_SEARCH: search by company name or ticker for typeahead when adding instruments.
    Returns {"matches": [...], "message": None or error string}. Uses same throttle as other AV calls;
    results cached briefly (5 min) to avoid repeated calls while typing.
    """
    global _last_request_time
    keywords = (keywords or "").strip()[:64]
    out: dict[str, Any] = {"matches": [], "message": None}
    if not keywords:
        return out

    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        out["message"] = "Alpha Vantage API key not set. Add ALPHA_VANTAGE_API_KEY to .env"
        return out

    cache_key = keywords.lower()
    now = time.monotonic()
    with _lock:
        if cache_key in _SEARCH_CACHE:
            cached_at, cached = _SEARCH_CACHE[cache_key]
            if now - cached_at < _SEARCH_CACHE_TTL:
                return cached
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
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                BASE_URL,
                params={"function": "SYMBOL_SEARCH", "keywords": keywords, "apikey": api_key},
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

    if not isinstance(data, dict):
        return out
    if "Error Message" in data:
        out["message"] = data["Error Message"]
        return out
    if "Note" in data:
        note = data["Note"]
        if _is_rate_limit_error(note):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
        else:
            out["message"] = note
        return out

    best_matches = data.get("bestMatches") or []
    for row in best_matches:
        if not isinstance(row, dict):
            continue
        symbol = (row.get("1. symbol") or "").strip()
        if not symbol:
            continue
        name = (row.get("2. name") or "").strip() or None
        raw_type = (row.get("3. type") or "").strip().lower()
        if "etf" in raw_type:
            type_ = "etf"
        elif raw_type:
            type_ = raw_type[:16]
        else:
            type_ = "stock"
        region = (row.get("4. region") or "").strip() or None
        currency = (row.get("8. currency") or "").strip() or None
        try:
            match_score = float(row.get("9. matchScore", 0) or 0)
        except (TypeError, ValueError):
            match_score = 0.0
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
            _SEARCH_CACHE[cache_key] = (time.monotonic(), out)
    return out


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
    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        out["message"] = "Alpha Vantage API key not set. Add ALPHA_VANTAGE_API_KEY to .env"
        return out

    try:
        import httpx
    except ImportError:
        out["message"] = "httpx not installed"
        return out

    try:
        with httpx.Client(timeout=30.0) as client:
            # 1) Daily time series: compact = last 100 days; full = 20+ years (use full when we need >100 days)
            num_bars = months * TRADING_DAYS_PER_MONTH
            daily_params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": api_key,
                "outputsize": "full" if num_bars > 100 else "compact",
            }
            r_daily = client.get(BASE_URL, params=daily_params)
            r_daily.raise_for_status()
            data_daily = r_daily.json()

            if "Time Series (Daily)" in data_daily:
                series = data_daily["Time Series (Daily)"]
                for date_str, day in sorted(series.items(), reverse=True)[:num_bars]:
                    try:
                        open_ = float(day.get("1. open", 0))
                        high = float(day.get("2. high", 0))
                        low = float(day.get("3. low", 0))
                        close = float(day.get("4. close", 0))
                        vol = int(float(day.get("5. volume", 0)))
                    except (TypeError, ValueError):
                        continue
                    out["prices"].append({
                        "date": date_str[:10],
                        "open": round(open_, 4),
                        "high": round(high, 4),
                        "low": round(low, 4),
                        "close": round(close, 4),
                        "volume": vol,
                    })
                out["prices"].sort(key=lambda x: x["date"])
                _add_indicators(out["prices"])
            elif "Error Message" in data_daily:
                out["message"] = data_daily["Error Message"]
                return out
            elif "Note" in data_daily:
                out["message"] = data_daily["Note"]
                if _is_rate_limit_error(out["message"]):
                    out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
                return out

            # 2) Overview for PE ratios
            overview_params = {
                "function": "OVERVIEW",
                "symbol": symbol,
                "apikey": api_key,
            }
            r_overview = client.get(BASE_URL, params=overview_params)
            r_overview.raise_for_status()
            data_overview = r_overview.json()

            if isinstance(data_overview, dict) and "Symbol" in data_overview:
                # Skip if response is rate-limit note or error (no Symbol)
                def _safe_float(*keys: str):
                    for k in keys:
                        v = data_overview.get(k)
                        if v in (None, "", "None", "-"):
                            continue
                        try:
                            return round(float(v), 2)
                        except (TypeError, ValueError):
                            continue
                    return None
                out["trailing_pe"] = _safe_float("PERatio", "PE Ratio", "TrailingPE")
                out["forward_pe"] = _safe_float("ForwardPE", "Forward PE", "Forward P/E")
                out["peg_ratio"] = _safe_float("PEGRatio", "PEG Ratio", "PEG")
                out["ev_to_ebitda"] = _safe_float("EVToEBITDA", "EV/EBITDA")
                # Earnings/revenue growth: API returns decimal (e.g. 0.9 = 90%). Store as percentage.
                qeg = _safe_float("QuarterlyEarningsGrowthYOY")
                if qeg is not None and abs(qeg) <= 2:
                    out["quarterly_earnings_growth_yoy"] = round(qeg * 100, 1)
                else:
                    out["quarterly_earnings_growth_yoy"] = qeg
                qrg = _safe_float("QuarterlyRevenueGrowthYOY")
                if qrg is not None and abs(qrg) <= 2:
                    out["quarterly_revenue_growth_yoy"] = round(qrg * 100, 1)
                else:
                    out["quarterly_revenue_growth_yoy"] = qrg
            if "Error Message" in (data_overview or {}):
                msg = (data_overview or {}).get("Error Message", "")
                if not out["message"]:
                    out["message"] = msg
            if "Note" in (data_overview or {}):
                note = (data_overview or {}).get("Note", "")
                if _is_rate_limit_error(note) and not out["message"]:
                    out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
    except httpx.HTTPStatusError as e:
        out["message"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
    return out


def get_earnings_estimates(symbol: str) -> dict[str, Any]:
    """
    Fetch EARNINGS_ESTIMATES for a symbol. Returns next fiscal year eps_estimate_average
    and 30-day revision counts (up/down). Cached (see alpha_vantage_cache_ttl_seconds); uses same throttle as other AV calls.
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

    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        out["message"] = "Alpha Vantage API key not set."
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

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                BASE_URL,
                params={"function": "EARNINGS_ESTIMATES", "symbol": symbol, "apikey": api_key},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
        return out

    if isinstance(data, dict) and "estimates" in data:
        estimates = data.get("estimates") or []
        for est in estimates:
            if not isinstance(est, dict):
                continue
            horizon = (est.get("horizon") or "").strip().lower()
            if horizon == "next fiscal year":
                try:
                    avg = est.get("eps_estimate_average")
                    if avg not in (None, "", "-"):
                        out["next_fy_eps_estimate"] = round(float(avg), 4)
                except (TypeError, ValueError):
                    pass
                for key, out_key in (
                    ("eps_estimate_revision_up_trailing_30_days", "eps_revision_up_30d"),
                    ("eps_estimate_revision_down_trailing_30_days", "eps_revision_down_30d"),
                ):
                    val = est.get(key)
                    if val is not None and val != "" and val != "-":
                        try:
                            out[out_key] = int(float(val))
                        except (TypeError, ValueError):
                            pass
                break
    elif isinstance(data, dict) and "Note" in data:
        out["message"] = data.get("Note", "")

    with _lock:
        _last_request_time = time.monotonic()
        if not _is_rate_limit_error(out.get("message") or ""):
            _ESTIMATES_CACHE[symbol] = (_last_request_time, out)
    return out


def get_earnings(symbol: str) -> dict[str, Any]:
    """
    Fetch EARNINGS (reported history) for a symbol. Returns trailing_12m_eps (sum of last 4 quarters)
    and quarterly_earnings list [{reportedDate, reportedEPS, fiscalDateEnding}] for historical PE.
    Cached (see alpha_vantage_cache_ttl_seconds); uses same throttle.
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
    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        out["message"] = "Alpha Vantage API key not set."
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

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(BASE_URL, params={"function": "EARNINGS", "symbol": symbol, "apikey": api_key})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        out["message"] = str(e)
        if _is_rate_limit_error(out["message"]):
            out["message"] = "Too many requests from the data provider. Please wait a few minutes and try again."
        return out

    if not isinstance(data, dict) or "quarterlyEarnings" not in data:
        if isinstance(data, dict) and "Note" in data:
            out["message"] = data.get("Note", "")
        with _lock:
            _last_request_time = time.monotonic()
            if not _is_rate_limit_error(out.get("message") or ""):
                _EARNINGS_CACHE[symbol] = (_last_request_time, out)
        return out

    quarters = []
    for q in data.get("quarterlyEarnings") or []:
        if not isinstance(q, dict):
            continue
        try:
            rd = (q.get("reportedDate") or "")[:10]
            eps = q.get("reportedEPS")
            fd = (q.get("fiscalDateEnding") or "")[:10]
            if rd and eps not in (None, "", "-"):
                quarters.append({"reportedDate": rd, "reportedEPS": float(eps), "fiscalDateEnding": fd})
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
    Next FY from EARNINGS_ESTIMATES (eps_estimate_average, horizon "next fiscal year").
    Trailing 12M = sum of last 4 reported quarters from EARNINGS.
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


# Lookback for PE percentile: always use 5 years so percentile is relative to 5-year history, not chart range
PE_PERCENTILE_LOOKBACK_MONTHS = 60


def get_historical_pe(symbol: str, months: int = 24) -> dict[str, Any]:
    """
    Build historical trailing P/E: for each trading day, trailing_12m_eps = sum of
    last 4 reported quarters as of that date; PE = close / trailing_12m_eps.
    Returns series (date, pe, close, trailing_12m_eps), current_pe, pe_percentile.
    PE percentile is computed relative to the past 5 years, not just the chart range.
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

    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        out["message"] = "Alpha Vantage API key not set."
        return out

    # Fetch 5 years of prices for PE percentile baseline (so percentile is vs 5-year history)
    prices_data = get_prices_and_valuation(symbol, months=PE_PERCENTILE_LOOKBACK_MONTHS)
    all_prices = prices_data.get("prices") or []
    earn = get_earnings(symbol)
    quarters = earn.get("quarterly_earnings") or []
    if not all_prices or not quarters:
        out["message"] = prices_data.get("message") or earn.get("message") or "No price or earnings data."
        return out

    # For each trading day d: trailing_12m_eps(d) = sum of reportedEPS for 4 most recent quarters with reportedDate <= d
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

    # Chart series: last ~months of calendar time (by trading days)
    num_bars = months * TRADING_DAYS_PER_MONTH
    out["series"] = full_series[-num_bars:] if num_bars < len(full_series) else full_series
    current = full_series[-1]
    out["current_pe"] = current["pe"]
    # PE percentile vs past 5 years (full_series), not just chart range
    pes_5y = [x["pe"] for x in full_series]
    n_below = sum(1 for pe in pes_5y if pe < current["pe"])
    out["pe_percentile"] = round(n_below / len(pes_5y) * 100, 1) if pes_5y else None
    return out


def get_prices_and_valuation(symbol: str, months: int = 6) -> dict[str, Any]:
    """
    Fetch OHLCV history and valuation for a ticker using Alpha Vantage.
    Cached (see alpha_vantage_cache_ttl_seconds); requests throttled (alpha_vantage_min_seconds_between_requests).
    """
    global _last_request_time
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"symbol": "", "prices": [], "trailing_pe": None, "forward_pe": None, "peg_ratio": None, "ev_to_ebitda": None, "message": "Symbol required."}

    key = (symbol, months)
    now = time.monotonic()
    with _lock:
        if key in _CACHE:
            cached_at, result = _CACHE[key]
            if now - cached_at < _cache_ttl_seconds():
                return result
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
