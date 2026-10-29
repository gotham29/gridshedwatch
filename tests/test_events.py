"""Scoring with several events in one grid: each event is scored on its own, alerts are counted
once per grid, and an alert that verifies any event is not a false alarm."""
import numpy as np
import pandas as pd

from gridshedwatch import alerts, benchmark, data

H = pd.Timedelta(hours=1)


def two_events_in_tx():
    tx = next(e for e in data.event_list() if e["grid"] == "tx")
    second = dict(tx, id="tx_b", onset=tx["onset"] + 30 * 24 * H, split="held-out")
    return [tx, second]


def test_v1_event_list_is_one_event_per_grid():
    ev = data.event_list()
    assert [e["id"] for e in ev] == data.grids()
    assert all(e["onset"] == data.onset(e["grid"]) for e in ev)


def test_each_event_scored_and_alerts_counted_once():
    a, b = two_events_in_tx()
    starts = {0: {"tx": {"watch": [a["onset"] - 10 * H, b["onset"] - 20 * H, b["onset"] + 500 * H]}}}
    r = benchmark.evaluate_alerts("x", starts, chance=False, events=[a, b])
    w = r.rows[r.rows.level == "watch"].set_index("event")
    assert w.loc["tx", "caught"] and w.loc["tx_b", "caught"]
    assert w.loc["tx", "lead_h"] == 10 and w.loc["tx_b", "lead_h"] == 20
    assert (w.n_alerts == 3).all() and (w.n_verified == 2).all()       # grid totals, not per event
    s = r.summary
    assert s["watch_caught_all"] == 2 and s["watch_caught_held_out"] == 1
    assert s["watch_false_alarm_ratio"] == round(1 - 2 / 3, 3)


def test_release_keeps_v1_tier1_and_scores_every_grid():
    """v2.0 at the v1.0 operating point: Tier 1 equals v1.0, Tier 2 is verified, quiet grids count alerts."""
    t2 = next(e for e in data.event_list("2.0") if e["id"] == "ciso_2022-09-06")
    starts = {"tx": [data.onset("tx") - 10 * H], "ca": [t2["onset"] - 20 * H], "aeci": [t2["onset"]]}

    def fn(grid, level, threshold, persistence, seed):
        tb = data.timebase(grid)
        x = np.zeros(len(tb), dtype=int)
        if level == "watch":
            x[tb["timestamp"].searchsorted(starts.get(grid, []))] = 1
        return x

    r1 = benchmark.evaluate("x", fn, [0], chance=False)
    r2 = benchmark.evaluate_release("x", fn, [0], chance=False)
    for k, v in r1.summary.items():
        if k not in ("method", "seeds") and v == v:
            assert r2.summary["tier1_" + k] == v, k
    assert r2.summary["tier1_watch_caught_all"] == 1 and r2.summary["tier2_watch_caught_all"] == 1
    assert r2.summary["all_watch_false_alarm_ratio"] == 0            # both event-grid alerts verify an event
    b = r2.burden[(r2.burden.level == "watch") & (r2.burden.n_alerts > 0)]
    assert sorted(b.grid) == ["aeci", "ca", "tx"]
    assert r2.summary["burden_all_watch_grids"] == 48 and r2.summary["burden_quiet_watch_grids"] == 39


def test_alert_export_has_no_duplicates_with_two_events():
    a, b = two_events_in_tx()
    starts = {0: {"tx": {"watch": [a["onset"] - 10 * H]}}}
    r = benchmark.evaluate_alerts("x", starts, chance=False, events=[a, b])
    out = alerts.from_rows(r.rows)
    assert len(out[(out.grid == "tx") & (out.level == "watch")]) == 1
