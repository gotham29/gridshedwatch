#!/usr/bin/env python3
"""Score reference methods under docs/protocol_v3.md and write results/v3.0/.

Step 1, per method (resumable; methods can run in parallel with --jobs):
    python scripts/score_v3.py --method gbm lstm ...      (default: every method)
  writes results/v3.0/methods/<method>/ with
    op.csv        operating point per level and budget (threshold, persistence, calibration-grid rate)
    events.csv    per seed x event x level at the protocol budget
    grids.csv     per seed x grid x level: alerts, verified, masked (near-miss), grid group
    curves.csv    Tier 1 catches per level and budget
    chance.csv    per level and null (season, any): observed, chance, p, chance lead
    sens.csv      Tier 1 catches with delayed data (latency) and with OE-417 onsets
    ablation.csv  alert rules (any signal, forecast error only) and the likelihood transform
Step 2, all methods together:
    python scripts/score_v3.py --stats
  writes results/v3.0/summary.csv, events.csv, stats_*.csv, loso.csv, lead_vs_notice.csv.
"""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import benchmark, data, submission  # noqa: E402
from gridshedwatch.baselines import HTM_V2, LABEL, METHODS, likelihood, oprule, scores  # noqa: E402
from gridshedwatch.config import BUDGET, GRID_CAP, LATENCY_H, SIGNALS, V3_CURVE, WINDOW  # noqa: E402

V = "2.0"                                     # the data release scored (48 grids, 10 events)
LEVELS = benchmark.LEVELS
OUT = ROOT / "results" / "v3.0"
VARIANTS = {"any_signal": list(SIGNALS), "forecast_error_only": ["forecast_error"]}


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
    return benchmark.from_scores(sc), sorted(sc), sc


def tier1(ev: pd.DataFrame) -> pd.DataFrame:
    return ev[ev.tier == 1]


def caught(ev: pd.DataFrame, col: str = "caught") -> float:
    """Tier 1 events caught, mean over seeds."""
    return float(tier1(ev).groupby("seed")[col].sum().mean())


def score_method(m: str, scores_root: Path, htm: Path, ablations: bool = True, only: list = None):
    """Protocol outputs, then ablations. only: rerun just these ablation variants, merged into ablation.csv."""
    out = OUT / "methods" / m
    if not only and ((out / "ablation.csv").exists() or ((out / "sens.csv").exists() and not ablations)):
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
    ops, evs, grs, curves, chance, sens = [], [], [], [], [], []
    for lv in LEVELS:
        cal = benchmark.Calibrator(fn, seeds, calib, lv)
        op = cal(BUDGET[lv])
        ops.append(dict(level=lv, budget=BUDGET[lv], **op))
        st = benchmark.starts_at(fn, seeds, list(group), lv, op["threshold"], op["persistence"])
        ev, gr = benchmark.verify_v3(st, lv, events, near)
        evs.append(ev.assign(level=lv))
        grs.append(gr.assign(level=lv, group=gr.grid.map(group)))
        st_ev = {kg: v for kg, v in st.items() if kg[1] in evg}
        for col in ("caught", "caught_pre"):
            if lv == "watch" and col == "caught_pre":
                continue
            obs = caught(ev, col)
            for mode in ("season", "any"):
                null = benchmark.chance_v3(st_ev, lv, t1, rng, mode)
                chance.append(dict(level=lv, measure=col, null=mode, observed=obs, chance=float(null[col].mean()),
                                   p=float((1 + (null[col] >= obs - 1e-9).sum()) / (len(null[col]) + 1)),
                                   chance_median_lead_h=float(np.median(null["leads"])) if len(null["leads"]) else np.nan))
        for b in V3_CURVE[lv]:
            o = op if b == BUDGET[lv] else cal(b)
            if b != BUDGET[lv]:
                ops.append(dict(level=lv, budget=b, **o))
            sb = st_ev if b == BUDGET[lv] else benchmark.starts_at(fn, seeds, evg, lv, o["threshold"], o["persistence"])
            e_b, _ = benchmark.verify_v3(sb, lv, t1)
            curves.append(dict(level=lv, budget=b, calib_rate=o["calib_rate"], caught=caught(e_b),
                               caught_pre=caught(e_b, "caught_pre")))
        for L in LATENCY_H:
            e_l, _ = benchmark.verify_v3(st_ev, lv, t1, shift_h=L)
            sens.append(dict(level=lv, variant=f"latency {L} h", caught=caught(e_l), caught_pre=caught(e_l, "caught_pre")))
        e_o, _ = benchmark.verify_v3(st_ev, lv, t1, onset_field="oe417_start_utc")
        sens.append(dict(level=lv, variant="onset: earlier of declaration and OE-417", caught=caught(e_o),
                         caught_pre=caught(e_o, "caught_pre")))
    pd.DataFrame(ops).to_csv(out / "op.csv", index=False)
    pd.concat(evs).to_csv(out / "events.csv", index=False)
    pd.concat(grs).to_csv(out / "grids.csv", index=False)
    pd.DataFrame(curves).to_csv(out / "curves.csv", index=False)
    pd.DataFrame(chance).to_csv(out / "chance.csv", index=False)
    pd.DataFrame(sens).to_csv(out / "sens.csv", index=False)
    print(m, "protocol done", flush=True)
    if ablations and sc is not None:
        ablate(m, fn, seeds, sc, out, list(VARIANTS) + ["likelihood_transform"])


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
        lk = {k: {g: pd.DataFrame({c: likelihood(df[c].to_numpy(), X[g][c[2:]].to_numpy(float)) for c in df})
                  for g, df in v.items()} for k, v in sc.items()}
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
    """False alarm ratio on event grids (mean over seeds), with and without near-miss masks."""
    s = gr.groupby("seed")[["n_alerts", "n_verified", "n_masked"]].sum()
    return dict(alerts=float(s.n_alerts.mean()), verified=float(s.n_verified.mean()), masked=float(s.n_masked.mean()),
                far=float((1 - s.n_verified / s.n_alerts).mean()),
                far_masked=float((1 - s.n_verified / (s.n_alerts - s.n_masked)).mean()))


