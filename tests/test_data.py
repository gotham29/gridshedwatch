"""The data snapshot and the five signals are exactly v1.0."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from gridshedwatch import data
from gridshedwatch.config import DATA, SIGNALS

EXPECTED = json.loads((Path(__file__).parent / "expected_signals.json").read_text())


def test_snapshot_checksums():
    for line in (DATA / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest, name


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
    for g in data.grids():
        tb = data.timebase(g)
        assert tb.in_warmup.sum() == 168
        assert tb.timestamp.iloc[0] < data.onset(g) < tb.timestamp.iloc[-1]


def test_no_lookahead_in_seasonal_anomaly():
    s = data.signal_series("tx")["demand_anom"]
    w = data.clean_eia930("tx")["D"]
    t = s.index[5000]
    # changing the future must not change the anomaly at t
    w2 = w.copy()
    w2[w2.index > t] = 0.0
    s2 = data.seasonal_anomaly(w2)
    assert s2[t] == s[t]
