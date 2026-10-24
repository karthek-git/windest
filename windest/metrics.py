import numpy as np
import pandas as pd


def rmse_mae(actual: pd.Series, pred: pd.Series) -> dict:
    d = pd.concat([actual, pred], axis=1, keys=["a", "p"]).dropna()
    if d.empty:
        return {"RMSE": np.nan, "MAE": np.nan, "n": 0}
    e = d["p"] - d["a"]
    return {"RMSE": float(np.sqrt((e**2).mean())), "MAE": float(e.abs().mean()), "n": len(d)}
