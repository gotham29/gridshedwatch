#!/usr/bin/env python3
"""Render the reference methods' comparison table (what `gridshedwatch score` prints new methods beside)
as the README table, between the leaderboard markers, with the weather control below it."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gridshedwatch import protocol  # noqa: E402


def main():
    t = protocol.comparison()
    cols = list(t.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, x in t.iterrows():
        lines.append("| " + " | ".join("yes" if v is True else "no" if v is False else f"{v:g}" if isinstance(v, float)
                                       else str(v) for v in x) + " |")
    s_all = pd.read_csv(ROOT / "results" / "v3.0" / "summary.csv").set_index("code")
    note = ("\nTier 1 load sheds, mean over seeds. *By chance*: the same alerts moved to random times in the same "
            "season; *p*: Holm-corrected over the 11 methods. Listed by watches caught; 8 events cannot rank the "
            "leading methods.")
    for c, what in (("dfanom", "how unusual the grid's own day-ahead forecast is for the season"),
                    ("dflevel", "the grid's own day-ahead forecast level")):
        if c in s_all.index:
            d = s_all.loc[c]
            note += (f" Weather control ({what}): {d.watch_caught:g} watches, {d.watch_chance_season:.2f} by chance, "
                     f"{d.warning_pre_caught:g} warnings before onset.")
    table = "\n".join(lines) + "\n" + note
    p = ROOT / "README.md"
    s = p.read_text()
    a, b = s.index("<!-- leaderboard:start -->"), s.index("<!-- leaderboard:end -->")
    p.write_text(s[:a] + "<!-- leaderboard:start -->\n" + table + "\n" + s[b:])


if __name__ == "__main__":
    main()
