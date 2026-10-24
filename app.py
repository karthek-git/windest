import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from windest import data, energy, metrics, model, report, viz

st.set_page_config(page_title="Wind outage estimator", page_icon=":material/air:", layout="wide",
                   initial_sidebar_state="collapsed")

SAMPLE_FOLDER = "data_hackathon_baywa_re"
Z = 1.2816  # 80 % two-sided band
# Chart colours (BayWa green for predictions, olive for measurements, red for losses)
C_PRIMARY, C_MEASURED, C_ERROR = "#018249", "#8CA52B", "#B3261E"


@st.cache_data(show_spinner="Reading turbine files…", max_entries=8)
def load(items):
    return data.load_dataset(items)


def read(files):
    return tuple((f.name, f.getvalue()) for f in files or [])


# ---------------- Step 1: upload ----------------
if st.session_state.get("dataset") is None:
    st.title(":material/air: Wind outage estimator")
    st.caption("Estimate the energy lost during a turbine data outage from the wind measured at reference turbines.")
    with st.container(horizontal=True):
        st.badge("1  Upload data", icon=":material/upload_file:", color="primary")
        st.badge("2  Review settings", icon=":material/tune:", color="gray")
        st.badge("3  Results", icon=":material/insights:", color="gray")

    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.subheader(":material/wind_power: Outage turbines")
        st.caption("Wind data of the affected turbine(s). The outage is the gap (NaN) in the series.")
        f_target = st.file_uploader("Outage turbine data", type=["xlsx", "csv"], accept_multiple_files=True,
                                    key="up_target", label_visibility="collapsed")
    with c2.container(border=True):
        st.subheader(":material/sensors: Reference turbines")
        st.caption("Neighbouring turbines with data during the outage. Add as many as you have.")
        f_ref = st.file_uploader("Reference turbine data", type=["xlsx", "csv"], accept_multiple_files=True,
                                 key="up_ref", label_visibility="collapsed")
    with c3.container(border=True):
        st.subheader(":material/show_chart: Power curves")
        st.caption("One power curve (wind speed in m/s, power in kW) per outage turbine.")
        f_curve = st.file_uploader("Power curves", type=["xlsx", "csv"], accept_multiple_files=True,
                                   key="up_curve", label_visibility="collapsed")
    st.caption("Time series need `timestamp` and `wind_speed` (10-minute values); optional `wind_direction`, "
               "`ambient_temperature`, `air_pressure`, `wind_speed_stddev`. Files are recognised by their columns, "
               "and the turbine name comes from `turbine_name` (or the file name).")

    try:
        t_tur, t_cur = load(read(f_target)) if f_target else ({}, {})
        r_tur, r_cur = load(read(f_ref)) if f_ref else ({}, {})
        _, c_cur = load(read(f_curve)) if f_curve else ({}, {})
    except Exception as e:
        st.error(f"Could not read the files: {e}", icon=":material/error:")
        st.stop()
    have_curves = {**r_cur, **t_cur, **c_cur}
    refs_found = [n for n in r_tur if n not in t_tur]
    missing = [t for t in t_tur if t not in have_curves]

    with st.container(border=True):
        st.subheader(":material/fact_check: Review")
        if not (t_tur or refs_found or have_curves):
            st.caption("Nothing uploaded yet. Add files above, or try the sample data.")
        else:
            st.markdown("**Outage turbines** " + (" ".join(f":blue-badge[{n}]" for n in sorted(t_tur)) or ":gray-badge[none]"))
            st.markdown("**Reference turbines** " + (" ".join(f":green-badge[{n}]" for n in sorted(refs_found)) or ":gray-badge[none]"))
            st.markdown("**Power curves** " + (" ".join(f":violet-badge[{n}]" for n in sorted(have_curves)) or ":gray-badge[none]"))
            for t, df in t_tur.items():
                gap = data.detect_outage(df["wind_speed"])
                if gap:
                    st.caption(f":material/check_circle: {t}: outage found, {gap[0]:%d %b %Y %H:%M} to {gap[1]:%d %b %Y %H:%M}")
                else:
                    st.caption(f":material/info: {t}: no gap longer than 6 h found, you can set the period by hand next.")
            if t_tur and not refs_found:
                st.warning("Add at least one reference turbine.", icon=":material/warning:")
            if missing:
                st.warning(f"No power curve for {', '.join(sorted(missing))}.", icon=":material/warning:")
            if refs_found and not t_tur:
                st.warning("Add the data of at least one outage turbine.", icon=":material/warning:")
    ready = bool(t_tur and refs_found and not missing)

    with st.container(horizontal=True):
        if st.button("Analyze outage", type="primary", icon=":material/play_arrow:", disabled=not ready):
            st.session_state.dataset = dict(target=read(f_target), reference=read(f_ref), curves=read(f_curve))
            st.rerun()
        if st.button("Use hackathon sample data", icon=":material/science:"):
            items = data.folder_items(SAMPLE_FOLDER)
            if not items:
                st.error(f"Sample folder `{SAMPLE_FOLDER}` not found.", icon=":material/error:")
            else:
                st.session_state.dataset = dict(
                    target=tuple(i for i in items if i[0].upper().startswith("T")),
                    reference=tuple(i for i in items if not i[0].upper().startswith("T")), curves=())
                st.rerun()
    st.stop()

# ---------------- Step 2/3: load the uploaded data ----------------
ds = st.session_state.dataset
try:
    t_tur, t_cur = load(ds["target"])
    r_tur, r_cur = load(ds["reference"])
    _, c_cur = load(ds["curves"]) if ds["curves"] else ({}, {})
except Exception as e:
    st.error(f"Could not read the data: {e}", icon=":material/error:")
    st.session_state.dataset = None
    st.stop()
data_key = hash((ds["target"], ds["reference"], ds["curves"]))
curves = {**r_cur, **t_cur, **c_cur}
tgt_turbines = t_tur
ref_turbines = {k: v for k, v in r_tur.items() if k not in t_tur}

