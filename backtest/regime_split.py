"""
Regime split: slices already-logged signal outcomes by market regime (trend
direction + volatility level at the moment the signal fired) to answer a
sharper question than the flat backtest number: is v1 actually blind
everywhere, or does it have an edge in specific conditions that a flat
average washes out?

Requires signal_log to already have outcomes filled in (run backfill.py +
evaluate.py first for the same asset/window).

Usage:
    python3 regime_split.py --source binance --asset BTCUSDT --days 90
    python3 regime_split.py --source sample --asset BTCUSDT --n 2000
"""

import argparse
import sys
from datetime import datetime, timezone
from statistics import stdev, median

sys.path.insert(0, "..")
import db

TREND_LOOKBACK = 60     # candles (~1h at 1m resolution) to judge trend direction
TREND_THRESHOLD = 0.15  # % move over lookback to call it trending vs ranging
VOL_LOOKBACK = 30       # candles for the rolling volatility measure


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def classify_regimes(klines):
    """Returns {iso_timestamp: {"trend": ..., "vol": ...}} for every candle
    with enough history behind it to classify."""
    closes = [k["close"] for k in klines]
    tags = {}

    # first pass: rolling volatility (stddev of 1-candle returns) per index
    vols = [None] * len(closes)
    for i in range(VOL_LOOKBACK, len(closes)):
        window = closes[i - VOL_LOOKBACK:i + 1]
        returns = [(window[j] - window[j - 1]) / window[j - 1] for j in range(1, len(window))]
        vols[i] = stdev(returns) if len(returns) > 1 else 0
    resolved_vols = [v for v in vols if v is not None]
    vol_median = median(resolved_vols) if resolved_vols else 0

    for i in range(TREND_LOOKBACK, len(closes)):
        if vols[i] is None:
            continue
        move_pct = ((closes[i] - closes[i - TREND_LOOKBACK]) / closes[i - TREND_LOOKBACK]) * 100
        if move_pct > TREND_THRESHOLD:
            trend = "uptrend"
        elif move_pct < -TREND_THRESHOLD:
            trend = "downtrend"
        else:
            trend = "ranging"

        vol_tag = "high_vol" if vols[i] > vol_median else "low_vol"
        tags[ms_to_iso(klines[i]["open_time"])] = {"trend": trend, "vol": vol_tag}

    return tags


def run(klines, asset):
    tags = classify_regimes(klines)
    rows = [r for r in db.all_rows() if r["asset"] == asset and r["verdict"] in ("BUY", "SELL")]

    buckets = {}  # (trend, vol) -> {horizon -> {CORRECT, WRONG}}
    for row in rows:
        tag = tags.get(row["signal_ts"])
        if not tag:
            continue
        key = (tag["trend"], tag["vol"])
        buckets.setdefault(key, {h: {"CORRECT": 0, "WRONG": 0} for h in ("1h", "4h", "24h")})
        for h in ("1h", "4h", "24h"):
            outcome = row[f"outcome_{h}"]
            if outcome in ("CORRECT", "WRONG"):
                buckets[key][h][outcome] += 1

    print(f"\n=== Zuvarik AI — Regime Split ({asset}) ===")
    print(f"{'regime':<22}{'1h':>10}{'4h':>10}{'24h':>10}{'  n(1h)':>10}")
    for key in sorted(buckets, key=lambda k: -sum(buckets[k]["1h"].values())):
        trend, vol = key
        row = buckets[key]
        line = f"{trend + '/' + vol:<22}"
        for h in ("1h", "4h", "24h"):
            c, w = row[h]["CORRECT"], row[h]["WRONG"]
            total = c + w
            acc = (c / total * 100) if total else 0
            line += f"{acc:9.1f}%"
        n1h = row["1h"]["CORRECT"] + row["1h"]["WRONG"]
        line += f"{n1h:10d}"
        print(line)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--asset", default="BTCUSDT")
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    if args.source == "sample":
        import generate_sample_data
        klines = generate_sample_data.generate_klines(symbol=args.asset, n=args.n)
    else:
        import fetch_binance
        klines = fetch_binance.fetch_klines_range(args.asset, interval="1m", days=args.days)

    run(klines, args.asset)
