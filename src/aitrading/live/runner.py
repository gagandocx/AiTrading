"""Live trading loop.

Cycle, once per closed bar:

    1. read equity and tick
    2. update risk state
    3. fetch bars, compute signal on CLOSED bars only
    4. size the position by volatility target
    5. pass through the risk gate
    6. reconcile the actual position to the approved target
    7. log a structured line

Point 3 is the discipline that makes live behaviour match the backtest: the
signal is computed from completed bars and acted on afterwards, exactly as the
backtester does. Reading a forming bar would make live results better than the
backtest for a while, then much worse.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from ..backtest import TIMEFRAMES
from ..config import Instrument, StrategyConfig
from ..signals import generate
from ..sizing import should_rebalance, target_lots
from .mt5_broker import MT5Broker
from .risk import Decision, RiskLimits, RiskManager, Verdict


@dataclass
class RunnerConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    poll_seconds: float = 5.0
    warmup_bars: int = 600
    dry_run: bool = False          # compute and log, never send orders
    max_cycles: Optional[int] = None
    log_path: Optional[str] = None


@dataclass
class CycleLog:
    time: str
    equity: float
    spread: float
    signal: Optional[float]
    current_lots: float
    target_lots: float
    verdict: str
    reason: str
    action: str = ""

    def line(self) -> str:
        s = "None" if self.signal is None else f"{self.signal:+.3f}"
        return (f"{self.time} eq={self.equity:>10.2f} spr={self.spread:.3f} "
                f"sig={s} pos={self.current_lots:+.2f} tgt={self.target_lots:+.2f} "
                f"{self.verdict:<6} {self.reason}"
                + (f" | {self.action}" if self.action else ""))


class LiveRunner:
    def __init__(self, broker: MT5Broker, inst: Instrument, strategy: StrategyConfig,
                 limits: RiskLimits, cfg: RunnerConfig):
        self.broker = broker
        self.inst = inst
        self.strategy = strategy
        self.cfg = cfg
        self.tf = TIMEFRAMES[cfg.timeframe]
        self.risk = RiskManager(limits, broker.equity())
        self.logs: List[CycleLog] = []
        self._last_bar_time: Optional[int] = None
        self._last_traded_signal = 0.0
        self._session_start = time.time()
        self._last_seen_position = broker.position_lots()

    # ------------------------------------------------------------------
    def _fetch_closed_bars(self):
        """Bars up to and including the last CLOSED one. Never the forming bar."""
        mt5 = self.broker.mt5
        tf_const = getattr(mt5, f"TIMEFRAME_{self.cfg.timeframe}")
        # start_pos=1 skips the currently forming bar.
        rates = mt5.copy_rates_from_pos(self.cfg.symbol, tf_const, 1,
                                        self.cfg.warmup_bars)
        if rates is None or len(rates) == 0:
            return None
        return rates

    def run_once(self) -> Optional[CycleLog]:
        b = self.broker
        equity = b.equity()
        tick = b.tick()
        if tick is None:
            return None

        now = datetime.now()
        self.risk.on_equity_update(equity, now.strftime("%Y-%m-%d"))

        # Detect closed trades so the risk manager sees realised outcomes.
        pos_now = b.position_lots()
        if abs(pos_now) < abs(self._last_seen_position) or pos_now * self._last_seen_position < 0:
            pnl = b.closed_pnl_since(self._session_start)
            self.risk.on_trade_closed(pnl, timestamp=time.time())
        self._last_seen_position = pos_now

        rates = self._fetch_closed_bars()
        if rates is None or len(rates) < self.strategy.warmup_bars():
            return CycleLog(now.strftime("%H:%M:%S"), equity, tick.spread, None,
                            pos_now, pos_now, "wait",
                            f"need {self.strategy.warmup_bars()} bars, "
                            f"have {0 if rates is None else len(rates)}")

        # Only act once per new closed bar.
        newest = int(rates[-1]["time"])
        if self._last_bar_time == newest:
            return None
        self._last_bar_time = newest

        closes = [float(r["close"]) for r in rates]
        sig = generate(closes, self.strategy)
        s = sig.signal[-1]
        v = sig.vol_per_bar[-1]

        if s is None or v is None:
            return CycleLog(now.strftime("%H:%M:%S"), equity, tick.spread, s,
                            pos_now, pos_now, "wait", "signal warming up")

        desired = target_lots(s, v, self.tf.bars_per_year, equity,
                              tick.mid, self.inst, self.strategy)

        if not should_rebalance(pos_now, desired, s, self._last_traded_signal,
                                self.strategy):
            return CycleLog(now.strftime("%H:%M:%S"), equity, tick.spread, s,
                            pos_now, pos_now, "hold", "throttled, no material change")

        decision: Decision = self.risk.evaluate(
            equity=equity, desired_lots=desired, price=tick.mid,
            spread=tick.spread, contract_size=b.contract_size,
            hour=now.hour, timestamp=time.time(),
        )

        target = desired
        if decision.verdict == Verdict.REDUCE:
            target = max(-decision.max_lots, min(decision.max_lots, desired))
        elif not decision.allowed:
            # On HALT, flatten. On BLOCK, hold what we have.
            target = 0.0 if decision.verdict == Verdict.HALT else pos_now

        log = CycleLog(now.strftime("%H:%M:%S"), equity, tick.spread, s,
                       pos_now, target, decision.verdict.value, decision.reason)

        if self.cfg.dry_run:
            log.action = "DRY RUN, no order sent"
        elif abs(target - pos_now) >= b.min_lot:
            res = b.reconcile_to(target)
            if res is None:
                log.action = "no order needed"
            elif res.ok:
                log.action = f"FILLED {res.filled_lots:.2f} @ {res.price:.2f}"
                self._last_traded_signal = s
            else:
                log.action = f"REJECTED retcode={res.retcode} {res.comment}"
        return log

    def run(self) -> None:
        cycles = 0
        print(f"live runner: {self.cfg.symbol} {self.cfg.timeframe} "
              f"{'DRY RUN' if self.cfg.dry_run else 'ARMED'} "
              f"account={self.broker.account_login} "
              f"{'DEMO' if self.broker.is_demo else 'LIVE'}")
        try:
            while self.cfg.max_cycles is None or cycles < self.cfg.max_cycles:
                log = self.run_once()
                if log:
                    self.logs.append(log)
                    print(log.line(), flush=True)
                    if self.cfg.log_path:
                        with open(self.cfg.log_path, "a") as fh:
                            fh.write(log.line() + "\n")
                    if log.verdict == Verdict.HALT.value:
                        print("HALTED. Flattening and exiting.", flush=True)
                        if not self.cfg.dry_run:
                            self.broker.close_all()
                        break
                cycles += 1
                time.sleep(self.cfg.poll_seconds)
        except KeyboardInterrupt:
            print("\ninterrupted; leaving positions untouched "
                  "(use --flatten-on-exit to close)", flush=True)
