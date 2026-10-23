"""Command line: `gridshedwatch <command>`.

  gridshedwatch info                          events, grids, data snapshot
  gridshedwatch signals <grid> -o FILE        the five signals for one grid (CSV)
  gridshedwatch baseline zscore -o DIR        write reference scores in the submission layout
  gridshedwatch score DIR --name NAME         score a method from its per-signal scores
"""
import argparse
import json
import sys

import pandas as pd

from . import benchmark, data, submission
from .config import VERSION


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
        sc = submission.load(a.folder)
        fn, seeds, name = benchmark.from_scores(sc), sorted(sc), a.name or str(a.folder)
    r = benchmark.evaluate(name, fn, seeds, chance=not a.no_chance)
    if a.events:
        r.rows.drop(columns=["starts"]).to_csv(a.events, index=False)
    s = r.summary
    if a.json:
        print(json.dumps(s, indent=2))
        return
    print(f"\n{name}  ({s['seeds']} seed{'s' if s['seeds'] > 1 else ''})")
    for lv in ("watch", "warning"):
        ch = f", chance {s[lv + '_chance_caught']}" if f"{lv}_chance_caught" in s else ""
        print(f"  {lv:8s} {s[lv + '_setting']:24s} caught {s[lv + '_caught_all']} of 8 [{s[lv + '_caught_all_ci']}]{ch}; "
              f"held-out {s[lv + '_caught_held_out']} of 5; median lead {s[lv + '_median_lead_h']} h; "
              f"{s[lv + '_alerts_per_grid_year']} alerts/grid/yr; false alarm ratio {s[lv + '_false_alarm_ratio']:.0%}")


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
    p.set_defaults(fn=_score)
    a = ap.parse_args(argv)
    if a.cmd == "score" and not (a.folder or a.oprule):
        ap.error("score needs a folder of scores or --oprule")
    a.fn(a)


if __name__ == "__main__":
    main()
