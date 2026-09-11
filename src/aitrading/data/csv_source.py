"""Load and save OHLCV bars as CSV. Dependency-free."""

import csv
import os
from typing import List

from ..backtest import Bar

HEADER = ["time", "open", "high", "low", "close"]


def save(bars: List[Bar], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for b in bars:
            w.writerow([b.time, b.open, b.high, b.low, b.close])


def load(path: str) -> List[Bar]:
    bars: List[Bar] = []
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        missing = [c for c in HEADER if c not in (r.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} missing required columns: {missing}")
        for row in r:
            bars.append(
                Bar(
                    time=row["time"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
            )
    validate(bars)
    return bars


def validate(bars: List[Bar]) -> None:
    """Fail loudly on the data problems that silently corrupt backtests."""
    if not bars:
        raise ValueError("no bars loaded")
    for i, b in enumerate(bars):
        if not (b.low <= b.open <= b.high and b.low <= b.close <= b.high):
            raise ValueError(f"bar {i} ({b.time}): OHLC inconsistent {b}")
        if b.low <= 0:
            raise ValueError(f"bar {i} ({b.time}): non-positive price")
