"""Build the GridShedWatch website (docs/index.html) from the v1.0 results and the event files.

    python scripts/build_site.py

Everything the page shows comes from results/v1.0/ and the package's events.yaml and
operator_notices.yaml; the layout lives in scripts/site_template.html. The link-preview
image docs/og.png is a screenshot of scripts/og/card.html at 1200x630 (update its numbers by hand
if the results change).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gridshedwatch import benchmark, data
from gridshedwatch.config import WINDOW

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "v1.0"
H = pd.Timedelta(hours=1)

METHODS = [  # file stem, display name, family
    ("oprule", "Operator-style rule", "Rules"),
    ("zscore", "Seasonal z-score", "Statistics"),
    ("lstm", "LSTM forecaster", "Machine learning"),
    ("htm", "HTM (htm-monitor)", "Machine learning"),
    ("chronos", "Chronos-Bolt (zero-shot)", "Foundation model"),
]


def num(x):
    return None if pd.isna(x) else float(x)


def ci(s):
    if pd.isna(s):
        return None
    a, b = str(s).split("-")
    return [float(a), float(b)]


def leaderboard():
    lb = pd.read_csv(RES / "leaderboard.csv").set_index("method")
    out = []
    for stem, name, fam in METHODS:
        r = lb.loc[name]
        m = {"id": stem, "name": name, "family": fam, "seeds": int(r.seeds)}
        for lv in ("watch", "warning"):
            m[lv] = {"caught": num(r[f"{lv}_caught_all"]), "ci": ci(r[f"{lv}_caught_all_ci"]),
                     "held_out": num(r[f"{lv}_caught_held_out"]), "lead": num(r[f"{lv}_median_lead_h"]),
                     "far": num(r[f"{lv}_false_alarm_ratio"]), "chance": num(r[f"{lv}_chance_caught"]),
                     "chance_p": num(r[f"{lv}_chance_p"]), "rate": num(r[f"{lv}_alerts_per_grid_year"]),
                     "setting": r[f"{lv}_setting"]}
        out.append(m)
    op = lb.loc["Operators (public notices)"]
    return out, {"caught": num(op.watch_caught_all), "held_out": num(op.watch_caught_held_out),
                 "lead": num(op.watch_median_lead_h)}


def per_event():
    """Fraction of seeds that caught each event, and the median lead among catches."""
    cells = {}
    for stem, _, _ in METHODS:
        d = pd.read_csv(RES / f"{stem}_events.csv")
        for (g, lv), x in d.groupby(["grid", "level"]):
            lead = x.loc[x.caught, "lead_h"].dropna()   # NaN: caught only after onset (warnings)
            cells[f"{stem}|{g}|{lv}"] = {"frac": round(float(x.caught.mean()), 2), "n": int(len(x)),
                                         "lead": None if lead.empty else round(float(lead.median()), 0)}
    sq = benchmark.status_quo()["by_grid"]
    for g, e in data.operator_notices().items():
        on = data.onset(g)
        pre = [pd.Timestamp(n["utc"]) for n in e["notices"] if n.get("public")]
        pre = [t for t in pre if on - WINDOW["watch"][0] * H <= t < on]
        cells[f"operators|{g}|watch"] = {"frac": 1.0 if sq[g] else 0.0, "n": 1,
                                         "lead": round((on - min(pre)) / H, 0) if pre else None}
    return cells


def local_str(on, tz):
    t = on.tz_localize("UTC").tz_convert(tz)
    h = t.strftime("%I").lstrip("0") + t.strftime(":%M") + (" a.m." if t.hour < 12 else " p.m.")
    return f"{t.strftime('%b')} {t.day} {t.year}, {h} {t.tzname()}"


def events():
    ev, notes = data.events(), data.operator_notices()
    out = []
    for g, e in ev.items():
        on = data.onset(g)
        n = notes[g]
        out.append({
            "grid": g, "name": e["grid"], "storm": e["storm"], "title": n["title"], "when": n["when"],
            "tagline": n["tagline"], "shed_mw": e["max_shed_mw"], "split": e["split"],
            "onset_utc": str(on), "onset_local": local_str(on, e["local_tz"]), "onset_basis": e["onset_basis"], "onset_label": n["onset_label"], "onset_source": n["onset_source"],
            "notices": [{"h": round((pd.Timestamp(x["utc"]) - on) / H, 1), "label": x["label"],
                         "by": x.get("by", "operator"), "public": bool(x.get("public")),
                         "approx": bool(x.get("approx"))} for x in n["notices"]],
            "sources": n.get("sources", []),
        })
    return out


def main():
    methods, ops = leaderboard()
    payload = {"methods": methods, "operators": ops, "cells": per_event(), "events": events(),
               "window": WINDOW}
    tpl = (ROOT / "scripts" / "site_template.html").read_text()
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    (ROOT / "docs" / "index.html").write_text(html)
    (ROOT / "docs" / ".nojekyll").write_text("")
    print("wrote docs/index.html", len(html) // 1024, "KB")


if __name__ == "__main__":
    main()
