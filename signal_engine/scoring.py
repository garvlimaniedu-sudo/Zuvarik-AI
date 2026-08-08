"""
Signal scoring model — v1.
Ported directly from TradeAssist AI's computeSignal() (script.js), same weights
and thresholds. This is the baseline every future version gets backtested against.

Versioning rule: never edit v1 in place once it has backtest history attached.
Copy to v2, change it there, and compare.
"""

from .indicators import ema, rsi, mean, stddev, round_

ENGINE_VERSION = "v1"


def compute_signal(prices, volumes, day_change_pct=0.0, news_bias=0.0):
    if len(prices) < 8:
        return {
            "verdict": "WAIT",
            "confidence": 42,
            "reasons": ["Collecting enough live candles."],
            "rsi": None, "ema_fast": None, "ema_slow": None,
            "momentum": None, "vol_ratio": None, "day_change": None,
            "engine_version": ENGINE_VERSION,
        }

    r = rsi(prices, min(14, max(7, len(prices) - 1)))
    fast = ema(prices[-20:], 9)
    slow = ema(prices[-30:], 21)
    now = prices[-1]
    ago = prices[max(0, len(prices) - 8)]
    momentum = ((now - ago) / ago) * 100 if ago else 0

    returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
    vol = stddev(returns) * 100

    latest_vol = volumes[-1] if volumes else 0
    avg_vol = mean(volumes[-20:]) or 1
    vol_ratio = latest_vol / avg_vol

    score = 0.0
    reasons = []

    if r < 30:
        score += 1.8; reasons.append("RSI is oversold.")
    elif r > 70:
        score -= 1.8; reasons.append("RSI is overbought.")
    else:
        reasons.append("RSI is neutral.")

    if fast > slow:
        score += 1.6; reasons.append("Short EMA is above long EMA.")
    else:
        score -= 1.6; reasons.append("Short EMA is below long EMA.")

    if momentum > 0.25:
        score += 1.1; reasons.append("Momentum is positive.")
    elif momentum < -0.25:
        score -= 1.1; reasons.append("Momentum is negative.")

    if vol_ratio > 1.25:
        score += 0.9 if momentum >= 0 else -0.6
        reasons.append("Volume is expanding.")
    elif vol_ratio < 0.8:
        score -= 0.5
        reasons.append("Volume is weak.")

    if day_change_pct > 1:
        score += 0.9; reasons.append("24h change is positive.")
    elif day_change_pct < -1:
        score -= 0.9; reasons.append("24h change is negative.")

    if news_bias > 0.6:
        score += 1; reasons.append("News bias is positive.")
    elif news_bias < -0.6:
        score -= 1; reasons.append("News bias is negative.")

    verdict = "BUY" if score > 1.4 else "SELL" if score < -1.4 else "HOLD"
    confidence = max(48, min(97, round(54 + abs(score) * 11 + min(8, vol * 2))))

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
        "rsi": round_(r, 1),
        "ema_fast": round_(fast, 4),
        "ema_slow": round_(slow, 4),
        "momentum": round_(momentum, 2),
        "vol_ratio": round_(vol_ratio, 2),
        "day_change": round_(day_change_pct, 2),
        "engine_version": ENGINE_VERSION,
    }
