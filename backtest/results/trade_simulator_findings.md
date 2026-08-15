# Real Trade Simulator Results — v4

Built `trade_simulator.py`: proper TP/SL/timeout exits, true intra-candle
ratio range (reconstructed from both assets' real highs/lows, not
close-to-close), realistic fees+slippage. Ran on real 30-day BTC/ETH data
(43,200 aligned 1m candles, 10,392 actionable signals).

## Three real runs, in order

**1. TP=SL=0.6%, standard two-leg taker fees (0.6% round-trip cost)**
Degenerate by accident — TP target happened to exactly equal round-trip
cost, so even "winning" trades netted to ~0%. Expectancy: -0.55%/trade.
Confirms nothing on its own (parameter coincidence), but 6,697/10,392 trades
timed out — first sign the real edge magnitude is much smaller than a 0.6%
target.

**2. TP=1.2%, SL=0.6% (2:1 reward:risk), same two-leg costs**
Only 363/10,392 trades (3.5%) hit TP at all — 8,362 timed out. This
independently confirms Device 2's finding from a completely different
method (real TP/SL execution, not fixed-horizon check): the ratio's actual
typical move is far smaller than a 1.2% target, so a wider target mostly
just times out instead of winning bigger. Expectancy: -0.56%/trade.

**3. TP=SL=0.15% (matched to the real edge's actual magnitude), single-leg
execution cost (0.06% round-trip — maker fee + minimal slippage, ONE pair
trade instead of two separate legs)**
**Expectancy: -0.017% per trade. 58.5% win rate. Nearly breakeven.**
5,597 TP / 2,756 SL / 2,039 timeout out of 10,392 signals.

## What this means

The strategy's core problem was never "wrong exit logic" alone (Device 2's
sweep already showed that) — it's that **standard two-leg taker-fee
execution costs (~0.6% round trip) are roughly 4-8x larger than the
strategy's real edge (~0.05-0.08% typical move)**. No amount of exit-timing
cleverness closes an 8x gap. But cutting execution costs toward single-leg,
maker-order economics AND sizing the profit target to match the edge's real
magnitude gets remarkably close — within 0.017 percentage points of
breakeven, not the wide gap seen at every setting in the wider TP/SL sweep.

**This is genuinely promising, not proof of a working strategy yet.** The
next real questions: does a real ETH/BTC direct-pair market exist with
enough liquidity to actually get maker fills near-continuously (see the
execution-cost research task); can meta-labeling filter to the subset of
signals where win rate is even a few points higher, which at this margin
would likely tip net expectancy positive; and this is one 30-day window —
needs the same treatment across more periods before trusting it.

## Reproducing this

The simulator is asset-agnostic — feed it any two candle series. See
`trade_simulator.py`'s docstring for the interface.
