#!/usr/bin/env python3
"""Freeze a release's new grids from a fresh EIA-930 pull (scripts/pull_eia930.py --ba all --write DIR).

For every grid in grids.yaml with `since` = the release, this copies its pulled file byte for byte into
gridshedwatch/snapshot_v<release>/eia930/, checks the coverage rule (config.MIN_COVERAGE of 2019 and
of the scored period, after the bad-data filter), and writes:

  SHA256SUMS          checksums of the copied files
  bounds_2019.json    0.1st-99.9th percentile of each signal over 2019, rounded to 0.01, frozen
  quality.csv         coverage, hours dropped by the bad-data filter, longest flat demand run, share of
                      hours with forecast error outside its 2019 range, change in mean demand since
                      2019, last hour, and the flags they set (config.FLAT_FLAG_H, SHIFT_FLAG), for
                      every grid of the release (earlier releases' grids included)

It also lists any balancing authority in the pull that passes the rule but is missing from grids.yaml,
and stops if a listed grid fails it. Earlier releases' snapshot folders are never touched.

Usage: python scripts/build_snapshot.py --source DIR [--version 2.0]
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import data  # noqa: E402
from gridshedwatch.config import (CAL_END, CAL_START, FLAT_FLAG_H, MIN_COVERAGE, RUN_END, RUN_START,  # noqa: E402
                                  SHIFT_FLAG, SIGNALS, SNAPSHOTS)

# EIA-930 respondents that are regions or the US total, not balancing authorities.
REGIONS = {"CAL", "CAR", "CENT", "FLA", "MIDA", "MIDW", "NE", "NW", "NY", "SE", "SW", "TEN", "TEX", "US48"}


def quality(f: Path) -> dict:
    """Coverage after the bad-data filter (share of hours with D, DF and NG), and flags."""
    w = pd.read_csv(f, index_col="period_utc")
    w.index = pd.to_datetime(w.index, format="%Y-%m-%dT%H")
    w = w[["D", "DF", "NG"]].dropna().sort_index()
    cal = (w.index >= CAL_START) & (w.index <= CAL_END)
    bad = data.glitch_mask(w, w[cal]) if cal.any() else pd.Series(True, index=w.index)
    ok = w[~bad]
    n = lambda a, b: len(pd.date_range(a, b, freq="h"))
    in_ = lambda x, a, b: int(((x.index >= a) & (x.index <= b)).sum())
    c, r = ok[(ok.index >= CAL_START) & (ok.index <= CAL_END)], ok[(ok.index >= RUN_START) & (ok.index <= RUN_END)]
    run = r.D
    flat = int(run.groupby((run.diff() != 0).cumsum()).size().max()) if len(run) else 0
    fe, fe19 = r.D - r.DF, c.D - c.DF
    outside = float(((fe < fe19.quantile(0.001)) | (fe > fe19.quantile(0.999))).mean()) if len(c) and len(r) else 1.0
    last = run[run.index > run.index.max() - pd.Timedelta(days=365)] if len(run) else run
    change = float(last.mean() / c.D.mean() - 1) if len(c) and len(run) else float("nan")
    return dict(cal_coverage=round(in_(ok, CAL_START, CAL_END) / n(CAL_START, CAL_END), 3),
                run_coverage=round(in_(ok, RUN_START, RUN_END) / n(RUN_START, RUN_END), 3),
                filtered_hours=int(bad[(w.index >= RUN_START) & (w.index <= RUN_END)].sum()),
                longest_flat_demand_h=flat, forecast_error_outside_2019=round(outside, 3),
                demand_change_since_2019=round(change, 3), last_hour=str(run.index.max())[:13],
                flat_flag=flat >= FLAT_FLAG_H, shift_flag=outside >= SHIFT_FLAG)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True, help="folder of pulled <BA>.csv.gz files")
    ap.add_argument("--version", default="2.0")
    a = ap.parse_args()
    dest = SNAPSHOTS[a.version]
    new = [g for g, x in data.grid_table().items() if x["since"] == a.version]
    if not new:
        raise SystemExit(f"no grids with since: '{a.version}' in grids.yaml")
    (dest / "eia930").mkdir(parents=True, exist_ok=True)

    listed = {x["eia930_respondent"] for x in data.grid_table().values()}
    for f in sorted(a.source.glob("*.csv.gz")):
        ba = f.name[:-7]
        if ba not in listed and ba not in REGIONS:
            q = quality(f)
            if q["cal_coverage"] >= MIN_COVERAGE and q["run_coverage"] >= MIN_COVERAGE:
                print(f"NOT LISTED but passes the coverage rule: {ba} {q}")

    sums = []
    for g in new:
        ba = data.grid_table()[g]["eia930_respondent"]
        q = quality(a.source / f"{ba}.csv.gz")
        if q["cal_coverage"] < MIN_COVERAGE or q["run_coverage"] < MIN_COVERAGE:
            raise SystemExit(f"{g} ({ba}) fails the coverage rule: {q}")
        out = dest / "eia930" / f"{ba}.csv.gz"
        shutil.copyfile(a.source / f"{ba}.csv.gz", out)
        sums.append(f"{hashlib.sha256(out.read_bytes()).hexdigest()}  eia930/{ba}.csv.gz")
    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n")

    bounds = {g: {f: list(v) for f, v in data.bounds_2019(g, frozen=False).items()} for g in new}
    assert all(set(b) == set(SIGNALS) for b in bounds.values())
    (dest / "bounds_2019.json").write_text(json.dumps(
        {"description": f"0.1st-99.9th percentile of each signal over 2019, rounded to 0.01, frozen for v{a.version} "
                        "(grids added in this release; earlier grids keep their own files).",
         "bounds": bounds}, indent=1) + "\n")

    rows = []
    for g in data.grids(a.version):
        x = data.grid_table()[g]
        rows.append(dict(grid=g, eia930_respondent=x["eia930_respondent"], since=x["since"],
                         **quality(data.snapshot(g) / "eia930" / f"{x['eia930_respondent']}.csv.gz")))
    pd.DataFrame(rows).to_csv(dest / "quality.csv", index=False)
    print(f"v{a.version}: {len(new)} new grids -> {dest.relative_to(ROOT)}; "
          f"flagged: {[r['grid'] for r in rows if r['flat_flag'] or r['shift_flag']]}")


if __name__ == "__main__":
    main()
