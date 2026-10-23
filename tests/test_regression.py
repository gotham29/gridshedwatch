"""Every published v1.0 number is reproduced. The operator-style rule and the z-score are rebuilt
from the data snapshot; the LSTM, Chronos and HTM are scored from the reference scores if they
are present (python scripts/fetch_reference.py), else skipped."""
from pathlib import Path

import pandas as pd
import pytest

from gridshedwatch import benchmark, data, submission
from gridshedwatch.baselines import oprule, zscore

ROOT = Path(__file__).resolve().parents[1]
BOARD = pd.read_csv(ROOT / "results" / "v1.0" / "leaderboard.csv").set_index("method")
KEYS = ["watch_setting", "warning_setting", "watch_caught_all", "watch_caught_held_out", "warning_caught_all",
        "warning_caught_held_out", "watch_median_lead_h", "watch_alerts_per_grid_year", "watch_false_alarm_ratio",
        "warning_alerts_per_grid_year", "warning_false_alarm_ratio", "watch_caught_seed_range",
        "warning_caught_seed_range"]


def check(name, fn, seeds):
    s = benchmark.evaluate(name, fn, seeds, chance=False).summary
    ref = BOARD.loc[name]
    for k in KEYS:
        a, b = s[k], ref[k]
        if isinstance(a, float):
            assert a == pytest.approx(float(b), abs=1e-9), k
        else:
            assert str(a) == str(b), k


@pytest.mark.slow
def test_oprule():
    check("Operator-style rule", oprule.alerts, [0])


@pytest.mark.slow
def test_zscore():
    check("Seasonal z-score", benchmark.from_scores({0: {g: zscore.scores(g) for g in data.grids()}}), [0])


@pytest.mark.parametrize("m,name", [("lstm", "LSTM forecaster"), ("chronos", "Chronos-Bolt (zero-shot)"),
                                    ("htm", "HTM (htm-monitor)")])
def test_reference_methods(m, name):
    folder = ROOT / "reference_scores" / m
    if not folder.exists():
        pytest.skip("reference scores not downloaded (python scripts/fetch_reference.py)")
    sc = submission.load(folder)
    check(name, benchmark.from_scores(sc), sorted(sc))
