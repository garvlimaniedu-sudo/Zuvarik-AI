"""
Realistic trade simulator for v4 (relative-value ETH/BTC).

Every prior evaluation of v4 asked "was the ratio's direction correct at a
fixed future timestamp" — that is NOT the same question as "could this
trade have made money." A directional-accuracy metric can call a trade
correct even if a realistic stop-loss would have closed it out at a loss
first (entry 100 -> 95 -> 101 "looks" like a winning BUY at the 101 checkpoint,
but a real trader with a stop-loss would have been stopped out at 95).

This module fixes that by simulating each trade properly:
  - explicit take-profit and stop-loss levels, checked every candle
  - a maximum holding period (timeout exit) if neither is hit
  - a TRUE intra-candle ratio range (not close-to-close), reconstructed
    from the two underlying assets' real highs/lows:
        ratio_high ~= quote_high / base_low   (the most the ratio could have reached)
        ratio_low  ~= quote_low  / base_high  (the least the ratio could have reached)
    This bounds the ratio's real intra-candle range correctly, since both
    assets move independently within their own candle.
  - realistic two-leg fees + slippage on both entry and exit (this trades
    two separate assets, not one, so costs are doubled versus a single-
    asset strategy)
  - same-candle TP/SL ambiguity resolved conservatively (SL-first) — see
    triple_barrier.py's docstring for the same reasoning applied here.

Reports real trading metrics, not just accuracy: win rate, average
win/loss, profit factor, expectancy per trade, max drawdown (running P&L),
and max consecutive losing streak — computed on NET (after cost) returns.
"""

from dataclasses import dataclass


@dataclass
class TradeResult:
    entry_idx: int
    verdict: str
    entry_ratio: float
    exit_idx: int
    exit_reason: str  # "TP", "SL", "TIMEOUT"
    gross_return_pct: float   # signed, in the trade's favor
    net_return_pct: float     # after fees + slippage


def ratio_high_low(base_candle, quote_candle):
    """True intra-candle bounds for quote/base, from each asset's own OHLC."""
    r_high = quote_candle["high"] / base_candle["low"] if base_candle["low"] else None
    r_low = quote_candle["low"] / base_candle["high"] if base_candle["high"] else None
    return r_high, r_low


def simulate_trade(entry_idx, verdict, base_candles, quote_candles,
                    tp_pct=0.006, sl_pct=0.006, max_hold=240,
                    fee_pct_per_leg=0.001, slippage_pct_per_leg=0.0005):
    """
    tp_pct/sl_pct default to 0.6% — wider than the earlier 0.3% tight-barrier
    test that collapsed to a coin flip; this is deliberately more realistic
    for a strategy meant to actually hold a position, not scalp micro-moves.
    fee_pct_per_leg defaults to Binance's standard 0.1% spot taker fee.
    Two legs (buying one asset, selling the other) means costs are doubled
    versus a single-asset trade — this is applied on both entry and exit.
    """
    entry_base = base_candles[entry_idx]
    entry_quote = quote_candles[entry_idx]
    entry_ratio = entry_quote["close"] / entry_base["close"]

    tp_level = entry_ratio * (1 + tp_pct) if verdict == "BUY" else entry_ratio * (1 - tp_pct)
    sl_level = entry_ratio * (1 - sl_pct) if verdict == "BUY" else entry_ratio * (1 + sl_pct)

    end_idx = min(entry_idx + max_hold, len(base_candles) - 1)
    exit_idx, exit_reason, exit_ratio = end_idx, "TIMEOUT", None

    for j in range(entry_idx + 1, end_idx + 1):
        r_high, r_low = ratio_high_low(base_candles[j], quote_candles[j])
        if r_high is None or r_low is None:
            continue

        if verdict == "BUY":
            hit_tp = r_high >= tp_level
            hit_sl = r_low <= sl_level
        else:  # SELL: profit if ratio falls
            hit_tp = r_low <= tp_level
            hit_sl = r_high >= sl_level

        if hit_tp and hit_sl:
            exit_idx, exit_reason, exit_ratio = j, "SL", sl_level  # conservative: SL-first
            break
        if hit_tp:
            exit_idx, exit_reason, exit_ratio = j, "TP", tp_level
            break
        if hit_sl:
            exit_idx, exit_reason, exit_ratio = j, "SL", sl_level
            break

    if exit_ratio is None:  # timed out — exit at the close of the final candle
        exit_ratio = quote_candles[end_idx]["close"] / base_candles[end_idx]["close"]

    signed_gross = ((exit_ratio / entry_ratio) - 1) * (1 if verdict == "BUY" else -1) * 100

    # two legs in, two legs out — fees+slippage apply on both entry and exit,
    # each touching two separate asset trades
    round_trip_cost_pct = 2 * (fee_pct_per_leg + slippage_pct_per_leg) * 2 * 100
    net = signed_gross - round_trip_cost_pct

    return TradeResult(entry_idx, verdict, entry_ratio, exit_idx, exit_reason, signed_gross, net)


def summarize(trades):
    if not trades:
        return {}
    net = [t.net_return_pct for t in trades]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    streak = maxstreak = 0
    for r in net:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
        if r <= 0:
            streak += 1
            maxstreak = max(maxstreak, streak)
        else:
            streak = 0

    gross_win = sum(wins) or 0
    gross_loss = abs(sum(losses)) or 1e-9

    return {
        "n_trades": len(trades),
        "win_rate_net": len(wins) / len(trades) * 100,
        "avg_win_net": sum(wins) / len(wins) if wins else 0,
        "avg_loss_net": sum(losses) / len(losses) if losses else 0,
        "expectancy_per_trade_net": sum(net) / len(net),
        "profit_factor": gross_win / gross_loss,
        "cumulative_net_return_pct": sum(net),
        "max_drawdown_pct": max_dd,
        "max_consecutive_losses": maxstreak,
        "exit_reason_counts": {
            r: sum(1 for t in trades if t.exit_reason == r) for r in ("TP", "SL", "TIMEOUT")
        },
    }
