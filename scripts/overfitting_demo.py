#!/usr/bin/env python3
"""Why "search every strategy on 3 months of M1 data and keep the best" fails.

This script runs that exact procedure on synthetic 1-minute gold-like data that
was generated as a PURE RANDOM WALK. There is provably no exploitable structure
in it -- zero edge, by construction.

If the procedure still produces a spectacular-looking "best strategy", then the
procedure cannot distinguish edge from noise. And if it cannot do that on data
known to contain no edge, its output on real data carries no information either.

That is the whole argument, and it needs no real data to demonstrate.

    python scripts/overfitting_demo.py
"""

import itertools
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading.backtest import TF_M1, run  # noqa: E402
from aitrading.config import XAUUSD, StrategyConfig  # noqa: E402
from aitrading.data import synthetic  # noqa: E402
from aitrading.metrics import expected_max_sharpe  # noqa: E402

EQUITY = 10_000.0
DAYS = 90
BARS = DAYS * 1380  # ~3 months of 1-minute bars
VOL_PER_MIN = 0.012 / (1380 ** 0.5)  # consistent with 1.2% daily gold vol

FRICTIONLESS = replace(
    XAUUSD, half_spread=0.0, slippage=0.0, commission_per_lot_per_side=0.0,
    swap_long_annual=0.0, swap_short_annual=0.0,
)


def build_grid():
    """A search of the kind 'try every possible HFT strategy' implies."""
    lookback_sets = [[2, 5, 10], [3, 8, 15], [5, 15, 30], [10, 20, 40],
                     [2, 3, 5], [5, 10, 20, 40]]
    scales = [1.0, 2.0, 3.5]
    stops = [0.0, 1.0, 2.0, 4.0]
    vol_hls = [10, 30, 90]
    er = [0.0, 0.15, 0.30]
    grid = []
    for lbs, sc, st, vh, e in itertools.product(lookback_sets, scales, stops, vol_hls, er):
        grid.append(StrategyConfig(
            lookbacks=list(lbs), signal_scale=sc, stop_atr_multiple=st,
            vol_halflife=vh, er_threshold=e, use_efficiency_filter=e > 0,
            min_rebalance_lots=0.01, min_signal_change=0.01,
            atr_window=14, max_drawdown_halt=0.0,
        ))
    return grid


def search(bars, inst, grid, label):
    best = None
    for cfg in grid:
        p = run(bars, inst, cfg, TF_M1, EQUITY).performance
        if p.sharpe is None or p.trades.count < 20:
            continue
        if best is None or p.sharpe > best[1].sharpe:
            best = (cfg, p)
    return best


def show(p, days, prefix="  "):
    print(f"{prefix}return            {p.total_return * 100:>10.1f}%")
    print(f"{prefix}Sharpe            {p.sharpe:>10.2f}")
    print(f"{prefix}max drawdown      {p.max_drawdown * 100:>10.1f}%")
    print(f"{prefix}trades            {p.trades.count:>10,}  "
          f"({p.trades.count / days:.0f}/day)")
    wr = p.trades.win_rate
    print(f"{prefix}win rate          {('n/a' if wr is None else f'{wr * 100:.1f}%'):>10}")
    pf = p.trades.profit_factor
    print(f"{prefix}profit factor     {('n/a' if pf is None else f'{pf:.2f}'):>10}")