def burden(gr: pd.DataFrame, lv: str) -> dict:
    """Alerts per grid-year (mean over seeds) on a group of quiet grids, with and without masks."""
    r = gr.assign(rate=gr.n_alerts / gr.years, rate_m=(gr.n_alerts - gr.n_masked) / gr.years).groupby("grid")[["rate", "rate_m"]].mean()
    cap = GRID_CAP * BUDGET[lv]
    return dict(burden_median=r.rate.median(), burden_p90=r.rate.quantile(0.9), burden_max=r.rate.max(),
                burden_max_grid=r.rate.idxmax(), over_cap=int((r.rate > cap).sum()),
                burden_p90_masked=r.rate_m.quantile(0.9), burden_max_masked=r.rate_m.max(),
                over_cap_masked=int((r.rate_m > cap).sum()))


# ------------------------------------------------------------------------------------- step 2

def label(m: str) -> str:
    return HTM_V2 if m == "htm" else LABEL.get(m, m)


def notice_leads() -> dict:
    """Hours before onset of each Tier 1 event's first public operator notice (None if none in the week)."""
    out = {}
    for g, e in data.operator_notices().items():
        on = data.onset(g)
        pub = [pd.Timestamp(n["utc"]) for n in e["notices"] if n.get("public")]
        pre = [t for t in pub if on - WINDOW["watch"][0] * benchmark.H <= t < on]
        out[g] = (on - min(pre)) / benchmark.H if pre else None
    return out


