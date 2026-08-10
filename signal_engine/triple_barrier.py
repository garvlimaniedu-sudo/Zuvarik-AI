"""
Triple-barrier labeling (standard technique from quantitative finance —
Lopez de Prado's "Advances in Financial Machine Learning").

v1/v2's evaluate.py only checks "where's the price at exactly +60min,"
completely ignoring the path taken to get there. A trade could spike to a
real stop-loss and back within that hour and we'd never know. Triple-barrier
fixes this: walk forward candle by candle from the entry point and ask which
of three barriers gets hit first —
  - upper barrier (take-profit level) -> label 1 (bullish outcome)
  - lower barrier (stop-loss level)   -> label 0 (bearish outcome)
  - time barrier (max_hold candles pass with neither hit) -> label None
    (ambiguous/timeout — excluded from training, not force-labeled)

This produces a training target that reflects what an actual trade would
experience, not just a snapshot at a fixed horizon.
"""


def label_triple_barrier(candles, entry_idx, tp_pct=0.003, sl_pct=0.003, max_hold=30):
    """
    candles: full OHLC list. entry_idx: index of the entry candle (uses its close).
    tp_pct/sl_pct: barrier distance as a fraction of entry price (0.003 = 0.3%).
    max_hold: max candles to look forward before declaring a timeout.

    Returns (label, resolved_idx). label is 1 (TP hit first), 0 (SL hit first),
    or None (timed out — caller should exclude this example from training).
    """
    entry_price = candles[entry_idx]["close"]
    tp_level = entry_price * (1 + tp_pct)
    sl_level = entry_price * (1 - sl_pct)
    end_idx = min(entry_idx + max_hold, len(candles) - 1)

    for j in range(entry_idx + 1, end_idx + 1):
        c = candles[j]
        hit_tp = c["high"] >= tp_level
        hit_sl = c["low"] <= sl_level
        if hit_tp and hit_sl:
            # both barriers touched within the same candle — can't tell which
            # came first from OHLC alone, so take the conservative assumption
            return 0, j
        if hit_tp:
            return 1, j
        if hit_sl:
            return 0, j

    return None, end_idx
