"""PatchTST forecaster (Nie et al., ICLR 2023), a current transformer baseline. Needs torch:
pip install gridshedwatch[lstm].

Per grid and signal (channel-independent, as in the paper), the model reads the previous 168 hours,
normalizes the window by its own mean and standard deviation (RevIN without affine terms), cuts it
into 13 patches of 24 hours with stride 12, and runs a 2-layer transformer encoder (d_model 64,
4 heads, feed-forward 128, dropout 0.1) with a flatten head that predicts the next hour. The score
is the absolute error in 2019-scaled units. Trained on 2019 only (Adam 1e-3, batch 64, up to 30
epochs, early stopping on the last 10% of 2019, patience 5), then frozen. Seed k uses torch seed
42 + 1000 k. Settings are the paper's small-model defaults adapted to hourly data, not tuned on
events.
"""
import numpy as np
import pandas as pd

from .. import data
from ..config import SIGNALS
from . import to_p

L, PATCH, STRIDE = 168, 24, 12
SEED_BASE = 42


def scores(grid: str, seed: int = 0, threads: int = 1) -> pd.DataFrame:
    from .lstm import _torch
    torch, nn = _torch()
    torch.set_num_threads(threads)
    n_patch = (L - PATCH) // STRIDE + 1

    class Net(nn.Module):
        def __init__(self, d=64, heads=4, layers=2, ff=128, drop=0.1):
            super().__init__()
            self.embed = nn.Linear(PATCH, d)
            self.pos = nn.Parameter(torch.zeros(n_patch, d))
            nn.init.uniform_(self.pos, -0.02, 0.02)
            enc = nn.TransformerEncoderLayer(d, heads, ff, drop, batch_first=True, norm_first=True)
            self.encoder = nn.TransformerEncoder(enc, layers, enable_nested_tensor=False)
            self.drop = nn.Dropout(drop)
            self.head = nn.Linear(n_patch * d, 1)

        def forward(self, x):                                     # x: (batch, L)
            mu, sd = x.mean(1, keepdim=True), x.std(1, keepdim=True) + 1e-5
            z = (x - mu) / sd
            p = z.unfold(1, PATCH, STRIDE)                         # (batch, n_patch, PATCH)
            h = self.encoder(self.embed(p) + self.pos)
            y = self.head(self.drop(h.flatten(1))).squeeze(-1)
            return y * sd.squeeze(-1) + mu.squeeze(-1)

    def windows(x):
        W = np.lib.stride_tricks.sliding_window_view(x, L + 1)
        return torch.tensor(W[:, :L], dtype=torch.float32), torch.tensor(W[:, L], dtype=torch.float32)

    def fit(model, X, y, s, max_epochs=30, patience=5):
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
        torch.manual_seed(SEED_BASE + 1000 * seed)
        net = fit(Net(), *windows(cal), SEED_BASE + 1000 * seed)
        full = np.concatenate([cal, run])
        Xw, yw = windows(full[len(cal) - L:])
        net.eval()
        with torch.no_grad():
            pred = torch.cat([net(x) for x in Xw.split(4096)])
        raw = (pred - yw).abs().numpy()
        out[f"p_{f}"] = np.round(to_p(raw), 6)
    return pd.DataFrame(out)
