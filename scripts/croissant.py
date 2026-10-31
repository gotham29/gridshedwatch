#!/usr/bin/env python3
"""Write the Croissant metadata of a release (croissant.json), with its Responsible AI fields.

Three record sets: the scored events (docs/events.csv, from scripts/event_table.py), the grids with
their data-quality flags (snapshot_v<version>/quality.csv), and the hourly EIA-930 data of every grid
(all snapshot folders up to the release). Files are addressed in the GitHub repository at --ref (the
release tag once it exists), the convention Croissant uses for files inside a git repository.
The RAI text summarizes docs/datasheet.md, which has the details.

Usage: python scripts/croissant.py [--version 2.0] [--ref main] [--out croissant.json]
Check: mlcroissant validate --jsonld croissant.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import data  # noqa: E402

REPO = "https://github.com/gotham29/gridshedwatch"
DOI = "https://doi.org/10.5281/zenodo.23626223"
CONTEXT = {
    "@language": "en", "@vocab": "https://schema.org/", "sc": "https://schema.org/",
    "cr": "http://mlcommons.org/croissant/", "rai": "http://mlcommons.org/croissant/RAI/",
    "dct": "http://purl.org/dc/terms/", "citeAs": "cr:citeAs", "column": "cr:column",
    "conformsTo": "dct:conformsTo", "data": {"@id": "cr:data", "@type": "@json"},
    "dataType": {"@id": "cr:dataType", "@type": "@vocab"}, "examples": {"@id": "cr:examples", "@type": "@json"},
    "extract": "cr:extract", "field": "cr:field", "fileProperty": "cr:fileProperty", "fileObject": "cr:fileObject",
    "fileSet": "cr:fileSet", "format": "cr:format", "includes": "cr:includes", "isLiveDataset": "cr:isLiveDataset",
    "jsonPath": "cr:jsonPath", "key": "cr:key", "md5": "cr:md5", "parentField": "cr:parentField", "path": "cr:path",
    "recordSet": "cr:recordSet", "references": "cr:references", "regex": "cr:regex", "repeated": "cr:repeated",
    "replace": "cr:replace", "separator": "cr:separator", "source": "cr:source", "subField": "cr:subField",
    "transform": "cr:transform", "samplingRate": "cr:samplingRate", "equivalentProperty": "cr:equivalentProperty",
}
RAI = {
    "rai:dataCollection": "Hourly demand, day-ahead demand forecast and net generation for each balancing authority "
        "were pulled from the EIA Open Data API (EIA-930) in October 2026 and frozen with SHA-256 checksums. Events "
        "and onset times were compiled by hand from operators' post-event reports and regulatory filings, NERC and "
        "FERC-NERC reports, and DOE OE-417 incident reports; every onset cites an official source and an independent "
        "second source.",
    "rai:dataCollectionType": ["Secondary Data Analysis", "Manual Human Curator"],
    "rai:dataCollectionTimeframe": ["2019-01-01", "2026-10-01"],
    "rai:dataPreprocessingProtocol": "Hours missing any of demand, forecast or net generation, or failing a bad-data "
        "filter set from 2019 (values at or below zero, or above twice the 2019 99.9th percentile), are dropped. Five "
        "signals are derived by one fixed rule: forecast error, imbalance, and seasonal anomalies of demand, net "
        "generation and imbalance. Grids need 90% coverage in 2019 and in 2020-2026; flat-demand and forecast-reporting "
        "flags are recorded, not used to drop grids.",
    "rai:dataAnnotationProtocol": "The only labels are event onset times. An event qualifies by a rule fixed in "
        "advance: Tier 1, an operator-initiated firm load shed of at least 250 MW caused by insufficient supply; "
        "Tier 2, an EEA 3 (NERC definition) for lack of supply with a documented emergency action and no firm load "
        "shed. Onset is the emergency declaration time; where it is unpublished, a fallback fixed in advance moves "
        "onset earlier, never later. Every candidate checked and every exclusion is recorded with its reason "
        "(docs/events.md, docs/tier2_candidates.yaml).",
    "rai:annotationsPerItem": "One onset per event, set by the author from cited sources; Tier 1 onsets were "
        "re-checked against their official documents.",
    "rai:dataLimitations": "Ten events, seven from two winter storms (Uri, Elliott); US balancing authorities "
        "reporting to EIA-930 only; hourly totals, so events in a small part of a large balancing authority are "
        "diluted; no weather or unit-outage data. Events are a complete case series under the rule, not a sample, "
        "so detection rates do not estimate operational performance. The replay treats each hourly value as "
        "available at its time stamp; live EIA-930 data arrive with a delay.",
    "rai:dataBiases": "Heat-driven and other non-winter shortfalls are underrepresented. Three Tier 1 events were "
        "used to design the shared alert rules, so results on them are not independent tests. Pretrained models may "
        "have seen public EIA-930 data. One reference method (HTM, via htm-monitor) is the author's own; it is scored "
        "by the same code as the others.",
    "rai:personalSensitiveInformation": "None. All data are aggregate grid totals and public reports.",
    "rai:dataUseCases": "Intended: comparing early-warning methods for supply-shortfall grid emergencies on public "
        "data at matched alert budgets, including lead time and false-alarm burden on grids without events. Not "
        "intended: estimating operational detection rates, detecting transmission or distribution failures, ranking "
        "methods on differences of about one event, or replacing operators' situational awareness.",
    "rai:dataSocialImpact": "Better early warning of supply shortfalls could give operators and the public more time "
        "to prepare for emergencies that have cost lives (at least 210 deaths in Uri). The benchmark is not an "
        "operational tool; a method that does well here has been tested on few events and on public data only.",
    "rai:hasSyntheticData": False,
    "rai:dataReleaseMaintenancePlan": "Versioned releases archived on Zenodo; each release freezes its events, data "
        "and scoring, and earlier versions stay reproducible from their tags. New qualifying events enter a new "
        "version scored with the frozen rules; corrections are made in a new version with the change and its source "
        "recorded. Maintained by the author through GitHub issues and pull requests.",
}


def field(rs, name, desc, dtype, src, extract=None, transform=None):
    s = {"fileSet" if src.endswith("files") else "fileObject": {"@id": src}, "extract": extract or {"column": name}}
    if transform:
        s["transform"] = transform
    return {"@type": "cr:Field", "@id": f"{rs}/{name}", "name": name, "description": desc, "dataType": dtype, "source": s}


def build(version: str, ref: str) -> dict:
    snaps = sorted({data.snapshot(g).name for g in data.grids(version)})
    ev = data.event_list(version)
    t1, t2 = sum(e["tier"] == 1 for e in ev), sum(e["tier"] == 2 for e in ev)
    files = [
        {"@type": "cr:FileObject", "@id": "repo", "name": "repo", "description": "The GridShedWatch repository.",
         "contentUrl": f"{REPO}/tree/{ref}", "encodingFormat": "git+https",
         "sha256": "https://github.com/mlcommons/croissant/issues/80"},
        {"@type": "cr:FileObject", "@id": "events-csv", "name": "events-csv", "containedIn": {"@id": "repo"},
         "contentUrl": "docs/events.csv", "encodingFormat": "text/csv",
         "description": "The scored events of the release (from gridshedwatch/events.yaml and docs/tier2_candidates.yaml)."},
        {"@type": "cr:FileObject", "@id": "quality-csv", "name": "quality-csv", "containedIn": {"@id": "repo"},
         "contentUrl": f"gridshedwatch/snapshot_v{version}/quality.csv", "encodingFormat": "text/csv",
         "description": "Every grid of the release with its coverage and data-quality flags."},
        {"@type": "cr:FileSet", "@id": "eia930-files", "name": "eia930-files", "containedIn": {"@id": "repo"},
         "encodingFormat": "text/csv", "includes": [f"gridshedwatch/{s}/eia930/*.csv.gz" for s in snaps],
         "description": "Frozen hourly EIA-930 data, one gzipped CSV per balancing authority; checksums in each "
                        "snapshot folder's SHA256SUMS."},
    ]
    E, Q, D = "events", "grids", "eia930"
    records = [
        {"@type": "cr:RecordSet", "@id": E, "name": E, "key": {"@id": f"{E}/id"},
         "description": f"{t1} Tier 1 load sheds and {t2} Tier 2 EEA 3 emergencies; onset times are the only labels.",
         "field": [field(E, "id", "Event id.", "sc:Text", "events-csv"),
                   field(E, "tier", "1: firm load shed; 2: EEA 3 without firm load shed.", "sc:Integer", "events-csv"),
                   field(E, "grid", "Grid id (see the grids record set).", "sc:Text", "events-csv"),
                   field(E, "eia930_respondent", "EIA-930 balancing authority code.", "sc:Text", "events-csv"),
                   field(E, "onset_utc", "Onset, UTC (emergency declaration or fixed fallback).", "sc:Text", "events-csv"),
                   field(E, "onset_basis", "What the onset time is and where it comes from.", "sc:Text", "events-csv"),
                   field(E, "split", "development or held-out.", "sc:Text", "events-csv"),
                   field(E, "since", "Release that added the event.", "sc:Text", "events-csv")]},
        {"@type": "cr:RecordSet", "@id": Q, "name": Q, "key": {"@id": f"{Q}/grid"},
         "description": "Grids of the release (one balancing authority each) with coverage and data-quality flags.",
         "field": [field(Q, "grid", "Grid id.", "sc:Text", "quality-csv"),
                   field(Q, "eia930_respondent", "EIA-930 balancing authority code.", "sc:Text", "quality-csv"),
                   field(Q, "since", "Release that added the grid.", "sc:Text", "quality-csv"),
                   field(Q, "run_coverage", "Share of 2020-2026 hours kept.", "sc:Float", "quality-csv"),
                   field(Q, "flat_flag", "Demand unchanged for 48 h or more.", "sc:Boolean", "quality-csv"),
                   field(Q, "shift_flag", "Forecast error outside its 2019 range in at least 25% of hours.",
                         "sc:Boolean", "quality-csv")]},
        {"@type": "cr:RecordSet", "@id": D, "name": D,
         "description": "Hourly EIA-930 totals per balancing authority, Jan 2019 to Oct 2026, UTC.",
         "field": [field(D, "eia930_respondent", "Balancing authority code, from the file name.", "sc:Text",
                         "eia930-files", extract={"fileProperty": "filename"},
                         transform={"regex": "^([A-Z0-9]+)\\.csv\\.gz$"}),
                   field(D, "period_utc", "Hour, UTC (YYYY-MM-DDTHH).", "sc:Text", "eia930-files"),
                   field(D, "D", "Demand, MWh.", "sc:Float", "eia930-files"),
                   field(D, "DF", "Day-ahead demand forecast, MWh.", "sc:Float", "eia930-files"),
                   field(D, "NG", "Net generation, MWh.", "sc:Float", "eia930-files")]},
    ]
    return {
        "@context": CONTEXT, "@type": "sc:Dataset", "conformsTo": "http://mlcommons.org/croissant/1.0",
        "name": "GridShedWatch",
        "description": f"A benchmark for early warning of US grid supply-shortfall emergencies: {len(ev)} documented "
                       f"events (v{version}), frozen hourly EIA-930 data for {len(data.grids(version))} balancing "
                       "authorities, and fixed event-level scoring at matched alert budgets.",
        "version": f"{version}.0", "datePublished": "2026-10-23", "url": REPO, "sameAs": DOI,
        "license": ["https://creativecommons.org/licenses/by/4.0/", "https://opensource.org/licenses/MIT"],
        "creator": {"@type": "sc:Person", "name": "Sam Heiserman", "email": "sam@htm-monitor.com"},
        "citeAs": f"Heiserman, S. (2026). GridShedWatch: a benchmark for early warning of grid load sheds. {DOI}",
        "keywords": ["power grid", "early warning", "anomaly detection", "benchmark", "EIA-930", "load shed"],
        "isLiveDataset": False, **RAI, "distribution": files, "recordSet": records,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="2.0")
    ap.add_argument("--ref", default="main", help="git ref the file paths refer to (the release tag once made)")
    ap.add_argument("--out", type=Path, default=ROOT / "croissant.json")
    a = ap.parse_args()
    a.out.write_text(json.dumps(build(a.version, a.ref), indent=1) + "\n")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
