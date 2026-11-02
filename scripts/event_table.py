#!/usr/bin/env python3
"""Build the event table (docs/event_table.md): one row per target event, Tier 1 from the package's
events.yaml and Tier 2 from the included candidates in docs/tier2_candidates.yaml, with the highest
level and onset, cause, impact, response and sources. The paper's table comes from the same files.

--figure also draws the per-event figure (docs/img/events_v2.png) from a release's alerts.csv
(scripts/score_release.py): for each event, demand and its day-ahead forecast around onset, the
windows in which a watch or a warning counts, and every method's verified alerts.

It also writes docs/events.csv, the scored events of the release in one table (the Croissant
metadata's event record set).

--events picks some events (by id) for a compact, text-width figure, as in the paper's main text.

Usage: python scripts/event_table.py [--out docs/event_table.md] [--figure [PATH]] [--events ID ...] [--version 2.0]
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import data  # noqa: E402
from gridshedwatch.baselines import HTM_V2, LABEL, METHODS  # noqa: E402
from gridshedwatch.config import WINDOW  # noqa: E402

H = pd.Timedelta(hours=1)


def link(s):
    return f"[{s['publisher']}: {s['title']}]({s['url']})"


def tier1():
    for g, e in yaml.safe_load((ROOT / "gridshedwatch" / "events.yaml").read_text())["events"].items():
        src = e["sources"]
        level = e["onset_basis"].split(";")[0].split("(")[0].strip()
        yield dict(event=f"{e['storm']}, {e['grid']}", tier=1, grid=e["eia930_respondent"], level=level,
                   onset=f"{e['onset_local']} local / {e['onset_utc']} UTC", cause=e["cause"], impact=e["impact"],
                   response=e["response"], note=e.get("note", ""), onset_src=src["onset"],
                   other=[src[k] for k in ("impact", "independent") if src.get(k) and src[k] != src["onset"]])


def tier2():
    for c in yaml.safe_load((ROOT / "docs" / "tier2_candidates.yaml").read_text())["candidates"]:
        if c["decision"] != "include":
            continue
        d, src = c["declared"], c["sources"]
        yield dict(event=f"{c.get('event_name', c['date_local'])}, {c['grid']}", tier=2, grid=c["eia930_respondent"], level=d["level"],
                   onset=f"{d['local']} / {d['utc']} UTC", cause=c["cause"], impact=c["impact"],
                   response=c["response"], note="", onset_src=src[c["onset_source"]],
                   other=[v for k, v in src.items() if k != c["onset_source"]])


def impact(i):
    shed = f"{i['shed_mw']:,} MW firm load shed" if i["shed_mw"] else "no firm load shed"
    return f"{shed}; {i['customers']}; {i['duration']}"


def figure(version: str, path: Path, ids: list = None) -> None:
    """One panel per event: demand vs forecast from 7 days before onset to 2 days after, the scoring
    windows, and each method's verified alert starts (one mark per seed, faint when few seeds agree)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    al = pd.read_csv(ROOT / "results" / f"v{version}" / "alerts.csv")
    label = {**LABEL, "htm": HTM_V2}                    # alerts.csv labels (v2.0 on)
    order = [m for m in METHODS if m != "random"]
    names = [label[m].split(" (")[0] for m in order]          # short names: "HTM", "Chronos-Bolt"
    lo, hi = WINDOW["warning"][0], WINDOW["warning"][1]
    events = sorted(data.event_list(version), key=lambda e: (e["tier"], e["onset"]))
    if ids:
        events = [e for i in ids for e in events if e["id"] == i]
    width = 5.5 if ids else 7.5                                    # NeurIPS text width, or the appendix page
    fig, axes = plt.subplots(len(events), 1, figsize=(width, (2.1 if ids else 1.75) * len(events)), sharex=True, squeeze=False)
    axes = axes[:, 0]
    for ax, e in zip(axes, events):
        w = data.clean_eia930(e["grid"])
        x = w[(w.index >= e["onset"] - lo * H) & (w.index <= e["onset"] + hi * H)]
        h = (x.index - e["onset"]) / H
        ax.axvspan(-lo, 0, color="#e7f1fb")
        ax.axvspan(0, hi, color="#f9eeda")
        ax.axvline(0, color="#c53030", lw=1)
        ax.plot(h, x.D / 1e3, color="#222", lw=1, label="demand")
        ax.plot(h, x.DF / 1e3, color="#888", lw=1, ls="--", label="day-ahead forecast")
        name = f"{e.get('storm') or e['event']}: {e['grid_name']}" + ("" if ids else f", onset {e['onset_local']} local") + \
            (" (Tier 2)" if e["tier"] == 2 else "")
        ax.set_title(name, fontsize=9, loc="left")
        y0, y1 = ax.get_ylim()
        lane = (y1 - y0) / (len(order) + 2)
        ax.set_ylim(y0 - lane * (len(order) + 1), y1)
        for i, m in enumerate(order):
            y = y0 - lane * (i + 1)
            r = al[(al.event == e["id"]) & (al.method == label[m])]
            n = len(METHODS[m][2])
            for lv, mk in (("watch", "o"), ("warning", "^")):
                s = r[r.level == lv]
                ax.scatter(s.h_from_onset, [y] * len(s), marker=mk, s=12, color="#2b6cb0" if lv == "watch" else "#c05621",
                           alpha=min(1.0, 1.5 / n), lw=0)
        ax.set_yticks([y0 - lane * (i + 1) for i in range(len(order))], names, fontsize=6)
        ax.tick_params(axis="y", length=0)
        gw = ax.twinx()                                   # demand scale on the right
        gw.set_ylim(ax.get_ylim())
        gw.set_yticks([t for t in MaxNLocator(3).tick_values(y0, y1) if y0 <= t <= y1])
        gw.set_ylabel("GW", fontsize=7)
        gw.tick_params(labelsize=6)
    axes[0].legend(fontsize=7, loc="upper left", frameon=False)
    axes[-1].set_xlabel("Hours from onset" + ("" if ids else " (blue: watch window; amber: warning window after "
                        "onset; \u25cf watch, \u25b2 warning)"), fontsize=8)
    axes[-1].set_xlim(-lo, hi)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    print(f"figure -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "event_table.md")
    ap.add_argument("--figure", type=Path, nargs="?", const=ROOT / "docs" / "img" / "events_v2.png")
    ap.add_argument("--events", nargs="+", help="event ids for a compact figure (default: every event)")
    ap.add_argument("--version", default="2.0")
    a = ap.parse_args()
    if a.figure:
        figure(a.version, a.figure, a.events)
    rows = sorted(list(tier1()) + list(tier2()), key=lambda r: (r["tier"], r["onset"].split(" ")[0]))
    out = ["# GridShedWatch target events", "",
           "Generated by scripts/event_table.py from gridshedwatch/events.yaml (Tier 1) and the included",
           "candidates in docs/tier2_candidates.yaml (Tier 2). Edit those files, not this one.", "",
           "| # | Event | Tier | Grid (EIA-930) | Highest level, onset | Cause | Impact | Response | Sources |",
           "|---|---|---|---|---|---|---|---|---|"]
    for n, r in enumerate(rows, 1):
        note = f" {r['note']}." if r["note"] else ""
        srcs = "Onset: " + link(r["onset_src"]) + "".join("; " + link(s) for s in r["other"])
        out.append(f"| {n} | {r['event']} | {r['tier']} | {r['grid']} | {r['level']}, {r['onset']} | {r['cause']} | "
                   f"{impact(r['impact'])}.{note} | {'; '.join(r['response'])} | {srcs} |")
    a.out.write_text("\n".join(out) + "\n")
    print(f"{len(rows)} events -> {a.out}")
    ev = pd.DataFrame([dict(id=e["id"], tier=e["tier"], grid=e["grid"], eia930_respondent=e["eia930_respondent"],
                            onset_utc=e["onset_utc"], onset_basis=e["onset_basis"], split=e["split"],
                            since=e["since"]) for e in data.event_list(a.version)])
    ev.to_csv(a.out.parent / "events.csv", index=False)


if __name__ == "__main__":
    main()
