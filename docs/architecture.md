# TradeAssist AI — Architecture for a Real Company

Built to survive past a demo: modular, ownable IP, room to raise money or bootstrap revenue, and legally sane from day one.

---

## 1. Core principle: separate the moat from the shell

Right now the whole app is one file. A company needs a clear line between:
- **The shell** (UI, auth, billing) — replaceable, low-value
- **The moat** (signal engine, backtested track record, proprietary data) — this is the actual asset

Everything below is designed around protecting that separation.

---

## 2. System architecture

```
┌─────────────────────────────────────────────────────────┐
│  CLIENT (Next.js / React, deployed on Vercel)            │
│  - Dashboard, charts, journal UI                         │
│  - Auth (Clerk/Supabase Auth)                            │
│  - Talks ONLY to your own API — never to Binance directly │
└───────────────────────┬───────────────────────────────────┘
                         │ HTTPS (your API)
┌───────────────────────▼───────────────────────────────────┐
│  API LAYER (Node/TypeScript, Vercel Functions or Fastify   │
│  on Railway/Render)                                        │
│  - /prices  /signals  /journal  /news  /backtest            │
│  - Rate limiting, auth checks, request validation           │
└──────┬───────────────┬───────────────┬─────────────────────┘
       │               │               │
┌──────▼─────┐  ┌───────▼──────┐  ┌─────▼──────────┐
│ MARKET DATA │  │ SIGNAL ENGINE│  │ NEWS/SENTIMENT  │
│ SERVICE     │  │ (your IP)    │  │ SERVICE         │
│ - Binance   │  │ - Indicators │  │ - GDELT + real  │
│   ingestion │  │ - Scoring    │  │   NLP sentiment │
│ - Caches to │  │ - Backtester │  │   (small LLM or │
│   Postgres/ │  │ - Logs every │  │   HF model)     │
│   Redis     │  │   call+result│  │                 │
└──────┬─────┘  └───────┬──────┘  └─────┬──────────┘
       │                │               │
       └────────────────▼───────────────┘
              ┌────────────────────┐
              │ POSTGRES (Supabase/│
              │ Neon) — source of  │
              │ truth               │
              │ - users, trades     │
              │ - price history     │
              │ - signal_log table  │
              │   (verdict, conf,   │
              │   outcome, ts)      │
              └────────────────────┘
```

**Why a backend now, not later:** the CORS-proxy-to-Binance trick in v1 can't survive real users — it's rate-limited and unowned. A backend also lets you own historical data, which is the raw material for the single most valuable thing you can build: **a verifiable track record.**

---

## 3. The signal engine as a real product, not a script

This is your actual IP. Structure it as an isolated package (own repo or `/packages/signal-engine` in a monorepo) with a clean interface:

```
signal-engine/
  indicators/     (rsi, ema, macd, bollinger, atr...)
  scoring/        (the weighted model — versioned: v1, v2...)
  backtest/       (replay historical data, measure hit rate)
  types.ts
```

Every signal it emits gets **logged with a timestamp and later checked against what actually happened.** That log is what turns "an app" into "a company with evidence." Investors, users, and your own admissions story all care about the same number: *what's the win rate, and can you prove it.*

Version your scoring model (v1, v2, v3) so you can A/B test changes and never lose the ability to say "here's what changed and why it got better."

---

## 4. Data you should start owning immediately

- **signal_log**: every verdict, confidence, inputs, and — 1h/4h/24h later — the actual price move. This is your backtestable dataset and eventually your credibility asset.
- **user_trades**: anonymized in aggregate, this becomes a second dataset (do real traders using your signals outperform?).
- Store both in Postgres from day one, even before you have real users — backfill from historical klines.

---

## 5. Stack recommendation (buildable solo, from a phone/tablet)

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js on Vercel | Free tier, StackBlitz-compatible, you already know the ecosystem |
| Backend | Vercel Functions (start) → Railway/Fly.io (scale) | No infra to manage early on |
| DB | Supabase (Postgres + auth + storage in one) | Free tier, works from mobile dashboard, auth built in |
| Signal engine | TypeScript package, unit-tested | Portable — can move off Vercel later without rewrite |
| News/sentiment | GDELT for headlines + a hosted small LLM (or even Claude/GPT API) for real sentiment scoring instead of keyword matching | Cheap, dramatically better than string-matching |
| Monitoring | Vercel Analytics + a simple `/status` page | Cheap credibility signal |

---

## 6. Legal/compliance — the part most student projects skip

Since this touches financial signals:
- **Add a clear disclaimer**: "not financial advice, educational/informational tool only" — visible in-app, not buried.
- If you ever take money or give personalized advice, you cross into regulated territory (investment advisor rules vary by country — India's SEBI, US SEC, etc.). Early stage as an "informational tool," you're likely fine, but this is worth a real lawyer conversation once you have paying users, not before.
- Keep this in mind now so the architecture doesn't box you out of it later (e.g., logging user consent, versioning your disclaimers).

---

## 7. Roadmap if this becomes "the company"

**Phase 1 (now — proof):** Backend + signal_log + backtest report. Goal: produce one honest number — "our signals were right X% of the time over Y months" — even if it's mediocre. Truth here matters more than a good-looking number.

**Phase 2 (users):** Auth, multi-device sync, real sentiment model, public backtest dashboard.

**Phase 3 (business):** Pick a wedge — paid signal alerts, a Pro tier with more assets/indicators, or an API for other builders. Don't try to monetize before Phase 1's number exists; it's your only real sales pitch.

**Phase 4 (identity):** Register the entity once there's real usage or revenue (in India: an LLP or Pvt Ltd once you're past hobby scale) — no rush to do this before Phase 1-2 are real.

---

## The one thing to internalize

The old repo was a well-built *demo*. The difference between a demo and a company is **a number you can defend** — a logged, versioned, backtested track record. Everything in this architecture exists to produce that number as early and honestly as possible.
