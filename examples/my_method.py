#!/usr/bin/env python3
"""Template: score your own method on GridShedWatch.

Your method's only job: for every grid, every hour of the timebase and each of the five signals,
a score in [0, 1] of how unusual that signal is now, using data up to that hour only. Here, as a
placeholder, the score is the causal percentile of each signal's absolute change from the
previous hour. Replace `my_scores` with your method.

Run:  python examples/my_method.py && gridshedwatch score my_scores --name "My method"
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gridshedwatch import data, submission  # noqa: E402
from gridshedwatch.baselines import to_p  # noqa: E402
from gridshedwatch.config import SIGNALS  # noqa: E402


def my_scores(grid: str, seed: int = 0) -> pd.DataFrame:
    X = data.signals(grid)               # timestamp + the five signals, one row per step
    cal = data.calibration(grid)         # 2019, if your method learns before the run
    out = {}
    for f in SIGNALS:
        x = X[f].to_numpy(float)
        raw = np.abs(np.diff(x, prepend=x[0]))
        out[f"p_{f}"] = to_p(raw)        # map any raw score to [0, 1], causally
    return pd.DataFrame(out)


if __name__ == "__main__":
    seeds = [0]                          # list several if your method is random
    scores = {k: {g: my_scores(g, k) for g in data.grids()} for k in seeds}
    submission.write(scores, "my_scores")
    print("wrote my_scores/; now: gridshedwatch score my_scores --name 'My method'")
