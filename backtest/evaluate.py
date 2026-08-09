"""
Evaluate: for every logged BUY/SELL signal, look up the price 1h/4h/24h later
and mark it CORRECT or WRONG. Then prints the one number Phase 1 exists to
produce: accuracy % per horizon, per engine version.

Usage (must match the same source/asset used in backfill.py so timestamps line up):
    python3 evaluate.py --source sample --asset BTCUSDT --n 2000
    python3 evaluate.py --source binance --asset BTCUSDT --limit 1000
    python3 evaluate.py --source binance --asset BTCUSDT --days 30

Pass --out results/latest.md to write a markdown report (used by the CI workflow).
Pass --version v1 (or v2, v2-confirmed) to isolate one engine version's results.
"""

import argparse
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, "..")
import db

HORIZONS = {"1h": 60, "4h": 240, "24h": 1440}  # in minutes -> candle offsets (1m candles)


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def find_future_price(ordered, index_by_ts, signal_ts, minutes_ahead):
    if signal_ts not in index_by_ts:
        return None
    idx = index_by_ts[signal_ts]
    target_idx = idx + minutes_ahead
    if target_idx >= len(ordered):
        return None
    return ordered[target_idx][1]


def run(klines, asset, engine_version=None):
    ordered = []
    ts_to_idx = {}
    for i, k in enumerate(klines):
        iso = ms_to_iso(k["open_time"])
        ordered.append((iso, k["close"]))
        ts_to_idx[iso] = i

    rows = [r for r in db.all_rows() if r["asset"] == asset]
    if engine_version:
        rows = [r for r in rows if r["engine_version"] == engine_version]
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

    total_signals = len(rows)
    buy_sell = sum(1 for r in rows if r["verdict"] in ("BUY", "SELL"))

    version_label = f" — engine {engine_version}" if engine_version else " — all versions"
    lines = []
    lines.append(f"# Zuvarik AI — Backtest Report ({asset}{version_label})\n")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
    lines.append(f"Total signals logged: {total_signals} (BUY/SELL: {buy_sell})\n")
    lines.append("| Horizon | Accuracy | Correct | Wrong | Not yet resolvable |")
    lines.append("|---|---|---|---|---|")
    for horizon in HORIZONS:
        c, w, na = results[horizon]["CORRECT"], results[horizon]["WRONG"], results[horizon]["N-A"]
        total = c + w
        acc = (c / total * 100) if total else 0
        lines.append(f"| {horizon} | {acc:.1f}% | {c} | {w} | {na} |")
    report = "\n".join(lines) + "\n"

    print(f"\n=== Zuvarik AI — Backtest Report ({asset}{version_label}) ===")
    for horizon in HORIZONS:
        c, w, na = results[horizon]["CORRECT"], results[horizon]["WRONG"], results[horizon]["N-A"]
        total = c + w
        acc = (c / total * 100) if total else 0
        print(f"  {horizon:>4}: {acc:5.1f}% accuracy  ({c} correct / {w} wrong, {na} not-yet-resolvable)")
    print()

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--asset", default="BTCUSDT")
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--days", type=float, default=None)
    parser.add_argument("--out", default=None, help="path to write markdown report, e.g. results/latest.md")
    parser.add_argument("--version", default=None, help="filter to one engine_version, e.g. v1, v2, v2-confirmed")
    args = parser.parse_args()

    if args.source == "sample":
        import generate_sample_data
        klines = generate_sample_data.generate_klines(symbol=args.asset, n=args.n)
    else:
        import fetch_binance
        if args.days is not None:
            total_candles = int(args.days * 24 * 60)
            klines = fetch_binance.fetch_klines_paginated(args.asset, interval="1m", total_limit=total_candles)
        else:
            klines = fetch_binance.fetch_klines(args.asset, interval="1m", limit=args.limit)

    report = run(klines, args.asset, engine_version=args.version)

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(report)
        print(f"Report written to {args.out}")
