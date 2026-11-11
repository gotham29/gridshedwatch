#!/usr/bin/env python3
"""The scoring protocol (docs/protocol_v3.md): reference methods, results/v3.0/, and new submissions.

Step 1, per method (resumable; methods can run in parallel with --jobs):
    python scripts/score_v3.py --method gbm lstm ...      (default: every method)
  writes results/v3.0/methods/<method>/ with
    op.csv        operating point per level and budget (threshold, persistence, calibration-grid rate)
    alerts.csv    the alerts at the operating point, in the alerts-track format
    events.csv    per seed x event x level at the protocol budget
    grids.csv     per seed x grid x level: alerts, verified, masked (near-miss), grid group
    curves.csv    Tier 1 catches per level and budget
    chance.csv    per level and null (season, any): observed, chance, p, chance lead
    sens.csv      Tier 1 catches with delayed data (latency) and with OE-417 onsets
    ablation.csv  alert rules (any signal, forecast error only) and the likelihood transform
Step 2, all methods together:
    python scripts/score_v3.py --stats
  writes results/v3.0/summary.csv, events.csv, stats_friedman.csv, loso.csv, lead_vs_notice.csv
  (every scored method folder; tests and Holm over the ranked entries only).
"""
import argparse
from functools import lru_cache
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import alerts, benchmark, data, submission
from .baselines import ENTRIES, HTM_V2, LABEL, METHODS, likelihood, oprule, scores
from .config import BUDGET, GRID_CAP, LATENCY_H, PACKAGE, ROOT, SIGNALS, V3_CURVE, V3_TOL, WINDOW

V = "2.0"                                     # the data release scored (48 grids, 10 events)
LEVELS = benchmark.LEVELS
OUT = ROOT / "results" / "v3.0"
VARIANTS = {"any_signal": list(SIGNALS), "forecast_error_only": ["forecast_error"]}


REFERENCE = PACKAGE / "reference_v3.csv"      # summary rows of the 11 reference methods (shipped with the package)
SALT = 0                                       # tie-break draw (--salt); results go to methods/<method>_salt<k>


def load(m: str, scores_root: Path, htm: Path):
    """(alert function, seeds, per-signal scores or None). Reference scores where they exist on disk,
    computed here otherwise (the deterministic methods)."""
    if m == "oprule":
        return oprule.alerts, [0], None
    d = htm if m == "htm" else scores_root / m
    if d.exists():                 # an extra folder (e.g. an HTM setup) may hold only some grids
        have = sorted({f.name.split(".")[0] for f in (d / "s0").iterdir()})
        sc = submission.load(d, V, grids=[g for g in data.grids(V) if g in have])
    else:
        sc = {k: {g: scores(m, g, k) for g in data.grids(V)} for k in METHODS[m][2]}
    sc = benchmark.untie(sc, SALT)
    return benchmark.from_scores(sc), sorted(sc), sc


def tier1(ev: pd.DataFrame) -> pd.DataFrame:
    return ev[ev.tier == 1]


def caught(ev: pd.DataFrame, col: str = "caught") -> float:
    """Tier 1 events caught, mean over seeds."""
    return float(tier1(ev).groupby("seed")[col].sum().mean())


