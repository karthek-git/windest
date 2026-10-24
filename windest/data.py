"""Loading turbine time series / power curves and detecting outages."""
import io
import re
from pathlib import Path

import pandas as pd

STEP = pd.Timedelta("10min")


def read_table(name: str, raw: bytes) -> pd.DataFrame:
    buf = io.BytesIO(raw)
    if name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(buf)
    return pd.read_csv(buf, sep=None, engine="python")


def folder_items(folder: str) -> list[tuple[str, bytes]]:
    """All .xlsx/.csv files in a folder as (filename, bytes), skipping lock/temp files."""
    files = [p for p in sorted(Path(folder).glob("*")) if p.suffix.lower() in (".xlsx", ".csv")]
    return [(p.name, p.read_bytes()) for p in files if not p.name.startswith((".", "~"))]


def load_dataset(items) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Sort files into turbine time series and power curves by their columns.

    Time series need `timestamp` + `wind_speed`; power curves need `wind_speed` + `power` (kW).
    The turbine name comes from the `turbine_name` column (falls back to the file name).
    """
    turbines, curves = {}, {}
    for fname, raw in items:
        df = read_table(fname, raw)
        df.columns = [str(c).strip().lower() for c in df.columns]
        name = str(df["turbine_name"].dropna().iloc[0]) if "turbine_name" in df else Path(fname).stem.split("_")[0]
        if "timestamp" in df and "wind_speed" in df:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"]).drop_duplicates("timestamp").set_index("timestamp").sort_index()
            df = df.drop(columns=["turbine_name"], errors="ignore").asfreq(STEP)
            if "test_set" in df:
                df["test_set"] = df["test_set"].fillna(False).astype(bool)
            turbines[name] = df
        elif "wind_speed" in df and "power" in df:
            curves[name] = (df[["wind_speed", "power"]].rename(columns={"power": "power_kw"})
                            .apply(pd.to_numeric, errors="coerce").dropna().sort_values("wind_speed"))
    return turbines, curves


def park_of(turbine: str) -> str:
    """Turbines of one wind park share the name without the trailing number (T1 -> 'T', Nord_2 -> 'Nord')."""
    return re.sub(r"[\s_\-]*\d+$", "", turbine.strip()) or turbine


def align(frames: dict, index: pd.DatetimeIndex) -> dict:
    """Put every turbine frame on the same 10-minute time axis (NaN where a turbine has no data)."""
    return {k: v.reindex(index) for k, v in frames.items()}


def detect_outage(target: pd.Series, min_steps: int = 36):
    """(start, end) of the longest run of NaNs (>= min_steps, i.e. 6 h), else None.

    Random gaps and short communication gaps are shorter than a real outage.
    """
    isna = target.isna()
    if not isna.any():
        return None
    run_id = (isna != isna.shift()).cumsum()
    sizes = isna.groupby(run_id).agg(["first", "size"])
    sizes = sizes[sizes["first"] & (sizes["size"] >= min_steps)]
    if sizes.empty:
        return None
    idx = target.index[run_id == sizes["size"].idxmax()]
    return idx[0], idx[-1]
