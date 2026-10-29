# GridShedWatch v1.0: the events

Every event in GridShedWatch is chosen by one rule, written down before any new grid was
scored. Nothing below was changed after looking at results. Machine-readable list:
`gridshedwatch/events.yaml`. Operators' notices before each event (the status quo row):
`gridshedwatch/operator_notices.yaml`.

## The rule

A **target event** is an operator-initiated firm load shed caused by insufficient supply
(an Energy Emergency Alert level 3 with load shed), that

1. happened between 2020-01-08 and 2026-10-01 (the scored period; 2019 is the calibration year),
2. shed **at least 250 MW** at its worst point, and
3. occurred in a balancing authority that reports hourly demand, day-ahead demand forecast and
   net generation to EIA-930 (the only data the system sees).

**Excluded by definition:** load shed caused by damage to wires or substations (hurricanes,
derechos, wildfire shutoffs). Those are transmission and distribution failures, not a gap
between supply and demand, which is what this case study tests.

**Onset** (unchanged from the published standard): the time the operator declared the highest
emergency level the event reached, from an official source, converted to UTC. How alerts are scored against the onset: docs/scoring.md.

**When the declaration time is not published** (fallback, fixed in advance): use the
earliest officially documented load-shed directive. If only the day is documented, use
00:00 local time on that day. Both choices move onset earlier, never later, so they can
only reduce claimed lead time and never turn a late alert into a "predicted" one.

## Target onsets

| Event | Region (EIA-930) | Onset, local | Onset, UTC | Basis | Source |
|---|---|---|---|---|---|
| CA heat wave, Aug 2020 | CISO | 2020-08-14 18:38 PDT | 2020-08-15 01:38 | Stage 3 Emergency (published onset) | CAISO root cause analysis |
| Uri, Feb 2021 | ERCO | 2021-02-15 01:20 CST | 2021-02-15 07:20 | EEA 3, rotating outages (published onset) | ERCOT |
| Uri, Feb 2021 | SWPP | 2021-02-15 10:08 CST | 2021-02-15 16:08 | EEA 3 declared | SPP |
| Uri, Feb 2021 | MISO | 2021-02-16 19:40 EST | 2021-02-17 00:40 | Max Gen Event Step 5 (EEA 3) for MISO South; 700 MW for capacity shortage | MISO, *The February 2021 Arctic Event* |
| Elliott, Dec 2022 | TVA | 2022-12-23 06:12 EST | 2022-12-23 11:12 | EEA 3 declared (published onset; the report gives Eastern time) | FERC-NERC Elliott inquiry |
| Elliott, Dec 2022 | DUK (Duke Energy Carolinas) | 2022-12-24 06:14 EST | 2022-12-24 11:14 | Fallback: first load-shed directive (EEA 3 time not published); up to 1,000 MW | Duke timeline (NC) |
| Elliott, Dec 2022 | CPLE (Duke Energy Progress) | 2022-12-24 06:25 EST | 2022-12-24 11:25 | Fallback: first load-shed request (600 MW; ~960 MW total) | Duke timeline (NC/SC) |
| Elliott, Dec 2022 | LGEE | 2022-12-23 13:36 EST | 2022-12-23 18:36 | EEA 3 declared (load shed >300 MW 17:58-22:11) | LG&E-KU responses to KY PSC |

## Why each choice

- **Firm load shed, not alerts or appeals.** Load shed is the outcome people experience and
  the one operators work hardest to avoid. Alerts without load shed are common (NERC counted
  10 EEA 3 declarations in 2025, none with load shed) and are a weaker test.
- **250 MW floor.** Excludes sheds too small to show up in a balancing authority's hourly
  totals (the two South Carolina sheds during Elliott were under 100 MW for 9 and 17 minutes).
  The floor was set before any new region was scored.
- **EIA-930 coverage.** The system only sees public hourly data; an event in an area that does
  not report to EIA-930 cannot be tested.
- **Same rule everywhere.** Every region uses the same model template, 2019 calibration
  (encoder bounds and the bad-data filter), alert rule and thresholds. No region is tuned.

## Completeness: where the event list comes from