def score_method(m: str, scores_root: Path, htm: Path, ablations: bool = True, only: list = None, redo: bool = False):
    """Protocol outputs, then ablations. only: rerun just these ablation variants, merged into ablation.csv.
    redo: rescore the protocol outputs even if present (ablation.csv is kept unless ablations are run)."""
    out = OUT / "methods" / (m + (f"_salt{SALT}" if SALT else ""))
    if not redo and not only and ((out / "ablation.csv").exists() or ((out / "sens.csv").exists() and not ablations)):
        print(m, "done already", flush=True)
        return
    out.mkdir(parents=True, exist_ok=True)
    fn, seeds, sc = load(m, scores_root, htm)
    if only:
        return ablate(m, fn, seeds, sc, out, only)
    events, near = data.event_list(V), data.near_misses()
    t1 = [e for e in events if e["tier"] == 1]
    calib, evalq = data.calibration_split(V)
    evg = data.event_grids(V)
    group = {**{g: "event" for g in evg}, **{g: "calibration" for g in calib}, **{g: "evaluation" for g in evalq}}
    have = set(sc[seeds[0]]) if sc is not None else set(group)
    missing = [g for g in calib if g not in have]
    if missing:
        raise SystemExit(f"{m}: no scores for calibration grids {missing}")
    group = {g: v for g, v in group.items() if g in have}           # grids without scores are left out
    evg, evalq = [g for g in evg if g in have], [g for g in evalq if g in have]
    rng = np.random.default_rng(0)
    ops, evs, grs, curves, chance, sens, rows = [], [], [], [], [], [], []
    for lv in LEVELS:
        cal = benchmark.Calibrator(fn, seeds, calib, lv)
        op = cal(BUDGET[lv])
        ops.append(dict(level=lv, budget=BUDGET[lv], **op))
        st = benchmark.starts_at(fn, seeds, list(group), lv, op["threshold"], op["persistence"])
        ev, gr, ch, sn = _from_starts(lv, st, events, near, t1, evg, group, rng)
        evs.append(ev)
        grs.append(gr)
        chance += ch
        sens += sn
        rows += [dict(grid=g, level=lv, start_utc=pd.Timestamp(t).strftime("%Y-%m-%d %H:%M"), seed=k)
                 for (k, g), v in st.items() for t in v]
        st_ev = {kg: v for kg, v in st.items() if kg[1] in evg}
        for b in V3_CURVE[lv]:
            o = op if b == BUDGET[lv] else cal(b)
            if b != BUDGET[lv]:
                ops.append(dict(level=lv, budget=b, **o))
            sb = st_ev if b == BUDGET[lv] else benchmark.starts_at(fn, seeds, evg, lv, o["threshold"], o["persistence"])
            e_b, _ = benchmark.verify_v3(sb, lv, t1)
            curves.append(dict(level=lv, budget=b, calib_rate=o["calib_rate"], caught=caught(e_b),
                               caught_pre=caught(e_b, "caught_pre")))
        o48 = benchmark.Calibrator(fn, seeds, [g for g in data.grids(V) if g in group], lv)(BUDGET[lv])
        e_48, _ = benchmark.verify_v3(benchmark.starts_at(fn, seeds, evg, lv, o48["threshold"], o48["persistence"]), lv, t1)
        sens.append(dict(level=lv, variant="operating point set on all grids (no labels)", caught=caught(e_48),
                         caught_pre=caught(e_48, "caught_pre")))
    pd.DataFrame(ops).to_csv(out / "op.csv", index=False)
    alerts.write(pd.DataFrame(rows, columns=["grid", "level", "start_utc", "seed"]), out / "alerts.csv")
    pd.concat(evs).to_csv(out / "events.csv", index=False)
    pd.concat(grs).to_csv(out / "grids.csv", index=False)
    pd.DataFrame(curves).to_csv(out / "curves.csv", index=False)
    pd.DataFrame(chance).to_csv(out / "chance.csv", index=False)
    pd.DataFrame(sens).to_csv(out / "sens.csv", index=False)
    print(m, "protocol done", flush=True)
    if ablations and sc is not None:
        ablate(m, fn, seeds, sc, out, list(VARIANTS) + ["likelihood_transform"])


@lru_cache(maxsize=None)
def _demand_pct(grid: str) -> pd.Series:
    """Causal percentile of a grid's seasonal demand anomaly, on its timebase."""
    from .baselines import to_p
    tb = data.timebase(grid)
    return pd.Series(to_p(data.signals(grid)["demand_anom"].to_numpy(float)), index=tb["timestamp"].to_numpy())


def _exposed(grid: str, t0, before: int, q: float = 0.99) -> bool:
    """Was the grid's demand anomaly in its top 1% at some hour in the window before t0?"""
    p = _demand_pct(grid)
    return bool((p.loc[t0 - pd.Timedelta(hours=before):t0] >= q).any())


