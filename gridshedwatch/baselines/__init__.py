"""Reference methods. Each turns the five signals into per-signal scores p in [0, 1], except the
operator-style rule, which raises alerts directly from demand and its day-ahead forecast."""
import bisect

import numpy as np


def to_p(score: np.ndarray) -> np.ndarray:
    """Causal empirical CDF: share of strictly earlier scores that are <= the current one."""
    seen, p = [], np.zeros(len(score))
    for t, s in enumerate(score):
        p[t] = bisect.bisect_right(seen, s) / len(seen) if seen else 0.0
        bisect.insort(seen, s)
    return p
