"""Power curve lookup and energy-loss calculation."""
import numpy as np
import pandas as pd

STEP_HOURS = 10 / 60
_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(15)
_GH_W = _GH_W / _GH_W.sum()


def power_from_wind(wind: pd.Series, curve: pd.DataFrame) -> pd.Series:
    """Interpolated power (kW) for each wind speed; NaN stays NaN, 0 outside the curve."""
    p = np.interp(wind, curve["wind_speed"], curve["power_kw"], left=0.0, right=0.0)
    return pd.Series(p, index=wind.index).where(wind.notna())


def expected_power(wind: pd.Series, curve: pd.DataFrame, sigma) -> pd.Series:
    """Average power if the true wind speed is `wind` ± a normal variation with std `sigma` (float or Series).

    The power curve is bent (convex below rated power), so plugging in one speed under-estimates the average
    power when the speed varies. This averages the curve over the variation instead: the model's prediction
    error and/or the turbulence inside the 10-minute interval.
    """
    if np.isscalar(sigma):
        if not sigma > 0:
            return power_from_wind(wind, curve)
        sig = sigma
    else:
        sig = sigma.reindex(wind.index).fillna(0.0).to_numpy()
    out = sum(w * power_from_wind((wind + sig * x).clip(lower=0), curve) for x, w in zip(_GH_X, _GH_W))
    return out.where(wind.notna())


def energy_kwh(power_kw: pd.Series) -> pd.Series:
    return power_kw * STEP_HOURS
