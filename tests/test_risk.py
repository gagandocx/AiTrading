"""Tests for the pre-trade risk gate.

This is the safety-critical module: it is the only thing standing between a
signal and an order. Every limit gets a test proving it actually blocks, and the
gate is verified to fail CLOSED on bad input.
"""

import pytest

from aitrading.live.risk import Decision, RiskLimits, RiskManager, Verdict

PRICE, CONTRACT, SPREAD = 4348.89, 100.0, 0.06
EQ = 10_000.0


def mgr(**kw):
    limits = RiskLimits(**kw)
    m = RiskManager(limits, EQ)
    m.on_equity_update(EQ, "2026-09-11")
    return m


def ev(m, equity=EQ, lots=0.02, spread=SPREAD, **kw):
    return m.evaluate(equity=equity, desired_lots=lots, price=PRICE,
                      spread=spread, contract_size=CONTRACT, **kw)


# --- baseline -------------------------------------------------------------
def test_normal_conditions_allow():
    d = ev(mgr())
    assert d.verdict is Verdict.ALLOW and d.allowed


def test_limits_are_validated():
    with pytest.raises(ValueError):
        RiskManager(RiskLimits(max_daily_loss_pct=0), EQ)
    with pytest.raises(ValueError):
        RiskManager(RiskLimits(max_drawdown_pct=1.5), EQ)
    with pytest.raises(ValueError):
        RiskManager(RiskLimits(), 0.0)


# --- fail closed ----------------------------------------------------------
def test_invalid_inputs_halt_rather_than_trade():
    """A gate that trades on nonsense is worse than no gate."""
    for bad in ({"equity": 0.0}, {"equity": -5.0}):
        m = mgr()
        d = ev(m, **bad)
        assert d.verdict is Verdict.HALT and not d.allowed

    m = mgr()
    d = m.evaluate(equity=EQ, desired_lots=0.02, price=0.0, spread=SPREAD,
                   contract_size=CONTRACT)
    assert d.verdict is Verdict.HALT


def test_nan_spread_is_blocked():
    d = ev(mgr(), spread=float("nan"))
    assert not d.allowed


# --- capital protection ---------------------------------------------------
def test_drawdown_limit_halts():
    m = mgr(max_drawdown_pct=0.10)
    m.on_equity_update(EQ, "2026-09-11")          # peak = 10,000
    d = ev(m, equity=8_900.0)                      # -11%
    assert d.verdict is Verdict.HALT
    assert "drawdown" in d.reason


def test_drawdown_measured_from_peak_not_start():
    m = mgr(max_drawdown_pct=0.10)
    m.on_equity_update(20_000.0, "2026-09-11")     # new peak
    d = ev(m, equity=17_500.0)                     # -12.5% from peak, +75% from start
    assert d.verdict is Verdict.HALT


def test_daily_loss_blocks_for_the_session_only():
    m = mgr(max_daily_loss_pct=0.02)
    d = ev(m, equity=9_700.0)                      # -3% on the day
    assert d.verdict is Verdict.BLOCK and not d.allowed
    # still blocked later in the same session even if equity recovers
    assert not ev(m, equity=9_950.0).allowed
    # new session clears it
    m.on_equity_update(9_950.0, "2026-09-12")
    assert ev(m, equity=9_950.0).allowed


def test_equity_floor_halts():
    m = mgr(min_equity=5_000.0)
    assert ev(m, equity=4_999.0).verdict is Verdict.HALT


# --- halt is sticky -------------------------------------------------------
def test_halt_persists_until_explicitly_reset():
    m = mgr(max_drawdown_pct=0.05)
    assert ev(m, equity=9_000.0).verdict is Verdict.HALT
    # even with perfect conditions restored
    assert ev(m, equity=EQ).verdict is Verdict.HALT
    m.reset_halt()
    assert ev(m, equity=EQ).allowed


# --- activity throttles ---------------------------------------------------
def test_trade_cap_blocks():
    m = mgr(max_trades_per_day=3)
    for _ in range(3):
        m.on_trade_closed(1.0)
    d = ev(m)
    assert d.verdict is Verdict.BLOCK and "cap" in d.reason


def test_consecutive_losses_halt():
    m = mgr(max_consecutive_losses=4)
    for _ in range(4):
        m.on_trade_closed(-10.0)
    assert ev(m).verdict is Verdict.HALT


