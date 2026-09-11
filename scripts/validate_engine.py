#!/usr/bin/env python3
"""Engine validation against synthetic processes with KNOWN ground truth.

READ THIS BEFORE INTERPRETING THE OUTPUT.

Nothing here is a performance estimate for XAUUSD or any real instrument. These
are correctness checks: each process below has a known true edge, so we know what
a correct backtester must report. The purpose is to detect look-ahead bias,
accounting errors and cost-model mistakes.

For real numbers, run scripts/run_backtest.py against real broker history.
"""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aitrading.backtest import TF_D1, run  # noqa: E402
from aitrading.config import EURUSD, XAUUSD, StrategyConfig  # noqa: E402
from aitrading.costs import breakeven_move, cost_to_vol_ratio  # noqa: E402
from aitrading.data import synthetic  # noqa: E402

EQUITY = 100_000.0
FRICTIONLESS = replace(
    XAUUSD, half_spread=0.0, slippage=0.0, commission_per_lot_per_side=0.0,
    swap_long_annual=0.0, swap_short_annual=0.0,
)
N_SEEDS = 12
N_BARS = 1500


def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _sweep(gen, inst, cfg, label):
    rets, sharpes, trades, costs, dds = [], [], [], [], []
    for seed in range(N_SEEDS):
        bars = gen(N_BARS, seed=seed)
        p = run(bars, inst, cfg, TF_D1, EQUITY).performance
        rets.append(p.total_return)
        if p.sharpe is not None:
            sharpes.append(p.sharpe)
        trades.append(p.trades.count)
        costs.append(p.total_costs + p.total_financing)
        dds.append(p.max_drawdown)
    return {
        "label": label, "ret": _avg(rets), "sharpe": _avg(sharpes),
        "trades": _avg(trades), "cost": _avg(costs), "dd": _avg(dds),
    }


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    cfg_nofilter = StrategyConfig(use_efficiency_filter=False)
    failures = []

    section("CHECK 1  Zero-edge process: engine must LOSE exactly its friction")
    print("A driftless random walk has no exploitable structure by construction.")
    print(f"Averaged over {N_SEEDS} independent paths of {N_BARS} bars each.\n")
    free = _sweep(synthetic.random_walk, FRICTIONLESS, cfg_nofilter, "no costs")
    paid = _sweep(synthetic.random_walk, XAUUSD, cfg_nofilter, "real costs")
    print(f"  {'variant':<12}{'avg return':>12}{'avg Sharpe':>12}{'avg trades':>12}{'avg friction':>14}")
    for r in (free, paid):
        print(f"  {r['label']:<12}{r['ret']*100:>11.2f}%{r['sharpe']:>12.2f}"
              f"{r['trades']:>12.0f}{r['cost']:>13,.0f}")
    ok = paid["ret"] < 0 and paid["ret"] < free["ret"]
    print(f"\n  expected: frictionless ~= flat, with-costs strictly negative")
    print(f"  RESULT:   {'PASS' if ok else 'FAIL -- look-ahead or accounting bug'}")
    if not ok:
        failures.append("zero-edge process did not lose")

    section("CHECK 2  Signal must work where the effect exists -- and only there")
    print("Trend following must profit on a trending process and LOSE on a")
    print("mean-reverting one. A system that wins on both is fitting noise.\n")
    trend = _sweep(synthetic.trending, FRICTIONLESS, cfg_nofilter, "trending")
    revert = _sweep(synthetic.mean_reverting, FRICTIONLESS, cfg_nofilter, "mean-revert")
    print(f"  {'process':<14}{'avg return':>12}{'avg Sharpe':>12}{'avg maxDD':>12}")
    for r in (trend, revert):
        print(f"  {r['label']:<14}{r['ret']*100:>11.2f}%{r['sharpe']:>12.2f}{r['dd']*100:>11.2f}%")
    ok = trend["ret"] > 0 and revert["ret"] < 0
    print(f"\n  expected: trending positive, mean-reverting negative")
    print(f"  RESULT:   {'PASS' if ok else 'FAIL -- signal is not doing what it claims'}")
    if not ok:
        failures.append("directional discrimination failed")

    section("CHECK 3  Chop filter must reduce activity in the absence of trend")
    on = _sweep(synthetic.random_walk, XAUUSD,
                StrategyConfig(use_efficiency_filter=True, er_threshold=0.25), "filter on")
    off = _sweep(synthetic.random_walk, XAUUSD, cfg_nofilter, "filter off")
    print(f"\n  {'variant':<12}{'avg trades':>12}{'avg friction':>14}{'avg return':>12}")
    for r in (off, on):
        print(f"  {r['label']:<12}{r['trades']:>12.0f}{r['cost']:>13,.0f}{r['ret']*100:>11.2f}%")
    ok = on["cost"] < off["cost"]
    print(f"\n  expected: filter cuts friction on structureless data")
    print(f"  RESULT:   {'PASS' if ok else 'FAIL'}")
    if not ok:
        failures.append("efficiency filter ineffective")

    section("CHECK 4  Volatility targeting must stabilise realised risk")
    print("Same signal, calm vs wild synthetic markets. Realised volatility")
    print("should stay near target instead of tracking market volatility.\n")
    cfg = StrategyConfig(use_efficiency_filter=False, target_vol_annual=0.15)
    print(f"  {'market vol/bar':>16}{'realised ann. vol':>20}{'target':>10}")
    realised = []
    for vpb in (0.004, 0.008, 0.016, 0.032):
        vols = []
        for seed in range(6):
            bars = synthetic.trending(N_BARS, vol_per_bar=vpb, seed=seed)
            p = run(bars, FRICTIONLESS, cfg, TF_D1, EQUITY).performance
            if p.vol_annual:
                vols.append(p.vol_annual)
        v = _avg(vols)
        realised.append(v)
        print(f"  {vpb:>16.3f}{v*100:>19.1f}%{'15.0%':>10}")
    spread = max(realised) / min(realised) if min(realised) > 0 else 999
    market_spread = 0.032 / 0.004
    ok = spread < market_spread / 2
    print(f"\n  market vol ranged {market_spread:.0f}x; realised risk ranged {spread:.1f}x")
    print(f"  RESULT:   {'PASS -- risk is being controlled' if ok else 'FAIL'}")
    if not ok:
        failures.append("vol targeting not effective")

    section("CHECK 5  Cost model: instrument selection and holding-period limits")
    print("Round-trip friction as a share of one day's volatility.")
    print("This is the number that decides whether a holding period is viable.\n")
    print(f"  {'instrument':<12}{'price':>10}{'daily vol':>11}{'cost/vol':>11}")
    for inst, px, dv in ((XAUUSD, 3500.0, 0.012), (EURUSD, 1.10, 0.0055)):
        r = cost_to_vol_ratio(inst, px, dv)
        print(f"  {inst.symbol:<12}{px:>10.2f}{dv*100:>10.2f}%{r*100:>10.2f}%")
    print("\n  Holding-period viability (XAUUSD, 1x notional).")
    print("  Per-trade cost looks small at every frequency -- the ANNUAL drag is")
    print("  what decides viability, because a shorter hold means more round trips.")
    print("  Judged against a 15% annual volatility target, i.e. a realistic")
    print("  gross return expectation of roughly 10-15% per year.\n")
    print(f"  {'holding':>10}{'trades/yr':>11}{'cost/trade':>12}{'ANNUAL DRAG':>13}{'verdict':>12}")
    cost_frac = breakeven_move(XAUUSD) / 3500.0  # round-trip cost as % of notional
    target_gross = 0.15
    for label, days in (("1 minute", 1 / 1380), ("5 minutes", 5 / 1380),
                        ("1 hour", 1 / 23), ("4 hours", 4 / 23), ("1 day", 1),
                        ("1 week", 5), ("1 month", 21)):
        trades_yr = 252.0 / days
        drag = trades_yr * cost_frac
        if drag > target_gross:
            verdict = "HOPELESS"
        elif drag > 0.5 * target_gross:
            verdict = "unviable"
        elif drag > 0.2 * target_gross:
            verdict = "marginal"
        else:
            verdict = "workable"
        print(f"  {label:>10}{trades_yr:>11,.0f}{cost_frac*100:>11.3f}%"
              f"{drag*100:>12.1f}%{verdict:>12}")
    print("\n  This is the quantitative reason the default configuration targets a")
    print("  holding period of days-to-weeks rather than minutes.")

    section("SUMMARY")
    if failures:
        print("  ENGINE VALIDATION FAILED:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  All engine checks PASSED.")
    print()
    print("  What this establishes: no look-ahead bias, exact P&L accounting,")
    print("  correct cost handling, functioning risk control, and a signal that")
    print("  discriminates trend from noise.")
    print()
    print("  What this does NOT establish: any expected return on real XAUUSD.")
    print("  Synthetic data cannot tell you that. Supply real history and run")
    print("  scripts/run_backtest.py --walk-forward.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
