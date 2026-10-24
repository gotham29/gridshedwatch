# GridShedWatch

**A benchmark for early warning of grid load sheds, scored the way forecasters score weather warnings.**

Website: **https://gotham29.github.io/gridshedwatch** (built from this repo by `scripts/build_site.py`).

Since 2020, US grid operators have had to cut power for lack of supply eight times. The public
was warned beforehand in four of them, and in none of the four during Winter Storm Elliott.
Plenty of methods claim to detect grid trouble early, but there has been no shared test of
whether a warning would actually have come in time. GridShedWatch is that test: every one of
those eight load sheds, public hourly data, and one fixed scoring procedure that any method can
be run through.

The National Weather Service scores every warning it issues on three numbers read together:
how many events were warned in advance, how much lead time people got, and how often warnings
were false alarms. GridShedWatch asks the same of grid warnings, at two levels: a **watch**
(about one a month per grid: something unusual is building) and a **warning** (two a year: act).

## What's in it

| | |
|---|---|
| **Events** | 8 supply-shortfall load sheds of at least 250 MW, Jan 2020 to Sep 2026, chosen by a stated rule from NERC's annual lists ([docs/events.md](docs/events.md)) |
| **Data** | A frozen snapshot of EIA-930 hourly demand, day-ahead forecast and net generation for the 8 grids, 2019-2026, and the five signals built from it ([gridshedwatch/snapshot_v1.0/](gridshedwatch/snapshot_v1.0/), [gridshedwatch/data.py](gridshedwatch/data.py)) |
| **Rules** | One shared rule that turns per-signal scores into watches and warnings, so methods differ only in how they score each hour ([gridshedwatch/rules.py](gridshedwatch/rules.py)) |
| **Scoring** | Same alert budget for every method, chosen without looking at the events; events caught, lead time and false alarm ratio, with bootstrap intervals and a chance baseline ([docs/scoring.md](docs/scoring.md)) |
| **Status quo** | Every operator notice in the week before each event, with times and sources ([gridshedwatch/operator_notices.yaml](gridshedwatch/operator_notices.yaml)) |
| **Reference methods** | An operator-style rule, a seasonal z-score, an LSTM forecaster, Chronos-Bolt (zero-shot), and HTM ([gridshedwatch/baselines/](gridshedwatch/baselines/)) |

| Event | Grid | Shed at its worst | Split |
|---|---|---|---|
| Heat wave, Aug 2020 | California (CAISO) | about 1,000 MW | development |
| Winter Storm Uri, Feb 2021 | Texas (ERCOT) | 20,000 MW | development |
| Uri | Southwest Power Pool | 2,700 MW | held-out |
| Uri | MISO (MISO South) | 700 MW | held-out |
| Winter Storm Elliott, Dec 2022 | Tennessee Valley Authority | 3,000 MW | development |
| Elliott | Duke Energy Carolinas | up to 1,000 MW | held-out |
| Elliott | Duke Energy Progress | about 960 MW | held-out |
| Elliott | LG&E and KU (Kentucky) | about 300 MW | held-out |

## Results, v1.0

<!-- leaderboard:start -->
| Method | Watches: caught (of 8) | held-out (of 5) | by chance | median lead (h) | Warnings: caught (of 8) | held-out (of 5) | by chance | False alarm ratio (watch / warning) |
|---|---|---|---|---|---|---|---|---|
| Operators (public notices) | 4 | 2 | - | 20 | - | - | - | - |
| Operator-style rule | 5 [3.0-7.0] | 4 | 1.2 | 85 | 2 [0.0-4.0] | 1 | 0.2 | 98% / 94% |
| Seasonal z-score | 5 [3.0-7.0] | 4 | 1.1 | 105 | 6 [4.0-8.0] | 4 | 0.2 | 98% / 92% |
| Chronos-Bolt (zero-shot) | 1 [0.0-3.0] | 1 | 0.9 | 9 | 3 [1.0-5.0] | 1 | 0.3 | 100% / 96% |
| LSTM forecaster | 6.4 [4.6-8.0] | 4.4 | 1.3 | 8 | 4.8 [2.8-6.8] | 2.8 | 0.3 | 99% / 94% |
| HTM (htm-monitor) | 6 [4.6-7.2] | 4 | 1.4 | 56 | 5.6 [3.8-7.2] | 3.6 | 0.3 | 98% / 93% |

Mean over 5 seeds for the LSTM and HTM. [a-b]: 5th-95th percentile with events resampled. Operators: public notices in the 7 days before onset, scored as watches.
<!-- leaderboard:end -->

Every method except Chronos's watches catches far more than chance, and none leads at both
levels. The differences are by kind of emergency: the simple rules caught all three Uri events
days ahead, the LSTM and HTM caught the Elliott events hours ahead (when the public got no
warning), and only the operators warned California. With eight events, differences of about one
event are not meaningful. Per-event results: `results/v1.0/<method>_events.csv`.

## Quick start

```bash
git clone https://github.com/gotham29/gridshedwatch && cd gridshedwatch
pip install -e ".[test]"
gridshedwatch info                       # the eight events and their timelines
gridshedwatch score --oprule             # score the built-in operator-style rule
python examples/my_method.py             # a template method: writes my_scores/
gridshedwatch score my_scores --name "My method"
```

## Add your method

A method's only job is to say, for every grid, every hour and each of the five signals, how
unusual that signal is now, as a score in [0, 1], using data up to that hour only. Write those
scores in the submission layout (`my_scores/s<seed>/<grid>.csv`, see
[gridshedwatch/submission.py](gridshedwatch/submission.py)) and run `gridshedwatch score`. The
shared rules, the label-free budget step and the scoring are done for you, so your method
cannot be tuned toward the eight events.

- Use the five signals provided (and 2019 for calibration). Methods that use other data, such as
  weather, are welcome and are listed separately.
- If your method is random, submit several seeds (`s0`, `s1`, ...); results are averaged.
- To add a result to the table, open a pull request with your scores (or a link to them), the
  code that produced them, and the output of `gridshedwatch score --json`. Every result is
  added, including ones that beat the reference methods.

## Reproducing v1.0

```bash
python -m pytest -q                      # rebuilds the rule and z-score results from the data
python scripts/fetch_reference.py        # reference scores for LSTM, Chronos, HTM (about 100 MB)
python -m pytest -q                      # now also checks those three against results/v1.0/
python scripts/reproduce_v1.py           # writes results/v1.0/ from scratch
docker build -t gridshedwatch . && docker run --rm gridshedwatch
```

The LSTM and Chronos can be rerun with `gridshedwatch baseline lstm|chronos -o DIR` (needs
`pip install -e ".[lstm]"` or `".[chronos]"`). Neural-network training is not bit-identical
across platforms and library versions, so a rerun gives close but not identical scores; the
reference scores are the official v1.0 results. HTM's scores come from
[htm-monitor](https://github.com/gotham29/htm-monitor), scored here like any other submission.

## Limits

- Eight events, seven from two storms (Uri and Elliott). One storm of a new kind could change
  the picture.
- Three events were used to design the shared rules; five were held out and scored once.
- Methods see only five signals from EIA-930: no weather, outage or market data.
- The status quo row covers operators' public notices; their notices to the industry and their
  false alarms in ordinary years are not yet compiled.

GridShedWatch grows as new events happen: each load shed that meets the rule is added in a new
version and scored with the rules frozen in v1.0.

## Citation and license

See [CITATION.cff](CITATION.cff). Code: MIT. Event list, timelines, documentation and results:
CC BY 4.0. EIA-930 data: U.S. public domain ([DATA_LICENSE.md](DATA_LICENSE.md)).
