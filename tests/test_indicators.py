import math

from aitrading.indicators import (
    atr, efficiency_ratio, ema, ewma_vol, log_returns, rolling_max, rolling_min, true_range,
)


def test_ema_preserves_constant():
    vals = [5.0] * 20
    out = ema(vals, halflife=5)
    assert len(out) == 20
    assert all(abs(v - 5.0) < 1e-12 for v in out)


def test_ema_halflife_is_exact():
    """After exactly `halflife` bars of a 0->1 step, the EMA must read 0.5.

    This is an analytic property of the parameterisation, so it pins down the
    alpha calculation rather than just checking it 'looks smooth'.
    """
    hl = 8
    vals = [0.0] + [1.0] * hl
    out = ema(vals, halflife=hl)
    assert abs(out[-1] - 0.5) < 1e-9


def test_log_returns_first_is_none_and_flat_is_zero():
    out = log_returns([10.0, 10.0, 10.0])
    assert out[0] is None
    assert all(abs(v) < 1e-15 for v in out[1:])


def test_ewma_vol_positive_and_aligned():
    closes = [100.0, 101.0, 99.5, 102.0, 98.0]
    out = ewma_vol(log_returns(closes), halflife=3)
    assert len(out) == len(closes)
    assert out[0] is None
    assert all(v is not None and v > 0 for v in out[1:])


def test_efficiency_ratio_is_one_for_pure_trend():
    """Monotonic series: net travel == total path travel, so ER == 1 exactly."""
    closes = [100.0 + i for i in range(40)]
    out = efficiency_ratio(closes, window=10)
    assert all(abs(v - 1.0) < 1e-12 for v in out[10:])


def test_efficiency_ratio_is_zero_for_pure_chop():
    """Zigzag returning to its start: net travel 0, so ER == 0."""
    closes = [100.0 if i % 2 == 0 else 101.0 for i in range(40)]
    out = efficiency_ratio(closes, window=10)
    assert all(abs(v) < 1e-12 for v in out[10:])


def test_efficiency_ratio_bounded():
    import random
    rng = random.Random(3)
    closes = [100.0]
    for _ in range(200):
        closes.append(closes[-1] * math.exp(rng.gauss(0, 0.01)))
    for v in efficiency_ratio(closes, window=20):
        if v is not None:
            assert -1e-12 <= v <= 1.0 + 1e-12


def test_true_range_and_atr_alignment():
    highs = [10, 11, 12, 11.5]
    lows = [9, 10, 11, 10.5]
    closes = [9.5, 10.5, 11.5, 11.0]
    tr = true_range(highs, lows, closes)
    assert tr[0] is None and len(tr) == 4
    a = atr(highs, lows, closes, window=2)
    assert len(a) == 4 and a[0] is None
    assert all(v > 0 for v in a[1:])


def test_rolling_max_min():
    vals = [3.0, 1.0, 4.0, 1.0, 5.0]
    assert rolling_max(vals, 3) == [None, None, 4.0, 4.0, 5.0]
    assert rolling_min(vals, 3) == [None, None, 1.0, 1.0, 1.0]
