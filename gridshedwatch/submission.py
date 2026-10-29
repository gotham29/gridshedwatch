"""Read and check a method's per-signal scores.

Layout of a submission folder:
    <folder>/s<seed>/<grid>.csv  (or .csv.gz)     one folder per seed; s0 only if deterministic
Each file has one row per timebase step of that grid (gridshedwatch.data.timebase), in order,
and five columns p_forecast_error, p_imbalance, p_demand_anom, p_net_generation_anom,
p_imbalance_anom, each in [0, 1]: how unusual that signal is at that hour (higher = more unusual).
Scores must be causal: the score at step t may use data up to t only.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .config import SIGNALS, VERSION

COLUMNS = [f"p_{s}" for s in SIGNALS]


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def check(df: pd.DataFrame, grid: str) -> None:
    n = len(data.timebase(grid))
    missing = [c for c in COLUMNS if c not in df]
    if missing:
        raise ValueError(f"{grid}: missing columns {missing}")
    if len(df) != n:
        raise ValueError(f"{grid}: {len(df)} rows, timebase has {n}")
    v = df[COLUMNS].to_numpy(float)
    if np.isnan(v).any():
        raise ValueError(f"{grid}: NaN scores")
    if (v < 0).any() or (v > 1).any():
        raise ValueError(f"{grid}: scores outside [0, 1]")


def load(folder, version: str = VERSION) -> dict:
    """{seed: {grid: DataFrame}} for every seed folder found, with every grid of the release."""
    folder = Path(folder)
    out = {}
    for sd in sorted(folder.glob("s[0-9]*")):
        if not sd.is_dir():
            continue
        k = int(sd.name[1:])
        out[k] = {}
        for g in data.grids(version):
            f = next((p for p in (sd / f"{g}.csv", sd / f"{g}.csv.gz") if p.exists()), None)
            if f is None:
                raise FileNotFoundError(f"{sd}: no scores for {g}")
            df = _read(f)
            check(df, g)
            out[k][g] = df[COLUMNS]
    if not out:
        raise FileNotFoundError(f"{folder}: no s<seed>/ folders")
    return out


def write(scores: dict, folder) -> None:
    """Write {seed: {grid: DataFrame}} in the submission layout."""
    for k, per_grid in scores.items():
        d = Path(folder) / f"s{k}"
        d.mkdir(parents=True, exist_ok=True)
        for g, df in per_grid.items():
            check(df, g)
            df[COLUMNS].to_csv(d / f"{g}.csv.gz", index=False, float_format="%.17g",
                               compression={"method": "gzip", "mtime": 0})
