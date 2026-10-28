"""Random scores: each signal's score is a uniform draw each hour, independent of the data. Run
through the same rules and budget as every method, it shows what the table looks like with no
information at all (the chance baseline does the same by shifting a method's own alerts).
Seed k draws from numpy's default generator seeded 1000 + k."""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS


def scores(grid: str, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng([1000 + seed, data.grids().index(grid)])
    n = len(data.timebase(grid))
    return pd.DataFrame({f"p_{f}": np.round(rng.random(n), 6) for f in SIGNALS})
