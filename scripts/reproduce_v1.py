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
from gridshedwatch import alerts, benchmark, data, submission  # noqa: E402
from gridshedwatch.baselines import LABEL, V1_METHODS, oprule, zscore  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", nargs="+", default=V1_METHODS, choices=list(LABEL))
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
        r.rows.drop(columns=["starts", "event", "onset"]).to_csv(a.out / f"{m}_events.csv", index=False)   # v1.0: event = grid
        alerts.write(alerts.from_rows(r.rows), a.out / "alerts" / f"{m}.csv")
        rows.append(r.summary)
        print(json.dumps(r.summary), flush=True)
    S = pd.DataFrame([{k: v for k, v in x.items() if k != "by_grid"} for x in rows])
    S.to_csv(a.out / "leaderboard.csv", index=False)
    print(S.to_string(index=False))


if __name__ == "__main__":
    main()
