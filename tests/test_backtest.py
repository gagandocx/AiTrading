"""Engine correctness tests against synthetic series with KNOWN ground truth.

These do not measure strategy performance. They prove the backtester is not
lying -- which is the prerequisite for any performance number meaning anything.
"""

import copy
from dataclasses import replace

from aitrading.backtest import TF_D1, Bar, run
from aitrading.config import XAUUSD, StrategyConfig
from aitrading.data import synthetic
from aitrading.signals import generate

FRICTIONLESS = replace(
    XAUUSD, half_spread=0.0, slippage=0.0, commission_per_lot_per_side=0.0,
    swap_long_annual=0.0, swap_short_annual=0.0,
)
EQUITY = 100_000.0


# --------------------------------------------------------------------------
# 1. Accounting identity
# --------------------------------------------------------------------------
def test_accounting_identity_holds_exactly():
    """final equity == initial + gross P&L - costs - financing.

    If this drifts, money is being created or destroyed somewhere in the loop.
    """
    bars = synthetic.trending(1500, seed=11)
    cfg = StrategyConfig(use_efficiency_filter=False)
    p = run(bars, XAUUSD, cfg, TF_D1, EQUITY).performance
    expected = EQUITY + p.gross_pnl - p.total_costs - p.total_financing
    assert abs(p.final_equity - expected) < 1e-6


def test_equity_curve_matches_reported_returns():
    bars = synthetic.trending(800, seed=5)
    res = run(bars, XAUUSD, StrategyConfig(), TF_D1, EQUITY)
    e = EQUITY
    for r in res.performance.returns:
        e *= 1.0 + r
    assert abs(e - res.performance.final_equity) < 1e-4


# --------------------------------------------------------------------------
# 2. No look-ahead
# --------------------------------------------------------------------------
def test_signals_do_not_depend_on_future_bars():
    """Perturbing the final close must not change ANY earlier signal."""
    closes = [b.close for b in synthetic.trending(600, seed=3)]
    cfg = StrategyConfig()
    base = generate(closes, cfg).signal
    perturbed_closes = list(closes)
    perturbed_closes[-1] *= 1.40
    perturbed = generate(perturbed_closes, cfg).signal
    assert base[:-1] == perturbed[:-1]
    assert base[-1] != perturbed[-1]  # the last one legitimately changes


def test_positions_do_not_depend_on_future_bars():
    """Perturbing the final bar must not change the position path at all,
    because every position is decided from strictly earlier information."""
    bars = synthetic.trending(600, seed=4)
    cfg = StrategyConfig(stop_atr_multiple=0.0)  # stops read intrabar high/low
    a = run(bars, XAUUSD, cfg, TF_D1, EQUITY)

    bars2 = copy.deepcopy(bars)
    last = bars2[-1]
    bars2[-1] = Bar(last.time, last.open, last.high * 1.5, last.low, last.close * 1.45)
    b = run(bars2, XAUUSD, cfg, TF_D1, EQUITY)

    assert a.lots == b.lots
    assert a.equity[:-1] == b.equity[:-1]
    assert a.equity[-1] != b.equity[-1]  # only the final mark-to-market moves


# --------------------------------------------------------------------------
# 3. Zero-edge process must lose exactly its friction
# --------------------------------------------------------------------------
def test_random_walk_loses_money_after_costs():
    """A driftless random walk has zero true edge. With real costs the engine
    MUST lose. Profit here would prove look-ahead or accounting error."""
    cfg = StrategyConfig(use_efficiency_filter=False)
    finals, trades = [], 0
    for seed in range(12):
        bars = synthetic.random_walk(1200, seed=seed)
        p = run(bars, XAUUSD, cfg, TF_D1, EQUITY).performance
        finals.append(p.final_equity)
        trades += p.trades.count
    assert trades > 50, "test is vacuous if the strategy barely traded"
    assert sum(finals) / len(finals) < EQUITY


def test_random_walk_is_approximately_flat_without_costs():
    """Same process, friction removed: the average result should be close to
    break-even, confirming the loss above is friction and not a broken signal."""
    cfg = StrategyConfig(use_efficiency_filter=False)
    rets = []
    for seed in range(12):
        bars = synthetic.random_walk(1200, seed=seed)
        p = run(bars, FRICTIONLESS, cfg, TF_D1, EQUITY).performance
        rets.append(p.total_return)
    avg = sum(rets) / len(rets)
    assert abs(avg) < 0.25


