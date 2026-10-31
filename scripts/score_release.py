#!/usr/bin/env python3
"""Score every reference method on a release, as fixed in docs/protocol_v2.md, and write results/v<version>/.

  summary.csv        one row per method: Tier 1 (= v1.0), Tier 2, false alarm ratio over all events,
                     alert burden on all, quiet and unflagged quiet grids
  events.csv         per method x event x level: share of seeds that caught it, median lead (h)
  burden.csv         per method x grid x level: alerts per grid-year (mean over seeds) with the grid's
                     data-quality flags
  sensitivity.csv    the same summary with the operating point re-derived over all the release's grids
  alerts.csv         per method x event x level x seed: each alert that verifies the event, its hours from
                     onset, and the signals at or above threshold in the hours that raised it (blank for
                     the operator rule, which has no scores)

HTM's entry is htm-monitor frozen after 2019 (--htm, the folder exported by htm-monitor's
`htm_gsw.py export --variant pre_frozen --version 2.0`); v1.0's HTM row stays the Tier 1 row.
Needs reference scores for every grid of the release (scripts/make_scores.py <method> --version 2.0).

Usage: python scripts/score_release.py [--version 2.0] [--htm DIR] [--method zscore gbm ...]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import benchmark, data, submission  # noqa: E402
from gridshedwatch.baselines import HTM_V2, LABEL, METHODS, oprule, zscore  # noqa: E402


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


def event_alerts(label: str, fn, rows: pd.DataFrame) -> list:
    """Alerts inside each event's scoring window, at the operating point, with the signals behind them."""
    sc = getattr(fn, "scores", None)
    out = []
    for x in rows.itertuples():
        on = pd.Timestamp(x.onset)
        st = [pd.Timestamp(s) for s in str(x.starts).split("|") if s and s != "nan"]
        for s in benchmark.verified(st, on, x.level):
            sig = ""
            if sc is not None:
                i = int(np.flatnonzero((data.timebase(x.grid)["timestamp"] == s).to_numpy())[0])
                p = sc[x.seed][x.grid].iloc[max(i - int(x.L) + 1, 0): i + 1]
                sig = "+".join(c[2:] for c in p if (p[c] >= x.threshold).any())
            out.append(dict(method=label, event=x.event, level=x.level, seed=x.seed, start=s,
                            h_from_onset=round((s - on) / pd.Timedelta(hours=1)), signals=sig))
    return out


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
    summary, events, burden, sens, alerts = [], [], [], [], []
    for label, fn, seeds in entries(a.version, a.htm, a.method):
        print(label, flush=True)
        r = benchmark.evaluate_release(label, fn, seeds, a.version)
        summary.append(r.summary)
        ev = r.rows.groupby(["event", "level"]).agg(caught=("caught", "mean"), lead_h=("lead_h", "median")).reset_index()
        events.append(ev.assign(method=label))
        alerts += event_alerts(label, fn, r.rows)
        b = r.burden.groupby(["grid", "level"]).rate.mean().round(2).reset_index()
        burden.append(b.join(q, on="grid").assign(method=label))
        sens.append(benchmark.evaluate_release(label, fn, seeds, a.version, chance=False, op_from=a.version).summary)
        pd.DataFrame(summary).to_csv(out / "summary.csv", index=False)               # written as it goes
    pd.concat(events)[["method", "event", "level", "caught", "lead_h"]].to_csv(out / "events.csv", index=False)
    pd.concat(burden)[["method", "grid", "level", "rate", "flat_flag", "shift_flag"]].to_csv(out / "burden.csv", index=False)
    pd.DataFrame(sens).to_csv(out / "sensitivity.csv", index=False)
    pd.DataFrame(alerts).to_csv(out / "alerts.csv", index=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
