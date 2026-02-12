"""
Market data for instruments (stocks/ETFs) via Alpha Vantage.
Returns price history and valuation (trailing PE, forward PE) for the frontend chart.
Uses in-memory cache (15 min) and request throttling (free tier: 5 requests/min).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.settings import settings

_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 900  # 15 minutes
# Free tier: 5 requests/min → space requests at least 12 seconds apart (2 calls per symbol: daily + overview)
_MIN_SECONDS_BETWEEN_REQUESTS = 12.0
_last_request_time: float = 0.0
_lock = threading.Lock()

BASE_URL = "https://www.alphavantage.co/query"

# Technical indicator periods
SMA_PERIOD = 20
RSI_PERIOD = 14
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


def _fetch_one(symbol: str, months: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "symbol": symbol,
        "prices": [],
        "trailing_pe": None,
        "forward_pe": None,
        "peg_ratio": None,
        "ev_to_ebitda": None,
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
            # 1) Daily time series (compact = last 100 days; 6 months ≈ 126, we get 100)
            daily_params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": api_key,
                "outputsize": "compact",
            }
            r_daily = client.get(BASE_URL, params=daily_params)
            r_daily.raise_for_status()
            data_daily = r_daily.json()

            if "Time Series (Daily)" in data_daily:
                series = data_daily["Time Series (Daily)"]
                for date_str, day in sorted(series.items(), reverse=True)[: months * 31]:
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

            if isinstance(data_overview, dict):
                def _safe_float(val, key_alt=None):
                    v = data_overview.get(val) if isinstance(val, str) else val
                    if key_alt:
                        v = v or data_overview.get(key_alt)
                    if v in (None, "", "None", "-"):
                        return None
                    try:
                        return round(float(v), 2)
                    except (TypeError, ValueError):
                        return None
                out["trailing_pe"] = _safe_float("PERatio", "PE Ratio")
                out["forward_pe"] = _safe_float("ForwardPE", "Forward PE")
                out["peg_ratio"] = _safe_float("PEGRatio", "PEG Ratio")
                out["ev_to_ebitda"] = _safe_float("EVToEBITDA", "EV/EBITDA")
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


def get_prices_and_valuation(symbol: str, months: int = 6) -> dict[str, Any]:
    """
    Fetch OHLCV history and valuation for a ticker using Alpha Vantage.
    Cached 15 minutes; requests throttled to stay under 5/min (free tier).
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
            if now - cached_at < _CACHE_TTL_SECONDS:
                return result
            del _CACHE[key]

        elapsed = now - _last_request_time
        if elapsed < _MIN_SECONDS_BETWEEN_REQUESTS:
            time.sleep(_MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
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