top, top_btn = st.columns([5, 1], vertical_alignment="center")
top.title(":material/air: Wind outage estimator")
top.caption(":material/tune: Settings are in the sidebar, open it with the arrow at the top left.")
if top_btn.button("Change data", icon=":material/upload_file:", width="stretch"):
    st.session_state.dataset = None
    st.rerun()

# ---------------- Sidebar: settings ----------------
names = sorted(tgt_turbines)
with st.sidebar:
    st.subheader(":material/wind_power: Turbines")
    targets = st.multiselect("Outage turbines", names, default=names)
    if not targets:
        st.info("Select at least one outage turbine.")
        st.stop()
    ref_parks_all = sorted({data.park_of(n) for n in ref_turbines})
    ref_mode = st.segmented_control("Reference turbines", ["Automatic", "Manual"], default="Automatic",
                                    help="Automatic: the tool picks the best reference turbines for each outage "
                                         "turbine from everything you uploaded. Manual: choose whole wind parks.") or "Automatic"
    if ref_mode == "Manual":
        ref_parks = st.multiselect("Reference wind parks", ref_parks_all, default=ref_parks_all,
                                   help="Reference turbines are grouped by name without the number (H1, H2 → park H).")
        if not ref_parks:
            st.info("Select at least one reference park.")
            st.stop()
    else:
        ref_parks = ref_parks_all
        st.caption("Picked per outage turbine, see the Method tab.")

    lead = tgt_turbines[targets[0]]["wind_speed"]
    tgt_turbines = data.align(tgt_turbines, lead.index)
    ref_turbines = data.align(ref_turbines, lead.index)
    auto = data.detect_outage(lead)
    span = (lead.index[0].to_pydatetime(), lead.index[-1].to_pydatetime())
    d0 = auto or (lead.index[-432], lead.index[-1])
    st.subheader(":material/schedule: Outage period")
    start, end = st.slider("Outage", span[0], span[1], (d0[0].to_pydatetime(), d0[1].to_pydatetime()),
                           step=pd.Timedelta("10min").to_pytimedelta(), format="DD MMM HH:mm",
                           label_visibility="collapsed")
    st.caption("Detected automatically as the longest gap in the data." if auto else
               "No gap detected, set the period manually.")
    start, end = pd.Timestamp(start), pd.Timestamp(end)

    st.subheader(":material/tune: Model")
    method_name = st.selectbox("Method", list(model.METHODS),
                               help="The default combines the reference parks and wind direction. The others are "
                                    "classic single-reference MCP methods (Measure-Correlate-Predict) for comparison.")
    mk = model.METHODS[method_name]
    is_reg = mk == "reg"
    smooth = st.select_slider("Smoothing of reference (10-min steps)", [1, 3, 5], value=5)
    sectors = st.select_slider("Wind-direction sectors", [1, 4, 8], value=8, disabled=not is_reg,
                               help="1 = one set of weights for all directions.")
    extras_sel = st.multiselect("Additional parameters", list(model.EXTRAS), default=["turbulence"],
                                format_func=model.EXTRAS.get, disabled=not is_reg,
                                help="Extra predictors taken from the reference turbines. See the Method tab for "
                                     "which ones actually help.")
    st.subheader(":material/bolt: Power curve")
    use_expected = st.toggle("Account for prediction error", value=True,
                             help="Average the power curve over the model's error instead of using the "
                                  "predicted speed alone. Removes a systematic under-estimate.")
    use_density = st.toggle("Correct for air density", value=True,
                            help="Estimate the affected turbine's temperature and pressure from the reference "
                                 "turbines, compute air density and rescale the wind speed before the power curve "
                                 "(IEC 61400-12-1 normalisation, v·(ρ/ρ₀)^(1/3)).")
    has_turb = "turbulence" in model.build_extras(ref_turbines, ref_parks, ["turbulence"], 1)
    use_turb = st.toggle("Include turbulence", value=False, disabled=not has_turb,
                         help="Within every 10-minute average the wind fluctuates by the reported standard "
                              "deviation. Averaging the power curve over that variation (IEC turbulence "
                              "normalisation idea) raises power below rated speed. Off by default: it cannot be "
                              "checked without measured power.") and has_turb
    rho0 = st.number_input("Power-curve air density ρ₀ (kg/m³)", 1.0, 1.4, model.RHO_STD, 0.005, format="%.3f",
                           disabled=not use_density,
                           help="Density the manufacturer's power curve is valid for. 1.225 is the usual standard.")



def build_ctx(refs, parks):
    """Everything the model needs from a set of reference turbines."""
    return dict(means=model.park_means(refs, parks), direction=model.ref_direction(refs, parks, smooth),
                extras=model.build_extras(refs, parks, list(model.EXTRAS), smooth),
                atm=model.atmos_reference(refs, parks, smooth))


@st.cache_data(show_spinner="Selecting reference turbines…", max_entries=32)
def auto_refs(_key, t, start, end, smooth):
    """Best reference turbines for outage turbine `t` (cross-validated greedy + swap, see model.select_references)."""
    df = tgt_turbines[t]
    idx = df.index
    out = (idx >= start) & (idx <= end)
    test = (df["test_set"] & df["wind_speed"].notna()).to_numpy() if "test_set" in df else np.zeros(len(idx), bool)
    return model.select_references(df["wind_speed"], ref_turbines, pd.Series(~out & ~test, index=idx), smooth)


ctx_default = build_ctx(ref_turbines, ref_parks)
_ctx_memo = {}


def ctx_for(t):
    if ref_mode == "Manual":
        return ctx_default
    sel = tuple(auto_refs(data_key, t, start, end, smooth)["selected"])
    if sel not in _ctx_memo:
        _ctx_memo[sel] = build_ctx({n: ref_turbines[n] for n in sel}, sorted({data.park_of(n) for n in sel}))
    return _ctx_memo[sel]


def extra_frame(names, extras_all):
    cols = [c for n in names for c in model.EXTRA_COLS.get(n, [n]) if c in extras_all]
    return extras_all[cols] if cols else None


