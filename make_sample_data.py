"""Generate synthetic sample data (reference + target farm, with a simulated outage)."""
import numpy as np
import pandas as pd

rng = np.random.default_rng(0)
idx = pd.date_range("2024-03-01", periods=30 * 144, freq="10min", tz="Europe/Berlin").tz_localize(None)
base = pd.Series(8 + 3 * np.sin(np.arange(len(idx)) / 200) + rng.normal(0, 1, len(idx)).cumsum() * 0.02, index=idx)
base = base.rolling(6, min_periods=1).mean().clip(lower=0.3)
ref = (base + rng.normal(0, 0.4, len(idx))).clip(lower=0)
tgt = (0.95 * base + 0.3 + rng.normal(0, 0.5, len(idx))).clip(lower=0)
tgt_out = tgt.copy()
tgt_out.loc["2024-03-25 06:00":"2024-03-26 18:00"] = np.nan
ref.rename("wind_speed").to_csv("sample_data/reference.csv", index_label="timestamp")
tgt_out.rename("wind_speed").to_csv("sample_data/target.csv", index_label="timestamp")
tgt.rename("wind_speed").to_csv("sample_data/target_truth.csv", index_label="timestamp")
v = np.arange(0, 26)
p = np.clip(3000 / (1 + np.exp(-(v - 8))) , 0, 3000); p[v < 3] = 0; p[v >= 25] = 0
pd.DataFrame({"wind_speed": v, "power_kw": p.round(0)}).to_csv("sample_data/power_curve.csv", index=False)
