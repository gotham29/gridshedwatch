"""Events, the frozen EIA-930 snapshot, and the five signals built from it.

The snapshot (gridshedwatch/snapshot_v1.0/eia930/<BA>.csv.gz) holds hourly D (demand), DF (day-ahead demand
forecast) and NG (net generation) from EIA-930, UTC, Jan 2019 - Oct 2026, as pulled in Oct 2026.
EIA revises old values, so the snapshot, not today's API, defines v1.0. scripts/pull_eia930.py
re-pulls it and reports any differences.

Signal rule (same for every grid, no look-ahead):
  1. Keep hours that have all of D, DF and NG.
  2. Bad-data filter: drop hours where D, DF or NG is <= 0 or above 2x that series' 2019
     99.9th percentile.
  3. forecast_error = D - DF; imbalance = D - NG.
  4. Seasonal anomalies of D, NG and D - NG: value minus the median of the same hour 1-4 weeks
     earlier (2019 seeds the lags).
"""
from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from .config import CAL_END, CAL_START, DATA, PACKAGE, RUN_END, RUN_START, SEASONAL_LAGS, SIGNALS, WARMUP_STEPS

H = pd.Timedelta(hours=1)


@lru_cache(maxsize=None)
def events() -> dict:
    """The eight v1.0 events, keyed by grid id (tx, ca, tva, spp, miso, duk, cple, lgee)."""
    return yaml.safe_load((PACKAGE / "events.yaml").read_text())["events"]


def grids() -> list:
    return list(events())


def onset(grid: str) -> pd.Timestamp:
    return pd.Timestamp(events()[grid]["onset_utc"])


@lru_cache(maxsize=None)
def load_eia930(grid: str) -> pd.DataFrame:
    """Hourly D, DF, NG for a grid (UTC index), hours with all three present."""
    ba = events()[grid]["eia930_respondent"]
    w = pd.read_csv(DATA / "eia930" / f"{ba}.csv.gz", index_col="period_utc")
    w.index = pd.to_datetime(w.index, format="%Y-%m-%dT%H")
    w.index.name = "timestamp"
    return w[["D", "DF", "NG"]].dropna().sort_index()


def glitch_mask(w: pd.DataFrame, ref: pd.DataFrame, cols=("D", "DF", "NG")) -> pd.Series:
    """True where any column is <= 0 or above 2x its 99.9th percentile in ref."""
    bad = pd.Series(False, index=w.index)
    for c in cols:
        hi = 2 * ref[c][ref[c] > 0].quantile(0.999)
        bad |= (w[c] <= 0) | (w[c] > hi)
    return bad


def clean_eia930(grid: str) -> pd.DataFrame:
    """D, DF, NG after the 2019 bad-data filter."""
    w = load_eia930(grid)
    cal = (w.index >= CAL_START) & (w.index <= CAL_END)
    return w[~glitch_mask(w, w[cal])]


def seasonal_anomaly(x: pd.Series) -> pd.Series:
    x = x.asfreq("h")
    base = pd.concat([x.shift(L) for L in SEASONAL_LAGS], axis=1).median(axis=1, skipna=True)
    return (x - base).dropna()


@lru_cache(maxsize=None)
def signal_series(grid: str) -> dict:
    """Each signal as its own series, 2019 through the end of the run (index: UTC hours)."""
    w = clean_eia930(grid)
    return {"forecast_error": w["D"] - w["DF"], "imbalance": w["D"] - w["NG"],
            "demand_anom": seasonal_anomaly(w["D"]), "net_generation_anom": seasonal_anomaly(w["NG"]),
            "imbalance_anom": seasonal_anomaly(w["D"] - w["NG"])}


@lru_cache(maxsize=None)
def timebase(grid: str) -> pd.DataFrame:
    """The scored timeline: every run hour in which any signal exists, in order.

    Columns: t (step index), timestamp, in_warmup (first WARMUP_STEPS steps). Alert episodes are
    runs of consecutive steps, so an hour missing from every signal does not break an episode.
    """
    idx = None
    for s in signal_series(grid).values():
        run = s.index[(s.index >= RUN_START) & (s.index <= RUN_END)]
        idx = run if idx is None else idx.union(run)
    tb = pd.DataFrame({"t": np.arange(len(idx)), "timestamp": idx})
    tb["in_warmup"] = (tb["t"] < WARMUP_STEPS).astype(int)
    return tb


@lru_cache(maxsize=None)
def signals(grid: str) -> pd.DataFrame:
    """The five signals on the timebase (last value held where a signal is missing)."""
    tb = timebase(grid)
    out = {f: s.reindex(tb["timestamp"], method="ffill").to_numpy() for f, s in signal_series(grid).items()}
    df = pd.DataFrame(out)[list(SIGNALS)]
    df.insert(0, "timestamp", tb["timestamp"].to_numpy())
    return df


def calibration(grid: str) -> pd.DataFrame:
    """The five signals over 2019 (for methods that learn before the run), on their own hours."""
    ser = signal_series(grid)
    cal = {f: s[(s.index >= CAL_START) & (s.index <= CAL_END)] for f, s in ser.items()}
    return pd.DataFrame(cal)[list(SIGNALS)]


def scored_years(grid: str) -> float:
    tb = timebase(grid)
    s = tb.loc[tb.in_warmup == 0, "timestamp"]
    return (s.iloc[-1] - s.iloc[0]) / pd.Timedelta(days=365.25)


@lru_cache(maxsize=None)
def operator_notices() -> dict:
    """Operators' notices in the week before each event (status quo row)."""
    return yaml.safe_load((PACKAGE / "operator_notices.yaml").read_text())["events"]


def bounds_2019(grid: str) -> dict:
    """0.1st-99.9th percentile of each signal over 2019 (for methods that need a fixed scale)."""
    cal = calibration(grid)
    return {f: (round(float(cal[f].dropna().quantile(0.001)), 2), round(float(cal[f].dropna().quantile(0.999)), 2))
            for f in SIGNALS}
