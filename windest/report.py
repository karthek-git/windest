"""Insurance e-mail: plain-language report text (English / German) and an .eml with the data attached."""
from email.message import EmailMessage

import pandas as pd

TXT = {
    "en": dict(
        fmt="%d %b %Y %H:%M",
        subject="Business interruption claim: outage of {turbines}{site_s} – estimated energy not produced {total} kWh{ref_s}",
        greeting="Dear {name},", greeting_default="Sir or Madam",
        intro="I am writing about the data-communication outage of {turbines}{site_in}. No wind measurements are available "
              "for the outage, so the energy that was not produced has been estimated from neighbouring turbines.",
        h1="1. The outage",
        period="Period: {start} to {end} (local time, Europe/Berlin)",
        duration="Duration: {hours} hours",
        affected="Affected turbines: {turbines}",
        h2="2. Estimated energy not produced",
        col_t="Turbine", col_e="Energy (kWh)", col_r="80 % range (kWh)", col_w="Mean wind (m/s)",
        total_line="Total: {total} kWh (80 % range {lo} to {hi} kWh)",
        h3="3. How the figures were calculated",
        m1="Wind speed: the missing wind speeds were reconstructed from the measured wind of reference turbines ({refs}). "
           "{method}",
        m2="Power and energy: each wind speed was converted into power with the manufacturer's power curve of the "
           "turbine, and the power was multiplied by 1/6 hour for every 10-minute value. The energy was summed over the outage.",
        method_reg="A linear model, fitted on {n_train} measured values of the affected turbine outside the outage, combines the "
                   "reference winds{sectors}{extras}.",
        method_other="The transfer function is the {name} method, fitted on measured values of the affected turbine outside the outage.",
        sectors_txt=" with separate weights for {n} wind-direction sectors",
        extras_txt=" and additional reference measurements ({list})",
        density="Air density: the power curve was corrected for the estimated air density (mean {rho} kg/m³ against {rho0} kg/m³ "
                "in the power curve), which changed the result by {eff} %.",
        turb="Turbulence: the power curve was averaged over the wind-speed variation within each 10-minute interval, which changed the result by {eff} %.",
        expected="Estimation error: because a predicted wind speed is not exact and the power curve is not a straight line, the power was "
                 "averaged over the typical estimation error. This avoids a systematic under-estimate of the energy.",
        h4="4. Accuracy of the method",
        acc1="The method was tested on real measurements that it had not seen ({test_range}). Wind-speed error: {rmse} m/s (RMSE), "
             "{mae} m/s (MAE) on average over the affected turbines. Over the same days the estimated energy differed from the "
             "energy calculated from the measured wind by {devs}.",
        acc_nodev="No held-out measurements were available, so the accuracy was checked on {val_range}.",
        range_txt="The range is deliberately conservative: it assumes that all estimation errors act in the same direction at the same time.",
        h5="5. Assumptions and limitations",
        l1="Energy is calculated with the power-curve method from 10-minute average wind speeds; it does not include curtailment, "
           "availability losses or other causes unless they are part of the supplied power curve.",
        l2="The reference turbines are not at the affected site; the estimate relies on the statistical relationship between the sites in the training period.",
        l3="Time stamps are local time (Europe/Berlin).",
        cmp="On the test days at {turbine}, the wind-speed error was {ours} m/s with the method used and {lo} to {hi} m/s with the other "
            "MCP variants that were compared (OLS, variance-ratio, orthogonal and binned).",
        h6="6. Standards and references",
        std1="Method family: the wind speed was reconstructed with Measure-Correlate-Predict (MCP), a standard approach in wind resource "
             "assessment. The relationship between reference and affected turbines is learned from simultaneous measurements and then "
             "applied to the reference data of the outage [1, 2].",
        std2="Power and energy: 10-minute average wind speeds and the manufacturer's power curve, the data basis used for power performance "
             "in IEC 61400-12-1 [3].",
        std3="Air density: the wind speed is normalised to the air density of the power curve with v × (ρ / ρ₀)^(1/3), ρ₀ = {rho0} kg/m³, "
             "the normalisation described in IEC 61400-12-1 [3].",
        std4="These references describe the methods used. This report does not claim formal certification or compliance with a standard.",
        refs=["[1] Basse, A. et al. (2021), Wind Energy Science 6, 1473: long-term correction of short-term wind measurements (MCP).",
              "[2] Rogers, A.L., Rogers, J.W., Manwell, J.F. (2005), Comparison of the performance of four measure-correlate-predict algorithms.",
              "[3] IEC 61400-12-1, Wind energy generation systems - Part 12-1: Power performance measurements of electricity producing wind turbines."],
        attach="Attachment: {file} (10-minute wind speed, power and energy estimates for the outage).",
        close="Please let me know if you need further information or the underlying data.",
        regards="Kind regards", none_ref="",
    ),
    "de": dict(
        fmt="%d.%m.%Y %H:%M",
        subject="Betriebsunterbrechung: Ausfall von {turbines}{site_s} – geschätzte nicht erzeugte Energie {total} kWh{ref_s}",
        greeting="Guten Tag {name},", greeting_default="Damen und Herren",
        intro="ich melde den Ausfall der Datenkommunikation von {turbines}{site_in}. Für den Ausfallzeitraum liegen keine "
              "Windmessungen vor; die nicht erzeugte Energie (Ausfallarbeit) wurde daher anhand benachbarter Anlagen geschätzt.",
        h1="1. Der Ausfall",
        period="Zeitraum: {start} bis {end} (Ortszeit, Europe/Berlin)",
        duration="Dauer: {hours} Stunden",
        affected="Betroffene Anlagen: {turbines}",
        h2="2. Geschätzte nicht erzeugte Energie",
        col_t="Anlage", col_e="Energie (kWh)", col_r="80-%-Bereich (kWh)", col_w="Mittl. Wind (m/s)",
        total_line="Gesamt: {total} kWh (80-%-Bereich {lo} bis {hi} kWh)",
        h3="3. Berechnung der Werte",
        m1="Windgeschwindigkeit: Die fehlenden Windgeschwindigkeiten wurden aus den gemessenen Windwerten von Referenzanlagen "
           "({refs}) rekonstruiert. {method}",
        m2="Leistung und Energie: Jede Windgeschwindigkeit wurde mit der Herstellerleistungskurve der Anlage in Leistung umgerechnet; "
           "die Leistung wurde für jeden 10-Minuten-Wert mit 1/6 Stunde multipliziert und über den Ausfall summiert.",
        method_reg="Ein lineares Modell, angepasst an {n_train} gemessene Werte der betroffenen Anlage außerhalb des Ausfalls, "
                   "verknüpft die Referenzwinde{sectors}{extras}.",
        method_other="Die Übertragungsfunktion ist die Methode „{name}“, angepasst an gemessene Werte der betroffenen Anlage außerhalb des Ausfalls.",
        sectors_txt=" mit getrennten Gewichten für {n} Windrichtungssektoren",
        extras_txt=" und zusätzlichen Referenzmessungen ({list})",
        density="Luftdichte: Die Leistungskurve wurde auf die geschätzte Luftdichte korrigiert (Mittel {rho} kg/m³ gegenüber "
                "{rho0} kg/m³ in der Leistungskurve); das Ergebnis änderte sich um {eff} %.",
        turb="Turbulenz: Die Leistungskurve wurde über die Schwankung der Windgeschwindigkeit innerhalb der 10-Minuten-Intervalle gemittelt; "
             "das Ergebnis änderte sich um {eff} %.",
        expected="Schätzfehler: Da eine vorhergesagte Windgeschwindigkeit nicht exakt ist und die Leistungskurve nicht linear verläuft, "
                 "wurde die Leistung über den typischen Schätzfehler gemittelt. Das vermeidet eine systematische Unterschätzung der Energie.",
        h4="4. Genauigkeit des Verfahrens",
        acc1="Das Verfahren wurde an echten Messwerten getestet, die es nicht kannte ({test_range}). Fehler der Windgeschwindigkeit: "
             "{rmse} m/s (RMSE), {mae} m/s (MAE) im Mittel über die betroffenen Anlagen. Über dieselben Tage wich die geschätzte Energie "
             "von der aus der gemessenen Windgeschwindigkeit berechneten Energie um {devs} ab.",
        acc_nodev="Es lagen keine zurückgehaltenen Messwerte vor; die Genauigkeit wurde daher für {val_range} geprüft.",
        range_txt="Der Bereich ist bewusst konservativ: Er nimmt an, dass alle Schätzfehler gleichzeitig in dieselbe Richtung wirken.",
        h5="5. Annahmen und Einschränkungen",
        l1="Die Energie wird mit der Leistungskurvenmethode aus 10-Minuten-Mittelwerten der Windgeschwindigkeit berechnet; Abregelung, "
           "Verfügbarkeitsverluste oder andere Ursachen sind nur enthalten, soweit sie in der gelieferten Leistungskurve stecken.",
        l2="Die Referenzanlagen stehen nicht am betroffenen Standort; die Schätzung beruht auf dem statistischen Zusammenhang der Standorte im Trainingszeitraum.",
        l3="Zeitstempel sind Ortszeit (Europe/Berlin).",
        cmp="An den Testtagen bei {turbine} lag der Fehler der Windgeschwindigkeit bei {ours} m/s mit dem verwendeten Verfahren und bei {lo} bis {hi} m/s "
            "mit den übrigen verglichenen MCP-Varianten (OLS, Varianzverhältnis, orthogonal und klassiert).",
        h6="6. Normen und Quellen",
        std1="Verfahrensfamilie: Die Windgeschwindigkeit wurde mit Measure-Correlate-Predict (MCP) rekonstruiert, einem Standardansatz der "
             "Windpotenzialbestimmung. Der Zusammenhang zwischen Referenz- und betroffener Anlage wird aus gleichzeitigen Messungen gelernt und dann "
             "auf die Referenzdaten des Ausfalls angewendet [1, 2].",
        std2="Leistung und Energie: 10-Minuten-Mittelwerte der Windgeschwindigkeit und die Herstellerleistungskurve, die Datenbasis der "
             "Leistungskurvenmessung nach IEC 61400-12-1 [3].",
        std3="Luftdichte: Die Windgeschwindigkeit wird mit v × (ρ / ρ₀)^(1/3), ρ₀ = {rho0} kg/m³, auf die Luftdichte der Leistungskurve normiert, "
             "wie in IEC 61400-12-1 beschrieben [3].",
        std4="Diese Quellen beschreiben die verwendeten Verfahren. Dieser Bericht erhebt keinen Anspruch auf formale Zertifizierung oder Normkonformität.",
        refs=["[1] Basse, A. et al. (2021), Wind Energy Science 6, 1473: Langzeitkorrektur kurzer Windmessungen (MCP).",
              "[2] Rogers, A.L., Rogers, J.W., Manwell, J.F. (2005), Comparison of the performance of four measure-correlate-predict algorithms.",
              "[3] IEC 61400-12-1, Wind energy generation systems - Part 12-1: Power performance measurements of electricity producing wind turbines."],
        attach="Anlage: {file} (10-Minuten-Werte für Windgeschwindigkeit, Leistung und Energie während des Ausfalls).",
        close="Für weitere Informationen oder die zugrunde liegenden Daten stehe ich gern zur Verfügung.",
        regards="Mit freundlichen Grüßen", none_ref="",
    ),
}


