"""Protocol v4.0: score a method's alert start times, with no alert budget.

Input: {seed: [(grid, Timestamp), ...]} or a CSV with grid, start_utc[, seed]. Alerts on one grid that
start within MERGE_H hours of the first alert of a run count as one false alarm at most (runs do not
chain, so an alert renewed every day counts every day); catches use every alert. For each seed, then averaged:
  caught          load sheds with an alert starting in the 7 days before onset (of 8), and by storm
  before_notice   of those, caught before the operator's first notice of any kind (and before_public:
                  before its first public notice)
  lead_h          median, over caught load sheds, of hours from the first such alert to onset
  false alarms    alerts per year on every grid, except those within a week either side of a load shed or
                  a masked emergency on that grid; median and worst grid
  selectivity     share of storm-hit quiet grids (demand anomaly in its top 1% in the 7 days before the
                  storm's first load shed; Uri and Elliott; grids with a masked emergency that week left
                  out) alerted in that week, next to the same share on the grids that shed load and
                  on every unmasked quiet grid in those weeks, with no demand filter
  chance          the seasonal chance baseline (benchmark.chance_v3): share of 2,000 moved copies that
                  catch at least as many load sheds
The forecast baseline at the same median false-alarm rate is read from FORECAST_LADDER.
"""
from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from . import benchmark, data
from .config import PACKAGE

VERSION4 = "2.0"                 # grids and events of release 2.0, scored by protocol v4.0
MERGE_H = 24
WEEK_H = 168
STORMS = ("Uri", "Elliott")
FORECAST_LADDER = PACKAGE / "forecast_ladder.csv"
H = pd.Timedelta(hours=1)


@lru_cache(maxsize=None)
def setup():
    ev = data.event_list(VERSION4)
    t1 = tuple(e for e in ev if e["tier"] == 1)
    near = tuple(data.near_misses()) + tuple(dict(id=e["id"], grid=e["grid"], time=e["onset"]) for e in ev if e["tier"] == 2)
    grids = tuple(data.grids(VERSION4))
    shed = {e["grid"] for e in t1}
    notices = yaml.safe_load((PACKAGE / "operator_notices.yaml").read_text())["events"]
    first = {g: min((pd.Timestamp(n["utc"]) for n in v.get("notices", [])), default=None) for g, v in notices.items()}
    from .protocol import _exposed
    units = []
    for storm in STORMS:
        es = [e for e in t1 if e["storm"] == storm]
        t0 = min(e["onset"] for e in es)
        units += [(storm, e["grid"], True, e["onset"]) for e in es]
        for g in grids:
            if g in shed or any(n["grid"] == g and abs(n["time"] - t0) <= WEEK_H * H for n in near):
                continue
            if _exposed(g, t0, WEEK_H):
                units.append((storm, g, False, t0))
    return t1, near, grids, first, tuple(units)


@lru_cache(maxsize=None)
def first_public() -> dict:
    """Each shed grid's first public notice (conservation appeal, emergency alert or press release)."""
    notices = yaml.safe_load((PACKAGE / "operator_notices.yaml").read_text())["events"]
    return {g: min((pd.Timestamp(n["utc"]) for n in v.get("notices", []) if n.get("public")), default=None)
            for g, v in notices.items()}


@lru_cache(maxsize=None)
def storm_quiet_all() -> tuple:
    """Every quiet grid in each storm's week, with no demand filter (grids with a masked emergency
    that week left out): (storm, grid, False, t0)."""
    t1, near, grids, _, _ = setup()
    shed = {e["grid"] for e in t1}
    out = []
    for storm in STORMS:
        t0 = min(e["onset"] for e in t1 if e["storm"] == storm)
        out += [(storm, g, False, t0) for g in grids if g not in shed
                and not any(n["grid"] == g and abs(n["time"] - t0) <= WEEK_H * H for n in near)]
    return tuple(out)


def merge(starts) -> list:
    out = []
    for t in sorted(starts):
        if not out or t - out[-1] >= MERGE_H * H:
            out.append(t)
    return out