# ---------------- Per-turbine model, validation and loss ----------------
def power_of(wind, curve, sigma, rho=None, turb=None):
    """Power (kW) from wind speed.

    rho:  air density series -> wind speed is first scaled by (ρ/ρ₀)^(1/3)
    sigma: model prediction error (m/s), used if "prediction error" is on
    turb:  within-interval wind std. dev. series, used if "turbulence" is on
    The power curve is averaged over the combined variation sqrt(σ² + turb²).
    """
    var = sigma**2 if use_expected else 0.0
    if use_turb and turb is not None:
        t = turb.reindex(wind.index)
        var = var + t.fillna(t.mean()) ** 2
    sig = np.sqrt(var)
    if use_density and rho is not None:
        f = ((rho.reindex(wind.index) / rho0) ** (1 / 3)).fillna(1.0)
        wind, sig = wind * f, sig * f
    return energy.expected_power(wind, curve, sig)


def evaluate(y, pred, mask, curve, sigma, rho_pred=None, rho_act=None, turb_pred=None, turb_act=None) -> dict:
    """Wind, power and summed-energy errors of `pred` against measured `y` on the rows in `mask`.

    Measured power is the curve at the measured speed (and measured density, where available).
    """
    ra = None if rho_pred is None else rho_act.fillna(rho_pred)
    ta = None if turb_pred is None else turb_act.fillna(turb_pred)
    pa = power_of(y[mask], curve, 0.0, ra, ta)
    pp = power_of(pred[mask], curve, sigma, rho_pred, turb_pred).where(pa.notna())
    ea, ep = energy.energy_kwh(pa).sum(), energy.energy_kwh(pp).sum()
    return dict(wind=metrics.rmse_mae(y[mask], pred[mask]), power=metrics.rmse_mae(pa, pp),
                energy_dev=(ep / ea - 1) * 100 if ea else np.nan, mask=mask)


def run(t: str, code=None, ex_names=None, sec=None) -> dict:
    """Chronological split around the outage (e.g. train 1 Jul-31 Aug, test 4-9 Sep, validation 10-30 Sep).

    train  known rows before the outage            -> fit the scoring model
    test   the "shown" test rows (test_set flag)    -> scored with the train model
    val    known rows after the test rows           -> scored with the train model, used to choose settings
    final  fitted on train + validation (every known value outside the outage and the test rows) -> predicts the outage
    Without a test flag, the last 20 % before the outage serves as validation.
    """
    code = code or mk
    ex_names = extras_sel if ex_names is None else ex_names
    sec = sectors if sec is None else sec
    ctx = ctx_for(t)
    means, direction, extras_all, atm_ref = ctx["means"], ctx["direction"], ctx["extras"], ctx["atm"]
    ex = extra_frame(ex_names, extras_all) if code == "reg" else None
    df = tgt_turbines[t]
    y = df["wind_speed"]
    curve = curves.get(t, next(iter(curves.values()), None))
    idx = y.index
    out = pd.Series((idx >= start) & (idx <= end), index=idx)
    known = y.notna()
    test = (df["test_set"] & known & ~out) if "test_set" in df else pd.Series(False, index=idx)
    if test.any():
        train = pd.Series(idx < start, index=idx)
        val = pd.Series(idx > idx[test.to_numpy()][-1], index=idx) & known & ~out
        cut = val.idxmax() if val.any() else idx[-1]
    else:
        pre_times = idx[idx < start]
        cut = pre_times[int(0.8 * len(pre_times))]
        train = pd.Series(idx < cut, index=idx)
        val = pd.Series((idx >= cut) & (idx < start), index=idx) & known

    def fit_one(mask):
        return (model.fit(y, means, direction, mask, smooth, sec, ex) if code == "reg"
                else model.fit_mcp(code, y, means, mask, smooth))

    final_mask = ~out & ~test  # test rows stay untouched
    m_a, m = fit_one(train), fit_one(final_mask)
    pred_a, pred = (x.predict(means, direction, ex) for x in (m_a, m))
    at_a = model.fit_atmos(df, atm_ref, train) if use_density else None
    at_f = model.fit_atmos(df, atm_ref, final_mask) if use_density else None
    rho_a = at_a.predict(atm_ref)["rho"] if at_a else None
    rho_f = at_f.predict(atm_ref)["rho"] if at_f else None
    rho_act = model.air_density(df["ambient_temperature"], df["air_pressure"]) if at_a else None
    tl_a = model.fit_line(df["wind_speed_stddev"], extras_all["turbulence"], train) if use_turb and "wind_speed_stddev" in df and "turbulence" in extras_all else None
    tl_f = model.fit_line(df["wind_speed_stddev"], extras_all["turbulence"], final_mask) if tl_a else None
    turb_a = model.line_predict(tl_a, extras_all["turbulence"]) if tl_a else None
    turb_f = model.line_predict(tl_f, extras_all["turbulence"]) if tl_f else None
    turb_act = df["wind_speed_stddev"] if tl_a else None

    r = dict(name=t, y=y, out=out.to_numpy(), ctx=ctx, refs=(list(means.columns) if ref_mode == "Manual" else auto_refs(data_key, t, start, end, smooth)["selected"]), model=m, curve=curve, pred=pred, split=dict(train=train, val=val, test=test),
             cut=cut, pred_by={"Validation": pred_a, "Test": pred_a}, train_end=idx[train.to_numpy()][-1])
    if curve is not None:
        r["val"] = evaluate(y, pred_a, val, curve, m_a.resid_std, rho_a, rho_act, turb_a, turb_act)
        r["split"] = dict(train=train, val=val, test=test)
        if test.any():
            r["test"] = evaluate(y, pred_a, test, curve, m_a.resid_std, rho_a, rho_act, turb_a, turb_act)
        sigma = (r.get("test") or r["val"])["wind"]["RMSE"]  # out-of-sample error drives the range
        wo = pred[out.to_numpy()]
        r["p"] = power_of(wo, curve, m.resid_std, rho_f, turb_f)
        r["e"] = energy.energy_kwh(r["p"])
        r["e_lo"] = energy.energy_kwh(power_of((wo - Z * sigma).clip(lower=0), curve, m.resid_std, rho_f, turb_f))
        r["e_hi"] = energy.energy_kwh(power_of(wo + Z * sigma, curve, m.resid_std, rho_f, turb_f))
        if turb_f is not None:
            r["turb"] = turb_f[out.to_numpy()]
            r["e_nt"] = energy.energy_kwh(power_of(wo, curve, m.resid_std, rho_f, None))
        r["atmos"] = at_f
        if at_f:
            r["rho"] = rho_f[out.to_numpy()]
            r["e_std"] = energy.energy_kwh(power_of(wo, curve, m.resid_std, rho_f * 0 + rho0, turb_f))  # factor 1
            pa_ = at_a.predict(atm_ref)
            chk = test if test.any() else val
            act = pd.DataFrame({"temp": df["ambient_temperature"], "pres": df["air_pressure"], "rho": rho_act})[chk.to_numpy()]
            err = (pa_[chk.to_numpy()] - act).dropna()
            r["atm_check"] = {k: float(np.sqrt((err[k] ** 2).mean())) for k in ("temp", "pres", "rho")}
            r["atm_check_rows"] = "test" if test.any() else "validation"
    return r


