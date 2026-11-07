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

Releases (`evaluate_release`): v2.0 keeps each method's v1.0 operating point, chosen on v1.0's 8 grids
as above, and applies it unchanged to every grid of the release. Each tier of events is verified on
its own (Tier 1 reproduces v1.0 exactly), one false alarm ratio counts every event, and alert burden
(alerts per grid-year, no labels needed) is reported for every grid, including grids with no event.

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
    fn.scores = scores                                  # kept for diagnostics (which signals fired)
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


def rates(alert_fn: Callable, seeds: Iterable[int], grids: Iterable[str]) -> pd.DataFrame:
    """Alerts per grid-year for every setting, seed and grid (no events needed), for operating_point."""
    rows = []
    for k in seeds:
        for g in grids:
            tb, yrs = data.timebase(g), data.scored_years(g)
            warm = tb["in_warmup"].to_numpy()
            for level in LEVELS:
                for thr in THRESHOLDS:
                    for L in PERSISTENCE[level]:
                        n = len(rules.episodes(alert_fn(g, level, thr, L, k), tb["timestamp"], warm))
                        rows.append(dict(seed=k, grid=g, level=level, threshold=thr, L=L, rate=n / yrs))
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
    burden: pd.DataFrame = field(default=None)     # evaluate_release: one row per seed x grid x level


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


def evaluate_release(method: str, alert_fn: Callable, seeds: Iterable[int], version: str = "2.0",
                     chance: bool = True, seed: int = 0, op_from: str = "1.0") -> Result:
    """Score a release at the v1.0 operating point (see the module docstring).

    Summary keys: tier1_* (the v1.0 summary, reproduced), tier2_* (catches, lead and chance for the
    Tier 2 events), all_<level>_false_alarm_ratio (alerts on event grids that verify no event of any
    tier), and burden_* over all grids, quiet grids (no event) and quiet grids without a data-quality
    flag: median, 90th percentile and highest alerts per grid-year, and grids over GRID_CAP x budget.
    op_from="1.0" is the protocol; op_from=version re-derives the operating point over all the release's
    grids (a sensitivity analysis; still no labels).
    """
    seeds = list(seeds)
    if op_from == "1.0":
        sw = sweep(alert_fn, seeds)                     # v1.0 grids and events: the v1.0 operating point
    else:
        sw = rates(alert_fn, seeds, data.grids(op_from))
    op = operating_point(sw)
    events = data.event_list(version)
    sets = {"tier1": [e for e in events if e["tier"] == 1], "tier2": [e for e in events if e["tier"] == 2], "all": events}
    by = {k: _by_grid(v) for k, v in sets.items()}
    rows, burden = {k: [] for k in sets}, []
    for k in seeds:
        for g in data.grids(version):
            tb, yrs = data.timebase(g), data.scored_years(g)
            warm = tb["in_warmup"].to_numpy()
            for lv in LEVELS:
                st = rules.episodes(alert_fn(g, lv, op[lv][0], op[lv][1], k), tb["timestamp"], warm)
                burden.append(dict(seed=k, grid=g, level=lv, rate=len(st) / yrs, n_alerts=len(st), years=yrs))
                for name in sets:
                    if g in by[name]:
                        rows[name] += [dict(seed=k, grid=g, level=lv, threshold=op[lv][0], L=op[lv][1], **r)
                                       for r in _rows(st, g, lv, by[name][g], yrs)]
    setting = {lv: f"threshold {op[lv][0]}, {op[lv][1]} h" for lv in LEVELS}
    s = {"method": method, "seeds": len(seeds), "version": version, "operating_point_from": op_from}
    out = {}
    for name in sets:
        out[name], t = _verify(method, pd.DataFrame(rows[name]), seeds, setting, chance and name != "all", seed,
                               events=sets[name])
        if name == "tier1":
            s.update({f"tier1_{key}": v for key, v in t.items() if key not in ("method", "seeds")})
        elif name == "tier2":
            s.update({f"tier2_{key}": v for key, v in t.items() if "caught" in key or "lead" in key or "chance" in key})
        else:
            s.update({f"all_{lv}_false_alarm_ratio": t[f"{lv}_false_alarm_ratio"] for lv in LEVELS})
    burden = pd.DataFrame(burden)
    s.update(_burden(burden, version))
    rows = pd.concat([out["tier1"], out["tier2"]], ignore_index=True)
    return Result(method, sw, op, rows, s, burden)


def _burden(burden: pd.DataFrame, version: str) -> dict:
    """Alerts per grid-year (mean over seeds) across grids: all, quiet (no event), quiet without a flag."""
    q = data.quality(version)
    has_event = set(data.event_grids(version))
    groups = {"all": list(q.index), "quiet": [g for g in q.index if g not in has_event]}
    groups["quiet_unflagged"] = [g for g in groups["quiet"] if not (q.loc[g, "flat_flag"] or q.loc[g, "shift_flag"])]
    s = {}
    for lv in LEVELS:
        per_grid = burden[burden.level == lv].groupby("grid").rate.mean()
        for name, gs in groups.items():
            x = per_grid.reindex(gs)
            s[f"burden_{name}_{lv}_grids"] = len(gs)
            s[f"burden_{name}_{lv}_median"] = round(float(x.median()), 2)
            s[f"burden_{name}_{lv}_p90"] = round(float(x.quantile(0.9)), 2)
            s[f"burden_{name}_{lv}_max"] = round(float(x.max()), 2)
            s[f"burden_{name}_{lv}_max_grid"] = str(x.idxmax())
            s[f"burden_{name}_{lv}_over_cap"] = int((x > GRID_CAP * BUDGET[lv]).sum())
    return s


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


