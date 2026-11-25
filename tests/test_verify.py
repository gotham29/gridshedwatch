"""Protocol v4.0 (gridshedwatch/verify.py): alert merging and the forecast baseline's reference scores."""
import pandas as pd

from gridshedwatch import verify


def test_merge_within_24h():
    t = pd.Timestamp("2021-02-10 00:00")
    h = pd.Timedelta(hours=1)
    assert verify.merge([t, t + 5 * h, t + 30 * h, t + 40 * h, t + 60 * h]) == [t, t + 30 * h, t + 60 * h]


def test_forecast_baseline_reference():
    s = verify.score(verify.read("results/v3.0/methods/dfanom/alerts.csv"), chance=False)
    assert s["caught"] == 8 and s["caught_before_notice"] == 2 and s["storm_hit_n"] == 27
