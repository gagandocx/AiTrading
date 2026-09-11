"""Purged walk-forward parameter selection.

This is how "tweaking the parameters" is done honestly. The alternative --
searching a grid over the whole history and reporting the best result -- produces
a number that describes the past and predicts nothing.

Protocol per fold:
  1. Fit (grid-search) on data strictly BEFORE the test window.
  2. Leave an embargo gap so overlapping look-back windows cannot leak.
  3. Evaluate the single chosen config on the untouched test window.
  4. Concatenate test-window returns across folds -> the out-of-sample record.

Only step 4 is reportable, and even that must be deflated by the number of
configurations searched.
"""

from dataclasses import dataclass, replace
from typing import List, Optional, Sequence

from .backtest import Bar, BacktestResult, Timeframe, run
from .config import Instrument, StrategyConfig
from .metrics import Performance, TradeStats, deflated_sharpe, expected_max_sharpe


@dataclass
class FoldResult:
    index: int
    train_bars: int
    test_bars: int
    chosen: StrategyConfig
    train_sharpe: Optional[float]
    test_sharpe: Optional[float]
    test_return: float


@dataclass
class WalkForwardResult:
    folds: List[FoldResult]
    oos: Performance
    configs_tried: int

    @property
    def oos_sharpe(self) -> Optional[float]:
        return self.oos.sharpe

    @property
    def oos_deflated_sharpe(self) -> Optional[float]:
        sr, se = self.oos.sharpe, self.oos.sharpe_stderr
        if sr is None or se is None:
            return None
        return deflated_sharpe(sr, self.configs_tried, se)

    @property
    def hurdle(self) -> Optional[float]:
        se = self.oos.sharpe_stderr
        if se is None:
            return None
        return expected_max_sharpe(self.configs_tried, se)

    @property
    def is_credible(self) -> bool:
        """True only if the OOS Sharpe survives the multiple-testing hurdle."""
        d = self.oos_deflated_sharpe
        return d is not None and d > 0.0


def default_grid() -> List[StrategyConfig]:
    """A deliberately SMALL grid.

    Every extra configuration raises the statistical bar the result must clear
    (see metrics.expected_max_sharpe). Searching 10,000 combinations does not
    find a better strategy, it finds a better-disguised random one.
    """
    grid: List[StrategyConfig] = []
    lookback_sets = [
        [10, 30, 60, 120],
        [20, 60, 120, 240],
        [40, 120, 240, 480],
    ]
    for lbs in lookback_sets:
        for er_thr in (0.0, 0.20, 0.30):
            for scale in (0.75, 1.5):
                grid.append(
                    StrategyConfig(
                        lookbacks=list(lbs),
                        er_threshold=er_thr,
                        use_efficiency_filter=er_thr > 0.0,
                        signal_scale=scale,
                    )
                )
    return grid


def _aggregate(
    fold_results: Sequence[BacktestResult], initial_equity: float, bars_per_year: float
) -> Performance:
    """Chain per-fold out-of-sample returns into one continuous OOS record."""
    perf = Performance(bars_per_year=bars_per_year, initial_equity=initial_equity)
    perf.trades = TradeStats()
    equity = initial_equity
    perf.equity_curve.append(equity)

    for res in fold_results:
        p = res.performance
        for r in p.returns:
            equity *= 1.0 + r
            perf.returns.append(r)
            perf.equity_curve.append(equity)
        perf.bars += p.bars
        perf.bars_in_market += p.bars_in_market
        perf.total_costs += p.total_costs
        perf.total_financing += p.total_financing
        perf.gross_pnl += p.gross_pnl
        perf.turnover_lots += p.turnover_lots
        perf.trades.count += p.trades.count
        perf.trades.wins += p.trades.wins
        perf.trades.losses += p.trades.losses
        perf.trades.gross_profit += p.trades.gross_profit
        perf.trades.gross_loss += p.trades.gross_loss
        perf.halted = perf.halted or p.halted

    perf.final_equity = equity
    return perf


