# Changelog

The benchmark version (events, data, rules, scoring) and the package version are separate:
a package patch release never changes a score.

## 1.1.0 (2026-10-24)
- Alerts track: `gridshedwatch score-alerts FILE` scores any method's watch and warning start
  times (`gridshedwatch/alerts.py`), at the same budget plus a per-grid cap of 3x the budget.
  Template: `examples/my_alerts.py`.
- The five reference methods' alerts are published in `results/v1.0/alerts/`; scoring them
  reproduces the v1.0 table exactly (`tests/test_alerts.py`). `gridshedwatch score --alerts-out`
  writes any scores-track method's alerts in that format.
- No v1.0 setting or score changed.
- Website at https://gotham29.github.io/gridshedwatch (`docs/index.html`, built by
  `scripts/build_site.py` from `results/v1.0/` and the event files). No score changed.

## 1.0.1 (2026-10-23)
- Packaging fix: the EIA-930 snapshot now ships inside the package
  (`gridshedwatch/snapshot_v1.0/`), so a regular `pip install` works outside the repo. No data,
  rule or score changed; the snapshot checksums are identical.
- CI: a job that installs the package normally and runs it from outside the repo.

## 1.0.0 (2026-10-23)
- Benchmark v1.0: 8 events, EIA-930 snapshot 2019-2026, shared watch/warning rules,
  weather-service-style scoring, five reference methods. Reference scores are attached to the
  v1.0.0 GitHub release.