def _from_starts(lv, st, events, near, t1, evg, group, rng):
    """Everything scored from alert starts {(seed, grid): [Timestamp]} at one level: per-event and per-grid
    rows, the chance baselines, and the latency and onset sensitivities. Shared by both tracks."""
    ev, gr = benchmark.verify_v3(st, lv, events, near)
    st_ev = {kg: v for kg, v in st.items() if kg[1] in evg}
    chance, sens = [], []
    for col in ("caught", "caught_pre"):
        if lv == "watch" and col == "caught_pre":
            continue
        obs = caught(ev, col)
        for mode in ("season", "any"):
            null = benchmark.chance_v3(st_ev, lv, t1, rng, mode)
            chance.append(dict(level=lv, measure=col, null=mode, observed=obs, chance=float(null[col].mean()),
                               p=float((1 + (null[col] >= obs - 1e-9).sum()) / (len(null[col]) + 1)),
                               chance_median_lead_h=float(np.median(null["leads"])) if len(null["leads"]) else np.nan))
    # Further chance tests (own random stream, so the headline draws above are unchanged): realistic
    # delay, held-out events, each storm left out, each seed alone, and any time at least 30 days away.
    rng2 = np.random.default_rng(1)
    ids = lambda evs: {e["id"] for e in evs}

    def test(name, st_x, evs, ev_x, col):
        null = benchmark.chance_v3(st_x, lv, evs, rng2, "any30" if name == "any30" else "season")
        obs = caught(ev_x[ev_x.event.isin(ids(evs))], col)
        chance.append(dict(level=lv, measure=col, null=name, observed=obs, chance=float(null[col].mean()),
                           p=float((1 + (null[col] >= obs - 1e-9).sum()) / (len(null[col]) + 1)),
                           chance_median_lead_h=np.nan))
    e24, _ = benchmark.verify_v3(st_ev, lv, t1, shift_h=24)
    st24 = {kg: [t + pd.Timedelta(hours=24) for t in v] for kg, v in st_ev.items()}
    for col in (("caught",) if lv == "watch" else ("caught_pre", "caught")):
        test("any30", st_ev, t1, ev, col)
        test("lat24", st24, t1, e24.assign(tier=1), col)
        test("heldout", st_ev, [e for e in t1 if e["split"] == "held-out"], ev, col)
        for storm in sorted({e["storm"] for e in t1}):
            test("without_" + storm.split()[0].lower(), st_ev, [e for e in t1 if e["storm"] != storm], ev, col)
        for k in sorted({k for k, _ in st_ev}):
            test(f"seed{k}", {kg: v for kg, v in st_ev.items() if kg[0] == k}, t1, ev[ev.seed == k], col)
    for L in LATENCY_H:
        e_l, _ = benchmark.verify_v3(st_ev, lv, t1, shift_h=L)
        sens.append(dict(level=lv, variant=f"latency {L} h", caught=caught(e_l), caught_pre=caught(e_l, "caught_pre")))
    e_o, _ = benchmark.verify_v3(st_ev, lv, t1, onset_field="oe417_start_utc")
    sens.append(dict(level=lv, variant="onset: earlier of declaration and OE-417", caught=caught(e_o),
                     caught_pre=caught(e_o, "caught_pre")))
    # Storm-window negative control: share of evaluation quiet grids (no emergency) with an alert starting in
    # the 168 h before each storm's first load-shed onset, i.e. that would have "caught" an event that never
    # happened. A method that only detects unusual weather alerts on quiet grids in the storm as well.
    evalq = [g for g, k in group.items() if k == "evaluation"]
    if not evalq:                                  # a setup run on no evaluation quiet grid (htm_online)
        return ev.assign(level=lv), gr.assign(level=lv, group=gr.grid.map(group)), chance, sens
    before = WINDOW["watch"][0]
    for storm in sorted({e["storm"] for e in t1}):
        t0 = min(e["onset"] for e in t1 if e["storm"] == storm)
        share = np.mean([np.mean([any(0 < (t0 - t) / pd.Timedelta(hours=1) <= before for t in st.get((k, g), []))
                                  for g in evalq]) for k in sorted({k for k, _ in st})])
        sens.append(dict(level=lv, variant=f"storm control: {storm}", caught=float(share), caught_pre=float(share)))
    # exposure-matched: only quiet grids whose own demand anomaly reached its top 1% in that window
    for storm in sorted({e["storm"] for e in t1}):
        t0 = min(e["onset"] for e in t1 if e["storm"] == storm)
        exp_ = [g for g in evalq if _exposed(g, t0, before)]
        share = np.mean([np.mean([any(0 < (t0 - t) / pd.Timedelta(hours=1) <= before for t in st.get((k, g), []))
                                  for g in exp_]) for k in sorted({k for k, _ in st})]) if exp_ else np.nan
        sens.append(dict(level=lv, variant=f"storm control, exposed grids ({len(exp_)}): {storm}", caught=float(share),
                         caught_pre=float(share)))
    # the same share for a typical week: pseudo-onsets every 7 days through the scored period
    tb = data.timebase(evalq[0])
    ts = pd.date_range(tb.loc[tb.in_warmup == 0, "timestamp"].iloc[0] + pd.Timedelta(hours=before),
                       tb["timestamp"].iloc[-1], freq="7D")
    seeds_ = sorted({k for k, _ in st})
    hit = [[np.searchsorted(np.sort(np.array(st.get((k, g), []), dtype="datetime64[ns]")), ts.values) -
            np.searchsorted(np.sort(np.array(st.get((k, g), []), dtype="datetime64[ns]")),
                            (ts - pd.Timedelta(hours=before)).values, side="right") > 0 for g in evalq] for k in seeds_]
    sens.append(dict(level=lv, variant="storm control: typical week", caught=float(np.mean(hit)), caught_pre=float(np.mean(hit))))
    return ev.assign(level=lv), gr.assign(level=lv, group=gr.grid.map(group)), chance, sens


