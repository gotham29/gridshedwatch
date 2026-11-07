# GridShedWatch v3.0 scoring protocol

Fixed on 2026-11-03, before any v3.0 rescoring was run. Any later change to this
file is a deviation and is listed at the end with its date and reason. v2.0 results stay published and
are reported beside v3.0 as a comparison.

## What does not change

Events (`events.yaml`, including `split`), grids (48), signals, scoring windows, the shared alert rules
(`config.py`), alert budgets (12 watches, 2 warnings per grid-year), every method's reference scores and
seeds, and HTM's entry (2019 pretraining, frozen; the other three HTM setups are reported as ablations).

The shared alert rules exist so that methods in the scores track differ only in their scores: every
method's scores are turned into alerts the same way. They are not part of a method. A method can skip
them by submitting its own watch and warning times (alerts track), scored by the same event rules.

## What changes, and why

1. **Operating point: calibrated on quiet grids only, with an exact budget.** The 39 quiet grids are
   split into a calibration half and an evaluation half, fixed by sorting the BA codes'
   SHA-256 hashes (list in `grids.yaml`, `calib`). For each method and level, persistence is fixed at the
   shortest setting (watch 3 h, warning 6 h), and the threshold is the score quantile at which the median
   calibration grid's alert rate equals the budget. No event grid's data are seen. Each method's
   threshold and realized rate on every grid group are reported. Reason: v2.0 chose from a 30-setting grid
   on the 8 Tier 1 grids, so the budget was a ceiling rather than a match, and the search saw the data
   around the held-out events.
2. **Alert-rate curves.** Events caught against the median-grid alert rate, at watch budgets
   3, 6, 12, 24, 48 and warning budgets 0.5, 1, 2, 4, 8 per grid-year, calibrated as in (1). The
   protocol budget is one point on each curve.
3. **Tier 1 is the headline; Tier 2 events are case studies.** Counts, tests and rankings use the 8
   Tier 1 events only. Tier 2 events are reported one by one and are never pooled with Tier 1 (as
   protocol v2.0, item 3, already required).
4. **Warnings before and after onset are reported separately.** A warning that starts before onset is an
   early warning; one that starts in the 48 h after onset is in-event detection. The headline warning
   count is before onset only. The 48 h window is unchanged and reported as in v2.0.
5. **Seasonal chance baseline.** Each method's alerts on a grid are shifted together by a random whole
   number of years (1 to 6, wrapped within 2020 to 2026) plus a uniform offset of up to 15 days either
   way, 2,000 times. This keeps how often, how clustered and in what season a method alerts.
   p = (1 + shifted copies catching at least as many events) / 2,001. Holm correction across methods,
   per level. v2.0's shift to any time is reported beside it.
6. **Uncertainty.** Per-method detection rates get exact (Clopper-Pearson) 95% intervals. Because Tier 1
   has only three storms, the dependence on storms is shown by leaving one storm out (Aug 2020 heat, Uri,
   Elliott) rather than by a clustered bootstrap. Friedman and Nemenyi are run on the 8 Tier 1 events;
   pairwise exact sign tests are Holm-corrected. Post-hoc power is replaced by the minimum
   difference the 8 events can detect (an exact sign test needs 6 of 6 discordant events at alpha 0.05).
7. **Lead time.** Median lead with its n (events caught). A chance lead from the shifted copies in (5).
   For each event, the lead over the operator's first public notice (status quo).
8. **Near-miss masks (scoring only; the event rule is unchanged).** An event is still exactly what
   Box 1 says: a firm load shed of at least 250 MW for lack of supply (Tier 1), or a qualifying EEA 3
   (Tier 2). Separately, some periods on the benchmark's grids were documented emergencies that fall
   short of that rule: a supply-caused firm load shed below 250 MW, or an EEA 2 or higher for lack of
   supply, each with an official source (`events.yaml`, `near_miss`). An alert that would verify such a
   period under the event windows counts neither as verified nor as false. They are never events, never
   counted as caught, and never used to choose anything. False alarm ratio and burden are reported with
   and without masks.
9. **False alarm ratio.** Reported with its parts (verified alerts, all alerts) and the critical success
   index, since at a matched budget FAR largely follows from events caught.
10. **Held-out results.** Every Tier 1 measure is also reported on the 5 held-out events. They share storms
    with the development events (Uri, Elliott), so they test new grids, not new weather systems.

## Sensitivity analyses and ablations, fixed now

- Data latency: alert starts delayed by 1, 6 and 24 h.
- Onset: the earlier of the declaration and the DOE OE-417 start time.
- Operating point as in v2.0 (8 Tier 1 grids, setting grid) and on all 48 grids.
- Alert rules: two alternatives, applied to every method: any signal hot (max over signals), and the
  forecast-error signal alone.
- Score transform: HTM's anomaly-likelihood transform applied to every method's scores.
- HTM: all four learning setups.

## New reference methods

Added before any of them is scored, with settings fixed here. All see the five signals, go through the
shared rules and the operating point in (1), and output a causal percentile in [0, 1] per signal and hour.

- **CUSUM.** Two-sided CUSUM on each signal, standardized by its trailing 30-day median and MAD;
  k = 0.5, statistic reset to 0 after it exceeds h = 5. Score: the larger of the two sides. Deterministic.
- **Critical slowing down.** On each signal, rolling variance and lag-1 autocorrelation over the past
  168 h. Score: the mean of their causal percentiles. Deterministic.
