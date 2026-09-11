#!/usr/bin/env python3
"""Automated research cycle. Run this on your PC; it produces a report for me.

    python scripts\\auto_backtest.py --cycle 2

What it does:
  1. splits your data into RESEARCH (70%) and a SEALED LOCKBOX (30%)
  2. runs this cycle's pre-registered hypotheses on the research set only,
     with purged walk-forward
  3. appends to the search ledger, so the significance hurdle rises
  4. writes reports/cycle_NN.json for me to analyse
  5. with --push, commits and pushes it automatically

The lockbox is NOT touched. It is opened once, at the very end, by
scripts/open_lockbox.py -- and only if a candidate has cleared the hurdle.
"""

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading.backtest import TIMEFRAMES  # noqa: E402
from aitrading.config import XAUUSD  # noqa: E402
from aitrading.data import csv_source  # noqa: E402
from aitrading.research import hypotheses, lockbox  # noqa: E402
from aitrading.research.ledger import Ledger  # noqa: E402
from aitrading.walkforward import walk_forward  # noqa: E402

LEDGER_PATH = ROOT / "research_state" / "ledger.json"
SEAL_PATH = ROOT / "research_state" / "lockbox_seal.json"
REPORT_DIR = ROOT / "reports"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", type=int, required=True)
    ap.add_argument("--csv", default=str(ROOT / "data" / "XAUUSD_D1.csv"))
    ap.add_argument("--timeframe", default="D1", choices=sorted(TIMEFRAMES))
    ap.add_argument("--costs", default=str(ROOT / "data" / "XAUUSD_costs.json"))
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--research-frac", type=float, default=0.70)
    ap.add_argument("--push", action="store_true", help="git commit and push the report")
    args = ap.parse_args()

    tf = TIMEFRAMES[args.timeframe]
    bars = csv_source.load(args.csv)

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

    sp = lockbox.split(bars, args.research_frac)
    ledger = Ledger.load(str(LEDGER_PATH))
    hyps = hypotheses.get(args.cycle)

    print("=" * 82)
    print(f"RESEARCH CYCLE {args.cycle}   {args.timeframe}   {len(bars):,} bars")
    print("=" * 82)
    print(f"  {sp.describe(tf.bars_per_year)}")
    print(f"  lockbox sealed: {lockbox.SealRecord(SEAL_PATH).is_sealed(args.timeframe)}")
    print(f"  configurations already examined (all cycles): "
          f"{ledger.cumulative_configs:,}")
    print()

    research_years = len(sp.research) / tf.bars_per_year
    planned = sum(h.size for h in hyps) * args.folds
    hurdle = ledger.hurdle(research_years, additional_configs=planned)
    print(f"  this cycle adds {planned:,} configs -> cumulative "
          f"{ledger.cumulative_configs + planned:,}")
    print(f"  HURDLE to beat (deflated vs cumulative): Sharpe {hurdle:.2f}")
    print()

    results = []
    best_overall = None
    for h in hyps:
        print(f"  [{h.name}] {h.size} configs")
        print(f"    rationale: {h.rationale[:100]}...")
        try:
            wf = walk_forward(sp.research, inst, tf, grid=h.grid,
                              n_folds=args.folds, initial_equity=args.equity)
        except ValueError as e:
            print(f"    SKIPPED: {e}")
            continue
        p = wf.oos
        sr = p.sharpe or 0.0
        entry = {
            "hypothesis": h.name,
            "rationale": h.rationale,
            "configs": h.size,
            "oos_bars": p.bars,
            "oos_years": round(p.bars / tf.bars_per_year, 3),
            "oos_sharpe": round(sr, 3),
            "oos_cagr": round((p.cagr or 0.0) * 100, 3),
            "max_drawdown_pct": round(p.max_drawdown * 100, 2),
            "trades": p.trades.count,
            "trades_per_day": round(p.trades.count / max(p.bars, 1)
                                    * (tf.bars_per_year / 252), 3),
            "win_rate_pct": round((p.trades.win_rate or 0) * 100, 2),
            "profit_factor": (None if p.trades.profit_factor in (None, float("inf"))
                              else round(p.trades.profit_factor, 3)),
            "costs": round(p.total_costs, 2),
            "financing": round(p.total_financing, 2),
            "cost_share_of_gross": (None if p.cost_share_of_gross is None
                                    else round(p.cost_share_of_gross, 3)),
            "deflated_vs_cumulative": round(sr - hurdle, 3),
            "beats_hurdle": bool(sr - hurdle > 0),
            "chosen_per_fold": [
                {"fold": f.index, "lookbacks": f.chosen.lookbacks,
                 "mode": f.chosen.signal_mode, "er": f.chosen.er_threshold,
                 "stop_atr": f.chosen.stop_atr_multiple,
                 "oos_sharpe": (None if f.test_sharpe is None else round(f.test_sharpe, 3))}
                for f in wf.folds
            ],
        }
        results.append(entry)
        print(f"    OOS Sharpe {sr:>6.2f}   deflated {sr - hurdle:>+6.2f}   "
              f"{'BEATS HURDLE' if sr > hurdle else 'noise'}   "
              f"{entry['trades_per_day']:.2f} trades/day")
        if best_overall is None or sr > best_overall[1]:
            best_overall = (h.name, sr)

    ledger.record(
        description=f"cycle {args.cycle}: " + ", ".join(h.name for h in hyps),
        configs_tested=planned, timeframe=args.timeframe,
        best_raw_sharpe=(best_overall[1] if best_overall else None),
        oos_years=research_years,
        notes=f"{len(results)} hypotheses completed",
    )
    ledger.save()

    report = {
        "cycle": args.cycle,
        "timestamp": time.time(),
        "machine": platform.node(),
        "timeframe": args.timeframe,
        "csv": Path(args.csv).name,
        "total_bars": len(bars),
        "research_bars": len(sp.research),
        "lockbox_bars": len(sp.lockbox),
        "research_end": sp.research_end_time,
        "lockbox_start": sp.lockbox_start_time,
        "lockbox_still_sealed": lockbox.SealRecord(SEAL_PATH).is_sealed(args.timeframe),
        "instrument": asdict(inst),
        "cumulative_configs_after": ledger.cumulative_configs,
        "hurdle": round(hurdle, 3),
        "results": results,
        "verdict": ("CANDIDATE FOUND" if any(r["beats_hurdle"] for r in results)
                    else "no hypothesis beat the hurdle"),
    }
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"cycle_{args.cycle:02d}_{args.timeframe}.json"
    out.write_text(json.dumps(report, indent=2))

    print()
    print("=" * 82)
    print(f"  VERDICT: {report['verdict']}")
    print(f"  report -> {out.relative_to(ROOT)}")
    print(f"  ledger -> cumulative {ledger.cumulative_configs:,} configs")
    print("=" * 82)
    print()
    print(ledger.summary())

    if args.push:
        import subprocess
        for cmd in (["git", "add", "-f", str(out), str(LEDGER_PATH)],
                    ["git", "commit", "-m", f"research: cycle {args.cycle} "
                     f"{args.timeframe} report ({report['verdict']})"],
                    ["git", "push"]):
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            print(f"  $ {' '.join(cmd[:3])} -> {r.returncode}")
            if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
                print(f"    {r.stderr.strip()[:200]}")
    else:
        print("\n  Not pushed. To send it to me:")
        print(f"    git add -f {out.relative_to(ROOT)} research_state/ledger.json")
        print(f'    git commit -m "research: cycle {args.cycle} report"')
        print("    git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
