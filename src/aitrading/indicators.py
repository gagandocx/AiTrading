"""Pure-stdlib indicators.

Every function is streaming-safe (no look-ahead) and returns a list the same
length as its input, with None where the value is not yet defined. That
None-padding convention is what makes look-ahead bugs obvious instead of silent.
"""

import math
from typing import List, Optional, Sequence

Num = Optional[float]


def ema(values: Sequence[float], halflife: float) -> List[Num]:
    """Exponential moving average parameterised by half-life in bars."""
    if halflife <= 0:
        raise ValueError("halflife must be positive")
    alpha = 1.0 - math.exp(-math.log(2.0) / halflife)
    out: List[Num] = []
    state: Optional[float] = None
    for v in values:
        state = v if state is None else state + alpha * (v - state)
        out.append(state)
    return out


def log_returns(closes: Sequence[float]) -> List[Num]:
    """Bar-over-bar log returns; first element is None."""
    out: List[Num] = [None]
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        out.append(math.log(cur / prev) if prev > 0 and cur > 0 else 0.0)
    return out


def ewma_vol(returns: Sequence[Num], halflife: float, floor: float = 1e-9) -> List[Num]:
    """EWMA volatility of returns, per bar (not annualised).

    Uses the mean-zero convention (E[r]=0), standard for short-horizon vol and
    more stable than subtracting a noisy drift estimate.
    """
    alpha = 1.0 - math.exp(-math.log(2.0) / halflife)
    out: List[Num] = []
    var: Optional[float] = None
    for r in returns:
        if r is None:
            out.append(None)
            continue
        var = r * r if var is None else var + alpha * (r * r - var)
        out.append(max(math.sqrt(var), floor))
    return out


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> List[Num]:
    out: List[Num] = [None]
    for i in range(1, len(closes)):
        pc = closes[i - 1]
        out.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int
) -> List[Num]:
    """Wilder-style ATR using an EMA of true range."""
    tr = true_range(highs, lows, closes)
    valid = [t for t in tr if t is not None]
    if not valid:
        return [None] * len(closes)
    smoothed = ema(valid, halflife=window)
    out: List[Num] = [None]
    out.extend(smoothed)
    return out[: len(closes)]


def efficiency_ratio(closes: Sequence[float], window: int) -> List[Num]:
    """Kaufman efficiency ratio: net directional travel / total path travel.

    Ranges 0..1. Near 1 means a clean directional move; near 0 means chop.
    Gating a trend signal on this is the cheapest available defence against
    whipsaw when you only have one instrument to trade.
    """
    out: List[Num] = [None] * len(closes)
    if window < 1:
        raise ValueError("window must be >= 1")
    # `path` holds the sum of |diff| over the last `window` steps, which spans
    # prices closes[i-window] .. closes[i]. The numerator must span exactly the
    # same prices or the ratio is not bounded by 1.
    path = 0.0
    for i in range(1, len(closes)):
        path += abs(closes[i] - closes[i - 1])
        if i > window:
            path -= abs(closes[i - window] - closes[i - window - 1])
        if i >= window:
            net = abs(closes[i] - closes[i - window])
            out[i] = (net / path) if path > 0 else 0.0
    return out


def rolling_max(values: Sequence[float], window: int) -> List[Num]:
    out: List[Num] = []
    for i in range(len(values)):
        out.append(max(values[i - window + 1 : i + 1]) if i >= window - 1 else None)
    return out


def rolling_min(values: Sequence[float], window: int) -> List[Num]:
    out: List[Num] = []
    for i in range(len(values)):
        out.append(min(values[i - window + 1 : i + 1]) if i >= window - 1 else None)
    return out