try:
    R = {t: run(t) for t in targets}
except ValueError as e:
    st.error(str(e))
    st.stop()
if any(r["curve"] is None for r in R.values()):
    st.error("No power curve found. Upload `<turbine>_power_curve.xlsx` files.")
    st.stop()



def _row(r):
    return {"Wind RMSE val (m/s)": r["val"]["wind"]["RMSE"], "Wind RMSE test (m/s)": r.get("test", r["val"])["wind"]["RMSE"],
            "Power RMSE test (kW)": r.get("test", r["val"])["power"]["RMSE"],
            "Energy dev. test (%)": r.get("test", r["val"])["energy_dev"]}


@st.cache_data(show_spinner="Comparing methods…", max_entries=16)
def compare_methods(_key, focus, ref_mode, ref_parks, start, end, smooth, sectors, use_expected, use_density, rho0, use_turb, extras_sel):
    rows = []
    for name, code in model.METHODS.items():
        x = run(focus, code, extras_sel if code == "reg" else ())
        rows.append({"Method": name, **_row(x), "Estimated loss (kWh)": x["e"].sum()})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner="Testing additional parameters…", max_entries=16)
def compare_extras(_key, focus, ref_mode, ref_parks, start, end, smooth, sectors, use_expected, use_density, rho0, use_turb):
    rows = [{"Added parameter": "none (base model)", **_row(run(focus, "reg", ()))}]
    for n, label in model.EXTRAS.items():
        if extra_frame([n], ctx_for(focus)["extras"]) is not None:
            rows.append({"Added parameter": label, **_row(run(focus, "reg", (n,)))})
    return pd.DataFrame(rows).drop(columns=["Power RMSE test (kW)", "Energy dev. test (%)"])


hours = (end - start).total_seconds() / 3600 + 1 / 6
total = sum(r["e"].sum() for r in R.values())
total_lo = sum(r["e_lo"].sum() for r in R.values())
total_hi = sum(r["e_hi"].sum() for r in R.values())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Estimated energy loss", f"{total:,.0f} kWh", border=True)
c2.metric("80 % range", f"{total_lo:,.0f} – {total_hi:,.0f} kWh", border=True)
c3.metric("Outage duration", f"{hours:.1f} h", border=True)
c4.metric("Turbines affected", len(targets), border=True)

focus = st.segmented_control("Turbine shown in the charts", targets, default=targets[0]) or targets[0]
r = R[focus]
m = r["model"]

tab_wind, tab_energy, tab_flow, tab_method, tab_report = st.tabs(
    [":material/show_chart: Wind speed", ":material/bolt: Energy loss", ":material/animation: Outage replay",
     ":material/query_stats: Method and accuracy", ":material/mail: Insurance report"])

pad = pd.Timedelta(days=2)

# ---------------- Wind speed ----------------
with tab_wind:
    fig = go.Figure()
    cmeans = r["ctx"]["means"]
    for p in cmeans.columns:
        fig.add_scatter(x=cmeans.index, y=cmeans[p], name=f"Reference park {p} (mean)", line=dict(width=1), opacity=.6)
    fig.add_scatter(x=r["y"].index, y=r["y"].where(~r["out"]), name=f"{focus} measured", line=dict(color=C_MEASURED))
    po = r["pred"][r["out"]]
    fig.add_scatter(x=po.index, y=po, name=f"{focus} predicted", line=dict(color=C_PRIMARY, width=2))
    fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(yaxis_title="Wind speed (m/s)", hovermode="x unified", height=450,
                      xaxis=dict(range=[start - pad, end + pad], rangeslider=dict(visible=True)))
    with st.container(border=True):
        st.plotly_chart(fig, width="stretch")
    st.caption("Times are local (Europe/Berlin). The shaded area is the outage; zoom out to see the full period.")

