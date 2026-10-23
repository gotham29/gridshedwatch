#!/usr/bin/env python3
"""Score every reference method and write results/v1.0/. Reference scores for the LSTM, Chronos
and HTM are read from reference_scores/ (download: python scripts/fetch_reference.py); the
operator-style rule and the z-score are computed from the data here.

Usage: python scripts/reproduce_v1.py [--method zscore oprule lstm chronos htm] [--no-chance]
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import benchmark, data, submission  # noqa: E402
from gridshedwatch.baselines import oprule, zscore  # noqa: E402

LABEL = {"oprule": "Operator-style rule", "zscore": "Seasonal z-score", "chronos": "Chronos-Bolt (zero-shot)",
         "lstm": "LSTM forecaster", "htm": "HTM (htm-monitor)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", nargs="+", default=list(LABEL))
    ap.add_argument("--no-chance", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "v1.0")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows = [benchmark.status_quo()]
    for m in a.method:
        if m == "oprule":
            fn, seeds = oprule.alerts, [0]
        elif m == "zscore":
            sc = {0: {g: zscore.scores(g) for g in data.grids()}}
            fn, seeds = benchmark.from_scores(sc), [0]
        else:
            sc = submission.load(ROOT / "reference_scores" / m)
            fn, seeds = benchmark.from_scores(sc), sorted(sc)
        r = benchmark.evaluate(LABEL[m], fn, seeds, chance=not a.no_chance)
        r.rows.drop(columns=["starts"]).to_csv(a.out / f"{m}_events.csv", index=False)
        rows.append(r.summary)
        print(json.dumps(r.summary), flush=True)
    S = pd.DataFrame([{k: v for k, v in x.items() if k != "by_grid"} for x in rows])
    S.to_csv(a.out / "leaderboard.csv", index=False)
    print(S.to_string(index=False))


if __name__ == "__main__":
    main()
