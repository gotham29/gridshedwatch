"""The added baselines are causal (a score never depends on later data) and valid submissions."""
import numpy as np
import pytest

from gridshedwatch import data, submission
from gridshedwatch.baselines import random_scores, subpca

GRID = "lgee"
CUT = 30_000


def _perturbed(monkeypatch):
    real = data.signals(GRID).copy()
    fake = real.copy()
    cols = [c for c in fake.columns if c != "timestamp"]
    fake.loc[CUT:, cols] = fake.loc[CUT:, cols].to_numpy() * 3 + 7
    monkeypatch.setattr(data, "signals", lambda g: fake if g == GRID else real)


def _check_causal(fn, monkeypatch):
    before = fn(GRID)
    submission.check(before, GRID)
    _perturbed(monkeypatch)
    after = fn(GRID)
    assert np.array_equal(before.iloc[:CUT].to_numpy(), after.iloc[:CUT].to_numpy())
    assert not np.array_equal(before.iloc[CUT:].to_numpy(), after.iloc[CUT:].to_numpy())


def test_subpca_is_causal(monkeypatch):
    pytest.importorskip("sklearn")
    _check_causal(subpca.scores, monkeypatch)


def test_gbm_is_causal(monkeypatch):
    pytest.importorskip("lightgbm")
    from gridshedwatch.baselines import gbm
    _check_causal(lambda g: gbm.scores(g, 0), monkeypatch)


def test_random_scores_are_valid_and_seeded():
    a, b = random_scores.scores(GRID, 0), random_scores.scores(GRID, 1)
    submission.check(a, GRID)
    assert a.equals(random_scores.scores(GRID, 0))
    assert not a.equals(b)