def test_a_win_resets_the_loss_streak():
    m = mgr(max_consecutive_losses=3)
    m.on_trade_closed(-1.0)
    m.on_trade_closed(-1.0)
    m.on_trade_closed(+1.0)
    assert m.state.consecutive_losses == 0
    assert ev(m).allowed


def test_cooldown_after_loss():
    m = mgr(cooldown_seconds_after_loss=60.0)
    m.on_trade_closed(-5.0, timestamp=1000.0)
    assert not ev(m, timestamp=1030.0).allowed   # 30s elapsed
    assert ev(m, timestamp=1061.0).allowed       # 61s elapsed


def test_trade_counter_resets_each_session():
    m = mgr(max_trades_per_day=2)
    m.on_trade_closed(1.0)
    m.on_trade_closed(1.0)
    assert not ev(m).allowed
    m.on_equity_update(EQ, "2026-09-12")
    assert ev(m).allowed


# --- execution quality: the control that matters at high frequency --------
def test_absolute_spread_cap_blocks_news_spikes():
    m = mgr(max_spread=0.20, median_spread=0.06)
    assert ev(m, spread=0.10).allowed
    d = ev(m, spread=0.85)                        # typical CPI/NFP blowout
    assert d.verdict is Verdict.BLOCK and "spread" in d.reason


def test_relative_spread_cap_blocks_abnormal_widening():
    """Catches widening that is still below the absolute cap but far above
    normal -- the case that quietly destroys fast strategies."""
    m = mgr(max_spread=1.00, median_spread=0.06,
            max_spread_multiple_of_median=3.0)
    assert ev(m, spread=0.15).allowed             # 2.5x median
    assert not ev(m, spread=0.25).allowed         # 4.2x median


def test_blocked_session_hours():
    m = mgr(blocked_hours=[23, 0])
    assert not ev(m, hour=23).allowed             # rollover window
    assert not ev(m, hour=0).allowed
    assert ev(m, hour=14).allowed


def test_news_blackout_window_is_symmetric():
    m = mgr(news_blackout_minutes=5)
    assert not ev(m, minutes_to_news=-2.0).allowed   # just after
    assert not ev(m, minutes_to_news=3.0).allowed    # just before
    assert ev(m, minutes_to_news=30.0).allowed


# --- sizing ---------------------------------------------------------------
def test_oversized_order_is_reduced_not_refused():
    m = mgr(max_position_lots=0.05)
    d = ev(m, lots=0.50)
    assert d.verdict is Verdict.REDUCE and d.allowed
    assert d.max_lots == pytest.approx(0.05)


def test_leverage_cap_binds_on_small_accounts():
    """$1,000 equity, gold at $4,349: 3x leverage allows only ~0.069 lots, so
    the leverage rule must bind before the nominal lot cap.

    The manager is constructed AT $1,000 here. Constructing it at a higher
    equity and then passing $1,000 would correctly register as a catastrophic
    drawdown and halt -- which is the gate working, not a sizing test.
    """
    m = RiskManager(RiskLimits(max_position_lots=1.0, max_leverage=3.0), 1_000.0)
    m.on_equity_update(1_000.0, "2026-09-11")
    d = m.evaluate(equity=1_000.0, desired_lots=0.50, price=PRICE,
                   spread=SPREAD, contract_size=CONTRACT)
    assert d.verdict is Verdict.REDUCE
    assert d.max_lots == pytest.approx(3_000.0 / (CONTRACT * PRICE), rel=1e-9)
    assert d.max_lots < 0.07


def test_both_size_caps_apply_and_the_tighter_one_wins():
    m = mgr(max_position_lots=0.02, max_leverage=3.0)
    d = ev(m, lots=1.0)
    assert d.max_lots == pytest.approx(0.02)


# --- audit ---------------------------------------------------------------
def test_halts_are_recorded_in_the_audit_log():
    m = mgr(max_drawdown_pct=0.05)
    ev(m, equity=9_000.0)
    assert any("HALT" in entry for entry in m.audit_log)


def test_severity_order_halt_beats_block():
    """A drawdown breach and a wide spread at once must report the HALT, since
    that is the condition requiring intervention."""
    m = mgr(max_drawdown_pct=0.05, max_spread=0.10)
    d = ev(m, equity=9_000.0, spread=5.00)
    assert d.verdict is Verdict.HALT
