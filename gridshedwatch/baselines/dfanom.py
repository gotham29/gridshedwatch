"""Weather control: how unusual the grid's own day-ahead demand forecast is for the time of year: the
forecast minus the median of the same hour in the previous four weeks (the rule the seasonal signals
use), as a causal percentile, for every signal. No realized data, so no publication delay. Deterministic."""
import numpy as np
import pandas as pd

from .. import data
from ..config import SEASONAL_LAGS, SIGNALS
from . import to_p


def scores(grid: str) -> pd.DataFrame:
    w = data.clean_eia930(grid)
    df = w["DF"].asfreq("h").reindex(data.timebase(grid)["timestamp"]).ffill()
    base = pd.concat([df.shift(L) for L in SEASONAL_LAGS], axis=1).median(axis=1)
    p = to_p((df - base).fillna(0).to_numpy(float))
    return pd.DataFrame({f"p_{f}": p for f in SIGNALS})