# ---------------------------------------------------------------- v3.0 (docs/protocol_v3.md)

def from_scores_simple(scores: Dict[int, Dict[str, pd.DataFrame]], signals) -> Callable:
    """Like from_scores, through rules.alerts_simple (the v3.0 alert-rule ablation)."""
    def fn(grid, level, threshold, persistence, seed):
        return rules.alerts_simple(scores[seed][grid], data.timebase(grid)["in_warmup"].to_numpy(),
                                   signals, threshold, persistence)
    fn.scores = scores
    return fn


def starts_at(alert_fn: Callable, seeds, grids, level: str, threshold: float, persistence: int) -> dict:
    """Alert episode start times {(seed, grid): [Timestamp]} at one setting."""
    out = {}
    for k in seeds:
        for g in grids:
            tb = data.timebase(g)
            out[(k, g)] = rules.episodes(alert_fn(g, level, threshold, persistence, k), tb["timestamp"],
                                         tb["in_warmup"].to_numpy())
    return out


def median_rate(st: dict, grids) -> float:
    """Median over grids of alerts per grid-year (mean over seeds)."""
    r = pd.Series({kg: len(v) / data.scored_years(kg[1]) for kg, v in st.items()})
    return float(r.groupby(level=1).mean().reindex(list(grids)).median())


class Calibrator:
    """Label-free operating point (protocol v3.0, item 1): persistence fixed per level, threshold set
    so that the median calibration grid alerts at the budget. A scan of config.V3_SCAN brackets the
    budget, then bisection; rates are cached, so several budgets (the curves) share the scan. Alert
    counts can fall again at very low thresholds (episodes merge), so the bracket is the highest
    scanned threshold at or above the budget. A method that cannot reach the budget is set at its
    highest-rate threshold and flagged."""

    def __init__(self, alert_fn: Callable, seeds, grids, level: str, persistence: int = None):
        from .config import V3_PERSISTENCE
        self.fn, self.seeds, self.grids, self.level = alert_fn, list(seeds), list(grids), level
        self.L = persistence or V3_PERSISTENCE[level]
        self.cache = {}

    def rate(self, thr: float) -> float:
        if thr not in self.cache:
            self.cache[thr] = median_rate(starts_at(self.fn, self.seeds, self.grids, self.level, thr, self.L), self.grids)
        return self.cache[thr]

    def __call__(self, budget: float) -> dict:
        from .config import V3_BISECT, V3_SCAN, V3_TOL
        scan = [(t, self.rate(t)) for t in V3_SCAN]
        above = [t for t, r in scan if r >= budget]
        if not above:
            t, r = max(scan, key=lambda x: x[1])
            return dict(threshold=t, persistence=self.L, calib_rate=r, reached=False)
        lo = max(above)
        hi = min([t for t, _ in scan if t > lo], default=None)
        best = (lo, self.rate(lo))
        if hi is not None:
            for _ in range(V3_BISECT):
                if abs(best[1] - budget) <= V3_TOL * budget:
                    break
                mid = (lo + hi) / 2
                r = self.rate(mid)
                if abs(r - budget) < abs(best[1] - budget):
                    best = (mid, r)
                lo, hi = (mid, hi) if r >= budget else (lo, mid)
            if abs(self.rate(hi) - budget) < abs(best[1] - budget):
                best = (hi, self.rate(hi))
        return dict(threshold=float(best[0]), persistence=self.L, calib_rate=best[1],
                    reached=bool(abs(best[1] - budget) <= 2.5 * V3_TOL * budget))


def untie(scores: Dict[int, Dict[str, pd.DataFrame]], salt: int = 0) -> Dict[int, Dict[str, pd.DataFrame]]:
    """Break exact ties in per-signal scores with a seeded uniform jitter below config.TIE_JITTER, far
    smaller than any real score difference (causal percentiles are rounded to 1e-6), so a threshold can
    always meet the budget (deviation 2026-11-06: HTM's likelihood piles up at exactly 0.999).
    Deterministic: the jitter depends only on the seed, grid, signal and `salt` (0 = the protocol draw;
    other salts measure how much a result depends on the draw)."""
    import zlib
    from .config import TIE_JITTER
    out = {}
    for k, per in scores.items():
        out[k] = {}
        for g, df in per.items():
            cols = {}
            for c in df:
                rng = np.random.default_rng(zlib.crc32((f"{k}/{g}/{c}" + (f"/{salt}" if salt else "")).encode()))
                cols[c] = df[c].to_numpy(float) + rng.uniform(0, TIE_JITTER, len(df))
            out[k][g] = pd.DataFrame(cols, index=df.index)
    return out


