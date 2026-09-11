#!/usr/bin/env python3
"""Open the sealed holdout. ONE TIME ONLY.

Run this only when a candidate has cleared the cumulative hurdle on the research
set. The number it prints is the honest estimate of future performance, because
the lockbox has never influenced any decision.

    python scripts\\open_lockbox.py --cycle 4 --lookbacks 20 60 120 --stop-atr 4.0

After this runs, the dataset is permanently marked as opened. Testing another
candidate on it would make it in-sample, and the script will refuse.
"""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading.backtest import TIMEFRAMES, run  # noqa: E402
from aitrading.config import XAUUSD, StrategyConfig  # noqa: E402
from aitrading.data import csv_source  # noqa: E402
from aitrading.report import summarise  # noqa: E402
from aitrading.research import lockbox  # noqa: E402

SEAL_PATH = ROOT / "research_state" / "lockbox_seal.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", type=int, required=True)
    ap.add_argument("--csv", default=str(ROOT / "data" / "XAUUSD_D1.csv"))
    ap.add_argument("--timeframe", default="D1", choices=sorted(TIMEFRAMES))
    ap.add_argument("--costs", default=str(ROOT / "data" / "XAUUSD_costs.json"))
    ap.add_argument("--lookbacks", type=int, nargs="+", required=True)
    ap.add_argument("--mode", default="trend",
                    choices=["trend", "reversal", "long_only_trend"])
    ap.add_argument("--signal-scale", type=float, default=1.0)
    ap.add_argument("--er-threshold", type=float, default=0.20)
    ap.add_argument("--stop-atr", type=float, default=3.0)
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--research-frac", type=float, default=0.70)
    ap.add_argument("--i-am-sure", action="store_true",
                    help="required: confirms you accept this is a one-shot test")
    args = ap.parse_args()

    seal = lockbox.SealRecord(SEAL_PATH)
    dataset = f"{Path(args.csv).stem}_{args.timeframe}"

    try:
        seal.require_sealed(dataset)
    except lockbox.LockboxViolation as e:
        print(f"\nREFUSED\n{e}\n")
        return 2

    if not args.i_am_sure:
        print(f"\nThis will permanently open the lockbox for {dataset!r}.")
        print("It can only be done once. Re-run with --i-am-sure to proceed.\n")
        return 1

    bars = csv_source.load(args.csv)
    tf = TIMEFRAMES[args.timeframe]
    sp = lockbox.split(bars, args.research_frac)

    inst = XAUUSD
    cp = Path(args.costs)
    if cp.exists():
        d = json.loads(cp.read_text())
        upd = {}
        if "half_spread_suggested" in d:
            upd["half_spread"] = float(d["half_spread_suggested"])
        for k in ("contract_size", "min_lot", "lot_step", "max_lot",
                  "commission_per_lot_per_side", "slippage",
                  "swap_long_annual", "swap_short_annual"):
            if k in d:
                upd[k] = float(d[k])
        inst = replace(inst, **upd)

    cfg = StrategyConfig(
        lookbacks=list(args.lookbacks), signal_mode=args.mode,
        signal_scale=args.signal_scale, er_threshold=args.er_threshold,
        use_efficiency_filter=args.er_threshold > 0,
        stop_atr_multiple=args.stop_atr, max_drawdown_halt=0.0,
    )

    print("=" * 78)
    print(f"OPENING LOCKBOX  {dataset}  {len(sp.lockbox):,} bars "
          f"({len(sp.lockbox) / tf.bars_per_year:.2f} years)")
    print(f"period: {sp.lockbox_start_time[:10]} -> {bars[-1].time[:10]}")
    print("=" * 78)

    res = run(sp.lockbox, inst, cfg, tf, args.equity)
    print(summarise(res, title="LOCKBOX RESULT (never used in any decision)"))

    sr = res.performance.sharpe
    seal.record_open(dataset, args.cycle, str(cfg.lookbacks) + "/" + args.mode, sr)

    print("\n" + "=" * 78)
    print("  This is a single out-of-sample test, so there is NO multiple-testing")
    print("  correction to apply -- the number above stands as measured.")
    print(f"  Lockbox {dataset!r} is now permanently marked as opened.")
    if sr is not None and sr > 0.3:
        print("\n  Positive. Next step is forward-testing on a DEMO account for")
        print("  3+ months. A lockbox result is still history, not the future.")
    else:
        print("\n  Not positive. The research-set result did not generalise.")
        print("  This is the correct time to stop, not to search further: any")
        print("  further tuning would now be fitting to the lockbox too.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
