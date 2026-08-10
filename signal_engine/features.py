"""
Feature engineering for v3.

v1/v2's RSI + EMA-crossover + momentum are all reacting to essentially the
same underlying price action, so they're not as independent as having three
inputs suggests. This module adds features that capture genuinely different
information: trend acceleration (MACD-style), price position within its own
volatility band (Bollinger %B), normalized volatility (ATR), and time-of-day
(crypto does have session effects, even if weaker than in traditional markets).

FEATURE_KEYS defines the fixed vector order every function in this module
and logistic.py agree on — never reorder it once a model has been trained
against it.
"""

import math
from .indicators import ema, rsi, mean, stddev
from .patterns import bullish_engulfing, bearish_engulfing, hammer, shooting_star, doji

FEATURE_KEYS = [
    "rsi", "ema_diff_pct", "momentum", "vol_ratio", "day_change",
    "macd_proxy", "bollinger_pctb", "atr_pct", "hour_sin", "hour_cos",
    "bullish_engulfing", "bearish_engulfing", "hammer", "shooting_star", "doji",
]


def build_features(candles, day_change_pct=0.0):
    """candles: trailing window of OHLCV dicts, most recent last (>= ~40 for
    all features to be meaningful; fewer will zero-fill the longer-lookback ones)."""
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    r = rsi(closes, min(14, max(7, len(closes) - 1))) if len(closes) > 8 else 50

    fast = ema(closes[-20:], 9) if len(closes) >= 9 else closes[-1]
    slow = ema(closes[-30:], 21) if len(closes) >= 21 else closes[-1]
    ema_diff_pct = ((fast - slow) / slow) * 100 if slow else 0

    now = closes[-1]
    ago = closes[max(0, len(closes) - 8)]
    momentum = ((now - ago) / ago) * 100 if ago else 0

    latest_vol = volumes[-1] if volumes else 0
    avg_vol = mean(volumes[-20:]) or 1
    vol_ratio = latest_vol / avg_vol

    # MACD proxy: 12-EMA minus 26-EMA (trend acceleration), as a % of price.
    # Simplification: no signal-line crossover, just the raw MACD line.
    ema12 = ema(closes[-26:], 12) if len(closes) >= 12 else now
    ema26 = ema(closes[-26:], 26) if len(closes) >= 26 else now
    macd_proxy = ((ema12 - ema26) / now) * 100 if now else 0

    # Bollinger %B: where price sits within its own 20-candle volatility band.
    # 0 = at lower band, 1 = at upper band, 0.5 = at the midline.
    window20 = closes[-20:] if len(closes) >= 20 else closes
    sma20 = mean(window20)
    std20 = stddev(window20)
    upper, lower = sma20 + 2 * std20, sma20 - 2 * std20
    bollinger_pctb = (now - lower) / (upper - lower) if upper != lower else 0.5

    # ATR proxy (no gap handling, simple high-low range average) as % of price.
    window14 = candles[-14:] if len(candles) >= 14 else candles
    atr = mean([c["high"] - c["low"] for c in window14])
    atr_pct = (atr / now) * 100 if now else 0

    # time-of-day, cyclically encoded so hour 23 and hour 0 are "close"
    ts_ms = candles[-1].get("open_time")
    if ts_ms:
        from datetime import datetime, timezone
        hour = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour
    else:
        hour = 0
    hour_sin = math.sin(2 * math.pi * hour / 24)
    hour_cos = math.cos(2 * math.pi * hour / 24)

    recent = candles[-3:]
    feats = {
        "rsi": r,
        "ema_diff_pct": ema_diff_pct,
        "momentum": momentum,
        "vol_ratio": vol_ratio,
        "day_change": day_change_pct,
        "macd_proxy": macd_proxy,
        "bollinger_pctb": bollinger_pctb,
        "atr_pct": atr_pct,
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "bullish_engulfing": 1.0 if bullish_engulfing(recent) else 0.0,
        "bearish_engulfing": 1.0 if bearish_engulfing(recent) else 0.0,
        "hammer": 1.0 if hammer(recent) else 0.0,
        "shooting_star": 1.0 if shooting_star(recent) else 0.0,
        "doji": 1.0 if doji(recent) else 0.0,
    }
    return feats


def vectorize(feats):
    return [feats[k] for k in FEATURE_KEYS]
