"""
Meta-labeling filter for v1/v4 signals — branch feature/meta-labeling.

Standard "meta-labeling" (Lopez de Prado): instead of predicting direction
(BUY/SELL) itself, this trains a SECOND, much narrower model that only
answers "should we act on the primary model's call, or sit this one out?"
The primary model (v1 or v4) still decides direction; this one decides
whether that call is trustworthy enough to trade, using only information
that was already available at signal time.

Why this sidesteps the v5 dead end: it needs zero new external data. Its
only inputs are columns already written to signal_log by v1/v4 + a ground
truth label that already exists once evaluate.py has been run once on that
data (outcome_Xh == "CORRECT"/"WRONG"). No new fetcher, no new API, no new
geo-blocking risk.

IMPORTANT — status as of this commit: NOT YET RUN AGAINST REAL DATA.
signal_log is a local, ephemeral SQLite table (see backtest/db.py) —
nothing persists between sessions, so there is no logged history sitting
in this repo to train on. Running this for real requires, in order, in
one session:
    1. backfill.py (or train_v4.py) to populate signal_log with v1/v4 rows
    2. evaluate.py --version v1  (and --version v4) to populate the
       outcome_Xh columns those rows need as a training label
    3. train_meta.py (this branch) to actually fit and report a number
No accuracy number is reported here or in train_meta.py's own output
because none has been produced. Per this project's standing rule: log
real numbers, including bad ones — never a placeholder pretending to be
one.
"""

import json

ENGINE_VERSION = "meta-v1"  # tags this module's own identity; the underlying BUY/SELL
                             # verdict and its own engine_version tag (v1 or v4) are left
                             # untouched — meta-labeling filters, it doesn't replace, the
                             # primary call.

# v1 rows carry rsi/ema_fast/ema_slow/momentum/vol_ratio/day_change (see scoring.py).
# v4 rows don't — it's a ratio z-score model (see scoring_v4.py) with a different sig
# dict shape, so those columns are NULL for v4 rows in signal_log. is_v1/is_v4 let the
# model use engine identity as a feature even when those columns are NULL, rather than
# silently treating a NULL as a 0 (0 momentum is a real value; NULL is "not applicable").
FEATURE_NAMES = [
    "confidence", "rsi_centered", "ema_spread", "momentum", "vol_ratio",
    "day_change", "reasons_count", "is_v1", "is_v4",
]


def build_features(row):
    """row: a sqlite3.Row (or dict) from signal_log, as returned by db.all_rows().
    Returns a fixed-length float vector in FEATURE_NAMES order. Missing
    (NULL) numeric fields — expected for v4 rows — are imputed to 0.0 only
    after the engine-identity flags already tell the model which regime
    it's in."""
    is_v1 = 1.0 if row["engine_version"] == "v1" else 0.0
    is_v4 = 1.0 if row["engine_version"] == "v4" else 0.0

    rsi = row["rsi"]
    rsi_centered = (rsi - 50.0) if rsi is not None else 0.0
    ema_spread = (
        (row["ema_fast"] - row["ema_slow"])
        if (row["ema_fast"] is not None and row["ema_slow"] is not None)
        else 0.0
    )
    momentum = row["momentum"] if row["momentum"] is not None else 0.0
    vol_ratio = row["vol_ratio"] if row["vol_ratio"] is not None else 1.0
    day_change = row["day_change"] if row["day_change"] is not None else 0.0

    try:
        reasons_count = float(len(json.loads(row["reasons"] or "[]")))
    except (TypeError, ValueError):
        reasons_count = 0.0

    return [
        float(row["confidence"]), rsi_centered, ema_spread, momentum,
        vol_ratio, day_change, reasons_count, is_v1, is_v4,
    ]


def build_label(row, horizon="1h"):
    """Ground truth for meta-labeling: did the PRIMARY (v1/v4) signal's own
    verdict turn out correct? Reuses evaluate.py's own CORRECT/WRONG
    grading — this module never re-derives correctness itself, to avoid
    two separate, potentially-diverging definitions of "correct" existing
    in the same project. Returns None if evaluate.py hasn't graded this
    row yet (outcome column still NULL) — caller must filter these out
    before training, never impute a label for an outcome that isn't
    known."""
    outcome = row[f"outcome_{horizon}"]
    if outcome is None:
        return None
    return 1.0 if outcome == "CORRECT" else 0.0


def decide(proba, act_threshold=0.5):
    """proba: meta-model's estimated probability the primary signal is
    correct. Returns 'ACT' or 'SKIP'. act_threshold is deliberately left
    at a neutral 0.5 rather than pre-tuned — this branch has not yet run
    against real data, so there's no real basis yet for picking a
    threshold above/below 0.5; tune only against an actual walk-forward
    result, never in the abstract."""
    return "ACT" if proba >= act_threshold else "SKIP"
