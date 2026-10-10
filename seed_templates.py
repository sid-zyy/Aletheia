"""Version 1 of the logsheet templates, one per test document, plus the customer request form.

These only seed the template registry on first start. From then on the mappings live in the database and are changed by an
administrator (new version, tested, activated), never here. The layout (which cell holds what) is computed from the compact
specs below: single values in two label/value column pairs, tables underneath. Every value cell gets a defined name, so a
sheet stays readable when the lab inserts rows or columns.

Q8 is still open (the lab's own logsheets): when they arrive, their layouts become new template versions (label and table
mappings work on sheets Aletheia did not draw).
"""
import re

# field spec: (path, label, type[, required]) ; table spec: dict(table=path, caption, columns=[...], rows=n, **options)
NUM, TXT, DATE = "number", "text", "date"
SPECS = {
    "work": ("Work instruction", "WI", [
        ("series", "Test series no.", TXT, True), ("sample", "Sample code no.", TXT, True), ("customer", "Customer", TXT),
        ("start", "Test started", DATE), ("completed", "Test completed", DATE), ("standard", "Standard", TXT),
        ("allotted", "Allotted to", TXT), ("engineer", "Test engineer", TXT, True)], ("@ids.work[0]", "@ids.work[1]")),
    "proforma": ("Proforma for transformers", "PF", [
        ("kva", "Rating (kVA)", NUM, True), ("hv", "HV voltage (V)", NUM, True), ("lv", "LV voltage (V)", NUM, True),
        ("hv_max_kv", "Highest system voltage (kV)", NUM), ("bil", "Insulation levels", TXT), ("z_pct", "Impedance at 75 C (%)", NUM, True),
        ("phases", "Phases", NUM), ("freq", "Frequency (Hz)", NUM), ("vector", "Vector group", TXT), ("cooling", "Cooling", TXT),
        ("taps", "Tapping range", TXT), ("loss50", "Guaranteed total loss, 50% load (W)", NUM), ("loss100", "Guaranteed total loss, 100% load (W)", NUM),
        ("oil_l", "Oil quantity (l)", TXT), ("mfg", "Month / year of manufacture", TXT), ("construction", "Construction", TXT),
        ("limits.oil", "Top-oil rise limit (K)", NUM), ("limits.wdg", "Winding rise limit (K)", NUM),
        ("efficiency", "Energy efficiency level", TXT), ("coil", "Coil", TXT), ("core", "Core material", TXT),
        ("lv_winding", "LV winding details", TXT), ("hv_winding", "HV winding details", TXT),
        dict(table="tests", caption="Tests to be carried out", rows_as="values", rows=10, columns=[dict(label="Test", type=TXT)])], None),
    "losses": ("Losses datasheet", "LS", [
        ("nll_bt", "No-load loss before SC (W)", NUM), ("nll_at", "No-load loss after SC (W)", NUM),
        dict(table="rows", caption="Losses and impedance (75 C)", rows=9, required=True, columns=[
            dict(label="Tap / condition", type=TXT), dict(label="%Z"), dict(label="%X"), dict(label="%X change"), dict(label="R HV (ohm)"),
            dict(label="R LV (mohm)"), dict(label="Load loss 100% (W)"), dict(label="X/R"), dict(label="Isc peak (kA)"), dict(label="Isc rms (kA)"),
            dict(label="Stray loss (W)"), dict(label="Load loss 50% (W)"), dict(label="Total loss 50% (W)"), dict(label="Total loss 100% (W)")])],
        ("@ids.losses[0]", "@ids.losses[1]"), [dict(field="cols", by="const", value=["tap", "z", "x", "xchg", "rhv", "rlv", "ll100", "xr", "ipk", "irms", "stray", "ll50", "t50", "t100"])]),
    "resistance": ("Losses logsheet (resistance)", "RS", [
        ("date_bt", "Date, before SC", DATE), ("date_at", "Date, after SC", DATE), ("oil_top[0]", "Top oil before (C)", NUM),
        ("oil_top[1]", "Top oil after (C)", NUM), ("oil_bot[0]", "Bottom oil before (C)", NUM), ("oil_bot[1]", "Bottom oil after (C)", NUM),
        dict(table="hv", caption="Winding resistance (HV ohm, LV milli-ohm)", rows=4, rows_as="dict", keys=["N", "H", "L"], required=True, columns=[
            dict(label="Tap / winding", type=TXT), dict(group=["BT R1", "BT R2", "BT R3"], title="Before short circuit"),
            dict(group=["AT R1", "AT R2", "AT R3"], title="After short circuit")]),
        dict(table="lv", share="hv", rows_as="row", key="LV", required=True)], ("@ids.resistance[0]", "@ids.resistance[1]")),
    "noload": ("Losses logsheet (no-load)", "NL", [
        ("v100", "Rated voltage, 100% (V)", NUM), ("v1125", "Voltage at 112.5% (V)", NUM), ("remarks", "Remarks", TXT),
        dict(table="rows", caption="No-load readings", rows=6, required=True, columns=[
            dict(label="Condition", type=TXT), dict(group=["V1", "V2", "V3"], title="Voltage (V)"), dict(label="Average V"),
            dict(group=["I1", "I2", "I3"], title="Current (A)"), dict(label="Average I"), dict(group=["W1", "W2", "W3"], title="Watts"),
            dict(label="Total W"), dict(label="Frequency (Hz)"), dict(label="Corrected loss (W)")])], ("@ids.noload[0]", "@ids.noload[1]")),
    "routine": ("Routine test logsheet", "RT", [
        ("date_bt", "Date, before SC", DATE), ("date_at", "Date, after SC", DATE), ("amb[0]", "Ambient before (C)", NUM), ("amb[1]", "Ambient after (C)", NUM),
        ("rh[0]", "RH before (%)", NUM), ("rh[1]", "RH after (%)", NUM), ("vector", "Vector group (measured)", TXT),
        ("induced.v", "Induced test voltage (V)", NUM), ("induced.f", "Induced test frequency (Hz)", NUM), ("induced.t", "Induced test duration (s)", NUM),
        ("induced.i[0]", "Induced test current, start (A)", NUM), ("induced.i[1]", "Induced test current, end (A)", NUM), ("induced.obs", "Induced test observation", TXT),
        ("hvac.kv", "HV separate source test (kV)", NUM), ("hvac.t", "HV separate source duration (s)", NUM), ("hvac.obs", "HV separate source observation", TXT),
        ("lvac.kv", "LV separate source test (kV)", NUM), ("lvac.t", "LV separate source duration (s)", NUM), ("lvac.obs", "LV separate source observation", TXT),
        dict(table="ir", caption="Insulation resistance (Gohm)", rows=3, rows_as="dict", columns=[dict(label="Between", type=TXT), dict(label="IR before"), dict(label="IR after")]),
        dict(table="ratio.BT", caption="Voltage ratio, all taps", rows=7, pick=1, columns=[
            dict(label="Tap no.", type=TXT), dict(group=["BT 1U", "BT 1V", "BT 1W"], title="Before short circuit"),
            dict(group=["AT 1U", "AT 1V", "AT 1W"], title="After short circuit")]),
        dict(table="ratio.AT", share="ratio.BT", pick=2)], ("@ids.routine[0]", "@ids.routine[1]")),
    "sc": ("Short-circuit logsheet", "SC", [
        ("date", "Date of test", DATE), ("condition", "Condition of sample", TXT), ("during", "Observation during test", TXT),
        ("after", "Observation after test", TXT), ("inspection", "Untanking / inspection", TXT),
        dict(table="required", caption="Required test currents", rows=3, rows_as="dict", required=True, columns=[
            dict(label="Tap", type=TXT), dict(label="Required rms (kA)"), dict(label="Required peak (kA)")]),
        dict(table="shots", caption="Oscillograms", rows=30, required=True, columns=[
            dict(label="Oscillogram no.", type=TXT), dict(label="Tap position", type=TXT), dict(label="Setting (as logged)"), dict(label="Peak (kA)"),
            dict(label="RMS U (kA)"), dict(label="RMS V (kA)"), dict(label="RMS W (kA)"), dict(label="Average rms (kA)"), dict(label="Duration (s)"),
            dict(label="Note", type=TXT, blank="")])], ("@ids.sc[0]", "@ids.sc[1]")),
    "temp": ("Temperature-rise logsheet", "TR", [
        ("dates", "Date(s) of test", TXT), ("tap", "Tap position", TXT), ("current", "Test current (A)", NUM), ("nll", "No-load loss (W)", NUM),
        ("fll", "Full-load loss (W)", NUM), ("total", "Total loss injected (W)", NUM), ("rhv_cold", "HV cold resistance (ohm)", NUM),
        ("rlv_cold", "LV cold resistance (mohm)", NUM), ("amb_cold", "Ambient at cold resistance (C)", NUM), ("rhv_hot", "HV hot resistance (ohm)", NUM),
        ("rlv_hot", "LV hot resistance (mohm)", NUM), ("amb_sd", "Ambient at shut-down (C)", NUM), ("corr", "Correction used in formula (K)", NUM),
        ("corr_written", "Correction written on sheet (K)", NUM), ("oil_rise_reported", "Top-oil rise, as logged (K)", NUM),
        ("hv_rise", "HV winding rise, as logged (K)", NUM), ("lv_rise", "LV winding rise, as logged (K)", NUM),
        ("material_k", "Winding material constant (235 Cu / 225 Al)", NUM),
        dict(table="hours", caption="Hourly readings", rows=24, required=True, columns=[
            dict(label="Hour"), dict(label="Top oil (C)"), dict(label="Bottom oil (C)"), dict(label="Ambient 1 (C)"), dict(label="Ambient 2 (C)"), dict(label="Ambient 3 (C)")])],
        ("@ids.temp[0]", "@ids.temp[1]")),
    "pressure": ("Pressure / oil-leakage logsheet", "PR", [
        ("amb", "Ambient (C)", NUM), ("atm_kpa", "Atmospheric pressure (kPa)", NUM), ("plate_m", "Plate / tank height (m)", NUM), ("routine.kpa", "Routine pressure (kPa)", NUM),
        ("routine.min", "Routine pressure duration (min)", NUM), ("routine.date", "Routine pressure date", DATE), ("routine.obs", "Routine pressure observation", TXT),
        ("type.date", "Type tests date(s)", TXT), ("type.pressure.kpa", "Type pressure (kPa)", NUM), ("type.pressure.min", "Type pressure duration (min)", NUM),
        ("type.pressure.max", "Pressure: max deflection, as logged (mm)", NUM), ("type.pressure.obs", "Pressure test observation", TXT),
        ("type.vacuum.mmhg", "Vacuum (mmHg)", NUM), ("type.vacuum.min", "Vacuum duration (min)", NUM), ("type.vacuum.max", "Vacuum: max deflection, as logged (mm)", NUM),
        ("type.vacuum.obs", "Vacuum test observation", TXT), ("leak.kpa", "Oil leakage pressure (kPa)", NUM), ("leak.head_kpa", "Oil head (kPa)", NUM),
        ("leak.hrs", "Oil leakage duration (h)", NUM), ("leak.date", "Oil leakage date", DATE), ("leak.obs", "Oil leakage observation", TXT),
        dict(table="type.pressure.pts", caption="Pressure test: deflection points (mm)", rows=6, columns=[dict(label="Pressure: before"), dict(label="Pressure: after")]),
        dict(table="type.vacuum.pts", caption="Vacuum test: deflection points (mm)", rows=6, columns=[dict(label="Vacuum: before"), dict(label="Vacuum: after")])],
        ("@ids.pressure[0]", "@ids.pressure[1]")),
}
# Optional values the lab may not log on every sheet (Q11: logged winding rises)
OPTIONAL_OK = {"temp": {"hv_rise", "lv_rise", "oil_rise_reported", "corr_written"},
               "proforma": {"efficiency", "coil", "core", "lv_winding", "hv_winding"},  # printed on the description sheet when given
               "pressure": {"atm_kpa"}}


