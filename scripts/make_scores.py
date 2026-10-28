#!/usr/bin/env python3
"""Compute a reference method's per-signal scores and write them in the submission layout,
reference_scores/<method>/s<seed>/<grid>.csv.gz. Files already written are skipped, so a stopped
run picks up where it left off.

Usage: python scripts/make_scores.py gbm [--seeds 0 1] [--out reference_scores]
Methods and their seeds: gridshedwatch/baselines/__init__.py (METHODS).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import data, submission  # noqa: E402
from gridshedwatch.baselines import METHODS, scores  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("method", choices=[m for m, v in METHODS.items() if v[1]])
    ap.add_argument("--seeds", nargs="+", type=int)
    ap.add_argument("--out", type=Path, default=ROOT / "reference_scores")
    a = ap.parse_args()
    for k in a.seeds if a.seeds is not None else METHODS[a.method][2]:
        for g in data.grids():
            if (a.out / a.method / f"s{k}" / f"{g}.csv.gz").exists():
                continue
            submission.write({k: {g: scores(a.method, g, k)}}, a.out / a.method)
            print(a.method, f"s{k}", g, flush=True)


if __name__ == "__main__":
    main()
