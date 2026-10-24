"""Loading wind CSVs and detecting outages."""
import pandas as pd

TZ = "Europe/Berlin"


def load_wind_csv(file) -> pd.Series:
    """Read a 'timestamp, wind speed' CSV into a 10-min indexed Series (NaN = missing)."""
    df = pd.read_csv(file, sep=None, engine="python")
    ts = pd.to_datetime(df.iloc[:, 0], errors="coerce", dayfirst=False)
    s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values, index=ts)
    s = s[s.index.notna()].sort_index()
    s = s[~s.index.duplicated(keep="first")]
    return s.asfreq("10min")


def load_power_curve(file) -> pd.DataFrame:
    """Read a power curve CSV: wind speed (m/s) | power (kW)."""
    df = pd.read_csv(file, sep=None, engine="python").iloc[:, :2]
    df.columns = ["wind_speed", "power_kw"]
    return df.apply(pd.to_numeric, errors="coerce").dropna().sort_values("wind_speed")


def detect_outage(target: pd.Series, min_steps: int = 6):
    """Return (start, end) of the longest run of NaNs in the target series, or None."""
    isna = target.isna()
    if not isna.any():
        return None
    run_id = (isna != isna.shift()).cumsum()
    runs = isna.groupby(run_id).agg(["first", "size"])
    runs = runs[runs["first"] & (runs["size"] >= min_steps)]
    if runs.empty:
        return None
    best = runs["size"].idxmax()
    idx = target.index[run_id == best]
    return idx[0], idx[-1]
