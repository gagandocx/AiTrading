# Commodities & FX: What Actually Works

A survey of strategies in commodity futures and foreign exchange, ranked by strength of
out-of-sample evidence rather than by sophistication. Sources are linked inline. Content from
external sources was rephrased for compliance with licensing restrictions.

---

## 0. How to read "proven"

Most published strategies fail one of four tests. Apply these before believing any claim:

| Test | Question | Typical failure |
|---|---|---|
| Out-of-sample persistence | Does it work on data discovered *after* publication? | Most equity-style anomalies halve post-publication |
| Cross-market generality | Same signal, unrelated markets, no re-tuning? | Curve-fit indicators work in one market only |
| Cost survival | Survives realistic spread + slippage + financing + roll cost? | High-turnover signals die at ~1.5x modelled cost |
| Economic mechanism | Is there a risk-transfer or structural reason someone pays you? | Pure data-mined patterns have no reason to persist |

Only two families pass all four across decades and dozens of markets: **trend (time-series
momentum)** and **carry**. Everything else is either a smaller satellite, a capacity-constrained
structural edge, or an infrastructure business.

Also: **advanced ≠ profitable.** The most consistently profitable operations in these markets are
not the ones with the most sophisticated alpha models — they are the ones with the best cost
structure, risk sizing, and capital durability applied to fairly simple signals.

---

## 1. Tier 1 — The durable premia (both asset classes)

### 1.1 Time-series momentum / trend following

The single most-validated systematic strategy in futures and FX.

