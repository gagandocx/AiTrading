"""Performance metrics, including honest correction for multiple testing.

The multiple-testing haircut is not optional decoration. If you try 500 parameter
combinations and report the best raw Sharpe, that number is meaningless. These
functions quantify exactly how meaningless.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

# Standard deviations below this are treated as zero variance. Real bar returns
# have sd of order 1e-3, so this cannot mask a legitimate series.
_DEGENERATE_SD = 1e-12


@dataclass
class TradeStats:
    count: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0  # positive number

    @property
    def win_rate(self) -> Optional[float]:
        return self.wins / self.count if self.count else None

    @property
    def avg_win(self) -> Optional[float]:
        return self.gross_profit / self.wins if self.wins else None

    @property
    def avg_loss(self) -> Optional[float]:
        return self.gross_loss / self.losses if self.losses else None

    @property
    def profit_factor(self) -> Optional[float]:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else None
        return self.gross_profit / self.gross_loss

    @property
    def expectancy(self) -> Optional[float]:
        """Average P&L per trade. This -- not win rate -- is what compounds."""
        return (self.gross_profit - self.gross_loss) / self.count if self.count else None


@dataclass
class Performance:
    bars: int = 0
    bars_per_year: float = 252.0
    initial_equity: float = 0.0
    final_equity: float = 0.0
    returns: List[float] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    total_costs: float = 0.0
    total_financing: float = 0.0
    gross_pnl: float = 0.0
    turnover_lots: float = 0.0
    trades: TradeStats = field(default_factory=TradeStats)
    bars_in_market: int = 0
    halted: bool = False

    # ---- return-based metrics -------------------------------------------------
    @property
    def total_return(self) -> float:
        if self.initial_equity <= 0:
            return 0.0
        return self.final_equity / self.initial_equity - 1.0

    @property
    def years(self) -> float:
        return self.bars / self.bars_per_year if self.bars_per_year else 0.0

    @property
    def cagr(self) -> Optional[float]:
        if self.years <= 0 or self.initial_equity <= 0 or self.final_equity <= 0:
            return None
        return (self.final_equity / self.initial_equity) ** (1.0 / self.years) - 1.0

    @property
    def vol_annual(self) -> Optional[float]:
        if len(self.returns) < 2:
            return None
        return stdev(self.returns) * math.sqrt(self.bars_per_year)

    @property
    def sharpe(self) -> Optional[float]:
        """Annualised Sharpe of bar returns (excess over zero).

        Returns None for a degenerate (effectively zero-variance) series. The
        threshold is not `== 0`: a constant series leaves floating-point residue
        of order 1e-18 in the standard deviation, which would otherwise yield a
        Sharpe of ~1e16.
        """
        if len(self.returns) < 2:
            return None
        sd = stdev(self.returns)
        if sd < _DEGENERATE_SD:
            return None
        return (mean(self.returns) / sd) * math.sqrt(self.bars_per_year)

    @property
    def sortino(self) -> Optional[float]:
        if len(self.returns) < 2:
            return None
        downside = [r for r in self.returns if r < 0]
        if not downside:
            return None
        dd = math.sqrt(sum(r * r for r in downside) / len(self.returns))
        if dd < _DEGENERATE_SD:
            return None
        return (mean(self.returns) / dd) * math.sqrt(self.bars_per_year)

    @property
    def max_drawdown(self) -> float:
        peak = -float("inf")
        worst = 0.0
        for e in self.equity_curve:
            peak = max(peak, e)
            if peak > 0:
                worst = min(worst, e / peak - 1.0)
        return worst

    @property
    def calmar(self) -> Optional[float]:
        mdd = abs(self.max_drawdown)
        c = self.cagr
        if c is None or mdd == 0:
            return None
        return c / mdd

    @property
    def time_in_market(self) -> Optional[float]:
        return self.bars_in_market / self.bars if self.bars else None

    @property
    def cost_drag_annual(self) -> Optional[float]:
        """Total friction as a fraction of starting equity, per year."""
        if self.years <= 0 or self.initial_equity <= 0:
            return None
        return (self.total_costs + self.total_financing) / self.initial_equity / self.years

    @property
    def cost_share_of_gross(self) -> Optional[float]:
        """Friction as a share of gross P&L. Above ~0.5 the strategy is a
        cost-generation machine that happens to trade."""
        if self.gross_pnl <= 0:
            return None
        return (self.total_costs + self.total_financing) / self.gross_pnl

    # ---- statistical significance --------------------------------------------
    @property
    def sharpe_stderr(self) -> Optional[float]:
        """Standard error of the Sharpe estimate (Lo 2002 approximation)."""
        sr = self.sharpe
        if sr is None or self.bars < 2:
            return None
        sr_per_bar = sr / math.sqrt(self.bars_per_year)
        se_per_bar = math.sqrt((1.0 + 0.5 * sr_per_bar**2) / self.bars)
        return se_per_bar * math.sqrt(self.bars_per_year)

    def sharpe_t_stat(self) -> Optional[float]:
        sr, se = self.sharpe, self.sharpe_stderr
        if sr is None or se in (None, 0):
            return None
        return sr / se


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: Sequence[float]) -> float:
    """Sample standard deviation."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def expected_max_sharpe(n_trials: int, sharpe_stderr: float) -> float:
    """Expected maximum Sharpe from `n_trials` strategies with ZERO true edge.

    Bailey & Lopez de Prado's expected-maximum-of-N-normals approximation. If
    your best backtest Sharpe does not clear this bar, you have found noise.
    """
    if n_trials <= 1 or sharpe_stderr <= 0:
        return 0.0
    n = float(n_trials)
    z = math.sqrt(2.0 * math.log(n))
    # First-order correction to the expected maximum of N standard normals.
    expected_z = z - (math.log(math.log(n)) + math.log(4.0 * math.pi)) / (2.0 * z)
    return max(0.0, expected_z) * sharpe_stderr


def deflated_sharpe(observed_sharpe: float, n_trials: int, sharpe_stderr: float) -> float:
    """Observed Sharpe minus the Sharpe a zero-edge search would have produced.

    Report THIS, not the raw number, whenever parameters were selected by search.
    """
    return observed_sharpe - expected_max_sharpe(n_trials, sharpe_stderr)