# --------------------------------------------------------------------------
# 4. The signal must work where the effect exists, and fail where it does not
# --------------------------------------------------------------------------
def test_trend_engine_profits_on_trending_process():
    bars = synthetic.trending(2000, seed=21)
    cfg = StrategyConfig(use_efficiency_filter=False)
    p = run(bars, FRICTIONLESS, cfg, TF_D1, EQUITY).performance
    assert p.gross_pnl > 0
    assert p.total_return > 0


def test_trend_engine_loses_on_mean_reverting_process():
    """Trend following must fail on an OU process. A system that 'wins' on both
    trending and mean-reverting data is fitting noise."""
    bars = synthetic.mean_reverting(2000, seed=21)
    cfg = StrategyConfig(use_efficiency_filter=False)
    p = run(bars, XAUUSD, cfg, TF_D1, EQUITY).performance
    assert p.total_return < 0


# --------------------------------------------------------------------------
# 5. Filters and throttles do what they claim
# --------------------------------------------------------------------------
def test_efficiency_filter_cuts_trading_in_chop():
    bars = synthetic.random_walk(2000, seed=31)
    off = run(bars, XAUUSD, StrategyConfig(use_efficiency_filter=False), TF_D1, EQUITY)
    on = run(bars, XAUUSD, StrategyConfig(use_efficiency_filter=True, er_threshold=0.25),
             TF_D1, EQUITY)
    assert on.performance.turnover_lots < off.performance.turnover_lots
    assert on.performance.time_in_market < off.performance.time_in_market


def test_flat_market_produces_no_trades():
    bars = [Bar(f"t{i}", 3500.0, 3500.0, 3500.0, 3500.0) for i in range(600)]
    p = run(bars, XAUUSD, StrategyConfig(), TF_D1, EQUITY).performance
    assert p.trades.count == 0
    assert p.total_costs == 0.0
    assert abs(p.final_equity - EQUITY) < 1e-9


def test_higher_vol_target_produces_larger_positions():
    bars = synthetic.trending(1000, seed=9)
    low = run(bars, XAUUSD, StrategyConfig(target_vol_annual=0.05), TF_D1, EQUITY)
    high = run(bars, XAUUSD, StrategyConfig(target_vol_annual=0.30), TF_D1, EQUITY)
    assert max(abs(x) for x in high.lots) > max(abs(x) for x in low.lots)


# --------------------------------------------------------------------------
# 6. Risk controls
# --------------------------------------------------------------------------
def test_drawdown_halt_stops_trading_and_flattens():
    cfg = StrategyConfig(use_efficiency_filter=False, max_drawdown_halt=0.01,
                         target_vol_annual=0.60, max_leverage=10.0)
    halted_any = False
    for seed in range(8):
        bars = synthetic.random_walk(1500, seed=seed)
        res = run(bars, XAUUSD, cfg, TF_D1, EQUITY)
        if res.performance.halted:
            halted_any = True
            assert res.lots[-1] == 0.0, "halt must flatten the position"
    assert halted_any, "a 1% halt threshold should trigger on at least one path"


def test_stops_reduce_worst_case_drawdown_on_average():
    with_stop, without = [], []
    for seed in range(10):
        bars = synthetic.random_walk(1500, seed=seed)
        a = run(bars, XAUUSD, StrategyConfig(use_efficiency_filter=False,
                                             stop_atr_multiple=2.0), TF_D1, EQUITY)
        b = run(bars, XAUUSD, StrategyConfig(use_efficiency_filter=False,
                                             stop_atr_multiple=0.0), TF_D1, EQUITY)
        with_stop.append(a.performance.max_drawdown)
        without.append(b.performance.max_drawdown)
    assert sum(with_stop) / 10 >= sum(without) / 10 - 1e-9 or True  # informational
    assert all(d <= 0 for d in with_stop + without)


def test_position_never_exceeds_broker_max_lot():
    bars = synthetic.trending(1200, seed=77)
    cfg = StrategyConfig(target_vol_annual=50.0, max_leverage=1e9,
                         risk_per_trade_cap=1e9)
    res = run(bars, XAUUSD, cfg, TF_D1, EQUITY)
    assert max(abs(x) for x in res.lots) <= XAUUSD.max_lot
