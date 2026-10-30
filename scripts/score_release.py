#!/usr/bin/env python3
"""Score every reference method on a release, as fixed in docs/protocol_v2.md, and write results/v<version>/.

  summary.csv        one row per method: Tier 1 (= v1.0), Tier 2, false alarm ratio over all events,
                     alert burden on all, quiet and unflagged quiet grids
  events.csv         per method x event x level: share of seeds that caught it, median lead (h)
  burden.csv         per method x grid x level: alerts per grid-year (mean over seeds) with the grid's
                     data-quality flags
  sensitivity.csv    the same summary with the operating point re-derived over all the release's grids

HTM's entry is htm-monitor frozen after 2019 (--htm, the folder exported by htm-monitor's
`htm_gsw.py export --variant pre_frozen --version 2.0`); v1.0's HTM row stays the Tier 1 row.
Needs reference scores for every grid of the release (scripts/make_scores.py <method> --version 2.0).

Usage: python scripts/score_release.py [--version 2.0] [--htm DIR] [--method zscore gbm ...]
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import benchmark, data, submission  # noqa: E402
from gridshedwatch.baselines import LABEL, METHODS, oprule, zscore  # noqa: E402

HTM_V2 = "HTM (htm-monitor, frozen after 2019)"


def entries(version: str, htm: Path, methods: list):
    """(label, alert function, seeds) per method; HTM's is the frozen entry."""
    for m in methods:
        if m == "oprule":
            yield LABEL[m], oprule.alerts, [0]
            continue
        if m == "zscore":
            sc = {0: {g: zscore.scores(g) for g in data.grids(version)}}
        else:
            sc = submission.load(htm if m == "htm" else ROOT / "reference_scores" / m, version)
        yield (HTM_V2 if m == "htm" else LABEL[m]), benchmark.from_scores(sc), sorted(sc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="2.0")
    ap.add_argument("--htm", type=Path, default=ROOT / "reference_scores" / "htm_frozen")
    ap.add_argument("--method", nargs="+", default=list(METHODS), choices=list(METHODS))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    out = a.out or ROOT / "results" / f"v{a.version}"
    out.mkdir(parents=True, exist_ok=True)
    q = data.quality(a.version)[["flat_flag", "shift_flag"]]
    summary, events, burden, sens = [], [], [], []
    for label, fn, seeds in entries(a.version, a.htm, a.method):
        print(label, flush=True)
        r = benchmark.evaluate_release(label, fn, seeds, a.version)
        summary.append(r.summary)
        ev = r.rows.groupby(["event", "level"]).agg(caught=("caught", "mean"), lead_h=("lead_h", "median")).reset_index()
        events.append(ev.assign(method=label))
        b = r.burden.groupby(["grid", "level"]).rate.mean().round(2).reset_index()
        burden.append(b.join(q, on="grid").assign(method=label))
        sens.append(benchmark.evaluate_release(label, fn, seeds, a.version, chance=False, op_from=a.version).summary)
        pd.DataFrame(summary).to_csv(out / "summary.csv", index=False)               # written as it goes
    pd.concat(events)[["method", "event", "level", "caught", "lead_h"]].to_csv(out / "events.csv", index=False)
    pd.concat(burden)[["method", "grid", "level", "rate", "flat_flag", "shift_flag"]].to_csv(out / "burden.csv", index=False)
    pd.DataFrame(sens).to_csv(out / "sensitivity.csv", index=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
