# Zuvarik AI — Research Scoreboard

**Rule: never overwrite a row once it's logged.** Each row is one real,
reproducible experiment against real data. This table is the project's
control group — if a later experiment looks better, it gets a new row, not
an edit to an old one. Append-only, same principle as `signal_log` itself.

All bps figures are **net expectancy per trade, after realistic costs**
(via `trade_simulator.py`), not raw directional accuracy — see
`results/trade_simulator_findings.md` for why that distinction matters.

| # | Experiment | Window | n trades | Net expectancy | OOS? | Notes |
|---|---|---|---|---|---|---|
| 1 | v4 baseline (std 2-leg taker fees) | 30d (window A) | 10,392 | **-55.0 bps** | ✓ real data | Standard execution cost assumption |
| 2 | v4 baseline (single-leg, edge-matched target) | 30d (window A) | 10,392 | **-1.7 bps** | ✓ real data | Near-breakeven; single-leg execution + 0.15% TP/SL |
| 3 | v4 baseline (single-leg, edge-matched target) | 30d (window B, later) | 10,411 | **-7.75 bps** (weighted avg across z-buckets, see #4) | ✓ real data | **Same exact config as #2, different calendar window — result is NOT stable across time.** Flagged, not resolved. |
| 4 | + z-score magnitude filter | 30d (window B) | z∈[1.5,2.0): 5,990 / [2.0,2.5): 2,785 / [2.5,3.0): 1,062 / [3.0,∞): 574 | -8.14 / -7.25 / -7.22 / -7.15 bps | ✓ real data | Qualitative pattern holds (higher \|z\| → better expectancy) but magnitude of improvement (~1bp) is much smaller than hoped, and every bucket is still net-negative in this window |

## Open, unresolved before trusting any of the above

**Row 3 is the most important open problem right now, not row 4.** The
exact same strategy and cost assumptions produced -1.7 bps in one 30-day
window and -7.75 bps (weighted) in another, non-overlapping window shortly
after. This means:
- Either the earlier -1.7 bps result was itself a lucky window, or
- Real market conditions shifted enough between the two windows to matter
  a lot, or both.

Either way, **no single-window result (including the promising -1.7 bps
one) should be treated as reliable until this variance is understood.**
This is a prerequisite for trusting rows 4+ too, not a separate problem —
the whole scoreboard rests on knowing how much window-to-window noise to
expect.

## Next rows queued (Tier 1, per the roadmap)

- Volatility regime conditioning (assigned: Device 2)
- MFE/MAE excursion analysis (assigned: Device 3)
- Entry timing variants (queued, unassigned)
- Repeat rows 2-4 across several more independent windows to characterize
  the variance found in row 3, before adding anything else
