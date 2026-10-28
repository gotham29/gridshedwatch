"""Scoring with several events in one grid: each event is scored on its own, alerts are counted
once per grid, and an alert that verifies any event is not a false alarm."""
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


def test_alert_export_has_no_duplicates_with_two_events():
    a, b = two_events_in_tx()
    starts = {0: {"tx": {"watch": [a["onset"] - 10 * H]}}}
    r = benchmark.evaluate_alerts("x", starts, chance=False, events=[a, b])
    out = alerts.from_rows(r.rows)
    assert len(out[(out.grid == "tx") & (out.level == "watch")]) == 1
