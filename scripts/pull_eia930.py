#!/usr/bin/env python3
"""Re-pull EIA-930 D, DF and NG for the eight v1.0 grids and compare with the frozen snapshot.

EIA revises old values, so differences are expected over time; v1.0 is defined by the snapshot
in data/v1.0/eia930/. This script reports how much today's API differs, and with --write saves a
fresh pull to a separate folder for a future version. Needs a free key from
https://www.eia.gov/opendata/ in the EIA_API_KEY environment variable.

Usage: EIA_API_KEY=... python scripts/pull_eia930.py [--grid tx ...] [--write data/next/eia930]
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import data  # noqa: E402

API = "https://api.eia.gov/v2/electricity/rto/region-data/data/"


def pull(ba: str, key: str) -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        q = [("api_key", key), ("frequency", "hourly"), ("data[0]", "value"), ("facets[respondent][]", ba),
             ("facets[type][]", "D"), ("facets[type][]", "DF"), ("facets[type][]", "NG"),
             ("start", "2019-01-01T00"), ("end", "2026-10-01T00"), ("sort[0][column]", "period"),
             ("sort[0][direction]", "asc"), ("offset", offset), ("length", 5000)]
        d = json.loads(urllib.request.urlopen(API + "?" + urllib.parse.urlencode(q), timeout=120).read())["response"]
        rows += d["data"]
        offset += 5000
        if offset >= int(d["total"]):
            break
        time.sleep(0.2)
    df = pd.DataFrame(rows)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    w = df.pivot_table(index="period", columns="type", values="value", aggfunc="first").sort_index()
    w.index.name = "period_utc"
    return w[["D", "DF", "NG"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", nargs="+", default=data.grids())
    ap.add_argument("--write", type=Path)
    a = ap.parse_args()
    key = os.environ.get("EIA_API_KEY")
    if not key:
        raise SystemExit("set EIA_API_KEY (free at https://www.eia.gov/opendata/)")
    for g in a.grid:
        ba = data.events()[g]["eia930_respondent"]
        new = pull(ba, key)
        old = pd.read_csv(data.DATA / "eia930" / f"{ba}.csv.gz", index_col="period_utc")
        j = old.join(new, how="outer", lsuffix="_v1", rsuffix="_now")
        diff = {c: int((j[f"{c}_v1"].fillna(-1) != j[f"{c}_now"].fillna(-1)).sum()) for c in ("D", "DF", "NG")}
        print(f"{g:5s} {ba:5s} hours v1 {len(old)}, now {len(new)}; values that differ: {diff}")
        if a.write:
            a.write.mkdir(parents=True, exist_ok=True)
            new.to_csv(a.write / f"{ba}.csv.gz", compression={"method": "gzip", "mtime": 0})


if __name__ == "__main__":
    main()