# ---------------- Energy ----------------
with tab_energy:
    rows = [{"Turbine": t, "Energy loss (kWh)": R[t]["e"].sum(), "Low (kWh)": R[t]["e_lo"].sum(),
             "High (kWh)": R[t]["e_hi"].sum(), "Mean predicted wind (m/s)": R[t]["pred"][R[t]["out"]].mean()}
            for t in targets]
    st.dataframe(pd.DataFrame(rows).set_index("Turbine").round(1), width="stretch")
    if r.get("atmos"):
        eff = r["e"].sum() - r["e_std"].sum()
        st.info(f"**Air density.** {focus}: mean {r['rho'].mean():.3f} kg/m³ during the outage "
                f"(power curve valid for {rho0:.3f}). Correcting the power curve changes the estimated loss by "
                f"**{eff:+,.0f} kWh ({eff / r['e_std'].sum() * 100:+.1f} %)**.", icon=":material/air:")
        if r.get("turb") is not None:
            eff = r["e"].sum() - r["e_nt"].sum()
            st.info(f"**Turbulence.** {focus}: mean within-interval std. dev. {r['turb'].mean():.2f} m/s (estimated from the "
                    f"reference turbines). Averaging the power curve over it changes the loss by "
                    f"**{eff:+,.0f} kWh ({eff / r['e_nt'].sum() * 100:+.1f} %)**.", icon=":material/air:")
    elif use_density:
        st.warning("Air-density correction is off for this turbine: no temperature/pressure data to learn from.")
    fig = go.Figure()
    fig.add_scatter(x=r["e_hi"].index, y=r["e_hi"], line_width=0, showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=r["e_lo"].index, y=r["e_lo"], fill="tonexty", line_width=0, name="80 % range",
                    fillcolor="rgba(179,38,30,.2)", hoverinfo="skip")
    fig.add_bar(x=r["e"].index, y=r["e"], name="Lost energy per 10 min", marker_color=C_ERROR)
    fig.update_layout(yaxis_title="kWh per 10 min", height=330, title=f"{focus}: lost energy")
    with st.container(border=True):
        st.plotly_chart(fig, width="stretch")
    cum = go.Figure()
    for t in targets:
        cum.add_scatter(x=R[t]["e"].index, y=R[t]["e"].cumsum(), name=t)
    cum.update_layout(yaxis_title="Cumulative kWh", height=300, title="Cumulative loss")
    with st.container(border=True):
        st.plotly_chart(cum, width="stretch")