EXTRA_NAMES = {
    "turbulence": ("reference turbulence", "Referenz-Turbulenz"), "temperature": ("reference temperature", "Referenz-Temperatur"),
    "pressure": ("reference air pressure", "Referenz-Luftdruck"), "pressure_trend": ("air-pressure change", "Luftdruckänderung"),
    "time_of_day": ("time of day", "Tageszeit"), "wind_trend": ("6 h mean reference wind", "6-h-Mittel des Referenzwinds"),
    "wind_ramp": ("reference wind change", "Änderung des Referenzwinds"),
}


def _list(items, lang):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" und " if lang == "de" else " and ") + items[-1]


def build_report(lang: str, f: dict) -> tuple[str, str]:
    """Return (subject, body). `f` holds the facts, see app.py."""
    t = TXT[lang]
    de = lang == "de"
    num = (lambda x: f"{x:,.0f}".replace(",", ".")) if de else (lambda x: f"{x:,.0f}")
    def fl(x, nd=1, sign=False):
        out = f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"
        return out.replace(".", ",") if de else out

    names = [r["name"] for r in f["turbines"]]
    site_s = f" ({f['site']})" if f.get("site") else ""
    site_in = f" {'am Standort' if de else 'at'} {f['site']}" if f.get("site") else ""
    ref_s = f" [{f['claim']}]" if f.get("claim") else ""
    subject = t["subject"].format(turbines=_list(names, lang), site_s=site_s, total=num(f["total"]), ref_s=ref_s)

    w = max(len(t["col_t"]), max(len(n) for n in names))
    rows = [f"  {t['col_t']:<{w}}  {t['col_e']:>14}  {t['col_r']:>22}  {t['col_w']:>16}"]
    for r in f["turbines"]:
        rows.append(f"  {r['name']:<{w}}  {num(r['loss']):>14}  {num(r['lo']) + ' - ' + num(r['hi']):>22}  {fl(r['mean_wind']):>16}")
    table = "\n".join(rows)

    if f["method_kind"] == "reg":
        sectors = t["sectors_txt"].format(n=f["sectors"]) if f["sectors"] > 1 else ""
        extras = (t["extras_txt"].format(list=", ".join(EXTRA_NAMES[k][1 if de else 0] for k in f["extras"]))
                  if f["extras"] else "")
        method = t["method_reg"].format(n_train=num(f["n_train"]), sectors=sectors, extras=extras)
    else:
        method = t["method_other"].format(name=f["method_name"])

    notes = [t["m1"].format(refs=f["refs_text"], method=method), t["m2"]]
    if f.get("density") is not None:
        notes.append(t["density"].format(rho=fl(f["density"]["rho"], 3), rho0=fl(f["density"]["rho0"], 3), eff=fl(f["density"]["eff"], 1, True)))
    if f.get("turb_eff") is not None:
        notes.append(t["turb"].format(eff=fl(f["turb_eff"], 1, True)))
    if f["expected"]:
        notes.append(t["expected"])

    with_test = [r for r in f["turbines"] if r.get("test_dev") is not None]
    if with_test:
        devs = _list([f"{fl(r['test_dev'], 1, True)} % ({r['name']})" for r in with_test], lang)
        acc = t["acc1"].format(test_range=f["test_range"], rmse=fl(sum(r["test_rmse"] for r in with_test) / len(with_test), 2),
                               mae=fl(sum(r["test_mae"] for r in with_test) / len(with_test), 2), devs=devs)
    else:
        acc = t["acc_nodev"].format(val_range=f.get("val_range", "-"))

    if f.get("recipient"):
        greeting = t["greeting"].format(name=f["recipient"])
    else:
        greeting = "Sehr geehrte Damen und Herren," if de else "Dear Sir or Madam,"
    cmp_line = ""
    if f.get("method_cmp"):
        mc = f["method_cmp"]
        cmp_line = t["cmp"].format(turbine=mc["turbine"], ours=fl(mc["ours"], 2), lo=fl(mc["lo"], 2), hi=fl(mc["hi"], 2))
    rho0_txt = fl(f["density"]["rho0"], 3) if f.get("density") else fl(1.225, 3)
    std = [t["std1"], t["std2"]] + ([t["std3"].format(rho0=rho0_txt)] if f.get("density") else []) + [t["std4"]]
    body = "\n".join([
        greeting, "",
        t["intro"].format(turbines=_list(names, lang), site_in=site_in), "",
        t["h1"], "  " + t["period"].format(start=f["start"].strftime(t["fmt"]), end=f["end"].strftime(t["fmt"])),
        "  " + t["duration"].format(hours=fl(f["hours"])), "  " + t["affected"].format(turbines=", ".join(names)), "",
        t["h2"], table, "",
        "  " + t["total_line"].format(total=num(f["total"]), lo=num(f["lo"]), hi=num(f["hi"])), "",
        t["h3"], *[f"  - {n}" for n in notes], "",
        t["h4"], "  " + acc, *(["  " + cmp_line] if cmp_line else []), "  " + t["range_txt"], "",
        t["h5"], f"  - {t['l1']}", f"  - {t['l2']}", f"  - {t['l3']}", "",
        t["h6"], *[f"  - {x}" for x in std], "", *[f"  {r}" for r in t["refs"]], "",
        t["attach"].format(file=f["csv_name"]), t["close"], "",
        t["regards"], f.get("sender") or "", f.get("company") or "",
    ]).rstrip() + "\n"
    return subject, body


