"""Explainable wind-speed transfer model.

target(t) ≈ b + Σ_park  w_park · mean_of_turbines_in_park(t)

One park-average per reference park, lightly smoothed in time, combined by least squares.
Optionally the weights are fitted separately for each wind-direction sector (the reference
direction tells us which way the wind blows, and so how the two sites are exposed to it).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import park_of

RIDGE = 1.0  # light shrinkage so sparsely populated sectors stay stable


def park_means(turbines: dict[str, pd.DataFrame], parks: list[str], column="wind_speed") -> pd.DataFrame:
    """Average of `column` over all turbines of each park (NaNs skipped)."""
    out = {}
    for p in parks:
        cols = [df[column] for n, df in turbines.items() if park_of(n) == p]
        if cols:
            out[p] = pd.concat(cols, axis=1).mean(axis=1)
    return pd.DataFrame(out)


def ref_direction(turbines: dict[str, pd.DataFrame], parks: list[str], smooth: int = 3) -> pd.Series:
    """Circular mean wind direction (deg) over all turbines of the reference parks."""
    th = [np.deg2rad(df["wind_direction"]) for n, df in turbines.items() if park_of(n) in parks and "wind_direction" in df]
    if not th:
        return pd.Series(np.nan, index=next(iter(turbines.values())).index)
    s = pd.concat([np.sin(t) for t in th], axis=1).mean(axis=1)
    c = pd.concat([np.cos(t) for t in th], axis=1).mean(axis=1)
    if smooth > 1:
        s, c = (x.rolling(smooth, center=True, min_periods=1).mean() for x in (s, c))
    return pd.Series(np.rad2deg(np.arctan2(s, c)) % 360, index=s.index)


def smooth_means(x: pd.DataFrame, window: int) -> pd.DataFrame:
    return x if window <= 1 else x.rolling(window, center=True, min_periods=1).mean()


_smooth = smooth_means


def sector_label(i: int, n: int) -> str:
    deg = i * 360 / n
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return f"{names[i]} ({deg:.0f}°)" if n == 8 else f"{deg:.0f}°"


EXTRAS = {
    "turbulence": "Reference turbulence (wind-speed std. dev.)",
    "temperature": "Reference temperature",
    "pressure": "Reference air pressure",
    "pressure_trend": "Air-pressure change over 3 h",
    "time_of_day": "Time of day",
    "wind_trend": "Reference wind, 6 h mean",
    "wind_ramp": "Reference wind change ±1 h",
}
EXTRA_COLS = {"time_of_day": ["tod_sin", "tod_cos"], "wind_ramp": ["ramp_past", "ramp_next"]}


def build_extras(turbines: dict[str, pd.DataFrame], parks: list[str], names, smooth: int = 5) -> pd.DataFrame:
    """Additional predictors from the *reference* turbines (the affected ones have no data in an outage).

    Variables that are missing or constant at a park (e.g. air pressure and std. dev. at park O) are skipped.
    """
    ref = {n: df for n, df in turbines.items() if park_of(n) in parks}
    idx = next(iter(turbines.values())).index

    def avg(col):
        cols = [df[col] for df in ref.values() if col in df and df[col].std() > 1e-6]
        return pd.concat(cols, axis=1).mean(axis=1) if cols else None

    out = {}
    ref_speed = park_means(turbines, parks).mean(axis=1)
    for name in names:
        if name == "wind_trend":
            out[name] = ref_speed.rolling(36, center=True, min_periods=6).mean()
            continue
        if name == "wind_ramp":
            out["ramp_past"], out["ramp_next"] = ref_speed - ref_speed.shift(6), ref_speed.shift(-6) - ref_speed
            continue
        if name == "time_of_day":
            h = idx.hour + idx.minute / 60
            out["tod_sin"], out["tod_cos"] = (pd.Series(f(2 * np.pi * h / 24), index=idx) for f in (np.sin, np.cos))
            continue
        col = {"turbulence": "wind_speed_stddev", "temperature": "ambient_temperature",
               "pressure": "air_pressure", "pressure_trend": "air_pressure"}[name]
        v = avg(col)
        if v is None:
            continue
        if name == "pressure_trend":
            v = v.diff(18)
        out[name] = v.rolling(smooth, center=True, min_periods=1).mean() if smooth > 1 else v
    return pd.DataFrame(out, index=idx)


def _design(x: pd.DataFrame, direction: pd.Series, sectors: int, extras: pd.DataFrame | None = None) -> pd.DataFrame:
    """Columns: per sector, an indicator (intercept) and each park's speed times the indicator; then extras."""
    w = 360 / max(sectors, 1)
    if sectors <= 1:
        sec = pd.Series(0.0, index=x.index)
    else:
        sec = ((direction + w / 2) % 360 // w).reindex(x.index)
    cols = {}
    for s in range(max(sectors, 1)):
        ind = (sec == s).astype(float)
        cols[(s, "1")] = ind
        for p in x.columns:
            cols[(s, p)] = x[p] * ind
    X = pd.DataFrame(cols)
    if extras is not None and not extras.empty:
        for c in extras.columns:
            X[("x", c)] = extras[c].reindex(x.index)
    return X.where(sec.notna() & x.notna().all(axis=1), np.nan)


def _ridge_lstsq(A: np.ndarray, y: np.ndarray) -> np.ndarray:
    scale = A.std(axis=0)
    scale[scale == 0] = 1
    B = A / scale
    beta = np.linalg.solve(B.T @ B + RIDGE * np.eye(B.shape[1]), B.T @ y)
    return beta / scale


@dataclass
class ParkModel:
    parks: list
    sectors: int
    smooth: int
    coef: np.ndarray          # plain model (no sectors): weight per park
    intercept: float
    beta: np.ndarray | None   # sector (+extras) model coefficients
    beta_base: np.ndarray | None  # sector model without extras, used where extras are missing
    extra_cols: list
    fb_slope: float           # fallback on the mean of the available parks
    fb_intercept: float
    resid_std: float
    r2: float
    n_train: int

    def predict(self, means: pd.DataFrame, direction: pd.Series, extras: pd.DataFrame | None = None) -> pd.Series:
        x = _smooth(means[self.parks], self.smooth)
        pred = pd.Series(np.nan, index=x.index)
        full = x.notna().all(axis=1)
        pred[full] = x[full].values @ self.coef + self.intercept
        if self.beta_base is not None:
            X = _design(x, direction, self.sectors)
            ok = X.notna().all(axis=1)
            pred[ok] = X[ok].values @ self.beta_base
        if self.beta is not None:
            ex = extras[self.extra_cols] if self.extra_cols and extras is not None else None
            X = _design(x, direction, self.sectors, ex)
            ok = X.notna().all(axis=1)
            pred[ok] = X[ok].values @ self.beta
        part = pred.isna() & x.notna().any(axis=1)
        pred[part] = self.fb_slope * x[part].mean(axis=1) + self.fb_intercept
        return pred.clip(lower=0)

    def sector_table(self) -> pd.DataFrame | None:
        """Weights per direction sector (rows) and park (columns), of the model without extras."""
        beta = self.beta_base if self.extra_cols else self.beta
        if beta is None or self.sectors <= 1:
            return None
        k = len(self.parks) + 1
        rows = {sector_label(s, self.sectors): dict(zip(self.parks + ["intercept"],
                                                        np.r_[beta[s * k + 1:(s + 1) * k], beta[s * k]]))
                for s in range(self.sectors)}
        return pd.DataFrame(rows).T

    def extra_weights(self) -> pd.Series | None:
        if self.beta is None or not self.extra_cols:
            return None
        return pd.Series(self.beta[-len(self.extra_cols):], index=self.extra_cols)


def fit(target: pd.Series, means: pd.DataFrame, direction: pd.Series, train_mask: pd.Series,
        smooth: int = 3, sectors: int = 1, extras: pd.DataFrame | None = None) -> ParkModel:
    parks = list(means.columns)
    x = _smooth(means, smooth)
    y = target.where(train_mask).rename("y")
    full = pd.concat([y, x], axis=1).dropna()
    if len(full) < 50:
        raise ValueError("Not enough overlapping data between target and reference to fit a model.")
    yv = full["y"].to_numpy()
    A = np.c_[full[parks].to_numpy(), np.ones(len(full))]
    plain = np.linalg.lstsq(A, yv, rcond=None)[0]
    fb = pd.concat([y, x.mean(axis=1).rename("xm")], axis=1).dropna()
    fs, fi = np.polyfit(fb["xm"], fb["y"], 1)

    def solve(ex):
        d = pd.concat([y, _design(x, direction, sectors, ex)], axis=1).dropna()
        if len(d) < 50:
            return None, None, None
        A_, y_ = d.iloc[:, 1:].to_numpy(), d["y"].to_numpy()
        b = _ridge_lstsq(A_, y_)
        return b, y_ - A_ @ b, y_

    beta = beta_base = None
    resid, yfit = yv - A @ plain, yv
    extra_cols = list(extras.columns) if extras is not None and not extras.empty else []
    if sectors > 1 or extra_cols:
        if extra_cols:
            beta_base = solve(None)[0]
        b1, r1, y1 = solve(extras if extra_cols else None)
        if b1 is not None:
            beta, resid, yfit = b1, r1, y1
        else:
            extra_cols, beta_base = [], None
    return ParkModel(parks, sectors, smooth, plain[:-1], float(plain[-1]), beta, beta_base, extra_cols,
                     float(fs), float(fi), float(resid.std()), float(1 - resid.var() / yfit.var()), len(yfit))


# ---------------------------------------------------------------------------------------------
# Classic single-reference MCP (Measure-Correlate-Predict) variants, for comparison
# ---------------------------------------------------------------------------------------------
METHODS = {
    "Park regression (default)": "reg",
    "OLS MCP": "ols",
    "Variance-ratio MCP": "vr",
    "Orthogonal (TLS) MCP": "tls",
    "Binned MCP": "bin",
}
BIN_WIDTH, BIN_MIN_N = 1.0, 20


@dataclass
class MCPModel:
    kind: str
    smooth: int
    parks: list
    coef: np.ndarray            # slope (nan for binned)
    intercept: float
    centers: np.ndarray | None  # binned: reference-bin centres
    levels: np.ndarray | None   # binned: mean target speed per bin
    resid_std: float
    r2: float
    n_train: int
    beta = None
    sectors = 1

    def predict(self, means: pd.DataFrame, direction=None, extras=None) -> pd.Series:
        r = _smooth(means[self.parks], self.smooth).mean(axis=1)
        if self.kind == "bin":
            p = pd.Series(np.interp(r, self.centers, self.levels), index=r.index).where(r.notna())
        else:
            p = self.coef[0] * r + self.intercept
        return p.clip(lower=0)

    def sector_table(self):
        return None


def fit_mcp(kind: str, target: pd.Series, means: pd.DataFrame, train_mask: pd.Series, smooth: int = 3) -> MCPModel:
    """One reference series (mean of the reference parks) and one transfer function.

    ols  slope = r·σy/σx          (least squares, lowest wind RMSE, shrinks the spread)
    vr   slope = σy/σx            (variance ratio, keeps the spread of the wind)
    tls  slope from orthogonal regression (errors in both series)
    bin  mean target speed per 1 m/s reference bin, interpolated
    """
    r = _smooth(means, smooth).mean(axis=1).rename("x")
    d = pd.concat([target.where(train_mask).rename("y"), r], axis=1).dropna()
    if len(d) < 50:
        raise ValueError("Not enough overlapping data between target and reference to fit a model.")
    x, y = d["x"].to_numpy(), d["y"].to_numpy()
    sx, sy, rho = x.std(ddof=1), y.std(ddof=1), np.corrcoef(x, y)[0, 1]
    centers = levels = None
    if kind == "ols":
        a = rho * sy / sx
    elif kind == "vr":
        a = sy / sx
    elif kind == "tls":
        sxy = np.cov(x, y)[0, 1]
        a = (sy**2 - sx**2 + np.sqrt((sy**2 - sx**2) ** 2 + 4 * sxy**2)) / (2 * sxy)
    elif kind == "bin":
        b = np.floor(x / BIN_WIDTH)
        g = pd.DataFrame({"y": y, "b": b}).groupby("b")["y"].agg(["mean", "size"])
        g = g[g["size"] >= BIN_MIN_N]
        centers, levels = (g.index.to_numpy() + 0.5) * BIN_WIDTH, g["mean"].to_numpy()
        a = np.nan
    else:
        raise ValueError(kind)
    b0 = float(y.mean() - a * x.mean()) if kind != "bin" else np.nan
    m = MCPModel(kind, smooth, list(means.columns), np.array([a]), b0, centers, levels, 0.0, 0.0, len(d))
    res = y - m.predict(means).reindex(d.index).to_numpy()
    m.resid_std, m.r2 = float(res.std()), float(1 - res.var() / y.var())
    return m


# ---------------------------------------------------------------------------------------------
# Air density (from temperature and pressure) for the power-curve correction
# ---------------------------------------------------------------------------------------------
R_DRY_AIR = 287.05  # J/(kg·K)
RHO_STD = 1.225     # kg/m³, density at which manufacturer power curves are normally given


def air_density(temp_c, pres_hpa):
    """Dry-air density in kg/m³ from the ideal gas law (humidity ignored)."""
    return pres_hpa * 100 / (R_DRY_AIR * (temp_c + 273.15))


def atmos_reference(turbines: dict[str, pd.DataFrame], parks: list[str], smooth: int = 5) -> pd.DataFrame:
    """Reference temperature and pressure: averages over the reference turbines (constant series skipped)."""
    out = {}
    for key, col in (("temp", "ambient_temperature"), ("pres", "air_pressure")):
        cols = [df[col] for n, df in turbines.items() if park_of(n) in parks and col in df and df[col].std() > 1e-6]
        if cols:
            v = pd.concat(cols, axis=1).mean(axis=1)
            out[key] = v.rolling(smooth, center=True, min_periods=1).mean() if smooth > 1 else v
    return pd.DataFrame(out)


@dataclass
class AtmosModel:
    lines: dict           # {"temp": (slope, intercept), "pres": (slope, intercept)}
    rmse: dict            # in-sample RMSE of each line

    def predict(self, ref: pd.DataFrame) -> pd.DataFrame:
        t = self.lines["temp"][0] * ref["temp"] + self.lines["temp"][1]
        p = self.lines["pres"][0] * ref["pres"] + self.lines["pres"][1]
        return pd.DataFrame({"temp": t, "pres": p, "rho": air_density(t, p)})


def fit_atmos(df: pd.DataFrame, ref: pd.DataFrame, train_mask: pd.Series) -> AtmosModel | None:
    """Predict the affected turbine's temperature and pressure from the references (straight lines).

    Returns None if the turbine has no temperature/pressure data or the references lack them.
    """
    lines, rmse = {}, {}
    for key, col in (("temp", "ambient_temperature"), ("pres", "air_pressure")):
        if key not in ref or col not in df:
            return None
        d = pd.concat([df[col].where(train_mask).rename("y"), ref[key].rename("x")], axis=1).dropna()
        if len(d) < 50 or d["y"].std() < 1e-6:
            return None
        a, b = np.polyfit(d["x"], d["y"], 1)
        lines[key], rmse[key] = (float(a), float(b)), float(np.sqrt(((a * d["x"] + b - d["y"]) ** 2).mean()))
    return AtmosModel(lines, rmse)


def fit_line(target: pd.Series, ref: pd.Series, train_mask: pd.Series):
    """Straight line target ≈ a·ref + b on the training rows; None if there is too little (or constant) data."""
    d = pd.concat([target.where(train_mask).rename("y"), ref.rename("x")], axis=1).dropna()
    if len(d) < 50 or d["y"].std() < 1e-6:
        return None
    a, b = np.polyfit(d["x"], d["y"], 1)
    return float(a), float(b)


def line_predict(line, ref: pd.Series) -> pd.Series:
    return (line[0] * ref + line[1]).clip(lower=0)


# ---------------------------------------------------------------------------------------------
# Automatic selection of reference turbines
# ---------------------------------------------------------------------------------------------
def select_references(target: pd.Series, ref_turbines: dict, usable: pd.Series, smooth: int = 5, folds: int = 6,
                      min_gain: float = 0.005, max_candidates: int = 15) -> dict:
    """Choose the reference turbines that predict the target best.

    Score of a set = RMSE of a plain park-average regression, cross-validated with `folds` contiguous
    time blocks over the `usable` rows (so no outage or test rows are ever used).
    Steps: 1) greedy forward selection, a turbine is added while it lowers the score by >= `min_gain`;
           2) swap pass, replace a chosen turbine by an unchosen one if that lowers the score by >= `min_gain`;
           3) drop pass, remove a turbine if the score does not get worse.
    Returns the selected names, a step table and a ranking of every turbine on its own.
    """
    usable = usable.fillna(False).astype(bool)
    pos = usable.cumsum().to_numpy()
    fold = pd.Series(np.minimum((pos - 1) * folds // max(pos.max(), 1), folds - 1), index=usable.index)
    nodir = pd.Series(np.nan, index=usable.index)
    memo: dict = {}

    def score(sel) -> float:
        key = frozenset(sel)
        if key in memo:
            return memo[key]
        parks = sorted({park_of(n) for n in sel})
        means = park_means({n: ref_turbines[n] for n in sel}, parks)
        se, cnt = 0.0, 0
        try:
            for k in range(folds):
                te = usable & (fold == k)
                m = fit(target, means, nodir, usable & (fold != k), smooth, 1)
                p = m.predict(means, nodir)
                ok = (te & target.notna() & p.notna()).to_numpy()
                e = (p - target).to_numpy()[ok]
                se, cnt = se + float((e**2).sum()), cnt + int(ok.sum())
        except ValueError:
            memo[key] = np.inf
            return np.inf
        memo[key] = float(np.sqrt(se / cnt)) if cnt else np.inf
        return memo[key]

    singles = {n: score([n]) for n in ref_turbines}
    corr = {n: float(target.where(usable).corr(ref_turbines[n]["wind_speed"])) for n in ref_turbines}
    ranked = sorted(singles, key=singles.get)
    if not np.isfinite(singles[ranked[0]]):
        raise ValueError("No reference turbine overlaps the outage turbine's data well enough to use.")
    cands = ranked[:max_candidates]

    steps, sel, cur = [], [], np.inf

    def log(action, name):
        steps.append({"Step": len(steps) + 1, "Action": action, "Turbine": name, "Turbines in set": len(sel),
                      "CV RMSE (m/s)": cur, "Change (%)": (cur / prev - 1) * 100 if np.isfinite(prev) else np.nan})

    prev = np.inf
    while len(sel) < len(cands):                                  # 1) greedy forward selection
        best = min((c for c in cands if c not in sel), key=lambda c: score(sel + [c]))
        sc = score(sel + [best])
        if sel and sc > cur * (1 - min_gain):
            break
        prev, sel, cur = cur, sel + [best], sc
        log("add", best)
    for _ in range(3):                                            # 2) swap pass
        moved = False
        for c in list(sel):
            for o in (x for x in cands if x not in sel):
                trial = [o if x == c else x for x in sel]
                sc = score(trial)
                if sc < cur * (1 - min_gain):
                    prev, sel, cur, moved = cur, trial, sc, True
                    log(f"swap {c} →", o)
                    break
            if moved:
                break
        if not moved:
            break
    for c in list(sel):                                           # 3) drop pass
        trial = [x for x in sel if x != c]
        if trial and score(trial) <= cur:
            prev, sel, cur = cur, trial, score(trial)
            log("drop", c)

    ranking = pd.DataFrame({"Turbine": ranked, "CV RMSE alone (m/s)": [singles[n] for n in ranked],
                            "Correlation": [corr[n] for n in ranked],
                            "Selected": [n in sel for n in ranked]})
    return dict(selected=sel, steps=pd.DataFrame(steps), ranking=ranking, cv_rmse=cur)
