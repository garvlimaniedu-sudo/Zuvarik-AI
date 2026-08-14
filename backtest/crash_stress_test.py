"""
Crash-regime stress test for v4 (relative-value ETH/BTC mean-reversion).

Every prior validation of v4 tested "normal" market conditions. This
specifically hunts for the worst realized-volatility period available and
re-runs v4 isolated on just that window — because mean-reversion strategies
are structurally vulnerable to strong one-directional moves (a "stretched"
ratio can keep running instead of reverting, and losses compound). This is
the test that answers "can this survive the harshest moments," not just
"is it accurate on average."

Method:
  1. Scan a long history of hourly BTC candles for the highest-realized-
     volatility contiguous WINDOW_HOURS-hour window (default 7 days).
  2. Pull real 1-minute BTC+ETH data for that specific window (plus lookback
     buffer for the z-score window and lookahead buffer for horizon checks).
  3. Run v4's actual compute_signal() unchanged through it.
  4. Report not just accuracy, but the metrics that actually determine
     survivability: worst single-trade loss and longest consecutive-loss
     streak, per horizon.

Usage:
    python3 crash_stress_test.py --asset_base BTCUSDT --asset_quote ETHUSDT --scan_days 200
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from statistics import stdev

sys.path.insert(0, "..")
from signal_engine.scoring_v4 import compute_signal, ZSCORE_WINDOW
import fetch_binance

HORIZONS = {"1h": 60, "4h": 240, "24h": 1440}
WINDOW_HOURS = 168  # 7 days


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def find_worst_week(scan_days, base_asset):
    hourly = fetch_binance.fetch_klines_paginated(base_asset, interval="1h", total_limit=scan_days * 24)
    closes = [k["close"] for k in hourly]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    best_idx, best_vol = WINDOW_HOURS, 0
    for i in range(WINDOW_HOURS, len(returns)):
        v = stdev(returns[i - WINDOW_HOURS:i])
        if v > best_vol:
            best_vol, best_idx = v, i

    start_ms = hourly[best_idx - WINDOW_HOURS]["open_time"]
    end_ms = hourly[best_idx]["open_time"]
    start_price, end_price = closes[best_idx - WINDOW_HOURS], closes[best_idx]
    print(f"Worst {WINDOW_HOURS}h window found: {ms_to_iso(start_ms)} to {ms_to_iso(end_ms)}")
    print(f"  {base_asset}: {start_price:.0f} -> {end_price:.0f} ({(end_price/start_price-1)*100:.1f}%), "
          f"realized hourly-return stdev: {best_vol:.5f}")
    return start_ms, end_ms


def run(base_asset, quote_asset, scan_days):
    start_ms, end_ms = find_worst_week(scan_days, base_asset)
    buffer_ms = 86_400_000  # 1 day lookback/lookahead buffer

    base = fetch_binance.fetch_klines_paginated(base_asset, interval="1m",
                                                  start_time=start_ms - buffer_ms, end_time=end_ms + buffer_ms)
    quote = fetch_binance.fetch_klines_paginated(quote_asset, interval="1m",
                                                   start_time=start_ms - buffer_ms, end_time=end_ms + buffer_ms)

    base_by_ts = {k["open_time"]: k["close"] for k in base}
    quote_by_ts = {k["open_time"]: k["close"] for k in quote}
    common_ts = sorted(set(base_by_ts) & set(quote_by_ts))
    ratios = [quote_by_ts[t] / base_by_ts[t] for t in common_ts]

    signals = []
    for i in range(ZSCORE_WINDOW, len(ratios)):
        window = ratios[max(0, i - 60):i + 1]
        sig = compute_signal(window)
        if sig["verdict"] in ("BUY", "SELL"):
            signals.append((i, sig["verdict"], ratios[i]))

    print(f"\nActionable signals in stress window: {len(signals)}")

    results = {h: [] for h in HORIZONS}
    for i, verdict, entry_ratio in signals:
        for h, mins in HORIZONS.items():
            j = i + mins
            if j >= len(ratios):
                continue
            future = ratios[j]
            moved_up = future > entry_ratio
            correct = moved_up if verdict == "BUY" else not moved_up
            signed_pct = (future / entry_ratio - 1) * (1 if verdict == "BUY" else -1) * 100
            results[h].append((correct, signed_pct, common_ts[i]))

    print(f"\n=== Zuvarik AI — v4 Crash-Regime Stress Test ({quote_asset}/{base_asset}) ===")
    for h in HORIZONS:
        rows = results[h]
        if not rows:
            continue
        acc = sum(1 for r in rows if r[0]) / len(rows) * 100
        worst = min(rows, key=lambda r: r[1])
        streak = maxstreak = 0
        for r in rows:
            streak = streak + 1 if not r[0] else 0
            maxstreak = max(maxstreak, streak)
        print(f"  {h:>4}: {acc:5.1f}% accuracy (n={len(rows)})  |  "
              f"worst single trade: {worst[1]:6.3f}%  |  longest loss streak: {maxstreak}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset_base", default="BTCUSDT")
    parser.add_argument("--asset_quote", default="ETHUSDT")
    parser.add_argument("--scan_days", type=int, default=200)
    args = parser.parse_args()

    run(args.asset_base, args.asset_quote, args.scan_days)
