#!/usr/bin/env python3
"""Rank every strategy family on your intraday data.

    python scripts\\strategy_library.py --csv data\\XAUUSD_M5.csv --timeframe M5

Tests 14 distinct families -- trend-following, breakout, oscillator reversion,
session-anchored -- with a couple of parameter variants each, and ranks by net
return after your measured broker costs. Buy-and-hold is included as the
benchmark, because a strategy that loses to holding the asset is not a strategy.
"""

import argparse
import json
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading import families as F  # noqa: E402
from aitrading.backtest import TIMEFRAMES, run  # noqa: E402
from aitrading.config import XAUUSD, StrategyConfig  # noqa: E402
from aitrading.data import csv_source  # noqa: E402


def build(bars):
    """(label, signal series) for every family and variant."""
    c = [b.close for b in bars]
    h = [b.high for b in bars]
    l = [b.low for b in bars]
    t = [b.time for b in bars]
    out = []

    # --- trend / breakout -------------------------------------------------
    for fast, slow in ((5, 20), (10, 50), (20, 100)):
        out.append((f"ma_cross {fast}/{slow}", F.ma_cross(c, fast, slow)))
    for f_, s_, sg in ((12, 26, 9), (24, 52, 18)):
        out.append((f"macd {f_}/{s_}/{sg}", F.macd(c, f_, s_, sg)))
    for w, m in ((20, 1.5), (20, 2.5), (50, 2.0)):
        out.append((f"keltner {w}/{m}", F.keltner_breakout(h, l, c, w, m)))
    for lb, m in ((20, 1.0), (60, 1.0)):
        out.append((f"atr_breakout {lb}/{m}", F.atr_breakout(h, l, c, lb, m)))
    for rb in (6, 12, 24):
        out.append((f"open_range {rb}b", F.opening_range_breakout(t, h, l, c, rb)))
    out.append(("rsi_trend 14", F.rsi_trend(c, 14)))

    # --- mean reversion ---------------------------------------------------
    for p, os_, ob in ((14, 30, 70), (14, 20, 80), (7, 25, 75)):
        out.append((f"rsi_rev {p}/{os_}-{ob}", F.rsi_reversion(c, p, os_, ob)))
    for w in (14, 30):
        out.append((f"stoch_rev {w}", F.stoch_reversion(h, l, c, w, 20, 80)))
    for z in (1.5, 2.5):
        out.append((f"twap_rev z{z}", F.twap_reversion(t, c, z)))

    # --- families already in the engine -----------------------------------
    for mode, lbs in (("trend", [12, 36, 72]), ("reversal", [12, 36, 72]),
                      ("breakout", [24, 72, 144]), ("donchian_exit", [24, 72, 144]),
                      ("bollinger", [24, 72, 144]), ("long_only_trend", [12, 36, 72])):
        out.append((f"{mode} {lbs[0]}", ("__builtin__", mode, lbs)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--timeframe", required=True, choices=sorted(TIMEFRAMES))
    ap.add_argument("--costs", default=str(ROOT / "data" / "XAUUSD_costs.json"))
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--top", type=int, default=99)
    args = ap.parse_args()

    bars = csv_source.load(args.csv)
    tf = TIMEFRAMES[args.timeframe]
    days = len(bars) / (tf.bars_per_year / 252)
    years = days / 252

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

    base = StrategyConfig(
        use_efficiency_filter=False, stop_atr_multiple=0.0, atr_window=14,
        max_drawdown_halt=0.0, min_rebalance_lots=0.01, min_signal_change=0.05,
        vol_halflife=50, target_vol_annual=0.15)

    rows = []
    for label, sig in build(bars):
        if isinstance(sig, tuple) and sig[0] == "__builtin__":
            _, mode, lbs = sig
            cfg = replace(base, signal_mode=mode, lookbacks=lbs, signal_scale=1.5,
                          vol_halflife=max(10, lbs[0] * 3))
            p = run(bars, inst, cfg, tf, args.equity).performance
        else:
            p = run(bars, inst, base, tf, args.equity,
                    precomputed_signal=sig).performance
        if p.bars == 0:
            continue
        ann = ((1 + p.total_return) ** (252 / days) - 1) * 100 if days > 0 else 0.0
        rows.append((p.total_return, label, ann, p, p.trades.count / days))

    c = [b.close for b in bars]
    bh_ret = c[-1] / c[0] - 1
    bh_ann = ((1 + bh_ret) ** (252 / days) - 1) * 100
    rets = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    bh_sr = ((c[-1] / c[0]) ** (1 / years) - 1) / (
        statistics.stdev(rets) * math.sqrt(tf.bars_per_year))

    rows.sort(reverse=True)
    print("=" * 100)
    print(f"STRATEGY LIBRARY  {args.timeframe}  {len(bars):,} bars = "
          f"{days:.0f} trading days ({years:.2f}y)")
    print(f"costs: ${(inst.round_trip_cost_price_units() * inst.contract_size + 2 * inst.commission_per_lot_per_side):.2f}/lot round trip")
    print("=" * 100)
    print(f"  {'#':>3} {'strategy':<22}{'/day':>7}{'RETURN':>9}{'ann.':>9}"
          f"{'Sharpe':>8}{'t':>6}{'maxDD':>8}{'win%':>7}{'PF':>6}{'friction':>10}")
    print("  " + "-" * 96)
    for rank, (ret, label, ann, p, tpd) in enumerate(rows[:args.top], 1):
        se = p.sharpe_stderr or 0
        t = (p.sharpe / se) if (p.sharpe and se) else 0.0
        pf = p.trades.profit_factor
        mark = "  <" if ret > bh_ret else ""
        print(f"  {rank:>3} {label:<22}{tpd:>7.1f}{ret * 100:>8.2f}%{ann:>8.1f}%"
              f"{(p.sharpe or 0):>8.2f}{t:>6.2f}{p.max_drawdown * 100:>7.1f}%"
              f"{(p.trades.win_rate or 0) * 100:>6.1f}%"
              f"{(0 if pf in (None, float('inf')) else pf):>6.2f}"
              f"{p.total_costs + p.total_financing:>10,.0f}{mark}")

    print("  " + "-" * 96)
    print(f"      {'BUY AND HOLD':<22}{0.0:>7.1f}{bh_ret * 100:>8.2f}%{bh_ann:>8.1f}%"
          f"{bh_sr:>8.2f}{'':>6}{'':>8}{'':>7}{'':>6}{0:>10}")
    beat = sum(1 for r in rows if r[0] > bh_ret)
    pos = sum(1 for r in rows if r[0] > 0)
    print(f"\n  {pos}/{len(rows)} profitable   {beat}/{len(rows)} beat buy-and-hold")
    print(f"  '<' marks strategies that beat holding the asset")
    print(f"\n  Sharpe standard error on this span: {(1 / years) ** 0.5:.2f} -- a single")
    print(f"  pre-registered strategy needs Sharpe > {2 * (1 / years) ** 0.5:.2f} to be significant;")
    print(f"  the BEST OF {len(rows)} needs far more, since picking a winner is itself a search.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
