"""Human-readable performance reporting."""

from typing import Optional

from .backtest import BacktestResult
from .walkforward import WalkForwardResult


def _pct(x: Optional[float], nd: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def _num(x: Optional[float], nd: int = 2) -> str:
    if x is None:
        return "n/a"
    if x == float("inf"):
        return "inf"
    return f"{x:.{nd}f}"


def summarise(res: BacktestResult, title: str = "BACKTEST") -> str:
    p = res.performance
    t = p.trades
    L = [f"=== {title} ===",
         f"  bars                 {p.bars:,}  ({p.years:.2f} years)",
         f"  equity               {p.initial_equity:,.0f} -> {p.final_equity:,.0f}",
         f"  total return         {_pct(p.total_return)}",
         f"  CAGR                 {_pct(p.cagr)}",
         f"  annualised vol       {_pct(p.vol_annual)}",
         f"  Sharpe               {_num(p.sharpe)}   (t-stat {_num(p.sharpe_t_stat())})",
         f"  Sortino              {_num(p.sortino)}",
         f"  max drawdown         {_pct(p.max_drawdown)}",
         f"  Calmar               {_num(p.calmar)}",
         f"  time in market       {_pct(p.time_in_market)}",
         "  --- trades ---",
         f"  count                {t.count}",
         f"  win rate             {_pct(t.win_rate)}",
         f"  avg win / avg loss   {_num(t.avg_win)} / {_num(t.avg_loss)}",
         f"  profit factor        {_num(t.profit_factor)}",
         f"  expectancy per trade {_num(t.expectancy)}",
         "  --- friction ---",
         f"  gross P&L            {p.gross_pnl:,.0f}",
         f"  transaction costs    {p.total_costs:,.0f}",
         f"  financing            {p.total_financing:,.0f}",
         f"  cost drag / yr       {_pct(p.cost_drag_annual)}",
         f"  costs / gross P&L    {_pct(p.cost_share_of_gross)}",
         f"  turnover (lots)      {_num(p.turnover_lots)}"]
    if p.halted:
        L.append("  !! DRAWDOWN HALT TRIGGERED -- trading stopped mid-run")
    return "\n".join(L)


def summarise_walk_forward(wf: WalkForwardResult) -> str:
    L = ["=== WALK-FORWARD (out-of-sample only) ===",
         f"  folds                {len(wf.folds)}",
         f"  configs searched     {wf.configs_tried}",
         ""]
    L.append(f"  {'fold':>4} {'train':>8} {'test':>7} {'IS SR':>8} {'OOS SR':>8} {'OOS ret':>9}  lookbacks / ER")
    for f in wf.folds:
        lbs = ",".join(str(x) for x in f.chosen.lookbacks)
        L.append(
            f"  {f.index:>4} {f.train_bars:>8,} {f.test_bars:>7,} "
            f"{_num(f.train_sharpe):>8} {_num(f.test_sharpe):>8} {_pct(f.test_return):>9}  "
            f"{lbs} / {f.chosen.er_threshold:.2f}"
        )

    L += ["", summarise(
        type("R", (), {"performance": wf.oos})(), title="AGGREGATE OUT-OF-SAMPLE"
    ), "", "  --- multiple-testing correction ---",
        f"  OOS Sharpe           {_num(wf.oos_sharpe)}",
        f"  noise hurdle         {_num(wf.hurdle)}   "
        f"(Sharpe a zero-edge search of {wf.configs_tried} configs would produce)",
        f"  DEFLATED Sharpe      {_num(wf.oos_deflated_sharpe)}",
        f"  verdict              {'CREDIBLE' if wf.is_credible else 'NOT DISTINGUISHABLE FROM NOISE'}"]
    return "\n".join(L)