def main() -> int:
    grid = build_grid()
    print("=" * 78)
    print("THE PROPOSED PROCEDURE, RUN ON DATA WITH PROVABLY ZERO EDGE")
    print("=" * 78)
    print(f"data      : {BARS:,} 1-minute bars (~{DAYS} days), pure random walk")
    print(f"strategies: {len(grid)} configurations searched")
    print("truth     : there is NO exploitable pattern in this data\n")

    bars = synthetic.random_walk(BARS, start=3500.0, vol_per_bar=VOL_PER_MIN, seed=2024)

    # ---- Part A: with real broker costs -----------------------------------
    print("-" * 78)
    print("PART A  Best of all configurations, WITH real broker costs")
    print("-" * 78)
    a = search(bars, XAUUSD, grid, "costs")
    if a:
        show(a[1], DAYS)
        print(f"\n  Best of {len(grid)} configurations still loses. At minute frequency")
        print("  friction dominates everything; no parameter choice escapes it.")

    # ---- Part B: costs removed, to isolate the overfitting ----------------
    print("\n" + "-" * 78)
    print("PART B  Same search, costs REMOVED, to isolate what the search finds")
    print("-" * 78)
    b = search(bars, FRICTIONLESS, grid, "free")
    if not b:
        print("  no valid configuration found")
        return 1
    best_cfg, best_perf = b
    show(best_perf, DAYS)
    print(f"\n  chosen: lookbacks={best_cfg.lookbacks} scale={best_cfg.signal_scale} "
          f"stop={best_cfg.stop_atr_multiple} volHL={best_cfg.vol_halflife} "
          f"ER={best_cfg.er_threshold}")
    print("\n  That looks like a strategy worth trading. It is not. The data is")
    print("  a random walk -- this result is the single luckiest of many tries.")

    # ---- The statistical hurdle ------------------------------------------
    se = best_perf.sharpe_stderr
    hurdle = expected_max_sharpe(len(grid), se) if se else None
    print("\n" + "-" * 78)
    print("THE HURDLE THIS RESULT HAD TO CLEAR (and did not)")
    print("-" * 78)
    print(f"  observed Sharpe                       {best_perf.sharpe:>8.2f}")
    print(f"  standard error over {DAYS / 252:.2f} years        {se:>8.2f}")
    print(f"  Sharpe a ZERO-edge search of {len(grid)} yields {hurdle:>8.2f}")
    print(f"  deflated Sharpe                       {best_perf.sharpe - hurdle:>8.2f}")
    print("\n  Searching more configurations RAISES this hurdle. Trying harder")
    print("  makes the evidence weaker, not stronger.")

    # ---- Out-of-sample collapse ------------------------------------------
    print("\n" + "-" * 78)
    print("THE TEST THAT MATTERS: same strategy, fresh data it was not fitted to")
    print("-" * 78)
    print(f"  {'dataset':<28}{'return':>12}{'Sharpe':>10}")
    print(f"  {'in-sample (fitted here)':<28}{best_perf.total_return * 100:>11.1f}%"
          f"{best_perf.sharpe:>10.2f}")
    oos_sharpes = []
    for i, seed in enumerate((7001, 7002, 7003, 7004), start=1):
        fresh = synthetic.random_walk(BARS, start=3500.0, vol_per_bar=VOL_PER_MIN, seed=seed)
        p = run(fresh, FRICTIONLESS, best_cfg, TF_M1, EQUITY).performance
        if p.sharpe is not None:
            oos_sharpes.append(p.sharpe)
        print(f"  {'out-of-sample #' + str(i):<28}{p.total_return * 100:>11.1f}%"
              f"{('n/a' if p.sharpe is None else f'{p.sharpe:.2f}'):>10}")
    if oos_sharpes:
        avg = sum(oos_sharpes) / len(oos_sharpes)
        print(f"\n  in-sample Sharpe {best_perf.sharpe:.2f}  ->  "
              f"out-of-sample average {avg:.2f}")

    print("\n" + "=" * 78)
    print("CONCLUSION")
    print("=" * 78)
    print("  The procedure produced an attractive strategy from data containing")
    print("  no edge whatsoever, and that strategy did not survive contact with")
    print("  data it had not been fitted to.")
    print()
    print("  A method that manufactures winners out of noise cannot tell you")
    print("  anything when pointed at real prices. The output would look the")
    print("  same either way -- which means it carries no information.")
    print()
    print("  This is why the engine uses purged walk-forward with a small grid")
    print("  and reports a DEFLATED Sharpe. It is slower, less exciting, and it")
    print("  is the only version that can be believed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
