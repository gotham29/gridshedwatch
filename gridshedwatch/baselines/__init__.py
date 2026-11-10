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
    # reported beside the entries, not entries (docs/protocol_v3.md, New reference methods)
    "gbm_rt": ("Gradient-boosted forecaster (refit yearly)", "gbm:scores_retrained", range(5)),
    "dflevel": ("Day-ahead forecast level (weather control)", "dflevel", [0]),
}
CONTROLS = {"dflevel"}                                            # scored like a method, reported beside
ENTRIES = [m for m in METHODS if not m.endswith("_rt") and m not in CONTROLS]   # ranked and tested
LABEL = {m: v[0] for m, v in METHODS.items()}
HTM_V2 = "HTM (htm-monitor, frozen after 2019)"     # HTM's entry from v2.0 on (docs/protocol_v2.md)
V1_METHODS = ["oprule", "zscore", "chronos", "lstm", "htm"]     # the published v1.0 table


def scores(method: str, grid: str, seed: int = 0, **kw):
    """Per-signal scores of a reference method for one grid and seed (computed, not read from disk).
    METHODS gives "module" or "module:function"; extra keyword arguments (e.g. device) go to it."""
    spec = METHODS[method][1]
    if spec is None:
        raise ValueError(f"{method} has no scoring module here; its scores come from reference_scores/")
    mod, _, name = spec.partition(":")
    fn = getattr(importlib.import_module(f"{__name__}.{mod}"), name or "scores")
    import inspect
    kw = {k: v for k, v in kw.items() if k in inspect.signature(fn).parameters}
    return fn(grid, seed, **kw) if len(METHODS[method][2]) > 1 else fn(grid, **kw)  # deterministic: no seed


def training_sets(timestamps, cal: np.ndarray, run: np.ndarray, retrain: bool):
    """(run rows, training series) pairs. Frozen: all rows from a model fit on 2019 (cal). Refit
    yearly (docs/protocol_v3.md): each year's rows from a model fit on the preceding calendar year,
    2019 for the first. run may hold NaN (gaps); training windows with a gap are dropped."""
    if not retrain:
        return [(np.arange(len(run)), cal)]
    yr = pd.DatetimeIndex(timestamps).year.to_numpy()
    years = sorted(set(yr))
    return [(np.flatnonzero(yr == y), cal if y == years[0] else run[yr == y - 1]) for y in years]


def finite_windows(x: np.ndarray, L: int):
    """Sliding windows of L inputs plus the next value, keeping only windows without NaN."""
    W = np.lib.stride_tricks.sliding_window_view(np.asarray(x, float), L + 1)
    return W[np.isfinite(W).all(axis=1)]


def to_p(score: np.ndarray) -> np.ndarray:
    """Causal empirical CDF: share of strictly earlier scores that are <= the current one."""
    seen, p = [], np.zeros(len(score))
    for t, s in enumerate(score):
        p[t] = bisect.bisect_right(seen, s) / len(seen) if seen else 0.0
        bisect.insort(seen, s)
    return p


def likelihood(score: np.ndarray, value: np.ndarray = None, learn: int = 60, samples: int = 20, hist: int = 300,
               every: int = 10, avg: int = 3) -> np.ndarray:
    """Anomaly likelihood (Ahmad et al., 2017) as htm-monitor computes it, with htm-monitor's settings
    in hours (not Numenta's defaults, which assume 5-minute data). Vectorized; checked against
    htm-monitor's own output (identical on every hour of ERCOT's five signals, 2019-2026).

    0.5 for the first learn + samples steps. Then, every `every` steps, a normal is fit to the
    `avg`-step moving average of the previous `hist` scores (the first `learn` skipped while they are
    in the window; mean at least 0.03, variance at least 0.0003), or a null distribution if `value`
    barely varied over the window. Likelihood = 1 - the upper-tail probability of the current moving
    average, mirrored about the mean as in Numenta's code (so an unusually low score also scores
    high, which matters for percentile inputs); a tail below 1e-5 right after another is raised to 1e-3 (Numenta's filter)."""
    from scipy.special import erfc
    x = np.asarray(score, float)
    n, prob = len(x), learn + samples
    out = np.full(n, 0.5)
    if n <= prob:
        return out
    a = pd.Series(x).rolling(avg, min_periods=1).mean().to_numpy()
    mean, sd = np.full(n, 0.5), np.full(n, 1e3)
    for t in range(prob, n, every):
        lo = max(0, t - hist)
        h = pd.Series(x[lo:t]).rolling(avg, min_periods=1).mean().to_numpy()
        skip = min(t, max(0, learn - lo))
        m, v = 0.5, 1e6
        if len(h) > skip and not (value is not None and np.var(np.asarray(value, float)[lo:t][skip:]) < 1.5e-5):
            m, v = max(h[skip:].mean(), 0.03), max(h[skip:].var(), 0.0003)
        mean[t:t + every], sd[t:t + every] = m, np.sqrt(v)
    tail = lambda y: 0.5 * erfc(np.abs(y - mean) / sd / 1.4142)
    cur, prev = tail(a), tail(np.r_[a[0], a[:-1]])
    cur = np.where((cur <= 1e-5) & (prev <= 1e-5), 1e-3, cur)
    out[prob:] = 1.0 - cur[prob:]
    return out
