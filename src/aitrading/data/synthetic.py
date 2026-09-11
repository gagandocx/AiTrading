"""Synthetic price generators with KNOWN statistical properties.

These exist to validate the ENGINE, never to estimate strategy performance.
Because we know the ground truth of each process, we know what a correct
backtester must report:

  random_walk    -> zero true edge. Engine MUST lose approximately its cost
                    drag. Any profit here proves a look-ahead or accounting bug.
  trending       -> persistent drift regimes. A trend engine MUST profit gross.
  mean_reverting -> OU process. A trend engine MUST lose.

Results on synthetic data say nothing about XAUUSD. Use scripts/run_backtest.py
with real MT5 history for that.
"""

import math
import random
from typing import List

from ..backtest import Bar


def _path_to_bars(path: List[float], substeps: int, seed: int) -> List[Bar]:
    """Convert a close-to-close path into OHLC bars with plausible wicks."""
    rng = random.Random(seed + 99991)
    bars: List[Bar] = []
    for i in range(1, len(path)):
        o, c = path[i - 1], path[i]
        # Simulate an intrabar Brownian bridge to get a realistic high/low.
        hi, lo = max(o, c), min(o, c)
        step_sd = abs(c - o) / math.sqrt(substeps) if c != o else abs(o) * 1e-5
        x = o
        for _ in range(substeps):
            x += rng.gauss(0.0, step_sd)
            hi, lo = max(hi, x), min(lo, x)
        bars.append(Bar(time=f"t{i}", open=o, high=hi, low=lo, close=c))
    return bars


def random_walk(n: int, start: float = 3500.0, vol_per_bar: float = 0.012, seed: int = 7) -> List[Bar]:
    """Driftless geometric random walk. TRUE EDGE = ZERO by construction."""
    rng = random.Random(seed)
    path = [start]
    for _ in range(n):
        path.append(path[-1] * math.exp(rng.gauss(0.0, vol_per_bar)))
    return _path_to_bars(path, substeps=6, seed=seed)


def trending(
    n: int,
    start: float = 3500.0,
    vol_per_bar: float = 0.012,
    drift_per_bar: float = 0.0035,
    regime_len: int = 120,
    seed: int = 7,
) -> List[Bar]:
    """Regime-switching drift: persistent up/down trends plus noise.

    A working trend-following engine MUST make money gross on this series.
    """
    rng = random.Random(seed)
    path = [start]
    direction = 1.0
    for i in range(n):
        if i % regime_len == 0:
            direction = 1.0 if rng.random() < 0.5 else -1.0
        mu = direction * drift_per_bar
        path.append(path[-1] * math.exp(mu + rng.gauss(0.0, vol_per_bar)))
    return _path_to_bars(path, substeps=6, seed=seed)


def mean_reverting(
    n: int,
    start: float = 3500.0,
    vol_per_bar: float = 0.012,
    kappa: float = 0.08,
    seed: int = 7,
) -> List[Bar]:
    """Ornstein-Uhlenbeck in log price. A trend engine MUST lose on this."""
    rng = random.Random(seed)
    anchor = math.log(start)
    x = anchor
    path = [start]
    for _ in range(n):
        x += kappa * (anchor - x) + rng.gauss(0.0, vol_per_bar)
        path.append(math.exp(x))
    return _path_to_bars(path, substeps=6, seed=seed)