def ablate(m, fn, seeds, sc, out, names):
    if sc is None:
        return
    events, near = data.event_list(V), data.near_misses()
    calib, evalq = data.calibration_split(V)
    have = set(sc[seeds[0]])
    evg, evalq = [g for g in data.event_grids(V) if g in have], [g for g in evalq if g in have]
    variants = {n: benchmark.from_scores_simple(sc, sig) for n, sig in VARIANTS.items() if n in names}
    if "likelihood_transform" in names and m != "htm":       # HTM's entry already is the likelihood
        X = {g: data.signals(g) for g in sc[seeds[0]]}
        lk = benchmark.untie({k: {g: pd.DataFrame({c: likelihood(df[c].to_numpy(), X[g][c[2:]].to_numpy(float)) for c in df})
                                  for g, df in v.items()} for k, v in sc.items()})
        variants["likelihood_transform"] = benchmark.from_scores(lk)
    if not variants:
        return
    rows = []
    for name, f in variants.items():
        for lv in LEVELS:
            o = benchmark.Calibrator(f, seeds, calib, lv)(BUDGET[lv])
            st = benchmark.starts_at(f, seeds, evg + list(evalq), lv, o["threshold"], o["persistence"])
            ev, gr = benchmark.verify_v3(st, lv, events, near)
            rows.append(dict(variant=name, level=lv, threshold=o["threshold"], caught=caught(ev),
                             caught_pre=caught(ev, "caught_pre"), **far(gr[gr.grid.isin(evg)]),
                             **(burden(gr[gr.grid.isin(evalq)], lv) if evalq else {})))
    new = pd.DataFrame(rows)
    f = out / "ablation.csv"
    if f.exists():
        old = pd.read_csv(f)
        new = pd.concat([old[~old.variant.isin(new.variant.unique())], new], ignore_index=True)
    new.to_csv(f, index=False)
    print(m, "ablations done:", ", ".join(variants), flush=True)


def far(gr: pd.DataFrame) -> dict:
    """False alarm ratio on the Tier 1 grids (mean over seeds): false / (false + alerts that start before a
    Tier 1 onset in its window). An alert is false if it verifies no event of any tier; alerts that verify
    only a Tier 2 event, or a load shed after onset, are left out; masked: near-miss alerts left out too."""
    gr = gr[gr.grid.isin({e["grid"] for e in data.event_list(V) if e["tier"] == 1})]
    s = gr.groupby("seed")[["n_alerts", "n_verified", "n_verified_t1", "n_masked"]].sum()
    false = s.n_alerts - s.n_verified
    return dict(alerts=float(s.n_alerts.mean()), verified_t1=float(s.n_verified_t1.mean()), masked=float(s.n_masked.mean()),
                far=float((false / (false + s.n_verified_t1)).mean()),
                far_masked=float(((false - s.n_masked) / (false - s.n_masked + s.n_verified_t1)).mean()))


def burden(gr: pd.DataFrame, lv: str) -> dict:
    """Alerts per grid-year (mean over seeds) on a group of quiet grids, with and without masks."""
    r = gr.assign(rate=gr.n_alerts / gr.years, rate_m=(gr.n_alerts - gr.n_masked) / gr.years).groupby("grid")[["rate", "rate_m"]].mean()
    cap = GRID_CAP * BUDGET[lv]
    if r.empty:                                                  # a setup scored without evaluation-half grids
        return {}
    return dict(burden_median=r.rate.median(), burden_p90=r.rate.quantile(0.9), burden_max=r.rate.max(),
                burden_max_grid=r.rate.idxmax(), over_cap=int((r.rate > cap).sum()),
                burden_p90_masked=r.rate_m.quantile(0.9), burden_max_masked=r.rate_m.max(),
                over_cap_masked=int((r.rate_m > cap).sum()))


# ------------------------------------------------------------------------------------- step 2

def label(m: str) -> str:
    return HTM_V2 if m == "htm" else LABEL.get(m, m)


