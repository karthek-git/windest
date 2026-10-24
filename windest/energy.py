"""Power curve lookup and energy-loss calculation."""
import numpy as np
import pandas as pd

STEP_HOURS = 10 / 60


def power_from_wind(wind: pd.Series, curve: pd.DataFrame) -> pd.Series:
    p = np.interp(wind, curve["wind_speed"], curve["power_kw"], left=0.0, right=0.0)
    return pd.Series(p, index=wind.index).where(wind.notna())


def energy_kwh(power_kw: pd.Series, n_turbines: int = 1) -> pd.Series:
    return power_kw * STEP_HOURS * n_turbines
