"""Score a warning method on GridShedWatch.

Two tracks. Scores track (`evaluate`): a method is a function
`alerts(grid, level, threshold, persistence, seed) -> 0/1 array` on the grid's timebase. Most methods supply per-signal scores and use `from_scores`, which runs them
through the shared rules; a method with its own alert logic (the operator-style rule) supplies
the function directly.

Steps, all fixed in advance:
  1. Sweep: alert episodes for every (threshold, persistence) setting, every grid and seed.
  2. Operating point: for each level, the setting whose median-grid alert rate (mean over seeds)
     is the largest at or under the budget (12 watches, 2 warnings per grid-year). No labels.
  3. Verification at that setting: events caught, lead time, alerts per grid-year, false alarm
     ratio, with bootstrap intervals over events and a chance baseline.

Alerts track (`evaluate_alerts`): a method submits its watch and warning start times directly.
Step 3 is identical; steps 1-2 are replaced by a check that the entry is within the same budget.

Events and grids: alerts are raised per grid, and each grid's alerts are verified against every
event in that grid (data.event_list(); v1.0 has one per grid). Scored rows are one per seed x event
x level; alert counts and rates belong to the grid, and an alert counts as verified if it verifies
any of its grid's events.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable

import numpy as np
import pandas as pd

from . import data, rules
from .config import BOOTSTRAP_DRAWS, BUDGET, GRID_CAP, CHANCE_SHIFTS, PERSISTENCE, THRESHOLDS, WINDOW

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


def verified(starts: list, onset: pd.Timestamp, level: str, window: dict = None) -> list:
    before, after = (window or WINDOW)[level]
    lo, hi = onset - before * H, onset + after * H
    if after == 0:
        return [s for s in starts if lo <= s < onset]
    return [s for s in starts if lo <= s <= hi]


def _by_grid(events: Iterable[dict] = None) -> Dict[str, list]:
    """Events grouped by grid id, in list order (default: data.event_list())."""
    out = {}
    for e in (data.event_list() if events is None else events):
        out.setdefault(e["grid"], []).append(e)
    return out


def sweep(alert_fn: Callable, seeds: Iterable[int], grids: Iterable[str] = None, window: dict = None,
          events: Iterable[dict] = None) -> pd.DataFrame:
    by_grid = _by_grid(events)
    rows = []
    for k in seeds:
        for g in grids or list(by_grid):
            tb = data.timebase(g)
            yrs = data.scored_years(g)
            warm = tb["in_warmup"].to_numpy()
            for level in LEVELS:
                for thr in THRESHOLDS:
                    for L in PERSISTENCE[level]:
                        al = alert_fn(g, level, thr, L, k)
                        st = rules.episodes(al, tb["timestamp"], warm)
                        rows += [dict(seed=k, grid=g, level=level, threshold=thr, L=L, **r)
                                 for r in _rows(st, g, level, by_grid[g], yrs, window)]
    return pd.DataFrame(rows)


def _row(st: list, grid: str, level: str, yrs: float = None, on: pd.Timestamp = None, window: dict = None) -> dict:
    """Verification of one seed x grid x level from its alert episode start times."""
    yrs = data.scored_years(grid) if yrs is None else yrs
    on = data.onset(grid) if on is None else on
    ver = verified(st, on, level, window)
    pre = [s for s in ver if s < on]
    caught = bool(pre) if level == "watch" else bool(ver)
    return dict(rate=len(st) / yrs, n_alerts=len(st), n_verified=len(ver), years=yrs, caught=caught,
                lead_h=(on - min(pre)) / H if pre else np.nan, starts="|".join(str(s) for s in st))


def _rows(st: list, grid: str, level: str, events: list, yrs: float = None, window: dict = None) -> list:
    """Verification of one seed x grid x level against each of the grid's events (one row per event).
    n_verified counts the grid's alerts that verify any of its events, so no alert counts twice."""
    out = [dict(event=e["id"], onset=e["onset"], **_row(st, grid, level, yrs, e["onset"], window)) for e in events]
    if len(events) > 1:
        n = len({s for e in events for s in verified(st, e["onset"], level, window)})
        for r in out:
            r["n_verified"] = n
    return out


def operating_point(sw: pd.DataFrame, budget: dict = None) -> Dict[str, tuple]:
    """Label-free setting per level: largest median-grid alert rate within budget."""
    budget = budget or BUDGET
    op = {}
    for level in LEVELS:
        x = sw[sw.level == level]
        per_grid = x.groupby(["threshold", "L", "grid"]).rate.mean()
        med = per_grid.groupby(["threshold", "L"]).median()
        ok = med[med <= budget[level]]
        if ok.empty:
            raise ValueError(f"no {level} setting within budget")
        best = ok.sort_values(kind="mergesort").index[-1]
        op[level] = (float(best[0]), int(best[1]), float(ok[best]))
    return op


def _boot(v: np.ndarray, rng) -> tuple:
    s = v[rng.integers(0, len(v), size=(BOOTSTRAP_DRAWS, len(v)))].sum(1)
    lo, hi = np.percentile(s, [5, 95])
    return float(lo), float(hi)


