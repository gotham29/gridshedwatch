"""Seasonal z-score: how far each signal sits from the median of its past 30 days, in robust
standard deviations (median absolute deviation x 1.4826). Deterministic."""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p

WINDOW_H = 720


def robust_z(x: np.ndarray, W: int = WINDOW_H) -> np.ndarray:
    s = pd.Series(x)
    past = s.shift(1)
    med = past.rolling(W, min_periods=24).median()
    mad = (past - med).abs().rolling(W, min_periods=24).median()
    z = (s - med).abs() / (1.4826 * mad.replace(0, np.nan))
    return z.fillna(0).to_numpy()


def scores(grid: str) -> pd.DataFrame:
    X = data.signals(grid)
    return pd.DataFrame({f"p_{f}": to_p(robust_z(X[f].to_numpy(float))) for f in SIGNALS})
