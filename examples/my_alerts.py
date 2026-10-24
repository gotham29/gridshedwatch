#!/usr/bin/env python3
"""Template: score a method that raises its own alerts (alerts track).

Any method that decides when to raise a watch or a warning can be scored: write one row per
alert episode (grid, level, start_utc[, seed]) and run `gridshedwatch score-alerts`. Use data up
to the alert's time only, and stay within the budget (about 12 watches and 2 warnings per grid
per year, and no grid above 3 times that). Here, as a placeholder, a watch starts when demand's
excess over its day-ahead forecast has been above its 2019 99th percentile for 3 hours in a row,
and a warning when above its 2019 99.9th percentile for 6 hours. A quiet period after each alert
(31 days for watches, 183 for warnings) keeps it within the budget on every grid.
Replace `my_alerts` with your method; it may use any data, including weather.

Run:  python examples/my_alerts.py && gridshedwatch score-alerts my_alerts.csv --name "My rule"
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gridshedwatch import alerts, data  # noqa: E402

RULE = {"watch": (0.99, 3, 31), "warning": (0.999, 6, 183)}   # (2019 percentile, hours in a row, quiet days)


def my_alerts(grid: str) -> list:
    w = data.clean_eia930(grid)                          # hourly D, DF, NG (UTC)
    excess = (w.D - w.DF) / w.DF
    cal = excess[excess.index.year == 2019]              # learn the threshold from 2019 only
    lo, hi = alerts.scored_period(grid)
    excess = excess[(excess.index >= lo) & (excess.index <= hi)]
    rows = []
    for level, (q, hours, quiet) in RULE.items():
        on = excess > cal.quantile(q)
        run = on.groupby((~on).cumsum()).cumsum()       # hours in a row above the threshold
        last = None
        for t in run.index[run == hours]:                # the alert comes on after `hours` hours
            if last is None or t - last >= pd.Timedelta(days=quiet):
                rows.append(dict(grid=grid, level=level, start_utc=t.strftime("%Y-%m-%d %H:%M")))
                last = t
    return rows


if __name__ == "__main__":
    df = pd.DataFrame([r for g in data.grids() for r in my_alerts(g)])
    alerts.write(df, "my_alerts.csv")
    print(f"wrote my_alerts.csv ({len(df)} alerts); now: gridshedwatch score-alerts my_alerts.csv --name 'My rule'")
