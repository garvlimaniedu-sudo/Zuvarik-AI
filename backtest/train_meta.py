"""
Meta-labeling: walk-forward trains a second model that decides whether to
ACT or SKIP a v1/v4 signal, using only columns already in signal_log plus
the CORRECT/WRONG ground truth evaluate.py already produces. See
signal_engine/meta_label.py's docstring for the full rationale and the
exact reason this branch sidesteps the v5 funding-rate dead end.

============================================================================
STATUS: NOT YET RUN AGAINST REAL DATA. As of this commit there IS no
printed result number — by design, not by oversight. Do not treat any
number from a future run of this script as validated until you've checked
sample size and per-fold consistency below, same standard as v1–v5.
============================================================================

signal_log is local/ephemeral SQLite (backtest/db.py) — nothing persists
between sessions. Producing a real result requires, in ONE session, in
this order:

    python3 backfill.py --source binance --asset BTCUSDT --days 90        # v1 rows
    python3 train_v4.py --source binance --days 90                        # v4 rows
    python3 evaluate.py --source binance --asset BTCUSDT --version v1 --days 90
    python3 evaluate.py --source binance --asset BTCUSDT --version v4 --days 90
                                                                            # ^ populates outcome_1h/4h/24h,
                                                                            #   which this script's labels depend on
    python3 train_meta.py --horizon 1h                                    # this script

Design choices worth reading before changing:

1. WALK-FORWARD, NOT RANDOM SPLIT: rows are sorted by signal_ts and split
   into folds chronologically (train on earlier signals, test on later
   ones) — a random train/test split would leak future-regime information
   into training, exactly the mistake this project's design principles
   (project handoff, section 4) explicitly rule out.

2. LABEL SOURCE: build_label() in meta_label.py reads outcome_<horizon>
   directly off the row — it does NOT recompute correctness itself. If
   evaluate.py hasn't been run for a given engine_version/horizon yet,
   those rows are silently unusable (outcome is NULL) and get filtered
   out before training, never imputed.

3. WHAT "ACCURACY" MEANS HERE — READ BEFORE COMPARING TO v1's 48-51%:
   this script reports TWO different numbers per fold, and they are not
   interchangeable:
     - meta-model accuracy: how often the meta-model correctly predicts
       whether the PRIMARY signal was correct (a binary classification
       accuracy on ACT-was-CORRECT vs SKIP-was-WRONG, not itself a trading
       return).
     - filtered accuracy: of the signals the meta-model said ACT on, what
       fraction were actually correct. This is the one worth comparing to
       v1's raw ~48-51% baseline (does filtering raise the effective hit
       rate on the subset it lets through), but ONLY if the ACT subset is
       large enough to not be noise — same "small samples lie" rule as
       everywhere else in this project (section 4). A filtered accuracy
       from an ACT subset under a few hundred trades is reported as such,
       explicitly flagged as not-yet-meaningful, not written up as a
       headline number.

4. ENGINE MIX: trains one shared meta-model across v1 and v4 rows
   together (is_v1/is_v4 flags let it learn separately if the two
   regimes need different treatment) rather than two fully separate
   models, since either engine's logged volume alone may be too thin to
   train on independently — revisit once real volumes are known.

5. EXPANDING VS ROLLING WINDOW: folds below use an expanding training
   window, same starting point train_v3.py used before fix/v3-rolling-
   window addressed its fold-collapse problem. Meta-labeling is lower-
   dimensional (9 features, binary target, no direction call to hedge on)
   so the same collapse is less likely, but this is NOT assumed safe —
   if a real run shows late folds concentrating almost all ACT calls in
   fold 1 the way v3's BUY/SELL calls did, switch this to a fixed rolling
   window exactly like fix/v3-rolling-window does. Check for it, don't
   assume it away.
"""

import argparse
import sys

sys.path.insert(0, "..")
import db
from signal_engine.meta_label import build_features, build_label, decide, FEATURE_NAMES
from signal_engine.logistic import train, predict_proba, standardize, apply_standardize

ENGINE_VERSIONS = ("v1", "v4")
MIN_ACT_SAMPLE = 200  # per-fold ACT count below this is flagged as noise, not a result


