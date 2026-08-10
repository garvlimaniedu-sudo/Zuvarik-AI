"""
v3: walk-forward trained logistic regression, triple-barrier labeled.

Critical rule this script exists to enforce: the model NEVER sees a test
fold's data during its own training. It's trained fold-by-fold on an
expanding window of the past, then only ever predicts on the fold
immediately after — the same constraint a live deployment would face
(you can't train on the future). This is what "walk-forward" means and
why it's the honest way to validate a fitted model, unlike a single
train/test split on the whole history.

Logs predictions to signal_log as engine_version "v3" — reuses evaluate.py
unchanged for the final accuracy report (run it with --version v3 after
this).

Usage:
    python3 train_v3.py --source binance --asset BTCUSDT --days 90
    python3 train_v3.py --source sample --asset BTCUSDT --n 4000
"""

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, "..")
from signal_engine.features import build_features, vectorize, FEATURE_KEYS
from signal_engine.triple_barrier import label_triple_barrier
from signal_engine.logistic import standardize, apply_standardize, train, predict_proba
import db

ENGINE_VERSION = "v3"
LOOKBACK = 40         # trailing candles needed for features to be meaningful
MAX_HOLD = 30          # triple-barrier time limit, in candles
TP_PCT = 0.003         # 0.3% take-profit barrier
SL_PCT = 0.003         # 0.3% stop-loss barrier
FOLDS = 5              # walk-forward folds
BUY_THRESHOLD = 0.60   # predicted probability above this -> BUY
SELL_THRESHOLD = 0.40  # predicted probability below this -> SELL


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def build_training_set(candles, start, end):
    """Builds (X, y) from candles[start:end], each example labeled via
    triple-barrier using only that example's own future (still within the
    fold — no leakage across folds since folds are used in order)."""
    X, y = [], []
    for i in range(start, end):
        if i < LOOKBACK:
            continue
        label, _ = label_triple_barrier(candles, i, tp_pct=TP_PCT, sl_pct=SL_PCT, max_hold=MAX_HOLD)
        if label is None:
            continue  # timeout — ambiguous, excluded from training
        window = candles[max(0, i - LOOKBACK + 1):i + 1]
        day_change = ((window[-1]["close"] - window[0]["close"]) / window[0]["close"]) * 100 if window[0]["close"] else 0
        feats = build_features(window, day_change_pct=day_change)
        X.append(vectorize(feats))
        y.append(label)
    return X, y


def run(klines, asset):
    db.init_db()
    n = len(klines)
    fold_bounds = [int(n * i / FOLDS) for i in range(FOLDS + 1)]

    total_logged = {"BUY": 0, "SELL": 0, "HOLD": 0}
    total_train_examples = 0

    for k in range(1, FOLDS):
        train_end = fold_bounds[k]
        test_start, test_end = fold_bounds[k], fold_bounds[k + 1]

        # expanding window: train on everything before this fold, not just the previous one
        X_train, y_train = build_training_set(klines, LOOKBACK, train_end)
        if len(X_train) < 30 or len(set(y_train)) < 2:
            print(f"Fold {k}: not enough labeled examples ({len(X_train)}) or only one class — skipping.")
            continue
        total_train_examples += len(X_train)

        X_scaled, means, stds = standardize(X_train)
        w, b = train(X_scaled, y_train, lr=0.1, epochs=300, l2=0.001)

        fold_logged = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for i in range(max(test_start, LOOKBACK), test_end):
            window = klines[max(0, i - LOOKBACK + 1):i + 1]
            day_change = ((window[-1]["close"] - window[0]["close"]) / window[0]["close"]) * 100 if window[0]["close"] else 0
            feats = build_features(window, day_change_pct=day_change)
            x = vectorize(feats)
            x_scaled = apply_standardize([x], means, stds)[0]
            proba = predict_proba(x_scaled, w, b)

            if proba > BUY_THRESHOLD:
                verdict = "BUY"
            elif proba < SELL_THRESHOLD:
                verdict = "SELL"
            else:
                verdict = "HOLD"
            fold_logged[verdict] += 1
            total_logged[verdict] += 1

            if verdict in ("BUY", "SELL"):
                confidence = max(48, min(97, round(50 + abs(proba - 0.5) * 100)))
                sig = {
                    "verdict": verdict, "confidence": confidence,
                    "reasons": [f"v3 model probability: {proba:.3f}"],
                    "rsi": feats["rsi"], "ema_fast": None, "ema_slow": None,
                    "momentum": feats["momentum"], "vol_ratio": feats["vol_ratio"],
                    "day_change": feats["day_change"], "engine_version": ENGINE_VERSION,
                }
                db.insert_signal(
                    asset=asset,
                    signal_ts=ms_to_iso(klines[i]["open_time"]),
                    sig=sig,
                    price_at_signal=klines[i]["close"],
                )

        print(f"Fold {k}: trained on {len(X_train)} examples "
              f"(train/test split at candle {train_end}), test fold logged {fold_logged}")

    print(f"\n=== Zuvarik AI — v3 Walk-Forward Training ({asset}) ===")
    print(f"Total training examples used across folds: {total_train_examples}")
    print(f"Total signals logged: {total_logged}")
    print(f"Labeling: triple-barrier (TP {TP_PCT*100:.1f}% / SL {SL_PCT*100:.1f}% / max hold {MAX_HOLD} candles)")
    print(f"Run evaluate.py --version v3 next to see the real, walk-forward-honest accuracy.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["sample", "binance"], default="sample")
    parser.add_argument("--asset", default="BTCUSDT")
    parser.add_argument("--n", type=int, default=4000)
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