- **Retrained forecasters.** The LSTM, PatchTST and gradient-boosted forecasters with their v2.0
  settings, refit on 1 January of each year on the preceding 12 months (2019 for 2020, and so on),
  5 seeds. Reported beside the frozen versions, which stay as entries.
- **Chronos-Bolt (base).** Same use as Chronos-Bolt (small): zero-shot next-hour forecasts from 512 h of
  context, scored by absolute error.

## Deviations

- 2026-11-03, before any v3.0 scoring (clarifications, found while writing the code): (a) item 5's whole
  years run from 1 to 5, not 6, because alerts wrap modulo 6 years and a 6-year shift would leave them
  in place; (b) item 1's calibration split is computed by `data.calibration_split()` and written to
  `results/v3.0/calibration_grids.csv` rather than listed in `grids.yaml`.
- 2026-11-03, before any refit forecaster or Chronos-Bolt base was scored (compute): the LSTM and PatchTST
  refits (about 24 and 14 minutes per grid and seed on a laptop CPU, against 4 and 2.4 frozen) are run
  with seed 0 only, on the 28 grids the scores need (the 9 event grids and the 19 calibration grids), so
  they have no evaluation-half burden. The gradient-boosted refit is run as fixed (5 seeds, 48 grids).
- 2026-11-05, before Chronos-Bolt base was scored (compute): not run. One grid took over 33 minutes on
  a laptop CPU and about 2.5 hours on its GPU (mps), so the 28 scored grids were out of reach.
  Chronos-Bolt small remains the foundation-model entry; `chronos.scores_base` is kept for anyone with
  the compute.
- 2026-11-05, before either was scored (compute): the LSTM and PatchTST refits are not run. Six
  single-core processes finished no grid in two hours, so the 28 grids would take most of a day, and
  the HTM setups had priority. The gradient-boosted refit, the leading method's, is reported.
  `scores_retrained` stays in both modules.
- 2026-11-04 (logged late, found by an independent audit): before the first v3.0 results, the SPP West
  near-miss was removed (SPP West is not a benchmark grid) and the ERCOT 2023-09-06 EEA 2 time set
  exactly; afterwards the likelihood transform used in the ablation was rewritten twice to match
  htm-monitor's algorithm, and the ablations were rerun. None touches the Tier 1 headline.
- 2026-11-06, after the first v3.0 results, following an independent audit; every method was rescored:
  - Ties in scores are broken with a seeded jitter below 1e-7 (reference scores are percentiles rounded to 1e-6;
    scores computed during the run are not rounded, where a jitter this small can reorder only near-ties),
    and bisection continues until the calibration rate is within 2% of the budget; `reached` now means
    within 5%. Reason: HTM's likelihood piles up at exactly 0.999, so its warning threshold had landed
    at 2.79 warnings per grid-year (40% over budget) while marked as reached.
  - Seasonal chance baseline: only the first 6 whole years of a method's alerts are shifted (modulo 6
    years), so 2026 alerts no longer fold onto earlier years. The old version was conservative.
  - False alarm ratio: on the 8 Tier 1 grids, with warnings verified only before onset; alerts that
    verify only a Tier 2 event or a load shed after onset are left out, not counted false. The critical
    success index is dropped (it mixed events and alerts).
  - Item 6 corrected: pairwise sign tests are dropped. With 8 events and 10 Holm-corrected
    comparisons, the smallest possible adjusted p is 0.078 (8 of 8), so none could reach 0.05; the
    earlier "6 of 6" statement held only for a single uncorrected test. Friedman and Nemenyi remain.
  - Holm correction of the chance tests runs over the ranked entries only.
  - The budget is matched on the calibration grids, not on the grids where events are scored, so the
    summary also reports each method's alert rate on the Tier 1 grids and its catches above chance.
  - Sensitivities: the operating point set on all grids (still label-free) is now run; the operating
    point as in v2.0 is reported from `results/v2.0`, not rerun.
  - HTM setups: the online setup is scored on its 27 grids (no NV Energy run, so its Tier 2 is
    incomplete); the keep-learning and same-encoder setups keep their v2.0 numbers (compute).
  - Leads: the count is of events caught by at least one seed; intervals are for the rounded
    seed-mean count.
- 2026-11-07, after a second independent audit; chance steps rerun:
  - The seasonal (and any-time) chance baseline uses ONE shift per draw, shared by every grid. Shifting
    each grid separately treated events of the same storm on different grids as independent, which made
    the spread of chance catches too narrow and some p-values too small. Item 5 allowed either reading.
  - The tie-break jitter does not guarantee the budget: single-seed methods move in steps of one alert
    per grid at the smallest warning budget (0.5), and critical slowing down cannot reach 48 watches.
    Such curve points keep `reached = False` and are marked on the curves.
  - HTM's warning threshold falls inside its tie at 0.999, so its warning results depend on the draw.
    HTM is also scored with tie-break salts 1 to 4 (`--salt`), and the paper reports the protocol draw
    with the range over the 5 draws. Other methods have no such tie.
  - The any-time chance baseline (item 5's comparison with v2.0) is not reported: with one shift shared
    by all grids, a draw near zero shift leaves every alert in place, which puts a floor of about 0.003
    to 0.007 under its p-values. All claims use the seasonal baseline, whose shifts are always at least
    a year less 15 days. Its `_any` columns in the results are kept but not used.
