"""Fixed settings of GridShedWatch v1.0. Changing any of these makes a different benchmark."""
from pathlib import Path

import pandas as pd

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent
# Frozen EIA-930 snapshots, shipped inside the package. Each release adds grids in its own folder;
# grids from earlier releases keep their files unchanged.
SNAPSHOTS = {"1.0": PACKAGE / "snapshot_v1.0", "2.0": PACKAGE / "snapshot_v2.0"}
DATA = SNAPSHOTS["1.0"]

VERSION = "1.0"     # default release for data.grids() and data.event_list()

# Grids added in v2.0: every EIA-930 balancing authority (not a region) with all of D, DF and NG
# for at least MIN_COVERAGE of the hours in 2019 and in the scored period, after the bad-data filter.
MIN_COVERAGE = 0.9
# Data-quality flags (quality.csv; flagged grids are reported with and without, never dropped):
FLAT_FLAG_H = 48            # demand unchanged for at least this many hours in a row
SHIFT_FLAG = 0.25           # forecast error outside its 2019 range in at least this share of scored hours
                            # (a change in how the forecast is reported; demand growth alone is not flagged)

# Scored period (UTC) and calibration year. Methods may learn from 2019; it is never scored.
RUN_START, RUN_END = pd.Timestamp("2020-01-01 00:00"), pd.Timestamp("2026-10-01 00:00")
CAL_START, CAL_END = pd.Timestamp("2019-01-01 00:00"), pd.Timestamp("2019-12-31 23:00")
WARMUP_STEPS = 168          # first week of the run: no alerts are scored

# The five signals every method sees (built from EIA-930 D, DF, NG; see data.py).
SIGNALS = ("forecast_error", "imbalance", "demand_anom", "net_generation_anom", "imbalance_anom")
SEASONAL_LAGS = (168, 336, 504, 672)

# Scoring windows (hours relative to onset): a watch counts in the 7 days before onset;
# a warning also counts up to 48 h after onset.
WINDOW = {"watch": (168, 0), "warning": (168, 48)}

# Alert budgets (episodes per grid per year), chosen without event labels.
BUDGET = {"watch": 12.0, "warning": 2.0}
# Alerts track only: no grid may exceed GRID_CAP x budget (alerts there can be placed grid by grid,
# so a median alone could be met while flooding a few grids). Every reference method's alerts
# meet it (highest single-grid rates in v1.0: 17.7 watches, 5.1 warnings per year).
GRID_CAP = 3.0

# Shared alert rules. Per-signal scores p in [0, 1] -> system alert.
# Watch = rule A (both signal groups hot within 3 h), warning = rule D (within 24 h).
RULE = {
    "watch": {"group_coincidence_window": 3},
    "warning": {"group_coincidence_window": 24},
}
BASE_RULE = {
    "threshold": 0.995,
    "warmth_window": 8,
    "group_k": 2,
    "groups": {
        "structure": {"members": ["demand_anom", "net_generation_anom"], "min_instant_members": 2,
                      "min_group_warmth": 0.45},
        "residual": {"members": ["forecast_error", "imbalance", "imbalance_anom"], "min_instant_members": 1,
                     "min_group_warmth": 0.5},
    },
}

# Settings searched for each method's label-free operating point (matched alert budget).
THRESHOLDS = (0.90, 0.95, 0.98, 0.99, 0.995, 0.999)
PERSISTENCE = {"watch": (3, 4, 6, 8, 12), "warning": (6, 9, 12, 18, 24)}

BOOTSTRAP_DRAWS = 10_000
CHANCE_SHIFTS = 2_000
