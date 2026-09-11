"""A library of distinct, widely-documented strategy families.

Each function returns a per-bar exposure in [-1, +1], aligned to the input bars,
with None where the signal is not yet defined. Every one uses information up to
and including bar i only -- the backtester executes at bar i+1's open.

These are separate HYPOTHESES, not reparameterisations of one idea. Some trade
with the move (ma_cross, macd, keltner, atr_breakout, orb), some against it
(rsi_reversion, stoch_reversion, twap_reversion), and they disagree with each
other by construction. That matters: a library where everything is secretly
momentum tells you nothing when momentum fails.
"""

import math
from typing import List, Optional, Sequence

from .indicators import atr, ema, ewma_vol, log_returns

Num = Optional[float]


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _hour(ts: str) -> Optional[int]:
    try:
        return int(ts.split(" ")[1].split(":")[0])
    except (IndexError, ValueError):
        return None


def _day(ts: str) -> str:
    return ts.split(" ")[0]


# --------------------------------------------------------------------------
# Trend-following families
# --------------------------------------------------------------------------
def ma_cross(closes: Sequence[float], fast: int, slow: int) -> List[Num]:
    """Dual moving-average crossover. The oldest systematic rule there is."""
    f, s = ema(closes, fast), ema(closes, slow)
    out: List[Num] = []
    for i in range(len(closes)):
        if i < slow * 2:
            out.append(None)
            continue
        out.append(1.0 if f[i] > s[i] else -1.0)
    return out


def macd(closes: Sequence[float], fast: int, slow: int, signal: int) -> List[Num]:
    """MACD histogram sign: (fastEMA - slowEMA) versus its own EMA."""
    f, s = ema(closes, fast), ema(closes, slow)
    line = [(f[i] - s[i]) if f[i] is not None and s[i] is not None else 0.0
            for i in range(len(closes))]
    sig = ema(line, signal)
    out: List[Num] = []
    for i in range(len(closes)):
        if i < slow * 2 + signal:
            out.append(None)
            continue
        out.append(1.0 if line[i] > sig[i] else -1.0)
    return out


def keltner_breakout(highs, lows, closes, window: int, mult: float) -> List[Num]:
    """Break of an ATR-width band around a moving average."""
    mid = ema(closes, window)
    a = atr(highs, lows, closes, window)
    out: List[Num] = []
    for i in range(len(closes)):
        if i < window * 2 or a[i] is None or mid[i] is None:
            out.append(None)
            continue
        upper, lower = mid[i] + mult * a[i], mid[i] - mult * a[i]
        if closes[i] > upper:
            out.append(1.0)
        elif closes[i] < lower:
            out.append(-1.0)
        else:
            out.append(0.0)
    return out


def atr_breakout(highs, lows, closes, lookback: int, mult: float) -> List[Num]:
    """Volatility breakout: price has moved more than mult x ATR over lookback."""
    a = atr(highs, lows, closes, lookback)
    out: List[Num] = []
    for i in range(len(closes)):
        if i < lookback * 2 or a[i] is None or a[i] <= 0:
            out.append(None)
            continue
        move = closes[i] - closes[i - lookback]
        z = move / (a[i] * math.sqrt(lookback))
        out.append(_clip(z / mult) if abs(z) > mult * 0.5 else 0.0)
    return out


def opening_range_breakout(
    times: Sequence[str], highs, lows, closes, range_bars: int
) -> List[Num]:
    """Opening-range breakout: trade a break of the session's first N bars.

    A genuinely intraday rule with its own published evidence, and structurally
    different from the others here because it is anchored to the session clock
    rather than to a rolling window. Flat until the opening range completes, and
    flat again at the session end.
    """
    out: List[Num] = [None] * len(closes)
    day_start = 0
    cur_day = _day(times[0]) if times else ""
    hi = lo = None
    for i in range(len(closes)):
        d = _day(times[i])
        if d != cur_day:
            cur_day, day_start, hi, lo = d, i, None, None
        n_into = i - day_start
        if n_into < range_bars:
            out[i] = 0.0                       # still forming the range
            continue
        if hi is None:
            hi = max(highs[day_start:day_start + range_bars])
            lo = min(lows[day_start:day_start + range_bars])
        if closes[i] > hi:
            out[i] = 1.0
        elif closes[i] < lo:
            out[i] = -1.0
        else:
            out[i] = 0.0
    return out


# --------------------------------------------------------------------------
# Mean-reversion families
# --------------------------------------------------------------------------
def _rsi(closes: Sequence[float], period: int) -> List[Num]:
    out: List[Num] = [None] * len(closes)
    gains, losses = 0.0, 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if i <= period:
            gains += g
            losses += l
            if i == period:
                ag, al = gains / period, losses / period
                out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
                _rsi._ag, _rsi._al = ag, al
            continue
        ag = (_rsi._ag * (period - 1) + g) / period
        al = (_rsi._al * (period - 1) + l) / period
        _rsi._ag, _rsi._al = ag, al
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def rsi_reversion(closes, period: int, os_level: float, ob_level: float) -> List[Num]:
    """Buy oversold, sell overbought, flat in between."""
    r = _rsi(closes, period)
    out: List[Num] = []
    for i, v in enumerate(r):
        if v is None:
            out.append(None)
        elif v <= os_level:
            out.append(1.0)
        elif v >= ob_level:
            out.append(-1.0)
        else:
            out.append(0.0)
    return out


def rsi_trend(closes, period: int) -> List[Num]:
    """RSI as a momentum filter rather than a reversion one: long above 50."""
    r = _rsi(closes, period)
    return [None if v is None else (1.0 if v > 50 else -1.0) for v in r]


def stoch_reversion(highs, lows, closes, window: int, os_level: float,
                    ob_level: float) -> List[Num]:
    """Stochastic oscillator reversion: position within the recent high-low range."""
    out: List[Num] = []
    for i in range(len(closes)):
        if i < window:
            out.append(None)
            continue
        hh = max(highs[i - window + 1:i + 1])
        ll = min(lows[i - window + 1:i + 1])
        if hh <= ll:
            out.append(0.0)
            continue
        k = 100.0 * (closes[i] - ll) / (hh - ll)
        out.append(1.0 if k <= os_level else (-1.0 if k >= ob_level else 0.0))
    return out


def twap_reversion(times: Sequence[str], closes, entry_z: float) -> List[Num]:
    """Reversion to the session's running average price.

    A volume-weighted version (VWAP) is the standard desk tool; MT5 bar exports
    here carry no volume, so this uses the time-weighted average and is named
    accordingly rather than pretending to be VWAP.
    """
    out: List[Num] = [None] * len(closes)
    vol = ewma_vol(log_returns(closes), 50)
    run_sum, n = 0.0, 0
    cur_day = _day(times[0]) if times else ""
    for i in range(len(closes)):
        d = _day(times[i])
        if d != cur_day:
            cur_day, run_sum, n = d, 0.0, 0
        run_sum += closes[i]
        n += 1
        if n < 10 or vol[i] is None or vol[i] <= 0:
            out[i] = 0.0
            continue
        twap = run_sum / n
        sd = vol[i] * twap * math.sqrt(n)
        if sd <= 0:
            out[i] = 0.0
            continue
        z = (closes[i] - twap) / sd
        if z >= entry_z:
            out[i] = -1.0
        elif z <= -entry_z:
            out[i] = 1.0
        else:
            out[i] = 0.0
    return out
