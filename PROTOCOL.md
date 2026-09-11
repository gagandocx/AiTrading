# Research Protocol

The automated loop, and the rules that keep it from lying to us.

## The loop

```
   YOU (Windows + MT5)                    ME
   ------------------                     --
   run_cycle.bat N        ---report--->   pull, analyse
        ^                                      |
        |                                      v
        +-------------new hypotheses-----------+
```

```cmd
run_cycle.bat 3          REM D1
run_cycle.bat 3 H1       REM H1
```

That one command pulls my latest changes, runs the engine's tests, executes the
cycle's pre-registered hypotheses on the **research** portion of your data, and
pushes a JSON report back to me. Then tell me it finished.

## Why this loop has a stopping rule

The obvious version of this — "iterate until the backtest is profitable" — is
guaranteed to succeed and guaranteed to be worthless. `scripts/overfitting_demo.py`
demonstrates it concretely: 648 configurations extracted a Sharpe 3.35 strategy
from data generated as **pure random noise**, and it collapsed to −0.35 on fresh
noise. Automating that process just reaches the false conclusion faster.

Three mechanisms prevent it.

### 1. The search ledger raises the bar every cycle

`research_state/ledger.json` is append-only and records every configuration ever
tested, across all cycles and machines. A result is judged against the Sharpe a
**zero-edge search of that cumulative size** would be expected to produce.

Current state: **1,448 configurations already searched**, which means:

| Dataset | Hurdle to beat |
|---|---|
| D1 research split (11.65y) | Sharpe **0.94** |
| H1 (5.1y) | Sharpe **1.43** |

Every cycle pushes these higher. **Searching harder makes proof harder.** That is
the honest arithmetic, and it is why "keep going until profitable" cannot converge.

Deleting the ledger to lower the hurdle is the research equivalent of deleting
losing trades before showing someone your track record.

### 2. A sealed lockbox, opened exactly once

Data splits chronologically:

```
  RESEARCH  first 70%   (D1: 2,936 bars, 11.65y, ends 2021-10-25)  -- iterate freely
  LOCKBOX   last 30%    (D1: 1,259 bars,  5.00y, from 2021-10-26)  -- SEALED
```

The lockbox is never touched during iteration, so no amount of searching can
overfit to it. When a candidate finally clears the cumulative hurdle, we run
`scripts/open_lockbox.py` **once**. That number is the honest forecast.

`SealRecord` permanently marks the dataset as opened and refuses a second open.
A twice-opened holdout is not a holdout.

### 3. Pre-registered hypotheses

Each cycle in `src/aitrading/research/hypotheses.py` must state what it tests and
**why**, before running. Grids are capped at 40 configs (enforced by a test).
A named hypothesis with a rationale can be wrong; "try 5,000 combinations" cannot.

## Termination conditions — agreed in advance

The loop stops when **one** of these is met:

1. **SUCCESS** — a hypothesis beats the cumulative hurdle on the research split,
   *and* confirms on the lockbox, *and* beats buy-and-hold gold. → demo for 3+ months.
2. **FAILURE** — 10 cycles complete with nothing clearing the hurdle. → the
   conclusion is "no edge in single-instrument XAUUSD timing," which is a real
   finding, not a failure of effort.
3. **HURDLE EXCEEDS PLAUSIBILITY** — cumulative search pushes the bar above
   Sharpe ~2.0, at which point no honest result can clear it and further
   searching is pure noise-mining.

Cycles used so far: **6 of 10.**

## Your own settings get an easier test

This is worth knowing. When *I* search 2,000 configurations and keep the best, the
result must clear the expected maximum of 2,000 zero-edge trials. When **you** name
one configuration in advance, there is no search to correct for — it only needs
~2 standard errors:

| Test | Threshold on D1 |
|---|---|
| My optimised result (1,448 configs searched) | Sharpe **0.94** |
| Your single pre-registered setting | Sharpe **~0.50** |

```cmd
python scripts\test_settings.py --settings my_settings.json --research-only
```

That is not a loophole — it is the correct statistics of pre-registration, and it
means a setting you genuinely believe in is the cheapest hypothesis we can test.

## Results so far

| Cycle | Tested | Raw SR | vs cumulative | Outcome |
|---|---|---|---|---|
| 1 | D1 trend, 90 configs | 0.19 | −0.38 | noise |
| 2 | swap sensitivity, 450 | 0.44 | −0.28 | noise even at zero financing |
| 3 | H1 frequency sweep, 180 | 1.17 | −0.17 | lost to buy-and-hold |
| 4 | M1 HFT, 648 | — | — | −6.1%/22d, friction 4.54× gross |
| 5 | reversal + long-only, 40 | 0.31 | −0.48 | reversal dead; long-only was bull beta |
| 6 | GaganEA salvage, 40 | −0.10 | −1.04 | both negative |

Benchmark to beat: **buy-and-hold gold, Sharpe 1.06** (2021–2026), which has
outperformed every strategy tested.

## Files

| Path | Role |
|---|---|
| `run_cycle.bat` | one-click cycle (you run this) |
| `scripts/auto_backtest.py` | cycle runner, writes `reports/cycle_NN.json` |
| `scripts/test_settings.py` | test one pre-registered settings file |
| `scripts/open_lockbox.py` | final one-shot validation |
| `src/aitrading/research/ledger.py` | cumulative search accounting |
| `src/aitrading/research/lockbox.py` | sealed holdout + seal enforcement |
| `src/aitrading/research/hypotheses.py` | pre-registered cycles (I edit this) |
| `research_state/ledger.json` | **append-only.** Do not delete. |
| `research_state/lockbox_seal.json` | records lockbox opens |
