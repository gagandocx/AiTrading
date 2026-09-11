# data/

Market data lives here but is **not committed** (see `.gitignore`) — it is
broker-specific, often licensed, and large.

## Expected files

| File | Produced by | Purpose |
|---|---|---|
| `XAUUSD_D1.csv` | `scripts/export_from_mt5.py` or `mql5/ExportBars.mq5` | primary backtest |
| `XAUUSD_H4.csv` | same | timeframe comparison |
| `XAUUSD_costs.json` | `scripts/export_from_mt5.py` | calibrates the cost model |

## Format

```csv
time,open,high,low,close
2010-01-04 00:00:00,1096.35,1124.30,1094.72,1117.70
```

Oldest row first. `csv_source.load()` validates that every bar satisfies
`low <= open,close <= high` and rejects non-positive prices, so a malformed
export fails immediately rather than silently corrupting results.

## Do not put tick data here

For a days-to-weeks holding period, ticks add no information and cost tens of
gigabytes. Ticks are useful only for measuring the spread distribution, which
`export_from_mt5.py --costs-only` handles by sampling live quotes.