def verify_v3(st: dict, level: str, events, near=(), shift_h: float = 0, onset_field: str = None):
    """Per-event and per-grid verification of alert starts {(seed, grid): [Timestamp]}.

    Event rows (one per seed x event): caught (watch: an alert before onset; warning: an alert in the
    window), caught_pre (an alert before onset), lead_h (from the first alert before onset).
    Grid rows (one per seed x grid): n_alerts, n_verified (verify any event of the grid), n_masked
    (verify a near-miss of the grid and no event), years. shift_h delays every alert (latency);
    onset_field replaces each event's onset by the earlier of it and that field, when present."""
    by_ev, by_nm = _by_grid(events), {}
    for n in near:
        by_nm.setdefault(n["grid"], []).append(n)
    ev_rows, grid_rows = [], []
    for (k, g), starts in st.items():
        s = [t + shift_h * H for t in starts]
        ver, ver_t1 = set(), set()
        for e in by_ev.get(g, []):
            on = e["onset"]
            if onset_field and e.get(onset_field):
                on = min(on, pd.Timestamp(e[onset_field]))
            v = verified(s, on, level)
            ver |= set(v)
            pre = [t for t in v if t < on]
            if e["tier"] == 1:
                ver_t1 |= set(pre)
            ev_rows.append(dict(seed=k, grid=g, event=e["id"], tier=e["tier"], split=e.get("split"),
                                storm=e.get("storm", e["id"]), caught=bool(pre) if level == "watch" else bool(v),
                                caught_pre=bool(pre), lead_h=(on - min(pre)) / H if pre else np.nan))
        nm = {t for n in by_nm.get(g, []) for t in verified(s, n["time"], level)} - ver
        grid_rows.append(dict(seed=k, grid=g, n_alerts=len(s), n_verified=len(ver), n_verified_t1=len(ver_t1), n_masked=len(nm),
                              years=data.scored_years(g)))
    return pd.DataFrame(ev_rows), pd.DataFrame(grid_rows)


def chance_v3(st: dict, level: str, events, rng, mode: str = "season", shifts: int = None) -> dict:
    """Chance baseline: the method's own alerts on each grid, shifted together, `shifts` times.
    mode "season" (v3.0): by a whole number of years (config.SEASON_SHIFT_YEARS) plus a uniform offset
    of up to SEASON_SHIFT_DAYS, wrapped modulo 6 years, so season, rate and clustering are kept.
    mode "any" (v2.0): to a uniformly random time in the scored period.
    Returns per-shift catches (mean over seeds) for `caught` and `caught_pre`, and pre-onset leads."""
    from .config import SEASON_SHIFT_DAYS, SEASON_SHIFT_YEARS
    shifts = shifts or CHANCE_SHIFTS
    Y = 8760.0
    by_ev = _by_grid(events)
    seeds = sorted({k for k, _ in st})
    tot, tot_pre, leads = np.zeros(shifts), np.zeros(shifts), []
    before, after = WINDOW[level]
    # One shift per draw, shared by every grid: events of one storm on several grids stay together, so
    # the null keeps their dependence (deviation 2026-11-07).
    yrs = Y * rng.integers(SEASON_SHIFT_YEARS[0], SEASON_SHIFT_YEARS[1] + 1, shifts) \
        + rng.uniform(-24 * SEASON_SHIFT_DAYS, 24 * SEASON_SHIFT_DAYS, shifts)
    frac = rng.uniform(0, 1, shifts)
    for g, evs in by_ev.items():
        tb = data.timebase(g)
        t0 = tb.loc[tb.in_warmup == 0, "timestamp"].iloc[0]
        T = (tb["timestamp"].iloc[-1] - t0) / H
        if mode == "season":
            off, period = yrs, 6 * Y
        else:
            off, period = frac * T, T
        for k in seeds:
            s = np.array([(t - t0) / H for t in st.get((k, g), [])])
            if not len(s):
                continue
            if mode == "season":
                s = s[s < period]                      # exactly 6 whole years of alerts (no year counted twice)
            x = (s[None, :] + off[:, None]) % period
            for e in evs:
                d = (e["onset"] - t0) / H - x                  # hours before onset
                pre = (d > 0) & (d <= before)
                win = pre | ((d <= 0) & (d >= -after)) if after else pre
                c_pre = pre.any(axis=1)
                tot_pre += c_pre / len(seeds)
                tot += (c_pre if level == "watch" else win.any(axis=1)) / len(seeds)
                ld = np.where(pre, d, -np.inf).max(axis=1)
                leads.extend(ld[np.isfinite(ld)].tolist())
    return dict(caught=tot, caught_pre=tot_pre, leads=np.array(leads))


def clopper_pearson(x: int, n: int, a: float = 0.05) -> tuple:
    from scipy.stats import beta
    lo = 0.0 if x == 0 else float(beta.ppf(a / 2, x, n - x + 1))
    hi = 1.0 if x == n else float(beta.ppf(1 - a / 2, x + 1, n - x))
    return lo, hi
