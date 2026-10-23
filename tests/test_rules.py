"""The shared alert rule: reference loop and vectorized version agree, on simple cases and at random."""
import numpy as np
import pandas as pd
import pytest

from gridshedwatch import rules
from gridshedwatch.config import SIGNALS


def frame(rows):
    return pd.DataFrame(rows, columns=[f"p_{s}" for s in SIGNALS])


def test_needs_both_groups_and_persistence():
    n = 40
    p = np.zeros((n, 5))
    p[10:20, 0] = 1.0            # residual only (forecast_error): never alerts
    p[25:35, :] = 1.0            # everything hot for 10 steps
    warm = np.zeros(n, dtype=int)
    a = rules.alerts(frame(p), warm, "watch", 0.99, 3)
    assert a[10:24].sum() == 0
    assert a[25:27].sum() == 0 and a[27] == 1 and a[34] == 1


def test_warmup_steps_never_alert():
    p = np.ones((20, 5))
    warm = np.r_[np.ones(10, dtype=int), np.zeros(10, dtype=int)]
    a = rules.alerts(frame(p), warm, "watch", 0.5, 3)
    assert a[:12].sum() == 0 and a[12] == 1


@pytest.mark.parametrize("trial", range(20))
def test_fast_equals_reference(trial):
    rng = np.random.default_rng(trial)
    n = 2000
    p = rng.uniform(0, 1, (n, 5))
    for _ in range(6):
        a = rng.integers(0, n - 100)
        p[a:a + rng.integers(1, 80), rng.choice(5, rng.integers(1, 6), replace=False)] = rng.uniform(0.95, 1)
    warm = (np.arange(n) < 168).astype(int)
    for level in ("watch", "warning"):
        thr, L = float(rng.choice([0.9, 0.95, 0.99])), int(rng.choice([3, 6, 12, 24]))
        assert (rules.alerts(frame(p), warm, level, thr, L) == rules.alerts_fast(frame(p), warm, level, thr, L)).all()


def test_matches_htm_monitor_if_installed():
    dec = pytest.importorskip("htm_monitor.orchestration.decision")
    rng = np.random.default_rng(7)
    n = 1500
    p = rng.uniform(0.9, 1, (n, 5))
    cfg = {"decision": {"threshold": 0.99, "model_warmth": {"window_size": 8},
                        "system": {"group_k": 2, "min_system_len": 4, "persistence_window": 4,
                                   "group_coincidence_window": 3, "release_after": 0},
                        "groups": {"structure": {"members": ["demand_anom", "net_generation_anom"],
                                                 "min_instant_members": 2, "min_group_warmth": 0.45},
                                   "residual": {"members": ["forecast_error", "imbalance", "imbalance_anom"],
                                                "min_instant_members": 1, "min_group_warmth": 0.5}}}}
    d = dec.GroupedConsensusDecision(cfg)
    ref = [d.step({s: {"p": p[i, j]} for j, s in enumerate(SIGNALS)})["alert"] for i in range(n)]
    assert (np.array(ref) == rules.alerts_fast(frame(p), np.zeros(n, dtype=int), "watch", 0.99, 4)).all()


def test_episodes_are_runs():
    ts = pd.date_range("2021-01-01", periods=10, freq="h")
    al = np.array([0, 1, 1, 0, 1, 0, 0, 1, 1, 1])
    st = rules.episodes(al, ts, np.zeros(10, dtype=int))
    assert st == [ts[1], ts[4], ts[7]]
