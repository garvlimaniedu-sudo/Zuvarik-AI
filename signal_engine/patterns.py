"""
Candlestick pattern detection.

Honest framing: these are widely-known TA patterns with mixed/weak standalone
predictive power in liquid markets (see README caveat in scoring_v2.py).
They're used here as a small confirming/vetoing input, not a primary driver —
weighted much lower than RSI/EMA/momentum.

All functions take the last few raw OHLC candle dicts (from fetch_binance.py's
{open, high, low, close, volume} format) and return booleans.
"""


def body(c):
    return abs(c["close"] - c["open"])


def range_(c):
    return max(c["high"] - c["low"], 1e-9)


def is_bullish(c):
    return c["close"] > c["open"]


def bullish_engulfing(candles):
    if len(candles) < 2:
        return False
    prev, cur = candles[-2], candles[-1]
    return (
        not is_bullish(prev) and is_bullish(cur)
        and cur["open"] <= prev["close"] and cur["close"] >= prev["open"]
    )


def bearish_engulfing(candles):
    if len(candles) < 2:
        return False
    prev, cur = candles[-2], candles[-1]
    return (
        is_bullish(prev) and not is_bullish(cur)
        and cur["open"] >= prev["close"] and cur["close"] <= prev["open"]
    )


def hammer(candles):
    if len(candles) < 1:
        return False
    c = candles[-1]
    b = body(c)
    lower_wick = min(c["open"], c["close"]) - c["low"]
    upper_wick = c["high"] - max(c["open"], c["close"])
    return b > 0 and lower_wick >= 2 * b and upper_wick <= b * 0.5


def shooting_star(candles):
    if len(candles) < 1:
        return False
    c = candles[-1]
    b = body(c)
    upper_wick = c["high"] - max(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    return b > 0 and upper_wick >= 2 * b and lower_wick <= b * 0.5


def doji(candles):
    if len(candles) < 1:
        return False
    c = candles[-1]
    return body(c) <= 0.1 * range_(c)


def pattern_score(candles):
    """Returns (score_adjustment, dampen_factor, detected_names)."""
    score = 0.0
    dampen = 1.0
    detected = []

    if bullish_engulfing(candles):
        score += 0.8; detected.append("bullish_engulfing")
    if bearish_engulfing(candles):
        score -= 0.8; detected.append("bearish_engulfing")
    if hammer(candles):
        score += 0.6; detected.append("hammer")
    if shooting_star(candles):
        score -= 0.6; detected.append("shooting_star")
    if doji(candles):
        dampen = 0.85; detected.append("doji")  # indecision — reduce conviction, don't flip direction

    return score, dampen, detected