def notice_leads() -> dict:
    """Hours before onset of each Tier 1 event's first public operator notice, and of its first operator
    notice of any kind (conservative operations, EEA 1 or 2, advisories), in the week before onset
    (None if none): {grid: (public, any)}."""
    out = {}
    for g, e in data.operator_notices().items():
        on = data.onset(g)
        first = lambda ts: (lambda pre: (on - min(pre)) / benchmark.H if pre else None)(
            [t for t in ts if on - WINDOW["watch"][0] * benchmark.H <= t < on])
        out[g] = (first([pd.Timestamp(n["utc"]) for n in e["notices"] if n.get("public")]),
                  first([pd.Timestamp(n["utc"]) for n in e["notices"]]))
    return out


def stats(primary: list):
    from scipy.stats import friedmanchisquare, rankdata, studentized_range
    have = sorted(p.name for p in (OUT / "methods").iterdir() if (p / "sens.csv").exists())
    ms = [m for m in primary if m in have] + [m for m in have if m not in primary]
    rd = lambda m, f: pd.read_csv(OUT / "methods" / m / f)
    calib, evalq = data.calibration_split(V)
    pd.DataFrame({"grid": calib + evalq, "half": ["calibration"] * len(calib) + ["evaluation"] * len(evalq)}) \
        .to_csv(OUT / "calibration_grids.csv", index=False)
    summary, per_event, per_ev_mat = [], [], {}
    nl = notice_leads()
    lead_rows = []
    for m in ms:
        ev, gr, op, ch = rd(m, "events.csv"), rd(m, "grids.csv"), rd(m, "op.csv"), rd(m, "chance.csv")
        s = {"method": label(m), "code": m, "seeds": ev.seed.nunique()}
        for lv in LEVELS:
            e = ev[ev.level == lv]
            o = op[(op.level == lv) & (op.budget == BUDGET[lv])].iloc[0]
            t = e[e.tier == 1]
            s[f"{lv}_threshold"], s[f"{lv}_persistence"] = round(o.threshold, 5), (int(o.persistence) if o.persistence == o.persistence else np.nan)
            s[f"{lv}_calib_rate"], s[f"{lv}_reached"] = round(o.calib_rate, 2), bool(o.reached)
            t1g = gr[(gr.level == lv) & gr.grid.isin(set(t.grid))]
            s[f"{lv}_tier1_grid_rate"] = round(float((t1g.n_alerts / t1g.years).groupby(t1g.grid).mean().median()), 2)
            for col in (["caught"] if lv == "watch" else ["caught_pre", "caught"]):
                c = t.groupby("seed")[col].sum()
                key = f"{lv}_{'pre' if col == 'caught_pre' else 'any'}" if lv == "warning" else lv
                n = int(round(c.mean()))
                s[f"{key}_caught"] = round(float(c.mean()), 1)
                s[f"{key}_ci"] = "%.2f-%.2f" % benchmark.clopper_pearson(n, 8)      # for the seed-mean count, rounded
                s[f"{key}_seed_range"] = f"{int(c.min())}-{int(c.max())}"
                s[f"{key}_held_out"] = round(float(t[t.split == "held-out"].groupby("seed")[col].sum().mean()), 1)
                cs = ch[(ch.level == lv) & (ch.measure == col) & ch.null.str.startswith("seed")]
                if len(cs):
                    s[f"{key}_p_seed_median"], s[f"{key}_p_seed_max"] = float(cs.p.median()), float(cs.p.max())
                for mode in [x for x in ch.null.unique() if not x.startswith("seed")]:
                    r = ch[(ch.level == lv) & (ch.measure == col) & (ch.null == mode)]
                    if len(r):
                        s[f"{key}_chance_{mode}"], s[f"{key}_p_{mode}"] = round(r.chance.iloc[0], 2), r.p.iloc[0]
                        s[f"{key}_chance_lead_h"] = round(r.chance_median_lead_h.iloc[0], 0) if mode == "season" else s.get(f"{key}_chance_lead_h")
                s[f"{key}_above_chance"] = round(s[f"{key}_caught"] - s.get(f"{key}_chance_season", np.nan), 2)
                per_ev_mat[(m, key)] = t.groupby("event")[col].mean()
            pre = t[t.caught_pre]
            leads = pre.groupby("event").lead_h.median()
            s[f"{lv}_median_lead_h"], s[f"{lv}_lead_events_any_seed"] = (round(float(leads.median()), 0) if len(leads) else np.nan), len(leads)
            if lv == "watch":
                for g, ln in nl.items():
                    lead_rows.append(dict(method=label(m), event=g, method_lead_h=leads.get(g, np.nan), notice_lead_h=ln[0],
                                          any_notice_lead_h=ln[1]))
            f = far(gr[(gr.level == lv) & (gr.group == "event")])
            s.update({f"{lv}_{k}": round(v, 3) for k, v in f.items()})
            b = burden(gr[(gr.level == lv) & (gr.group == "evaluation")], lv)
            s.update({f"{lv}_{k}": (round(v, 2) if isinstance(v, float) else v) for k, v in b.items()})
            t2 = e[e.tier == 2].groupby("event")[["caught", "caught_pre"]].mean()
            for eid, r in t2.iterrows():
                s[f"{lv}_tier2_{eid}"] = round(float(r.caught_pre if lv == "warning" else r.caught), 1)
            per_event.append(e.groupby(["event", "tier", "split", "storm"]).agg(
                caught=("caught", "mean"), caught_pre=("caught_pre", "mean"), lead_h=("lead_h", "median"))
                .reset_index().assign(method=label(m), level=lv))
        summary.append(s)
    pd.DataFrame(summary).to_csv(OUT / "summary.csv", index=False)
    pd.concat(per_event).to_csv(OUT / "events.csv", index=False)
    pd.DataFrame(lead_rows).to_csv(OUT / "lead_vs_notice.csv", index=False)
    # Holm-corrected chance p across methods, per measure and null
    sm = pd.DataFrame(summary)
    ent = sm.index[sm.code.isin(ENTRIES)]                       # Holm over the ranked entries only
    for col in [c for c in sm if "_p_" in c]:
        p = sm.loc[ent, col].to_numpy(float)
        order = np.argsort(p)
        adj = np.maximum.accumulate(np.minimum(1, (len(p) - np.arange(len(p))) * p[order]))
        sm.loc[ent[order], col + "_holm"] = adj
    sm.to_csv(OUT / "summary.csv", index=False)
    if OUT == ROOT / "results" / "v3.0":           # the reference rows new submissions are shown against
        sm[sm.code.isin(list(ENTRIES))].to_csv(REFERENCE, index=False)
    # Friedman and Nemenyi over the ranked entries, and leave one storm out. No pairwise tests: with 8 events
    # and 10 Holm-corrected comparisons, none could reach 0.05 even at 8 of 8 (deviation 2026-11-06).
    storms = {e["id"]: e.get("storm") for e in data.event_list(V) if e["tier"] == 1}
    hp = lambda c: sm.set_index("code")[c] if c in sm else pd.Series(dtype=float)
    passed = [c for c in sm.code if c in ENTRIES and hp("watch_p_season_holm").get(c, 1) < 0.05
              and hp("warning_pre_p_season_holm").get(c, 1) < 0.05]
    fr, loso = [], []
    for key in ("watch", "warning_pre", "warning_any"):
        X = pd.DataFrame({m: per_ev_mat[(m, key)] for m in ms if (m, key) in per_ev_mat and m in ENTRIES})  # entries only
        if X.shape[1] < 3:
            continue
        R = np.array([rankdata(-row) for row in X.to_numpy()])
        k, n = X.shape[1], X.shape[0]
        cd = lambda k: studentized_range.ppf(0.95, k, np.inf) / np.sqrt(2) * np.sqrt(k * (k + 1) / (6 * n))
        Xn = X.drop(columns="random", errors="ignore")           # the tests reported: without random scores
        Rn = np.array([rankdata(-row) for row in Xn.to_numpy()]).mean(0)
        top4 = [m for m in Xn.columns if m in passed] or list(Xn.sum().sort_values(ascending=False).index[:4])
        fr.append(dict(measure=key, events=n, methods=k, friedman_p=friedmanchisquare(*X.to_numpy().T).pvalue,
                       friedman_p_without_random=friedmanchisquare(*Xn.to_numpy().T).pvalue,
                       nemenyi_cd=cd(k), nemenyi_cd_without_random=cd(Xn.shape[1]),
                       max_rank_gap_without_random=Rn.max() - Rn.min(),
                       friedman_p_top4=friedmanchisquare(*Xn[top4].to_numpy().T).pvalue,
                       top4=" ".join(top4), **{f"rank_{label(m)}": r for m, r in zip(X.columns, R.mean(0))}))
        for st in sorted(set(storms.values())):
            keep = [e for e in X.index if storms.get(e) != st]
            loso.append(dict(measure=key, without=st, events=len(keep), **{label(m): round(float(X.loc[keep, m].sum()), 1) for m in X.columns}))
    pd.DataFrame(fr).to_csv(OUT / "stats_friedman.csv", index=False)
    selectivity([m for m in ms if (OUT / "methods" / m / "alerts.csv").exists()])
    pd.DataFrame(loso).to_csv(OUT / "loso.csv", index=False)
    print("wrote", OUT)



