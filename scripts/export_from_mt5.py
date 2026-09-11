#!/usr/bin/env python3
"""Export real history and REAL broker costs from your MT5 terminal.

Run this on the Windows machine where MT5 is installed:

    pip install MetaTrader5
    python scripts/export_from_mt5.py --symbol XAUUSD --timeframes D1 H4 --years 15

Outputs into data/:
    XAUUSD_D1.csv        bars, oldest first
    XAUUSD_H4.csv
    XAUUSD_costs.json    measured spread + contract spec -> feeds the cost model

IMPORTANT about spread measurement: it samples the LIVE spread, so run it while
the market is open and during the hours you actually intend to trade. A spread
sampled at 3am London is not the spread you will pay. Skip it with --no-costs if
the market is closed, then run again later with --costs-only.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading.data import csv_source, mt5_source  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframes", nargs="+", default=["D1", "H4"])
    ap.add_argument("--years", type=float, default=15.0)
    ap.add_argument("--outdir", default=str(ROOT / "data"))
    ap.add_argument("--no-costs", action="store_true", help="skip live spread sampling")
    ap.add_argument("--costs-only", action="store_true", help="only sample spread")
    ap.add_argument("--spread-samples", type=int, default=60)
    ap.add_argument("--terminal-path", default=None, help="path to terminal64.exe")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    mt5_source.connect(path=args.terminal_path)
    try:
        symbol = mt5_source.resolve_symbol(args.symbol)
        if symbol != args.symbol:
            print(f"note: your broker calls it {symbol!r}, not {args.symbol!r}")

        if not args.costs_only:
            for tf in args.timeframes:
                span = mt5_source.span_for(tf, args.years)
                if span < args.years:
                    print(f"  {tf:>3}: capping span to {span * 365:.0f} days "
                          f"(intraday data is for cost calibration, not edge testing)")
                bars = mt5_source.fetch(symbol, tf, years=span)
                path = outdir / f"{args.symbol}_{tf}.csv"
                csv_source.save(bars, str(path))
                mb = path.stat().st_size / 1e6
                print(f"  {tf:>3}: {len(bars):>7,} bars  "
                      f"{bars[0].time} -> {bars[-1].time}  "
                      f"({mb:.1f} MB) -> {path.name}")

                # Warn when the export is too short to be useful for its purpose.
                if tf == "D1":
                    years_got = len(bars) / 252.0
                    if years_got < 8:
                        print(f"       WARNING: only ~{years_got:.1f} years of D1. The edge")
                        print(f"       test wants 15+. Open a {symbol} D1 chart, hold Home")
                        print(f"       to force a full download, then re-run.")
                    else:
                        se = (1.0 / years_got) ** 0.5
                        print(f"       ~{years_got:.1f} years -> Sharpe standard error "
                              f"{se:.2f}. Good.")
                elif len(bars) < 5000:
                    print(f"       WARNING: only {len(bars)} bars. Open a {symbol} {tf} "
                          f"chart in MT5, press Home to scroll back, then re-run.")

        if not args.no_costs:
            print(f"\nsampling live spread ({args.spread_samples}s)...")
            costs = mt5_source.measure_costs(symbol, samples=args.spread_samples)
            path = outdir / f"{args.symbol}_costs.json"
            path.write_text(json.dumps(costs, indent=2))
            print(json.dumps(costs, indent=2))
            print(f"\n  -> {path.name}")
            print("\n  Add your commission per lot per side (from your contract "
                  "specification\n  or account statement) to that JSON as "
                  '"commission_per_lot_per_side".')
    finally:
        mt5_source.shutdown()

    print("\nDone. Now run:")
    print(f"  python scripts/run_backtest.py --csv data/{args.symbol}_D1.csv "
          f"--timeframe D1 --costs data/{args.symbol}_costs.json --walk-forward")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
