# Zuvarik AI

Live crypto market intelligence — built to prove itself, not just demo itself.

## What this is

Zuvarik AI tracks live crypto markets (BTC, ETH, BNB, SOL, XRP) and generates
BUY/SELL/HOLD signals from a transparent, rules-based engine: RSI, EMA
crossover, momentum, volume expansion, 24h change, and live news sentiment.
It also runs a trade journal with target/stop tracking and hold/exit coaching
based on the live signal.

None of that is new — it's the second generation of an earlier project,
**TradeAssist AI**, a single-file client-side dashboard that did all of this
live in the browser with zero backend. That version proved the idea works
as a demo. This one is being built to prove it works as evidence.

## What's different this time

The old version had no way to answer the one question that actually matters:
*is the signal engine right?* Every call disappeared the moment the page
refreshed. Zuvarik AI is built backend-first around a single principle —

> **Every signal gets logged. Every logged signal gets checked against what
> actually happened. The resulting win rate is the product's real pitch.**

## Architecture

```
client (Next.js)  →  API layer  →  signal engine (versioned, own package)
                                 →  market data service (owns its own cache)
                                 →  news/sentiment service
                        ↓
                   Postgres (signal_log, user_trades, price history)
```

Full architecture writeup: see `/docs/architecture.md` (ported from the
original planning doc).

## Current stage: Phase 1 — the backtester

Before any UI, auth, or users, the goal is one honest number: *signal
accuracy over N months of backtested data.* This repo currently contains:

- `signal_engine/` — the scoring model (v1, ported line-for-line from
  TradeAssist AI's `computeSignal()`), versioned so future changes can be
  compared against this baseline
- `backtest/schema.sql` — the `signal_log` table (Postgres), the core
  evidence table the whole company is built around
- `backtest/backfill.py` — replays historical klines through the engine,
  candle by candle, logging every signal
- `backtest/evaluate.py` — checks each logged signal against price 1h/4h/24h
  later and reports accuracy
- `backtest/db.py` — local SQLite dev mirror of the Postgres schema (stdlib
  only, zero installs, swapped for a real Postgres connection in production)

Run it locally:
```bash
cd backtest
python3 backfill.py --source binance --asset BTCUSDT --limit 1000
python3 evaluate.py --source binance --asset BTCUSDT --limit 1000
```
(`--source sample` generates synthetic data for offline pipeline testing —
never used for a real reported accuracy number.)

## Roadmap

1. **Signal log + backtester** *(current)* — produce one honest accuracy number
2. Backend + owned market data (kill client-side API calls)
3. Extract signal engine into its own tested package, version it properly
4. Rebuild the frontend against the new API
5. Real sentiment scoring (replace keyword matching)
6. Auth + persistent multi-device journal
7. Public backtest dashboard — the number becomes the pitch

## Disclaimer

Educational and informational only. Not financial advice.

---

Built by Garv Limani.
