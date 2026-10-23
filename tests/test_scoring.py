"""Scoring windows, the label-free operating point and the status quo row."""
import numpy as np
import pandas as pd

from gridshedwatch import benchmark

ON = pd.Timestamp("2021-02-15 07:00")
H = pd.Timedelta(hours=1)


def test_watch_window_is_week_before_onset():
    st = [ON - 169 * H, ON - 168 * H, ON - 1 * H, ON, ON + 1 * H]
    assert benchmark.verified(st, ON, "watch") == [ON - 168 * H, ON - 1 * H]


def test_warning_window_runs_to_48h_after():
    st = [ON - 168 * H, ON, ON + 48 * H, ON + 49 * H]
    assert benchmark.verified(st, ON, "warning") == [ON - 168 * H, ON, ON + 48 * H]


def test_operating_point_largest_rate_within_budget():
    rows = []
    for g, base in [("a", 1.0), ("b", 2.0), ("c", 3.0)]:
        for thr, mult in [(0.9, 10.0), (0.99, 4.0), (0.999, 1.0)]:
            for L in (3, 6):
                rows.append(dict(seed=0, grid=g, level="watch", threshold=thr, L=L, rate=base * mult / (L / 3)))
                rows.append(dict(seed=0, grid=g, level="warning", threshold=thr, L=L, rate=base * mult / (L / 3) / 5))
    op = benchmark.operating_point(pd.DataFrame(rows))
    # watch medians (grid b): 20, 10, 8, 4, 2, 1 -> largest <= 12 is 10 (thr 0.9, L 6)
    assert op["watch"][:2] == (0.9, 6)
    # warning medians: 4, 2, 1.6, 0.8, ... -> largest <= 2 is 2 (thr 0.9, L 6)
    assert op["warning"][:2] == (0.9, 6)


def test_status_quo_public_warnings():
    s = benchmark.status_quo()
    assert s["watch_caught_all"] == 4.0
    assert s["by_grid"] == {"tx": True, "ca": True, "tva": False, "spp": True, "miso": True,
                            "duk": False, "cple": False, "lgee": False}
