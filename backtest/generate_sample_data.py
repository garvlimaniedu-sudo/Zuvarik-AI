"""
Synthetic 1-minute OHLCV generator — for offline local testing ONLY.
This exists because this dev sandbox has no internet access. It produces
a deterministic random-walk price series shaped like real crypto data
(same fields as fetch_binance.fetch_klines) so the full backfill/evaluate
pipeline can be built and verified end-to-end before it ever touches
production. Never use this data to report a real accuracy number —
only fetch_binance.py output counts for that.
"""

import random


def generate_klines(symbol="BTCUSDT", n=2000, start_price=60000, seed=42):
    rnd = random.Random(f"{seed}-{symbol}")
    klines = []
    price = start_price
    t = 1_700_000_000_000  # arbitrary ms epoch start
    for i in range(n):
        drift = rnd.gauss(0, 1) * (price * 0.0015)
        # occasional momentum bursts so RSI/EMA crossovers actually happen
        if rnd.random() < 0.03:
            drift += rnd.choice([-1, 1]) * price * 0.01
        open_p = price
        close_p = max(1, price + drift)
        high = max(open_p, close_p) * (1 + rnd.random() * 0.001)
        low = min(open_p, close_p) * (1 - rnd.random() * 0.001)
        volume = abs(rnd.gauss(50, 30)) + 5
        klines.append({
            "open_time": t,
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_p, 2),
            "volume": round(volume, 4),
        })
        price = close_p
        t += 60_000
    return klines
