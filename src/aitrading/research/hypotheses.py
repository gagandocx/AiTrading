"""Pre-registered hypotheses, one entry per research cycle.

Each cycle must state, BEFORE it runs, what is being tested and why. This is
what separates research from fishing: a named hypothesis with a stated rationale
can be wrong, whereas "try 5000 combinations" cannot.

Keep grids SMALL. Every configuration raises the cumulative hurdle in the
ledger, so a 500-config cycle makes it harder to prove anything, not easier.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List

from ..config import StrategyConfig


@dataclass
class Hypothesis:
    name: str
    rationale: str
    grid: List[StrategyConfig]

    @property
    def size(self) -> int:
        return len(self.grid)


def _cfg(**kw) -> StrategyConfig:
    base = dict(vol_halflife=30, atr_window=14, stop_atr_multiple=3.0,
                max_drawdown_halt=0.0, target_vol_annual=0.15)
    base.update(kw)
    return StrategyConfig(**base)


# --------------------------------------------------------------------------
# CYCLE 1 -- baseline, already run this session on D1/H1. Recorded for the
# ledger so the cumulative count reflects work already done.
# --------------------------------------------------------------------------
def cycle_01() -> List[Hypothesis]:
    return [
        Hypothesis(
            name="trend_multihorizon",
            rationale="Time-series momentum is the most out-of-sample-validated "
                      "systematic signal in futures and FX (Moskowitz/Ooi/Pedersen). "
                      "Tests whether it survives single-instrument gold at measured cost.",
            grid=[_cfg(lookbacks=lb, signal_scale=s, er_threshold=e,
                       use_efficiency_filter=e > 0)
                  for lb in ([10, 30, 60], [20, 60, 120], [40, 120, 240])
                  for s in (1.0, 2.0) for e in (0.0, 0.20)],
        ),
    ]


# --------------------------------------------------------------------------
# CYCLE 2 -- the GaganEA_v2.10 components worth salvaging.
#
# The prior EA's entry logic was shown to be noise: its chart-pattern detectors
# fire at identical rates on real gold and on synthetic random walks (~40% of
# bars). Its EXIT and RISK logic, however, is genuinely developed. This cycle
# tests whether the salvageable ideas add value on top of a real signal:
#
#   1. Multi-timeframe alignment (its H1 EMA200 + M5 EMA200 gate) -- approximated
#      here by requiring agreement between a slow and a fast trend horizon.
#   2. Correct reward:risk. The EA needed a 71.5% win rate to break even
#      (SL 2500 / T1 800 closing 65%). Tests wider stops instead.
#   3. Trend-strength gating, which is what its ADX filter was reaching for.
# --------------------------------------------------------------------------
def cycle_02() -> List[Hypothesis]:
    return [
        Hypothesis(
            name="mtf_alignment",
            rationale="Port of GaganEA's H1+M5 EMA alignment gate. Requiring a slow "
                      "and fast horizon to agree should cut whipsaw. Tests whether "
                      "that gate adds value once the fake pattern filter is removed.",
            grid=[_cfg(lookbacks=[f, f * 4, f * 12], signal_scale=1.5,
                       er_threshold=e, use_efficiency_filter=e > 0)
                  for f in (10, 20) for e in (0.25, 0.35)],
        ),
        Hypothesis(
            name="wide_stop_correct_rr",
            rationale="GaganEA required a 71.5% win rate to break even because its "
                      "first target closed 65% of the position at 0.32R. Tests whether "
                      "a correct reward:risk profile (wide stops, let winners run) "
                      "changes the outcome on the same instrument.",
            grid=[_cfg(lookbacks=[20, 60, 120], signal_scale=1.0,
                       stop_atr_multiple=sm, er_threshold=0.20,
                       use_efficiency_filter=True)
                  for sm in (0.0, 4.0, 6.0, 8.0)],
        ),
    ]


CYCLES: Dict[int, Callable[[], List[Hypothesis]]] = {
    1: cycle_01,
    2: cycle_02,
}


def get(cycle: int) -> List[Hypothesis]:
    if cycle not in CYCLES:
        raise KeyError(f"no hypotheses registered for cycle {cycle}. "
                       f"Available: {sorted(CYCLES)}")
    return CYCLES[cycle]()
