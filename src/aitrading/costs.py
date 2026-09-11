"""Transaction and financing cost model.

This module is the most important one in the repository. A backtest without an
honest cost model is a random number generator with a nice chart. Every number
here should be measured from your own broker statements, not assumed.
"""

from dataclasses import dataclass

from .config import Instrument


@dataclass
class FillResult:
    executed_price: float
    spread_slippage_cost: float  # account currency
    commission: float  # account currency

    @property
    def total(self) -> float:
        return self.spread_slippage_cost + self.commission


def execute(inst: Instrument, reference_price: float, lots_delta: float) -> FillResult:
    """Model a fill for a position change of `lots_delta` at `reference_price`.

    Cost is charged on the absolute size traded and is always adverse: buys fill
    above the reference, sells below. `reference_price` should be the mid or the
    bar open you are executing against.
    """
    if lots_delta == 0:
        return FillResult(reference_price, 0.0, 0.0)

    direction = 1.0 if lots_delta > 0 else -1.0
    edge = inst.half_spread + inst.slippage
    executed_price = reference_price + direction * edge

    size = abs(lots_delta)
    spread_slippage_cost = size * inst.contract_size * edge
    commission = size * inst.commission_per_lot_per_side
    return FillResult(executed_price, spread_slippage_cost, commission)


def financing(
    inst: Instrument, lots: float, price: float, bar_hours: float
) -> float:
    """Financing cost in account currency for holding `lots` over one bar.

    Returns a positive number when you pay. Modelled as an annualised rate on
    notional, which is a cleaner and more conservative abstraction than trying to
    replicate a broker's triple-Wednesday swap table.
    """
    if lots == 0 or bar_hours <= 0:
        return 0.0
    notional = abs(lots) * inst.contract_size * price
    rate = inst.swap_long_annual if lots > 0 else inst.swap_short_annual
    return notional * rate * (bar_hours / 24.0 / 365.0)


def breakeven_move(inst: Instrument) -> float:
    """Price move required to cover one round trip, in price units, per lot.

    Useful sanity check: if this is a meaningful fraction of the volatility of
    your holding period, the strategy cannot work no matter how good the signal.
    """
    per_lot_cost = (
        inst.contract_size * inst.round_trip_cost_price_units()
        + 2.0 * inst.commission_per_lot_per_side
    )
    return per_lot_cost / inst.contract_size


def cost_to_vol_ratio(inst: Instrument, price: float, daily_vol_fraction: float) -> float:
    """Round-trip cost as a fraction of one day's volatility.

    The single best number for deciding whether an instrument and a holding
    period are compatible. Below ~0.05 is comfortable; above ~0.25 means the
    frequency is wrong for the instrument.
    """
    if price <= 0 or daily_vol_fraction <= 0:
        raise ValueError("price and daily_vol_fraction must be positive")
    return breakeven_move(inst) / (price * daily_vol_fraction)
