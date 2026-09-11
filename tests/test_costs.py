from dataclasses import replace

from aitrading.config import EURUSD, XAUUSD
from aitrading.costs import breakeven_move, cost_to_vol_ratio, execute, financing


def test_costs_are_always_adverse():
    buy = execute(XAUUSD, 3500.0, +0.10)
    sell = execute(XAUUSD, 3500.0, -0.10)
    assert buy.executed_price > 3500.0
    assert sell.executed_price < 3500.0
    assert buy.total > 0 and sell.total > 0


def test_zero_trade_costs_nothing():
    f = execute(XAUUSD, 3500.0, 0.0)
    assert f.total == 0.0 and f.executed_price == 3500.0


def test_cost_scales_linearly_with_size():
    small = execute(XAUUSD, 3500.0, 0.10).total
    big = execute(XAUUSD, 3500.0, 1.00).total
    assert abs(big - 10.0 * small) < 1e-9


def test_breakeven_move_matches_hand_calculation():
    """XAUUSD: edge = 0.10 + 0.05 = 0.15/side -> 0.30 round trip.
    Per lot: 100 oz * 0.30 = $30 spread/slippage + 2 * $3.50 commission = $37.
    Divided by 100 oz -> 0.37 price units."""
    assert abs(breakeven_move(XAUUSD) - 0.37) < 1e-12


def test_cost_to_vol_ratio_matches_hand_calculation():
    r = cost_to_vol_ratio(XAUUSD, price=3500.0, daily_vol_fraction=0.012)
    assert abs(r - 0.37 / (3500.0 * 0.012)) < 1e-12
    assert 0.008 < r < 0.009


def test_gold_beats_eurusd_on_cost_per_unit_opportunity():
    """The reason we chose XAUUSD: wider spread, but far more volatility."""
    gold = cost_to_vol_ratio(XAUUSD, 3500.0, 0.012)
    eur = cost_to_vol_ratio(EURUSD, 1.10, 0.0055)
    assert gold < eur


def test_financing_sign_and_scaling():
    long_cost = financing(XAUUSD, +1.0, 3500.0, bar_hours=24.0)
    short_cost = financing(XAUUSD, -1.0, 3500.0, bar_hours=24.0)
    assert long_cost > 0 and short_cost > 0
    assert long_cost > short_cost  # long gold financing is dearer in the spec
    assert abs(financing(XAUUSD, 0.0, 3500.0, 24.0)) == 0.0
    two_bars = financing(XAUUSD, 1.0, 3500.0, bar_hours=48.0)
    assert abs(two_bars - 2.0 * long_cost) < 1e-9


def test_zero_cost_instrument_is_frictionless():
    free = replace(XAUUSD, half_spread=0.0, slippage=0.0,
                   commission_per_lot_per_side=0.0,
                   swap_long_annual=0.0, swap_short_annual=0.0)
    assert execute(free, 3500.0, 1.0).total == 0.0
    assert breakeven_move(free) == 0.0



def test_export_spans_allow_enough_intraday_history_to_resolve_an_edge():
    """M1/M5 caps must permit a testable span, not just a spread sample.

    Sharpe standard error is 1/sqrt(years), so a 3-month intraday sample (SE 2.0)
    cannot resolve any realistic edge. These caps were originally set on the
    assumption that intraday data existed only to measure spread; once M1/M5
    became the target trading timeframes, span became the binding constraint.
    """
    from aitrading.data.mt5_source import span_for

    assert span_for("D1", 15.0) == 15.0
    assert span_for("H4", 15.0) == 15.0
    # M5 must reach a span where a single pre-registered config is testable:
    # 2 years -> SE 0.71 -> significant at Sharpe ~1.4.
    assert span_for("M5", 15.0) >= 2.0
    assert span_for("M1", 15.0) >= 1.0
    assert span_for("M5", 0.25) == 0.25        # a smaller request is respected


def test_intraday_span_still_bounded_to_keep_files_manageable():
    """Unbounded M1 would be tens of millions of rows for no added precision."""
    from aitrading.data.mt5_source import span_for

    assert span_for("M1", 50.0) <= 1.0         # ~348k rows, ~20 MB
    assert span_for("M5", 50.0) <= 5.0
