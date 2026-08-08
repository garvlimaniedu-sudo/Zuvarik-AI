"""
Evaluate: for every logged BUY/SELL signal, look up the price 1h/4h/24h later
and mark it CORRECT or WRONG. Then prints the one number Phase 1 exists to
produce: accuracy % per horizon, per engine version.

Usage (must match the same source/asset used in backfill.py so timestamps line up):
    python3 evaluate.py --source sample --asset BTCUSDT --n 2000
    python3 evaluate.py --source binance --asset BTCUSDT --limit 1000
"""

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, "..")
import db

HORIZONS = {"1h": 60, "4h": 240, "24h": 1440}  # in minutes -> candle offsets (1m candles)


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def build_price_index(klines):
    """Map ISO timestamp -> close price, plus an ordered list for offset lookups."""
    by_ts = {}
    ordered = []
    for k in klines:
        iso = ms_to_iso(k["open_time"])
        by_ts[iso] = k["close"]
        ordered.append((iso, k["close"]))
    return by_ts, ordered


def find_future_price(ordered, index_by_ts, signal_ts, minutes_ahead):
    if signal_ts not in index_by_ts:
        return None
    idx = index_by_ts[signal_ts]
    target_idx = idx + minutes_ahead
    if target_idx >= len(ordered):
        return None
    return ordered[target_idx][1]


def run(klines, asset):
    ordered = []
    ts_to_idx = {}
    for i, k in enumerate(klines):
        iso = ms_to_iso(k["open_time"])
        ordered.append((iso, k["close"]))
        ts_to_idx[iso] = i

    rows = [r for r in db.all_rows() if r["asset"] == asset]
    results = {h: {"CORRECT": 0, "WRONG": 0, "N-A": 0} for h in HORIZONS}

    for row in rows:
        if row["verdict"] not in ("BUY", "SELL"):
            continue
        for horizon, minutes in HORIZONS.items():
            outcome_col = f"outcome_{horizon}"
            if row[outcome_col] is not None:
                results[horizon][row[outcome_col]] += 1
                continue

            future_price = find_future_price(ordered, ts_to_idx, row["signal_ts"], minutes)
            if future_price is None:
                results[horizon]["N-A"] += 1
                continue

            moved_up = future_price > row["price_at_signal"]
            correct = moved_up if row["verdict"] == "BUY" else not moved_up
            outcome = "CORRECT" if correct else "WRONG"
            db.update_outcome(row["id"], horizon, future_price, outcome)
            results[horizon][outcome] += 1

    print(f"\n=== Zuvarik AI — Backtest Report ({asset}) ===")
    for horizon in HORIZONS:
        c, w, na = results[horizon]["CORRECT"], results[horizon]["WRONG"], results[horizon]["N-A"]
        total = c + w
        acc = (c / total * 100) if total else 0
        print(f"  {horizon:>4}: {acc:5.1f}% accuracy  ({c} correct / {w} wrong, {na} not-yet-resolvable)")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--asset", default="BTCUSDT")
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    if args.source == "sample":
        import generate_sample_data
        klines = generate_sample_data.generate_klines(symbol=args.asset, n=args.n)
    else:
        import fetch_binance
        klines = fetch_binance.fetch_klines(args.asset, interval="1m", limit=args.limit)

    run(klines, args.asset)
