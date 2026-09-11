"""Signal generation: a risk-normalised, multi-horizon trend ensemble.

Why this and not something cleverer: time-series momentum is the most
out-of-sample-validated systematic signal in futures and FX (Moskowitz, Ooi &
Pedersen 2012; Hurst, Ooi & Pedersen's century study). On a single instrument we
cannot get breadth from markets, so we get robustness from averaging horizons
instead of optimising one.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .config import StrategyConfig
from .indicators import efficiency_ratio, ewma_vol, log_returns


@dataclass
class SignalSeries:
    """Per-bar signal state. All lists are aligned to the input bars."""

    signal: List[Optional[float]]  # desired exposure in [-1, +1]
    vol_per_bar: List[Optional[float]]  # EWMA volatility, per bar
    efficiency: List[Optional[float]]
    raw_score: List[Optional[float]]  # pre-squash blended z-score

    def __len__(self) -> int:
        return len(self.signal)


def _risk_adjusted_momentum(
    closes: Sequence[float], i: int, lookback: int, vol_per_bar: float
) -> Optional[float]:
    """Momentum over `lookback` bars, scaled by the volatility of that horizon.

    Dividing by vol * sqrt(lookback) makes the score comparable across horizons
    and across volatility regimes -- without it, long look-backs dominate purely
    because they span bigger moves.
    """
    if i < lookback or vol_per_bar <= 0:
        return None
    past, now = closes[i - lookback], closes[i]
    if past <= 0 or now <= 0:
        return None
    horizon_vol = vol_per_bar * math.sqrt(lookback)
    if horizon_vol <= 0:
        return None
    return math.log(now / past) / horizon_vol


def generate(
    closes: Sequence[float],
    cfg: StrategyConfig,
) -> SignalSeries:
    """Compute the exposure signal for every bar.

    Contract: `signal[i]` uses information up to and including the close of bar
    `i` only. The backtester must therefore act on it no earlier than bar i+1.
    """
    n = len(closes)
    rets = log_returns(closes)
    vol = ewma_vol(rets, cfg.vol_halflife, cfg.vol_floor)
    er = efficiency_ratio(closes, cfg.er_window) if cfg.use_efficiency_filter else [None] * n

    signal: List[Optional[float]] = [None] * n
    raw: List[Optional[float]] = [None] * n

    for i in range(n):
        v = vol[i]
        if v is None:
            continue

        scores = []
        for lb in cfg.lookbacks:
            s = _risk_adjusted_momentum(closes, i, lb, v)
            if s is not None:
                scores.append(s)
        if len(scores) != len(cfg.lookbacks):
            continue  # require every horizon to be available -> no partial warmup

        blended = sum(scores) / len(scores)
        raw[i] = blended

        # tanh squash: bounded exposure, and it de-emphasises extreme readings
        # rather than piling on after a move has already happened.
        shaped = math.tanh(cfg.signal_scale * blended)
        shaped = max(-cfg.max_signal, min(cfg.max_signal, shaped))

        mode = cfg.signal_mode
        if mode == "reversal":
            # Short-horizon mean reversion: bet against the recent move. The
            # efficiency filter is inverted for this mode, since reversion wants
            # choppy conditions, not clean trends.
            shaped = -shaped
        elif mode == "long_only_trend":
            shaped = max(0.0, shaped)
        elif mode in ("breakout", "donchian_exit"):
            shaped = _breakout_signal(closes, i, cfg, prev=signal[i - 1] if i else None)
            if shaped is None:
                continue
        elif mode == "bollinger":
            shaped = _bollinger_signal(closes, i, cfg, v, prev=signal[i - 1] if i else None)
            if shaped is None:
                continue
        elif mode != "trend":
            raise ValueError(f"unknown signal_mode {mode!r}")

        if cfg.use_efficiency_filter:
            e = er[i]
            if e is None:
                shaped = 0.0
            elif cfg.signal_mode == "reversal":
                # trade reversion only when the market is NOT trending
                if e > cfg.er_threshold:
                    shaped = 0.0
            elif e < cfg.er_threshold:
                shaped = 0.0

        signal[i] = shaped

    return SignalSeries(signal=signal, vol_per_bar=vol, efficiency=er, raw_score=raw)



def _breakout_signal(
    closes: Sequence[float], i: int, cfg: StrategyConfig, prev: Optional[float]
) -> Optional[float]:
    """Donchian channel breakout -- the classic Turtle rule.

    Long when price closes above the highest close of the entry window, short when
    below the lowest. `donchian_exit` additionally holds the position until an
    opposite, shorter channel is breached, which is the original two-window design
    (long entry on a 20-day break, exit on a 10-day break the other way).

    Distinct from `trend`: this is a threshold event on the price extreme, not a
    continuous function of recent return.
    """
    entry_n = cfg.lookbacks[-1]
    if i < entry_n:
        return None
    window = closes[i - entry_n:i]  # strictly prior bars, no look-ahead
    hi, lo = max(window), min(window)
    px = closes[i]

    if px > hi:
        return 1.0
    if px < lo:
        return -1.0

    if cfg.signal_mode == "donchian_exit" and prev:
        exit_n = max(2, entry_n // 2)
        ewin = closes[i - exit_n:i]
        ehi, elo = max(ewin), min(ewin)
        # hold until the opposite shorter channel breaks
        if prev > 0:
            return 0.0 if px < elo else prev
        if prev < 0:
            return 0.0 if px > ehi else prev
    return 0.0


def _bollinger_signal(
    closes: Sequence[float], i: int, cfg: StrategyConfig, vol_per_bar: float,
    prev: Optional[float],
) -> Optional[float]:
    """Counter-trend entry at a volatility extreme, exit back at the mean.

    Enters only when price is more than `entry_z` standard deviations from its
    moving average, and flattens once it recovers to within `exit_z`. The band
    logic is what makes this a different hypothesis from `reversal`, which scales
    exposure continuously with recent return and is therefore always in the market.
    """
    n = cfg.lookbacks[len(cfg.lookbacks) // 2]
    if i < n or vol_per_bar <= 0:
        return None
    window = closes[i - n:i]
    ma = sum(window) / len(window)
    if ma <= 0:
        return None
    sd = vol_per_bar * ma * math.sqrt(n)
    if sd <= 0:
        return None
    z = (closes[i] - ma) / sd

    if abs(z) < cfg.exit_z:
        return 0.0                      # recovered to the mean: flatten
    if z >= cfg.entry_z:
        return -1.0                     # stretched high: short it
    if z <= -cfg.entry_z:
        return 1.0                      # stretched low: buy it
    return prev if prev is not None else 0.0
