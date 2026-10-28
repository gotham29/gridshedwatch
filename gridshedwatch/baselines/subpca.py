"""Sub-PCA: PCA on subsequences, the top-ranked univariate detector in TSB-AD (Liu & Paparrizos,
NeurIPS 2024 D&B). Needs scikit-learn.

Per grid and signal, each hour is represented by the window of the last 24 values (ending at that
hour, so scores are causal), minus the window's mean. PCA is fit on 2019 windows, keeping the
components that explain 90% of the variance; the score is the reconstruction error of the hour's
window, in 2019 standard deviations of that error. Deterministic. Settings are TSB-AD-style
defaults, not tuned on events.
"""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p

L = 24
VARIANCE = 0.90


def _windows(x: np.ndarray) -> np.ndarray:
    W = np.lib.stride_tricks.sliding_window_view(x, L)
    return W - W.mean(axis=1, keepdims=True)


def scores(grid: str) -> pd.DataFrame:
    from sklearn.decomposition import PCA

    X = data.signals(grid)
    cal_all = data.calibration(grid)
    b = data.bounds_2019(grid)
    out = {}
    for f in SIGNALS:
        lo, hi = b[f]
        cal = (cal_all[f].dropna().to_numpy(float) - lo) / (hi - lo)
        run = np.nan_to_num((X[f].to_numpy(float) - lo) / (hi - lo), nan=0.0)
        Wc = _windows(cal)
        pca = PCA(n_components=VARIANCE, svd_solver="full").fit(Wc)
        err_c = ((Wc - pca.inverse_transform(pca.transform(Wc))) ** 2).sum(1)
        Wr = _windows(np.concatenate([cal[-(L - 1):], run]))      # window ending at each run hour
        err = ((Wr - pca.inverse_transform(pca.transform(Wr))) ** 2).sum(1)
        out[f"p_{f}"] = np.round(to_p(err / err_c.std()), 6)
    return pd.DataFrame(out)
