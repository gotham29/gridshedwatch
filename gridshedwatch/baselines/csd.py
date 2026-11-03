"""Critical slowing down (Scheffer et al., 2009; Cotilla-Sanchez et al., 2012): rolling variance and
lag-1 autocorrelation of each signal over the past 168 hours; score = mean of their causal
percentiles (docs/protocol_v3.md). Deterministic."""
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p

WINDOW_H = 168


def indicators(x: pd.Series):
    var = x.rolling(WINDOW_H, min_periods=24).var()
    ac1 = x.rolling(WINDOW_H, min_periods=24).corr(x.shift(1))
    return var.fillna(0).to_numpy(), ac1.fillna(0).to_numpy()


def scores(grid: str) -> pd.DataFrame:
    X = data.signals(grid)
    out = {}
    for f in SIGNALS:
        var, ac1 = indicators(pd.Series(X[f].to_numpy(float)))
        out[f"p_{f}"] = (to_p(var) + to_p(ac1)) / 2
    return pd.DataFrame(out)