- [Moskowitz, Ooi & Pedersen (2012)](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
  found an asset's own trailing 12-month excess return positively predicts its next-period return,
  across equity index, bond, commodity and currency futures; the effect persists roughly a year then
  partially reverses. Robust across look-backs, holding periods and sub-samples.
- [Hurst, Ooi & Pedersen, *A Century of Evidence on Trend-Following*](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following)
  extends the result back over a century.
- Mechanism: slow information diffusion, under-reaction then over-reaction, plus non-price flows
  (hedgers, rebalancers, central banks, index programmes) that are price-insensitive and persistent.
- Practical construction: multiple look-backs (~1m / 3m / 12m) blended, position sized inversely to
  realised volatility, capped per-market risk, portfolio scaled to a target volatility. MOP used
  volatility-scaled positions with a high target, roughly 2x effective leverage
  ([discussion](https://alphaarchitect.com/time-series-momentum-volatility-scaling-and-crisis-alpha/)).
- Realistic expectation: Sharpe ~0.5–0.8 net at scale on a diversified 60–120 market portfolio,
  large positive skew, long flat/drawdown stretches (2011–2019 was brutal), strong "crisis alpha"
  in sustained dislocations (2008, 2014 oil, 2022 inflation).
- Where it decayed: short-horizon (<1 month) price trend in liquid FX majors. Where it did not:
  medium/slow horizons in commodities, especially energy and ags.

### 1.2 Carry

- [Koijen, Moskowitz, Pedersen & Vrugt, *Carry* (JFE 2018)](https://www.aqr.com/Insights/Research/Journal-Article/Carry)
  generalised FX carry into a universal definition — the return earned if prices don't move — and
  showed it predicts returns cross-sectionally and in time series in currencies, commodities,
  equities, bonds, credit and options. Critically, carry strategies across asset classes are
  [only weakly correlated with each other](https://epfl.ch/labs/sfi-pcd/wp-content/uploads/2021/07/Discussion-of-Carry-2012.pdf),
  which is the entire argument for running carry as a multi-asset book rather than an FX book.
- **In FX**, carry = interest-rate differential (long high-yielders, short low-yielders). High
  historical Sharpe, but the return is compensation for crash risk, not free money:
  [Jurek](http://users.nber.org/~confer/2008/apf08/jurek.pdf) showed crash risk premia explain
  roughly 30–40% of the excess return, and hedging the crash with options leaves returns
  statistically indistinguishable from zero in dollar-neutral form. Carry behaviour also varies
  sharply with the monetary regime
  ([ECB WP 1968](https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1968.en.pdf)).
  [Daniel, Hodrick & Lu (2017)](https://drupalgsb-dev.cc.columbia.edu/sites/default/files-efs/pubfiles/6378/Daniel.Hodrick.Lu.Carry%20Trade.Critical%20Finance%20Review.2017.pdf)
  found a diversified dollar-carry construction had higher return, higher Sharpe and much less
  skew/downside than naive high-minus-low carry.
- **In commodities**, carry = the futures curve slope (backwardation vs contango), i.e. roll yield.
  [Erb & Harvey (2006)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=650923) showed the
  average individual commodity future earned roughly zero excess return over their sample, while
  term-structure and momentum-based tactical strategies delivered higher return and lower risk than
  long-only exposure. The economic link: low inventories → backwardated curve → positive roll yield
  ([CME research](https://www.cmegroup.com/trading/agricultural/files/an-update-on-empirical-relationships-in-the-commodity-futures-markets.pdf)).
  This is the theory of storage, and it is the cleanest fundamental signal in commodities.
- Practical: never run naive carry. Vol-scale it, cap concentration, neutralise the dominant factor
  (USD in FX, energy beta in commodities), and either buy convex tail hedges or reduce gross when
  carry-to-vol is thin and positioning is crowded.

### 1.3 Value / long-horizon mean reversion

- FX: real exchange rate vs 5-year average, or PPP/FEER deviation. Slow (multi-year holding), low
  Sharpe standalone (~0.2–0.4), but **negatively correlated with carry and trend**, which makes it
  valuable as a portfolio component rather than a standalone book.
- Commodities: price relative to 5-year average, or vs cost-of-production/marginal-cost anchors.
  Works better in commodities with real supply elasticity (ags, industrial metals) than in those
  with structural regime shifts (natural gas post-shale).

### 1.4 The combination layer — where the profit actually is

Trend + carry + value, equal-risk-weighted, vol-targeted, across ~60–120 futures and forwards,
historically produces a materially better Sharpe than any single sleeve because the components have
low or negative pairwise correlation. Almost all realised edge in this business comes from:

1. Breadth (more uncorrelated markets, not better indicators)
2. Risk sizing (inverse-vol, correlation-aware, drawdown-responsive)
3. Cost control (roll timing, execution algos, netting across sleeves)
4. Capital durability (surviving the 3-year flat stretch)

---

## 2. Tier 2 — Commodity-specific structural edges

Higher Sharpe, much lower capacity. This is where real specialist money is made.

| Strategy | Mechanism | Notes |
|---|---|---|
| **Calendar spreads** | Trade curve shape, not price level: inventory/storage economics, not direction | Far lower vol than outright, margin-efficient, but tail risk is violent (Amaranth) |
| **Crack spread** (crude vs gasoline/distillate) | Refinery margin; mean-reverts to refining economics | Seasonal: gasoline crack builds into summer driving season |
| **Crush spread** (soybeans vs meal/oil) | Processing margin | Anchored by physical crush plant economics |
| **Spark / dark spread** (power vs gas/coal + carbon) | Generation margin | Requires heat-rate and emissions modelling; power is the least efficient major market |
| **Cash-and-carry / storage arb** | Contango wider than full carry cost (storage + finance + insurance) | Needs actual storage access; the pure financial version is a levered bet on curve, not arbitrage |
| **Location / freight spreads** | Same commodity, different delivery point, vs shipping cost | Brent–WTI, TTF–JKM LNG, regional power hubs |
| **Quality / grade spreads** | Substitutable grades diverge beyond blending economics | Ags and metals |
| **Index roll / rebalance pressure** | GSCI/BCOM roll windows and January reweights are mechanical, pre-announced flows | Anticipation trade; visibly decayed as it became widely known |
| **Hedging pressure / positioning** | Producers' net short hedging demand must be absorbed; CFTC COT data proxies it | See [Fernandez-Perez, Fuertes & Miffre](https://acfr.aut.ac.nz/__data/assets/pdf_file/0020/61715/Paper_Adrian_version-for-AFM-2016.pdf) — long-short signal portfolios beat long-only |
| **Seasonality** | Genuine physical seasonality in gas (heating), power (cooling), ags (harvest/planting) | Only trust it where the physical cause is explicit; otherwise it's a calendar overfit |
| **Weather / fundamentals nowcasting** | NOAA/ECMWF ensembles, satellite NDVI for crops, storage/inventory reports (EIA, USDA WASDE) | Real, persistent edge — but it's a data-and-domain business, not a modelling trick |

Curve trades combined with a term-structure signal are the highest-quality commodity alpha available
to a non-physical player. Note that static curve-slope signals are the naive version;
[dynamic/conditional term-structure signals](https://www.kdajdqs.org/bbs/reference/871/download/1476)
improve on a single-snapshot slope.

---

## 3. Tier 2 — FX-specific edges

| Strategy | Mechanism | Evidence / caveat |
|---|---|---|
| **Order flow** | Customer flow carries private information about fundamentals | [Evans & Lyons](https://www.johnhcochrane.com/s/evans_lyons_jpe.pdf) found order flow explains a large share of daily returns; [Menkhoff et al. (BIS WP 405)](http://www.bis.org/publ/work405.pdf) found customer flows highly informative about future rates with real economic value. **Requires being a bank or having flow data — not available to outsiders.** |
| **Dollar factor timing** | One factor dominates FX covariance; timing it vs. trading crosses is a distinct decision | Underpins the Daniel-Hodrick-Lu dollar-neutral carry improvement |
| **FX volatility risk premium** | Implied > realised on average; sell vol / variance | Short-vol tail is identical in shape to carry's tail — do not stack both unhedged |
| **Risk reversals / skew** | Options skew prices crash risk in carry pairs; sometimes over-priced | Cleanest expression of "carry without the crash" — see Jurek |
| **Fixing-window / benchmark flows** | WM/Reuters 4pm fix, month-end rebalancing, index events create predictable pressure | Post-2013 scandal reforms widened the window and reduced the edge |
| **Triangular / latency arbitrage** | Cross-venue price inconsistency | Real but is an infrastructure race (co-location, microwave), not a strategy |
| **Central bank reaction-function trades** | Trade the gap between market-implied policy path and a model of the CB's own reaction function | Discretionary/semi-systematic; the main source of macro-fund FX P&L |
| **Pegged / managed regime trades** | Asymmetric payoff betting against unsustainable pegs, via options | Huge convexity, long dead time; CHF Jan 2015 is the canonical reminder that the *hedge* side also blows up |
| **EM carry with tail hedges** | Higher carry, higher crash risk, funding-dependent | Capacity-limited by local liquidity and convertibility; NDF basis is its own trade |

---

## 4. What is decayed, crowded, or mythology

- **Short-term technical patterns** (candlesticks, most oscillator crossovers, Elliott wave,
  harmonic patterns): no credible out-of-sample cross-market evidence. Widely sold, rarely traded by
  anyone with capital at risk.
- **Naive high-minus-low FX carry**: the classic Sharpe was substantially crash-risk compensation;
  post-2008 the developed-market rate dispersion that powered it largely vanished, then returned
  differently in 2022+.
- **Fast trend in FX majors**: heavily arbitraged.
- **Index roll anticipation**: publicly known and pre-positioned.
- **Long-only commodity index as a "return" allocation**: Erb & Harvey's point stands — it is mostly
  a bet on curve shape and weighting scheme, not a reliable premium.
- **Martingale / grid / averaging-down systems**: positive win rate, unbounded loss. Not a strategy.
- **Any single-market backtest with Sharpe > 2 and < 500 trades**: assume overfit until proven
  otherwise on unrelated markets.

---

## 5. Realistic expectations

| Strategy | Net Sharpe (realistic) | Capacity | Decay risk | Skew |
|---|---|---|---|---|
| Multi-asset trend (diversified) | 0.5–0.8 | Very high ($10bn+) | Low | Positive |
| Commodity curve/carry (long-short) | 0.6–1.0 | Medium | Low-medium | Mildly negative |
| FX carry, vol-targeted + tail-hedged | 0.4–0.7 | High | Medium | Negative (less if hedged) |
| FX/commodity value | 0.2–0.4 | High | Low | Neutral |
| Calendar & processing spreads | 1.0–2.0 | Low | Medium | Fat-tailed |
| Physical/weather fundamentals | 1.0–2.0+ | Low | Low | Varies |
| Market making / latency | 3.0+ | Very low | High | Positive but jump-exposed |
| Retail technical patterns | ≤ 0 net of costs | n/a | n/a | Negative |

Combine Tier 1 sleeves for a durable core; add Tier 2 where you have a genuine data or access
advantage. Do not expect Tier 1 Sharpes above ~1.0 net at any real size — anyone promising that is
either overfitting or selling something.

---

## 6. If building this systematically (notes for `AiTrading`)

**Where ML genuinely helps**
- Volatility and covariance forecasting (better sizing beats better signals)
- Regime classification for gating and gross scaling
- Execution: slippage prediction, optimal roll timing, order scheduling
- Alternative-data nowcasting (satellite, shipping AIS, weather ensembles, text)
- Non-linear blending of a *small* number of economically-motivated signals

**Where ML reliably destroys capital**
- Raw price-series return prediction (signal-to-noise is far too low)
- Deep nets on OHLCV with thousands of features and a few thousand effective observations
- Any pipeline where the backtest is the objective function being optimised
- Reinforcement learning on simulated fills without a market-impact model

**Non-negotiable engineering**
1. Point-in-time data, no survivorship bias, no restated fundamentals
2. Continuous futures series built with explicit roll rules; never trade the stitched price
3. Realistic cost model: spread + impact (nonlinear in participation) + financing + roll + fees
4. Walk-forward / purged cross-validation with embargo; track number of configurations tried and
   deflate Sharpe accordingly
5. Vol targeting and per-market risk caps in the *portfolio* layer, not the signal layer
6. Kill switches: max drawdown, max daily loss, position/exposure limits, data-staleness halts

---

## 7. Honest bottom line

There is no hidden "most profitable" strategy. What is proven is a short list of risk premia —
trend and carry above all — that pay you for absorbing risk others want to shed, plus a set of
narrow structural edges that require physical access, proprietary flow, or infrastructure. The
durable competitive advantages are breadth, cost, risk sizing, and the ability to keep the capital
invested through drawdown. Everything else in retail-facing trading education is noise.

This document is research analysis, not investment advice. Trading leveraged futures and FX can lose
more than the capital committed.
