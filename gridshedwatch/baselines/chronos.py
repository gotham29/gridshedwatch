"""Chronos-Bolt, zero-shot (Ansari et al., 2024). Needs: pip install gridshedwatch[chronos].

Per grid and signal, the pretrained model forecasts the next hour from the previous 512 (the 2019
tail supplies the context for the first run hours); score = |actual - median forecast|. No
training or tuning, so it is deterministic. Caveat: the pretraining corpus includes public
electricity data, so overlap with 2020-2026 EIA-930 cannot be ruled out.
"""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p

CTX = 512
MODEL = "amazon/chronos-bolt-small"


def scores(grid: str, model: str = MODEL, device: str = "cpu", batch: int = 1024) -> pd.DataFrame:
    try:
        import torch
        from chronos import BaseChronosPipeline
    except ImportError as e:                      # pragma: no cover
        raise ImportError("the Chronos baseline needs: pip install gridshedwatch[chronos]") from e
    pipe = BaseChronosPipeline.from_pretrained(model, device_map=device, torch_dtype=torch.float32)
    X = data.signals(grid)
    cal_all = data.calibration(grid)
    out = {}
    for f in SIGNALS:
        cal = cal_all[f].dropna().to_numpy(float)
        run = np.nan_to_num(X[f].to_numpy(float), nan=float(np.nanmedian(cal)))
        full = np.concatenate([cal[-CTX:], run]).astype(np.float32)
        W = np.lib.stride_tricks.sliding_window_view(full, CTX + 1)
        raw = np.empty(len(W), dtype=np.float32)
        for a in range(0, len(W), batch):
            q, _ = pipe.predict_quantiles(torch.tensor(W[a:a + batch, :CTX]), prediction_length=1, quantile_levels=[0.5])
            raw[a:a + batch] = np.abs(W[a:a + batch, CTX] - q[:, 0, 0].numpy())
        out[f"p_{f}"] = np.round(to_p(raw), 6)
    return pd.DataFrame(out)
