# GridShedWatch v1.0: datasheet

Following the questions of *Datasheets for Datasets* (Gebru et al., 2021), for the benchmark as
a whole: the event list, the data snapshot, the operator-notice timelines and the scoring.
Details are in [events.md](events.md) and [scoring.md](scoring.md); this page points to them
rather than repeating them.

## Motivation

- **Why was it created?** To give early-warning methods for grid emergencies a common,
  public test. Many methods claim to detect grid stress early, but each is evaluated on its own
  events, data and metric, usually per hour on simulated grids or a single storm, so none can
  be compared. GridShedWatch fixes the events, the data, the alert budget and the scoring.
- **Who created it?** Sam Heiserman (independent; htm-monitor / DataGrip LLC). One of the
  five reference methods (HTM, via htm-monitor) is the author's own; it is scored by the same
  path as the others, and the benchmark code does not depend on it.
- **Funding:** none.

## Composition

- **Events (`gridshedwatch/events.yaml`):** 8 instances, one per affected grid: every
  operator-initiated firm load shed caused by insufficient supply in North America, Jan 2020
  to Sep 2026, of at least 250 MW at its worst, in a balancing authority that reports to
  EIA-930. Each has an onset time with its basis and source, the size of the shed, and a split
  (3 development, 5 held-out). The list is complete under the rule, checked against NERC's
  annual *State of Reliability* load-shed tables; exclusions and why are listed in events.md.
- **Data (`gridshedwatch/snapshot_v1.0/`):** hourly demand (D), day-ahead demand forecast (DF)
  and net generation (NG) from EIA-930 for the 8 balancing authorities, Jan 2019 to Oct 2026,
  UTC, about 5.6 MB compressed, with SHA-256 checksums. The five signals every method sees are
  derived from it by one rule (`gridshedwatch/data.py`).
- **Operator notices (`gridshedwatch/operator_notices.yaml`):** every notice found from each
  operator in the week before its event, with time (UTC; marked when only the day is
  published), audience (public or industry) and sources. They form the status-quo row.
- **Reference results (`results/v1.0/`):** per-event and summary results for five methods, and
  their alerts in the alerts-track format. Reference scores for the LSTM, Chronos and HTM are a
  release asset (about 100 MB).
- **Labels:** the onset times are the only labels. There are no per-hour labels.
- **Missing data:** hours without all of D, DF and NG, and hours failing a bad-data filter set
  from 2019 (values at or below zero, or above twice the 2019 99.9th percentile), are dropped
  before signals are built; the remaining hours form each grid's timeline.
- **Is it a sample?** No: it is every event meeting the rule in the period. It is small (8
  events, 7 from two storms), which limits what any comparison can show; see *Known biases*.
- **Personal or sensitive data:** none. All data are aggregate grid totals and public notices.

## Collection

- **EIA-930:** pulled from the EIA Open Data API in October 2026 (`scripts/pull_eia930.py`).
  EIA revises historical values, so the frozen snapshot, not the live API, defines v1.0; the
  script reports how far today's API has drifted.
- **Events and onsets:** from NERC *State of Reliability* reports, the FERC-NERC inquiry
  reports on Winter Storms Uri and Elliott, CAISO's root cause analysis of August 2020, and
  operators' own reports and regulatory filings (sources per event in events.yaml and
  events.md). Where the emergency declaration time is not published, a fallback fixed in
  advance moves onset earlier, never later.
- **Operator notices:** from operators' reports, filings, press releases and contemporaneous
  news coverage, collected by hand and checked against the sources listed per notice.
- **Who collected it:** the author. Every time and claim is tied to a cited source.

## Preprocessing

- Signals: forecast error (D - DF), imbalance (D - NG), and seasonal anomalies of D, NG and
  D - NG (value minus the median of the same hour 1 to 4 weeks earlier). No smoothing, no
  scaling beyond what each method does. The raw snapshot is kept, so other signal rules can be
  built from it.

## Uses

- **Intended:** comparing methods that warn of supply-shortfall load sheds from public grid
  data, at matched alert budgets; testing whether a method's warnings come early enough to
  matter; adding new methods through either track (scores or alerts).
- **Not intended:** estimating a method's detection rate in operation (8 events is a case
  series, not a sample of future emergencies); evaluating detection of transmission or
  distribution failures (excluded by design); ranking methods on differences of about one
  event; replacing operators' own situational awareness, which uses far more data.
- **Known biases and limits:**
  - Seven of eight events come from two winter storms; heat-driven and other shortfalls are
    underrepresented. The held-out events share storms with two development events.
  - Three events were used to design the shared alert rules; results on them are not
    independent tests.
  - The signals are balancing-authority totals: an event in a small part of a very large
    balancing authority (MISO South within MISO) is diluted.
  - The replay treats each hourly value as available at its time stamp; live EIA-930 data
    arrive with a short delay.
  - The status-quo row covers public notices only; operators' notices to the industry and their
    false alarms in ordinary years are not compiled.

## Distribution

- **Where:** https://github.com/gotham29/gridshedwatch, archived on Zenodo with every release
  (DOI [10.5281/zenodo.23626223](https://doi.org/10.5281/zenodo.23626223)); website
  https://gotham29.github.io/gridshedwatch.
- **License:** code MIT; event list, notices, documentation and results CC BY 4.0; EIA-930
  data U.S. public domain ([DATA_LICENSE.md](../DATA_LICENSE.md)).

## Maintenance

- **Maintainer:** Sam Heiserman (sam@htm-monitor.com); issues and pull requests on GitHub.
- **Versioning:** the benchmark version (events, data, rules, scoring) is separate from the
  package version; a package release never changes a score (CHANGELOG.md). Each new load shed
  that meets the rule is added in a new benchmark version, scored with the rules frozen in v1.0,
  and earlier versions stay reproducible from their tags.
- **Errata:** corrections to an onset or a notice are made in a new version, with the change
  and its source recorded in the change log; old results are not silently rewritten.
- **Contributions:** new results through pull requests (template in `.github/`); every result
  is listed.
