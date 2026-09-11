#!/usr/bin/env python3
"""Find the trade frequency that maximises NET risk-adjusted return.

Frequency is treated as an output, not an input. Each speed band gets its own
purged walk-forward with its own small grid, so results are comparable and each
band's Sharpe is deflated by the number of configurations searched within it.

    python scripts/frequency_sweep.py --csv data/XAUUSD_H1.csv --timeframe H1

Reading the output: the only column that matters is DEFLATED Sharpe. A band with
a high raw Sharpe and a negative deflated Sharpe found nothing.
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading.backtest import TIMEFRAMES  # noqa: E402
from aitrading.config import XAUUSD, StrategyConfig  # noqa: E402
from aitrading.costs import breakeven_move  # noqa: E402
from aitrading.data import csv_source  # noqa: E402
from aitrading.walkforward import walk_forward  # noqa: E402

# Speed bands, as multiples of the bar interval. Each entry is
# (label, lookback multipliers, rebalance throttle, min signal change).
BANDS = [
    ("very slow", [48, 120, 240], 0.05, 0.30),
    ("slow",      [24, 72, 168],  0.04, 0.20),
    ("medium",    [12, 36, 72],   0.03, 0.12),
    ("fast",      [6, 18, 36],    0.02, 0.06),
    ("very fast", [3, 8, 16],     0.01, 0.02),
    ("ultra",     [2, 4, 8],      0.01, 0.01),
]


def band_grid(lookbacks, throttle, sigchg) -> List[StrategyConfig]:
    """A deliberately small per-band grid: 6 configs keeps the hurdle low."""
    out = []
    for scale in (1.0, 2.0):
        for er in (0.0, 0.15, 0.30):
            out.append(StrategyConfig(
                lookbacks=list(lookbacks),
                signal_scale=scale,
                er_threshold=er,
                use_efficiency_filter=er > 0,
                min_rebalance_lots=throttle,
                min_signal_change=sigchg,
                vol_halflife=max(10, lookbacks[0] * 2),
                er_window=max(20, lookbacks[1]),
                atr_window=14,
                stop_atr_multiple=3.0,
                max_drawdown_halt=0.0,   # measure the strategy, not the halt
                target_vol_annual=0.15,
            ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--timeframe", required=True, choices=sorted(TIMEFRAMES))
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    bars = csv_source.load(args.csv)
    tf = TIMEFRAMES[args.timeframe]
    bars_per_day = tf.bars_per_year / 252.0
    years = len(bars) / tf.bars_per_year
    se = (1.0 / years) ** 0.5

    inst = replace(XAUUSD, half_spread=0.03, slippage=0.005,
                   commission_per_lot_per_side=3.00)
    price = sorted(b.close for b in bars)[len(bars) // 2]
    cost_frac = breakeven_move(inst) / price

    print("=" * 96)
    print(f"FREQUENCY SWEEP  {args.timeframe}  {len(bars):,} bars  {years:.2f} years")
    print("=" * 96)
    print(f"  span gives Sharpe SE {se:.2f} -> a result is only conclusive "
          f"above ~{2 * se:.2f}")
    print(f"  measured friction {cost_frac * 100:.4f}% of notional per round trip\n")

    print(f"  {'band':<11}{'trades/day':>11}{'trades/yr':>11}{'cost drag':>11}"
          f"{'OOS SR':>9}{'DEFLATED':>10}{'net CAGR':>10}{'maxDD':>9}{'verdict':>10}")
    print("  " + "-" * 92)

    rows = []
    for label, lbs, throttle, sigchg in BANDS:
        grid = band_grid(lbs, throttle, sigchg)
        try:
            wf = walk_forward(bars, inst, tf, grid=grid, n_folds=args.folds,
                              initial_equity=args.equity)
        except ValueError:
            print(f"  {label:<11}{'insufficient history for this band':>60}")
            continue
        p = wf.oos
        tpd = (p.trades.count / p.bars * bars_per_day) if p.bars else 0.0
        tpy = tpd * 252
        drag = tpy * cost_frac
        d = wf.oos_deflated_sharpe
        verdict = "CREDIBLE" if (d is not None and d > 0) else "noise"
        rows.append((label, tpd, d, p))
        print(f"  {label:<11}{tpd:>11.1f}{tpy:>11,.0f}{drag * 100:>10.1f}%"
              f"{(p.sharpe or 0):>9.2f}{(d or 0):>10.2f}"
              f"{(p.cagr or 0) * 100:>9.2f}%{p.max_drawdown * 100:>8.1f}%"
              f"{verdict:>10}")

    print("\n" + "=" * 96)
    credible = [r for r in rows if r[2] is not None and r[2] > 0]
    if credible:
        best = max(credible, key=lambda r: r[2])
        print(f"  BEST CREDIBLE BAND: {best[0]} at {best[1]:.1f} trades/day, "
              f"deflated Sharpe {best[2]:.2f}")
        print("  Next step: forward-test on demo for 3+ months before any capital.")
    else:
        print("  NO BAND PRODUCED A CREDIBLE RESULT.")
        print("  Every frequency from very slow to ultra failed to beat the noise")
        print("  hurdle for its own search. At this cost level, on this instrument,")
        print("  intraday trading does not clear its friction.")
        if rows:
            b = max(rows, key=lambda r: (r[2] if r[2] is not None else -99))
            print(f"\n  least-bad: {b[0]} at {b[1]:.1f}/day, deflated {b[2]:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
