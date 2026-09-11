"""Sealed holdout ("lockbox") data splitting.

The one technique that makes iterative strategy research legitimate.

Data is split chronologically into:

    RESEARCH  (first 70%)  -- iterate freely, walk-forward, tune, repeat
    LOCKBOX   (last 30%)   -- SEALED. Opened exactly ONCE, ever.

During iteration the lockbox is never touched, so no amount of searching can
overfit to it. When a candidate finally clears the walk-forward hurdle on the
research set, it is run on the lockbox a single time. That number is the honest
estimate of future performance.

If you open the lockbox twice, it stops being a lockbox and becomes just more
research data. The seal is enforced by recording every open in a file that lives
alongside the ledger, so a second open is visible rather than silent.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from ..backtest import Bar


class LockboxViolation(RuntimeError):
    """Raised on an attempt to open an already-opened lockbox."""


@dataclass
class Split:
    research: List[Bar]
    lockbox: List[Bar]
    research_end_time: str
    lockbox_start_time: str

    @property
    def research_years(self) -> float:
        return len(self.research) / 252.0  # caller rescales by timeframe

    def describe(self, bars_per_year: float) -> str:
        return (f"research {len(self.research):,} bars "
                f"({len(self.research) / bars_per_year:.2f}y, ends {self.research_end_time[:10]})"
                f"  |  LOCKBOX {len(self.lockbox):,} bars "
                f"({len(self.lockbox) / bars_per_year:.2f}y, from {self.lockbox_start_time[:10]})")


def split(bars: Sequence[Bar], research_frac: float = 0.70) -> Split:
    if not 0.4 <= research_frac <= 0.9:
        raise ValueError("research_frac should be between 0.4 and 0.9")
    n = len(bars)
    cut = int(n * research_frac)
    if cut < 200 or n - cut < 200:
        raise ValueError(f"not enough bars to split ({n})")
    return Split(
        research=list(bars[:cut]),
        lockbox=list(bars[cut:]),
        research_end_time=bars[cut - 1].time,
        lockbox_start_time=bars[cut].time,
    )


@dataclass
class SealRecord:
    path: Path

    def opens(self) -> List[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text()).get("opens", [])

    def is_sealed(self, dataset: str) -> bool:
        return not any(o["dataset"] == dataset for o in self.opens())

    def record_open(self, dataset: str, cycle: int, candidate: str,
                    result_sharpe: Optional[float]) -> None:
        opens = self.opens()
        opens.append({
            "dataset": dataset, "cycle": cycle, "candidate": candidate,
            "result_sharpe": result_sharpe, "timestamp": time.time(),
        })
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"opens": opens,
             "warning": "Each dataset may be opened ONCE. A second open means "
                        "the holdout is no longer out-of-sample."},
            indent=2))

    def require_sealed(self, dataset: str) -> None:
        if not self.is_sealed(dataset):
            prior = [o for o in self.opens() if o["dataset"] == dataset]
            raise LockboxViolation(
                f"Lockbox {dataset!r} was already opened "
                f"(cycle {prior[0]['cycle']}, Sharpe {prior[0]['result_sharpe']}).\n"
                f"Opening it again would make it in-sample. To test another "
                f"candidate honestly you need NEW data that has never been used."
            )
