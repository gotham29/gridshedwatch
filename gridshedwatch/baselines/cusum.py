"""CUSUM (Page, 1954): two-sided cumulative sum of each signal's robust deviation from its past 30
days, k = 0.5, each side reset to 0 after it passes h = 5 (docs/protocol_v3.md). Deterministic."""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p
from .zscore import robust_dev

K, H_RESET = 0.5, 5.0


def cusum(z: np.ndarray) -> np.ndarray:
    hi = lo = 0.0
    out = np.zeros(len(z))
    for t, v in enumerate(z):
        hi, lo = max(0.0, hi + v - K), max(0.0, lo - v - K)
        out[t] = max(hi, lo)
        hi, lo = (0.0 if hi > H_RESET else hi), (0.0 if lo > H_RESET else lo)
    return out


def scores(grid: str) -> pd.DataFrame:
    X = data.signals(grid)
    return pd.DataFrame({f"p_{f}": to_p(cusum(robust_dev(X[f].to_numpy(float)))) for f in SIGNALS})
