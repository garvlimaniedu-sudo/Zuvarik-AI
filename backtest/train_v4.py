"""
v4: relative-value (cross-asset ratio) mean-reversion — walk-forward tested.

Originally built and validated on ETH/BTC (see backtest/results/v4.md from
that run: 62.1-62.6% at 1h, 56.7-57.3% at 4h, 53.3-53.5% at 24h, consistent
across independent 30-day and 90-day windows). Generalized here to any two
assets via --base_asset/--quote_asset, to test whether the mean-reverting
ratio structure that worked for ETH/BTC generalizes to other pairs
(BNB/ETH, XRP/BTC) or was specific to that one pair — a single working pair
is a finding about one relationship, not yet evidence the underlying idea
(correlated-asset ratios mean-revert) is a general one worth building on.

Fetches base_asset and quote_asset klines for the same real time window,
aligns them by timestamp, builds the quote/base ratio series, and
walk-forward evaluates the z-score mean-reversion rule from scoring_v4.py
against real triple-barrier-labeled outcomes on the ratio's own future path
(not either asset's raw price — a "correct" v4 call is about the ratio
moving the predicted direction, not either asset's absolute price).

Design choices worth reading before changing:

1. ALIGNMENT: Binance serves BTCUSDT and ETHUSDT as independently paginated
   kline series. They are usually candle-for-candle aligned on 1m intervals,
   but this script does NOT assume that — it intersects on open_time so a
   missing candle on either side never desyncs the ratio series or lets a
   BTC candle get paired with the wrong ETH candle.

2. NO TRAINING/FITTING HAPPENING HERE, UNLIKE v3: this is a fixed
   z-score rule (from scoring_v4.py), not a fitted model, so there's no
   train/test leakage risk in the ML sense — but this script still walks
   forward through the ratio series exactly like a live deployment would
   (each signal only ever looks at CURRENT and PAST candles for its rolling
   mean/stddev, never future ones), because a rule that peeked forward
   would be a look-ahead-biased backtest even without any learned weights.

3. EVALUATION: evaluate.py's run() function only cares about a list of
   {open_time, close} dicts and a signal_log table — it doesn't know or
   care whether "close" is a real asset price or a synthetic ratio. So
   this script builds a synthetic "ratio klines" list (open_time from the
   real aligned candles, close = the ratio) and calls evaluate.run()
   directly with it, reusing the exact same accuracy-checking logic as
   v1/v2/v3 without duplicating or diverging from it.

4. LABELING: triple_barrier.py is reused unchanged on the ratio series —
   it's asset-agnostic (just walks a list of {high, low, close} looking for
   barrier hits), so passing it synthetic ratio-OHLC (using the ratio value
   for all of open/high/low/close, since we don't have true ratio intra-
   candle range) works correctly for its purpose here, though this is a
   simplification: TP/SL barrier hits are checked only against the ratio's
   candle-close-to-candle-close path, not a true intra-candle high/low of
   the ratio itself (which would require computing ratio highs/lows from
   BTC/ETH's own highs/lows, which don't move in perfect lockstep and would
   overstate volatility). Worth revisiting if v4 shows a real signal, but
   fine for a first honest test of the underlying idea.

Usage:
    python3 train_v4.py --source binance --base_asset BTCUSDT --quote_asset ETHUSDT --days 90
    python3 train_v4.py --source binance --base_asset ETHUSDT --quote_asset BNBUSDT --days 90
    python3 train_v4.py --source binance --base_asset BTCUSDT --quote_asset XRPUSDT --days 90
    python3 train_v4.py --source sample --n 4000     (offline pipeline smoke test only)
"""

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, "..")
from signal_engine.scoring_v4 import compute_signal, ENGINE_VERSION, ZSCORE_WINDOW
from signal_engine.triple_barrier import label_triple_barrier
import db
import evaluate as evaluate_module

TP_PCT = 0.004   # 0.4% ratio move — ETH/BTC ratio is typically less volatile
SL_PCT = 0.004   # than either asset's own price, so barriers are a bit tighter than v3's
MAX_HOLD = 30    # candles


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def align_klines(base_klines, quote_klines):
    """Intersect two independently-fetched kline series on open_time so a
    gap or listing mismatch on either side can never misalign the ratio.
    Generalized from the original BTC/ETH-only version (device 2's earlier
    session) to work with any two assets — e.g. base=ETHUSDT/quote=BNBUSDT
    for BNB/ETH, or base=BTCUSDT/quote=XRPUSDT for XRP/BTC.
    Returns (aligned_open_times, aligned_ratios). Ratio = quote_close / base_close."""
    base_by_time = {k["open_time"]: k for k in base_klines}
    quote_by_time = {k["open_time"]: k for k in quote_klines}
    common_times = sorted(set(base_by_time) & set(quote_by_time))

    ratios = []
    for t in common_times:
        base_close = base_by_time[t]["close"]
        quote_close = quote_by_time[t]["close"]
        ratios.append(quote_close / base_close if base_close else 0)

    return common_times, ratios


def build_ratio_klines(common_times, ratios):
    """Synthetic OHLC list matching fetch_binance.py's dict shape, so
    evaluate.py and triple_barrier.py can consume it unmodified. See
    docstring point 3/4 above for why open/high/low/close all use the
    ratio value."""
    return [
        {"open_time": t, "open": r, "high": r, "low": r, "close": r, "volume": 0.0}
        for t, r in zip(common_times, ratios)
    ]


