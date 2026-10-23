"""Operator-style rule: no per-signal model and no groups. An hour is hot when demand runs above
the day-ahead forecast by more than the trailing year's q-th percentile of percent forecast error
(q = the benchmark threshold); an alert is on after `persistence` hot hours in a row."""
from functools import lru_cache

import numpy as np
import pandas as pd

from .. import data


@lru_cache(maxsize=None)
def hot(grid: str, q: float) -> np.ndarray:
    w = data.clean_eia930(grid)
    pct = ((w["D"] - w["DF"]) / w["DF"].where(w["DF"] > 0) * 100).asfreq("h")
    thr = pct.shift(1).rolling(8760, min_periods=24 * 90).quantile(q)
    ts = data.timebase(grid)["timestamp"]
    p, th = pct.reindex(ts).to_numpy(), thr.reindex(ts).to_numpy()
    return np.nan_to_num(p, nan=-np.inf) > np.nan_to_num(th, nan=np.inf)


def alerts(grid: str, level: str, threshold: float, persistence: int, seed: int = 0) -> np.ndarray:
    h = hot(grid, threshold)
    warm = data.timebase(grid)["in_warmup"].to_numpy()
    a, run = np.zeros(len(h), dtype=int), 0
    for i, x in enumerate(h):
        if warm[i]:
            run = 0
            continue
        run = run + 1 if x else 0
        a[i] = int(run >= persistence)
    return a
