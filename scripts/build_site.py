"""Build the GridShedWatch website (docs/index.html) from the final results and the event files.

    python scripts/build_site.py

Everything the page shows comes from results/v3.0/ and the package's events.yaml and
operator_notices.yaml; the layout lives in scripts/site_template.html. The link-preview
image docs/og.png is a screenshot of scripts/og/card.html at 1200x630 (update its numbers by hand
if the results change).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gridshedwatch import data
from gridshedwatch.config import WINDOW

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "v3.0"
H = pd.Timedelta(hours=1)

METHODS = [  # code, display name, family (the 11 reference methods, then the weather control)
    ("gbm", "LightGBM", "Forecaster"), ("lstm", "LSTM", "Forecaster"), ("htm", "HTM", "Sequence memory"),
    ("patchtst", "PatchTST", "Forecaster"), ("chronos", "Chronos-Bolt", "Foundation model"),
    ("cusum", "CUSUM", "Statistics"), ("zscore", "Seasonal z-score", "Statistics"),
    ("oprule", "Operator-style rule", "Rules"), ("csd", "Critical slowing down", "Statistics"),
    ("subpca", "Sub-PCA", "Detector"), ("random", "Random scores", "Floor"),
    ("dfanom", "Forecast-anomaly control", "Weather control"),
]


def num(x):
    return None if pd.isna(x) else float(x)


def ci(s):
    if pd.isna(s):
        return None
    a, b = str(s).split("-")
    return [float(a), float(b)]


def leaderboard():
    sm = pd.read_csv(RES / "summary.csv").set_index("code")
    out = []
    for code, name, fam in METHODS:
        r = sm.loc[code]
        m = {"id": code, "name": name, "family": fam, "seeds": int(r.seeds)}
        for lv, key in (("watch", "watch"), ("warning", "warning_pre")):      # warnings: before onset
            lo, hi = ci(r[f"{key}_ci"]) or (None, None)
            m[lv] = {"caught": num(r[f"{key}_caught"]), "ci": None if lo is None else [round(8 * lo, 1), round(8 * hi, 1)],
                     "held_out": num(r[f"{key}_held_out"]), "lead": num(r[f"{lv}_median_lead_h"]),
                     "far": num(r[f"{lv}_far"]), "chance": num(r[f"{key}_chance_season"]),
                     "chance_p": num(r.get(f"{key}_p_season_holm", r[f"{key}_p_season"])),
                     "rate": num(r[f"{lv}_burden_median"]), "setting": None}
        out.append(m)
    ln = pd.read_csv(RES / "lead_vs_notice.csv").drop_duplicates("event").set_index("event").notice_lead_h
    held = {e["id"] for e in data.event_list("2.0") if e["tier"] == 1 and e["split"] == "held-out"}
    return out, {"caught": float(ln.notna().sum()), "held_out": float(ln[ln.index.isin(held)].notna().sum()),
                 "lead": num(ln.median())}


def per_event():
    """Share of seeds that caught each event, and the median lead among catches; operators' public notices."""
    ev = pd.read_csv(RES / "events.csv")
    cells = {}
    for code, name, _ in METHODS:
        d = ev[(ev.method == pd.read_csv(RES / "summary.csv").set_index("code").loc[code, "method"]) & (ev.tier == 1)]
        for _, x in d.iterrows():
            frac = x.caught_pre if x.level == "warning" else x.caught
            cells[f"{code}|{x.event}|{x.level}"] = {"frac": round(float(frac), 2), "n": 1,
                                                   "lead": None if pd.isna(x.lead_h) else round(float(x.lead_h), 0)}
    ln = pd.read_csv(RES / "lead_vs_notice.csv").drop_duplicates("event").set_index("event").notice_lead_h
    for g, v in ln.items():
        cells[f"operators|{g}|watch"] = {"frac": 0.0 if pd.isna(v) else 1.0, "n": 1, "lead": None if pd.isna(v) else round(float(v), 0)}
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