# ------------------------------------------------------------------------------ new submissions

def _score_alerts(starts: dict, mdir: Path):
    """Alerts track: submitted watch and warning starts {seed: {grid: {level: [Timestamp]}}}, scored by the
    same event rules. No threshold is set; the median calibration grid must alert at most the budget (+5%),
    as the scores track's operating point does. Grids left out of the file count as raising no alerts."""
    events, near = data.event_list(V), data.near_misses()
    t1 = [e for e in events if e["tier"] == 1]
    calib, evalq = data.calibration_split(V)
    evg = data.event_grids(V)
    group = {**{g: "event" for g in evg}, **{g: "calibration" for g in calib}, **{g: "evaluation" for g in evalq}}
    rng = np.random.default_rng(0)
    ops, evs, grs, chance, sens = [], [], [], [], []
    for lv in LEVELS:
        st = {(k, g): sorted(starts[k].get(g, {}).get(lv, [])) for k in sorted(starts) for g in group}
        r = benchmark.median_rate({kg: v for kg, v in st.items() if kg[1] in calib}, calib)
        ops.append(dict(level=lv, budget=BUDGET[lv], threshold=np.nan, persistence=np.nan, calib_rate=r,
                        reached=bool(r <= BUDGET[lv] * (1 + 2.5 * V3_TOL))))
        ev, gr, ch, sn = _from_starts(lv, st, events, near, t1, evg, group, rng)
        evs.append(ev)
        grs.append(gr)
        chance += ch
        sens += sn
    mdir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ops).to_csv(mdir / "op.csv", index=False)
    pd.concat(evs).to_csv(mdir / "events.csv", index=False)
    pd.concat(grs).to_csv(mdir / "grids.csv", index=False)
    pd.DataFrame(chance).to_csv(mdir / "chance.csv", index=False)
    pd.DataFrame(sens).to_csv(mdir / "sens.csv", index=False)


