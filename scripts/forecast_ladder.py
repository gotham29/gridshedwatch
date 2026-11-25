#!/usr/bin/env python3
"""Build gridshedwatch/forecast_ladder.csv: the forecast baseline (baselines/dfanom.py through the shared
watch rule) at a ladder of alert rates, each scored by protocol v4.0 (gridshedwatch/verify.py).
`gridshedwatch score-alerts` reads it to show the baseline at a submission's own false-alarm rate."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import benchmark, verify  # noqa: E402
from gridshedwatch.baselines import dfanom  # noqa: E402

RATES = (2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32, 48)


def main():
    _, _, grids, _, _ = verify.setup()
    fn = benchmark.from_scores({0: {g: dfanom.scores(g) for g in grids}})
    cal = benchmark.Calibrator(fn, [0], grids, "watch")
    rows = []
    for r in RATES:
        op = cal(r)
        st = benchmark.starts_at(fn, [0], grids, "watch", op["threshold"], op["persistence"])
        s = verify.score({0: [(g, t) for (_, g), v in st.items() for t in v]}, chance=False)
        rows.append(dict(rate=r, threshold=op["threshold"], **{k: v for k, v in s.items() if not isinstance(v, dict)}))
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(verify.FORECAST_LADDER, index=False)


if __name__ == "__main__":
    main()
