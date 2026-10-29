"""Command line: `gridshedwatch <command>`.

  gridshedwatch info                          events, grids, data snapshot
  gridshedwatch signals <grid> -o FILE        the five signals for one grid (CSV)
  gridshedwatch baseline zscore -o DIR        write reference scores in the submission layout
  gridshedwatch score DIR --name NAME         scores track: score a method from its per-signal scores
  gridshedwatch score DIR --version 2.0       the same at the v1.0 operating point on every v2.0 grid
  gridshedwatch score-alerts FILE --name NAME  alerts track: score a method's watch/warning start times
"""
import argparse
import json
import sys

import pandas as pd

from . import alerts, benchmark, data, submission
from .config import BUDGET, GRID_CAP, VERSION


def _info(a):
    ev = data.events()
    print(f"GridShedWatch v{VERSION}: {len(ev)} events")
    for g, e in ev.items():
        tb = data.timebase(g)
        print(f"  {g:5s} {e['grid']:28s} {e['storm']:20s} onset {e['onset_utc']} UTC  {e['split']:11s} {len(tb)} steps")


def _signals(a):
    data.signals(a.grid).to_csv(a.output, index=False)
    print(f"wrote {a.output}")


def _baseline(a):
    if a.method == "zscore":
        from .baselines import zscore
        sc = {0: {g: zscore.scores(g) for g in data.grids()}}
    elif a.method == "lstm":
        from .baselines import lstm
        sc = {k: {g: lstm.scores(g, k, a.threads) for g in data.grids()} for k in a.seeds}
    elif a.method == "chronos":
        from .baselines import chronos
        sc = {0: {g: chronos.scores(g, device=a.device) for g in data.grids()}}
    else:
        sys.exit("operator-style rule has no per-signal scores; use `gridshedwatch score --oprule`")
    submission.write(sc, a.output)
    print(f"wrote {a.output}")


def _score(a):
    if a.oprule:
        from .baselines import oprule
        fn, seeds, name = oprule.alerts, [0], a.name or "Operator-style rule"
    else:
        sc = submission.load(a.folder, a.version)
        fn, seeds, name = benchmark.from_scores(sc), sorted(sc), a.name or str(a.folder)
    if a.version != "1.0":
        r = benchmark.evaluate_release(name, fn, seeds, a.version, chance=not a.no_chance)
        return _report_release(a, r)
    r = benchmark.evaluate(name, fn, seeds, chance=not a.no_chance)
    if a.alerts_out:
        alerts.write(alerts.from_rows(r.rows), a.alerts_out)
        print(f"wrote the alerts at the operating point to {a.alerts_out}")
    _report(a, r)


def _score_alerts(a):
    r = benchmark.evaluate_alerts(a.name or str(a.file), alerts.load(a.file), chance=not a.no_chance)
    _report(a, r)
    over = [lv for lv in ("watch", "warning") if not r.summary[f"{lv}_within_budget"]]
    if over and not a.json:
        for lv in over:
            print(f"\n  OVER BUDGET ({lv}): the median grid must be at most {BUDGET[lv]:g} alerts/yr and every grid at most "
                  f"{GRID_CAP * BUDGET[lv]:g}/yr; this entry has median {r.summary[lv + '_median_grid_rate']} and "
                  f"highest {r.summary[lv + '_max_grid_rate']}. Not comparable with the table until reduced.")


def _report(a, r):
    if a.events:
        r.rows.drop(columns=["starts"]).to_csv(a.events, index=False)
    s = r.summary
    if a.json:
        print(json.dumps(s, indent=2, default=lambda v: None))
        return
    name = s["method"]
    print(f"\n{name}  ({s['seeds']} seed{'s' if s['seeds'] > 1 else ''})")
    for lv in ("watch", "warning"):
        ch = f", chance {s[lv + '_chance_caught']}" if f"{lv}_chance_caught" in s else ""
        far = s[lv + '_false_alarm_ratio']
        far = "n/a" if far != far else f"{far:.0%}"
        print(f"  {lv:8s} {s[lv + '_setting']:24s} caught {s[lv + '_caught_all']} of 8 [{s[lv + '_caught_all_ci']}]{ch}; "
              f"held-out {s[lv + '_caught_held_out']} of 5; median lead {s[lv + '_median_lead_h']} h; "
              f"{s[lv + '_alerts_per_grid_year']} alerts/grid/yr; false alarm ratio {far}")


def _report_release(a, r):
    if a.events:
        r.rows.drop(columns=["starts"]).to_csv(a.events, index=False)
    s = r.summary
    if a.json:
        print(json.dumps(s, indent=2, default=lambda v: None))
        return
    print(f"\n{s['method']}  ({s['seeds']} seed{'s' if s['seeds'] > 1 else ''}), v{s['version']} at the v1.0 operating point")
    for lv in ("watch", "warning"):
        print(f"  {lv:8s} {s['tier1_' + lv + '_setting']:24s} Tier 1 caught {s['tier1_' + lv + '_caught_all']} of 8; "
              f"Tier 2 caught {s['tier2_' + lv + '_caught_all']} of 2; false alarm ratio, all events "
              f"{s['all_' + lv + '_false_alarm_ratio']:.0%}")
        for g in ("all", "quiet", "quiet_unflagged"):
            k = f"burden_{g}_{lv}"
            print(f"           alerts/grid/yr, {g.replace('_', ' ')} grids ({s[k + '_grids']}): median {s[k + '_median']}, "
                  f"90th pct {s[k + '_p90']}, highest {s[k + '_max']} ({s[k + '_max_grid']}); over cap: {s[k + '_over_cap']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gridshedwatch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info").set_defaults(fn=_info)
    p = sub.add_parser("signals")
    p.add_argument("grid", choices=data.grids())
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(fn=_signals)
    p = sub.add_parser("baseline")
    p.add_argument("method", choices=["zscore", "lstm", "chronos"])
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--device", default="cpu")
    p.set_defaults(fn=_baseline)
    p = sub.add_parser("score")
    p.add_argument("folder", nargs="?")
    p.add_argument("--name")
    p.add_argument("--oprule", action="store_true", help="score the built-in operator-style rule")
    p.add_argument("--no-chance", action="store_true")
    p.add_argument("--events", help="also write per-event rows to this CSV")
    p.add_argument("--json", action="store_true")
    p.add_argument("--alerts-out", help="also write the alerts at the operating point, in the alerts-track format")
    p.add_argument("--version", default="1.0", choices=["1.0", "2.0"], help="release to score (2.0: every v2.0 grid)")
    p.set_defaults(fn=_score)
    p = sub.add_parser("score-alerts")
    p.add_argument("file", help="CSV with grid, level, start_utc[, seed] (see gridshedwatch/alerts.py)")
    p.add_argument("--name")
    p.add_argument("--no-chance", action="store_true")
    p.add_argument("--events", help="also write per-event rows to this CSV")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=_score_alerts)
    a = ap.parse_args(argv)
    if a.cmd == "score" and not (a.folder or a.oprule):
        ap.error("score needs a folder of scores or --oprule")
    a.fn(a)


if __name__ == "__main__":
    main()
