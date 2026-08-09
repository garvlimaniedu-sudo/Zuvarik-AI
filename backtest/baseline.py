"""
Baseline check: before crediting v1 (or any future version) with "skill," see
what trivial strategies score on the same data. If "always BUY" or "just
follow the trailing trend" score close to what the real engine scores, the
engine isn't adding value — it's riding drift/momentum that a one-line rule
already captures for free.

Usage:
    python3 baseline.py --source binance --asset BTCUSDT --days 90
    python3 baseline.py --source sample --asset BTCUSDT --n 3000
"""

import argparse
import sys
from datetime import datetime, timezone

HORIZONS = {"1h": 60, "4h": 240, "24h": 1440}
TREND_LOOKBACK = 60


def evaluate_strategy(klines, predict_fn, name):
    closes = [k["close"] for k in klines]
    results = {h: {"CORRECT": 0, "WRONG": 0} for h in HORIZONS}

    for i in range(TREND_LOOKBACK, len(closes)):
        verdict = predict_fn(closes, i)
        if verdict not in ("BUY", "SELL"):
            continue
        for h, minutes in HORIZONS.items():
            j = i + minutes
            if j >= len(closes):
                continue
            moved_up = closes[j] > closes[i]
            correct = moved_up if verdict == "BUY" else not moved_up
            results[h]["CORRECT" if correct else "WRONG"] += 1

    print(f"\n{name}:")
    for h in HORIZONS:
        c, w = results[h]["CORRECT"], results[h]["WRONG"]
        total = c + w
        acc = (c / total * 100) if total else 0
        print(f"  {h:>4}: {acc:5.1f}%  ({c} correct / {w} wrong, n={total})")


def always_buy(closes, i):
    return "BUY"


def trend_follow(closes, i):
    move = closes[i] - closes[i - TREND_LOOKBACK]
    return "BUY" if move > 0 else "SELL"


def mean_revert(closes, i):
    # opposite of trend_follow: bet the recent move reverses
    move = closes[i] - closes[i - TREND_LOOKBACK]
    return "SELL" if move > 0 else "BUY"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--asset", default="BTCUSDT")
    parser.add_argument("--n", type=int, default=3000)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    if args.source == "sample":
        import generate_sample_data
        klines = generate_sample_data.generate_klines(symbol=args.asset, n=args.n)
    else:
        import fetch_binance
        klines = fetch_binance.fetch_klines_range(args.asset, interval="1m", days=args.days)

    print(f"=== Baseline check — {args.asset}, {len(klines)} candles ===")
    print("(compare these against v1's reported 48-51% — if a baseline matches or beats it, v1 adds nothing)")

    evaluate_strategy(klines, always_buy, "Always BUY (pure drift bet)")
    evaluate_strategy(klines, trend_follow, "Trend-follow (bet the last 1h continues)")
    evaluate_strategy(klines, mean_revert, "Mean-revert (bet the last 1h reverses)")