def _chance(rows: pd.DataFrame, level: str, rng, window: dict = None) -> tuple:
    """Expected catches and median lead if the same alerts were shifted to random times."""
    before, after = (window or WINDOW)[level]
    caught = np.zeros(CHANCE_SHIFTS)
    leads = []
    for _, x in rows.iterrows():
        tb = data.timebase(x.grid)
        t0 = tb.loc[tb.in_warmup == 0, "timestamp"].iloc[0]
        T = (tb["timestamp"].iloc[-1] - t0) / H
        s = np.array([(pd.Timestamp(v) - t0) / H for v in str(x.starts).split("|") if v and v != "nan"])
        o = (pd.Timestamp(x.onset) - t0) / H
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


def evaluate(method: str, alert_fn: Callable, seeds: Iterable[int], chance: bool = True, seed: int = 0,
             budget: dict = None, window: dict = None, events: Iterable[dict] = None) -> Result:
    """Scores track: sweep the shared settings, pick the label-free operating point, verify.

    budget and window default to the v1.0 settings (config.BUDGET, config.WINDOW); other values are
    for sensitivity analyses and make a different benchmark. events defaults to data.event_list()."""
    seeds = list(seeds)
    sw = sweep(alert_fn, seeds, window=window, events=events)
    op = operating_point(sw, budget)
    rows = pd.concat([sw[(sw.level == lv) & np.isclose(sw.threshold, op[lv][0]) & (sw.L == op[lv][1])] for lv in LEVELS])
    setting = {lv: f"threshold {op[lv][0]}, {op[lv][1]} h" for lv in LEVELS}
    return Result(method, sw, op, *_verify(method, rows, seeds, setting, chance, seed, window, events))


def evaluate_alerts(method: str, starts: dict, chance: bool = True, seed: int = 0, events: Iterable[dict] = None) -> Result:
    """Alerts track: score submitted alert episode starts {seed: {grid: {level: [Timestamp]}}} as they are.

    No operating point is chosen. Instead each level is checked against the same budget (median-grid
    rate at most the budget, as in the scores track) and, because alerts can be placed grid by grid,
    no single grid above GRID_CAP times the budget. `<level>_within_budget` says whether the entry
    is comparable with the table.
    """
    seeds = sorted(starts)
    by_grid = _by_grid(events)
    rows = [dict(seed=k, grid=g, level=lv, **r) for k in seeds for g in by_grid for lv in LEVELS
            for r in _rows(sorted(starts[k].get(g, {}).get(lv, [])), g, lv, by_grid[g])]
    rows = pd.DataFrame(rows)
    setting = {lv: "submitted alerts" for lv in LEVELS}
    rows, s = _verify(method, rows, seeds, setting, chance, seed, events=events)
    for lv in LEVELS:
        per_grid = rows[rows.level == lv].groupby("grid").rate.mean()
        s[f"{lv}_max_grid_rate"] = round(float(per_grid.max()), 2)
        s[f"{lv}_within_budget"] = bool(per_grid.median() <= BUDGET[lv] and per_grid.max() <= GRID_CAP * BUDGET[lv])
    return Result(method, None, None, rows, s)


def _verify(method, rows, seeds, setting, chance, seed, window=None, events=None):
    split = {e["id"]: e["split"] for es in _by_grid(events).values() for e in es}
    rows = rows.assign(held_out=rows.event.map(lambda e: split[e] == "held-out"))
    rng = np.random.default_rng(seed)
    s = {"method": method, "seeds": len(seeds)}
    for lv in LEVELS:
        x = rows[rows.level == lv]
        per_event = x.groupby("event").caught.mean()
        held = per_event[[e for e in per_event.index if split[e] == "held-out"]]
        per_seed = x.drop_duplicates(["seed", "grid"]).groupby("seed").agg(
            alerts=("n_alerts", "sum"), ver=("n_verified", "sum"), yrs=("years", "sum"))      # per grid
        per_seed["caught"] = x.groupby("seed").caught.sum()                                     # per event
        s[f"{lv}_setting"] = setting[lv]
        s[f"{lv}_median_grid_rate"] = round(float(x.groupby("grid").rate.mean().median()), 2)
        s[f"{lv}_caught_all"] = round(float(per_event.sum()), 1)
        s[f"{lv}_caught_all_ci"] = "%.1f-%.1f" % _boot(per_event.to_numpy(float), rng)
        s[f"{lv}_caught_held_out"] = round(float(held.sum()), 1)
        s[f"{lv}_caught_held_out_ci"] = "%.1f-%.1f" % _boot(held.to_numpy(float), rng)
        s[f"{lv}_caught_seed_range"] = f"{int(per_seed.caught.min())}-{int(per_seed.caught.max())}"
        s[f"{lv}_median_lead_h"] = round(float(np.nanmedian(x.lead_h)), 0) if x.lead_h.notna().any() else np.nan
        s[f"{lv}_alerts_per_grid_year"] = round(float((per_seed.alerts / per_seed.yrs).mean()), 1)
        s[f"{lv}_false_alarm_ratio"] = round(float((1 - per_seed.ver / per_seed.alerts).mean()), 3) \
            if (per_seed.alerts > 0).all() else np.nan
        if chance:
            nulls = [_chance(g, lv, rng, window) for _, g in x.groupby("seed")]
            s[f"{lv}_chance_caught"] = round(float(np.mean([c for c, _, _ in nulls])), 1)
            s[f"{lv}_chance_median_lead_h"] = round(float(np.nanmedian([m for _, m, _ in nulls])), 0)
            s[f"{lv}_chance_p"] = round(float(np.mean([(d >= c_obs).mean() for (_, _, d), c_obs in
                                                       zip(nulls, x.groupby("seed").caught.sum())])), 3)
    return rows, s


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
