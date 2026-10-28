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
}
LABEL = {m: v[0] for m, v in METHODS.items()}
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
