"""
Local dev database — SQLite, stdlib only, zero installs.
Same columns as backtest/schema.sql (Postgres). Swap this module for
a psycopg2/asyncpg connection when deploying; nothing else in the
pipeline needs to change since backfill.py and evaluate.py only call
these functions, never raw SQL directly.

Perf note: insert_signal/update_outcome used to open+commit+close a fresh
sqlite3 connection on every single call. At 90-day scale (100k+ candles,
40-50k BUY/SELL rows x 3 horizons) that was the dominant cost of a run
(~15 min observed) even though the actual logic is trivial. This module now
keeps one process-wide connection open, wraps writes in an explicit
transaction, and batches inserts/updates via executemany so a full run's
worth of writes cost one commit instead of tens of thousands of them.
Call db.close() when a script is done (backfill.py / confirm_pipeline.py /
evaluate.py all do this) so the WAL/journal gets flushed cleanly.
"""

import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "zuvarik_local.db")

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset           TEXT NOT NULL,
    signal_ts       TEXT NOT NULL,
    engine_version  TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    confidence      INTEGER NOT NULL,
    price_at_signal REAL NOT NULL,
    rsi             REAL,
    ema_fast        REAL,
    ema_slow        REAL,
    momentum        REAL,
    vol_ratio       REAL,
    day_change      REAL,
    news_bias       REAL,
    reasons         TEXT,
    price_1h        REAL,
    price_4h        REAL,
    price_24h       REAL,
    outcome_1h      TEXT,
    outcome_4h      TEXT,
    outcome_24h     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signal_log_asset_ts ON signal_log (asset, signal_ts);
"""

_conn = None
_pending_inserts = []   # buffered rows for insert_signal, flushed in batches
_INSERT_SQL = """INSERT INTO signal_log
    (asset, signal_ts, engine_version, verdict, confidence, price_at_signal,
     rsi, ema_fast, ema_slow, momentum, vol_ratio, day_change, news_bias, reasons)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
_BATCH_SIZE = 2000


def get_conn():
    """Returns the single shared connection, opening it on first use."""
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
        # WAL + relaxed sync: safe for a local backtest run (not a durability-
        # critical production ledger), and roughly an order of magnitude
        # faster for high write volume than the default rollback journal.
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def init_db():
    conn = get_conn()
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()


def insert_signal(asset, signal_ts, sig, price_at_signal, news_bias=0.0):
    """Buffers a row instead of writing immediately. Call flush_inserts() (or
    close()) to actually commit — backfill.py / confirm_pipeline.py do this
    automatically, but if you're scripting ad hoc, remember to flush."""
    _pending_inserts.append((
        asset, signal_ts, sig["engine_version"], sig["verdict"], sig["confidence"],
        price_at_signal, sig.get("rsi"), sig.get("ema_fast"), sig.get("ema_slow"),
        sig.get("momentum"), sig.get("vol_ratio"), sig.get("day_change"),
        news_bias, json.dumps(sig.get("reasons", [])),
    ))
    if len(_pending_inserts) >= _BATCH_SIZE:
        flush_inserts()


def flush_inserts():
    if not _pending_inserts:
        return
    conn = get_conn()
    conn.executemany(_INSERT_SQL, _pending_inserts)
    conn.commit()
    _pending_inserts.clear()


def fetch_unevaluated(horizon_col):
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM signal_log WHERE {horizon_col} IS NULL AND verdict IN ('BUY','SELL')"
    ).fetchall()
    return rows


def update_outcome(row_id, horizon, price, outcome):
    """Buffers an update instead of writing immediately, same batching
    strategy as insert_signal. evaluate.py flushes at the end of its run."""
    _pending_updates.setdefault(horizon, []).append((price, outcome, row_id))
    if sum(len(v) for v in _pending_updates.values()) >= _BATCH_SIZE:
        flush_updates()


_pending_updates = {}


def flush_updates():
    if not _pending_updates:
        return
    conn = get_conn()
    for horizon, rows in _pending_updates.items():
        conn.executemany(
            f"UPDATE signal_log SET price_{horizon} = ?, outcome_{horizon} = ? WHERE id = ?",
            rows,
        )
    conn.commit()
    _pending_updates.clear()


def all_rows():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM signal_log ORDER BY signal_ts").fetchall()
    return rows


def close():
    """Flush any buffered writes and close the connection. Safe to call even
    if nothing was buffered or the connection was never opened."""
    global _conn
    flush_inserts()
    flush_updates()
    if _conn is not None:
        _conn.close()
        _conn = None