def slug(path): return re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_").upper()


def layout(section):
    title, prefix, items, ids, consts = (SPECS[section] + (None,))[:5]
    fields, row = [], 4
    if ids:  # identifiers as written on this sheet
        fields += [dict(field=ids[0], label="Test series no. (as written)", cell="B3", name=f"{prefix}_SERIES", type=TXT),
                   dict(field=ids[1], label="Sample code no. (as written)", cell="E3", name=f"{prefix}_SAMPLE", type=TXT)]
        if section == "work": fields[0]["cell"], fields[1]["cell"] = "B4", "E4"; row = 6
    singles = [x for x in items if isinstance(x, tuple)]
    for n, (path, label, typ, *req) in enumerate(singles):
        col = "B" if n % 2 == 0 else "E"
        if section == "work" and path in ("series", "sample"):  # the work instruction's own identifiers are its main fields
            cell = "B4" if path == "series" else "E4"
            fields = [f for f in fields if f["cell"] != cell or f["field"].startswith("@")]
        else:
            cell = f"{col}{row}"
            if n % 2: row += 1
        fields.append(dict(field=path, label=label, cell=cell, name=f"{prefix}_{slug(path)}", type=typ, required=bool(req and req[0])))
    row += 3
    placed = {}
    for t in [x for x in items if isinstance(x, dict)]:
        f = dict(field=t["table"], type="table", **{k: v for k, v in t.items() if k not in ("table", "share")})
        if t.get("share"):
            base = placed[t["share"]]
            f.update(at=base["at"], columns=base["columns"], rows=base["rows"], caption=None)
        else:
            f["at"] = f"A{row}"; placed[t["table"]] = f
            row += f.get("rows", 5) + (2 if any("group" in c for c in f["columns"]) else 1) + 3
        fields.append(f)
    for c in consts or []: fields.append(dict(c))
    return dict(section=section, title=title, sheet_title=title, version=1, kind="logsheet",
                fingerprint=dict(contains=f"Aletheia template {section}", within="A1:L3"), fields=fields)


