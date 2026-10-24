"""Alerts track: file checks, budget check, and that the committed alert files of the five
reference methods (results/v1.0/alerts/) reproduce the published table."""
from pathlib import Path

import pandas as pd
import pytest

from gridshedwatch import alerts, benchmark, data

ROOT = Path(__file__).resolve().parents[1]
BOARD = pd.read_csv(ROOT / "results" / "v1.0" / "leaderboard.csv").set_index("method")
H = pd.Timedelta(hours=1)
KEYS = ["watch_caught_all", "watch_caught_held_out", "warning_caught_all", "warning_caught_held_out",
        "watch_median_lead_h", "warning_median_lead_h", "watch_alerts_per_grid_year", "warning_alerts_per_grid_year",
        "watch_false_alarm_ratio", "warning_false_alarm_ratio", "watch_caught_seed_range", "warning_caught_seed_range",
        "watch_median_grid_rate", "warning_median_grid_rate"]


def row(grid="tx", level="watch", t=None, seed=0):
    t = t if t is not None else pd.Timestamp("2021-02-14 21:00")
    return dict(grid=grid, level=level, start_utc=str(t), seed=seed)


@pytest.mark.parametrize("bad,msg", [
    ([dict(grid="tx", level="watch")], "missing columns"),
    ([row(grid="xx")], "unknown grids"),
    ([row(level="alarm")], "unknown levels"),
    ([row(t=pd.Timestamp("2019-06-01"))], "outside the scored period"),
    ([row(), row()], "duplicate"),
])
def test_bad_files_are_rejected(bad, msg):
    with pytest.raises(ValueError, match=msg):
        alerts.check(pd.DataFrame(bad))


def test_seed_defaults_to_zero_and_minutes_allowed():
    df = alerts.check(pd.DataFrame([dict(grid="tx", level="watch", start_utc="2021-02-14 21:20")]))
    assert df.seed.tolist() == [0]


def test_one_watch_is_caught_with_its_lead():
    r = benchmark.evaluate_alerts("x", {0: {"tx": {"watch": [data.onset("tx") - 10 * H]}}}, chance=False)
    tx = r.rows[(r.rows.grid == "tx") & (r.rows.level == "watch")].iloc[0]
    assert tx.caught and tx.lead_h == pytest.approx(10)
    assert r.summary["watch_caught_all"] == 1.0 and r.summary["watch_within_budget"]


def test_watch_after_onset_does_not_count_but_warning_does():
    on = data.onset("tx")
    r = benchmark.evaluate_alerts("x", {0: {"tx": {"watch": [on + H], "warning": [on + H]}}}, chance=False)
    assert r.summary["watch_caught_all"] == 0.0 and r.summary["warning_caught_all"] == 1.0


def test_flooding_one_grid_is_over_budget():
    lo, hi = alerts.scored_period("ca")
    flood = list(pd.date_range(lo, hi, freq="7D"))        # about 52 watches a year on one grid
    r = benchmark.evaluate_alerts("x", {0: {"ca": {"watch": flood}}}, chance=False)
    assert r.summary["watch_median_grid_rate"] == 0.0     # the median alone would pass
    assert not r.summary["watch_within_budget"]


@pytest.mark.parametrize("m,name", [("oprule", "Operator-style rule"), ("zscore", "Seasonal z-score"),
                                    ("lstm", "LSTM forecaster"), ("chronos", "Chronos-Bolt (zero-shot)"),
                                    ("htm", "HTM (htm-monitor)")])
def test_reference_alert_files_reproduce_the_table(m, name):
    s = benchmark.evaluate_alerts(name, alerts.load(ROOT / "results" / "v1.0" / "alerts" / f"{m}.csv"), chance=False).summary
    ref = BOARD.loc[name]
    for k in KEYS:
        a, b = s[k], ref[k]
        if isinstance(a, float):
            assert (a != a and b != b) or a == pytest.approx(float(b), abs=1e-9), k
        else:
            assert str(a) == str(b), k
    assert s["watch_within_budget"] and s["warning_within_budget"]