NERC's annual *State of Reliability* reports list every operator-initiated firm load shed in
North America by year (2026 report, Table 3.1; 2025 overview, Table 2), cross-checked against
DOE OE-417 reports for 2020-2022 (EIA Electric Power Monthly, Appendix B; later years are not
public). Event sizes and
affected balancing authorities come from the FERC-NERC inquiry reports on Winter Storm Uri
(2021) and Winter Storm Elliott (2022) and from CAISO's August 2020 root cause analysis.

| Year | NERC-listed load shed | Decision |
|---|---|---|
| 2020 | California heat wave (Aug 14-15) | **Target** (CAISO, 1,000 MW) |
| 2020 | California wildfires | Excluded: wildfire / public safety shutoffs |
| 2020 | Hurricane Laura | Excluded: storm damage |
| 2020 | El Paso Electric, Aug 13 (218 MW, 1:51-4:27 PM MDT; DOE OE-417) | Excluded: below the 250 MW floor |
| 2020 | Imperial Irrigation District, Sept 5 (100 MW, 5:25-8:55 PM PDT; DOE OE-417) | Excluded: below the 250 MW floor |
| 2021 | Winter Storm Uri | **Targets:** ERCOT (20,000 MW), SPP (2,700 MW), MISO (700 MW, MISO South) |
| 2022 | June heat wave | Excluded: AEP Columbus load shed after a derecho damaged transmission (NERC event analysis) |
| 2022 | Baja California, June 5 (filed in DOE OE-417 by CAISO as Reliability Coordinator) | Excluded: in Mexico (CENACE cuts after a supplier plant failed), not an EIA-930 balancing authority |
| 2022 | Winter Storm Elliott | **Targets:** TVA (3,000 MW), Duke Energy Carolinas and Duke Energy Progress (1,900 MW combined), LG&E-KU (300 MW). Excluded: Dominion Energy SC (94 MW, 9 min), Santee Cooper (86 MW, 17 min), below the floor |
| 2023 | None | - |
| 2024 | Western Interconnection generator trip, failed dispatch (0.43 h) | Excluded: entity and MW not published, so it cannot be placed in a balancing authority |
| 2025 | No supply-caused load shed (NERC: 10 EEA 3 declarations, none with load shed) | - |
| 2025 | MISO, New Orleans area, May 25 (500 MW to Entergy at 4:21 PM and 100 MW to CLECO at 4:30 PM; Louisiana PSC) | Excluded: declared a Transmission System Emergency, not a capacity emergency (no EEA 3) |
| 2026 (Jan-Sep) | None found (Winter Storm Fern, summer heat: emergency orders, no load shed reported) | To confirm against NERC's 2027 report |

### Known limitations, stated up front

- **MISO is one huge balancing authority in EIA-930.** The 700 MW shed was in MISO South
  (Entergy Texas), a small share of MISO's total load, so the signal is diluted. It stays in:
  an expected, disclosed miss is more credible than a convenient exclusion.
- **MISO's earlier Uri sheds are excluded by the rule.** On Feb 15-16 MISO also ordered
  sheds in East Texas, Louisiana and Illinois under *transmission* emergencies (800, 300,
  1,000 and 130 MW). Only the Feb 16 evening EEA 3 was a supply shortfall.
- **Uri and Elliott each produce several targets.** Events in the same storm are not fully
  independent tests, but they are different grids with different generation mixes and
  operators. Results are reported per event and per storm.
- **California's September 2020 and September 2022 emergencies are no longer targets** (no
  load was shed). They become explanatory windows, like the COVID window.


## Development and held-out events

The shared alert rules (docs/scoring.md) were designed on three events from an earlier study:
Texas/Uri, TVA/Elliott and California/August 2020 (`split: development`). The other five were
held out and scored once, after the rules were frozen (`split: held-out`). Seven of the eight
events come from two storms, so the held-out events share weather with two development
events; they are different grids with different operators and generation. The full design
history, including the rounds that did not pass, is in htm-monitor's
[docs/event_selection.md](https://github.com/gotham29/htm-monitor/blob/master/docs/event_selection.md).

## Future versions

Each new load shed that meets the rule is added in a new version and scored with the rules
frozen in v1.0. Candidate next tiers: EEA 3 declarations without load shed, and grids outside
the US with public hourly data.
