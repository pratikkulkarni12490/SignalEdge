"""Technical indicator math — pure Python, no numpy/pandas dependency.

All functions take/return plain lists so they're trivial to unit test and
don't tie the project to a heavy dependency for what is, underneath, simple
arithmetic on a list of closes.
"""

from config import SMA_SHORT, SMA_LONG, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT


def sma(values, window):
    """Simple moving average of the last `window` values. None if not enough data."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def rsi(closes, period=RSI_PERIOD):
    """Wilder's RSI over the given period. None if not enough data.

    Uses Wilder's smoothing (the standard RSI definition), not a plain SMA of
    gains/losses — a plain-SMA RSI drifts from what every charting platform
    reports.
    """
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def range_position_pct(close, low_52w, high_52w):
    """Where `close` sits between the 52-week low (0) and high (100). None if range is degenerate."""
    if high_52w is None or low_52w is None or high_52w <= low_52w:
        return None
    return round((close - low_52w) / (high_52w - low_52w) * 100, 1)


def classify_trend(close, sma50, sma200):
    """Coarse trend label from price vs. its two moving averages.

    Not a golden/death *cross* detector by itself (that needs yesterday's
    sma50 vs sma200 too, computed by the caller from consecutive rows) — this
    just states where price sits relative to both averages today.
    """
    if sma50 is None or sma200 is None:
        return "INSUFFICIENT_HISTORY"
    if close > sma50 > sma200:
        return "ABOVE_BOTH_ALIGNED"      # uptrend: price > 50DMA > 200DMA
    if close > sma50 and close > sma200:
        return "ABOVE_BOTH"
    if close < sma50 < sma200:
        return "BELOW_BOTH_ALIGNED"      # downtrend: price < 50DMA < 200DMA
    if close < sma50 and close < sma200:
        return "BELOW_BOTH"
    return "MIXED"


def classify_rsi(value):
    if value is None:
        return None
    if value <= RSI_OVERSOLD:
        return "OVERSOLD"
    if value >= RSI_OVERBOUGHT:
        return "OVERBOUGHT"
    return "NEUTRAL"


def detect_cross(prev_sma50, prev_sma200, curr_sma50, curr_sma200):
    """Golden/death cross detection from two consecutive days of SMA50/SMA200.

    Returns 'GOLDEN_CROSS', 'DEATH_CROSS', or None. Needs the *previous* row's
    SMAs — a cross is a change in ordering between two days, not a snapshot.
    """
    if None in (prev_sma50, prev_sma200, curr_sma50, curr_sma200):
        return None
    was_below = prev_sma50 <= prev_sma200
    is_above = curr_sma50 > curr_sma200
    if was_below and is_above:
        return "GOLDEN_CROSS"
    was_above = prev_sma50 >= prev_sma200
    is_below = curr_sma50 < curr_sma200
    if was_above and is_below:
        return "DEATH_CROSS"
    return None


def compute_for_series(dates, closes):
    """Compute the full technical-signal row for the *latest* point in a
    chronologically-sorted (date, close) series. Returns a dict or None if
    the series is empty.
    """
    if not closes:
        return None

    close = closes[-1]
    s50 = sma(closes, SMA_SHORT)
    s200 = sma(closes, SMA_LONG)
    r = rsi(closes, RSI_PERIOD)

    window = closes[-252:] if len(closes) >= 252 else closes  # ~52 trading weeks
    low_52w, high_52w = min(window), max(window)

    trend = classify_trend(close, s50, s200)

    cross = None
    if len(closes) >= SMA_LONG + 1:
        prev_s50 = sma(closes[:-1], SMA_SHORT)
        prev_s200 = sma(closes[:-1], SMA_LONG)
        cross = detect_cross(prev_s50, prev_s200, s50, s200)

    return {
        "as_of_date": dates[-1],
        "close": close,
        "sma50": s50,
        "sma200": s200,
        "rsi14": r,
        "week52_high": high_52w,
        "week52_low": low_52w,
        "range_position_pct": range_position_pct(close, low_52w, high_52w),
        "trend": cross or trend,
        "rsi_state": classify_rsi(r),
    }
