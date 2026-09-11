#!/usr/bin/env python3
"""Run the bot against MT5. Demo accounts only, unless you override it.

Start here -- observe without trading:

    python scripts\\run_live.py --dry-run

Then arm it on a DEMO account:

    python scripts\\run_live.py --timeframe M5 --trades-per-day 60

Frequency is yours to set. What the validation actually found, on this account's
own data (docs/results/xauusd-findings.md):

    trades/day    return over 22 days    max DD    friction / gross P&L
         282.7                 -9.73%   -10.42%                    7.57
         193.8                 -7.59%    -8.52%                     n/a
         104.6                 -3.83%    -6.01%                   39.30
          53.0                 +0.11%    -2.17%                    0.94

Higher frequency was worse on BOTH return and drawdown at every step, and even
the best row is statistically indistinguishable from zero over 22 days. The
default here is the least-bad point on that curve, not a validated edge.
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitrading.config import REGISTRY, StrategyConfig  # noqa: E402
from aitrading.live.mt5_broker import LiveAccountRefused, MT5Broker  # noqa: E402
from aitrading.live.risk import RiskLimits  # noqa: E402
from aitrading.live.runner import LiveRunner, RunnerConfig  # noqa: E402

# Frequency presets, mapped from the measured curve above.
PRESETS = {
    #  name        lookbacks          throttle  sig-change  scale
    "calm":     ([120, 240, 480],     0.05,     0.25,       1.0),
    "balanced": ([30, 60, 120],       0.03,     0.15,       1.0),   # default
    "fast":     ([10, 20, 40],        0.02,     0.05,       1.5),
    "veryfast": ([3, 8, 15],          0.01,     0.01,       2.0),
    "ultra":    ([2, 3, 5],           0.01,     0.005,      3.0),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="M5", choices=["M1", "M5", "H1", "H4", "D1"])
    ap.add_argument("--preset", default="balanced", choices=sorted(PRESETS))
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and log everything, send no orders")
    ap.add_argument("--poll-seconds", type=float, default=5.0)
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--log", default=None, help="append cycle log to this file")

    # risk
    ap.add_argument("--target-vol", type=float, default=0.15)
    ap.add_argument("--max-daily-loss", type=float, default=0.02)
    ap.add_argument("--max-drawdown", type=float, default=0.10)
    ap.add_argument("--max-lots", type=float, default=0.02)
    ap.add_argument("--max-leverage", type=float, default=2.0)
    ap.add_argument("--trades-per-day", type=int, default=100)
    ap.add_argument("--max-spread", type=float, default=0.20)
    ap.add_argument("--median-spread", type=float, default=0.06)
    ap.add_argument("--blocked-hours", type=int, nargs="*", default=[23, 0])

    ap.add_argument("--i-understand-live-risk", action="store_true",
                    help="permit a real-money account (strongly discouraged)")
    ap.add_argument("--terminal-path", default=None)
    args = ap.parse_args()

    lbs, throttle, sigchg, scale = PRESETS[args.preset]
    strategy = StrategyConfig(
        lookbacks=lbs, min_rebalance_lots=throttle, min_signal_change=sigchg,
        signal_scale=scale, target_vol_annual=args.target_vol,
        max_leverage=args.max_leverage, use_efficiency_filter=True,
        er_threshold=0.20, stop_atr_multiple=3.0,
        max_drawdown_halt=args.max_drawdown,
    )
    limits = RiskLimits(
        max_daily_loss_pct=args.max_daily_loss,
        max_drawdown_pct=args.max_drawdown,
        max_position_lots=args.max_lots,
        max_leverage=args.max_leverage,
        max_trades_per_day=args.trades_per_day,
        max_spread=args.max_spread,
        median_spread=args.median_spread,
        blocked_hours=list(args.blocked_hours),
    )

    try:
        broker = MT5Broker(args.symbol, allow_live=args.i_understand_live_risk,
                           terminal_path=args.terminal_path)
    except LiveAccountRefused as e:
        print(f"\nREFUSED\n{e}\n")
        return 2

    inst = replace(REGISTRY.get(args.symbol, REGISTRY["XAUUSD"]),
                   symbol=args.symbol, contract_size=broker.contract_size,
                   min_lot=broker.min_lot, lot_step=broker.lot_step,
                   max_lot=broker.max_lot, digits=broker.digits,
                   half_spread=args.median_spread / 2.0)

    equity = broker.equity()
    min_notional = broker.min_lot * broker.contract_size
    tick = broker.tick()
    if tick:
        min_notional *= tick.mid

    print(f"\naccount   {broker.account_login} "
          f"{'DEMO' if broker.is_demo else '*** LIVE ***'} ({broker.currency})")
    print(f"equity    {equity:,.2f}")
    print(f"preset    {args.preset}  timeframe {args.timeframe}")
    print(f"min size  {broker.min_lot} lots = {min_notional:,.0f} notional "
          f"= {min_notional / equity:.1f}x equity")
    if min_notional / equity > 1.0:
        print("\n  WARNING: the smallest position your broker allows exceeds your")
        print("  equity. Volatility targeting cannot reduce risk below this floor.")
        print("  Expected drawdown is governed by account size, not by settings.")
    print()

    runner = LiveRunner(broker, inst, strategy, limits, RunnerConfig(
        symbol=args.symbol, timeframe=args.timeframe, dry_run=args.dry_run,
        poll_seconds=args.poll_seconds, max_cycles=args.max_cycles,
        log_path=args.log,
    ))
    try:
        runner.run()
    finally:
        broker.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
