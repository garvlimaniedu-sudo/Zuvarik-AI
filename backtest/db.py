"""
Local dev database — SQLite, stdlib only, zero installs.
Same columns as backtest/schema.sql (Postgres). Swap this module for
a psycopg2/asyncpg connection when deploying; nothing else in the
pipeline needs to change since backfill.py and evaluate.py only call
these functions, never raw SQL directly.
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


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()
    conn.close()


def insert_signal(asset, signal_ts, sig, price_at_signal, news_bias=0.0):
    conn = get_conn()
    conn.execute(
        """INSERT INTO signal_log
        (asset, signal_ts, engine_version, verdict, confidence, price_at_signal,
         rsi, ema_fast, ema_slow, momentum, vol_ratio, day_change, news_bias, reasons)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            asset, signal_ts, sig["engine_version"], sig["verdict"], sig["confidence"],
            price_at_signal, sig.get("rsi"), sig.get("ema_fast"), sig.get("ema_slow"),
            sig.get("momentum"), sig.get("vol_ratio"), sig.get("day_change"),
            news_bias, json.dumps(sig.get("reasons", [])),
        ),
    )
    conn.commit()
    conn.close()


def fetch_unevaluated(horizon_col):
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM signal_log WHERE {horizon_col} IS NULL AND verdict IN ('BUY','SELL')"
    ).fetchall()
    conn.close()
    return rows


def update_outcome(row_id, horizon, price, outcome):
    conn = get_conn()
    conn.execute(
        f"UPDATE signal_log SET price_{horizon} = ?, outcome_{horizon} = ? WHERE id = ?",
        (price, outcome, row_id),
    )
    conn.commit()
    conn.close()


def all_rows():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM signal_log ORDER BY signal_ts").fetchall()
    conn.close()
    return rows
