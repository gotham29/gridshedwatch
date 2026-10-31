# GridShedWatch v2.0 scoring protocol

Fixed on 2026-10-29, before any method's v2.0 results were looked at (one exception, below). Any later
change to this file is a deviation and is listed at the end with its date and reason.

## What v2.0 adds

- **Events: 10.** The 8 Tier 1 load sheds of v1.0, unchanged, plus 2 Tier 2 events: NV Energy,
  2020-08-18, and CAISO, 2022-09-06 (`gridshedwatch/events.yaml`, `tier2`). Tier 2 = a strict EEA 3
  for lack of supply, a material action, no operator-directed firm load shed, and an official
  declaration time plus an independent source. The four tests for each candidate are in
  `docs/tier2_candidates.yaml`. Onset = the EEA 3 declaration. Both are held-out events.
- **Why only 2 Tier 2 events.** Reported EEA 3s outside ERCOT (where EEA 3 means controlled outages)
  are few. The Western ones in Aug 2020 and Jan 2024 were published without the balancing authority's
  name (WECC and WIRAB list them as BA1 to BA10). The requests for the names (RC West, NERC, WECC) were
  open when the list was frozen. Names that arrive later go into a v2.1 release, checked by the same
  four tests and scored under this protocol.
- **Grids: 48.** The 8 v1.0 grids, plus every other EIA-930 balancing authority with D, DF and NG for
  at least 90% of the hours in 2019 and in the scored period, after the v1.0 bad-data filter
  (`gridshedwatch/grids.yaml`, `scripts/build_snapshot.py`). Regions and the US total are not grids.
  Excluded by the rule: Homestead (HST), Seminole (SEC), Puget Sound (PSEI), and the respondents with
  partial or no reporting (AEC, BHBA, GVL, JEA, NSB, SWPW). 39 of the 48 grids have no event ("quiet grids").
- **Signals: unchanged.** The v1.0 signal rule applies to every grid with no grid-specific handling.
  v1.0's 8 data files are unchanged (`snapshot_v1.0`); the 40 new ones are in `snapshot_v2.0`.

## Scoring

1. **Operating point.** Each method's v1.0 operating point: the label-free setting chosen on v1.0's 8
   grids for the v1.0 budget (12 watches, 2 warnings per grid-year at the median grid). It is applied
   unchanged to all 48 grids (`benchmark.evaluate_release`).
2. **Tier 1 table.** Exactly the v1.0 table (checked by `tests/test_events.py`).
3. **Tier 2 table.** Events caught per level, median lead time, and the chance baseline. Scored
   separately from Tier 1 and never pooled with it into one count.
4. **False alarm ratio.** Over the 9 grids with events, an alert is verified if it verifies any
   event of either tier.
5. **Alert burden.** Alerts per grid-year, mean over seeds, for all 48 grids, the 39 quiet grids, and
   the quiet grids without a data-quality flag: median, 90th percentile, highest (with its grid), and
   the number of grids above 3x the budget. Burden needs no labels, so it holds even if a quiet grid had
   an emergency nobody published.
6. **Data-quality flags** (`snapshot_v2.0/quality.csv`): flat demand for 48 hours or more (SWPP,
   LDWP, IID), and forecast error outside its 2019 range in at least 25% of scored hours (CHPD, WACM:
   changes in how the forecast was reported). Flagged grids are reported with and without, never
   dropped. `grids.yaml` notes two more facts: WACM and WAUW stop reporting on 2026-04-02, and EPE and
   IID each had a firm load shed below the Tier 1 floor.

## Methods

The nine reference methods, with v1.0's seeds and settings. HTM's v2.0 entry is htm-monitor with
2019 pretraining and learning frozen after 2019, per-seed encoders as in v1.0
(`htm_gsw.py --variant pre_frozen`). It was chosen because it matches the protocol of the LSTM,
gradient-boosted and PatchTST baselines (fit on 2019, then score). The four HTM learning variants
were compared on the 8 v1.0 events only, and are reported as an ablation. v1.0's HTM row stays the
official Tier 1 row.

## Sensitivity analyses, fixed now

- The operating point re-derived over all 48 grids (still label-free).
- Burden with and without flagged grids (above).
- The v1.0 sensitivity variants (budget, windows) on the 10 events.

## Deviations

- 2026-10-29: while testing the scoring code, the seasonal z-score was scored on v2.0 before this
  file was committed. Nothing in this protocol was changed after it.
- 2026-10-30 (a note, not a change): reference scores come from two platforms. LSTM, Chronos and
  v1.0 HTM keep their published v1.0 scores (Linux) on v1.0's grids; every other reference score
  (the new grids for all methods, and all grids for the gradient-boosted, PatchTST, Sub-PCA and
  random baselines) was computed on macOS, and HTM v2.0 in Docker (Linux). Platform effect,
  checked on v1.0's events with LSTM and PatchTST computed both ways: per-hour scores differ
  (different trained weights) but event-level results match (LSTM identical; PatchTST at the same
  operating points, 5.8 vs 6.0 warnings caught, inside its seed range of 5-7).
