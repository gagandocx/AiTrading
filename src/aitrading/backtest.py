"""Event-driven backtest engine.

Correctness rules enforced here, in priority order:

1. NO LOOK-AHEAD. The signal at bar i uses closes up to bar i. It is executed at
   the OPEN of bar i+1. There is no path by which a decision sees its own bar.
2. Costs are charged on every position change, always adverse.
3. Financing is charged for every bar a position is held.
4. Intrabar stop fills assume the worst case: the stop is hit before any
   favourable excursion within the bar.

The random-walk test in tests/test_backtest.py exists specifically to catch
violations of rule 1 -- on a driftless random walk, this engine must LOSE
approximately its cost drag. A backtester that profits there is broken.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

from . import costs as cost_model
from .config import Instrument, StrategyConfig
from .indicators import atr
from .metrics import Performance, TradeStats
from .signals import generate


@dataclass
class Bar:
    time: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class Timeframe:
    name: str
    bar_hours: float
    bars_per_year: float


# Gold and FX trade roughly 23h/day, 5 days/week -> ~252 trading days.
TF_D1 = Timeframe("D1", 24.0, 252.0)
TF_H4 = Timeframe("H4", 4.0, 252.0 * 6)
TF_H1 = Timeframe("H1", 1.0, 252.0 * 23)
TF_M15 = Timeframe("M15", 15.0 / 60.0, 252.0 * 92)
TF_M5 = Timeframe("M5", 5.0 / 60.0, 252.0 * 276)
TF_M1 = Timeframe("M1", 1.0 / 60.0, 252.0 * 1380)
TIMEFRAMES = {"D1": TF_D1, "H4": TF_H4, "H1": TF_H1,
              "M15": TF_M15, "M5": TF_M5, "M1": TF_M1}


@dataclass
class BacktestResult:
    performance: Performance
    lots: List[float]
    signal: List[Optional[float]]
    equity: List[float]


def run(
    bars: Sequence[Bar],
    inst: Instrument,
    cfg: StrategyConfig,
    tf: Timeframe,
    initial_equity: float = 10_000.0,
) -> BacktestResult:
    n = len(bars)
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    sig = generate(closes, cfg)
    atr_series = atr(highs, lows, closes, cfg.atr_window) if cfg.stop_atr_multiple > 0 else [None] * n

    from .sizing import should_rebalance, target_lots  # local import: avoids cycle

    equity = initial_equity
    peak_equity = initial_equity
    lots = 0.0
    last_traded_signal = 0.0
    stop_price: Optional[float] = None
    entry_price: Optional[float] = None
    open_trade_pnl = 0.0
    halted = False

    perf = Performance(
        bars_per_year=tf.bars_per_year,
        initial_equity=initial_equity,
        trades=TradeStats(),
    )
    perf.equity_curve.append(equity)
    lots_hist: List[float] = [0.0]

    def close_trade(pnl: float) -> None:
        perf.trades.count += 1
        if pnl >= 0:
            perf.trades.wins += 1
            perf.trades.gross_profit += pnl
        else:
            perf.trades.losses += 1
            perf.trades.gross_loss += abs(pnl)

    for i in range(1, n):
        bar = bars[i]
        prev_close = closes[i - 1]
        equity_at_bar_start = equity

        # --- 1. financing on the position carried into this bar ---------------
        fin = cost_model.financing(inst, lots, prev_close, tf.bar_hours)
        equity -= fin
        perf.total_financing += fin

        # --- 2. P&L on the carried position from prev close to this open ------
        lots_before = lots
        seg_a = lots_before * inst.contract_size * (bar.open - prev_close)
        equity += seg_a
        perf.gross_pnl += seg_a
        open_trade_pnl += seg_a

        # --- 3. decide and execute at THIS bar's open, using bar i-1's signal -
        s = sig.signal[i - 1]
        v = sig.vol_per_bar[i - 1]
        txn = 0.0

        # Session gating. Applied here, not in the signal, because it depends on
        # bar timestamps rather than price. Forces flat outside the permitted
        # window and before the daily rollover, which is the direct test of
        # whether overnight financing is the binding cost.
        session_ok = True
        if cfg.close_before_rollover or cfg.session_hours != (0, 24):
            hour = _bar_hour(bar.time)
            if hour is not None:
                lo, hi = cfg.session_hours
                if not (lo <= hour < hi):
                    session_ok = False
                if cfg.close_before_rollover and hour >= cfg.rollover_hour:
                    session_ok = False

        if halted or not session_ok:
            desired = 0.0
        elif s is None or v is None:
            desired = lots_before
        else:
            desired = target_lots(
                signal=s,
                vol_per_bar=v,
                bars_per_year=tf.bars_per_year,
                equity=equity,
                price=bar.open,
                inst=inst,
                cfg=cfg,
            )
            if not should_rebalance(lots_before, desired, s, last_traded_signal, cfg):
                desired = lots_before

        if desired != lots_before:
            delta = desired - lots_before
            fill = cost_model.execute(inst, bar.open, delta)
            txn = fill.total
            equity -= txn
            perf.total_costs += txn
            perf.turnover_lots += abs(delta)

            crossing_zero = lots_before != 0 and (desired == 0 or lots_before * desired < 0)
            if crossing_zero:
                close_trade(open_trade_pnl - txn)
                open_trade_pnl = 0.0
            if desired != 0 and (lots_before == 0 or lots_before * desired < 0):
                entry_price = fill.executed_price
                if cfg.stop_atr_multiple > 0 and atr_series[i - 1]:
                    a = atr_series[i - 1]
                    stop_price = (
                        entry_price - cfg.stop_atr_multiple * a
                        if desired > 0
                        else entry_price + cfg.stop_atr_multiple * a
                    )
                else:
                    stop_price = None
            elif desired == 0:
                stop_price = None
                entry_price = None

            lots = desired
            if s is not None:
                last_traded_signal = s

        # --- 4. intrabar stop check (worst case: stop before favourable move) --
        stopped = False
        if lots != 0 and stop_price is not None:
            hit = (lots > 0 and bar.low <= stop_price) or (lots < 0 and bar.high >= stop_price)
            if hit:
                exit_ref = stop_price
                seg_b = lots * inst.contract_size * (exit_ref - bar.open)
                equity += seg_b
                perf.gross_pnl += seg_b
                open_trade_pnl += seg_b

                fill = cost_model.execute(inst, exit_ref, -lots)
                equity -= fill.total
                perf.total_costs += fill.total
                perf.turnover_lots += abs(lots)
                close_trade(open_trade_pnl - fill.total)

                open_trade_pnl = 0.0
                lots = 0.0
                stop_price = None
                entry_price = None
                last_traded_signal = 0.0
                stopped = True

        # --- 5. mark to market from open to close ----------------------------
        if not stopped:
            seg_b = lots * inst.contract_size * (bar.close - bar.open)
            equity += seg_b
            perf.gross_pnl += seg_b
            open_trade_pnl += seg_b

        if lots != 0:
            perf.bars_in_market += 1

        # --- 6. drawdown circuit breaker --------------------------------------
        peak_equity = max(peak_equity, equity)
        if cfg.max_drawdown_halt > 0 and peak_equity > 0:
            if equity / peak_equity - 1.0 <= -cfg.max_drawdown_halt:
                halted = True

        ret = (equity / equity_at_bar_start - 1.0) if equity_at_bar_start > 0 else 0.0
        perf.returns.append(ret)
        perf.equity_curve.append(equity)
        lots_hist.append(lots)
        perf.bars += 1

    if lots != 0:
        close_trade(open_trade_pnl)

    perf.final_equity = equity
    perf.halted = halted
    return BacktestResult(
        performance=perf, lots=lots_hist, signal=sig.signal, equity=perf.equity_curve
    )



def _bar_hour(timestamp: str) -> Optional[int]:
    """Extract the hour from a 'YYYY-MM-DD HH:MM:SS' bar timestamp.

    Returns None for synthetic bars (e.g. 't1', 't2') so session gating is simply
    inert on generated data rather than raising.
    """
    try:
        return int(timestamp.split(" ")[1].split(":")[0])
    except (IndexError, ValueError):
        return None
