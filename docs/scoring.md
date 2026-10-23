# GridShedWatch v1.0: scoring

GridShedWatch scores a warning method the way the US National Weather Service scores its
warnings: did the alert come before the event, how much notice did it give, and how often did
it cry wolf. All settings below are in `gridshedwatch/config.py`; changing one makes a
different benchmark.

## What a method sees and produces

- **Input:** five hourly signals per grid, built from public EIA-930 demand (D), day-ahead
  demand forecast (DF) and net generation (NG) by one rule for every grid
  (`gridshedwatch/data.py`): forecast error (D - DF), imbalance (D - NG), and seasonal
  anomalies of D, NG and D - NG (value minus the median of the same hour 1-4 weeks earlier).
  Hours failing a 2019 bad-data filter are dropped. No weather, outage or market data.
- **Period:** run hour by hour from 2020-01-01 to 2026-10-01 UTC, seeing only the past. 2019
  is available for calibration and is never scored. The first week of the run (168 steps) is
  warm-up: no alert counts.
- **Output:** for every step and signal, a score p in [0, 1], how unusual that signal is now.
  Any monotone anomaly score works if it is mapped to [0, 1]; the reference methods use the
  causal empirical CDF of their raw scores (`baselines.to_p`).

## The shared alert rules

Every method's scores pass through the same rule (`gridshedwatch/rules.py`), so methods differ
only in how they score each hour.

- A signal is hot when p >= threshold; its warmth is the share of hot steps in its last 8.
- Two groups: *structure* (demand and generation anomalies; hot if both signals are hot, or
  their mean warmth is at least 0.45) and *residual* (forecast error, imbalance, imbalance
  anomaly; hot if any is hot, or mean warmth at least 0.5).
- The system is hot when both groups were hot at some step in the last W steps and one of
  them is hot now: W = 3 for a **watch**, 24 for a **warning**.
- An alert is on once the system has been hot for L consecutive steps (persistence). An alert
  episode is a run of consecutive alert steps.

The operator-style reference rule is the one exception: it has no per-signal scores and raises
alerts directly when demand exceeds its forecast by more than the trailing year's q-th
percentile of percent forecast error for L hours in a row.

## Operating point: the same alert budget for everyone

A method that alerts constantly catches everything, so each method is compared at the same
alert budget: **12 watch episodes and 2 warning episodes per grid per year.** For each level,
every combination of threshold (0.90, 0.95, 0.98, 0.99, 0.995, 0.999) and persistence (watch
3, 4, 6, 8, 12 h; warning 6, 9, 12, 18, 24 h) is run on all grids and seeds; the setting
chosen is the one whose median-grid alert rate (mean over seeds) is the largest at or under the
budget. This step reads alert counts only, never the events, so a method cannot be tuned
toward the answers.

## Verification

At that setting, for each level:

- **Events caught** (probability of detection): a watch counts if an episode starts in the
  168 h before onset; a warning counts from 168 h before to 48 h after onset (a late warning
  still confirms the emergency). Reported for all 8 events and for the 5 held-out events.
- **Lead time:** hours from the first counting episode to onset, per event; medians over
  caught event-seeds.
- **Alerts per grid-year** and the **false alarm ratio:** the share of all episodes that did
  not start in a counting window. With one load shed per grid in six-plus years, nearly every
  watch is a false alarm for every method; the ratio is reported because forecasters report
  it, but methods mostly differ in what they catch.
- **Uncertainty:** methods with randomness run on 5 seeds (mean, and range over seeds); the
  5th-95th percentile when the events are resampled with replacement (10,000 draws).
- **Chance:** each method's own episodes shifted to random times (2,000 shifts, wrap-around),
  keeping their number and clustering. Expected catches by chance are about 1 watch and 0.3
  warnings for every reference method. A randomly timed alert that lands in the 7-day window
  lands about 4 days early on average, so a long median lead is not, by itself, evidence of
  early warning; read lead times per event.

## Status quo row

The operators' own public notices (`gridshedwatch/operator_notices.yaml`) are scored as
watches: caught if any public-facing notice came in the 168 h before onset. v1.0: 4 of 8
(California, MISO, Texas, SPP); none of the four Elliott events. Operators' notices to the
industry, and their false alarms in ordinary years, are not yet compiled.

## Fairness rules for reference methods

Same inputs, same shared rules, same budgets, each method's own label-free setting. Methods
with randomness: 5 seeds. Pretrained models run as published, with any possible overlap of
their training data with the test years stated.

## Change log

- 2026-10-23: v1.0 released. Settings frozen as above; reference results in `results/v1.0/`.
