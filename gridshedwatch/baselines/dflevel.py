"""Weather control: how unusual the grid's own day-ahead demand forecast is. Every signal gets the causal
percentile of the day-ahead forecast (DF), so the shared rule alerts when the operator already expects
extreme demand. It uses no realized data, so it has no publication delay. A method that beats chance but
not this control may be detecting forecast weather rather than a supply shortfall. Deterministic."""
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p


def scores(grid: str) -> pd.DataFrame:
    w = data.clean_eia930(grid)
    df = w["DF"].asfreq("h").reindex(data.timebase(grid)["timestamp"]).ffill().fillna(0).to_numpy(float)
    p = to_p(df)
    return pd.DataFrame({f"p_{f}": p for f in SIGNALS})
