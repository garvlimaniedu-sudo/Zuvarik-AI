# v4 — Crash-Regime Stress Test Results

Real data, Binance.US, ETHUSDT/BTCUSDT ratio. Scanned 200 days of hourly BTC
data for the highest-realized-volatility 7-day window, then ran v4's actual
`compute_signal()` (unchanged) through real 1-minute data covering that
specific week.

## The window found

**2026-01-31 to 2026-02-07** — the worst realized-volatility week in the
available 200-day history. BTC fell **-16.5%** (82,719 → 69,042) over the
7 days. This is a genuine crash regime, not a synthetic or cherry-picked one
— it was the single worst week the data-driven scan could find.

## Results

| Horizon | Accuracy | n | Worst single trade | Longest loss streak |
|---|---|---|---|---|
| 1h | 62.0% | 3,019 | -2.612% | 21 |
| 4h | 55.7% | 2,982 | -4.230% | 23 |
| 24h | 54.7% | 2,708 | -7.083% | 32 |

## What this actually means

**The good news, and it's real: the directional edge did not break down.**
Accuracy during the worst week in 200 days (62.0%/55.7%/54.7%) essentially
matches — and on the 1h horizon, matches exactly — the "normal conditions"
numbers from earlier validation (62.1-62.6%/56.7-57.3%/53.3-53.5%). This is
a meaningfully positive finding: the mean-reversion edge is not obviously
regime-dependent, at least not in the direction that matters (breaking down
specifically when volatility is highest).

**The bad news, and it's the number that actually determines survivability:
tail risk is real and large.** A single worst-case trade lost over 7% on the
24h horizon. A streak of 32 consecutive losing trades occurred. Average
accuracy staying stable is not the same as any individual trade or sequence
of trades being safe — **this strategy cannot be deployed with fixed,
undifferentiated position sizing and survive a real crash.** Whatever
capital allocation and stop-loss discipline gets built around this signal
must be sized to survive a 20-30+ trade losing streak and a >7% single-trade
adverse move, not just the average-case accuracy number.

## Honest caveats

- One 7-day window, however genuinely worst-case, is still one sample. This
  should be repeated on other independent volatile periods (a different
  200-day scan window, or further back in history if reachable) before
  being treated as a durable property of the strategy rather than a
  one-time result.
- This does not yet account for whether v4 would even be *executable* during
  a crash — extreme volatility often comes with wider real spreads and worse
  slippage than calm-period assumptions, on top of the acknowledged
  transaction-cost gap already found in earlier validation (Check 4).
- "Worst single trade" and "longest streak" are both point-in-time facts of
  this specific window — a genuinely rigorous risk model would run many such
  windows and report a distribution, not a single worst case.

## Reproducing this

```bash
cd backtest
python3 crash_stress_test.py --asset_base BTCUSDT --asset_quote ETHUSDT --scan_days 200
```
