"""
Confirmation pipeline: implements "don't trust a signal until it survives
being rechecked."

For every preliminary v2 signal:
  1. Fire at candle i.
  2. Recheck at candle i+RECHECK_1 (default +5) — does the engine still agree
     on direction using fresh data as of that point?
  3. If yes, recheck again at i+RECHECK_2 (default +15).
  4. Only signals that survive BOTH rechecks get logged as CONFIRMED — and
     logged with signal_ts/price_at_signal set to the i+RECHECK_2 point,
     because that's the earliest point you could have honestly entered the
     trade. Logging the original candle's price would be back-testing a
     trade you didn't actually have the information to make yet.

This trades a large chunk of signal volume for (hopefully) higher quality —
prints a funnel showing exactly how much gets filtered out at each stage,
so the tradeoff is visible, not hidden inside a single accuracy number.

Usage:
    python3 confirm_pipeline.py --source binance --asset BTCUSDT --days 90
    python3 confirm_pipeline.py --source sample --asset BTCUSDT --n 3000
"""

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, "..")
from signal_engine.scoring_v2 import compute_signal, ENGINE_VERSION
import db

WINDOW = 60
RECHECK_1 = 5
RECHECK_2 = 15


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def signal_at(klines, i):
    window_start = max(0, i - WINDOW + 1)
    window = klines[window_start:i + 1]
    closes = [k["close"] for k in window]
    day_change = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] else 0
    return compute_signal(window, day_change_pct=day_change, news_bias=0.0)


def run(klines, asset):
    db.init_db()
    funnel = {"prelim": 0, "survived_recheck1": 0, "confirmed": 0}
    rejections = {"reversed_at_5": 0, "reversed_at_15": 0, "went_hold": 0}

    max_i = len(klines) - RECHECK_2 - 1

    for i in range(8, max_i):
        prelim = signal_at(klines, i)
        if prelim["verdict"] not in ("BUY", "SELL"):
            continue
        funnel["prelim"] += 1
        direction = prelim["verdict"]

        check1 = signal_at(klines, i + RECHECK_1)
        if check1["verdict"] != direction:
            if check1["verdict"] == "HOLD":
                rejections["went_hold"] += 1
            else:
                rejections["reversed_at_5"] += 1
            continue
        funnel["survived_recheck1"] += 1

        check2 = signal_at(klines, i + RECHECK_2)
        if check2["verdict"] != direction:
            rejections["reversed_at_15"] += 1
            continue

        # confirmed — log at the confirmation point, not the original candle
        confirm_idx = i + RECHECK_2
        db.insert_signal(
            asset=asset,
            signal_ts=ms_to_iso(klines[confirm_idx]["open_time"]),
            sig=check2,
            price_at_signal=klines[confirm_idx]["close"],
            news_bias=0.0,
        )
        funnel["confirmed"] += 1

    print(f"\n=== Zuvarik AI — Confirmation Funnel ({asset}, engine {ENGINE_VERSION}) ===")
    print(f"  Preliminary signals:        {funnel['prelim']}")
    print(f"  Survived recheck @+{RECHECK_1}:      {funnel['survived_recheck1']}"
          f"  ({funnel['survived_recheck1'] / funnel['prelim'] * 100 if funnel['prelim'] else 0:.1f}% kept)")
    print(f"  Confirmed @+{RECHECK_2} (logged):   {funnel['confirmed']}"
          f"  ({funnel['confirmed'] / funnel['prelim'] * 100 if funnel['prelim'] else 0:.1f}% of prelim survived both checks)")
    print(f"  Rejected — reversed@+{RECHECK_1}:  {rejections['reversed_at_5']}")
    print(f"  Rejected — went HOLD@+{RECHECK_1}: {rejections['went_hold']}")
    print(f"  Rejected — reversed@+{RECHECK_2}: {rejections['reversed_at_15']}")
    print(f"\nRun evaluate.py next (same asset) to see if the survivors are actually more accurate.\n")


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
        total_candles = int(args.days * 24 * 60)
        klines = fetch_binance.fetch_klines_paginated(args.asset, interval="1m", total_limit=total_candles)

    run(klines, args.asset)
    db.close()
