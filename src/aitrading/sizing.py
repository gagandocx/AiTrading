"""Position sizing: volatility targeting.

Sizing matters more than signal quality. A mediocre signal sized correctly
survives; an excellent signal sized badly does not. Everything here converts a
dimensionless signal in [-1, +1] into a concrete lot count.
"""

import math

from .config import Instrument, StrategyConfig


def annualise_vol(vol_per_bar: float, bars_per_year: float) -> float:
    return vol_per_bar * math.sqrt(bars_per_year)


def target_lots(
    signal: float,
    vol_per_bar: float,
    bars_per_year: float,
    equity: float,
    price: float,
    inst: Instrument,
    cfg: StrategyConfig,
) -> float:
    """Lots required to express `signal` at the configured risk target.

    Chain: signal -> desired annualised vol -> notional -> lots, then apply the
    leverage cap, the per-trade risk cap, and the broker's lot grid.
    """
    if equity <= 0 or price <= 0 or vol_per_bar <= 0 or signal == 0:
        return 0.0

    vol_annual = annualise_vol(vol_per_bar, bars_per_year)
    if vol_annual <= 0:
        return 0.0

    # Notional such that notional * vol_annual == equity * target_vol * |signal|
    desired_notional = equity * cfg.target_vol_annual * abs(signal) / vol_annual

    # Leverage cap
    desired_notional = min(desired_notional, equity * cfg.max_leverage)

    # Per-trade risk cap: loss at a one-day adverse move must stay within budget.
    daily_vol = annualise_vol(vol_per_bar, bars_per_year) / math.sqrt(252.0)
    if daily_vol > 0:
        max_notional_by_risk = equity * cfg.risk_per_trade_cap / daily_vol
        desired_notional = min(desired_notional, max_notional_by_risk)

    lots = desired_notional / (inst.contract_size * price)
    lots = math.copysign(lots, signal)
    return inst.clamp_lots(lots)


def should_rebalance(
    current_lots: float,
    desired_lots: float,
    current_signal: float,
    last_traded_signal: float,
    cfg: StrategyConfig,
) -> bool:
    """Trade throttle.

    Rebalancing on every tiny drift is how single-instrument systems bleed out.
    Require either a material size change or a material signal change. Always
    allow a full exit, and always allow a direction flip.
    """
    if desired_lots == 0.0 and current_lots != 0.0:
        return True
    if current_lots == 0.0 and desired_lots != 0.0:
        return True
    if current_lots * desired_lots < 0:  # direction flip
        return True
    if abs(desired_lots - current_lots) >= cfg.min_rebalance_lots:
        return True
    if abs(current_signal - last_traded_signal) >= cfg.min_signal_change:
        return True
    return False
