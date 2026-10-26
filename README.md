# GridShedWatch

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23626223.svg)](https://doi.org/10.5281/zenodo.23626223) [![tests](https://github.com/gotham29/gridshedwatch/actions/workflows/tests.yml/badge.svg)](https://github.com/gotham29/gridshedwatch/actions/workflows/tests.yml)

**A benchmark for early warning of grid load sheds, scored the way forecasters score weather warnings.**

Website: **https://gotham29.github.io/gridshedwatch** (built from this repo by `scripts/build_site.py`).

Since 2020, US grid operators have had to cut power for lack of supply eight times. The public
was warned beforehand in four of them, and in none of the four during Winter Storm Elliott.
Plenty of methods claim to detect grid trouble early, but there has been no shared test of
whether a warning would actually have come in time. GridShedWatch is that test: every one of
those eight load sheds, public hourly data, and one fixed scoring procedure that any method can
be run through.

The idea behind it isn't new. The National Weather Service has
[scored its warnings for decades](https://doi.org/10.1175/waf-d-18-0120.1) on three numbers read
together: how many events were warned in advance, how much notice people got, and how many
warnings were false alarms. GridShedWatch applies that established framework to grid
emergencies, at the weather service's own two levels: a **watch** (something unusual is
building) and a **warning** (act now).

![What operators announced in the week before each load shed](https://raw.githubusercontent.com/gotham29/gridshedwatch/main/docs/img/operator_notices.png)

Uri and the 2020 California heat wave were forecast days out, and operators climbed a ladder of
notices. Elliott built faster than the forecasts: in all four Elliott events, the public's first
word was the blackout itself. That gap is what an independent warning signal could fill, and
what GridShedWatch measures.

## What's in it

| | |
|---|---|
| **Events** | 8 supply-shortfall load sheds of at least 250 MW, Jan 2020 to Sep 2026, chosen by a stated rule from NERC's annual lists ([docs/events.md](https://github.com/gotham29/gridshedwatch/blob/main/docs/events.md)) |
| **Data** | A frozen snapshot of EIA-930 hourly demand, day-ahead forecast and net generation for the 8 grids, 2019-2026, and the five signals built from it ([gridshedwatch/snapshot_v1.0/](https://github.com/gotham29/gridshedwatch/tree/main/gridshedwatch/snapshot_v1.0/), [gridshedwatch/data.py](https://github.com/gotham29/gridshedwatch/blob/main/gridshedwatch/data.py)) |
| **Rules** | One shared rule that turns per-signal scores into watches and warnings, so methods differ only in how they score each hour ([gridshedwatch/rules.py](https://github.com/gotham29/gridshedwatch/blob/main/gridshedwatch/rules.py)) |
| **Scoring** | Same alert budget for every method, chosen without looking at the events; events caught, lead time and false alarm ratio, with bootstrap intervals and a chance baseline ([docs/scoring.md](https://github.com/gotham29/gridshedwatch/blob/main/docs/scoring.md)) |
| **Status quo** | Every operator notice in the week before each event, with times and sources ([gridshedwatch/operator_notices.yaml](https://github.com/gotham29/gridshedwatch/blob/main/gridshedwatch/operator_notices.yaml)) |
| **Reference methods** | An operator-style rule, a seasonal z-score, an LSTM forecaster, Chronos-Bolt (zero-shot), and HTM ([gridshedwatch/baselines/](https://github.com/gotham29/gridshedwatch/tree/main/gridshedwatch/baselines/)) |
| **Datasheet** | Motivation, composition, collection, intended uses, known biases and maintenance ([docs/datasheet.md](https://github.com/gotham29/gridshedwatch/blob/main/docs/datasheet.md)) |

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

All five reference methods are in the scores track; no alerts-track entries yet. Mean over 5 seeds for the LSTM and HTM. [a-b]: 5th-95th percentile with events resampled. Operators: public notices in the 7 days before onset, scored as watches.
<!-- leaderboard:end -->

Every method except Chronos's watches catches far more than chance, and none leads at both
levels. The differences are by kind of emergency: the simple rules caught all three Uri events
days ahead, the LSTM and HTM caught the Elliott events hours ahead (when the public got no
warning), and only the operators warned California. With eight events, differences of about one
event are not meaningful. Per-event results: `results/v1.0/<method>_events.csv`.

## Quick start

```bash
pip install gridshedwatch                # or, to work on the code:
git clone https://github.com/gotham29/gridshedwatch && cd gridshedwatch
pip install -e ".[test]"
gridshedwatch info                       # the eight events and their timelines
gridshedwatch score --oprule             # score the built-in operator-style rule
python examples/my_method.py             # scores track template: writes my_scores/
gridshedwatch score my_scores --name "My method"
python examples/my_alerts.py             # alerts track template: writes my_alerts.csv
gridshedwatch score-alerts my_alerts.csv --name "My rule"
```

## Add your method

There are two ways in.

**Scores track** (the controlled comparison). Your method says, for every grid, every hour and
each of the five signals, how unusual that signal is now, as a score in [0, 1], using data up to
that hour only. Write the scores in the submission layout (`my_scores/s<seed>/<grid>.csv`, see
[gridshedwatch/submission.py](https://github.com/gotham29/gridshedwatch/blob/main/gridshedwatch/submission.py)) and run `gridshedwatch score`. The
shared rules, the label-free budget step and the scoring are done for you, so your method
cannot be tuned toward the eight events. Template: [examples/my_method.py](https://github.com/gotham29/gridshedwatch/blob/main/examples/my_method.py).

**Alerts track** (any method). If your method decides on its own when to raise a watch or a
warning (a rule, a classifier, a weather-based model, a human forecaster), list when each alert
started and score the list. For example, take a simple rule: raise a watch when demand has run
unusually far above its forecast for three hours, and a warning when it has done so badly for
six ([examples/my_alerts.py](https://github.com/gotham29/gridshedwatch/blob/main/examples/my_alerts.py)).
Running it writes one line per alert (add a `seed` column if your method is random):

```
grid,level,start_utc
tx,watch,2021-02-09 12:00
tx,warning,2021-02-09 21:00
duk,watch,2022-12-24 00:00
...
```

Score it:

```
gridshedwatch score-alerts my_alerts.csv --name "My rule"
```

```
My rule  (1 seed)
  watch    submitted alerts   caught 3.0 of 8 [1.0-5.0], chance 0.9; held-out 2.0 of 5;
                              median lead 131.0 h; 5.7 alerts/grid/yr; false alarm ratio 99%
  warning  submitted alerts   caught 1.0 of 8 [0.0-3.0], chance 0.1; held-out 0.0 of 5;
                              median lead 130.0 h; 0.6 alerts/grid/yr; false alarm ratio 97%
```

The rule watched 3 of the 8 load sheds where its alerts at random times would have caught about
one, and warned Texas five days before Uri; it missed the rest. Alerts-track entries are scored
exactly like the scores track, at the same budget (median grid at most 12 watches and 2 warnings
a year, no grid above 3 times that); an entry over budget is flagged. Format:
[gridshedwatch/alerts.py](https://github.com/gotham29/gridshedwatch/blob/main/gridshedwatch/alerts.py).
The five reference methods' alerts, in [results/v1.0/alerts/](https://github.com/gotham29/gridshedwatch/tree/main/results/v1.0/alerts/),
are further worked examples and reproduce the table above.

![How one method is scored on one grid](https://raw.githubusercontent.com/gotham29/gridshedwatch/main/docs/img/scoring_example.png)

- Scores track: use the five signals provided (and 2019 for calibration). Alerts track: any data
  available at the time of each alert. Methods that use data beyond the five signals are listed
  separately.
- If your method is random, submit several seeds; results are averaged.
- To add a result to the table, open a pull request with your scores or alerts (or a link to
  them), the code that produced them, the output of `--json`, and short answers on the data used
  and, for the alerts track, which events you looked at while developing
  ([docs/scoring.md](https://github.com/gotham29/gridshedwatch/blob/main/docs/scoring.md#listing-a-result)). Every result is added, including ones
  that beat the reference methods.

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
- Reference methods see only five signals from EIA-930: no weather, outage or market data. The
  alerts track is open to methods that use more.
- The status quo row covers operators' public notices; their notices to the industry and their
  false alarms in ordinary years are not yet compiled.

GridShedWatch grows as new events happen: each load shed that meets the rule is added in a new
version and scored with the rules frozen in v1.0.

## Citation and license

DOI: [10.5281/zenodo.23626223](https://doi.org/10.5281/zenodo.23626223) (archived on Zenodo with every release). See [CITATION.cff](https://github.com/gotham29/gridshedwatch/blob/main/CITATION.cff). Code: MIT. Event list, timelines, documentation and results:
CC BY 4.0. EIA-930 data: U.S. public domain ([DATA_LICENSE.md](https://github.com/gotham29/gridshedwatch/blob/main/DATA_LICENSE.md)).
