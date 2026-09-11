import math

from aitrading.config import XAUUSD, StrategyConfig
from aitrading.sizing import annualise_vol, should_rebalance, target_lots

CFG = StrategyConfig()
BPY = 252.0


def _lots(signal, vol_per_bar=0.012, equity=100_000.0, price=3500.0, cfg=CFG):
    return target_lots(signal, vol_per_bar, BPY, equity, price, XAUUSD, cfg)


def test_zero_signal_means_no_position():
    assert _lots(0.0) == 0.0


def test_direction_follows_signal():
    assert _lots(+0.8) > 0
    assert _lots(-0.8) < 0


def test_size_increases_with_signal_strength():
    assert abs(_lots(0.9)) >= abs(_lots(0.3))


def test_size_decreases_when_volatility_rises():
    """Volatility targeting: the same signal in a more volatile market must
    produce a SMALLER position. This is the core risk-control property."""
    calm = abs(_lots(1.0, vol_per_bar=0.006))
    wild = abs(_lots(1.0, vol_per_bar=0.030))
    assert wild < calm


def test_leverage_cap_is_respected():
    """Very low volatility would otherwise demand enormous size."""
    equity, price = 100_000.0, 3500.0
    lots = abs(_lots(1.0, vol_per_bar=0.0002, equity=equity, price=price))
    notional = lots * XAUUSD.contract_size * price
    assert notional <= equity * CFG.max_leverage + 1e-6


def test_risk_per_trade_cap_is_respected():
    cfg = StrategyConfig(max_leverage=100.0, risk_per_trade_cap=0.01,
                         target_vol_annual=5.0)
    vol_per_bar = 0.012
    equity, price = 100_000.0, 3500.0
    lots = abs(_lots(1.0, vol_per_bar=vol_per_bar, equity=equity, price=price, cfg=cfg))
    notional = lots * XAUUSD.contract_size * price
    daily_vol = annualise_vol(vol_per_bar, BPY) / math.sqrt(252.0)
    loss_at_one_sigma = notional * daily_vol
    assert loss_at_one_sigma <= equity * cfg.risk_per_trade_cap * 1.05


def test_non_positive_inputs_are_safe():
    assert target_lots(1.0, 0.012, BPY, 0.0, 3500.0, XAUUSD, CFG) == 0.0
    assert target_lots(1.0, 0.0, BPY, 100_000.0, 3500.0, XAUUSD, CFG) == 0.0
    assert target_lots(1.0, 0.012, BPY, 100_000.0, 0.0, XAUUSD, CFG) == 0.0


def test_clamp_lots_respects_broker_grid():
    assert XAUUSD.clamp_lots(0.004) == 0.0  # below minimum
    assert XAUUSD.clamp_lots(9999.0) == XAUUSD.max_lot
    assert XAUUSD.clamp_lots(0.10) == 0.10  # exact step survives


def test_clamp_lots_rounds_down_never_up():
    """Rounding to nearest would let a position exceed the leverage cap that
    sizing just computed. Risk limits must only ever bind downward."""
    assert XAUUSD.clamp_lots(0.126) == 0.12
    assert XAUUSD.clamp_lots(0.129) == 0.12
    assert XAUUSD.clamp_lots(-0.126) == -0.12
    assert abs(XAUUSD.clamp_lots(0.857142)) <= 0.857142


def test_throttle_allows_exits_entries_and_flips():
    assert should_rebalance(0.5, 0.0, 0.0, 0.5, CFG)      # exit
    assert should_rebalance(0.0, 0.5, 0.5, 0.0, CFG)      # entry
    assert should_rebalance(0.5, -0.5, -0.5, 0.5, CFG)    # flip


def test_throttle_blocks_trivial_adjustments():
    """A 0.001-lot drift with a static signal must NOT trigger a trade."""
    assert not should_rebalance(0.500, 0.501, 0.60, 0.60, CFG)


def test_throttle_allows_material_signal_change():
    assert should_rebalance(0.500, 0.501, 0.90, 0.60, CFG)
