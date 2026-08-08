-- signal_log: the core evidence table for Zuvarik AI.
-- Every signal the engine ever produces gets one row here, and gets
-- checked against what actually happened afterward. This table is
-- the entire Phase 1 goal.
--
-- Written in Postgres syntax (production target: Supabase/Neon).
-- Locally, db.py creates the SQLite-compatible equivalent so this
-- can be built and tested with zero external services.

CREATE TABLE IF NOT EXISTS signal_log (
    id              SERIAL PRIMARY KEY,
    asset           TEXT NOT NULL,              -- e.g. BTCUSDT
    signal_ts       TIMESTAMPTZ NOT NULL,        -- candle close time the signal was computed at
    engine_version  TEXT NOT NULL,               -- e.g. v1 — never edit a version once it has history
    verdict         TEXT NOT NULL,               -- BUY / SELL / HOLD / WAIT
    confidence      INTEGER NOT NULL,
    price_at_signal DOUBLE PRECISION NOT NULL,
    rsi             DOUBLE PRECISION,
    ema_fast        DOUBLE PRECISION,
    ema_slow        DOUBLE PRECISION,
    momentum        DOUBLE PRECISION,
    vol_ratio       DOUBLE PRECISION,
    day_change      DOUBLE PRECISION,
    news_bias       DOUBLE PRECISION,
    reasons         TEXT,                        -- JSON-encoded list of reason strings

    -- filled in later by evaluate.py once enough time has passed
    price_1h        DOUBLE PRECISION,
    price_4h        DOUBLE PRECISION,
    price_24h       DOUBLE PRECISION,
    outcome_1h      TEXT,                        -- CORRECT / WRONG / N-A
    outcome_4h      TEXT,
    outcome_24h     TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signal_log_asset_ts ON signal_log (asset, signal_ts);
CREATE INDEX IF NOT EXISTS idx_signal_log_version ON signal_log (engine_version);