def predictions_csv(parts: dict) -> str:
    """parts: {turbine: DataFrame(index=timestamp, columns wind_ms, power_kw, energy_kwh, energy_low_kwh, energy_high_kwh)}."""
    frames = []
    for name, df in parts.items():
        d = df.copy()
        d.insert(0, "turbine", name)
        frames.append(d)
    out = pd.concat(frames)
    out.index.name = "timestamp"
    return out.round(3).to_csv()


def build_eml(subject: str, body: str, csv_text: str, csv_name: str, to: str = "", sender: str = "") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    if to:
        msg["To"] = to
    if sender:
        msg["From"] = sender
    msg["X-Unsent"] = "1"  # opens as an editable draft in Outlook / Apple Mail
    msg.set_content(body)
    msg.add_attachment(csv_text.encode("utf-8"), maintype="text", subtype="csv", filename=csv_name)
    return bytes(msg)


def export_csv(parts: dict, tests: dict | None = None, layout: str = "long") -> str:
    """Predicted values as CSV.

    parts: {turbine: DataFrame(index=timestamp; wind_ms, power_kw, energy_kwh, energy_low_kwh, energy_high_kwh)} for the outage.
    tests: optional {turbine: DataFrame(index=timestamp; measured_wind_ms, wind_ms)} for the held-out test days.
    layout: "long" (one row per turbine and time step) or "wide" (one row per time step, columns per turbine).
    """
    if layout == "wide":
        cols = {}
        for name, df in parts.items():
            cols[f"{name}_wind_ms"] = df["wind_ms"]
            cols[f"{name}_power_kw"] = df["power_kw"]
            cols[f"{name}_energy_kwh"] = df["energy_kwh"]
        out = pd.DataFrame(cols)
        out.insert(0, "period", "outage")
        if tests:
            tcols = {}
            for name, df in tests.items():
                tcols[f"{name}_wind_ms"] = df["wind_ms"]
                tcols[f"{name}_measured_wind_ms"] = df["measured_wind_ms"]
            t = pd.DataFrame(tcols)
            t.insert(0, "period", "test")
            out = pd.concat([out, t]).sort_index()
    else:
        frames = []
        for name, df in parts.items():
            d = df.copy()
            d.insert(0, "turbine", name)
            d.insert(1, "period", "outage")
            frames.append(d)
        for name, df in (tests or {}).items():
            d = df.copy()
            d.insert(0, "turbine", name)
            d.insert(1, "period", "test")
            frames.append(d)
        out = pd.concat(frames).sort_index(kind="stable")
        lead = [c for c in ["turbine", "period", "measured_wind_ms", "wind_ms"] if c in out.columns]
        out = out[lead + [c for c in out.columns if c not in lead]]
        out = out.rename(columns={"wind_ms": "predicted_wind_ms", "power_kw": "predicted_power_kw",
                                  "energy_kwh": "predicted_energy_kwh"})
    out.index.name = "timestamp"
    return out.round(3).to_csv(date_format="%Y-%m-%d %H:%M")