def read(path) -> dict:
    df = pd.read_csv(path)
    if "level" in df:                                   # older files: only the watch level is an alert
        df = df[df.level == "watch"]
    if "seed" not in df:
        df["seed"] = 0
    bad = sorted(set(df.grid) - set(data.grids(VERSION4)))
    if bad:
        raise ValueError(f"unknown grids {bad}; use {data.grids(VERSION4)}")
    df["start_utc"] = pd.to_datetime(df.start_utc, utc=True).dt.tz_localize(None)
    return {int(k): list(zip(x.grid, x.start_utc)) for k, x in df.groupby("seed")} or {0: []}


def score(alerts: dict, chance: bool = True, seed: int = 0) -> dict:
    t1, near, grids, first, units = setup()
    st, raw = {}, {}                                    # merged runs (false alarms) and raw starts (catches)
    for k, rows in alerts.items():
        by = {}
        for g, t in rows:
            by.setdefault(g, []).append(pd.Timestamp(t))
        for g in grids:
            raw[(k, g)] = sorted(set(by.get(g, [])))
            st[(k, g)] = merge(raw[(k, g)])
    ev, gr = benchmark.verify_v3(raw, "watch", t1, near)
    on = {e["id"]: e["onset"] for e in t1}
    ev["before_notice"] = [bool(c) and (first.get(g) is None or l > (on[i] - first[g]) / H)
                           for c, g, l, i in zip(ev.caught, ev.grid, ev.lead_h, ev.event)]
    pub = first_public()
    ev["before_public"] = [bool(c) and (pub.get(g) is None or l > (on[i] - pub[g]) / H)
                           for c, g, l, i in zip(ev.caught, ev.grid, ev.lead_h, ev.event)]
    quiet_from = {}                                     # the week before and the week after each shed or masked emergency
    for t in [(e["grid"], e["onset"]) for e in t1] + [(n["grid"], n["time"]) for n in near]:
        quiet_from.setdefault(t[0], []).append(t[1])
    yrs = {g: data.scored_years(g) for g in grids}
    fa = pd.Series({g: np.mean([sum(not any(abs(s - t) < WEEK_H * H for t in quiet_from.get(g, [])) for s in st[(k, g)])
                                for k in alerts]) / yrs[g] for g in grids})
    seeds = sorted(alerts)
    hit = lambda us: np.array([np.mean([any(t - WEEK_H * H < s <= t for s in raw[(k, g)]) for k in seeds]) for _, g, _, t in us])
    val, every = hit(units), hit(storm_quiet_all())
    shed = np.array([u[2] for u in units])
    out = dict(seeds=len(seeds), caught=round(ev.groupby("seed").caught.sum().mean(), 1),
               caught_by_storm={s: round(x.groupby("seed").caught.sum().mean(), 1) for s, x in ev.groupby("storm")},
               caught_before_notice=round(ev.groupby("seed").before_notice.sum().mean(), 1),
               caught_before_public=round(ev.groupby("seed").before_public.sum().mean(), 1),
               median_lead_h=round(float(ev[ev.caught].groupby("event").lead_h.median().median()), 0) if ev.caught.any() else None,
               fa_median=round(float(fa.median()), 1), fa_worst=round(float(fa.max()), 1), fa_worst_grid=fa.idxmax(),
               storm_hit_alerted_pct=round(100 * val[~shed].mean()), storm_hit_n=int((~shed).sum()),
               shed_alerted_pct=round(100 * val[shed].mean()),
               storm_quiet_all_alerted_pct=round(100 * every.mean()), storm_quiet_all_n=len(every))
    if chance:
        st_ev = {kg: v for kg, v in raw.items() if kg[1] in {e["grid"] for e in t1}}
        c = benchmark.chance_v3(st_ev, "watch", t1, np.random.default_rng(seed))["caught"]
        out.update(chance_mean=round(float(c.mean()), 2),
                   chance_share=round(float((1 + (c >= out["caught"] - 1e-9).sum()) / (len(c) + 1)), 4))
    return out


def forecast_at(rate: float):
    """The forecast baseline's row at the ladder rate nearest a median false-alarm rate."""
    lad = pd.read_csv(FORECAST_LADDER)
    return lad.iloc[(lad.fa_median - rate).abs().argmin()].to_dict()
