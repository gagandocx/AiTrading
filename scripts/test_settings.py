#!/usr/bin/env python3
"""Test ONE specific settings set that you specify in advance.

This is statistically the strongest test available to you, and it is worth
understanding why.

When I search 2,000 configurations and keep the best, the result must clear a
huge hurdle (expected max Sharpe of 2,000 zero-edge trials). When YOU name a
single configuration BEFORE seeing its result, there is no search to correct
for: it only has to clear ~2 standard errors. On 16.6 years of D1 that is a
Sharpe of about 0.50 instead of about 0.81.

So a setting you believe in, stated up front, gets a genuinely easier test than
anything I could find by optimisation. That is not a loophole -- it is the
correct statistics of pre-registration.

    python scripts\\test_settings.py --settings my_settings.json

Example my_settings.json:
{
  "name": "gagan_preferred",
  "lookbacks": [20, 60, 120],
  "signal_mode": "trend",
  "signal_scale": 1.5,
  "er_threshold": 0.20,
  "stop_atr_multiple": 4.0,
  "target_vol_annual": 0.15,
  "vol_halflife": 30,
  "min_rebalance_lots": 0.02,
  "min_signal_change": 0.10
}
"""

import argparse
import json
import math
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

ALLOWED = {
    "lookbacks", "signal_mode", "signal_scale", "max_signal", "vol_halflife",
    "target_vol_annual", "max_leverage", "risk_per_trade_cap",
    "use_efficiency_filter", "er_window", "er_threshold",
    "min_rebalance_lots", "min_signal_change", "stop_atr_multiple",
    "atr_window", "max_drawdown_halt",
}


def load_settings(path: str):
    d = json.loads(Path(path).read_text())
    name = d.pop("name", Path(path).stem)
    unknown = set(d) - ALLOWED
    if unknown:
        raise SystemExit(f"unknown settings keys: {sorted(unknown)}\n"
                         f"allowed: {sorted(ALLOWED)}")
    if "er_threshold" in d and "use_efficiency_filter" not in d:
        d["use_efficiency_filter"] = float(d["er_threshold"]) > 0
    return name, StrategyConfig(**d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", required=True)
    ap.add_argument("--csv", default=str(ROOT / "data" / "XAUUSD_D1.csv"))
    ap.add_argument("--timeframe", default="D1", choices=sorted(TIMEFRAMES))
    ap.add_argument("--costs", default=str(ROOT / "data" / "XAUUSD_costs.json"))
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--research-frac", type=float, default=0.70)
    ap.add_argument("--research-only", action="store_true",
                    help="test on the research split only, leaving the lockbox sealed")
    args = ap.parse_args()

    name, cfg = load_settings(args.settings)
    bars = csv_source.load(args.csv)
    tf = TIMEFRAMES[args.timeframe]

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

    test_bars = lockbox.split(bars, args.research_frac).research if args.research_only else bars
    years = len(test_bars) / tf.bars_per_year

    print("=" * 78)
    print(f"PRE-REGISTERED SETTINGS TEST: {name}")
    print("=" * 78)
    print(f"  {args.timeframe}  {len(test_bars):,} bars  {years:.2f} years"
          f"{'  (research split only)' if args.research_only else '  (full history)'}")
    print(f"  lookbacks={cfg.lookbacks} mode={cfg.signal_mode} "
          f"scale={cfg.signal_scale} ER={cfg.er_threshold} stopATR={cfg.stop_atr_multiple}")
    print()

    res = run(test_bars, inst, cfg, tf, args.equity)
    print(summarise(res, title=f"RESULT: {name}"))

    p = res.performance
    sr, se = p.sharpe, p.sharpe_stderr
    print("\n  --- significance (single pre-registered config, NO search penalty) ---")
    if sr is None or se is None:
        print("  insufficient data for a significance test")
        return 0
    t = sr / se
    print(f"  Sharpe                    {sr:>7.2f}")
    print(f"  standard error            {se:>7.2f}")
    print(f"  t-statistic               {t:>7.2f}")
    print(f"  threshold for t>2         {2 * se:>7.2f}")
    # buy & hold comparison -- the benchmark that matters
    closes = [b.close for b in test_bars]
    bh_cagr = (closes[-1] / closes[0]) ** (1 / years) - 1
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    import statistics
    bh_vol = statistics.stdev(rets) * math.sqrt(tf.bars_per_year)
    print(f"\n  buy-and-hold Sharpe       {bh_cagr / bh_vol:>7.2f}  "
          f"(CAGR {bh_cagr * 100:.2f}%)")
    print(f"  your settings' Sharpe     {sr:>7.2f}  "
          f"(CAGR {(p.cagr or 0) * 100:.2f}%)")

    beats_zero = t > 2
    beats_bh = sr > bh_cagr / bh_vol
    print()
    if beats_zero and beats_bh:
        print("  SIGNIFICANT and beats buy-and-hold. Next: confirm on the lockbox")
        print("  (scripts/open_lockbox.py), then demo for 3+ months.")
    elif beats_zero:
        print("  Statistically non-zero, but does NOT beat simply holding gold.")
        print("  A strategy that underperforms its own asset is not worth its risk.")
    else:
        print("  Not distinguishable from zero at t>2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