def stats(primary: list):
    from scipy.stats import binomtest, friedmanchisquare, rankdata, studentized_range
    ms = [m for m in primary if (OUT / "methods" / m / "sens.csv").exists()]
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
            s[f"{lv}_threshold"], s[f"{lv}_persistence"] = round(o.threshold, 5), int(o.persistence)
            s[f"{lv}_calib_rate"], s[f"{lv}_reached"] = round(o.calib_rate, 2), bool(o.reached)
            for col in (["caught"] if lv == "watch" else ["caught_pre", "caught"]):
                c = t.groupby("seed")[col].sum()
                key = f"{lv}_{'pre' if col == 'caught_pre' else 'any'}" if lv == "warning" else lv
                n = int(round(c.mean()))
                s[f"{key}_caught"] = round(float(c.mean()), 1)
                s[f"{key}_ci"] = "%.2f-%.2f" % benchmark.clopper_pearson(n, 8)
                s[f"{key}_seed_range"] = f"{int(c.min())}-{int(c.max())}"
                s[f"{key}_held_out"] = round(float(t[t.split == "held-out"].groupby("seed")[col].sum().mean()), 1)
                for mode in ("season", "any"):
                    r = ch[(ch.level == lv) & (ch.measure == col) & (ch.null == mode)]
                    if len(r):
                        s[f"{key}_chance_{mode}"], s[f"{key}_p_{mode}"] = round(r.chance.iloc[0], 2), r.p.iloc[0]
                        s[f"{key}_chance_lead_h"] = round(r.chance_median_lead_h.iloc[0], 0) if mode == "season" else s.get(f"{key}_chance_lead_h")
                per_ev_mat[(m, key)] = t.groupby("event")[col].mean()
            pre = t[t.caught_pre]
            leads = pre.groupby("event").lead_h.median()
            s[f"{lv}_median_lead_h"], s[f"{lv}_lead_n_events"] = (round(float(leads.median()), 0) if len(leads) else np.nan), len(leads)
            if lv == "watch":
                for g, ln in nl.items():
                    lead_rows.append(dict(method=label(m), event=g, method_lead_h=leads.get(g, np.nan), notice_lead_h=ln))
            f = far(gr[(gr.level == lv) & (gr.group == "event")])
            hits = s[f"{lv}_caught"] if lv == "watch" else s["warning_pre_caught"]
            s.update({f"{lv}_{k}": round(v, 3) for k, v in f.items()})
            s[f"{lv}_csi"] = round(hits / (8 + f["alerts"] - f["verified"] - f["masked"]), 3)
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
    for col in [c for c in sm if "_p_" in c]:
        p = sm[col].to_numpy(float)
        order = np.argsort(p)
        adj = np.maximum.accumulate(np.minimum(1, (len(p) - np.arange(len(p))) * p[order]))
        sm.loc[sm.index[order], col + "_holm"] = adj
    sm.to_csv(OUT / "summary.csv", index=False)
    # Friedman, Nemenyi, Holm-corrected sign tests against the leader, leave one storm out
    storms = {e["id"]: e.get("storm") for e in data.event_list(V) if e["tier"] == 1}
    fr, pw, loso = [], [], []
    for key in ("watch", "warning_pre", "warning_any"):
        X = pd.DataFrame({m: per_ev_mat[(m, key)] for m in ms if (m, key) in per_ev_mat and m in METHODS})  # entries only
        if X.shape[1] < 3:
            continue
        R = np.array([rankdata(-row) for row in X.to_numpy()])
        k, n = X.shape[1], X.shape[0]
        cd = studentized_range.ppf(0.95, k, np.inf) / np.sqrt(2) * np.sqrt(k * (k + 1) / (6 * n))
        fr.append(dict(measure=key, events=n, methods=k, friedman_p=friedmanchisquare(*X.to_numpy().T).pvalue,
                       friedman_p_without_random=friedmanchisquare(*X.drop(columns="random", errors="ignore").to_numpy().T).pvalue,
                       nemenyi_cd=cd, **{f"rank_{label(m)}": r for m, r in zip(X.columns, R.mean(0))}))
        lead = X.sum().idxmax()
        rows = []
        for m in X.columns:
            if m == lead:
                continue
            d = X[lead] - X[m]
            better, worse = int((d > 0).sum()), int((d < 0).sum())
            p = binomtest(better, better + worse).pvalue if better + worse else 1.0
            rows.append(dict(measure=key, leader=label(lead), method=label(m), events_behind=round(float(d.sum()), 1),
                             leader_better=better, leader_worse=worse, sign_p=p))
        r = pd.DataFrame(rows).sort_values("sign_p")
        r["sign_p_holm"] = np.maximum.accumulate(np.minimum(1, (len(r) - np.arange(len(r))) * r.sign_p.to_numpy()))
        pw.append(r)
        for st in sorted(set(storms.values())):
            keep = [e for e in X.index if storms.get(e) != st]
            loso.append(dict(measure=key, without=st, events=len(keep), **{label(m): round(float(X.loc[keep, m].sum()), 1) for m in X.columns}))
    pd.DataFrame(fr).to_csv(OUT / "stats_friedman.csv", index=False)
    pd.concat(pw or [pd.DataFrame()]).to_csv(OUT / "stats_pairwise.csv", index=False)
    pd.DataFrame(loso).to_csv(OUT / "loso.csv", index=False)
    print("wrote", OUT)


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
    a = ap.parse_args()
    if a.stats:
        return stats(a.method)
    args = [(m, a.scores, a.htm, not a.no_ablations, a.variants) for m in a.method]
    if a.jobs > 1:
        with ProcessPoolExecutor(a.jobs) as ex:
            list(ex.map(score_method, *zip(*args)))
    else:
        for x in args:
            score_method(*x)


if __name__ == "__main__":
    main()
