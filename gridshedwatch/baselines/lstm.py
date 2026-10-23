"""LSTM forecaster (LSTM-AD, Malhotra et al., ESANN 2015). Needs: pip install gridshedwatch[lstm].

Per grid and signal, a 2-layer, 64-unit LSTM reads the previous 24 hours and predicts the next;
the score is the absolute error. Signals are scaled by their 2019 0.1-99.9th percentile range.
Trained on 2019 only (Adam 1e-3, batch 64, up to 50 epochs, early stopping on the last 10% of
2019), then frozen. Seed k uses torch seed 42 + 1000 k. Settings are common defaults, not tuned
on events. Expect about an hour per seed on a laptop CPU.
"""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p

L = 24
SEED_BASE = 42


def _torch():
    try:
        import torch
        from torch import nn
    except ImportError as e:                      # pragma: no cover
        raise ImportError("the LSTM baseline needs torch: pip install gridshedwatch[lstm]") from e
    return torch, nn


def scores(grid: str, seed: int = 0, threads: int = 1) -> pd.DataFrame:
    torch, nn = _torch()
    torch.set_num_threads(threads)

    class Net(nn.Module):
        def __init__(self, hidden=64, layers=2):
            super().__init__()
            self.lstm = nn.LSTM(1, hidden, num_layers=layers, batch_first=True)
            self.head = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1]).squeeze(-1)

    def windows(x):
        W = np.lib.stride_tricks.sliding_window_view(x, L + 1)
        return torch.tensor(W[:, :L, None], dtype=torch.float32), torch.tensor(W[:, L], dtype=torch.float32)

    def fit(model, X, y, s, max_epochs=50, patience=5):
        torch.manual_seed(s)
        n_val = max(1, len(X) // 10)
        Xtr, ytr, Xva, yva = X[:-n_val], y[:-n_val], X[-n_val:], y[-n_val:]
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        best, state, bad = np.inf, None, 0
        g = torch.Generator().manual_seed(s)
        for _ in range(max_epochs):
            model.train()
            for idx in torch.randperm(len(Xtr), generator=g).split(64):
                opt.zero_grad()
                nn.functional.mse_loss(model(Xtr[idx]), ytr[idx]).backward()
                opt.step()
            model.eval()
            with torch.no_grad():
                v = nn.functional.mse_loss(model(Xva), yva).item()
            if v < best - 1e-6:
                best, state, bad = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= patience:
                    break
        model.load_state_dict(state)
        return model

    X = data.signals(grid)
    cal_all = data.calibration(grid)
    b = data.bounds_2019(grid)
    out = {}
    for f in SIGNALS:
        lo, hi = b[f]
        cal = (cal_all[f].dropna().to_numpy(float) - lo) / (hi - lo)
        run = np.nan_to_num((X[f].to_numpy(float) - lo) / (hi - lo), nan=0.0)
        net = fit(Net(), *windows(cal), SEED_BASE + 1000 * seed)
        full = np.concatenate([cal, run])
        Xw, yw = windows(full[len(cal) - L:])
        net.eval()
        with torch.no_grad():
            pred = torch.cat([net(x) for x in Xw.split(4096)])
        raw = (pred - yw).abs().numpy()
        out[f"p_{f}"] = np.round(to_p(raw), 6)
    return pd.DataFrame(out)