def selectivity(methods: list):
    """Selectivity in the winter storms: does a method watch the grids that shed load more than quiet grids
    equally exposed to the same storm (demand anomaly in its top 1% in the week)? Per grid, the share of
    seeds with a watch starting in the 168 h before onset (shed grids: their own onset; quiet grids: the
    storm's first onset). Test: exact permutation of the shed labels within each storm; statistic = mean
    over shed grids minus mean over exposed quiet grids. Holm over the ranked entries."""
    import itertools
    t1 = [e for e in data.event_list(V) if e["tier"] == 1]
    _, evalq = data.calibration_split(V)
    before = WINDOW["watch"][0]
    units = []                                    # (storm, grid, shed, onset)
    for storm in ("Uri", "Elliott"):
        es = [e for e in t1 if e["storm"] == storm]
        t0 = min(e["onset"] for e in es)
        units += [(storm, e["grid"], True, e["onset"]) for e in es]
        units += [(storm, g, False, t0) for g in evalq if _exposed(g, t0, before)]
    rows = []
    for m in methods:
        a = pd.read_csv(OUT / "methods" / m / "alerts.csv", parse_dates=["start_utc"])
        a = a[a.level == "watch"]
        seeds = sorted(a.seed.unique()) or [0]
        val = np.array([np.mean([((a.seed == k) & (a.grid == g) & (a.start_utc <= t) &
                                  (a.start_utc > t - pd.Timedelta(hours=before))).any() for k in seeds])
                        for _, g, _, t in units])
        shed = np.array([u[2] for u in units])
        obs = val[shed].mean() - val[~shed].mean()
        # exact null: every relabelling within storms with the same number of shed grids per storm
        idx = {st: [i for i, u in enumerate(units) if u[0] == st] for st in ("Uri", "Elliott")}
        k = {st: int(shed[idx[st]].sum()) for st in idx}
        null = []
        for cu in itertools.combinations(idx["Uri"], k["Uri"]):
            for ce in itertools.combinations(idx["Elliott"], k["Elliott"]):
                lab = np.zeros(len(units), bool)
                lab[list(cu) + list(ce)] = True
                null.append(val[lab].mean() - val[~lab].mean())
        null = np.array(null)
        rows.append(dict(code=m, method=label(m), shed_pct=100 * val[shed].mean(), exposed_quiet_pct=100 * val[~shed].mean(),
                         n_shed=int(shed.sum()), n_quiet=int((~shed).sum()), p=float((null >= obs - 1e-12).mean())))
    t = pd.DataFrame(rows)
    if t.empty:                                   # no method with alerts in this results folder
        return t
    ent = t.index[t.code.isin(ENTRIES)]
    p = t.loc[ent, "p"].to_numpy(float)
    order = np.argsort(p)
    t.loc[ent[order], "p_holm"] = np.maximum.accumulate(np.minimum(1, (len(p) - np.arange(len(p))) * p[order]))
    t.to_csv(OUT / "selectivity.csv", index=False)
    return t


