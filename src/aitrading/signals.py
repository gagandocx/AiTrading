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

        if cfg.signal_mode == "reversal":
            # Short-horizon mean reversion: bet against the recent move. The
            # efficiency filter is inverted for this mode, since reversion wants
            # choppy conditions, not clean trends.
            shaped = -shaped
        elif cfg.signal_mode == "long_only_trend":
            shaped = max(0.0, shaped)
        elif cfg.signal_mode != "trend":
            raise ValueError(f"unknown signal_mode {cfg.signal_mode!r}")

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
