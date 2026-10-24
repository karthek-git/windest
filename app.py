import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from windest import data, energy, metrics, model

st.set_page_config(page_title="Wind outage estimator", layout="wide")
st.title("Wind farm outage – energy loss estimator")

# ---------------- Inputs ----------------
with st.sidebar:
    st.header("Inputs")
    ref_file = st.file_uploader("Reference farm wind (CSV)", type="csv")
    tgt_file = st.file_uploader("Affected farm wind (CSV)", type="csv")
    pc_file = st.file_uploader("Power curve (CSV: m/s, kW)", type="csv")
    n_turb = st.number_input("Number of turbines", 1, 500, 1)
    val_days = st.slider("Validation days (end of training data)", 1, 10, 3)
    use_sample = st.checkbox("Use sample data", value=not (ref_file and tgt_file and pc_file))

if use_sample:
    ref_file, tgt_file, pc_file = (f"sample_data/{n}.csv" for n in ("reference", "target", "power_curve"))
if not (ref_file and tgt_file and pc_file):
    st.info("Upload all three files or tick 'Use sample data'.")
    st.stop()

ref, tgt, curve = data.load_wind_csv(ref_file), data.load_wind_csv(tgt_file), data.load_power_curve(pc_file)
ref = ref.reindex(tgt.index.union(ref.index)).asfreq("10min")
tgt = tgt.reindex(ref.index)

auto = data.detect_outage(tgt)
with st.sidebar:
    st.subheader("Outage period")
    default = auto or (tgt.index[-144], tgt.index[-1])
    start = pd.Timestamp(st.text_input("Start", str(default[0])))
    end = pd.Timestamp(st.text_input("End", str(default[1])))
    if auto is None:
        st.caption("No gap detected – enter the period manually.")

outage = (tgt.index >= start) & (tgt.index <= end)
train = tgt.where(~outage)
train = train[train.index < start]

# ---------------- Fit / validate ----------------
cut = train.index[-1] - pd.Timedelta(days=val_days)
fit_t, val_t = train[train.index <= cut], train[train.index > cut]
m_val = model.fit(fit_t, ref)
val_pred = m_val.predict(ref).reindex(val_t.index)
val_metrics = metrics.rmse_mae(val_t, val_pred)

m = model.fit(train, ref)  # refit on all pre-outage data
pred = m.predict(ref)
pred_out = pred[outage]

# ---------------- Energy ----------------
p_out = energy.power_from_wind(pred_out, curve)
e_out = energy.energy_kwh(p_out, n_turb)
lo = energy.energy_kwh(energy.power_from_wind((pred_out - 1.28 * m.resid_std).clip(lower=0), curve), n_turb)
hi = energy.energy_kwh(energy.power_from_wind(pred_out + 1.28 * m.resid_std, curve), n_turb)

tab1, tab2, tab3, tab4 = st.tabs(["Wind speed", "Energy loss", "Method & accuracy", "Report"])

with tab1:
    fig = go.Figure()
    fig.add_scatter(x=ref.index, y=ref, name="Reference", line=dict(color="#999", width=1))
    fig.add_scatter(x=tgt.index, y=tgt.where(~outage), name="Affected (measured)", line=dict(color="#1f77b4"))
    fig.add_scatter(x=pred_out.index, y=pred_out, name="Affected (predicted)", line=dict(color="#d62728"))
    fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(yaxis_title="Wind speed (m/s)", hovermode="x unified", height=450)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    c1, c2, c3 = st.columns(3)
    c1.metric("Estimated energy loss", f"{e_out.sum():,.0f} kWh")
    c2.metric("Outage duration", f"{(end - start).total_seconds() / 3600:.1f} h")
    c3.metric("80% range", f"{lo.sum():,.0f} – {hi.sum():,.0f} kWh")
    fig = go.Figure()
    fig.add_scatter(x=hi.index, y=hi, line_width=0, showlegend=False)
    fig.add_scatter(x=lo.index, y=lo, fill="tonexty", line_width=0, name="80% range", fillcolor="rgba(214,39,40,.2)")
    fig.add_bar(x=e_out.index, y=e_out, name="Lost energy / 10 min", marker_color="#d62728")
    fig.update_layout(yaxis_title="kWh per 10 min", height=350)
    st.plotly_chart(fig, use_container_width=True)
    st.plotly_chart(go.Figure(go.Scatter(x=e_out.index, y=e_out.cumsum(), name="Cumulative")).update_layout(
        yaxis_title="Cumulative kWh", height=300), use_container_width=True)

with tab3:
    st.markdown(f"""
**Method.** Wind at the affected farm is modelled from the reference farm with a straight line:
`v_target = {m.slope:.3f} · v_ref(t − {m.lag_steps*10} min) + {m.intercept:.3f}`.
The reference lag (0–60 min) with the highest correlation is chosen; the line is fitted by least squares on all
pre-outage data. Predicted speeds are converted to power via the power curve (interpolated) and integrated
over 10-minute steps × number of turbines.

**Uncertainty.** Residual std on training data is {m.resid_std:.2f} m/s; the 80 % band shifts predictions by ±1.28σ.
""")
    a, b, c = st.columns(3)
    a.metric("Correlation (train)", f"{m.corr:.3f}")
    b.metric("Validation RMSE", f"{val_metrics['RMSE']:.2f} m/s")
    c.metric("Validation MAE", f"{val_metrics['MAE']:.2f} m/s")
    st.caption(f"Validated on the last {val_days} days before the outage ({val_metrics['n']} samples), model fitted on the rest.")
    sc = pd.concat([ref.shift(m.lag_steps), train], axis=1, keys=["ref", "target"]).dropna()
    st.plotly_chart(go.Figure(go.Scattergl(x=sc["ref"], y=sc["target"], mode="markers", marker=dict(size=3, opacity=.4)))
                    .update_layout(xaxis_title="Reference (m/s)", yaxis_title="Affected (m/s)", height=350),
                    use_container_width=True)

    if use_sample:
        truth = data.load_wind_csv("sample_data/target_truth.csv")
        st.subheader("Check against ground truth (sample data)")
        wm = metrics.rmse_mae(truth[outage], pred_out)
        pm = metrics.rmse_mae(energy.power_from_wind(truth[outage], curve), p_out)
        true_e = energy.energy_kwh(energy.power_from_wind(truth[outage], curve), n_turb).sum()
        st.table(pd.DataFrame({"Wind (m/s)": wm, "Power (kW)": pm}).T)
        st.metric("Energy deviation", f"{e_out.sum() - true_e:,.0f} kWh", f"{(e_out.sum()/true_e-1)*100:.1f} %")

with tab4:
    st.text_area("Insurance e-mail draft", height=300, value=f"""Subject: Business interruption – wind farm outage report

Dear Sir or Madam,

the communication link to our wind farm was lost from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} (Europe/Berlin), a duration of {(end-start).total_seconds()/3600:.1f} hours.

Wind speeds during the outage were reconstructed from a neighbouring reference farm using a linear model (correlation {m.corr:.2f}, validation RMSE {val_metrics['RMSE']:.2f} m/s) and converted to power with the turbine power curve ({n_turb} turbine(s)).

Estimated energy loss: {e_out.sum():,.0f} kWh (80 % range {lo.sum():,.0f} – {hi.sum():,.0f} kWh).

Kind regards""")
