"""
v4: relative-value mean-reversion on the ETH/BTC price ratio.

Every prior version (v1/v2/v3) predicts one asset's own absolute direction.
This is a structurally different bet: correlated-asset price RATIOS tend to
have more persistent, mean-reverting statistical structure than either
asset's absolute price alone — this is the basic premise behind statistical
arbitrage / pairs trading. ETH and BTC are highly correlated (both move with
"crypto risk-on/risk-off" sentiment), but their ratio still wanders and
snaps back toward its own recent mean, which is a different, and
potentially more exploitable, kind of structure than absolute trend-following.

This module is intentionally asset-agnostic: it only ever sees a plain list
of ratio values (ETH close / BTC close, aligned by timestamp) — it has no
idea what the two underlying assets are. That keeps it reusable for any
future ratio pair (e.g. SOL/BTC, BNB/ETH) without modification.

Signal logic — a z-score mean-reversion rule, deliberately simple (this is
a first test of the *idea*, not a tuned model):
  z = (current_ratio - rolling_mean) / rolling_stddev, over a trailing window
  z stretched high (ratio unusually rich vs its own recent history) -> SELL
    the ratio (short ETH/BTC — i.e. expect BTC to outperform ETH from here)
  z stretched low (ratio unusually cheap) -> BUY the ratio (long ETH/BTC —
    expect ETH to outperform BTC from here)
  |z| below threshold -> HOLD, nothing unusual enough to act on

"BUY"/"SELL" here describe the ratio's expected direction, not a literal
single-asset trade instruction — evaluate.py's existing accuracy check
(does the value go up after a BUY, down after a SELL) applies unchanged
whether the underlying value is a price or a ratio.
"""

from .indicators import mean, stddev

ENGINE_VERSION = "v4"
ZSCORE_WINDOW = 24   # rolling window (in candles) used to compute the ratio's own recent mean/stddev
Z_ENTRY = 1.5        # |z| above this triggers a BUY/SELL call; below it, HOLD


def zscore(ratios):
    """ratios: trailing window of ETH/BTC close ratios, most recent last.
    Returns the z-score of the most recent value against the window's own
    mean/stddev (excluding no candle — the window itself defines "recent normal")."""
    if len(ratios) < 5:
        return 0.0
    m = mean(ratios)
    s = stddev(ratios) or 1e-9
    return (ratios[-1] - m) / s


def compute_signal(ratios):
    """ratios: trailing window of ETH/BTC ratio values (len >= ZSCORE_WINDOW
    for a meaningful read; shorter windows zero-fill toward HOLD)."""
    window = ratios[-ZSCORE_WINDOW:] if len(ratios) >= ZSCORE_WINDOW else ratios
    z = zscore(window)

    if z <= -Z_ENTRY:
        verdict = "BUY"   # ratio unusually cheap -> expect reversion upward
    elif z >= Z_ENTRY:
        verdict = "SELL"  # ratio unusually rich -> expect reversion downward
    else:
        verdict = "HOLD"

    confidence = max(48, min(97, round(50 + min(abs(z), 4) * 11)))

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasons": [f"ETH/BTC ratio z-score: {z:.2f} (window {len(window)})"],
        "zscore": round(z, 3),
        "ratio": round(ratios[-1], 6) if ratios else None,
        "engine_version": ENGINE_VERSION,
    }
