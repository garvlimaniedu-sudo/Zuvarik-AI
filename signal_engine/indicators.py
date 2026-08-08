"""
Core technical indicators.
Ported from the original TradeAssist AI (script.js) — same math, same behavior,
now as a testable, versioned Python module instead of inline JS.
"""

def mean(values):
    if not values:
        return 0
    return sum(values) / len(values)


def stddev(values):
    if not values:
        return 0
    m = mean(values)
    return (mean([(v - m) ** 2 for v in values])) ** 0.5


def ema(values, period):
    if not values:
        return 0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50
    gains = 0.0
    losses = 0.0
    for i in range(len(values) - period, len(values)):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    rs = gains / (losses or 1)
    return 100 - (100 / (1 + rs))


def round_(n, d=2):
    p = 10 ** d
    return round(n * p) / p
