"""The shared alert rules: per-signal scores p(t) in [0, 1] -> watch and warning alerts.

Every method's scores go through the same rule, so methods differ only in how they score
each signal each hour.

Per signal:  hot(t) = p(t) >= threshold; warmth(t) = share of hot hours in the last 8 steps.
Per group:   the group is hot if enough members are hot now (min_instant_members) or its
             mean warmth is at least min_group_warmth. Two groups: structure (demand and
             generation anomalies) and residual (forecast error, imbalance, imbalance anomaly).
System:      hot if both groups were hot at some step in the last W steps and one of them is hot
             now (W = 3 for a watch, 24 for a warning).
Alert:       on while the system has been hot for at least L consecutive steps (persistence).

Steps in the warm-up week never reach the rule. This is the htm-monitor GroupedConsensusDecision
with its options fixed to the v1.0 values; tests/test_rules.py checks the two agree.
"""
from collections import deque

import numpy as np
import pandas as pd

from .config import BASE_RULE, RULE, SIGNALS


class AlertRule:
    def __init__(self, threshold: float, persistence: int, coincidence_window: int, base: dict = BASE_RULE):
        if persistence < 1 or coincidence_window < 1:
            raise ValueError("persistence and coincidence_window must be >= 1")
        self.threshold = float(threshold)
        self.L = int(persistence)
        self.W = int(coincidence_window)
        self.k = int(base["group_k"])
        self.groups = base["groups"]
        self.members = [m for g in self.groups.values() for m in g["members"]]
        self.buf = {m: deque(maxlen=int(base["warmth_window"])) for m in self.members}
        self.recent = {g: deque(maxlen=self.W) for g in self.groups}
        self.streak = 0

    def step(self, p: dict) -> int:
        hot = {m: 1 if float(p[m]) >= self.threshold else 0 for m in self.members}
        for m in self.members:
            self.buf[m].append(hot[m])
        warmth = {m: sum(b) / len(b) for m, b in self.buf.items()}
        ghot = {}
        for g, spec in self.groups.items():
            n = sum(hot[m] for m in spec["members"])
            w = sum(warmth[m] for m in spec["members"]) / len(spec["members"])
            ghot[g] = 1 if (n >= spec["min_instant_members"] or w >= spec["min_group_warmth"]) else 0
            self.recent[g].append(ghot[g])
        count = sum(1 for g in self.groups if any(self.recent[g]))
        system_hot = count >= self.k and any(ghot.values())
        self.streak = self.streak + 1 if system_hot else 0
        return 1 if self.streak >= self.L else 0


def alerts(p: pd.DataFrame, warmup: np.ndarray, level: str, threshold: float, persistence: int) -> np.ndarray:
    """Hourly alert series (0/1) for one grid. p: one column per signal (p_<signal> or <signal>)."""
    cols = {s: (p[f"p_{s}"] if f"p_{s}" in p else p[s]).to_numpy(float) for s in SIGNALS}
    rule = AlertRule(threshold, persistence, RULE[level]["group_coincidence_window"])
    out = np.zeros(len(p), dtype=int)
    for i in range(len(p)):
        if warmup[i]:
            continue
        out[i] = rule.step({s: cols[s][i] for s in SIGNALS})
    return out


def episodes(alert: np.ndarray, timestamps, warmup: np.ndarray) -> list:
    """Start times of alert episodes: runs of consecutive post-warm-up steps with alert = 1."""
    ts = pd.to_datetime(pd.Series(timestamps)).to_numpy()
    on = (np.asarray(alert) == 1) & (np.asarray(warmup) == 0)
    starts = on & ~np.r_[False, on[:-1]]
    return [pd.Timestamp(x) for x in ts[starts]]


def _run_length(x: np.ndarray) -> np.ndarray:
    """Length of the run of True ending at each position."""
    out = np.zeros(len(x), dtype=np.int64)
    run = 0
    idx = np.flatnonzero(np.diff(np.r_[0, x.astype(np.int8), 0]))     # run boundaries
    for a, b in zip(idx[::2], idx[1::2]):
        out[a:b] = np.arange(1, b - a + 1)
    return out


def alerts_fast(p: pd.DataFrame, warmup: np.ndarray, level: str, threshold: float, persistence: int,
                base: dict = BASE_RULE) -> np.ndarray:
    """Vectorized alerts(): identical output (tests/test_rules.py), about 100x faster."""
    W = RULE[level]["group_coincidence_window"]
    ww = int(base["warmth_window"])
    live = np.flatnonzero(np.asarray(warmup) == 0)
    n = len(live)
    hot = {}
    warmth = {}
    for s in SIGNALS:
        col = (p[f"p_{s}"] if f"p_{s}" in p else p[s]).to_numpy(float)[live]
        h = (col >= threshold).astype(np.int64)
        c = np.cumsum(np.r_[0, h])
        lo = np.maximum(np.arange(1, n + 1) - ww, 0)
        cnt = np.arange(1, n + 1) - lo
        hot[s] = h
        warmth[s] = (c[1:] - c[lo]) / cnt
    ghot = {}
    for g, spec in base["groups"].items():
        mem = spec["members"]
        inst = sum(hot[m] for m in mem)
        w = warmth[mem[0]]
        for m in mem[1:]:
            w = w + warmth[m]
        w = w / len(mem)
        ghot[g] = (inst >= spec["min_instant_members"]) | (w >= spec["min_group_warmth"])
    recent = {}
    for g, h in ghot.items():
        c = np.cumsum(np.r_[0, h.astype(np.int64)])
        lo = np.maximum(np.arange(1, n + 1) - W, 0)
        recent[g] = (c[1:] - c[lo]) > 0
    count = sum(r.astype(np.int64) for r in recent.values())
    system_hot = (count >= int(base["group_k"])) & np.logical_or.reduce(list(ghot.values()))
    out = np.zeros(len(p), dtype=int)
    out[live] = (_run_length(system_hot) >= int(persistence)).astype(int)
    return out
