"""
v3: walk-forward trained logistic regression, triple-barrier labeled.

Critical rule this script exists to enforce: the model NEVER sees a test
fold's data during its own training. It's trained fold-by-fold on a FIXED
ROLLING window of the most recent past (see ROLLING_DAYS), then only ever
predicts on the fold immediately after — the same constraint a live
deployment would face (you can't train on the future). This is what
"walk-forward" means and why it's the honest way to validate a fitted
model, unlike a single train/test split on the whole history.

Fix history: this used to train each fold on an EXPANDING window (all
history since the start). That caused later folds to blend multiple market
regimes together with no way to distinguish them, collapsing predicted
probabilities toward 0.5 and killing signal volume in later folds — see
run()'s docstring for the full explanation. Now fixed to a rolling window.

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
ROLLING_DAYS = 25      # fixed training window size, in days (not expanding) — see run() docstring
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
    """
    Rolling-window walk-forward (fixed, not expanding).

    Earlier version trained each fold on ALL accumulated history since the
    start (an expanding window). That caused a real bug: by fold 4, the
    model was blending ~4/5ths of the full 90-day history into one training
    set, mixing multiple market regimes with no way to tell them apart.
    Predicted probabilities collapsed toward 0.5 (the neutral zone) as a
    result — later folds fired almost no BUY/SELL signals at all, so a
    reported headline accuracy was really just fold 1's small-window result
    wearing a 90-day label.

    Fix: cap the training window at ROLLING_DAYS of the most recent history
    before each fold's test period, instead of letting it grow unbounded.
    This keeps every fold training on a similarly-sized, more homogeneous
    slice of time — standard practice for non-stationary data like crypto.
    """
    db.init_db()
    n = len(klines)
    fold_bounds = [int(n * i / FOLDS) for i in range(FOLDS + 1)]
    candles_per_day = 24 * 60  # 1m candles
    rolling_candles = ROLLING_DAYS * candles_per_day

    total_logged = {"BUY": 0, "SELL": 0, "HOLD": 0}
    total_train_examples = 0

    for k in range(1, FOLDS):
        train_end = fold_bounds[k]
        test_start, test_end = fold_bounds[k], fold_bounds[k + 1]

        # fixed rolling window: only the most recent ROLLING_DAYS before this
        # fold's test period, NOT everything since the start (that was the bug)
        train_start = max(LOOKBACK, train_end - rolling_candles)
        X_train, y_train = build_training_set(klines, train_start, train_end)

        pos = sum(1 for lbl in y_train if lbl == 1)
        neg = len(y_train) - pos
        print(f"Fold {k}: label balance — {pos} positive (TP-hit) / {neg} negative (SL-hit) "
              f"({pos / len(y_train) * 100:.1f}% positive)" if y_train else f"Fold {k}: no labeled examples.")

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
    db.close()
