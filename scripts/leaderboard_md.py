#!/usr/bin/env python3
"""Render results/v1.0/leaderboard.csv as the README table (between the leaderboard markers)."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def cell(x, ci=None):
    if pd.isna(x):
        return "-"
    s = f"{x:g}"
    return f"{s} [{ci}]" if isinstance(ci, str) else s


def main():
    S = pd.read_csv(ROOT / "results" / "v1.0" / "leaderboard.csv")
    lines = ["| Method | Watches: caught (of 8) | held-out (of 5) | by chance | median lead (h) | "
             "Warnings: caught (of 8) | held-out (of 5) | by chance | False alarm ratio (watch / warning) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for _, x in S.iterrows():
        far = "-" if pd.isna(x.get("watch_false_alarm_ratio")) else \
            f"{x.watch_false_alarm_ratio:.0%} / {x.warning_false_alarm_ratio:.0%}"
        lines.append(f"| {x['method']} | {cell(x.watch_caught_all, x.get('watch_caught_all_ci'))} | "
                     f"{cell(x.watch_caught_held_out)} | {cell(x.get('watch_chance_caught'))} | {cell(x.watch_median_lead_h)} | "
                     f"{cell(x.get('warning_caught_all'), x.get('warning_caught_all_ci'))} | {cell(x.get('warning_caught_held_out'))} | "
                     f"{cell(x.get('warning_chance_caught'))} | {far} |")
    lines.append("")
    lines.append("Mean over 5 seeds for the LSTM and HTM. [a-b]: 5th-95th percentile with events resampled. "
                 "Operators: public notices in the 7 days before onset, scored as watches.")
    table = "\n".join(lines)
    p = ROOT / "README.md"
    s = p.read_text()
    a, b = s.index("<!-- leaderboard:start -->"), s.index("<!-- leaderboard:end -->")
    p.write_text(s[:a] + "<!-- leaderboard:start -->\n" + table + "\n" + s[b:])
    print(table)


if __name__ == "__main__":
    main()
