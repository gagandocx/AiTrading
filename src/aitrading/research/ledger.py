"""Cumulative search ledger.

The central problem with iterative research is that every hypothesis you test
raises the chance that your best result is luck. A single walk-forward deflated
against its own grid is honest. Fifty walk-forwards, keeping the best, is not --
unless you deflate against the TOTAL number of configurations ever examined.

This ledger persists that count across cycles, machines and sessions. It is the
mechanism that stops an automated loop from becoming an overfitting machine: the
hurdle rises monotonically, so "keep trying until it looks good" cannot converge
on a false positive without the ledger exposing it.

The ledger is append-only. Deleting it to lower the hurdle is the research
equivalent of deleting your losing trades before showing someone your track
record.
"""

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..metrics import expected_max_sharpe


@dataclass
class CycleRecord:
    cycle: int
    timestamp: float
    description: str
    configs_tested: int
    timeframe: str
    best_raw_sharpe: Optional[float]
    best_deflated_vs_cycle: Optional[float]
    best_deflated_vs_cumulative: Optional[float]
    oos_years: float
    notes: str = ""


@dataclass
class Ledger:
    path: Path
    cycles: List[CycleRecord] = field(default_factory=list)

    # ---- persistence -----------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "Ledger":
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        raw = json.loads(p.read_text())
        return cls(path=p, cycles=[CycleRecord(**c) for c in raw.get("cycles", [])])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"cycles": [asdict(c) for c in self.cycles],
             "cumulative_configs": self.cumulative_configs,
             "warning": "APPEND-ONLY. Deleting entries invalidates every "
                        "subsequent significance claim."},
            indent=2))

    # ---- accounting ------------------------------------------------------
    @property
    def cumulative_configs(self) -> int:
        return sum(c.configs_tested for c in self.cycles)

    @property
    def next_cycle_number(self) -> int:
        return len(self.cycles) + 1

    def hurdle(self, oos_years: float, additional_configs: int = 0) -> float:
        """Sharpe a zero-edge search of this size is expected to produce."""
        if oos_years <= 0:
            return float("inf")
        se = (1.0 / oos_years) ** 0.5
        n = self.cumulative_configs + additional_configs
        return expected_max_sharpe(max(n, 1), se)

    def find_identical(self, description: str, configs_tested: int,
                       timeframe: str) -> Optional[CycleRecord]:
        """Locate a prior cycle testing the same hypotheses on the same data."""
        for c in self.cycles:
            if (c.description == description and c.configs_tested == configs_tested
                    and c.timeframe == timeframe):
                return c
        return None

    def record(self, description: str, configs_tested: int, timeframe: str,
               best_raw_sharpe: Optional[float], oos_years: float,
               notes: str = "") -> CycleRecord:
        """Append a cycle, unless it is a re-run of an identical one.

        Re-running the same hypotheses on the same data is verification, not new
        search: it examines no configurations that were not already examined. If
        it incremented the count, the hurdle would climb every time someone
        reproduced a result, which would punish exactly the behaviour we want.
        """
        prior = self.find_identical(description, configs_tested, timeframe)
        if prior is not None:
            return prior

        cycle_hurdle = expected_max_sharpe(
            max(configs_tested, 1), (1.0 / oos_years) ** 0.5) if oos_years > 0 else 0.0
        cum_hurdle = self.hurdle(oos_years, additional_configs=configs_tested)
        rec = CycleRecord(
            cycle=self.next_cycle_number,
            timestamp=time.time(),
            description=description,
            configs_tested=configs_tested,
            timeframe=timeframe,
            best_raw_sharpe=best_raw_sharpe,
            best_deflated_vs_cycle=(None if best_raw_sharpe is None
                                    else best_raw_sharpe - cycle_hurdle),
            best_deflated_vs_cumulative=(None if best_raw_sharpe is None
                                         else best_raw_sharpe - cum_hurdle),
            oos_years=oos_years,
            notes=notes,
        )
        self.cycles.append(rec)
        return rec

    def summary(self) -> str:
        if not self.cycles:
            return "ledger empty: no cycles run yet"
        L = [f"SEARCH LEDGER  ({len(self.cycles)} cycles, "
             f"{self.cumulative_configs:,} configurations examined)", ""]
        L.append(f"  {'cyc':>4}{'configs':>9}{'tf':>5}{'raw SR':>8}"
                 f"{'vs cycle':>10}{'vs CUMULATIVE':>15}  description")
        for c in self.cycles:
            raw = "n/a" if c.best_raw_sharpe is None else f"{c.best_raw_sharpe:.2f}"
            dc = "n/a" if c.best_deflated_vs_cycle is None else f"{c.best_deflated_vs_cycle:+.2f}"
            dk = ("n/a" if c.best_deflated_vs_cumulative is None
                  else f"{c.best_deflated_vs_cumulative:+.2f}")
            L.append(f"  {c.cycle:>4}{c.configs_tested:>9,}{c.timeframe:>5}"
                     f"{raw:>8}{dc:>10}{dk:>15}  {c.description[:40]}")
        L.append("")
        L.append("  'vs CUMULATIVE' is the only column that can support a claim.")
        return "\n".join(L)
