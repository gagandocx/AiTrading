# AiTrading

A single-instrument systematic trading engine for MT5, targeting **XAUUSD on D1**.

The core engine has **zero dependencies** and is fully unit-tested, so it runs
anywhere. MT5 is needed only for live data and execution.

---

## Status

| Component | State |
|---|---|
| Signal engine (multi-horizon trend, vol-targeted) | Built, 57 tests passing |
| Cost model (spread, slippage, commission, financing) | Built and validated |
| Backtest engine (no look-ahead, exact accounting) | Built and validated |
| Purged walk-forward with multiple-testing correction | Built |
| MT5 data export + cost measurement | Built and used |
| MT5 live execution + risk gate | Built, demo-enforced, 81 tests passing |
| **Edge on real XAUUSD (16.6 years)** | **NONE — deflated Sharpe −0.52** |

See **`docs/results/xauusd-findings.md`** for the full measured results. Summary:
the D1 trend signal shows no statistically credible edge, high-frequency trading
loses ~50%/yr to friction, and a $1,000 account cannot size gold safely.

---

## Live bot

```bash
# observe only, no orders sent
python scripts\run_live.py --dry-run

# armed, DEMO account only
python scripts\run_live.py --timeframe M5 --preset balanced
```

Refuses real-money accounts unless `--i-understand-live-risk` is passed
explicitly. Nothing in this repo sets that flag.

### Frequency presets, mapped to measured outcomes

| Preset | Trades/day | Return (22d) | Max DD | Friction ÷ gross |
|---|---|---|---|---|
| `ultra` | 282.7 | −9.73% | −10.42% | 7.57 |
| `veryfast` | 193.8 | −7.59% | −8.52% | — |
| `fast` | 104.6 | −3.83% | −6.01% | 39.30 |
| **`balanced`** (default) | **53.0** | **+0.11%** | **−2.17%** | **0.94** |
| `calm` | 27.3 | −0.79% | −3.38% | 10.10 |

Higher frequency was worse on **both** return and drawdown at every step. Even
`balanced` is statistically indistinguishable from zero over 22 days — it is the
least-bad point on the curve, not a validated edge.

### Risk gate

Every order passes `RiskManager.evaluate()`, which fails **closed**:

- daily loss limit → blocks for the session; drawdown limit → sticky HALT
- **spread guard** (absolute + multiple-of-median) — the highest-value control at
  speed, since gold's spread goes from $0.06 to $1.00+ around CPI/NFP/FOMC
- blocked session hours (rollover), news blackout window
- trade-count cap, consecutive-loss halt, post-loss cooldown
- position caps by both lots and leverage; oversized orders are **reduced**, not refused

### On a $1,000 account it will not trade, by design

Prudent sizing at 2× leverage gives 0.0046 lots. Your broker's minimum is 0.01.
The gate therefore blocks every order. To make it trade you must explicitly pass
`--max-leverage 4.4` or higher, which is you choosing ~71% annualised volatility.
The bot will not make that choice quietly on your behalf.

---

## Send me data and I can produce real results

### What to export (and what NOT to)

**Do NOT export tick data for the backtest.** At a days-to-weeks holding period
ticks add nothing, and 15 years of gold ticks is tens of gigabytes. Ticks are
useful for exactly one thing here: measuring the spread you actually pay.

| What | Why | Size |
|---|---|---|
| **D1 bars, 10–20 years** | the primary backtest — this is the priority | ~4,000 rows |
| **H4 bars, 10 years** | to confirm D1 is the right timeframe | ~23,000 rows |
| **Spread sample** | calibrates the cost model to YOUR broker | tiny |
| Your commission per lot per side | from the contract spec | one number |

### Option A — Python (preferred)

```bash
pip install MetaTrader5
python scripts/export_from_mt5.py --symbol XAUUSD --timeframes D1 H4 --years 15
```

Produces `data/XAUUSD_D1.csv`, `data/XAUUSD_H4.csv`, `data/XAUUSD_costs.json`.

### Option B — MQL5 script (no Python needed)

Compile and run `mql5/ExportBars.mq5` on a XAUUSD chart. See the header comment
for step-by-step instructions. Output lands in `MQL5/Files/`.

### Before exporting: unlock full history

MT5 ships with a truncated history by default.

1. Tools → Options → Charts → **Max bars in chart = Unlimited**
2. Open a XAUUSD chart on D1
3. Press and hold **Home** until it stops loading older bars

Without this you will export a few hundred bars and the walk-forward will refuse
to run.

### Required CSV format

```csv
time,open,high,low,close
2010-01-04 00:00:00,1096.35,1124.30,1094.72,1117.70
```

Oldest row first. Both exporters produce this automatically.

---

## Run it

```bash
# Engine correctness checks (synthetic data, no dependencies, no network)
python scripts/validate_engine.py

# Unit tests
pip install pytest && PYTHONPATH=src pytest tests/ -q

# Real backtest, out-of-sample
python scripts/run_backtest.py --csv data/XAUUSD_D1.csv --timeframe D1 \
    --costs data/XAUUSD_costs.json --walk-forward
```

---

## Design decisions and why

**XAUUSD over EURUSD.** Spread in isolation is the wrong metric; what matters is
spread ÷ volatility. Gold's round-trip cost is ~0.88% of one day's volatility
versus ~1.98% for EURUSD — roughly twice the opportunity per unit of friction,
despite the wider quoted spread. Gold also trends, driven by persistent
price-insensitive flows (central bank reserve buying, ETF creations, real-rate
regime shifts), whereas fast trend in FX majors is the most arbitraged signal in
the literature.

**D1, not H4 or faster.** Measured from the cost model at ~$0.30 round-trip on
gold:

| Holding period | Trades/yr | Annual cost drag | Verdict |
|---|---|---|---|
| 1 minute | 347,760 | 3676% | hopeless |
| 5 minutes | 69,552 | 735% | hopeless |
| 1 hour | 5,796 | 61.3% | hopeless |
| 4 hours | 1,449 | 15.3% | unviable vs a 15% target |
| **1 day** | **252** | **2.7%** | **workable** |
| 1 week | 50 | 0.5% | workable |

There is no high-frequency configuration of this system that survives retail
costs. That is arithmetic, not pessimism.

**Multi-horizon trend, not one optimised lookback.** Time-series momentum is the
most out-of-sample-validated systematic signal in futures and FX. On a single
instrument we cannot get breadth from markets, so robustness comes from averaging
horizons instead of tuning one.

**Volatility targeting.** Sizing matters more than signal quality. Validated to
compress an 8× swing in market volatility into a 1.8× swing in realised risk.

See `docs/research/strategy-landscape.md` for the evidence review behind these
choices.

---

## Honest expectations

A single-instrument system has no diversification. Expect **Sharpe 0.3–0.6** and
a **max drawdown of 20–35%**, with long flat periods. Trend following wins roughly
35–40% of its trades and makes money through payoff asymmetry, not hit rate. Any
configuration here showing a 90% win rate is hiding risk in its tail.

Not investment advice. Trading leveraged gold can lose more than you commit.
