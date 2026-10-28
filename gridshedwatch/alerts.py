"""Alerts track: read, check and write a method's watch and warning start times.

File format (CSV), one row per alert episode:
    grid,level,start_utc[,seed]
    tx,watch,2021-02-11 03:00,0
grid: one of gridshedwatch.data.grids(); level: watch or warning; start_utc: when the alert
episode began, UTC (ISO format; minutes allowed); seed: optional, for methods with randomness
(default 0). Starts must fall in the scored period: after the first week of the run (warm-up)
and before the end of the run. A grid with no rows has no alerts.

An episode is one alert, however long it lasts: if your method raises an alert and keeps it on,
list the time it came on. Alerts must be issued using data up to that time only.
"""
from pathlib import Path

import pandas as pd

from . import data

LEVELS = ("watch", "warning")
COLUMNS = ["grid", "level", "start_utc"]


def scored_period(grid: str) -> tuple:
    tb = data.timebase(grid)
    s = tb.loc[tb.in_warmup == 0, "timestamp"]
    return s.iloc[0], s.iloc[-1]


def check(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in COLUMNS if c not in df]
    if missing:
        raise ValueError(f"missing columns {missing}; need grid, level, start_utc (and optionally seed)")
    df = df.copy()
    if "seed" not in df:
        df["seed"] = 0
    bad = sorted(set(df.grid) - set(data.grids()))
    if bad:
        raise ValueError(f"unknown grids {bad}; use {data.grids()}")
    bad = sorted(set(df.level) - set(LEVELS))
    if bad:
        raise ValueError(f"unknown levels {bad}; use watch or warning")
    try:
        df["start_utc"] = pd.to_datetime(df.start_utc, utc=True).dt.tz_localize(None)
    except (ValueError, TypeError) as e:
        raise ValueError(f"start_utc must be UTC timestamps: {e}") from None
    df["seed"] = df.seed.astype(int)
    for g, x in df.groupby("grid"):
        lo, hi = scored_period(g)
        out = x[(x.start_utc < lo) | (x.start_utc > hi)]
        if len(out):
            raise ValueError(f"{g}: {len(out)} starts outside the scored period {lo} to {hi}, e.g. {out.start_utc.iloc[0]}")
    dup = df.duplicated(["seed", "grid", "level", "start_utc"])
    if dup.any():
        raise ValueError(f"{dup.sum()} duplicate rows (same seed, grid, level and start)")
    return df


def load(path) -> dict:
    """{seed: {grid: {level: [Timestamp, ...]}}}"""
    df = check(pd.read_csv(path))
    out = {}
    for (k, g, lv), x in df.groupby(["seed", "grid", "level"]):
        out.setdefault(int(k), {}).setdefault(g, {})[lv] = sorted(x.start_utc)
    return out or {0: {}}


def from_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Alert file rows from a scored Result's rows (to export a scores-track method's alerts)."""
    rows = rows.drop_duplicates(["seed", "grid", "level"])          # one row per event; alerts belong to the grid
    recs = [dict(grid=r.grid, level=r.level, start_utc=pd.Timestamp(t).strftime("%Y-%m-%d %H:%M"), seed=int(r.seed))
            for r in rows.itertuples() for t in str(r.starts).split("|") if t and t != "nan"]
    return pd.DataFrame(recs, columns=COLUMNS + ["seed"]).sort_values(["seed", "grid", "level", "start_utc"])


def write(df: pd.DataFrame, path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
