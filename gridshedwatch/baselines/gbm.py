"""Gradient-boosted forecaster. Needs: pip install lightgbm.

Per grid and signal, LightGBM predicts the next hour from the previous 24 hours, the same hour one
and two weeks earlier, and the hour of day and day of week; the score is the absolute error. Trained
on 2019 only (300 trees, learning rate 0.05, 31 leaves, early stopping on the last 10% of 2019),
then frozen. Seed k sets LightGBM's seed to 42 + 1000 k (bagging of rows and features makes runs
differ). Settings are common defaults, not tuned on events.
"""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p

LAGS = list(range(1, 25)) + [168, 336]
SEED_BASE = 42
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.8, verbose=-1, n_jobs=1)


def _features(x: pd.Series) -> pd.DataFrame:
    F = pd.DataFrame({f"lag{k}": x.shift(k) for k in LAGS}, index=x.index)
    F["hour"] = x.index.hour
    F["dow"] = x.index.dayofweek
    return F


def scores(grid: str, seed: int = 0) -> pd.DataFrame:
    import lightgbm as lgb

    X = data.signals(grid)
    cal_all = data.calibration(grid)
    b = data.bounds_2019(grid)
    ts = pd.DatetimeIndex(X["timestamp"])
    out = {}
    for f in SIGNALS:
        lo, hi = b[f]
        cal = ((cal_all[f].dropna() - lo) / (hi - lo)).asfreq("h")       # 2019 on a regular clock
        run = pd.Series(np.nan_to_num((X[f].to_numpy(float) - lo) / (hi - lo), nan=0.0), index=ts)
        Fc = _features(cal).dropna()
        yc = cal.loc[Fc.index].dropna()
        Fc = Fc.loc[yc.index]
        n_val = len(Fc) // 10
        m = lgb.LGBMRegressor(random_state=SEED_BASE + 1000 * seed, **PARAMS)
        m.fit(Fc.iloc[:-n_val], yc.iloc[:-n_val], eval_X=Fc.iloc[-n_val:], eval_y=yc.iloc[-n_val:],
              callbacks=[lgb.early_stopping(20, verbose=False)])
        full = pd.concat([cal, run]).sort_index()
        full = full[~full.index.duplicated(keep="last")].asfreq("h").ffill()   # last value held, as data.signals
        Fr = _features(full).loc[ts]
        raw = np.abs(m.predict(Fr) - run.to_numpy())
        out[f"p_{f}"] = np.round(to_p(raw), 6)
    return pd.DataFrame(out)
