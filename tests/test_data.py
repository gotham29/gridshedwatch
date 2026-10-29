"""The data snapshots and the five signals: exactly v1.0 for its 8 grids, and the v2.0 additions."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from gridshedwatch import data
from gridshedwatch.config import MIN_COVERAGE, ROOT, SIGNALS, SNAPSHOTS

EXPECTED = json.loads((Path(__file__).parent / "expected_signals.json").read_text())


@pytest.mark.parametrize("version", list(SNAPSHOTS))
def test_snapshot_checksums(version):
    folder = SNAPSHOTS[version]
    lines = (folder / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == sum(x["since"] == version for x in data.grid_table().values())
    for line in lines:
        digest, name = line.split()
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name


def test_release_sets():
    assert data.grids() == data.grids("1.0") == list(data.events())          # v1.0 is the default, unchanged
    assert [e["id"] for e in data.event_list()] == list(data.events())
    assert len(data.grids("2.0")) == 48 and data.grids("2.0")[:8] == data.grids("1.0")
    ev = data.event_list("2.0")
    assert len(ev) == 10 and sum(e["tier"] == 2 for e in ev) == 2
    assert all(e["grid"] in data.grids("2.0") for e in ev)
    for g, e in data.events().items():                                          # one source of truth per grid
        assert data.grid_table()[g]["eia930_respondent"] == e["eia930_respondent"]


def test_tier2_events_match_their_records():
    rec = {c["id"]: c for c in yaml.safe_load((ROOT / "docs" / "tier2_candidates.yaml").read_text())["candidates"]}
    for e in data.event_list("2.0"):
        if e["tier"] == 2:
            c = rec[e["id"]]
            assert c["decision"] == "include" and all(t["pass"] for t in c["tests"].values())
            assert e["onset"] == pd.Timestamp(c["declared"]["utc"]) and e["split"] == "held-out"


def test_v2_grids_pass_the_coverage_rule():
    q = pd.read_csv(SNAPSHOTS["2.0"] / "quality.csv").set_index("grid")
    assert list(q.index) == data.grids("2.0")
    new = [g for g in data.grids("2.0") if data.grid_table()[g]["since"] == "2.0"]
    assert (q.loc[new, ["cal_coverage", "run_coverage"]] >= MIN_COVERAGE).all().all()


def test_eight_events_and_splits():
    ev = data.events()
    assert len(ev) == 8
    assert sorted(g for g, e in ev.items() if e["split"] == "development") == ["ca", "tva", "tx"]


@pytest.mark.parametrize("grid", list(EXPECTED))
def test_signals_match_v1(grid):
    S = data.signals(grid)
    e = EXPECTED[grid]
    assert len(S) == e["steps"]
    assert str(S.timestamp.iloc[0]) == e["first"] and str(S.timestamp.iloc[-1]) == e["last"]
    for f in SIGNALS:
        assert np.isclose(S[f].sum(), e["sums"][f], rtol=0, atol=1e-3), f


def test_timebase_warmup_and_onsets_inside_run():
    for e in data.event_list("2.0"):
        tb = data.timebase(e["grid"])
        assert tb.in_warmup.sum() == 168
        assert tb.timestamp.iloc[168] < e["onset"] < tb.timestamp.iloc[-1]


def test_no_lookahead_in_seasonal_anomaly():
    s = data.signal_series("tx")["demand_anom"]
    w = data.clean_eia930("tx")["D"]
    t = s.index[5000]
    # changing the future must not change the anomaly at t
    w2 = w.copy()
    w2[w2.index > t] = 0.0
    s2 = data.seasonal_anomaly(w2)
    assert s2[t] == s[t]


def test_frozen_bounds_match_recomputed_within_rounding():
    from gridshedwatch import data
    for g in data.grids("2.0"):
        fz, rc = data.bounds_2019(g), data.bounds_2019(g, frozen=False)
        assert set(fz) == set(rc)
        for f in fz:
            assert abs(fz[f][0] - rc[f][0]) <= 0.0101 and abs(fz[f][1] - rc[f][1]) <= 0.0101, (g, f)
