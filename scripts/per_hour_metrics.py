#!/usr/bin/env python3
"""Score the v1.0 reference methods with the usual per-hour anomaly-detection metrics and compare
the ranking with GridShedWatch's event-level ranking.

Metrics come from TSB-AD's own implementation (pip install TSB-AD --no-deps; it needs only numpy
and scikit-learn for these): AUC-ROC, AUC-PR, VUS-ROC, VUS-PR, point F1, point-adjusted F1,
event-based F1, range F1 and affiliation F, with threshold-dependent ones at their oracle threshold,
as TSB-AD reports them.

Per-hour score of a method = the largest of its five per-signal scores at that hour. The operator
rule has no per-signal scores, so its score is the causal percentile of percent forecast error
(the quantity its rule thresholds). A random method draws uniform scores (5 seeds).

Labels, two variants:
  event:   the 48 hours from onset (the emergency itself, as a per-hour benchmark would label it)
  lead:    the 168 hours before onset (the window in which a watch counts)
Metrics are computed per grid (post-warm-up hours only), averaged over seeds, then over grids.

Usage: python scripts/per_hour_metrics.py [--jobs 2] [--out results/v1.0/per_hour]
"""
import argparse
import json
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import data, submission  # noqa: E402
from gridshedwatch.baselines import LABEL, to_p, zscore  # noqa: E402

H = pd.Timedelta(hours=1)
LABELS = {"event": (0, 48), "lead": (-168, 0)}          # hours relative to onset, [lo, hi)
WINDOW = 24                                              # TSB-AD sliding window (daily cycle)
RANDOM_SEEDS = range(5)


def oprule_score(grid):
    w = data.clean_eia930(grid)
    pct = ((w["D"] - w["DF"]) / w["DF"].where(w["DF"] > 0) * 100).asfreq("h")
    x = pct.reindex(data.timebase(grid)["timestamp"]).ffill().fillna(0).to_numpy()
    return to_p(x)


def scores_for(method, grid):
    """{seed: per-hour score on the timebase}."""
    if method == "oprule":
        return {0: oprule_score(grid)}
    if method == "zscore":
        return {0: zscore.scores(grid).to_numpy().max(axis=1)}
    if method == "random":
        n = len(data.timebase(grid))
        return {k: np.random.default_rng(1000 + k).random(n) for k in RANDOM_SEEDS}
    sc = submission.load(ROOT / "reference_scores" / method)
    return {k: sc[k][grid].to_numpy().max(axis=1) for k in sc}


def labels(grid, variant):
    tb = data.timebase(grid)
    d = (tb["timestamp"] - data.onset(grid)) / H
    lo, hi = LABELS[variant]
    return ((d >= lo) & (d < hi)).to_numpy(int)


def job(args):
    method, grid, variant, seed, score = args
    from TSB_AD.evaluation.metrics import get_metrics
    live = data.timebase(grid)["in_warmup"].to_numpy() == 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = get_metrics(np.asarray(score, float)[live], labels(grid, variant)[live], slidingWindow=WINDOW)
    return dict(method=method, grid=grid, labels=variant, seed=seed, **{k: float(v) for k, v in m.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "v1.0" / "per_hour")
    ap.add_argument("--method", nargs="+", default=["oprule", "zscore", "chronos", "subpca", "gbm", "patchtst", "lstm", "htm",
                                                    "random"])
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    done_file = a.out / "per_hour_raw.jsonl"           # one line per finished task, so a stopped run resumes
    rows = [json.loads(x) for x in done_file.read_text().splitlines()] if done_file.exists() else []
    done = {(r["method"], r["grid"], r["labels"], r["seed"]) for r in rows}
    tasks = [(m, g, v, k, s) for m in a.method for g in data.grids() for k, s in scores_for(m, g).items()
             for v in LABELS if (m, g, v, k) not in done]
    with ProcessPoolExecutor(a.jobs) as ex, done_file.open("a") as fh:
        for i, r in enumerate(ex.map(job, tasks, chunksize=1)):
            rows.append(r)
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(f"{i + 1}/{len(tasks)} {r['method']} {r['grid']} {r['labels']} s{r['seed']}", flush=True)
    raw = pd.DataFrame(rows)
    raw.to_csv(a.out / "per_hour_raw.csv", index=False)
    metrics = [c for c in raw.columns if c not in ("method", "grid", "labels", "seed")]
    per_grid = raw.groupby(["labels", "method", "grid"])[metrics].mean()
    summary = per_grid.groupby(["labels", "method"]).mean().reset_index()
    summary.insert(1, "name", summary.method.map(LABEL))
    summary.to_csv(a.out / "per_hour_summary.csv", index=False, float_format="%.4f")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