def score_new(name: str, folder=None, alerts_file=None, out=None) -> pd.DataFrame:
    """Score a new method under this protocol, next to the reference methods.

    Scores track: `folder` in the submission layout (gridshedwatch.submission); its operating point is set
    exactly as the reference methods' are. Alerts track: `alerts_file`, watch and warning start times
    (gridshedwatch.alerts). Results go to `out`/methods/<name>/; returns the comparison table, the new
    method last. Its chance p-value is not Holm-corrected (the reference methods' are, over themselves)."""
    import os
    import tempfile
    global OUT
    out, keep = Path(out or "gsw_results").resolve(), OUT
    mdir = out / "methods" / name
    OUT = out
    try:
        if folder is not None:
            folder = Path(folder).resolve()
            if folder.name != name:
                (out / "scores").mkdir(parents=True, exist_ok=True)
                link = out / "scores" / name
                if not link.exists():
                    os.symlink(folder, link)
                folder = link
            score_method(name, folder.parent, None, ablations=False)
        else:
            _score_alerts(alerts.load(alerts_file, V), mdir)
        tmp = Path(tempfile.mkdtemp(prefix="gsw_"))         # this method's summary row, on its own
        (tmp / "methods").mkdir()
        os.symlink(mdir, tmp / "methods" / name)
        OUT = tmp
        stats([name])
        s = pd.concat([pd.read_csv(REFERENCE), pd.read_csv(tmp / "summary.csv")], ignore_index=True)
    finally:
        OUT = keep
    t = comparison(s, name)
    t.to_csv(out / f"{name}_comparison.csv", index=False)
    return t


def comparison(s: pd.DataFrame = None, name: str = None) -> pd.DataFrame:
    """The comparison table: the reference methods by watches caught, then `name` (if given) last."""
    s = pd.read_csv(REFERENCE) if s is None else s
    s = s[s.code.isin(list(ENTRIES) + [name])].copy()
    s["p"] = s.watch_p_season_holm.fillna(s.watch_p_season)
    r = lambda x: np.floor(x + 0.5).astype("Int64").astype(str)        # half up, as in the paper
    t = pd.DataFrame({"method": s.method, "watches (of 8)": s.watch_caught, "by chance": s.watch_chance_season,
                      "p": s.p.round(4), "warnings before onset": s.warning_pre_caught,
                      "median watch lead (h)": s.watch_median_lead_h,
                      "quiet grids: median / 90th pct / worst": r(s.watch_burden_median)
                      + " / " + r(s.watch_burden_p90) + " / " + r(s.watch_burden_max),
                      "within budget": s.watch_reached & s.warning_reached})
    return pd.concat([t[s.code != name].sort_values("watches (of 8)", ascending=False), t[s.code == name]])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", nargs="+", default=list(METHODS),
                    help="reference methods, or any folder in --scores (e.g. an extra HTM setup)")
    ap.add_argument("--scores", type=Path, default=ROOT / "reference_scores")
    ap.add_argument("--htm", type=Path, default=ROOT / "reference_scores" / "htm_frozen")
    ap.add_argument("--no-ablations", action="store_true")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--variants", nargs="+", help="rerun only these ablation variants (merged into ablation.csv)")
    ap.add_argument("--salt", type=int, default=0, help="tie-break draw; nonzero writes methods/<method>_salt<k>")
    ap.add_argument("--redo", action="store_true", help="rescore protocol outputs that already exist")
    a = ap.parse_args()
    global SALT
    SALT = a.salt
    if a.stats:
        return stats(a.method)
    args = [(m, a.scores, a.htm, not a.no_ablations, a.variants, a.redo) for m in a.method]
    if a.jobs > 1:
        with ProcessPoolExecutor(a.jobs) as ex:
            list(ex.map(score_method, *zip(*args)))
    else:
        for x in args:
            score_method(*x)


if __name__ == "__main__":
    main()
