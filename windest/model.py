"""Explainable wind-speed transfer model: target ≈ slope * reference(t - lag) + intercept."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class LinearModel:
    slope: float
    intercept: float
    lag_steps: int
    resid_std: float
    corr: float
    n_train: int

    def predict(self, ref: pd.Series) -> pd.Series:
        pred = self.slope * ref.shift(self.lag_steps) + self.intercept
        return pred.clip(lower=0)


def fit(target: pd.Series, ref: pd.Series, max_lag_steps: int = 6) -> LinearModel:
    """Pick the reference lag with highest correlation, then fit OLS."""
    best = None
    for lag in range(0, max_lag_steps + 1):
        df = pd.concat([target, ref.shift(lag)], axis=1, keys=["y", "x"]).dropna()
        if len(df) < 10:
            continue
        c = df["y"].corr(df["x"])
        if best is None or c > best[0]:
            best = (c, lag, df)
    if best is None:
        raise ValueError("Not enough overlapping data to fit a model.")
    c, lag, df = best
    slope, intercept = np.polyfit(df["x"], df["y"], 1)
    resid = df["y"] - (slope * df["x"] + intercept)
    return LinearModel(float(slope), float(intercept), lag, float(resid.std()), float(c), len(df))