def run(common_times, ratios, ratio_klines, pair_label="ETHBTC"):
    db.init_db()
    logged = {"BUY": 0, "SELL": 0, "HOLD": 0}
    n = len(ratios)

    for i in range(ZSCORE_WINDOW, n):
        # walk-forward: only ever look at ratios up to and including index i
        window = ratios[max(0, i - ZSCORE_WINDOW + 1):i + 1]
        sig = compute_signal(window)
        logged[sig["verdict"]] += 1

        if sig["verdict"] not in ("BUY", "SELL"):
            continue

        # Log the signal itself. price_at_signal here is the RATIO value at
        # signal time, matching what evaluate.py will compare against
        # future ratio values — consistent units throughout.
        db.insert_signal(
            asset=pair_label,
            signal_ts=ms_to_iso(common_times[i]),
            sig=sig,
            price_at_signal=ratios[i],
        )

    print(f"v4 ({pair_label}) walk-forward run: {n - ZSCORE_WINDOW} candles evaluated, logged: {logged}")
    return logged


def label_diagnostics(ratio_klines, sample_stride=50):
    """Quick label-balance check on the ratio series via triple-barrier —
    same diagnostic device 1 added for v3, applied here so any imbalance in
    the ratio's own TP/SL hit distribution is visible before trusting an
    accuracy number. Sampled (not every candle) purely to keep this fast;
    it's a diagnostic printout, not the actual signal logic."""
    pos, neg, none = 0, 0, 0
    for i in range(0, len(ratio_klines) - MAX_HOLD - 1, sample_stride):
        label, _ = label_triple_barrier(ratio_klines, i, tp_pct=TP_PCT, sl_pct=SL_PCT, max_hold=MAX_HOLD)
        if label == 1:
            pos += 1
        elif label == 0:
            neg += 1
        else:
            none += 1
    total = pos + neg
    pos_pct = (pos / total * 100) if total else 0
    print(f"Ratio triple-barrier label balance (sampled every {sample_stride} candles): "
          f"{pos} positive / {neg} negative ({pos_pct:.1f}% positive), {none} timed out")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--btc_asset", "--base_asset", dest="base_asset", default="BTCUSDT",
                        help="denominator asset, e.g. BTCUSDT (kept --btc_asset as an alias for backward compatibility with the original ETH/BTC run)")
    parser.add_argument("--eth_asset", "--quote_asset", dest="quote_asset", default="ETHUSDT",
                        help="numerator asset, e.g. ETHUSDT (kept --eth_asset as an alias). Ratio computed is quote_asset/base_asset.")
    parser.add_argument("--n", type=int, default=4000, help="candle count (sample source)")
    parser.add_argument("--days", type=float, default=30, help="days of real history (binance source)")
    parser.add_argument("--out", default=None, help="path to write markdown report, e.g. results/v4.md")
    args = parser.parse_args()

    if args.source == "sample":
        import generate_sample_data
        # two independent synthetic series so the ratio isn't degenerately constant —
        # different seeds via the symbol string, same mechanism generate_sample_data
        # already uses to vary its output.
        base_klines = generate_sample_data.generate_klines(symbol=args.base_asset, n=args.n, start_price=60000)
        quote_klines = generate_sample_data.generate_klines(symbol=args.quote_asset, n=args.n, start_price=3000)
        print("[local dev] Using synthetic sample data for both legs — not a real accuracy number.")
    else:
        import fetch_binance
        total_candles = int(args.days * 24 * 60)
        print(f"Fetching {args.base_asset} and {args.quote_asset}, ~{args.days} days ({total_candles} candles each)...")
        base_klines = fetch_binance.fetch_klines_paginated(args.base_asset, interval="1m", total_limit=total_candles)
        quote_klines = fetch_binance.fetch_klines_paginated(args.quote_asset, interval="1m", total_limit=total_candles)
        print(f"Fetched {len(base_klines)} {args.base_asset} candles, {len(quote_klines)} {args.quote_asset} candles.")

    common_times, ratios = align_klines(base_klines, quote_klines)
    print(f"Aligned on {len(common_times)} common timestamps "
          f"({len(base_klines) - len(common_times)} {args.base_asset} / {len(quote_klines) - len(common_times)} {args.quote_asset} candles dropped for no counterpart).")

    ratio_klines = build_ratio_klines(common_times, ratios)
    label_diagnostics(ratio_klines)

    pair_label = f"{args.quote_asset.replace('USDT','')}{args.base_asset.replace('USDT','')}"  # e.g. ETHBTC, BNBETH, XRPBTC
    run(common_times, ratios, ratio_klines, pair_label=pair_label)
    db.close()

    # Reuse evaluate.py's run() directly against the synthetic ratio-klines
    # series, tagged v4 — same accuracy-checking logic as every other version,
    # no duplicated or diverging evaluation code.
    print("\nRunning evaluate.py logic against the ratio series (engine_version=v4)...")
    db.init_db()
    report = evaluate_module.run(ratio_klines, pair_label, engine_version=ENGINE_VERSION)
    db.close()

    if args.out:
        import os
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(report)
        print(f"Report written to {args.out}")