def walk_forward(
    bars: Sequence[Bar],
    inst: Instrument,
    tf: Timeframe,
    grid: Optional[List[StrategyConfig]] = None,
    n_folds: int = 5,
    min_train_frac: float = 0.35,
    embargo_bars: Optional[int] = None,
    initial_equity: float = 10_000.0,
    min_trades_in_train: int = 8,
) -> WalkForwardResult:
    grid = grid or default_grid()
    n = len(bars)
    warmup = max(c.warmup_bars() for c in grid)

    train_end0 = int(n * min_train_frac)
    remaining = n - train_end0
    if remaining < n_folds * (warmup + 40):
        raise ValueError(
            f"Not enough history: {n} bars for {n_folds} folds with warmup {warmup}. "
            f"Need at least ~{int(train_end0 + n_folds * (warmup + 40))} bars, or "
            f"reduce n_folds / use a faster timeframe."
        )

    fold_size = remaining // n_folds
    if embargo_bars is None:
        embargo_bars = warmup

    folds: List[FoldResult] = []
    oos_results: List[BacktestResult] = []

    for k in range(n_folds):
        test_start = train_end0 + k * fold_size
        test_end = n if k == n_folds - 1 else test_start + fold_size
        train_end = max(warmup + 1, test_start - embargo_bars)
        train = bars[:train_end]
        # The test slice carries `warmup` bars of history so signals are warm on
        # the first tradable test bar. Those bars are NOT scored: the fold's
        # reported returns begin after them.
        test_hist_start = max(0, test_start - warmup)
        test = bars[test_hist_start:test_end]

        best_cfg: Optional[StrategyConfig] = None
        best_sharpe: Optional[float] = None
        for cfg in grid:
            r = run(train, inst, cfg, tf, initial_equity)
            sr = r.performance.sharpe
            if sr is None or r.performance.trades.count < min_trades_in_train:
                continue
            if best_sharpe is None or sr > best_sharpe:
                best_sharpe, best_cfg = sr, cfg

        if best_cfg is None:
            best_cfg = grid[0]

        # Score only the true test window.
        test_res_full = run(test, inst, best_cfg, tf, initial_equity)
        scored_from = test_start - test_hist_start
        trimmed = _trim(test_res_full, scored_from, initial_equity, tf.bars_per_year)

        oos_results.append(trimmed)
        folds.append(
            FoldResult(
                index=k,
                train_bars=len(train),
                test_bars=trimmed.performance.bars,
                chosen=replace(best_cfg),
                train_sharpe=best_sharpe,
                test_sharpe=trimmed.performance.sharpe,
                test_return=trimmed.performance.total_return,
            )
        )

    oos = _aggregate(oos_results, initial_equity, tf.bars_per_year)
    return WalkForwardResult(folds=folds, oos=oos, configs_tried=len(grid) * n_folds)


def _trim(
    res: BacktestResult, from_bar: int, initial_equity: float, bars_per_year: float
) -> BacktestResult:
    """Drop the warmup portion of a fold so only true OOS bars are scored."""
    p = res.performance
    keep = p.returns[from_bar:] if from_bar < len(p.returns) else []
    new = Performance(bars_per_year=bars_per_year, initial_equity=initial_equity)
    new.trades = p.trades
    equity = initial_equity
    new.equity_curve.append(equity)
    for r in keep:
        equity *= 1.0 + r
        new.returns.append(r)
        new.equity_curve.append(equity)
    new.bars = len(keep)
    new.final_equity = equity
    # Cost/turnover attribution is approximated by the scored fraction of bars.
    frac = (len(keep) / p.bars) if p.bars else 0.0
    new.total_costs = p.total_costs * frac
    new.total_financing = p.total_financing * frac
    new.gross_pnl = p.gross_pnl * frac
    new.turnover_lots = p.turnover_lots * frac
    new.bars_in_market = int(p.bars_in_market * frac)
    new.halted = p.halted
    return BacktestResult(performance=new, lots=res.lots, signal=res.signal, equity=new.equity_curve)