def load_examples(horizon):
    """Pulls every v1/v4 signal_log row that both (a) is a BUY/SELL call
    and (b) has already been graded by evaluate.py for this horizon.
    Returns rows sorted by signal_ts (required for the walk-forward split
    below) alongside parallel X/y lists."""
    rows = [r for r in db.all_rows() if r["engine_version"] in ENGINE_VERSIONS
            and r["verdict"] in ("BUY", "SELL")]
    rows.sort(key=lambda r: r["signal_ts"])

    X, y, kept_rows = [], [], []
    for r in rows:
        label = build_label(r, horizon=horizon)
        if label is None:
            continue  # not yet evaluated — never impute, per meta_label.py's docstring
        X.append(build_features(r))
        y.append(label)
        kept_rows.append(r)
    return kept_rows, X, y


def walk_forward_folds(n, n_folds=5, min_train_frac=0.4):
    """Chronological expanding-window folds. See module docstring point 5
    on why this is flagged, not assumed safe, for this use case."""
    if n < 20:
        return []
    test_size = max(1, int(n * (1 - min_train_frac) / n_folds))
    folds = []
    train_end = int(n * min_train_frac)
    for _ in range(n_folds):
        test_end = min(n, train_end + test_size)
        if test_end <= train_end:
            break
        folds.append((0, train_end, train_end, test_end))
        train_end = test_end
    return folds


def run(horizon="1h"):
    rows, X, y = load_examples(horizon)
    n = len(X)
    print(f"Loaded {n} graded v1/v4 BUY/SELL signals for horizon={horizon}.")

    if n == 0:
        print(
            "\nNO DATA AVAILABLE. This is expected on a fresh session — "
            "signal_log is empty until backfill.py/train_v4.py + evaluate.py "
            "have been run first (see this file's module docstring for the "
            "exact command order). Nothing further to report.\n"
            "STATUS: NOT YET RUN AGAINST REAL DATA."
        )
        return None

    folds = walk_forward_folds(n)
    if not folds:
        print(
            f"\nOnly {n} examples available — below the threshold to form "
            "meaningful walk-forward folds (need a few hundred at minimum "
            "per this project's 'small samples lie' rule, section 4 of the "
            "handoff). Not reporting a fold-by-fold or headline number.\n"
            "STATUS: NOT YET RUN AGAINST REAL DATA (insufficient volume)."
        )
        return None

    fold_reports = []
    for i, (tr_start, tr_end, te_start, te_end) in enumerate(folds, 1):
        X_train, y_train = X[tr_start:tr_end], y[tr_start:tr_end]
        X_test, y_test = X[te_start:te_end], y[te_start:te_end]

        X_train_s, means, stds = standardize(X_train)
        X_test_s = apply_standardize(X_test, means, stds)
        w, b = train(X_train_s, y_train)

        acted, acted_correct, meta_correct = 0, 0, 0
        for xi, yi in zip(X_test_s, y_test):
            p = predict_proba(xi, w, b)
            pred_label = 1.0 if p >= 0.5 else 0.0
            if pred_label == yi:
                meta_correct += 1
            if decide(p) == "ACT":
                acted += 1
                if yi == 1.0:
                    acted_correct += 1

        meta_acc = meta_correct / len(y_test) * 100 if y_test else 0.0
        filtered_acc = acted_correct / acted * 100 if acted else None
        fold_reports.append({
            "fold": i, "train_n": len(y_train), "test_n": len(y_test),
            "meta_acc": meta_acc, "acted": acted, "filtered_acc": filtered_acc,
        })
        filt_str = f"{filtered_acc:.1f}%" if filtered_acc is not None else "N/A (0 ACT)"
        print(f"  Fold {i}: train={len(y_train)} test={len(y_test)} "
              f"meta_acc={meta_acc:.1f}% acted_on={acted}/{len(y_test)} "
              f"filtered_acc={filt_str}")

    small_act_folds = [f["fold"] for f in fold_reports if f["acted"] and f["acted"] < MIN_ACT_SAMPLE]
    if small_act_folds:
        print(
            f"\nCAUTION: fold(s) {small_act_folds} have an ACT subset under "
            f"{MIN_ACT_SAMPLE} trades — per this project's standard, treat any "
            "filtered_acc from those folds as noise, not a result."
        )

    print("\nSTATUS: real numbers above are only real if you actually ran "
          "backfill/train_v4 + evaluate first this session — this script "
          "does not fabricate or backfill data on its own.")
    return fold_reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", choices=["1h", "4h", "24h"], default="1h")
    args = parser.parse_args()

    db.init_db()
    run(horizon=args.horizon)
    db.close()
