"""Animated outage replay: reference turbines send wind to the outage turbine (schematic layout)."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from .data import park_of


def layout_positions(target: str, refs: list[str]) -> dict:
    """Schematic positions: the outage turbine in the middle, each reference park as a grid on a ring.

    The data has no coordinates, so this is NOT geographic.
    """
    pos = {target: (0.0, 0.0)}
    parks = sorted({park_of(n) for n in refs})
    for i, p in enumerate(parks):
        ang = 2 * np.pi * i / len(parks) + np.pi
        cx, cy = 5.4 * np.cos(ang), 3.0 * np.sin(ang)
        members = sorted(n for n in refs if park_of(n) == p)
        cols = 1 if len(members) == 1 else 2 if len(members) <= 2 else 3 if len(members) <= 6 else 4
        rows = int(np.ceil(len(members) / cols))
        for j, n in enumerate(members):
            r_, c_ = divmod(j, cols)
            in_row = min(cols, len(members) - r_ * cols)
            pos[n] = (cx + (c_ - (in_row - 1) / 2) * 1.9, cy + ((rows - 1) / 2 - r_) * 2.7)
    return pos


def flow_figure(target: str, ref_speed: pd.DataFrame, ref_dir: pd.DataFrame, selected: list[str], weights: dict,
                pred_speed: pd.Series, power_kw: pd.Series, energy_kwh: pd.Series, rated_kw: float,
                max_frames: int = 150, colors: dict | None = None) -> go.Figure:
    """ref_speed / ref_dir: one column per reference turbine, indexed like pred_speed (the outage rows)."""
    c = dict(primary="#018249", loss="#B3261E", muted="#9DB0A5", edge="#C9D6CD", tower="#6F8277") | (colors or {})
    refs = list(ref_speed.columns)
    pos = layout_positions(target, refs)
    n = len(pred_speed)
    step = max(1, int(np.ceil(n / max_frames)))
    ids = list(range(0, n, step))
    vmax = float(np.nanmax(ref_speed.to_numpy())) if ref_speed.notna().any().any() else 10.0
    cum = energy_kwh.cumsum()
    sel_idx = [refs.index(s) for s in selected if s in refs]
    w = np.array([weights.get(refs[i], 1.0) for i in sel_idx], float)
    w = w / w.sum() if w.size and w.sum() > 0 else w
    tx, ty = pos[target]

    # particle phases advance with the wind speed of the sending turbine; blades spin with the wind speed
    adv = np.zeros((len(ids), len(sel_idx)))
    for k, i in enumerate(sel_idx):
        adv[:, k] = np.cumsum(ref_speed.iloc[ids, i].fillna(0).to_numpy()) / 14.0
    n_part = 4
    rot_ref = np.cumsum(ref_speed.iloc[ids].fillna(0).to_numpy() * 7.0, axis=0)          # degrees, per frame and turbine
    rot_tgt = np.cumsum(pred_speed.iloc[ids].fillna(0).to_numpy() * 7.0)
    blade_col = lambda v: sample_colorscale("Greens", [min(max(0.25 + 0.75 * v / vmax, 0.25), 1.0)])[0]

    def turbine_shapes(f):
        """Tower + three blades per turbine, drawn in data coordinates (aspect ratio is locked to 1)."""
        shapes = []
        j = ids[f]
        sp = ref_speed.iloc[j]
        items = [(r, pos[r], 0.55, 0.95, rot_ref[f, k],
                  blade_col(sp.iloc[k]) if (pd.notna(sp.iloc[k]) and r in selected) else c["muted"], 3.5 if r in selected else 2.5)
                 for k, r in enumerate(refs)]
        items.append((target, (tx, ty), 0.9, 1.5, rot_tgt[f], c["loss"], 5.5))
        for _, (x, y), blade, tower, rot, col, wd in items:
            shapes.append(dict(type="line", x0=x, y0=y - tower, x1=x, y1=y, line=dict(color=c["tower"], width=wd - 1)))
            for q in range(3):
                a_ = np.deg2rad(90 + rot + 120 * q)
                shapes.append(dict(type="line", x0=x, y0=y, x1=x + blade * np.cos(a_), y1=y + blade * np.sin(a_),
                                   line=dict(color=col, width=wd)))
        return shapes

    def dyn(f):
        j = ids[f]
        sp = ref_speed.iloc[j]
        d = ref_dir.iloc[j] if ref_dir is not None else pd.Series(np.nan, index=refs)
        is_sel = np.array([r in selected for r in refs])
        hubs = go.Scatter(                                   # small hub markers: hover info and the colour bar
            x=[pos[r][0] for r in refs], y=[pos[r][1] for r in refs], mode="markers",
            marker=dict(size=9, color=sp.fillna(0).to_numpy(), colorscale="Greens", cmin=0, cmax=vmax,
                        opacity=np.where(is_sel, 1.0, 0.4), line=dict(width=1.5, color="white"),
                        colorbar=dict(title="Reference wind (m/s)", len=0.55, x=1.02) if f == 0 else None),
            customdata=[[r, "used" if r in selected else "not used", f"{v:.1f}" if pd.notna(v) else "n/a"]
                        for r, v in zip(refs, sp.to_numpy())],
            hovertemplate="%{customdata[0]} (%{customdata[1]})<br>%{customdata[2]} m/s<extra></extra>", showlegend=False)
        px, py = [], []
        for k, i in enumerate(sel_idx):
            x0, y0 = pos[refs[i]]
            for q in range(n_part):
                ph = (adv[f, k] + q / n_part) % 1.0
                px.append(x0 + ph * (tx - x0)); py.append(y0 + ph * (ty - y0))
        particles = go.Scatter(x=px, y=py, mode="markers", marker=dict(size=7, color=c["primary"], opacity=0.8),
                               hoverinfo="skip", showlegend=False)
        v, p = pred_speed.iloc[j], power_kw.iloc[j]
        tgt = go.Scatter(x=[tx], y=[ty], mode="markers", marker=dict(size=13, color=c["loss"], line=dict(width=2, color="white")),
                         hovertemplate=f"{target}: predicted, no measurement<extra></extra>", showlegend=False)
        arrow_ok = ~sp.isna().to_numpy() & ~d.isna().to_numpy()
        arrows = go.Scatter(
            x=[pos[r][0] + 0.55 for r in refs], y=[pos[r][1] - 0.7 for r in refs], mode="markers",
            marker=dict(symbol="arrow", size=17, angle=((d.fillna(0).to_numpy() + 180) % 360),
                        color=np.where(arrow_ok & is_sel, c["primary"], c["muted"]), opacity=np.where(arrow_ok, 0.9, 0)),
            hovertemplate="wind from %{customdata:.0f}°<extra></extra>", customdata=d.fillna(0).to_numpy(), showlegend=False)
        labels = go.Scatter(
            x=[pos[r][0] for r in refs] + [tx], y=[pos[r][1] - 1.0 for r in refs] + [ty - 1.55], mode="text",
            text=[f"{r}<br><b>{x:.1f} m/s</b>" if pd.notna(x) else f"{r}<br>n/a" for r, x in zip(refs, sp.to_numpy())]
                 + [f"<b>{target}</b><br>{v:.1f} m/s · {p / 1000:.2f} MW" if pd.notna(v) else target],
            textposition="bottom center", textfont=dict(size=12), hoverinfo="skip", showlegend=False)
        return [hubs, particles, tgt, arrows, labels]

    fig = go.Figure()
    for k, i in enumerate(sel_idx):                                   # static edges, width = model weight
        x0, y0 = pos[refs[i]]
        fig.add_scatter(x=[x0, tx], y=[y0, ty], mode="lines", line=dict(color=c["edge"], width=1 + 9 * w[k]),
                        hoverinfo="skip", showlegend=False)
    parks = sorted({park_of(r) for r in refs})
    fig.add_scatter(x=[np.mean([pos[r][0] for r in refs if park_of(r) == p]) for p in parks],
                    y=[max(pos[r][1] for r in refs if park_of(r) == p) + 1.5 for p in parks], mode="text",
                    text=[f"<b>Park {p}</b>" for p in parks], textfont=dict(size=15), hoverinfo="skip", showlegend=False)
    n_static = len(fig.data)
    for t_ in dyn(0):
        fig.add_trace(t_)
    dyn_idx = list(range(n_static, n_static + 5))

    def title(f):
        j = ids[f]
        return (f"{pred_speed.index[j]:%d %b %Y %H:%M}   ·   energy lost so far: <b>{cum.iloc[j]:,.0f} kWh</b>")

    frames = [go.Frame(data=dyn(f), traces=dyn_idx, name=str(f),
                       layout=dict(title=dict(text=title(f)), shapes=turbine_shapes(f)))
              for f in range(len(ids))]
    fig.frames = frames
    fig.update_layout(
        title=dict(text=title(0)), shapes=turbine_shapes(0), height=560, margin=dict(l=10, r=10, t=60, b=10),
        xaxis=dict(visible=False, range=[-8.6, 8.6]), yaxis=dict(visible=False, range=[-5.0, 5.2], scaleanchor="x"),
        updatemenus=[dict(type="buttons", direction="left", x=0.0, y=-0.02, xanchor="left", yanchor="top", pad=dict(t=10),
                          buttons=[dict(label="▶ Play", method="animate",
                                        args=[None, dict(frame=dict(duration=90, redraw=True), fromcurrent=True, transition=dict(duration=0))]),
                                   dict(label="⏸ Pause", method="animate",
                                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate", transition=dict(duration=0))])])],
        sliders=[dict(active=0, x=0.2, len=0.78, y=-0.02, pad=dict(t=10),
                      currentvalue=dict(visible=False),
                      steps=[dict(method="animate", label=f"{pred_speed.index[ids[f]]:%d %b %H:%M}" if f % max(1, len(ids) // 6) == 0 else "",
                                  args=[[str(f)], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
                             for f in range(len(ids))])])
    return fig
