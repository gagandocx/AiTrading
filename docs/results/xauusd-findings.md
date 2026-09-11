# XAUUSD Results — Real Broker Data

Data: 4,195 D1 bars (2010-06-14 → 2026-09-10, 16.6 years) and 30,186 M1 bars
(21.9 days), exported from the account's own MT5 terminal. Costs measured from
the same account. OHLC integrity validated on every bar.

**Measured cost model:** half spread $0.030, slippage $0.005, commission
$3.00/lot/side → **$13.00 round trip per lot** (0.0030% of notional).
Swap rates remain assumed, not measured — see sensitivity below.

---

## 1. Does the D1 trend strategy have an edge? No.

Purged walk-forward, 5 folds, 90 configurations searched, 10.8 years scored
strictly out-of-sample:

| Metric | Value |
|---|---|
| OOS Sharpe | **0.19** (t-stat 0.62) |
| Noise hurdle for 90 configs | 0.71 |
| **Deflated Sharpe** | **−0.52** |
| **Verdict** | **NOT DISTINGUISHABLE FROM NOISE** |
| CAGR | 1.10% |
| Max drawdown | −18.84% |
| Win rate / profit factor | 21.7% / 1.42 |
| Costs as share of gross P&L | 48.0% |

Per-fold OOS Sharpe: −0.72, +0.32, −0.30, +0.15, +1.14. The instability across
folds is itself diagnostic — a real edge does not swing from −0.72 to +1.14.

The positive profit factor (1.42) with a 21.7% win rate confirms the signal has
the *shape* of trend following (few large wins, many small losses). It simply
does not have the magnitude to clear costs or the noise hurdle.

## 2. Is an unmeasured swap rate hiding the edge? No.

Financing consumed $873 of $1,967 gross P&L (44%), and that rested on an assumed
4.5% long-gold swap. Testing the full plausible range:

| Long swap/yr | OOS Sharpe | Deflated | CAGR | Verdict |
|---|---|---|---|---|
| 0.0% | 0.44 | −0.26 | 3.08% | noise |
| 2.0% | 0.28 | −0.43 | 1.74% | noise |
| 4.5% | 0.19 | −0.52 | 1.10% | noise |
| 7.0% | 0.18 | −0.53 | 1.02% | noise |
| 10.0% | 0.09 | −0.62 | 0.39% | noise |

**Even at zero financing the result stays inside the noise band.** The swap is
genuinely expensive on multi-week gold holds, but it is not concealing an edge.

## 3. Does high-frequency trading work at these costs? No.

Tested on the real M1 data at ~190 trades/day — the requested frequency:

| Configuration | Return (21.9 days) | Sharpe | Trades/day | Friction ÷ gross P&L |
|---|---|---|---|---|
| HFT, real costs | **−6.1%** | −8.58 | 190.4 | **4.54** |
| HFT, zero costs | +1.3% | 1.82 | 193.7 | 0.00 |
| Slow config on M1 | −1.5% | −4.17 | 31.3 | — |
| Slow config on D1 | +17.9% | 0.17 | 0.5 | 0.31 |

−6.1% over 21.9 days annualises to roughly **−50% per year**.

The two HFT rows are the entire argument in two lines: the signal produced
**+1.3% gross**, and friction consumed **4.54× that amount**. The strategy is not
wrong about direction — it is simply paying 4.5 times more to trade than the
trading is worth.

All five predictions committed in `scripts/test_hft_hypothesis.py` before any
real data was seen held true.

## 4. Is the account large enough? No.

| | |
|---|---|
| Equity | $1,000 |
| Smallest tradeable position | 0.01 lots = **$4,349 notional** |
| Leverage at minimum size | **4.3×** |
| Forced annualised volatility | **71%** (target: 15%) |
| P(>50% drawdown within a year) | **~48%** |
| Equity needed for 0.01 lots at 15% vol | **$4,734** |

Volatility targeting cannot function: there is nothing below 0.01 lots to scale
down to. This constraint is independent of strategy quality — a genuinely
profitable system run at 71% volatility still has a high probability of ruin.

---

## Conclusion

Three independent findings, each individually disqualifying:

1. The D1 trend signal has no statistically credible edge on XAUUSD over 16.6
   years, and this is not an artifact of cost assumptions.
2. High-frequency trading loses ~50%/yr to friction at measured broker costs.
3. The account is ~4.7× too small to express any strategy at a sane risk level.

**Nothing in this repository should be traded with real money.**

## What the result actually implies

The measured OOS Sharpe of 0.19 is close to what the literature predicts for
single-instrument trend following, and the reason is structural: trend following
derives its edge from **breadth**, not from signal sophistication. Diversified
managed futures programmes achieve Sharpe 0.5–0.8 across 60–120 markets, where
uncorrelated positions cancel each other's noise. One instrument cannot do this.

The binding constraint is therefore not the signal, the parameters, or the
timeframe. It is trading a single instrument with $1,000 through a CFD broker.
Changing any of those three is a larger improvement than any amount of further
optimisation on this configuration — and further optimisation would only raise
the noise hurdle (see `scripts/overfitting_demo.py`).
