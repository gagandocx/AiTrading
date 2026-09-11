#!/usr/bin/env python3
"""Run a backtest or walk-forward evaluation on real history.

    python scripts/run_backtest.py --csv data/XAUUSD_D1.csv --timeframe D1 \
        --costs data/XAUUSD_costs.json --walk-forward

Always prefer --walk-forward. A single full-history backtest with chosen
parameters tells you what would have worked, which is not the same as what will.
"""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading.backtest import TIMEFRAMES, run  # noqa: E402
from aitrading.config import REGISTRY, Instrument, StrategyConfig  # noqa: E402
from aitrading.costs import breakeven_move, cost_to_vol_ratio  # noqa: E402
from aitrading.data import csv_source  # noqa: E402
from aitrading.metrics import stdev  # noqa: E402
from aitrading.report import summarise, summarise_walk_forward  # noqa: E402
from aitrading.walkforward import default_grid, walk_forward  # noqa: E402


def apply_measured_costs(inst: Instrument, path: str) -> Instrument:
    """Override the assumed cost model with numbers measured at your broker."""
    d = json.loads(Path(path).read_text())
    updates = {}
    if "half_spread_suggested" in d:
        updates["half_spread"] = float(d["half_spread_suggested"])
    for key in ("contract_size", "min_lot", "lot_step", "max_lot", "digits",
                "commission_per_lot_per_side", "swap_long_annual", "swap_short_annual",
                "slippage"):
        if key in d:
            updates[key] = int(d[key]) if key == "digits" else float(d[key])
    if "p90_spread" in d and "slippage" not in d:
        # Conservative default: assume adverse fills toward the 90th percentile.
        updates["slippage"] = max(
            0.0, (float(d["p90_spread"]) - float(d.get("median_spread", 0))) / 2.0
        )
    print(f"applied measured costs from {path}: {sorted(updates)}")
    return replace(inst, **updates)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--timeframe", default="D1", choices=sorted(TIMEFRAMES))
    ap.add_argument("--instrument", default="XAUUSD", choices=sorted(REGISTRY))
    ap.add_argument("--costs", default=None, help="JSON from export_from_mt5.py")
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--walk-forward", action="store_true")
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    inst = REGISTRY[args.instrument]
    if args.costs:
        inst = apply_measured_costs(inst, args.costs)

    bars = csv_source.load(args.csv)
    tf = TIMEFRAMES[args.timeframe]
    closes = [b.close for b in bars]

    # --- data and viability diagnostics before any performance number ---------
    import math
    import statistics
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    daily_vol = stdev(rets) * math.sqrt(tf.bars_per_year / 252.0)
    # Use the MEDIAN close as the cost reference, not the last close. Gold ran
    # from ~1100 to ~3500 over a typical sample, so the final price badly
    # misrepresents the cost ratio that applied across the history.
    ref_price = statistics.median(closes)
    print(f"loaded {len(bars):,} bars  {bars[0].time} -> {bars[-1].time}")
    print(f"price range {min(closes):,.2f} - {max(closes):,.2f} "
          f"(median {ref_price:,.2f}, used as cost reference)")
    print(f"measured daily volatility: {daily_vol * 100:.2f}%")
    ratio = cost_to_vol_ratio(inst, ref_price, daily_vol)
    print(f"round-trip cost {breakeven_move(inst):.4f} price units "
          f"= {ratio * 100:.2f}% of one day's volatility")
    if ratio > 0.25:
        print("  WARNING: friction exceeds 25% of daily volatility. Check that the")
        print("  cost model and the instrument's contract size are correct.")

    bars_per_day = tf.bars_per_year / 252.0
    print(f"\nfrequency check for {args.timeframe}:")
    for hold_bars in (1, 5, 20):
        hold_days = hold_bars / bars_per_day
        trades_yr = 252.0 / hold_days if hold_days > 0 else 0
        drag = trades_yr * breakeven_move(inst) / ref_price
        flag = "  <-- too expensive" if drag > 0.075 else ""
        print(f"  holding {hold_bars:>2} bars (~{hold_days:.1f} days): "
              f"{trades_yr:>6,.0f} trades/yr, {drag * 100:>5.1f}% annual cost drag{flag}")
    print()

    if args.walk_forward:
        wf = walk_forward(bars, inst, tf, grid=default_grid(), n_folds=args.folds,
                          initial_equity=args.equity)
        print(summarise_walk_forward(wf))
        print()
        if wf.is_credible:
            print("The out-of-sample result survives the multiple-testing hurdle.")
            print("Next step: forward-test on a DEMO account for at least 3 months")
            print("before committing capital. Backtests do not include your own")
            print("behaviour under drawdown.")
        else:
            print("The out-of-sample result is NOT distinguishable from noise.")
            print("Do not trade this. Options: use a longer history, a slower")
            print("timeframe, a smaller parameter grid, or accept that this")
            print("instrument/signal combination has no edge at your cost level.")
    else:
        res = run(bars, inst, StrategyConfig(), tf, args.equity)
        print(summarise(res, title=f"IN-SAMPLE {args.instrument} {args.timeframe}"))
        print("\nWARNING: this is a single in-sample backtest with default")
        print("parameters. It is a description of the past. Use --walk-forward.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
