"""Tests for the research protocol: search ledger and sealed lockbox.

These guard the two mechanisms that keep an automated iteration loop honest. If
the ledger stops raising its hurdle, or the lockbox can be opened twice, the
whole pipeline silently becomes an overfitting machine.
"""

import pytest

from aitrading.data import synthetic
from aitrading.research.ledger import Ledger
from aitrading.research.lockbox import LockboxViolation, SealRecord, split


# --- ledger ---------------------------------------------------------------
def test_hurdle_rises_monotonically_with_search(tmp_path):
    """The core property: more searching makes the bar HIGHER, never lower."""
    led = Ledger.load(str(tmp_path / "l.json"))
    prev = 0.0
    for i in range(6):
        led.record(f"cycle {i}", configs_tested=100, timeframe="D1",
                   best_raw_sharpe=1.0, oos_years=10.0)
        h = led.hurdle(10.0)
        assert h > prev, "hurdle must increase as configurations accumulate"
        prev = h


def test_cumulative_deflation_is_stricter_than_per_cycle(tmp_path):
    led = Ledger.load(str(tmp_path / "l.json"))
    for i in range(5):
        led.record(f"c{i}", configs_tested=200, timeframe="D1",
                   best_raw_sharpe=1.2, oos_years=10.0)
    last = led.cycles[-1]
    assert last.best_deflated_vs_cumulative < last.best_deflated_vs_cycle


def test_ledger_persists_across_reload(tmp_path):
    p = str(tmp_path / "l.json")
    led = Ledger.load(p)
    led.record("first", configs_tested=90, timeframe="D1",
               best_raw_sharpe=0.5, oos_years=16.6)
    led.save()

    reopened = Ledger.load(p)
    assert reopened.cumulative_configs == 90
    assert reopened.next_cycle_number == 2
    reopened.record("second", configs_tested=10, timeframe="H1",
                    best_raw_sharpe=0.9, oos_years=5.0)
    assert reopened.cumulative_configs == 100


def test_shorter_history_produces_a_higher_hurdle(tmp_path):
    led = Ledger.load(str(tmp_path / "l.json"))
    led.record("c", configs_tested=500, timeframe="D1",
               best_raw_sharpe=1.0, oos_years=5.0)
    assert led.hurdle(1.0) > led.hurdle(16.6)


def test_empty_ledger_summary_is_safe(tmp_path):
    assert "empty" in Ledger.load(str(tmp_path / "l.json")).summary()


# --- lockbox --------------------------------------------------------------
def test_split_is_chronological_and_disjoint():
    bars = synthetic.trending(1000, seed=1)
    sp = split(bars, 0.70)
    assert len(sp.research) == 700
    assert len(sp.lockbox) == 300
    # research must end strictly before the lockbox begins
    assert sp.research[-1].time == bars[699].time
    assert sp.lockbox[0].time == bars[700].time


def test_split_rejects_absurd_fractions():
    bars = synthetic.trending(1000, seed=1)
    for frac in (0.1, 0.99):
        with pytest.raises(ValueError):
            split(bars, frac)


def test_split_rejects_insufficient_data():
    with pytest.raises(ValueError):
        split(synthetic.trending(100, seed=1), 0.70)


def test_lockbox_starts_sealed(tmp_path):
    seal = SealRecord(tmp_path / "seal.json")
    assert seal.is_sealed("XAUUSD_D1")
    seal.require_sealed("XAUUSD_D1")   # must not raise


def test_second_open_is_refused(tmp_path):
    """The property that makes the holdout meaningful."""
    seal = SealRecord(tmp_path / "seal.json")
    seal.record_open("XAUUSD_D1", cycle=4, candidate="[20,60,120]/trend",
                     result_sharpe=0.42)
    assert not seal.is_sealed("XAUUSD_D1")
    with pytest.raises(LockboxViolation) as e:
        seal.require_sealed("XAUUSD_D1")
    assert "already opened" in str(e.value)


def test_opening_one_dataset_leaves_others_sealed(tmp_path):
    seal = SealRecord(tmp_path / "seal.json")
    seal.record_open("XAUUSD_D1", 4, "x", 0.4)
    assert not seal.is_sealed("XAUUSD_D1")
    assert seal.is_sealed("XAUUSD_H1")


def test_seal_record_persists(tmp_path):
    p = tmp_path / "seal.json"
    SealRecord(p).record_open("XAUUSD_D1", 4, "cand", 0.42)
    assert not SealRecord(p).is_sealed("XAUUSD_D1")


# --- hypotheses -----------------------------------------------------------
def test_registered_cycles_have_rationales_and_small_grids():
    from aitrading.research import hypotheses
    for cycle in hypotheses.CYCLES:
        for h in hypotheses.get(cycle):
            assert len(h.rationale) > 40, f"{h.name} needs a real rationale"
            assert h.size <= 40, (f"{h.name} has {h.size} configs; large grids "
                                 f"raise the hurdle faster than they find edge")


def test_unknown_cycle_raises():
    from aitrading.research import hypotheses
    with pytest.raises(KeyError):
        hypotheses.get(999)



def test_rerunning_identical_hypotheses_does_not_inflate_the_count(tmp_path):
    """Verification must be free.

    Re-running the same hypotheses on the same data examines no new
    configurations. If that raised the hurdle, reproducing a result would make it
    harder to prove -- penalising the one behaviour we most want to encourage.
    """
    led = Ledger.load(str(tmp_path / "l.json"))
    led.record("cycle 2: mtf_alignment", 40, "D1", -0.10, 11.65)
    assert led.cumulative_configs == 40

    for _ in range(5):
        led.record("cycle 2: mtf_alignment", 40, "D1", -0.10, 11.65)
    assert led.cumulative_configs == 40, "re-runs must not accumulate"
    assert len(led.cycles) == 1


def test_genuinely_new_hypotheses_do_increment(tmp_path):
    led = Ledger.load(str(tmp_path / "l.json"))
    led.record("cycle 2: mtf_alignment", 40, "D1", -0.10, 11.65)
    led.record("cycle 3: something new", 20, "D1", 0.4, 11.65)
    assert led.cumulative_configs == 60
    assert len(led.cycles) == 2


def test_same_hypothesis_on_a_different_timeframe_counts_as_new(tmp_path):
    """Testing the same idea on H1 after D1 IS additional search."""
    led = Ledger.load(str(tmp_path / "l.json"))
    led.record("trend baseline", 40, "D1", 0.2, 11.65)
    led.record("trend baseline", 40, "H1", 0.9, 5.1)
    assert led.cumulative_configs == 80
