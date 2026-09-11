"""MetaTrader 5 data adapter.

Requires the `MetaTrader5` package and a running MT5 terminal on Windows
(or Wine). This module is deliberately the ONLY place the MT5 dependency
appears, so the engine and all tests stay importable without it.

Your MT5 terminal is a free source of years of XAUUSD history. Increase it via
Tools -> Options -> Charts -> "Max bars in chart" = Unlimited, then open a
XAUUSD chart on your target timeframe and scroll back to force a full download.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from ..backtest import Bar

_TF_NAMES = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
             "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}

# Maximum span worth downloading per timeframe, in years.
#
# Intraday data is for calibrating execution costs, not for estimating edge --
# the standard error of a Sharpe estimate depends on calendar span, not on
# sampling frequency, so 15 years of M1 (5.2M bars) buys nothing over 15 years
# of D1 (3.8k bars). These caps stop an innocent "--years 15" from requesting
# millions of rows that serve no purpose.
_MAX_YEARS = {
    # M1/M5 remain capped: they exist to measure the spread and slippage
    # distribution, and a month of that is plenty. Years of M1 would be millions
    # of rows serving no purpose.
    "M1": 30.0 / 365.0,    # ~1 month
    "M5": 90.0 / 365.0,    # ~3 months
    # M15/H1/H4 are used for EDGE ESTIMATION on intraday strategies in the
    # 5-20 trades/day band, so span is the binding constraint on whether the
    # test can conclude anything (Sharpe SE = 1/sqrt(years)). Take everything
    # the broker will give: 15 years of H1 is ~87k rows, which is trivial.
    "M15": 5.0,
    "H1": 15.0,
    "H4": 25.0,
    "D1": 40.0,
}


def span_for(timeframe: str, requested_years: float) -> float:
    """Clamp a requested span to something sensible for the timeframe."""
    return min(requested_years, _MAX_YEARS.get(timeframe, requested_years))


def _require_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "MetaTrader5 is not installed. Run: pip install 'aitrading[mt5]'\n"
            "Note: the package requires Windows (or Wine) and a running MT5 terminal."
        ) from exc
    return mt5


def connect(login: Optional[int] = None, password: Optional[str] = None,
            server: Optional[str] = None, path: Optional[str] = None) -> None:
    mt5 = _require_mt5()
    kwargs = {}
    if path:
        kwargs["path"] = path
    if login:
        kwargs.update(login=login, password=password, server=server)
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")


def shutdown() -> None:
    mt5 = _require_mt5()
    mt5.shutdown()


def resolve_symbol(preferred: str) -> str:
    """Find the broker's actual name for a symbol.

    Brokers rename things constantly: XAUUSD, GOLD, XAUUSD.raw, XAUUSDm,
    XAUUSD_ecn. This searches for a match instead of failing.
    """
    mt5 = _require_mt5()
    if mt5.symbol_info(preferred) is not None:
        return preferred
    base = preferred.upper()
    candidates = []
    for s in mt5.symbols_get() or []:
        name = s.name.upper()
        if name.startswith(base) or (base == "XAUUSD" and "GOLD" in name):
            candidates.append(s.name)
    if not candidates:
        raise RuntimeError(f"No symbol matching {preferred!r} at this broker")
    candidates.sort(key=len)
    return candidates[0]


def fetch(symbol: str, timeframe: str, years: float = 10.0) -> List[Bar]:
    """Download historical bars. Returns oldest-first."""
    mt5 = _require_mt5()
    if timeframe not in _TF_NAMES:
        raise ValueError(f"timeframe must be one of {sorted(_TF_NAMES)}")
    tf_const = getattr(mt5, _TF_NAMES[timeframe])

    end = datetime.now()
    start = end - timedelta(days=int(365.25 * years))
    rates = mt5.copy_rates_range(symbol, tf_const, start, end)
    if rates is None or len(rates) == 0:
        raise RuntimeError(
            f"No history returned for {symbol} {timeframe}: {mt5.last_error()}\n"
            "Open a chart for this symbol/timeframe in MT5 and scroll back to "
            "force the terminal to download history, then retry."
        )
    return [
        Bar(
            time=datetime.fromtimestamp(int(r["time"])).strftime("%Y-%m-%d %H:%M:%S"),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
        )
        for r in rates
    ]


def measure_costs(symbol: str, samples: int = 60, delay_s: float = 1.0) -> dict:
    """Sample the live spread so the cost model uses YOUR broker's real numbers.

    Run this during your intended trading hours. A spread sampled at 3am London
    is not the spread you will actually pay.
    """
    import statistics
    import time

    mt5 = _require_mt5()
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) returned None")

    spreads = []
    for _ in range(samples):
        t = mt5.symbol_info_tick(symbol)
        if t and t.ask > 0 and t.bid > 0:
            spreads.append(t.ask - t.bid)
        time.sleep(delay_s)

    if not spreads:
        raise RuntimeError("no ticks captured; is the market open?")

    return {
        "symbol": symbol,
        "contract_size": float(info.trade_contract_size),
        "digits": int(info.digits),
        "min_lot": float(info.volume_min),
        "lot_step": float(info.volume_step),
        "max_lot": float(info.volume_max),
        "median_spread": statistics.median(spreads),
        "mean_spread": statistics.fmean(spreads),
        "p90_spread": sorted(spreads)[int(0.9 * (len(spreads) - 1))],
        "half_spread_suggested": statistics.median(spreads) / 2.0,
        "samples": len(spreads),
    }