REQUEST_FIELDS = (("customer", "Customer name"), ("address", "Address (street, area)"), ("city", "City / town"), ("state", "State / union territory"),
                  ("pin", "PIN code"), ("contact", "Contact person"), ("phone", "Phone"), ("email", "Email (for notifications)"),
                  ("sample", "Product description"), ("rating", "Rating"), ("serial", "Serial number"), ("manufacturer", "Manufacturer"),
                  ("drawings", "Drawing numbers"), ("tests", "Tests requested"), ("criteria", "Reference standard"),
                  ("witness", "Witness present (yes / no)"), ("witness_name", "Witness name and organisation"),
                  ("conformity", "Statement of conformity / decision rule"))


def request_form():
    """The customer request form, sent to the customer as an Excel file and read back at intake (labels, not fixed cells)."""
    fields = [dict(field=k, label=l, cell=f"B{4 + n}", name=f"RQ_{k.upper()}", type="text", by=["name", "label", "cell"]) for n, (k, l) in enumerate(REQUEST_FIELDS)]
    return dict(section="request", title="Customer request form", sheet_title="Customer request form", version=1, kind="request_form",
                fingerprint=dict(contains="Aletheia template request", within="A1:L3"), fields=fields)


def all_templates():
    """[(key, kind, section, name, mapping)] for the first start."""
    out = [(f"{s}-std", "logsheet", s, SPECS[s][0], layout(s)) for s in SPECS]
    out.append(("request-form", "request_form", "request", "Customer request form", request_form()))
    return out