# ---------------- Outage replay ----------------
with tab_flow:
    m = r["model"]
    sel_turb = list(r["refs"]) if ref_mode == "Automatic" else [n for n in ref_turbines if data.park_of(n) in ref_parks]
    out_idx = r["y"].index[r["out"]]
    spd = pd.DataFrame({n: ref_turbines[n]["wind_speed"] for n in ref_turbines}).loc[out_idx]
    drc = pd.DataFrame({n: ref_turbines[n]["wind_direction"] for n in ref_turbines if "wind_direction" in ref_turbines[n]})
    drc = drc.reindex(columns=spd.columns).loc[out_idx]
    pcoef = dict(zip(m.parks, np.abs(m.coef))) if len(m.parks) == len(m.coef) and len(m.coef) > 1 else {}
    per_park = pd.Series([data.park_of(n) for n in sel_turb]).value_counts().to_dict()
    weights = {n: pcoef.get(data.park_of(n), 1.0) / per_park[data.park_of(n)] for n in sel_turb}
    st.markdown(
        f"Replay of the outage at **{focus}**. Reference turbines (around) measure the wind; the outage turbine "
        "(centre) has no measurement, so its wind speed, power and lost energy are *calculated* from them. "
        "Dots flow from each reference turbine to the outage turbine, faster when it is windier, and thicker lines mean "
        "a bigger weight in the model. Small arrows show the wind direction. Faded turbines are not used.")
    fig = viz.flow_figure(focus, spd, drc, sel_turb, weights, r["pred"][r["out"]], r["p"], r["e"],
                          float(r["curve"]["power_kw"].max()),
                          colors=dict(primary=C_PRIMARY, loss=C_ERROR))
    with st.container(border=True):
        st.plotly_chart(fig, width="stretch")
    st.caption("Schematic layout, not to scale: the data contains no turbine coordinates. Press play, or drag the slider.")

    st.subheader("Worked example for one 10-minute step")
    t_pick = st.select_slider("Time", options=list(out_idx), value=out_idx[len(out_idx) // 3],
                              format_func=lambda t: f"{t:%d %b %H:%M}")
    ctx = r["ctx"]
    v_pred, p_now, e_now = r["pred"].loc[t_pick], r["p"].loc[t_pick], r["e"].loc[t_pick]
    lines = []
    if isinstance(m, model.ParkModel):
        xs = model.smooth_means(ctx["means"][m.parks], m.smooth)
        ex = ctx["extras"][m.extra_cols] if m.extra_cols else None
        beta = m.beta if m.beta is not None else None
        if beta is not None:
            X = model._design(xs, ctx["direction"], m.sectors, ex).loc[[t_pick]]
        if beta is not None and X.notna().all(axis=1).iloc[0]:
            contrib = X.iloc[0].to_numpy() * beta
            rows = []
            for (key, col), val, w_, c_ in zip(X.columns, X.iloc[0].to_numpy(), beta, contrib):
                if key == "x":
                    rows.append((model.EXTRAS.get(col, col) if col in model.EXTRAS else col, val, w_, c_))
                elif col == "1":
                    if val:
                        rows.append((f"Base level, sector {model.sector_label(key, m.sectors) if m.sectors > 1 else 'all directions'}", np.nan, np.nan, c_))
                elif val:
                    rows.append((f"Wind at park {col} (average of its turbines)", xs.loc[t_pick, col], w_, c_))
            if m.sectors > 1:
                st.caption(f"Reference wind comes from {ctx['direction'].loc[t_pick]:.0f}°, so the weights of the "
                           f"{model.sector_label(int(((ctx['direction'].loc[t_pick] + 180 / m.sectors) % 360) // (360 / m.sectors)), m.sectors)} "
                           "sector are used.")
            tbl = pd.DataFrame(rows, columns=["Input", "Value", "Weight", "Adds (m/s)"]).set_index("Input")
            st.dataframe(tbl.round(3), width="stretch")
        else:
            st.caption("A reference value is missing at this time, so the simpler fallback formula "
                       "(a line on the available parks) is used.")
    else:
        st.caption(f"{method_name}: v = {m.coef[0]:.2f} × reference + {m.intercept:.2f}" if m.kind != "bin" else f"{method_name}: lookup table")
    rho_t = r["rho"].loc[t_pick] if "rho" in r else None
    fac = (rho_t / rho0) ** (1 / 3) if rho_t is not None and use_density else 1.0
    v_eq = v_pred * fac
    plain = float(np.interp(v_eq, r["curve"]["wind_speed"], r["curve"]["power_kw"]))
    a, b, c, d_ = st.columns(4)
    a.metric("1  Predicted wind", f"{v_pred:.2f} m/s", border=True)
    b.metric("2  After air density" if use_density else "2  Air density off",
             f"{v_eq:.2f} m/s", f"ρ = {rho_t:.3f} kg/m³" if rho_t is not None and use_density else None, border=True)
    c.metric("3  Power from curve", f"{p_now:,.0f} kW", f"plain curve: {plain:,.0f} kW", border=True)
    d_.metric("4  Energy in 10 min", f"{e_now:,.0f} kWh", "power × 1/6 h", border=True)
    st.caption("Step 3 shows the power after averaging the curve over the prediction error (and turbulence if switched on); "
               "“plain curve” is the straight lookup at the speed from step 2. Summing step 4 over all outage steps "
               "gives the total energy loss.")


# ---------------- Method ----------------
with tab_method:
    exp_note = (" Because a predicted speed is never exact and the curve bends upward, the power curve is "
                "averaged over the model's typical error instead of read at a single point, which "
                "avoids a systematic under-estimate of energy." if use_expected else "")
    if mk == "reg":
        terms = " + ".join(f"{c:.2f}·v_{p}" for p, c in zip(m.parks, m.coef))
        sec_note = (f"\n\nThe weights are fitted **separately for each of {m.sectors} wind-direction sectors** "
                    f"(direction taken from the reference turbines), because the two sites are exposed differently "
                    f"depending on where the wind comes from. The formula below is the all-direction version; "
                    f"the per-sector weights are in the table." if m.beta is not None and m.sectors > 1 else "")
        ex_note = (f"\n\nAdditional predictors used: {', '.join(model.EXTRAS[n] for n in extras_sel)}."
                   if m.extra_cols else "")
        analyze = (f"For each affected turbine we learn how its wind speed relates to the *average wind speed of each "
                   f"reference park* (parks other than the affected one) from all measurements outside the outage "
                   f"({m.n_train:,} usable 10-min values). The reference series is smoothed over {smooth} steps to "
                   f"damp sensor noise. Result for **{focus}**: `v_{focus} = {terms} + {m.intercept:.2f}` "
                   f"(R² of the model used = {m.r2:.2f}).{sec_note}{ex_note}")
        predict = ("The formula is applied to the reference parks during the outage. If one reference park is "
                   "missing at a time step, the average of the parks that are available is used instead. "
                   "Negative speeds are set to 0.")
    else:
        how = {"ols": "a least-squares line (slope = correlation × σ_target / σ_ref). It gives the lowest wind-speed "
                      "error but shrinks the spread of the wind, so peaks are under-predicted.",
               "vr": "the variance-ratio line (slope = σ_target / σ_ref). It keeps the spread of the real wind but "
                     "has a larger point-by-point error.",
               "tls": "orthogonal (total least squares) regression, which assumes both series are noisy. Its slope "
                      "lands close to the variance-ratio one.",
               "bin": "the mean target speed in each 1 m/s bin of the reference speed, interpolated between bin "
                      "centres. It needs no straight-line assumption but is noisy where data is sparse."}[mk]
        line = (f"`v_{focus} = {m.coef[0]:.2f}·v_ref + {m.intercept:.2f}`" if mk != "bin" else "a lookup table")
        analyze = (f"The reference is the average of the reference parks ({', '.join(m.parks)}), smoothed over "
                   f"{smooth} steps. The transfer function is {how} Result for **{focus}**: {line} "
                   f"({m.n_train:,} usable values, R² = {m.r2:.2f}).")
        predict = "The transfer function is applied to the reference average during the outage. Negative speeds are set to 0."
    st.markdown(f"""
**Method: {method_name}**

**1. Analyze.** {analyze}

**2. Predict.** {predict}

**3. Calculate.** Predicted speeds are mapped to power with the turbine's power curve (linear interpolation) and
multiplied by 1/6 h per step to get kWh. The loss is summed over the outage.{exp_note}

**Uncertainty.** We measure the typical error on data the model has not seen (see below). The 80 % range shifts
every predicted speed by ±{Z:.2f} × that RMSE before the power curve is applied, a conservative band because it
assumes all errors point the same way.
""")
    tbl = m.sector_table()
    if tbl is not None:
        st.dataframe(tbl.round(2), width="stretch")
        st.caption(f"Weights by wind-direction sector for {focus}: v = Σ weight · v_park + intercept.")
    ew = m.extra_weights() if hasattr(m, "extra_weights") else None
    if ew is not None:
        info = {"turbulence": ("Reference turbulence (std. dev.)", "m/s"), "temperature": ("Reference temperature", "°C"),
                "pressure": ("Reference air pressure", "hPa"), "pressure_trend": ("Air-pressure change over 3 h", "hPa"),
                "tod_sin": ("Time of day (sine)", "–"), "tod_cos": ("Time of day (cosine)", "–"),
                "wind_trend": ("Reference wind, 6 h mean", "m/s"),
                "ramp_past": ("Reference wind change, past hour", "m/s"), "ramp_next": ("Reference wind change, next hour", "m/s")}
        sd = r["ctx"]["extras"][list(ew.index)][~r["out"]].std()
        et = pd.DataFrame({"Parameter": [info.get(c, (c, ""))[0] for c in ew.index],
                           "Unit": [info.get(c, (c, ""))[1] for c in ew.index],
                           "Weight (m/s per unit)": ew.values, "Typical swing, 1 σ": sd.values,
                           "Effect of a 1 σ swing (m/s)": ew.values * sd.values}).set_index("Parameter")
        st.subheader("What the additional parameters do")
        st.dataframe(et.round(3), width="stretch")
        top = et["Effect of a 1 σ swing (m/s)"].abs().idxmax()
        row = et.loc[top]
        st.caption(f"For {focus}, with everything else equal, a typical swing (1 σ = {row['Typical swing, 1 σ']:.2f} {row['Unit']}) in "
                   f"“{top}” moves the predicted wind speed by {row['Effect of a 1 σ swing (m/s)']:+.2f} m/s. "
                   "Positive weight: higher value, higher predicted wind.")
    if use_turb:
        st.markdown("**Turbulence in the power step.** The affected turbine's own turbulence is unknown during the outage, "
                    "so it is predicted from the reference turbulence with a straight line learned outside the outage. "
                    "The power curve is then averaged over a normal variation with that standard deviation, combined "
                    "with the model's prediction error: `σ_total = √(σ_error² + σ_turbulence²)`.")
    st.subheader("Accuracy")
    rows = []
    for t in targets:
        for split in ("val", "test"):
            x = R[t].get(split)
            if x:
                rows.append({"Turbine": t, "Split": split.capitalize(), "Wind RMSE (m/s)": x["wind"]["RMSE"],
                             "Wind MAE (m/s)": x["wind"]["MAE"], "Power RMSE (kW)": x["power"]["RMSE"],
                             "Power MAE (kW)": x["power"]["MAE"], "Energy deviation (%)": x["energy_dev"],
                             "Samples": x["wind"]["n"]})
    st.dataframe(pd.DataFrame(rows).set_index(["Turbine", "Split"]).round(2), width="stretch")
    first = r["y"].index[0]
    sp = r["split"]
    span = lambda m_: f"{r['y'].index[m_.to_numpy()][0]:%d %b} – {r['y'].index[m_.to_numpy()][-1]:%d %b}" if m_.any() else "none"
    st.caption(f"**Train:** {span(sp['train'])} (known rows before the outage). **Test:** {span(sp['test'])} "
               f"(shown rows with real values). **Validation:** {span(sp['val'])}. Both are scored with the model "
               "fitted on the train part only. The outage prediction uses a final model fitted on train + validation; "
               "the test rows are never used for fitting.")

    view = st.segmented_control("Show", ["Test", "Validation"], default="Test" if "test" in r else "Validation") or "Validation"
    key = "val" if view == "Validation" else "test"
    if key not in r:
        key = "val"
    v = r[key]["mask"]
    pv = r["pred_by"]["Validation" if key == "val" else "Test"]
    ov = go.Figure()
    ov.add_scatter(x=r["y"].index[v], y=r["y"][v], name="Measured", line=dict(color=C_MEASURED))
    ov.add_scatter(x=r["y"].index[v], y=pv[v], name="Predicted", line=dict(color=C_PRIMARY))
    ov.update_layout(yaxis_title="Wind speed (m/s)", height=320,
                     title=f"{focus}: {key} period, measured vs predicted")
    with st.container(border=True):
        st.plotly_chart(ov, width="stretch")

    sc = pd.concat([r["y"][v], pv[v]], axis=1, keys=["a", "p"]).dropna()
    s = go.Figure(go.Scattergl(x=sc["a"], y=sc["p"], mode="markers", marker=dict(size=4, opacity=.4), name="10-min values"))
    lim = [0, float(sc.max().max())]
    s.add_scatter(x=lim, y=lim, mode="lines", line=dict(dash="dash", color="gray"), name="Perfect")
    s.update_layout(xaxis_title="Measured (m/s)", yaxis_title="Predicted (m/s)", height=350)
    with st.container(border=True):
        st.plotly_chart(s, width="stretch")

    if ref_mode == "Automatic":
        sel = auto_refs(data_key, focus, start, end, smooth)
        st.subheader("Automatic reference selection")
        st.markdown(f"**{focus}** uses {len(sel['selected'])} of {len(ref_turbines)} uploaded reference turbines: "
                    + " ".join(f":green-badge[{n}]" for n in sel["selected"]))
        st.markdown(
            "How it works: every reference turbine is first scored on its own. Then the set is built greedily, adding "
            "the turbine that lowers the error most while the gain is at least 0.5 %, followed by a pass that tries to "
            "swap a chosen turbine for an unchosen one and a pass that drops turbines that do not help. The error is "
            "a 6-fold cross-validation over time blocks of the known data, so the outage and the test rows are never "
            "used. Turbines of one park are averaged, so a bad turbine cannot drag a whole park down.")
        rk = sel["ranking"]
        bar = go.Figure(go.Bar(x=rk["CV RMSE alone (m/s)"], y=rk["Turbine"], orientation="h",
                               marker_color=[C_PRIMARY if v else C_MEASURED for v in rk["Selected"]]))
        bar.update_layout(height=max(220, 34 * len(rk) + 80), xaxis_title="Error with this turbine alone (m/s, lower is better)",
                          yaxis=dict(autorange="reversed"), title=f"{focus}: reference turbines, selected in green")
        with st.container(border=True):
            st.plotly_chart(bar, width="stretch")
        st.dataframe(sel["steps"].set_index("Step").round(3), width="stretch")
        st.caption("Each step: the action taken, the size of the set afterwards and the cross-validated error. "
                   "Only the top 15 turbines on their own are considered when the pool is larger.")
    else:
        st.subheader("Which reference turbines fit best?")
        refs = [n for n in ref_turbines if data.park_of(n) in ref_parks]
        cor = {n: ref_turbines[n]["wind_speed"].where(~pd.Series(r["out"], index=r["y"].index)).corr(r["y"]) for n in refs}
        cor = pd.Series(cor).sort_values(ascending=False)
        st.bar_chart(cor.rename("Correlation with " + focus), horizontal=True)
        st.caption("Correlation between each reference turbine and the affected turbine outside the outage. "
                   "Park averages beat any single turbine because they cancel local noise.")

    if r.get("atmos"):
        st.subheader("Air-density correction")
        L, rm_ = r["atmos"].lines, r["atm_check"]
        st.markdown(f"""
The affected turbine has no temperature or pressure data during an outage, so both are estimated from the
reference turbines with straight lines: `T_{focus} = {L['temp'][0]:.2f}·T_ref + {L['temp'][1]:.1f}` and
`p_{focus} = {L['pres'][0]:.2f}·p_ref + {L['pres'][1]:.1f}` (pressure from parks that report real values).
Air density follows from the ideal gas law, `ρ = p / (287.05 · T)`. The power curve is valid for
ρ₀ = {rho0:.3f} kg/m³, so predicted wind speeds are rescaled to `v·(ρ/ρ₀)^(1/3)` before the lookup (the IEC 61400-12-1
normalisation). Humidity is ignored.
""")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Temperature error ({r['atm_check_rows']})", f"{rm_['temp']:.2f} °C", border=True)
        c2.metric("Pressure error", f"{rm_['pres']:.2f} hPa", border=True)
        c3.metric("Density error", f"{rm_['rho']:.4f} kg/m³", border=True)
    st.subheader("Compare methods")
    st.caption(f"{focus}, same data split and settings. Scored with the model fitted on the train part only.")
    st.dataframe(compare_methods(data_key, focus, ref_mode, tuple(ref_parks), start, end, smooth, sectors, use_expected,
                                 use_density, rho0, use_turb, tuple(extras_sel)).set_index("Method").round(2), width="stretch")
    st.subheader("Do additional parameters help?")
    st.caption(f"{focus}, park regression with {sectors} sector(s). Each row adds one parameter to the base model; "
               "a lower wind RMSE than the first row means it helps.")
    st.dataframe(compare_extras(data_key, focus, ref_mode, tuple(ref_parks), start, end, smooth, sectors, use_expected, use_density, rho0, use_turb)
                 .set_index("Added parameter").round(3), width="stretch")

# ---------------- Report ----------------
with tab_report:
    st.markdown("Fill in the details, check the text and download the e-mail. The e-mail file opens as a draft in "
                "your mail program with the prediction data attached.")
    f1, f2 = st.columns(2)
    lang_label = f1.segmented_control("Language", ["English", "Deutsch"], default="English") or "English"
    lang = "de" if lang_label == "Deutsch" else "en"
    site = f2.text_input("Wind farm / site name", placeholder="e.g. Windpark Nord")
    g1, g2, g3 = st.columns(3)
    claim = g1.text_input("Claim or policy reference", placeholder="optional")
    recipient = g2.text_input("Insurer contact", placeholder="e.g. Ms Schmidt")
    to_addr = g3.text_input("Insurer e-mail", placeholder="optional")
    h1_, h2_ = st.columns(2)
    sender = h1_.text_input("Your name")
    company = h2_.text_input("Your company")

    first = R[targets[0]]
    sp = first["split"]["test"]
    test_range = (f"{first['y'].index[sp.to_numpy()][0]:%d %b} to {first['y'].index[sp.to_numpy()][-1]:%d %b %Y}"
                  if sp.any() else "")
    if lang == "de" and sp.any():
        test_range = f"{first['y'].index[sp.to_numpy()][0]:%d.%m.} bis {first['y'].index[sp.to_numpy()][-1]:%d.%m.%Y}"
    sv = first["split"]["val"]
    val_range = f"{first['y'].index[sv.to_numpy()][0]:%d %b} to {first['y'].index[sv.to_numpy()][-1]:%d %b %Y}" if sv.any() else "-"
    rows = []
    for t in targets:
        x, te = R[t], R[t].get("test")
        rows.append(dict(name=t, loss=x["e"].sum(), lo=x["e_lo"].sum(), hi=x["e_hi"].sum(), mean_wind=x["pred"][x["out"]].mean(),
                         test_rmse=te["wind"]["RMSE"] if te else None, test_mae=te["wind"]["MAE"] if te else None,
                         test_dev=te["energy_dev"] if te else None))
    with_rho = [x for x in R.values() if x.get("atmos")]
    density = None
    if with_rho:
        e_sum, e_std = sum(x["e"].sum() for x in with_rho), sum(x["e_std"].sum() for x in with_rho)
        density = dict(rho=float(np.mean([x["rho"].mean() for x in with_rho])), rho0=rho0, eff=(e_sum / e_std - 1) * 100)
    with_turb = [x for x in R.values() if x.get("turb") is not None]
    turb_eff = ((sum(x["e"].sum() for x in with_turb) / sum(x["e_nt"].sum() for x in with_turb) - 1) * 100) if with_turb else None
    mfin = first["model"]
    refs_text = ("; ".join(f"{t}: {', '.join(R[t]['refs'])}" for t in targets) if ref_mode == "Automatic"
                 else "wind parks " + ", ".join(ref_parks))
    csv_name = "outage_predictions.csv"
    facts = dict(site=site, claim=claim, recipient=recipient, sender=sender, company=company, turbines=rows,
                 start=start, end=end, hours=hours, total=total, lo=total_lo, hi=total_hi, refs_text=refs_text,
                 method_kind=mk, method_name=method_name, sectors=getattr(mfin, "sectors", 1),
                 extras=[n for n in extras_sel if getattr(mfin, "extra_cols", None)] if mk == "reg" else [],
                 n_train=getattr(mfin, "n_train", 0), density=density, turb_eff=turb_eff, expected=use_expected,
                 test_range=test_range, val_range=val_range, csv_name=csv_name)
    subject, body = report.build_report(lang, facts)
    parts = {t: pd.DataFrame({"wind_ms": R[t]["pred"][R[t]["out"]], "power_kw": R[t]["p"], "energy_kwh": R[t]["e"],
                              "energy_low_kwh": R[t]["e_lo"], "energy_high_kwh": R[t]["e_hi"]}) for t in targets}
    csv_text = report.predictions_csv(parts)

    st.text_input("Subject", value=subject, key=f"subj_{hash(subject)}")
    text = st.text_area("E-mail text (editable)", value=body, height=520, key=f"body_{hash(body)}")
    subj = st.session_state.get(f"subj_{hash(subject)}", subject)
    with st.container(horizontal=True):
        st.download_button("E-mail draft (.eml)", report.build_eml(subj, text, csv_text, csv_name, to_addr, sender),
                           file_name="outage_report.eml", mime="message/rfc822", icon=":material/mail:",
                           type="primary", on_click="ignore")
        st.download_button("Text (.txt)", f"Subject: {subj}\n\n{text}", file_name="outage_report.txt",
                           mime="text/plain", icon=":material/description:", on_click="ignore")
        st.download_button("Predictions (.csv)", csv_text, file_name=csv_name, mime="text/csv",
                           icon=":material/table_chart:", on_click="ignore")
    with st.expander("Preview of the prediction data"):
        st.dataframe(pd.read_csv(__import__("io").StringIO(csv_text)).head(30), width="stretch")
