"""Pre-trade risk gate.

Every order passes through RiskManager.evaluate() before reaching the broker.
The gate is deliberately paranoid: it fails CLOSED. If state is missing, stale
or contradictory, it refuses to trade rather than assuming the best.

Design notes that matter for high-frequency operation:

* The SPREAD GUARD is the single most valuable control here. Gold's spread sits
  near $0.06 in calm conditions and blows out past $1.00 around CPI/NFP/FOMC and
  at the 17:00 ET rollover. At 200 trades/day, executing through those windows is
  what converts a break-even system into a large loss. Cost is not a constant.

* Limits are checked in order of severity, and a HALT is sticky: once tripped it
  persists until explicitly reset. A gate that silently re-enables itself is not
  a risk control.

* Drawdown is measured against peak equity, not starting equity, because that is
  what actually governs ruin.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Verdict(str, Enum):
    ALLOW = "allow"
    REDUCE = "reduce"   # trade permitted, but size capped
    BLOCK = "block"     # this order refused, trading continues
    HALT = "halt"       # trading stopped until manually reset


@dataclass
class RiskLimits:
    # --- capital protection -------------------------------------------------
    max_daily_loss_pct: float = 0.02      # halt for the day past this
    max_drawdown_pct: float = 0.10        # halt entirely past this (from peak)
    min_equity: float = 0.0               # absolute floor

    # --- position sizing ----------------------------------------------------
    max_position_lots: float = 0.10
    max_leverage: float = 3.0             # notional / equity

    # --- activity throttles -------------------------------------------------
    max_trades_per_day: int = 300
    max_consecutive_losses: int = 10
    cooldown_seconds_after_loss: float = 0.0

    # --- execution quality --------------------------------------------------
    # Skip trading when the spread exceeds this, in PRICE UNITS. For XAUUSD with
    # a $0.06 typical spread, $0.20 blocks news spikes while allowing normal
    # widening. Set from a measured distribution, never guessed.
    max_spread: float = 0.20
    max_spread_multiple_of_median: float = 3.0
    median_spread: float = 0.06

    # --- session control ----------------------------------------------------
    # Minutes around a scheduled event during which no new orders are sent.
    news_blackout_minutes: int = 3
    # Hours (broker server time) during which trading is disabled. Gold's
    # rollover window has the worst spreads of the day.
    blocked_hours: List[int] = field(default_factory=lambda: [23, 0])

    def validate(self) -> None:
        if not 0 < self.max_daily_loss_pct < 1:
            raise ValueError("max_daily_loss_pct must be in (0,1)")
        if not 0 < self.max_drawdown_pct < 1:
            raise ValueError("max_drawdown_pct must be in (0,1)")
        if self.max_position_lots <= 0:
            raise ValueError("max_position_lots must be positive")
        if self.max_spread <= 0:
            raise ValueError("max_spread must be positive")


@dataclass
class Decision:
    verdict: Verdict
    reason: str
    max_lots: float = 0.0

    @property
    def allowed(self) -> bool:
        return self.verdict in (Verdict.ALLOW, Verdict.REDUCE)


@dataclass
class RiskState:
    equity_peak: float = 0.0
    day_start_equity: float = 0.0
    current_day: Optional[str] = None
    trades_today: int = 0
    consecutive_losses: int = 0
    halted: bool = False
    halt_reason: str = ""
    day_blocked: bool = False
    last_loss_timestamp: Optional[float] = None


class RiskManager:
    """Stateful pre-trade gate. One instance per trading session."""

    def __init__(self, limits: RiskLimits, starting_equity: float):
        limits.validate()
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self.limits = limits
        self.state = RiskState(
            equity_peak=starting_equity,
            day_start_equity=starting_equity,
        )
        self._audit: List[str] = []

    # -- lifecycle ----------------------------------------------------------
    def on_equity_update(self, equity: float, day: str) -> None:
        """Call once per bar/tick before evaluating orders."""
        if day != self.state.current_day:
            self.state.current_day = day
            self.state.day_start_equity = equity
            self.state.trades_today = 0
            self.state.day_blocked = False
            self._log(f"new session {day}, day-start equity {equity:.2f}")
        self.state.equity_peak = max(self.state.equity_peak, equity)

    def on_trade_closed(self, pnl: float, timestamp: Optional[float] = None) -> None:
        self.state.trades_today += 1
        if pnl < 0:
            self.state.consecutive_losses += 1
            self.state.last_loss_timestamp = timestamp
        else:
            self.state.consecutive_losses = 0

    def reset_halt(self, note: str = "manual reset") -> None:
        """Halts are sticky by design; clearing one is an explicit act."""
        self.state.halted = False
        self.state.halt_reason = ""
        self._log(f"halt cleared: {note}")

    # -- the gate -----------------------------------------------------------
    def evaluate(
        self,
        equity: float,
        desired_lots: float,
        price: float,
        spread: float,
        contract_size: float,
        hour: Optional[int] = None,
        minutes_to_news: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> Decision:
        L = self.limits
        S = self.state

        # 0. Fail closed on nonsense inputs.
        if equity <= 0 or price <= 0 or contract_size <= 0:
            return self._halt("invalid inputs (equity/price/contract_size)")
        if spread < 0 or not math.isfinite(spread):
            return Decision(Verdict.BLOCK, f"invalid spread {spread}")

        # 1. Sticky halt.
        if S.halted:
            return Decision(Verdict.HALT, f"halted: {S.halt_reason}")

        # 2. Hard capital floors -> HALT.
        if equity <= L.min_equity:
            return self._halt(f"equity {equity:.2f} at or below floor {L.min_equity:.2f}")

        dd = (equity / S.equity_peak - 1.0) if S.equity_peak > 0 else 0.0
        if dd <= -L.max_drawdown_pct:
            return self._halt(f"drawdown {dd * 100:.2f}% breached "
                              f"limit {-L.max_drawdown_pct * 100:.2f}%")

        # 3. Daily loss -> block for the remainder of the session.
        if S.day_start_equity > 0:
            day_pnl = equity / S.day_start_equity - 1.0
            if day_pnl <= -L.max_daily_loss_pct:
                S.day_blocked = True
                return Decision(Verdict.BLOCK,
                                f"daily loss {day_pnl * 100:.2f}% hit limit; "
                                f"flat until next session")
        if S.day_blocked:
            return Decision(Verdict.BLOCK, "daily loss limit already hit today")

        # 4. Activity throttles.
        if S.trades_today >= L.max_trades_per_day:
            return Decision(Verdict.BLOCK,
                            f"trade cap reached ({S.trades_today}/{L.max_trades_per_day})")
        if S.consecutive_losses >= L.max_consecutive_losses:
            return self._halt(f"{S.consecutive_losses} consecutive losses")
        if (L.cooldown_seconds_after_loss > 0 and S.last_loss_timestamp is not None
                and timestamp is not None):
            elapsed = timestamp - S.last_loss_timestamp
            if elapsed < L.cooldown_seconds_after_loss:
                return Decision(Verdict.BLOCK,
                                f"cooldown {elapsed:.0f}s of "
                                f"{L.cooldown_seconds_after_loss:.0f}s")

        # 5. Execution quality. THIS is what protects a fast strategy.
        if spread > L.max_spread:
            return Decision(Verdict.BLOCK,
                            f"spread {spread:.3f} above cap {L.max_spread:.3f}")
        if L.median_spread > 0:
            mult = spread / L.median_spread
            if mult > L.max_spread_multiple_of_median:
                return Decision(Verdict.BLOCK,
                                f"spread {spread:.3f} is {mult:.1f}x median "
                                f"(cap {L.max_spread_multiple_of_median:.1f}x)")

        # 6. Session windows.
        if hour is not None and hour in L.blocked_hours:
            return Decision(Verdict.BLOCK, f"hour {hour} is a blocked session window")
        if minutes_to_news is not None and abs(minutes_to_news) <= L.news_blackout_minutes:
            return Decision(Verdict.BLOCK,
                            f"news blackout ({minutes_to_news:+.1f} min)")

        # 7. Size caps -- reduce rather than refuse.
        cap_lots = L.max_position_lots
        lev_cap_lots = (equity * L.max_leverage) / (contract_size * price)
        cap = min(cap_lots, lev_cap_lots)
        if cap <= 0:
            return Decision(Verdict.BLOCK, "size cap resolves to zero")

        if abs(desired_lots) > cap:
            return Decision(Verdict.REDUCE,
                            f"size {abs(desired_lots):.3f} capped to {cap:.3f} lots",
                            max_lots=cap)
        return Decision(Verdict.ALLOW, "ok", max_lots=cap)

    # -- helpers ------------------------------------------------------------
    def _halt(self, reason: str) -> Decision:
        self.state.halted = True
        self.state.halt_reason = reason
        self._log(f"HALT: {reason}")
        return Decision(Verdict.HALT, f"halted: {reason}")

    def _log(self, msg: str) -> None:
        self._audit.append(msg)

    @property
    def audit_log(self) -> List[str]:
        return list(self._audit)
