"""Reference methods. Each turns the five signals into per-signal scores p in [0, 1], except the
operator-style rule, which raises alerts directly from demand and its day-ahead forecast.

METHODS lists every reference method once: its table label, the module that scores it (None for
methods whose scores come from reference_scores/ only), and its seeds. Adding a method means adding
a module with scores(grid, seed) and one line here; scripts/make_scores.py and the scoring scripts
pick it up from this list.
"""
import bisect
import importlib

import numpy as np
import pandas as pd

METHODS = {
    "oprule": ("Operator-style rule", None, [0]),
    "zscore": ("Seasonal z-score", "zscore", [0]),
    "chronos": ("Chronos-Bolt (zero-shot)", "chronos", [0]),
    "lstm": ("LSTM forecaster", "lstm", range(5)),
    "htm": ("HTM (htm-monitor)", None, range(5)),
    "subpca": ("Sub-PCA", "subpca", [0]),
    "gbm": ("Gradient-boosted forecaster", "gbm", range(5)),
    "patchtst": ("PatchTST forecaster", "patchtst", range(5)),
    "random": ("Random scores", "random_scores", range(5)),
    "cusum": ("CUSUM", "cusum", [0]),                              # added in v3.0 (docs/protocol_v3.md)
    "csd": ("Critical slowing down", "csd", [0]),
}
LABEL = {m: v[0] for m, v in METHODS.items()}
HTM_V2 = "HTM (htm-monitor, frozen after 2019)"     # HTM's entry from v2.0 on (docs/protocol_v2.md)
V1_METHODS = ["oprule", "zscore", "chronos", "lstm", "htm"]     # the published v1.0 table


def scores(method: str, grid: str, seed: int = 0):
    """Per-signal scores of a reference method for one grid and seed (computed, not read from disk)."""
    mod = METHODS[method][1]
    if mod is None:
        raise ValueError(f"{method} has no scoring module here; its scores come from reference_scores/")
    fn = importlib.import_module(f"{__name__}.{mod}").scores
    return fn(grid, seed) if len(METHODS[method][2]) > 1 else fn(grid)     # deterministic methods take no seed


def to_p(score: np.ndarray) -> np.ndarray:
    """Causal empirical CDF: share of strictly earlier scores that are <= the current one."""
    seen, p = [], np.zeros(len(score))
    for t, s in enumerate(score):
        p[t] = bisect.bisect_right(seen, s) / len(seen) if seen else 0.0
        bisect.insort(seen, s)
    return p


def likelihood(p: np.ndarray, learn: int = 60, samples: int = 20, hist: int = 300, every: int = 10,
               short: int = 3) -> np.ndarray:
    """Anomaly-likelihood transform (Ahmad et al., 2017) with htm-monitor's settings, in hours (not
    Numenta's defaults, which assume 5-minute data): after a learning period of `learn` and `samples`
    estimation steps, a normal is fit to the `short`-step moving average of the past `hist` scores and
    re-fit every `every` steps; likelihood = its CDF at the current moving average (0.5 before that).
    For the v3.0 ablation that passes every method's scores through it."""
    from scipy.special import ndtr
    a = pd.Series(np.asarray(p, float)).rolling(short, min_periods=1).mean()
    past = a.shift(1)
    mu, sd = past.rolling(hist, min_periods=1).mean(), past.rolling(hist, min_periods=1).std()
    fit = np.arange(len(a)) // every * every                       # re-fit every `every` steps
    mu, sd = mu.to_numpy()[fit], np.sqrt(np.maximum(np.nan_to_num(sd.to_numpy()[fit] ** 2), 1.5e-5))
    out = ndtr((a.to_numpy() - mu) / sd)
    out[: learn + samples] = 0.5
    return np.nan_to_num(out, nan=0.5)
