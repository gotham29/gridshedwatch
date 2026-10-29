#!/usr/bin/env python3
"""Re-pull EIA-930 D, DF and NG and compare with the frozen snapshot, or pull new balancing authorities.

EIA revises old values, so differences are expected over time; v1.0 is defined by the snapshot
in gridshedwatch/snapshot_v1.0/eia930/. This script reports how much today's API differs, and with --write saves a
fresh pull to a separate folder for a future version. --ba pulls any EIA-930 respondents by code
(--ba all: every respondent EIA lists), for grids not yet in the benchmark. Needs a free key from
https://www.eia.gov/opendata/ in the EIA_API_KEY environment variable.

Usage: EIA_API_KEY=... python scripts/pull_eia930.py [--grid tx ...] [--write data/next/eia930]
       EIA_API_KEY=... python scripts/pull_eia930.py --ba NEVP AZPS ... --write data/next/eia930
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


def respondents(key: str) -> list:
    """Every EIA-930 respondent code (balancing authorities and regions)."""
    url = API.replace("/data/", "/facet/respondent") + "?" + urllib.parse.urlencode({"api_key": key})
    return sorted(f["id"] for f in json.loads(urllib.request.urlopen(url, timeout=120).read())["response"]["facets"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", nargs="+", default=data.grids())
    ap.add_argument("--ba", nargs="+", help="EIA-930 respondent codes to pull, or 'all'")
    ap.add_argument("--write", type=Path)
    a = ap.parse_args()
    key = os.environ.get("EIA_API_KEY")
    if not key:
        raise SystemExit("set EIA_API_KEY (free at https://www.eia.gov/opendata/)")
    if a.ba:
        todo = [(b, b) for b in (respondents(key) if a.ba == ["all"] else a.ba)]
    else:
        todo = [(g, data.events()[g]["eia930_respondent"]) for g in a.grid]
    for g, ba in todo:
        if a.write and (a.write / f"{ba}.csv.gz").exists():
            continue                                    # resume a stopped pull
        try:
            new = pull(ba, key)
        except (KeyError, ValueError) as e:             # respondents without D, DF or NG
            print(f"{ba:5s} skipped: {e}")
            continue
        old_file = data.DATA / "eia930" / f"{ba}.csv.gz"
        if old_file.exists():
            old = pd.read_csv(old_file, index_col="period_utc")
            j = old.join(new, how="outer", lsuffix="_v1", rsuffix="_now")
            diff = {c: int((j[f"{c}_v1"].fillna(-1) != j[f"{c}_now"].fillna(-1)).sum()) for c in ("D", "DF", "NG")}
            print(f"{g:5s} {ba:5s} hours v1 {len(old)}, now {len(new)}; values that differ: {diff}")
        else:
            print(f"{ba:5s} new: {len(new)} hours, {new.index[0]} to {new.index[-1]}", flush=True)
        if a.write:
            a.write.mkdir(parents=True, exist_ok=True)
            new.to_csv(a.write / f"{ba}.csv.gz", compression={"method": "gzip", "mtime": 0})


if __name__ == "__main__":
    main()
