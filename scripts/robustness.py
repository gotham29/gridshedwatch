#!/usr/bin/env python3
"""Rigor analyses on the v1.0 events, fixed before running (plan in the paper's appendix):

  A. significance   Friedman test over methods (events as blocks), Nemenyi critical difference,
                    and each method against the best one: paired bootstrap and exact sign test
  B. sensitivity    rankings at other alert budgets and window lengths, one setting at a time
  C. protocol       every method at the earlier shared setting (threshold 0.995, 3 h) vs matched budget
  D. by storm       events caught per storm (Uri, Elliott, the California heat wave)
  E. ensembles      seeded methods scored once on the causal percentile of their 5 seeds' mean score

Each method's alert sweep is computed once; other windows re-verify the same alert start times.
Needs the reference scores (scripts/fetch_reference.py, scripts/make_scores.py) and scipy.

On a later release (--version 2.0) only B runs, on all its events, as docs/protocol_v2.md fixes it:
each variant's operating point still comes from v1.0's grids, HTM's entry is htm-monitor frozen after
2019 (reference_scores/htm_frozen), and Tier 2 catches are also reported separately.

Usage: python scripts/robustness.py [--version 1.0] [--out results/v<version>/robustness]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import benchmark, data, submission  # noqa: E402
from gridshedwatch.baselines import LABEL, METHODS, oprule, to_p, zscore  # noqa: E402
from gridshedwatch.config import BUDGET, WINDOW  # noqa: E402

LEVELS = benchmark.LEVELS
COL = {"watch": "watches", "warning": "warnings"}
ENSEMBLE = ["htm", "lstm", "gbm", "patchtst"]
VARIANTS = {                                        # one setting changed at a time from v1.0
    "v1.0": ({}, {}),
    "watch budget 6": ({"watch": 6.0}, {}),
    "watch budget 24": ({"watch": 24.0}, {}),
    "warning budget 1": ({"warning": 1.0}, {}),
    "warning budget 4": ({"warning": 4.0}, {}),
    "watch window 72 h": ({}, {"watch": (72, 0)}),
    "watch window 336 h": ({}, {"watch": (336, 0)}),
    "warning after onset 24 h": ({}, {"warning": (168, 24)}),
    "warning after onset 72 h": ({}, {"warning": (168, 72)}),
}
SHARED = (0.995, 3)                                 # earlier htm-monitor comparison: threshold, persistence
NEMENYI_Q = {2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850, 7: 2.949, 8: 3.031, 9: 3.102, 10: 3.164}
DRAWS = 10_000


def entries(version="1.0"):
    """(key, label, alert function, seeds) for every method, plus each seeded method's ensemble and plain
    mean, with scores for the release's event grids (v1.0's grids are all among them)."""
    grids = data.event_grids(version)
    for m in METHODS:
        if m == "oprule":
            yield m, LABEL[m], oprule.alerts, [0]
            continue
        if m == "zscore":
            sc = {0: {g: zscore.scores(g) for g in grids}}
        else:
            folder = "htm_frozen" if m == "htm" and version != "1.0" else m
            sc = submission.load(ROOT / "reference_scores" / folder, version, grids)
        yield m, LABEL[m], benchmark.from_scores(sc), sorted(sc)
        if m in ENSEMBLE:
            mean = {g: {c: np.mean([sc[k][g][c].to_numpy() for k in sc], axis=0) for c in submission.COLUMNS}
                    for g in grids}
            ens = {0: {g: pd.DataFrame({c: to_p(v) for c, v in mean[g].items()}) for g in grids}}
            yield f"{m}_ens", f"{LABEL[m]} (5-seed ensemble)", benchmark.from_scores(ens), [0]
            # check, not in the plan: the plain mean, without re-ranking (HTM's scores are not percentiles)
            raw = {0: {g: pd.DataFrame(mean[g]) for g in grids}}
            yield f"{m}_mean", f"{LABEL[m]} (5-seed mean, check)", benchmark.from_scores(raw), [0]


def reverify(sw, window):
    """Sweep rows re-verified under other scoring windows, from the stored alert start times."""
    if not window:
        return sw
    w = {**WINDOW, **window}
    cols = []
    for r in sw.itertuples():
        st = [pd.Timestamp(s) for s in str(r.starts).split("|") if s and s != "nan"]
        cols.append(benchmark._row(st, r.grid, r.level, r.years, pd.Timestamp(r.onset), window=w))   # one row per event
    return sw.assign(**pd.DataFrame(cols, index=sw.index)[["n_verified", "caught", "lead_h"]])


def at_point(sw, op):
    return pd.concat([sw[(sw.level == lv) & np.isclose(sw.threshold, op[lv][0]) & (sw.L == op[lv][1])]
                      for lv in LEVELS])


def per_event(rows):
    """Share of seeds that caught each event, per level: DataFrame event x level (v1.0: event id = grid id)."""
    return rows.groupby(["event", "level"]).caught.mean().unstack("level")


def significance(caught, labels):
    """caught: {method: per-event Series} for one level. Friedman, Nemenyi CD, pairwise vs best."""
    M = pd.DataFrame(caught)                                     # events x methods
    ranks = M.rank(axis=1, ascending=False).mean()               # 1 = best
    chi2, p = stats.friedmanchisquare(*[M[c] for c in M])
    k, n = M.shape[1], M.shape[0]
    cd = NEMENYI_Q[k] * np.sqrt(k * (k + 1) / (6 * n))
    best = M.sum().idxmax()
    rng = np.random.default_rng(0)
    idx = rng.integers(0, n, size=(DRAWS, n))
    pair = []
    for c in M:
        if c == best:
            continue
        d = (M[best] - M[c]).to_numpy()
        boot = d[idx].sum(1)
        wins, losses = int((d > 0).sum()), int((d < 0).sum())
        sign_p = stats.binomtest(wins, wins + losses).pvalue if wins + losses else 1.0
        sd = d.std(ddof=1)
        need = int(np.ceil(((1.96 + 0.84) * sd / d.mean()) ** 2)) if d.mean() > 0 and sd > 0 else np.nan
        pair.append(dict(method=labels[c], vs=labels[best], diff=round(float(d.sum()), 2),
                         diff_ci="%.1f to %.1f" % tuple(np.percentile(boot, [2.5, 97.5])),
                         share_boot_le_0=round(float((boot <= 0).mean()), 4), events_better=wins,
                         events_worse=losses, sign_test_p=round(float(sign_p), 4),
                         rank_gap=round(float(ranks[c] - ranks[best]), 2), beyond_cd=bool(ranks[c] - ranks[best] > cd),
                         events_needed_80pct_power=need))
    summary = dict(friedman_chi2=round(float(chi2), 2), friedman_p=round(float(p), 4), methods=k, events=n,
                   critical_difference=round(float(cd), 2), best=labels[best])
    return ranks.rename(labels), pd.DataFrame(pair), summary


def cd_plot(ranks, cd, title, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    r = ranks.sort_values()
    fig, ax = plt.subplots(figsize=(7.5, 0.32 * len(r) + 1.2))
    ax.hlines(range(len(r)), 1, r.values, color="#c8c8c8", lw=1)
    ax.plot(r.values, range(len(r)), "o", color="#2b6cb0")
    ax.set_yticks(range(len(r)), r.index)
    ax.invert_yaxis()
    ax.set_xlim(0.5, len(r) + 0.5)
    ax.set_xlabel("Average rank over events (1 = best)")
    x0 = r.values[0]
    ax.plot([x0, x0 + cd], [-0.8, -0.8], color="#c53030", lw=3, solid_capstyle="butt")
    ax.text(x0 + cd / 2, -1.1, f"critical difference {cd:.2f}", ha="center", va="bottom", fontsize=9, color="#c53030")
    ax.set_ylim(len(r) - 0.5, -1.6)
    ax.set_title(title, fontsize=10, loc="left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    a.out = a.out or ROOT / "results" / f"v{a.version}" / "robustness"
    a.out.mkdir(parents=True, exist_ok=True)
    events = data.event_list(a.version)
    tier2 = [e["id"] for e in events if e["tier"] == 2]
    v1_grids = data.grids("1.0")
    storm = {g: e["storm"] for g, e in data.events().items()}
    labels, sens, proto, storms, ev = {}, [], [], [], {}
    for key, label, fn, seeds in entries(a.version):
        print(label, flush=True)
        labels[key] = label
        sw = benchmark.sweep(fn, seeds, events=events)
        for name, (budget, window) in VARIANTS.items():
            s = reverify(sw, window)
            op = benchmark.operating_point(s[s.grid.isin(v1_grids)], {**BUDGET, **budget})   # v1.0's grids
            rows = at_point(s, op)
            pe = per_event(rows)
            if name == "v1.0":
                ev[key] = pe
            sens.append(dict(variant=name, method=label, watches=round(pe["watch"].sum(), 1),
                             warnings=round(pe["warning"].sum(), 1),
                             **{f"{COL[lv]}_tier2": round(pe.loc[tier2, lv].sum(), 1) for lv in LEVELS if tier2},
                             watch_setting=f"{op['watch'][0]}, {op['watch'][1]} h",
                             warning_setting=f"{op['warning'][0]}, {op['warning'][1]} h"))
        if a.version != "1.0":
            continue
        x = sw[(sw.level == "watch") & np.isclose(sw.threshold, SHARED[0]) & (sw.L == SHARED[1])]
        proto.append(dict(method=label, shared_caught=round(x.groupby("grid").caught.mean().sum(), 1),
                          shared_alerts_per_grid_year=round(float(x.groupby("seed").apply(
                              lambda y: y.n_alerts.sum() / y.years.sum()).mean()), 1)))
        for g, r in ev[key].iterrows():
            storms.append(dict(method=label, storm=storm[g], grid=g, watch=r["watch"], warning=r["warning"]))

    main_methods = list(METHODS)                                   # tests and ranks on the nine methods only
    main_labels = [labels[m] for m in main_methods]
    sens = pd.DataFrame(sens)
    base = sens[sens.variant == "v1.0"].set_index("method").loc[main_labels]
    tau = []
    for name in VARIANTS:
        x = sens[sens.variant == name].set_index("method").loc[main_labels]
        tau.append(dict(variant=name, **{f"tau_{lv}": round(stats.kendalltau(base[COL[lv]], x[COL[lv]]).statistic, 2)
                                       for lv in LEVELS}))
    sens.to_csv(a.out / "sensitivity.csv", index=False)
    pd.DataFrame(tau).to_csv(a.out / "sensitivity_tau.csv", index=False)
    if a.version != "1.0":                                         # protocol_v2: only B on a release
        print(pd.DataFrame(tau).to_string(index=False))
        return

    proto = pd.DataFrame(proto)
    proto = proto[proto.method.isin(main_labels)].merge(
        base[["watches"]].rename(columns={"watches": "matched_budget_caught"}), left_on="method", right_index=True)
    proto["shared_rank"] = proto.shared_caught.rank(ascending=False, method="min").astype(int)
    proto["matched_rank"] = proto.matched_budget_caught.rank(ascending=False, method="min").astype(int)
    proto.to_csv(a.out / "protocol.csv", index=False)

    st = pd.DataFrame(storms)
    st.groupby(["method", "storm"])[["watch", "warning"]].sum().round(1).unstack("storm").to_csv(a.out / "by_storm.csv")

    sig = []
    for lv in LEVELS:
        ranks, pair, summ = significance({m: ev[m][lv] for m in main_methods}, labels)
        pair.insert(0, "level", lv)
        sig.append(pair)
        pd.Series(summ).to_csv(a.out / f"friedman_{lv}.csv", header=False)
        ranks.rename("average_rank").to_csv(a.out / f"ranks_{lv}.csv")
        title = f"{'Watches' if lv == 'watch' else 'Warnings'}: average rank over the 8 events (Friedman p = {summ['friedman_p']})"
        cd_plot(ranks, summ["critical_difference"], title, a.out / f"cd_{lv}.png")
        print(lv, summ, flush=True)
    pd.concat(sig).to_csv(a.out / "pairwise.csv", index=False)

    ens = sens[(sens.variant == "v1.0")].set_index("method")[["watches", "warnings"]]
    ens.to_csv(a.out / "v1_matched_budget_all.csv")
    print(ens.to_string())
    print(pd.DataFrame(tau).to_string(index=False))
    print(proto.to_string(index=False))


if __name__ == "__main__":
    main()
