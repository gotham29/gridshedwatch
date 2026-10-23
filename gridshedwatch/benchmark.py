"""Score a warning method on GridShedWatch.

A method is a function `alerts(grid, level, threshold, persistence, seed) -> 0/1 array` on the
grid's timebase. Most methods supply per-signal scores and use `from_scores`, which runs them
through the shared rules; a method with its own alert logic (the operator-style rule) supplies
the function directly.

Steps, all fixed in advance:
  1. Sweep: alert episodes for every (threshold, persistence) setting, every grid and seed.
  2. Operating point: for each level, the setting whose median-grid alert rate (mean over seeds)
     is the largest at or under the budget (12 watches, 2 warnings per grid-year). No labels.
  3. Verification at that setting: events caught, lead time, alerts per grid-year, false alarm
     ratio, with bootstrap intervals over events and a chance baseline.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable

import numpy as np
import pandas as pd

from . import data, rules
from .config import BOOTSTRAP_DRAWS, BUDGET, CHANCE_SHIFTS, PERSISTENCE, THRESHOLDS, WINDOW

H = pd.Timedelta(hours=1)
LEVELS = ("watch", "warning")


def from_scores(scores: Dict[int, Dict[str, pd.DataFrame]]) -> Callable:
    """Wrap per-signal scores {seed: {grid: DataFrame with p_<signal> columns}} as an alert function."""
    def fn(grid, level, threshold, persistence, seed):
        p = scores[seed][grid]
        tb = data.timebase(grid)
        if len(p) != len(tb):
            raise ValueError(f"{grid}: {len(p)} score rows, timebase has {len(tb)}")
        return rules.alerts_fast(p, tb["in_warmup"].to_numpy(), level, threshold, persistence)
    return fn


def verified(starts: list, onset: pd.Timestamp, level: str) -> list:
    before, after = WINDOW[level]
    lo, hi = onset - before * H, onset + after * H
    if after == 0:
        return [s for s in starts if lo <= s < onset]
    return [s for s in starts if lo <= s <= hi]


def sweep(alert_fn: Callable, seeds: Iterable[int], grids: Iterable[str] = None) -> pd.DataFrame:
    rows = []
    for k in seeds:
        for g in grids or data.grids():
            tb = data.timebase(g)
            yrs = data.scored_years(g)
            on = data.onset(g)
            warm = tb["in_warmup"].to_numpy()
            for level in LEVELS:
                for thr in THRESHOLDS:
                    for L in PERSISTENCE[level]:
                        al = alert_fn(g, level, thr, L, k)
                        st = rules.episodes(al, tb["timestamp"], warm)
                        ver = verified(st, on, level)
                        pre = [s for s in ver if s < on]
                        caught = bool(pre) if level == "watch" else bool(ver)
                        rows.append(dict(seed=k, grid=g, level=level, threshold=thr, L=L, rate=len(st) / yrs,
                                         n_alerts=len(st), n_verified=len(ver), years=yrs, caught=caught,
                                         lead_h=(on - min(pre)) / H if pre else np.nan,
                                         starts="|".join(str(s) for s in st)))
    return pd.DataFrame(rows)


def operating_point(sw: pd.DataFrame) -> Dict[str, tuple]:
    """Label-free setting per level: largest median-grid alert rate within budget."""
    op = {}
    for level in LEVELS:
        x = sw[sw.level == level]
        per_grid = x.groupby(["threshold", "L", "grid"]).rate.mean()
        med = per_grid.groupby(["threshold", "L"]).median()
        ok = med[med <= BUDGET[level]]
        if ok.empty:
            raise ValueError(f"no {level} setting within budget")
        best = ok.sort_values(kind="mergesort").index[-1]
        op[level] = (float(best[0]), int(best[1]), float(ok[best]))
    return op


def _boot(v: np.ndarray, rng) -> tuple:
    s = v[rng.integers(0, len(v), size=(BOOTSTRAP_DRAWS, len(v)))].sum(1)
    lo, hi = np.percentile(s, [5, 95])
    return float(lo), float(hi)


def _chance(rows: pd.DataFrame, level: str, rng) -> tuple:
    """Expected catches and median lead if the same alerts were shifted to random times."""
    before, after = WINDOW[level]
    caught = np.zeros(CHANCE_SHIFTS)
    leads = []
    for _, x in rows.iterrows():
        tb = data.timebase(x.grid)
        t0 = tb.loc[tb.in_warmup == 0, "timestamp"].iloc[0]
        T = (tb["timestamp"].iloc[-1] - t0) / H
        s = np.array([(pd.Timestamp(v) - t0) / H for v in str(x.starts).split("|") if v and v != "nan"])
        o = (data.onset(x.grid) - t0) / H
        off = rng.uniform(0, T, CHANCE_SHIFTS)
        if not len(s):
            continue
        d = o - ((s[None, :] + off[:, None]) % T)                  # shifts x episodes, hours before onset
        inwin = (d <= before) & ((d >= -after) if after else (d > 0))
        caught += inwin.any(axis=1)
        pos = np.where(inwin & (d > 0), d, -np.inf).max(axis=1)
        leads.extend(pos[np.isfinite(pos)].tolist())
    return float(caught.mean()), float(np.median(leads)) if leads else np.nan, caught


@dataclass
class Result:
    method: str
    sweep: pd.DataFrame
    op: dict
    rows: pd.DataFrame = field(default=None)       # one row per seed x grid x level at the operating point
    summary: dict = field(default=None)


def evaluate(method: str, alert_fn: Callable, seeds: Iterable[int], chance: bool = True, seed: int = 0) -> Result:
    seeds = list(seeds)
    sw = sweep(alert_fn, seeds)
    op = operating_point(sw)
    rows = pd.concat([sw[(sw.level == lv) & np.isclose(sw.threshold, op[lv][0]) & (sw.L == op[lv][1])] for lv in LEVELS])
    ev = data.events()
    rows = rows.assign(held_out=rows.grid.map(lambda g: ev[g]["split"] == "held-out"))
    rng = np.random.default_rng(seed)
    s = {"method": method, "seeds": len(seeds)}
    for lv in LEVELS:
        x = rows[rows.level == lv]
        per_event = x.groupby("grid").caught.mean()
        held = per_event[[g for g in per_event.index if ev[g]["split"] == "held-out"]]
        per_seed = x.groupby("seed").agg(alerts=("n_alerts", "sum"), ver=("n_verified", "sum"),
                                         caught=("caught", "sum"), yrs=("years", "sum"))
        s[f"{lv}_setting"] = f"threshold {op[lv][0]}, {op[lv][1]} h"
        s[f"{lv}_median_grid_rate"] = round(op[lv][2], 2)
        s[f"{lv}_caught_all"] = round(float(per_event.sum()), 1)
        s[f"{lv}_caught_all_ci"] = "%.1f-%.1f" % _boot(per_event.to_numpy(float), rng)
        s[f"{lv}_caught_held_out"] = round(float(held.sum()), 1)
        s[f"{lv}_caught_held_out_ci"] = "%.1f-%.1f" % _boot(held.to_numpy(float), rng)
        s[f"{lv}_caught_seed_range"] = f"{int(per_seed.caught.min())}-{int(per_seed.caught.max())}"
        s[f"{lv}_median_lead_h"] = round(float(np.nanmedian(x.lead_h)), 0) if x.lead_h.notna().any() else np.nan
        s[f"{lv}_alerts_per_grid_year"] = round(float((per_seed.alerts / per_seed.yrs).mean()), 1)
        s[f"{lv}_false_alarm_ratio"] = round(float((1 - per_seed.ver / per_seed.alerts).mean()), 3)
        if chance:
            nulls = [_chance(g, lv, rng) for _, g in x.groupby("seed")]
            s[f"{lv}_chance_caught"] = round(float(np.mean([c for c, _, _ in nulls])), 1)
            s[f"{lv}_chance_median_lead_h"] = round(float(np.nanmedian([m for _, m, _ in nulls])), 0)
            s[f"{lv}_chance_p"] = round(float(np.mean([(d >= c_obs).mean() for (_, _, d), c_obs in
                                                       zip(nulls, x.groupby("seed").caught.sum())])), 3)
    return Result(method, sw, op, rows, s)


def status_quo() -> dict:
    """The operators' public notices, scored as watches: caught = any public notice before onset."""
    caught, leads = {}, []
    for g, e in data.operator_notices().items():
        on = data.onset(g)
        pub = [pd.Timestamp(n["utc"]) for n in e["notices"] if n.get("public")]
        pre = [t for t in pub if on - WINDOW["watch"][0] * H <= t < on]
        caught[g] = bool(pre)
        if pre:
            leads.append((on - min(pre)) / H)
    ev = data.events()
    return {"method": "Operators (public notices)", "watch_caught_all": float(sum(caught.values())),
            "watch_caught_held_out": float(sum(v for g, v in caught.items() if ev[g]["split"] == "held-out")),
            "watch_median_lead_h": round(float(np.median(leads)), 0) if leads else np.nan, "by_grid": caught}
