"""
Backfill: replays historical 1m klines through the signal engine exactly the
way the live app would, candle by candle, and logs every BUY/SELL/HOLD/WAIT
into signal_log. This is how a track record gets built before real users
ever see the product.

Usage:
    python3 backfill.py --source sample --asset BTCUSDT --n 2000
    python3 backfill.py --source binance --asset BTCUSDT --limit 1000
    python3 backfill.py --source binance --asset BTCUSDT --days 30   # paginated, real multi-week history
"""

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, "..")
from signal_engine.scoring import compute_signal
import db


WINDOW = 60  # how many trailing candles the engine sees, same as the live app (fetchKlines limit=60)


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def run(klines, asset):
    db.init_db()
    closes = [k["close"] for k in klines]
    volumes = [k["volume"] for k in klines]

    logged = {"BUY": 0, "SELL": 0, "HOLD": 0, "WAIT": 0}

    for i in range(8, len(klines)):
        window_start = max(0, i - WINDOW + 1)
        price_window = closes[window_start:i + 1]
        vol_window = volumes[window_start:i + 1]

        # crude day-change proxy from the trailing window since we don't have
        # a real 24hr ticker in backfill mode
        day_change = ((price_window[-1] - price_window[0]) / price_window[0]) * 100 if price_window[0] else 0

        sig = compute_signal(price_window, vol_window, day_change_pct=day_change, news_bias=0.0)
        logged[sig["verdict"]] += 1

        db.insert_signal(
            asset=asset,
            signal_ts=ms_to_iso(klines[i]["open_time"]),
            sig=sig,
            price_at_signal=closes[i],
        )

    print(f"Backfilled {len(klines) - 8} candles for {asset}: {logged}")
    return logged


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--asset", default="BTCUSDT")
    parser.add_argument("--n", type=int, default=2000, help="candle count (sample source)")
    parser.add_argument("--limit", type=int, default=1000, help="candle count (binance source, single call, max 1000)")
    parser.add_argument("--days", type=float, default=None, help="binance source: pull this many days of real 1m history via pagination (overrides --limit)")
    args = parser.parse_args()

    if args.source == "sample":
        import generate_sample_data
        klines = generate_sample_data.generate_klines(symbol=args.asset, n=args.n)
        print(f"[local dev] Using synthetic sample data — not a real accuracy number.")
    else:
        import fetch_binance
        if args.days is not None:
            total_candles = int(args.days * 24 * 60)  # 1m candles
            print(f"Fetching ~{args.days} days ({total_candles} candles) of real {args.asset} history from Binance (paginated)...")
            klines = fetch_binance.fetch_klines_paginated(args.asset, interval="1m", total_limit=total_candles)
            print(f"Fetched {len(klines)} real candles.")
        else:
            klines = fetch_binance.fetch_klines(args.asset, interval="1m", limit=args.limit)

    run(klines, args.asset)
    db.close()
