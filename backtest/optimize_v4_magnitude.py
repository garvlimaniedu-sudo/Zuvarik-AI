"""
v4 magnitude optimization: does widening the entry threshold and/or
extending the holding period produce fewer, larger trades that actually
clear real-world round-trip costs?

Context: the validated v4 z-score rule (Z_ENTRY=1.5, see scoring_v4.py)
fires often and wins slightly more than half the time (e.g. ETH/BTC: ~60%
at 1h, ~53% at 24h — see backtest/results/v4.md). But win rate alone
doesn't tell you whether a trade is worth taking once real costs are
subtracted: a 60%-accurate strategy whose average winning move is 3bps and
whose average losing move is -3bps nets to roughly zero (or negative) after
a 10bps+ round-trip cost, regardless of how good the hit rate looks.

This script does NOT modify scoring_v4.py's default Z_ENTRY — that constant
is what backtest/train_v4.py and evaluate.py use for the validated,
reproducible v4 result other branches/devices may depend on. Instead this
computes the z-score series ONCE (identical logic to scoring_v4.zscore),
then sweeps entry thresholds and holding periods cheaply against that same
series, since neither parameter changes the z-score itself — only which
candles qualify as a signal (threshold) and how far forward we measure the
outcome (holding period).

TRADE DEFINITION AND KNOWN SIMPLIFICATION (read before trusting the output):
- Entry: the ratio value at the candle where |z| first crosses the
  threshold. Exit: the ratio value `hold` candles later (or the last
  available candle if the series ends first — those trades are excluded,
  same "not-yet-resolvable" handling as evaluate.py).
- Gross return per trade is SIGNED by direction: for a BUY (z <= -threshold,
  expecting the ratio to rise), return = (exit - entry) / entry. For a SELL
  (z >= +threshold), return = (entry - exit) / entry. A positive gross
  return means the trade would have been profitable before costs.
- Like train_v4.py, this does NOT enforce flat-before-next-entry — signals
  can overlap in time (e.g. a threshold-crossing candle followed a few
  candles later by another crossing before the first "trade" has exited).
  This matches how evaluate.py already treats every signal independently
  elsewhere in this project, but it means these are per-trade averages,
  not a realistic capital-constrained portfolio return — flagged here
  explicitly rather than silently implied.
- ~10bps round-trip cost is used as a rough single-number cost estimate.
  In reality a ratio trade like ETH/BTC requires two separate spot legs
  (buy quote asset, sell/short base asset, or vice versa), each with its
  own spread and slippage — so 10bps may understate real cost for a true
  two-leg execution. Treated here as the instructed baseline bar, not a
  claim that 10bps is necessarily sufficient in live trading.

Usage:
    python3 optimize_v4_magnitude.py --source binance --base_asset BTCUSDT --quote_asset ETHUSDT --days 90
    python3 optimize_v4_magnitude.py --source sample --n 4000   (offline pipeline smoke test only)
"""

import argparse
import sys

sys.path.insert(0, "..")
from signal_engine.indicators import mean, stddev
from train_v4 import align_klines  # reuse the exact same alignment logic as the validated v4 pipeline

ZSCORE_WINDOW = 24  # unchanged from scoring_v4.py, so the underlying z-score series is identical

THRESHOLDS = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
HOLD_MINUTES = [15, 30, 60, 120, 240, 480, 1440]  # 1m candles == minutes here
ROUND_TRIP_COST_BPS = 10  # instructed baseline: ~10bps+
REAL_MARGIN_BPS = 20      # a trade needs to clear cost by a real margin, not just barely — 2x cost as a working bar


def compute_zscore_series(ratios):
    """One pass over the whole ratio series, identical formula to
    scoring_v4.zscore, just computed for every index up front instead of
    recomputed per threshold (the z-score doesn't depend on the threshold
    or hold period, so this is the only expensive part and it's O(n))."""
    zs = [0.0] * len(ratios)
    for i in range(len(ratios)):
        window = ratios[max(0, i - ZSCORE_WINDOW + 1):i + 1]
        if len(window) < 5:
            continue
        m = mean(window)
        s = stddev(window) or 1e-9
        zs[i] = (window[-1] - m) / s
    return zs


