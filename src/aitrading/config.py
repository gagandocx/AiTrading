"""Instrument specifications and strategy configuration.

All costs are expressed in *price units* (not "pips") to avoid the endless
confusion around what a pip means on gold. Convert once, here, and never again.
"""

import math
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Instrument:
    """Contract specification for a single MT5 symbol."""

    symbol: str
    contract_size: float  # units of the base asset per 1.0 lot
    digits: int
    min_lot: float
    lot_step: float
    max_lot: float

    # --- cost model inputs (fill these from YOUR broker, not from defaults) ---
    half_spread: float  # price units; half the typical quoted spread
    commission_per_lot_per_side: float  # account currency
    slippage: float  # price units; expected adverse fill vs reference

    # Annualised financing applied while a position is held, as a fraction of
    # notional. Positive = you pay. MT5 brokers mark these up on both sides,
    # so both are normally positive. Measure them from your account statement.
    swap_long_annual: float = 0.0
    swap_short_annual: float = 0.0

    def round_trip_cost_price_units(self) -> float:
        """Spread + slippage paid across a full entry and exit, in price units."""
        return 2.0 * (self.half_spread + self.slippage)

    def clamp_lots(self, lots: float) -> float:
        """Snap a desired lot size onto the broker's tradable grid.

        Rounds DOWN, always. Rounding to nearest can push a position above a
        leverage or risk cap that the sizing layer just computed, which makes the
        cap meaningless. Under-risking by less than one lot step is harmless;
        silently over-risking is not.
        """
        sign = -1.0 if lots < 0 else 1.0
        mag = abs(lots)
        if mag < self.min_lot:
            return 0.0
        mag = min(mag, self.max_lot)
        steps = math.floor(mag / self.lot_step + 1e-9)
        return sign * round(steps * self.lot_step, 8)


# --- Reference specs. VERIFY every number against your own broker. ----------
# The defaults below are typical raw-spread ECN values, used so the engine runs
# out of the box. They are assumptions, not facts about your account.

XAUUSD = Instrument(
    symbol="XAUUSD",
    contract_size=100.0,  # 100 troy oz per lot
    digits=2,
    min_lot=0.01,
    lot_step=0.01,
    max_lot=50.0,
    half_spread=0.10,  # $0.20 quoted spread
    commission_per_lot_per_side=3.5,
    slippage=0.05,
    swap_long_annual=0.045,
    swap_short_annual=0.010,
)

EURUSD = Instrument(
    symbol="EURUSD",
    contract_size=100_000.0,
    digits=5,
    min_lot=0.01,
    lot_step=0.01,
    max_lot=100.0,
    half_spread=0.00001,  # 0.2 pip quoted spread
    commission_per_lot_per_side=3.5,
    slippage=0.000015,
    swap_long_annual=0.005,
    swap_short_annual=0.020,
)

REGISTRY = {"XAUUSD": XAUUSD, "EURUSD": EURUSD}


@dataclass
class StrategyConfig:
    """Signal and risk parameters.

    Defaults target a holding period of days-to-weeks. That is deliberate: see
    docs/research/strategy-landscape.md for why faster horizons lose to costs.
    """

    # Momentum look-backs in bars. Multiple horizons are averaged so that no
    # single parameter choice drives the result -- this is the main defence
    # against curve fitting on one instrument.
    lookbacks: List[int] = field(default_factory=lambda: [20, 60, 120, 240])

    # Signal shaping
    signal_scale: float = 1.0  # multiplier inside tanh; higher = more binary
    max_signal: float = 1.0

    # Volatility estimation
    vol_halflife: int = 30  # bars, EWMA half-life for realised vol
    vol_floor: float = 1e-9

    # Risk targeting
    target_vol_annual: float = 0.15  # 15% annualised portfolio volatility
    max_leverage: float = 3.0  # cap on notional / equity
    risk_per_trade_cap: float = 0.02  # max fraction of equity at 1 daily sigma

    # Signal family. "trend" is time-series momentum. "reversal" inverts it to
    # trade short-horizon mean reversion. "long_only_trend" clips shorts to zero,
    # which is a distinct hypothesis for an asset with a structural upward drift
    # (gold's buy-and-hold Sharpe over 2021-2026 was 1.06).
    signal_mode: str = "trend"  # trend | reversal | long_only_trend

    # Chop filter: Kaufman efficiency ratio over `er_window` bars must exceed
    # `er_threshold` to take a position. Directly targets the failure mode of
    # trend systems on a single mean-reverting instrument.
    use_efficiency_filter: bool = True
    er_window: int = 60
    er_threshold: float = 0.20

    # Trade throttling -- do not re-trade for tiny signal changes; this is
    # where single-instrument systems quietly bleed to costs.
    min_rebalance_lots: float = 0.02
    min_signal_change: float = 0.10

    # Hard risk controls
    stop_atr_multiple: float = 4.0  # 0 disables
    atr_window: int = 20
    max_drawdown_halt: float = 0.25  # halt trading past this equity drawdown

    def warmup_bars(self) -> int:
        """Bars required before the first valid signal."""
        return max(max(self.lookbacks), self.vol_halflife * 4, self.er_window, self.atr_window) + 1
