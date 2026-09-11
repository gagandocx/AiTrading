import math

from aitrading.metrics import (
    Performance, TradeStats, deflated_sharpe, expected_max_sharpe, mean, stdev,
)


def test_mean_and_stdev():
    assert abs(mean([1, 2, 3, 4]) - 2.5) < 1e-12
    assert abs(stdev([2, 4, 4, 4, 5, 5, 7, 9]) - 2.138089935299395) < 1e-9
    assert stdev([5.0]) == 0.0


def test_max_drawdown():
    p = Performance(equity_curve=[100, 110, 120, 130])
    assert p.max_drawdown == 0.0
    p2 = Performance(equity_curve=[100, 200, 100, 150])
    assert abs(p2.max_drawdown - (-0.5)) < 1e-12


def test_trade_stats_arithmetic():
    t = TradeStats(count=10, wins=3, losses=7, gross_profit=900.0, gross_loss=300.0)
    assert abs(t.win_rate - 0.3) < 1e-12
    assert abs(t.avg_win - 300.0) < 1e-12
    assert abs(t.avg_loss - (300.0 / 7)) < 1e-12
    assert abs(t.profit_factor - 3.0) < 1e-12
    assert abs(t.expectancy - 60.0) < 1e-12


def test_low_win_rate_can_still_be_highly_profitable():
    """The point made in the strategy doc, as an executable assertion:
    a 30% win rate with 7:1 payoff beats a 90% win rate with 1:9 payoff."""
    trend = TradeStats(count=100, wins=30, losses=70, gross_profit=30 * 700.0,
                       gross_loss=70 * 100.0)
    grid = TradeStats(count=100, wins=90, losses=10, gross_profit=90 * 100.0,
                      gross_loss=10 * 900.0)
    assert trend.win_rate < grid.win_rate
    assert trend.expectancy > grid.expectancy
    assert grid.expectancy == 0.0 or grid.expectancy < trend.expectancy


def test_sharpe_and_vol_are_annualised():
    rets = [0.001] * 300 + [-0.001] * 300
    p = Performance(bars=600, bars_per_year=252.0, returns=rets)
    sr = p.sharpe
    assert sr is not None and abs(sr) < 1e-9  # symmetric -> zero mean
    assert p.vol_annual is not None and p.vol_annual > 0


def test_sharpe_none_when_no_variance():
    p = Performance(bars=10, returns=[0.01] * 10)
    assert p.sharpe is None


def test_cost_accounting_ratios():
    p = Performance(bars=252, bars_per_year=252.0, initial_equity=10_000.0,
                    final_equity=11_000.0, gross_pnl=2_000.0,
                    total_costs=800.0, total_financing=200.0)
    assert abs(p.cost_share_of_gross - 0.5) < 1e-12
    assert abs(p.cost_drag_annual - 0.1) < 1e-12


def test_noise_hurdle_grows_with_search_size():
    se = 0.2
    h10 = expected_max_sharpe(10, se)
    h1000 = expected_max_sharpe(1000, se)
    assert 0 < h10 < h1000


def test_deflated_sharpe_penalises_search():
    se = 0.2
    raw = 1.0
    assert deflated_sharpe(raw, 1, se) == raw
    d = deflated_sharpe(raw, 500, se)
    assert d < raw


def test_a_mediocre_sharpe_from_a_big_search_is_not_credible():
    """500 configs, 3 years of daily data, observed Sharpe 0.8 -> not credible."""
    p = Performance(bars=756, bars_per_year=252.0,
                    returns=[0.0005 + (0.01 if i % 2 else -0.01) for i in range(756)])
    se = p.sharpe_stderr
    assert se is not None
    assert deflated_sharpe(0.8, 500, se) < 0.8