def sweep(ratios, zs):
    """Returns a list of dicts, one per (threshold, hold) combo, each with
    trade count, win rate, and average gross return in bps."""
    results = []
    n = len(ratios)

    for threshold in THRESHOLDS:
        # find every candle where |z| first qualifies (edge-trigger, not
        # "still above threshold" on every subsequent candle, to avoid
        # trivially double-counting one stretched period as many trades)
        signal_indices = []
        prev_qualified = False
        for i in range(ZSCORE_WINDOW, n):
            qualified = abs(zs[i]) >= threshold
            if qualified and not prev_qualified:
                direction = "BUY" if zs[i] <= -threshold else "SELL"
                signal_indices.append((i, direction))
            prev_qualified = qualified

        for hold in HOLD_MINUTES:
            returns = []
            for i, direction in signal_indices:
                exit_i = i + hold
                if exit_i >= n:
                    continue  # not yet resolvable, same handling as evaluate.py
                entry_price = ratios[i]
                exit_price = ratios[exit_i]
                if entry_price == 0:
                    continue
                raw_return = (exit_price - entry_price) / entry_price
                signed_return = raw_return if direction == "BUY" else -raw_return
                returns.append(signed_return)

            if not returns:
                results.append({
                    "threshold": threshold, "hold_min": hold, "n_trades": 0,
                    "win_rate": None, "avg_return_bps": None, "resolved": 0, "total_signals": len(signal_indices),
                })
                continue

            n_trades = len(returns)
            wins = sum(1 for r in returns if r > 0)
            win_rate = wins / n_trades * 100
            avg_return_bps = (sum(returns) / n_trades) * 10000  # convert fraction to basis points

            results.append({
                "threshold": threshold, "hold_min": hold, "n_trades": n_trades,
                "win_rate": win_rate, "avg_return_bps": avg_return_bps,
                "resolved": n_trades, "total_signals": len(signal_indices),
            })

    return results


def format_report(results, pair_label):
    lines = []
    lines.append(f"# Zuvarik AI — v4 Magnitude Optimization ({pair_label})\n")
    lines.append("Sweeping entry threshold (z-score) x holding period. "
                  f"Round-trip cost baseline: {ROUND_TRIP_COST_BPS}bps. "
                  f"\"Real margin\" bar used here: {REAL_MARGIN_BPS}bps (2x cost).\n")
    lines.append("| Z threshold | Hold (min) | Trades | Win rate | Avg gross return (bps) | Clears cost? | Real margin? |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        if r["n_trades"] == 0:
            lines.append(f"| {r['threshold']} | {r['hold_min']} | 0 (no resolvable trades) | - | - | - | - |")
            continue
        clears = "YES" if r["avg_return_bps"] > ROUND_TRIP_COST_BPS else "no"
        margin = "YES" if r["avg_return_bps"] > REAL_MARGIN_BPS else "no"
        lines.append(f"| {r['threshold']} | {r['hold_min']} | {r['n_trades']} | {r['win_rate']:.1f}% | "
                     f"{r['avg_return_bps']:.2f} | {clears} | {margin} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--base_asset", default="BTCUSDT")
    parser.add_argument("--quote_asset", default="ETHUSDT")
    parser.add_argument("--n", type=int, default=4000)
    parser.add_argument("--days", type=float, default=90)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.source == "sample":
        import generate_sample_data
        base_klines = generate_sample_data.generate_klines(symbol=args.base_asset, n=args.n, start_price=60000)
        quote_klines = generate_sample_data.generate_klines(symbol=args.quote_asset, n=args.n, start_price=3000)
        print("[local dev] Using synthetic sample data for both legs — not a real result.")
    else:
        import fetch_binance
        total_candles = int(args.days * 24 * 60)
        print(f"Fetching {args.base_asset} and {args.quote_asset}, ~{args.days} days ({total_candles} candles each)...")
        base_klines = fetch_binance.fetch_klines_paginated(args.base_asset, interval="1m", total_limit=total_candles)
        quote_klines = fetch_binance.fetch_klines_paginated(args.quote_asset, interval="1m", total_limit=total_candles)
        print(f"Fetched {len(base_klines)} {args.base_asset} candles, {len(quote_klines)} {args.quote_asset} candles.")

    common_times, ratios = align_klines(base_klines, quote_klines)
    print(f"Aligned on {len(common_times)} common timestamps.")

    print("Computing z-score series (single pass)...")
    zs = compute_zscore_series(ratios)

    print(f"Sweeping {len(THRESHOLDS)} thresholds x {len(HOLD_MINUTES)} hold periods = {len(THRESHOLDS)*len(HOLD_MINUTES)} combos...")
    results = sweep(ratios, zs)

    pair_label = f"{args.quote_asset.replace('USDT','')}{args.base_asset.replace('USDT','')}"
    report = format_report(results, pair_label)
    print(report)

    if args.out:
        import os
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(report)
        print(f"Report written to {args.out}")
