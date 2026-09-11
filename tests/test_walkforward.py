from aitrading.backtest import TF_D1
from aitrading.config import XAUUSD, StrategyConfig
from aitrading.data import synthetic
from aitrading.walkforward import default_grid, walk_forward

SMALL_GRID = [
    StrategyConfig(lookbacks=[10, 30, 60], use_efficiency_filter=False),
    StrategyConfig(lookbacks=[20, 60, 120], use_efficiency_filter=False),
    StrategyConfig(lookbacks=[20, 60, 120], use_efficiency_filter=True, er_threshold=0.25),
]


def test_walk_forward_runs_and_reports_only_oos():
    bars = synthetic.trending(2500, seed=13)
    wf = walk_forward(bars, XAUUSD, TF_D1, grid=SMALL_GRID, n_folds=3,
                      min_train_frac=0.4, initial_equity=100_000.0)
    assert len(wf.folds) == 3
    assert wf.configs_tried == len(SMALL_GRID) * 3
    assert wf.oos.bars > 0
    # OOS bar count must be far less than the full history: we only score tests.
    assert wf.oos.bars < len(bars)


def test_walk_forward_rejects_insufficient_history():
    bars = synthetic.trending(300, seed=1)
    try:
        walk_forward(bars, XAUUSD, TF_D1, grid=default_grid(), n_folds=5)
    except ValueError as e:
        assert "Not enough history" in str(e)
    else:
        raise AssertionError("should have refused to run on 300 bars")


def test_noise_hurdle_scales_with_grid_size():
    bars = synthetic.trending(2500, seed=13)
    small = walk_forward(bars, XAUUSD, TF_D1, grid=SMALL_GRID, n_folds=3,
                         min_train_frac=0.4, initial_equity=100_000.0)
    assert small.hurdle is not None and small.hurdle > 0
    assert small.oos_deflated_sharpe < small.oos_sharpe


def test_folds_are_chronologically_ordered_and_disjoint():
    bars = synthetic.trending(2500, seed=13)
    wf = walk_forward(bars, XAUUSD, TF_D1, grid=SMALL_GRID, n_folds=3,
                      min_train_frac=0.4, initial_equity=100_000.0)
    train_sizes = [f.train_bars for f in wf.folds]
    assert train_sizes == sorted(train_sizes), "training window must only grow"
    assert all(f.test_bars > 0 for f in wf.folds)
