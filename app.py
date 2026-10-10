"""Aletheia - Automated Test Report Generation System (CPRI Short Circuit Laboratory).
Run:  pip install -r requirements.txt && python app.py   ->  http://localhost:5000
Modules: Data Collection (importers.py: JSON / CSV / Excel / SQLite; vision.py: optional scan reading) | Database (SQLite)
         | Validation | Report Engine (PDF, frozen versions + QR verification) | Dashboard (static/index.html)
"""
import base64, json, hashlib, io, math, os, re, secrets, sqlite3, datetime as dt
import importers, vision
import rules
from rules import val as rule, nll_limits, ratio_tolerance, classify_observation
from statistics import mean
from flask import Flask, request, jsonify, send_file, send_from_directory, abort
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ALETHEIA_DB") or os.path.join(HERE, "aletheia.db")
AI_CACHE = os.path.join(os.path.dirname(os.path.abspath(DB)), "ai_cache.db")  # survives deleting the job database
DEMO = os.path.join(HERE, "sample_data", "AP_Transformers_25T1654.json")
DEMO_SCANS = os.path.join(HERE, "sample_data", "scans")  # the scanned sheets the demo data was typed from

def load_demo():
    with open(DEMO, encoding="utf-8") as f: return json.load(f)

app = Flask(__name__, static_folder=os.path.join(HERE, "static"))
STAGES = ["Request Captured", "Data Imported", "Validated", "Report Generated", "Approved & Exported"]
NAMES = {"request": "Customer request form", "proforma": "Proforma for transformers", "work": "Work instruction",
         "losses": "Losses datasheet", "resistance": "Losses logsheet (resistance)", "noload": "Losses logsheet (no-load)",
         "routine": "Routine test logsheet", "sc": "Short-circuit logsheet", "temp": "Temperature-rise logsheet",
         "pressure": "Pressure / oil-leakage logsheet"}
now = lambda: dt.datetime.now().isoformat(timespec="seconds")

# ----------------------------------------------------------------- database
from contextlib import contextmanager

@contextmanager
def db():
    """One short transaction per use: commit on success, roll back on error, always close."""
    c = sqlite3.connect(DB, timeout=15); c.row_factory = sqlite3.Row
    try:
        with c: yield c
    finally:
        c.close()

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, series TEXT UNIQUE, sample TEXT, customer TEXT, rating TEXT,
            stage INTEGER DEFAULT 0, data TEXT DEFAULT '{}', findings TEXT DEFAULT '[]', approver TEXT, approver_id TEXT, created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, job_id INT, source TEXT, kind TEXT, sha256 TEXT, at TEXT, UNIQUE(job_id, sha256));
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, job_id INT, filename TEXT, mime TEXT, sha256 TEXT, content BLOB, at TEXT, UNIQUE(job_id, sha256));
        CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, job_id INT, version INT, token TEXT UNIQUE, sha256 TEXT, pdf BLOB, approver TEXT, approver_id TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS vision_calls(id INTEGER PRIMARY KEY, day TEXT, model TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, job_id INT, event TEXT, at TEXT);""")
        for t in ("jobs", "reports"):  # databases from before the approver's employee ID was recorded
            if "approver_id" not in {r[1] for r in c.execute(f"PRAGMA table_info({t})")}: c.execute(f"ALTER TABLE {t} ADD COLUMN approver_id TEXT")

def log(c, jid, ev): c.execute("INSERT INTO audit(job_id,event,at) VALUES(?,?,?)", (jid, ev, now()))

def getjob(jid, full=True):
    with db() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not r: abort(404)
        j = dict(r); j["data"] = json.loads(j["data"]); j["findings"] = json.loads(j["findings"])
        j["stage_name"] = STAGES[j["stage"]]
        if full:
            j["audit"] = [dict(a) for a in c.execute("SELECT event,at FROM audit WHERE job_id=? ORDER BY id", (jid,))]
            j["imports"] = [dict(a) for a in c.execute("SELECT source,kind,sha256,at FROM imports WHERE job_id=?", (jid,))]
            j["sources"] = [dict(a) for a in c.execute("SELECT id,filename,mime,sha256,at FROM sources WHERE job_id=? ORDER BY id", (jid,))]
            j["reports"] = [dict(a) for a in c.execute("SELECT version,token,sha256,approver,approver_id,at FROM reports WHERE job_id=? ORDER BY version DESC", (jid,))]
        return j

def save(jid, **kw):
    kw["updated"] = now()
    with db() as c:
        c.execute(f"UPDATE jobs SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*[json.dumps(v) if isinstance(v, (dict, list)) else v for v in kw.values()], jid))

# --------------------------------------------------------------- validation
def validate(d):
    """Returns (findings, calc). Levels: pass / warn (needs reviewer attention) / fail (blocks)."""
    F, C = [], {}
    def add(l, c, t, src=None, found=None, exp=None, fix=None, na=False, basis=None, inconclusive=False, cause=None):
        """src: document(s) checked; found / exp: observed vs required value; fix: what the engineer should do.
        cause: technical reason a check was skipped, for the engineer only; never printed in the report."""
        f = dict(level=l, check=c, detail=t, **({"na": True} if na else {}), **({"inconclusive": True} if inconclusive else {}))
        if cause: f["cause"] = cause
        if basis: f["basis"] = rules.basis(*basis)  # where the threshold comes from and whether anyone has confirmed it
        f.update({k: v for k, v in dict(source=src, found=found, expected=exp, action=fix).items() if v is not None})
        for k in ("detail", "found", "expected"):  # an empty value formatted into the text reads NA, not Python's "None"
            if isinstance(f.get(k), str): f[k] = re.sub(r"\bNone\b", "NA", f[k])
        F.append(f)
    def na(check, src=None):
        """A blank (NA) or incomplete value skips only this check: it is reported as not evaluated instead of failing the run."""
        @contextmanager
        def guard():
            try:
                yield
            except (TypeError, ValueError, KeyError, IndexError, AttributeError, ZeroDivisionError) as e:
                if check: add("warn", check, f"Not evaluated: values it needs in the {src or 'source document'} are NA (left empty) or incomplete.", src=src, found="NA",
                              exp="All values this check needs", na=True, cause=f"{type(e).__name__}: {e}",
                              fix="Fill in the missing values if this test was performed; otherwise leave them as NA. The report lists it as not evaluated.")
        return guard()
    miss = [v for k, v in NAMES.items() if k not in d]
    # Missing documents do not block the report: checks run on what is present, and the report says what was not evaluated.
    add("warn" if miss else "pass", "Completeness of source documents",
        f"Missing: {', '.join(miss)}. Checks that need them were skipped; the report marks those tests as not evaluated." if miss
        else "All 10 source documents imported",
        src="All source documents", found=f"{len(NAMES) - len(miss)} of {len(NAMES)} documents imported", exp=f"All {len(NAMES)} documents",
        fix=("Import the missing documents if those tests were performed. If they were not requested, approve the report as it is; "
             "the missing tests are listed as not evaluated.") if miss else None)
    if "proforma" not in d and any(k in d for k in ("noload", "losses", "routine", "temp")):
        add("warn", "Limits not available", "The proforma is missing, so loss, impedance, no-load current, ratio and temperature-rise "
            "results could not be compared with their limits.", src=NAMES["proforma"], found="Proforma not imported",
            exp="Proforma with rating, guaranteed losses, impedance and temperature-rise limits",
            fix="Import the proforma to evaluate these results against their limits.")
    # 1. identifiers must agree across documents (handwriting: 4 can read as H or 6)
    norm = lambda s: s.upper().replace("H", "4")
    ids = d.get("ids", {})
    with na('Identifier consistency', "Identifiers on each sheet"):
        if "work" in ids:
            ws, wm = norm(ids["work"][0])[-7:], norm(ids["work"][1])[-4:]
            bad = [(k, s, m) for k, (s, m) in ids.items() if norm(s)[-7:] != ws or norm(m)[-4:] != wm]
            for k, s, m in bad:
                add("warn", "Identifier consistency", f"{NAMES.get(k, k)}: transcribed '{s}' / '{m}' but work instruction = {ws} / {wm}. Verify handwriting (4/6/H).",
                    src=NAMES.get(k, k), found=f"Series {s}, sample {m}", exp=f"Series ...{ws}, sample ...{wm} (as on the work instruction)",
                    fix=f"Look at the IDs on the scanned {NAMES.get(k, k).lower()}; handwritten 4, 6 and H are easy to confuse. If it was mistyped, correct it under 'Identifiers on each sheet'.")
            if not bad: add("pass", "Identifier consistency", f"Series {ws} / sample {wm} agree in all documents", src="All source documents")
    P = d.get("proforma", {})
    if P:
        with na(None):
            irat = P["kva"] * 1000 / ((math.sqrt(3) if P.get("phases", 3) == 3 else 1) * P["lv"]); C["irat"] = irat
    # 2. resistance
    R = d.get("resistance")
    if R:
        with na('Winding resistance phase imbalance', NAMES["resistance"]):
            worst = 0
            for ph in list(R["hv"].values()) + [R["lv"]]:
                for row in ph: worst = max(worst, (max(row) - min(row)) / mean(row) * 100)
            lim = rule("resistance_imbalance_pct")
            add("pass" if worst <= lim else "fail", "Winding resistance phase imbalance", f"Max imbalance {worst:.2f}% (limit {lim:g}%)",
                src=NAMES["resistance"], found=f"{worst:.2f}% between phases", exp=f"{lim:g}% or less", basis=("resistance_imbalance_pct",),
                fix="Re-check the three phase readings on the resistance log; a large imbalance can mean a winding fault or a misread value.")
        T = d.get("temp")
        if T:
            with na('Cold resistance cross-check', NAMES["temp"]):
                ok = abs(R["lv"][1][1] - T["rlv_cold"]) < 1e-4 and abs(R["hv"]["L"][1][1] - T["rhv_cold"]) < 1e-4
                add("pass" if ok else "warn", "Cold resistance cross-check", "Temp-rise cold R equals after-STC resistance at lowest tap" if ok else "Cold R in temp-rise log differs from resistance log",
                    src=f"{NAMES['temp']} vs {NAMES['resistance']}", found=f"Cold R in temp-rise log: HV {T['rhv_cold']}, LV {T['rlv_cold']}",
                    exp=f"Same as after-short-circuit resistance: HV {R['hv']['L'][1][1]}, LV {R['lv'][1][1]}",
                    fix=None if ok else "Confirm which cold resistance was used; the winding temperature rise depends on it.")
    # 3. no-load
    N = d.get("noload")
    if N and P:
        with na('No-load readings (averages and sums)', NAMES["noload"]):
            for lb, V, Va, I, Ia, W, Wa, f, Pc in N["rows"]:
                if abs(mean(I) - Ia) > .005: add("fail", "No-load current average", f"{lb}: mean of {I} = {mean(I):.3f}, logged {Ia}",
                    src=NAMES["noload"], found=f"{lb}: logged average {Ia} A", exp=f"Mean of I1, I2, I3 = {mean(I):.3f} A",
                    fix="Recalculate the average on the log sheet, or correct the phase current that was misread.")
                if abs(sum(W) - Wa) > .1: add("warn", "No-load watts sum", f"{lb}: W1+W2+W3 = {sum(W):.2f} but logged average/sum {Wa} (check reading)",
                    src=NAMES["noload"], found=f"{lb}: logged total {Wa} W", exp=f"W1 + W2 + W3 = {' + '.join(map(str, W))} = {sum(W):.2f} W",
                    fix="Check the three wattmeter readings and the total on the scan; one of them was probably misread or mis-added.")
        with na('No-load current limits', NAMES["noload"]):
            lim100, lim112 = nll_limits(P["kva"])
            r112 = [r for r in N["rows"] if "112" in str(r[0])]  # chosen by label, not by row position
            r100 = [r for r in N["rows"] if "112" not in str(r[0])]
            if not r112 or not r100: raise KeyError("a no-load row labelled 112.5% and at least one rated-voltage row")
            for nm, i, lim, key in (("100%", max(r[4] for r in r100), lim100, "nll_pct_to_200kva" if P["kva"] <= 200 else "nll_pct_above_200kva"),
                                    ("112.5%", max(r[4] for r in r112), lim112, "nll_112_pct_to_200kva" if P["kva"] <= 200 else "nll_112_pct_above_200kva")):
                pc = i / C["irat"] * 100
                add("pass" if pc <= lim else "fail", f"No-load current at {nm} voltage", f"{i} A = {pc:.2f}% of rated {C['irat']:.1f} A (limit {lim:g}% for {P['kva']} kVA)",
                    src=NAMES["noload"], found=f"{i} A ({pc:.2f}% of rated current)", exp=f"{lim:g}% of rated {C['irat']:.1f} A or less", basis=(key,),
                    fix=None if pc <= lim else "The sample exceeds the no-load current limit; confirm the reading before reporting a failure.")
    # 4. losses / impedance (IS 1180 limits from proforma, +/-10% impedance)
    L = d.get("losses")
    if L and P:
        with na('Total loss', NAMES["losses"]):
            rows = L["rows"]
            t100 = max(r[13] for r in rows); t50 = max(r[12] for r in rows if r[12])
            C["t100"], C["t50"] = t100, t50
            for pct, t, lim in (("100%", t100, P["loss100"]), ("50%", t50, P["loss50"])):
                cap = lim * (1 + rule("loss_positive_tolerance_pct") / 100)
                add("pass" if t <= cap else "fail", f"Total loss at {pct} load" + (" (75 C)" if pct == "100%" else ""), f"Max {t} W vs limit {lim} W",
                    src=NAMES["losses"], found=f"{t} W (worst tap)", exp=f"{lim} W or less (guaranteed in proforma)", basis=("loss_positive_tolerance_pct",),
                    fix=None if t <= cap else "Losses exceed the guaranteed value; confirm the readings and the 75 C correction.")
        with na('Impedance voltage (+/-10%)', NAMES["losses"]):
            zs = [r[1] for r in rows]; tol = rule("impedance_tolerance_pct") / 100; lo, hi = P["z_pct"] * (1 - tol), P["z_pct"] * (1 + tol)
            zok = all(lo <= z <= hi for z in zs)
            add("pass" if zok else "fail", "Impedance voltage (+/-10%)", f"%Z {min(zs)}-{max(zs)} vs declared {P['z_pct']} (band {lo:.2f}-{hi:.2f})",
                src=NAMES["losses"], found=f"%Z {min(zs)} to {max(zs)}", exp=f"{lo:.2f} to {hi:.2f} (declared {P['z_pct']}% +/-{tol * 100:g}%)", basis=("impedance_tolerance_pct",),
                fix=None if zok else "Impedance is outside the tolerance band; check the readings for each tap.")
        with na('Reactance change before/after short circuit', NAMES["losses"]):
            xc = max(abs(r[3]) for r in rows if r[3] is not None)
            xl = rule("reactance_change_pct")
            add("pass" if xc <= xl else "fail", "Reactance change before/after short circuit", f"Max {xc}% (limit {xl:g}%)" + (" - no winding displacement indicated" if xc <= xl else ""),
                src=NAMES["losses"], found=f"{xc}% change", exp=f"{xl:g}% or less", basis=("reactance_change_pct",),
                fix=None if xc <= xl else f"A reactance change above {xl:g}% suggests the windings moved during the short-circuit test.")
    # 5. voltage ratio, 7 taps +5% .. -10%
    Rt = d.get("routine")
    if Rt and P:
        with na('Voltage ratio, all taps', NAMES["routine"]):
            vph = P["lv"] / math.sqrt(3); dev = 0
            for side in Rt["ratio"].values():
                for i, row in enumerate(side):
                    th = P["hv"] * (1 + (5 - 2.5 * i) / 100) / vph
                    dev = max(dev, max(abs(x - th) / th * 100 for x in row))
            C["ratio_dev"] = dev
            rt = ratio_tolerance(P["z_pct"])
            add("pass" if dev <= rt else "fail", "Voltage ratio, all taps", f"Max deviation from theoretical {dev:.2f}% (tolerance {rt:.2f}%: smaller of 0.5% and 10% of {P['z_pct']}% impedance)",
                src=NAMES["routine"], found=f"{dev:.2f}% worst deviation", exp=f"{rt:.2f}% or less from the theoretical ratio", basis=("ratio_tolerance_pct", "ratio_impedance_fraction"),
                fix=None if dev <= rt else "Check the ratio readings for each tap on the routine test log.")
        with na('Dielectric routine tests', NAMES["routine"]):
            v = [classify_observation(Rt[k].get("obs")) for k in ("induced", "hvac", "lvac")]
            lvl = "fail" if False in v else "warn" if None in v else "pass"
            add(lvl, "Dielectric routine tests",
                {"pass": "Induced over-voltage, HV (28 kV) and LV (3 kV) power-frequency: withstood",
                 "fail": "A dielectric test records a discharge, flashover or breakdown.",
                 "warn": "The recorded observation could not be interpreted (empty or unusual wording), so it was not counted as passed."}[lvl],
                src=NAMES["routine"], found="; ".join(str(Rt[k].get("obs")) for k in ("induced", "hvac", "lvac")), exp="No disruptive discharge in any test",
                fix=None if lvl == "pass" else "Check the observations on the log against the scan; use plain wording such as 'No disruptive discharge, withstood'.")
    # 6. short circuit
    S = d.get("sc")
    if S:
        with na('SC RMS averages', NAMES["sc"]):
            for s in S["shots"]:
                if abs(mean(s[4:7]) - s[7]) > .01: add("warn", "SC RMS average", f"{s[0]}: mean {mean(s[4:7]):.3f} vs logged {s[7]}",
                    src=NAMES["sc"], found=f"Shot {s[0]}: logged average {s[7]} kA", exp=f"Mean of the three phases = {mean(s[4:7]):.3f} kA",
                    fix="Recalculate the average for this shot on the short-circuit log.")
        with na('SC current', NAMES["sc"]):
            C["sc"] = {}
            for tap, (ir, ip) in S["required"].items():
                sh = [s for s in S["shots"] if s[1] == tap and not s[9]]  # blank or NA note = normal shot
                mi, mp = mean(s[7] for s in sh), mean(s[3] for s in sh)
                C["sc"][tap] = (round(mi, 2), round(mp, 2))
                e = (mi - ir) / ir * 100
                tl = rule("sc_rms_tolerance_pct")
                add("pass" if abs(e) <= tl else "fail", f"SC current at {tap} tap", f"{len(sh)} shots: mean {mi:.2f} kA rms (req {ir}, {e:+.1f}%), peak {mp:.2f} kA (req {ip})",
                    src=NAMES["sc"], found=f"{mi:.2f} kA rms ({e:+.1f}%), peak {mp:.2f} kA over {len(sh)} shots", exp=f"{ir} kA rms +/-{tl:g}%, peak {ip} kA", basis=("sc_rms_tolerance_pct",),
                    fix=None if abs(e) <= tl else f"The applied current was outside +/-{tl:g}% of the required value; the test may need repeating.")
                # a mean can hide one bad shot: look at each shot, and at the peak, which was displayed but never checked
                off = [f"{s[0]} ({(s[7] - ir) / ir * 100:+.1f}%)" for s in sh if abs((s[7] - ir) / ir * 100) > tl]
                low = [f"{s[0]} ({s[3]} kA)" for s in sh if s[3] is not None and s[3] < ip]
                if off or low:
                    add("warn", f"SC shot-by-shot at {tap} tap", "; ".join(filter(None, [f"rms outside +/-{tl:g}%: " + ", ".join(off) if off else "", f"peak below required {ip} kA: " + ", ".join(low) if low else ""])),
                        src=NAMES["sc"], found=", ".join(off + low), exp=f"Every shot within +/-{tl:g}% rms and at or above {ip} kA peak", basis=("sc_rms_tolerance_pct",),
                        fix="Check these shots on the log. Whether a single shot below the required peak invalidates the test depends on the standard, which has not been checked.")
        with na('Thermal ability of SC', NAMES["sc"]):
            th = [s for s in S["shots"] if s[9] == "thermal"]
            tm = rule("sc_thermal_min_s")
            if th: add("pass" if th[0][8] >= tm else "fail", "Thermal ability of SC", f"Duration {th[0][8]} s (min {tm:g} s)",
                       src=NAMES["sc"], found=f"{th[0][8]} s", exp=f"{tm:g} s or more", basis=("sc_thermal_min_s",),
                       fix=None if th[0][8] >= tm else f"The thermal short-circuit shot was shorter than {tm:g} s.")
        with na('Post-test inspection', NAMES["sc"]):
            v = classify_observation(S["after"])
            add({True: "pass", False: "fail", None: "warn"}[v], "Post-test inspection",
                S["inspection"] if v is not None else f"The recorded finding '{S['after']}' could not be interpreted, so it was not counted as passed.",
                src=NAMES["sc"], found=S["after"], exp="No abnormalities",
                fix=None if v else "Abnormalities were recorded after the short-circuit test; review the untanking notes." if v is False
                    else "Check the finding against the scan; use plain wording such as 'No abnormalities'.")
    # 7. temperature rise
    T = d.get("temp")
    temp_ok = wdg_ok = False  # oil rise (hourly readings) and winding rise (resistances) are computed independently
    if T and P:
        with na('Top-oil temperature rise', NAMES["temp"]):
            rises = [h[1] - mean(h[3:6]) for h in T["hours"]]
            C.update(oil_rise=rises[-1]); temp_ok = True
        with na('Winding temperature rise', NAMES["temp"]):
            k, ca, cf = T["material_k"], T["amb_cold"], T["corr"]
            hv = T["rhv_hot"] / T["rhv_cold"] * (k + ca) - k - T["amb_sd"] + cf
            lv = T["rlv_hot"] / T["rlv_cold"] * (k + ca) - k - T["amb_sd"] + cf
            C.update(hv_rise=hv, lv_rise=lv); wdg_ok = True
        if temp_ok:
            with na('Top-oil temperature rise', NAMES["temp"]):
                oil = P["limits"]["oil"]
                um = rule("temp_margin_inconclusive_k"); thin = 0 <= oil - rises[-1] < um
                add("fail" if rises[-1] > oil else "warn" if thin else "pass", "Top-oil temperature rise", f"{rises[-1]:.2f} K (limit {oil} K" + (f", margin {oil - rises[-1]:.1f} K: inconclusive)" if thin else ")"),
                    src=NAMES["temp"], found=f"{rises[-1]:.2f} K at the last hour", exp=f"{oil} K or less", basis=("temp_margin_inconclusive_k",), inconclusive=thin,
                    fix=None if rises[-1] <= oil else "Top-oil rise exceeds the limit; the sample fails this test unless a reading is wrong.")
        if wdg_ok:
            with na('Winding temperature rise', NAMES["temp"]):
                w = P["limits"]["wdg"]
                for nm, v in (("HV", hv), ("LV", lv)):
                    um = rule("temp_margin_inconclusive_k"); thin = 0 <= w - v < um
                    add("fail" if v > w else "warn" if thin else "pass", f"{nm} winding temperature rise", f"{v:.1f} K (limit {w} K, margin {w - v:.1f} K" + (": inconclusive)" if thin else ")"),
                        src=NAMES["temp"], found=f"{v:.1f} K (margin {w - v:.1f} K)", exp=f"{w} K or less", basis=("temp_margin_inconclusive_k",), inconclusive=thin,
                        fix="Exceeds the limit; check the hot and cold resistance readings." if v > w else
                            f"Inconclusive: within {um:g} K of the limit, so a small reading or correction-factor error could change the verdict. Re-check the hot resistance and the correction factor; the lab's own measurement uncertainty should decide this." if thin else None)
        if temp_ok:
            with na('Steady-state criterion (<=1 K/h)', NAMES["temp"]):
                dd = [abs(rises[i + 1] - rises[i]) for i in range(len(rises) - 5, len(rises) - 1)]
                ss = rule("steady_state_k_per_h")
                add("pass" if max(dd) <= ss else "warn", "Steady-state criterion (<=1 K/h)", f"Last-4-hour change in oil rise: max {max(dd):.2f} K",
                    src=NAMES["temp"], found=f"{max(dd):.2f} K per hour over the last 4 hours", exp=f"{ss:g} K per hour or less", basis=("steady_state_k_per_h",),
                    fix=None if max(dd) <= ss else "The oil temperature had not settled; the test may have ended too early.")
        if temp_ok:
            with na('Reported vs computed oil rise', NAMES["temp"]):
                if abs(T["oil_rise_reported"] - rises[-1]) > .1: add("warn", "Reported vs computed oil rise", f"Logsheet reports {T['oil_rise_reported']} K, last-hour computed {rises[-1]:.2f} K",
                    src=NAMES["temp"], found=f"{T['oil_rise_reported']} K written on the log sheet", exp=f"{rises[-1]:.2f} K (top oil minus mean ambient, last hour)",
                    fix="Check which hour's readings the written figure was taken from. The report uses the computed value.")
        if wdg_ok:
            with na('Correction factor', NAMES["temp"]):
                if abs(T["corr_written"] - cf) > 1e-6: add("warn", "Correction factor", f"Written as {T['corr_written']} at top of page 2 but {cf} used in the formula - confirm",
                    src=NAMES["temp"], found=f"{T['corr_written']} written at the top of page 2", exp=f"{cf}, the value used in the winding-rise formula",
                    fix="Confirm the correct factor from the scan. It changes the winding temperature rise directly.")
        if temp_ok:
            with na('Injected loss = NLL + FLL', NAMES["temp"]):
                iok = abs(T["total"] - T["nll"] - T["fll"]) < .05
                add("pass" if iok else "warn", "Injected loss = NLL + FLL", f"{T['nll']} + {T['fll']} = {T['nll'] + T['fll']:.2f} W vs {T['total']} W",
                    src=NAMES["temp"], found=f"{T['total']} W injected", exp=f"No-load + full-load loss = {T['nll'] + T['fll']:.2f} W",
                    fix=None if iok else "The injected loss does not equal the sum of losses; check the figures on the log sheet.")
    # 8. pressure / vacuum / leakage
    Pr = d.get("pressure")
    if Pr:
        with na('Pressure and vacuum deflection', NAMES["pressure"]):
            for nm in ("pressure", "vacuum"):
                x = Pr["type"][nm]; m = max(abs(b - a) for a, b in x["pts"])
                dok = abs(m - x["max"]) < .01
                add("pass" if dok else "warn", f"{nm.title()} test deflection", f"Max permanent deflection {m:.2f} mm (logged {x['max']}); {x['obs']}",
                    src=NAMES["pressure"], found=f"{x['max']} mm logged as maximum", exp=f"{m:.2f} mm, the largest before/after difference",
                    fix=None if dok else "Re-check the deflection readings and the maximum written on the log.")
        with na('Oil leakage test', NAMES["pressure"]):
            lv = classify_observation(Pr["leak"]["obs"])
            add({True: "pass", False: "fail", None: "warn"}[lv], "Oil leakage test", f"{Pr['leak']['kpa']} kPa for {Pr['leak']['hrs']} h: {Pr['leak']['obs']}",
                src=NAMES["pressure"], found=Pr["leak"]["obs"], exp="No leakage at any point",
                fix=None if lv else "Leakage was recorded; the sample fails the oil leakage test." if lv is False
                    else "The recorded observation could not be interpreted; check it against the scan.")
    # 9. additional log sheets of other types: no known limits, so only completeness and identifiers
    work_ids = (ids.get("work") or [None, None]) if isinstance(ids, dict) else [None, None]
    ws_all = norm(str(work_ids[0] or (d.get("work") or {}).get("series") or ""))[-7:]
    wm_all = norm(str(work_ids[1] or (d.get("work") or {}).get("sample") or ""))[-4:]
    for o in (d.get("other") or {}).values():
        with na("Additional log sheet", "Additional log sheet"):
            t = str(o.get("title") or "Additional log sheet"); src = f"Additional log sheet: {t}"
            vals = [f.get("value") for f in o.get("fields") or []] + [c for tb in o.get("tables") or [] for r in tb.get("rows") or [] for c in r]
            empty = sum(v is None or (isinstance(v, str) and not v.strip()) for v in vals)
            add("warn" if empty or not vals else "pass", f"Additional record: {t}",
                f"{len(vals) - empty} of {len(vals)} values recorded" + (f"; {empty} NA" if empty else "") + ". No limits are known for this sheet, so values are reported as recorded.",
                src=src, found=f"{len(vals) - empty} values recorded, {empty} NA", exp="Every value on the sheet recorded",
                fix="Fill in the NA values on the sheet's page if they are on the scan, or leave them as NA." if empty else
                    ("Add the sheet's values, or remove it." if not vals else None))
            for f in o.get("fields") or []:
                lab, v = str(f.get("label") or "").lower(), str(f.get("value") or "")
                if not v.strip(): continue
                want, got = (ws_all, norm(v)[-7:]) if "series" in lab else (wm_all, norm(v)[-4:]) if "sample" in lab else (None, None)
                if want and got != want:
                    add("warn", "Identifier consistency", f"{t}: {f.get('label')} written as '{v}' but the job's is ...{want}. Verify handwriting (4/6/H).",
                        src=src, found=v, exp=f"...{want}", fix="Check the identifier on the scan and correct it on the sheet's page if it was misread.")
    return F, C

def safe_validate(d):
    """validate() for data that may be incomplete or mis-shaped (hand-edited spreadsheets): never raises.
    If one document's layout breaks the checks, it is named in a blocking finding and the other documents are still checked."""
    try:
        return validate(d)
    except Exception as e:  # noqa: BLE001 - any shape problem becomes a blocking finding the user can act on
        err = e
    culprits = []
    for k in [k for k in d if k != "request"]:
        try: validate({x: v for x, v in d.items() if x != k})
        except Exception: continue  # noqa: BLE001 - still failing without k, so k alone is not the cause
        culprits.append(k)
    what = lambda x: f"missing field {x}" if isinstance(x, KeyError) else f"{type(x).__name__}: {x}"
    if not culprits:
        return [dict(level="fail", check="Data structure", detail=f"Imported data is incomplete or not in the expected layout ({what(err)}). "
                     "Compare with a downloaded template, correct the file and import it again.")], {}
    try: F, C = validate({x: v for x, v in d.items() if x not in culprits})
    except Exception: F, C = [], {}  # noqa: BLE001
    F = [f for f in F if not (f["check"] == "Completeness of source documents")]
    for k in culprits:
        name = NAMES.get(k, "Identifiers on each sheet")
        F.insert(0, dict(level="fail", check=f"Data structure: {name}", source=name,
                         detail=f"The {name.lower()} is not in the expected layout ({what(err)}), so it could not be checked.",
                         found="Fields or table shape differ from the standard layout", expected="Same layout as the downloadable template",
                         action=f"Open the {name.lower()} (Edit under Sources) and correct it, re-import it from a corrected file, "
                                "or remove it from this job (Remove under Sources) if it should not be part of the report."))
    return F, C

class Soft(dict):
    """Header fields that may be absent on hand-entered requests print as NA instead of breaking the report."""
    def __missing__(self, k): return "NA"

# ------------------------------------------------------------------ report
def shown(v):
    """Copy of the data for printing: empty values (None or blank text) appear as NA."""
    if isinstance(v, dict): return {k: shown(x) for k, x in v.items()}
    if isinstance(v, list): return [shown(x) for x in v]
    return "NA" if v is None or (isinstance(v, str) and not v.strip()) else v

def fmt(v, spec=".1f"):
    """Number for the report, or NA when it could not be computed."""
    try: return format(v, spec)
    except (TypeError, ValueError): return "NA"

def build_pdf(j, version=None, verify_url=None):
    F, C = validate(j["data"]); d = shown(j["data"]); P, W, Rq = Soft(d.get("proforma", {})), Soft(d.get("work", {})), Soft(d.get("request", {}))
    Lim = Soft(P["limits"] if isinstance(P["limits"], dict) else {})
    has = lambda *ks: all(k in d for k in ks)
    missing = [v for k, v in NAMES.items() if k not in d]
    st = getSampleStyleSheet(); h = st["Heading3"]; n = st["BodyText"]; n.fontSize = 8.5
    cell = lambda s: Paragraph(str(s), ParagraphStyle_small)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
                            title=f"Test Report {j['series']}")
    def tbl(rows, widths=None, head=True):
        t = Table([[cell(c) for c in r] for r in rows], colWidths=widths, repeatRows=1 if head else 0)
        sty = [("GRID", (0, 0), (-1, -1), .4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if head: sty.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe7f1")))
        t.setStyle(TableStyle(sty)); return t
    kv = lambda pairs: tbl([[a, b] for a, b in pairs], [55 * mm, 125 * mm], head=False)
    verdict = lambda lv: {"pass": "PASS", "warn": "REVIEWED*" if j.get("approver") else "REVIEW*", "fail": "FAIL"}[lv]
    NOT = "NOT EVALUATED"
    def srow(name, needs, result, requirement, keys):
        """One summary line; tests whose documents were not provided are listed as not evaluated instead of failing."""
        if not has(*needs): return [name, "Data not provided (" + ", ".join(NAMES[k] for k in needs if k not in d) + ")", "-", NOT]
        try: got = result()
        except Exception: got = "NA"  # noqa: BLE001 - a summary cell must never break the report
        return [name, got, requirement(), res(*keys)]
    rank = {"pass": 0, "warn": 1, "fail": 2}
    def res(*keys):
        fs = [f for f in F if any(k in f["check"] for k in keys)]
        if fs and all(f.get("na") for f in fs): return NOT
        ls = [f["level"] for f in fs if not f.get("na")]
        return verdict(max(ls, key=rank.get)) if ls else "-"
    E = [Paragraph("CENTRAL POWER RESEARCH INSTITUTE, BENGALURU", st["Title"]),
         Paragraph("Short Circuit Laboratory - TEST REPORT", st["Heading2"]),
         kv([("Test report / series no.", j["series"]), ("Sample code no.", j["sample"]), ("Customer", f"{Rq['customer']}, {Rq['address']}"),
             ("Date(s) of test", f"{W['start']} to {W['completed']}"), ("Reference standard", W["standard"]),
             ("Tests performed", Rq["tests"] + (" (" + "; ".join(P["tests"]) + "), plus routine tests" if isinstance(P["tests"], list) else "")),
             ("Witness", Rq["witness"]), ("Report prepared by", W["engineer"] + " (Test Engineer)"),
             ("Decision rule", Rq["conformity"]),
             ("Report generated", now() + " by Aletheia" + (f" - version {version}" if version else ""))]),
         Paragraph("1. Description of test sample", h),
         kv([("Sample", Rq["sample"]), ("Rating", Rq["rating"]), ("Serial no.", Rq["serial"]), ("Drawing nos.", Rq["drawings"]),
             ("Voltage / phases / freq", f"{P['hv']} V / {P['lv']} V, {P['phases']} ph, {P['freq']} Hz, {P['vector']}, {P['cooling']}"),
             ("Taps", P["taps"]), ("Insulation levels", f"Um {P['hv_max_kv']} kV; {P['bil']}"), ("Impedance (75 C)", f"{P['z_pct']} %"),
             ("Guaranteed losses", f"{P['loss50']} W at 50% load; {P['loss100']} W at 100% load"), ("Oil volume / manufactured", f"{P['oil_l']} l / {P['mfg']}"),
             ("Construction", P["construction"])]),
         Paragraph("2. Summary of results", h),
         tbl([["Test", "Result obtained", "Requirement", "Verdict"],
              srow("Short-circuit withstand (dynamic + thermal)", ["sc"], lambda: "; ".join(f"{t}: {a} kA rms / {b} kA pk" for t, (a, b) in C.get("sc", {}).items()),
                   lambda: "Within +/-10% of required; no abnormality", ("SC", "Thermal", "Post-test", "Reactance")),
              srow("Temperature rise", ["temp", "proforma"], lambda: f"Top oil {fmt(C.get('oil_rise'))} K; HV wdg {fmt(C.get('hv_rise'))} K; LV wdg {fmt(C.get('lv_rise'))} K",
                   lambda: f"Oil {Lim['oil']} K; winding {Lim['wdg']} K", ("rise", "Steady")),
              srow("Total loss (75 C)", ["losses", "proforma"], lambda: f"{C.get('t100')} W (100%); {C.get('t50')} W (50%)",
                   lambda: f"{P['loss100']} W; {P['loss50']} W", ("Total loss",)),
              srow("Impedance", ["losses", "proforma"], lambda: "see detailed results", lambda: f"{P['z_pct']} % +/-10%", ("Impedance",)),
              srow("No-load current at 100% / 112.5%", ["noload", "proforma"], lambda: f"{d['noload']['rows'][0][4]} A / {d['noload']['rows'][2][4]} A",
                   lambda: "<=2% / <=5% of rated", ("No-load current",)),
              srow("Voltage ratio (all taps)", ["routine", "proforma"], lambda: f"max dev. {fmt(C.get('ratio_dev'), '.2f')}%", lambda: "+/-0.5%", ("Voltage ratio",)),
              srow("Dielectric routine tests", ["routine"], lambda: "; ".join(dict.fromkeys(str(d["routine"][k].get("obs", "-")) for k in ("induced", "hvac", "lvac"))),
                   lambda: "no disruptive discharge", ("Dielectric",)),
              srow("Pressure / vacuum / oil leakage", ["pressure"],
                   lambda: (lambda Pr0: f"Leakage: {Pr0['leak']['obs']}; deflection {Pr0['type']['pressure']['max']} mm (pressure), {Pr0['type']['vacuum']['max']} mm (vacuum)")(d["pressure"]),
                   lambda: "No leakage; deflection as logged", ("deflection", "leakage"))] +
             [[f"Additional record: {o.get('title', 'Additional log sheet')}", "Values recorded (see detailed results)", "No limits defined", "RECORDED"]
              for o in (d.get("other") or {}).values()],
             [48 * mm, 62 * mm, 45 * mm, 25 * mm])]
    E.append(Paragraph("3. Detailed results", h)); sub = iter(range(1, 20))
    def amb(x):
        try: return mean(x[3:6])
        except (TypeError, ValueError): return None
    def rise(x):
        try: return x[1] - amb(x)
        except TypeError: return None
    @contextmanager
    def part(name):
        """One detailed section; if its data is too incomplete to lay out, say so instead of failing the whole report."""
        try: yield
        except Exception:  # noqa: BLE001
            E.append(Paragraph(f"{name}: data incomplete (NA values); see the source document.", n))
    num = lambda title: Paragraph(f"3.{next(sub)} {title}", n)
    if has("resistance"):
        with part(NAMES['resistance']):
            R = d["resistance"]
            E += [num("Winding resistance (HV ohm / LV milli-ohm), before / after short circuit"),
                  tbl([["Tap/winding", "Before: R1, R2, R3", "After: R1, R2, R3"]] + [[f"HV tap {t}", ", ".join(map(str, r[0])), ", ".join(map(str, r[1]))] for t, r in R["hv"].items()] + [["LV", ", ".join(map(str, R["lv"][0])), ", ".join(map(str, R["lv"][1]))]])]
    if has("losses"):
        with part(NAMES['losses']):
            L = d["losses"]
            E += [num("Losses and impedance (reference temperature 75 C)"),
                  tbl([["Tap", "%Z", "%X", "%X chg", "Load loss W", "Stray W", "Total 100% W", "Total 50% W", "Isc rms/pk kA"]] +
                      [[r[0], r[1], r[2], r[3] if r[3] is not None else "-", r[6], r[10], r[13], r[12] or "-", f"{r[9]}/{r[8]}" if r[9] else "-"] for r in L["rows"]]),
                  Paragraph(f"No-load loss: {L['nll_bt']} W (before), {L['nll_at']} W (after).", n)]
    if has("noload"):
        with part(NAMES['noload']):
            E += [num("No-load current / loss"),
                  tbl([["Condition", "Avg V", "I1, I2, I3 (A)", "Avg I", "Watts", "f Hz"]] + [[r[0], r[2], ", ".join(map(str, r[3])), r[4], r[6], r[7]] for r in d["noload"]["rows"]])]
    if has("routine"):
        with part(NAMES['routine']):
            Rt = d["routine"]
            E += [num("Routine tests (before / after short circuit)"),
                  tbl([["Test", "Before", "After"]] + [[f"IR {k} (Gohm)", a, b] for k, (a, b) in Rt["ir"].items()] +
                      [["Induced over-voltage", f"{Rt['induced']['v']} V, {Rt['induced']['f']} Hz, {Rt['induced']['t']} s, {Rt['induced']['i'][0]} A", f"{Rt['induced']['i'][1]} A - {Rt['induced']['obs']}"],
                       ["HV / LV power-frequency", f"{Rt['hvac']['kv']} kV / {Rt['lvac']['kv']} kV for 60 s", Rt["hvac"]["obs"]],
                       ["Ambient / RH", f"{Rt['amb'][0]} C / {Rt['rh'][0]}%", f"{Rt['amb'][1]} C / {Rt['rh'][1]}%"]] +
                      [[f"Voltage ratio tap {i + 1}", ", ".join(map(str, a)), ", ".join(map(str, b))] for i, (a, b) in enumerate(zip(Rt["ratio"]["BT"], Rt["ratio"]["AT"]))])]
    if has("sc"):
        with part(NAMES['sc']):
            S = d["sc"]
            E += [num(f"Short-circuit test ({S['date']}; {S['condition']})"),
                  tbl([["Osc", "Tap", "Peak kA", "RMS U", "RMS V", "RMS W", "Avg", "Dur s", "Note"]] + [[s[0], s[1], s[3] or "-", s[4], s[5], s[6], s[7], s[8], s[9]] for s in S["shots"]]),
                  Paragraph(f"During / after test: {S['during']} / {S['after']}. Untanking: {S['inspection']}.", n)]
    if has("temp"):
        with part(NAMES['temp']):
            T = d["temp"]
            E += [num(f"Temperature rise ({T['dates']}; short-circuit method, {T['tap']} tap, {T['current']} A, injected {T['total']} W)"),
                  tbl([["Hour", "Top oil C", "Bottom oil C", "Mean ambient C", "Oil rise K"]] + [[x[0], x[1], x[2], fmt(amb(x), ".2f"), fmt(rise(x), ".2f")] for x in T["hours"]])]
            if "hv_rise" in C:
                E.append(Paragraph(f"Winding rise = (R2/R1)(235+{T['amb_cold']}) - 235 - {T['amb_sd']} + {T['corr']}: HV {C['hv_rise']:.1f} K, LV {C['lv_rise']:.1f} K.", n))
    if has("pressure"):
        with part(NAMES['pressure']):
            Pr = d["pressure"]; ty = Pr["type"]
            E += [num("Pressure, vacuum and oil-leakage tests"),
                  tbl([["Test", "Condition", "Result"], ["Routine pressure", f"{Pr['routine']['kpa']} kPa, {Pr['routine']['min']} min ({Pr['routine']['date']})", Pr["routine"]["obs"]],
                       ["Type pressure", f"{ty['pressure']['kpa']} kPa, {ty['pressure']['min']} min", f"Max deflection {ty['pressure']['max']} mm - {ty['pressure']['obs']}"],
                       ["Vacuum", f"{ty['vacuum']['mmhg']} mmHg, {ty['vacuum']['min']} min", f"Max deflection {ty['vacuum']['max']} mm - {ty['vacuum']['obs']}"],
                       ["Oil leakage", f"{Pr['leak']['kpa']} kPa (2 x {Pr['leak']['head_kpa']} kPa head), {Pr['leak']['hrs']} h ({Pr['leak']['date']})", Pr["leak"]["obs"]]])]
    for o in (d.get("other") or {}).values():  # additional log sheets of types without known limits: reported as recorded
        with part("Additional log sheet"):
            E.append(num(f"Additional test record: {o.get('title', 'Additional log sheet')} (recorded values; no limits evaluated)"))
            if o.get("fields"): E.append(kv([(f.get("label") or "-", f.get("value")) for f in o["fields"]]))
            for t in o.get("tables") or []:
                if t.get("title"): E.append(Paragraph(t["title"], n))
                E.append(tbl([t.get("columns") or [""] * len(t["rows"][0])] + t.get("rows", [])))
    if missing:
        E.append(Paragraph("Source documents not provided (the related tests were not evaluated): " + ", ".join(missing) + ".", n))
    fails = [f for f in F if f["level"] == "fail"]; warns = [f for f in F if f["level"] == "warn"]
    E += [Paragraph("4. Statement of conformity", h),
          Paragraph(f"Decision rule requested by the customer: {Rq['conformity']}. <b>" +
                    ("The sample does NOT comply: " + "; ".join(f["check"] for f in fails) if fails else
                     f"The sample complied with all {sum(f['level'] == 'pass' for f in F)} automatically evaluated requirements ({W['standard']})"
                     + (f". This statement covers only the tests whose data was provided; not evaluated: {', '.join(missing)}." if missing else ".")) + "</b>", n)]
    if warns:
        E += [Paragraph("* Items flagged by automated validation and accepted by the reviewer at approval:" if j.get("approver") else
                        "* Items flagged by automated validation - to be confirmed by the reviewer before approval:", n), tbl([["Check", "Detail"]] + [[f["check"], f["detail"]] for f in warns])]
    E += [Spacer(1, 14), tbl([["Test Engineer: " + W["engineer"], f"Approved by: {signed(j['approver'], j.get('approver_id')) or '(pending)'}"]], head=False),
          Paragraph("This report applies only to the sample tested and shall not be reproduced except in full. Auto-generated by Aletheia from digitised log sheets.", n)]
    if verify_url:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        w = QrCodeWidget(verify_url); b = w.getBounds(); size = 26 * mm
        q = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0]); q.add(w)
        t = Table([[q, Paragraph(f"<b>Verify this report (version {version})</b><br/>Scan the code or open {verify_url}<br/>"
                                 "The page shows the SHA-256 fingerprint of this exact PDF and whether it is the current, approved version.", n)]],
                  colWidths=[30 * mm, 150 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])); E += [Spacer(1, 8), t]
    doc.build(E); buf.seek(0); return buf

from reportlab.lib.styles import ParagraphStyle
ParagraphStyle_small = ParagraphStyle("c", fontSize=7.5, leading=9)

# --------------------------------------------------------------------- API
SERIES_RE, SAMPLE_RE = r"CPRIBLRSCL\d{2}T\d{4}", r"HVD\d{2}S\d{4}"
EMP_RE = r"[A-Z0-9][A-Z0-9/-]{1,19}"  # the lab's employee ID format is not known, so only its shape is checked
def signed(name, emp): return f"{name} (Employee ID {emp})" if name and emp else name  # reports approved before IDs were recorded show the name only
REQ_KEYS = ("customer", "address", "serial", "tests", "criteria", "witness", "conformity", "rating")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

@app.errorhandler(importers.ImportError_)
@app.errorhandler(vision.VisionError)
def bad_file(e): return jsonify(error=[str(e)]), 400

@app.errorhandler(413)
def too_big(e): return jsonify(error=["File is too large (20 MB maximum)"]), 413

def body(): return request.get_json(force=True, silent=True) or {}

def upload(b):
    """Uploaded files arrive as base64 inside JSON: {filename, b64}."""
    try: raw = base64.b64decode(b.get("b64") or "", validate=True)
    except ValueError: raise importers.ImportError_("Upload was not readable") from None
    if not raw: raise importers.ImportError_("The file is empty")
    return str(b.get("filename") or "upload")[:200], raw

def check_ids(b):
    """Only the series number is required (it identifies the record). Other fields may be left empty and are stored as NA;
    a sample code that is given must still have the CPRI format."""
    err = []
    if not str(b.get("series") or "").strip(): err.append("Test series number is required (it identifies the record)")
    elif not re.fullmatch(SERIES_RE, str(b["series"]).strip()): err.append("Series must look like CPRIBLRSCL25T1654")
    sample = str(b.get("sample") or "").strip()
    if sample and sample.upper() != "NA" and not re.fullmatch(SAMPLE_RE, sample): err.append("Sample code must look like HVD25S0847, or be left empty")
    if not err:
        b["series"] = str(b["series"]).strip()
        for f in ("sample", "customer", "rating"): b[f] = str(b.get(f) or "").strip() or "NA"
    return err

def data_changed(j, d, event):
    """Any change to test data sends the job back to 'Data Imported': checks and the report must be redone."""
    stale = j["stage"] >= 3
    # record details left as NA are filled from the imported documents (request form, work instruction)
    rq, wk = d.get("request") or {}, d.get("work") or {}
    found = dict(customer=rq.get("customer") or wk.get("customer"), rating=rq.get("rating"), sample=wk.get("sample"))
    fill = {k: str(v).strip() for k, v in found.items() if j.get(k) in (None, "", "NA") and v and str(v).strip()
            and (k != "sample" or re.fullmatch(SAMPLE_RE, str(v).strip()))}
    save(j["id"], data=d, stage=max(min(j["stage"], 1), 1), findings=[], approver=None, approver_id=None, **fill)
    with db() as c: log(c, j["id"], event + (" - earlier report is now out of date" if stale else ""))

def freeze(j):
    """Build the PDF once and store it: every generated/approved report is an immutable, hash-verifiable version."""
    with db() as c: v = (c.execute("SELECT MAX(version) FROM reports WHERE job_id=?", (j["id"],)).fetchone()[0] or 0) + 1
    token = secrets.token_urlsafe(12)
    pdf = build_pdf(j, v, request.host_url + "verify/" + token).getvalue()
    sha = hashlib.sha256(pdf).hexdigest()
    with db() as c: c.execute("INSERT INTO reports(job_id,version,token,sha256,pdf,approver,approver_id,at) VALUES(?,?,?,?,?,?,?,?)",
                         (j["id"], v, token, sha, pdf, j.get("approver"), j.get("approver_id"), now()))
    return v, sha

@app.get("/")
def index(): return send_from_directory(app.static_folder, "index.html")

@app.get("/api/jobs")
def jobs():
    q, s = f"%{request.args.get('q', '')}%", request.args.get("stage", "")
    sql = "SELECT id FROM jobs WHERE (series LIKE ? OR sample LIKE ? OR customer LIKE ? OR rating LIKE ?)" + (" AND stage=?" if s != "" else "") + " ORDER BY updated DESC, id DESC"
    with db() as c: ids = [r[0] for r in c.execute(sql, (q, q, q, q) + ((int(s),) if s != "" else ()))]
    out = []
    for i in ids:
        j = getjob(i, False); j["sections"] = list(j.pop("data").keys()); out.append(j)
    return jsonify(out)

def insert_job(c, b, event):
    rq = {**(b.get("request") or {})}
    cur = c.execute("INSERT INTO jobs(series,sample,customer,rating,data,created,updated) VALUES(?,?,?,?,?,?,?)",
                    (b["series"], b["sample"], b["customer"].strip(), b["rating"].strip(), json.dumps({"request": rq}), now(), now()))
    log(c, cur.lastrowid, event); return cur.lastrowid

@app.post("/api/jobs")
def create():
    b = body(); err = check_ids(b)
    if err: return jsonify(error=err), 400
    try:
        with db() as c: return jsonify(id=insert_job(c, b, "Customer request captured")), 201
    except sqlite3.IntegrityError: return jsonify(error=["Series number already exists"]), 409

@app.post("/api/jobs/from-file")
def create_from_file():
    """New request from a data file: the series number and request details come from the file (or the form, if typed)."""
    b = body(); name, raw = upload(b)
    typed = str(b.get("series") or "").strip().upper() or None
    content, kind, notes = importers.load_test_data(name, raw, typed)
    if not isinstance(content, dict) or not content: return jsonify(error=["No test data found in this file"]), 400
    rq, wk = content.get("request") or {}, content.get("work") or {}
    ids = (content.get("ids") or {}).get("work") or [None, None]
    series = typed or str(wk.get("series") or ids[0] or "").strip().upper()
    new = dict(series=series, sample=str(wk.get("sample") or ids[1] or "").strip().upper(), customer=rq.get("customer") or wk.get("customer"),
               rating=rq.get("rating"), request={k: rq[k] for k in REQ_KEYS if rq.get(k)})
    if not series: return jsonify(error=["This file has no test series number. Type it in the form, then drop the file again."]), 400
    if new["sample"] and not re.fullmatch(SAMPLE_RE, new["sample"]): new["sample"] = ""  # a misread sample code must not block the job
    err = check_ids(new)
    if err: return jsonify(error=err + ["Type the correct test series number in the form and drop the file again."]), 400
    try:
        with db() as c: i = insert_job(c, new, f"Customer request created from {name}")
    except sqlite3.IntegrityError: return jsonify(error=[f"Series {series} already exists. Open that job, or type a different series number."]), 409
    r = apply_import(getjob(i), i, name, content, kind, notes)
    if isinstance(r, tuple): return jsonify(id=i, warning=r[0].get_json().get("error")), 201  # job exists; import problem shown on its page
    return jsonify(id=i, **r.get_json()), 201

@app.post("/api/read-scan")
def read_scan():
    """AI reading of a customer request form or work instruction before the job exists (pre-fills the New request form)."""
    b = body(); k = b.get("section") if b.get("section") in ("request", "work") else "request"
    name, raw = upload(b)
    if len(raw) > importers.MAX_BYTES: raise importers.ImportError_("File is too large (20 MB maximum)")
    with db() as c:
        out = vision.extract(c, raw, sniff(raw), k, NAMES[k], load_demo().get(k, {}), app.config.get("VISION_TRANSPORT"),
                             sha=hashlib.sha256(raw).hexdigest(), cache_path=AI_CACHE, fresh=bool(b.get("fresh")))
    return jsonify(out)

@app.get("/api/jobs/<int:i>")
def one(i): return jsonify(getjob(i))

# ---- data collection: JSON, CSV, Excel, SQLite database
@app.post("/api/jobs/<int:i>/import")
def imp(i):
    j = getjob(i); b = body(); notes = []
    if isinstance(b.get("content"), dict): name, content, kind = str(b.get("filename") or "upload"), b["content"], "json"
    else:
        name, raw = upload(b); content, kind, notes = importers.load_test_data(name, raw, j["series"])
    return apply_import(j, i, name, content, kind, notes)

def apply_import(j, i, name, content, kind, notes):
    """Merge imported sections into a job (also used when a job is created from a file)."""
    ok = set(NAMES) | {"ids", "other"}
    if not isinstance(content, dict) or not content or not set(content) <= ok:
        return jsonify(error=["Unrecognised file: expected sections " + ", ".join(NAMES)]), 400
    bad = [k for k, v in content.items() if not isinstance(v, dict)]
    if bad: return jsonify(error=[f"Section '{k}' must contain named fields" for k in bad]), 400
    sha = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    try:
        with db() as c: c.execute("INSERT INTO imports(job_id,source,kind,sha256,at) VALUES(?,?,?,?,?)", (i, name, kind, sha, now()))
    except sqlite3.IntegrityError: return jsonify(error=["Duplicate file - identical content already imported for this job"]), 409
    if isinstance(content.get("other"), dict):  # additional log sheets: cleaned, added alongside any already on the job
        content["other"] = {str(k): clean_other(v) for k, v in content["other"].items() if isinstance(v, dict)}
    d = j["data"]
    for k, v in content.items(): d[k] = {**d.get(k, {}), **v} if k in ("ids", "request", "other") else v
    label = {"json": "JSON", "csv": "CSV", "xlsx": "Excel", "sqlite": "database"}[kind]
    data_changed(j, d, f"Imported {label} file {name} ({', '.join(content)})" + (f" [{'; '.join(notes)}]" if notes else ""))
    return jsonify(ok=True, kind=kind, sections=list(content), notes=notes)

@app.post("/api/jobs/<int:i>/section")
def section(i):
    """Save one section typed or corrected by hand (also used to accept an AI reading after review)."""
    j = getjob(i); b = body(); k = b.get("section")
    if k == "other": return save_other(j, b)
    if k not in set(NAMES) | {"ids"} or not isinstance(b.get("data"), dict): return jsonify(error=["Choose a section and provide its fields"]), 400
    d = j["data"]; d[k] = b["data"]
    data_changed(j, d, f"{NAMES.get(k, 'Identifiers')} {'entered from AI reading of ' + str(b['source'])[:120] + ' after review' if b.get('source') else 'edited by hand'}")
    return jsonify(ok=True)

def clean_other(o):
    """An additional log sheet: title, labelled fields and tables, whatever their shape when they arrive."""
    txt = lambda v: "" if v is None else str(v).strip()
    val = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else (txt(v) or None)
    fields = [dict(label=txt(f.get("label")), value=val(f.get("value"))) for f in o.get("fields") or [] if isinstance(f, dict)]
    fields = [f for f in fields if f["label"] or f["value"] is not None]
    tables = []
    for t in o.get("tables") or []:
        if not isinstance(t, dict): continue
        cols = [txt(c) for c in t.get("columns") or []]
        rows = [[val(c) for c in r] for r in t.get("rows") or [] if isinstance(r, list)]
        rows = [r for r in rows if any(c is not None for c in r)]
        width = max([len(cols)] + [len(r) for r in rows] or [0])
        if not width: continue
        cols += [""] * (width - len(cols)); rows = [r + [None] * (width - len(r)) for r in rows]
        tables.append(dict(title=txt(t.get("title")), columns=cols, rows=rows))
    return dict(title=txt(o.get("title")) or "Additional log sheet", fields=fields, tables=tables)

def save_other(j, b):
    if not isinstance(b.get("data"), dict): return jsonify(error=["Provide the sheet's fields"]), 400
    d = j["data"]; others = d.setdefault("other", {})
    key = str(b.get("key") or "")
    if not re.fullmatch(r"x\d{1,4}", key):
        n = 1
        while f"x{n}" in others: n += 1
        key = f"x{n}"
    sheet = clean_other(b["data"]); others[key] = sheet
    data_changed(j, d, f"Additional log sheet '{sheet['title']}' " + (f"entered from AI reading of {str(b['source'])[:120]} after review" if b.get("source") else "edited by hand"))
    return jsonify(ok=True, key=key)

@app.delete("/api/jobs/<int:i>/section/<k>")
def remove_section(i, k):
    """Detach one document's data from the job; the checks and the report must be redone. The customer request stays."""
    if k.startswith("other:"):
        j = getjob(i); d = j["data"]; key = k[6:]
        if key not in (d.get("other") or {}): return jsonify(error=["This log sheet is not part of the job"]), 404
        title = d["other"].pop(key).get("title", "Additional log sheet")
        if not d["other"]: del d["other"]
        data_changed(j, d, f"Additional log sheet '{title}' removed from the job"); return jsonify(ok=True)
    if k not in set(NAMES) - {"request"} | {"ids"}: return jsonify(error=["This document cannot be removed"]), 400
    j = getjob(i); d = j["data"]
    if k not in d: return jsonify(error=["This document is not part of the job"]), 404
    del d[k]
    data_changed(j, d, f"{NAMES.get(k, 'Identifiers on each sheet')} removed from the job")
    return jsonify(ok=True)

@app.get("/api/jobs/<int:i>/export/<fmt>")
def export(i, fmt):
    j = getjob(i, False); return send_export(j["data"], fmt, j["series"])

@app.get("/api/template/<fmt>")
def template(fmt): return send_export(load_demo(), fmt, "ALETHEIA_template", series="CPRIBLRSCL25T1654")

def send_export(d, fmt, name, series=None):
    series = series or name
    made = {"csv": lambda: (importers.export_csv(d), "text/csv"), "xlsx": lambda: (importers.export_xlsx(d), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "sqlite": lambda: (importers.export_sqlite(d, series), "application/vnd.sqlite3"), "json": lambda: (json.dumps(d, indent=1).encode(), "application/json")}.get(fmt)
    if not made: abort(404)
    raw, mime = made()
    return send_file(io.BytesIO(raw), mimetype=mime, as_attachment=True, download_name=f"{name}.{'db' if fmt == 'sqlite' else fmt}")

# ---- existing registers: bulk-create historical records from a spreadsheet, CSV or database
@app.post("/api/import-register")
def register():
    name, raw = upload(body()); recs, table = importers.load_register(name, raw); made, skipped = [], []
    for n, r in enumerate(recs, 1):
        r["series"], r["sample"] = r["series"].upper(), r["sample"].upper()
        err = check_ids(r)
        if err: skipped.append(dict(row=n, series=r["series"], reason="; ".join(err))); continue
        r["request"] = {k: r[k] for k in REQ_KEYS if r.get(k)}
        try:
            with db() as c: made.append(insert_job(c, r, f"Record imported from existing register {name}"))
        except sqlite3.IntegrityError: skipped.append(dict(row=n, series=r["series"], reason="Series number already exists"))
    return jsonify(created=len(made), ids=made, skipped=skipped, table=table, rows=len(recs))

@app.get("/api/register-template.csv")
def register_template():
    rows = "series,sample,customer,rating,address,serial,tests,standard,witness,conformity\nCPRIBLRSCL25T1601,HVD25S0801,Example Transformers Pvt Ltd,100 kVA / 11 kV / 433 V,\"Plot 1, Industrial Area, Bengaluru\",2201,Type test,IS 1180,,\n"
    return send_file(io.BytesIO(rows.encode("utf-8-sig")), mimetype="text/csv", as_attachment=True, download_name="ALETHEIA_register_template.csv")

# ---- source documents (scans / photographs kept as evidence) and optional AI reading
def sniff(raw):
    if raw.startswith(b"%PDF-"): return "application/pdf"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if raw.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP": return "image/webp"
    raise importers.ImportError_("Source documents must be PDF, PNG, JPEG or WebP")

@app.post("/api/jobs/<int:i>/sources")
def add_source(i):
    getjob(i, False); name, raw = upload(body())
    if len(raw) > importers.MAX_BYTES: raise importers.ImportError_("File is too large (20 MB maximum)")
    try:
        with db() as c: return jsonify(id=insert_source(c, i, name, raw)), 201
    except sqlite3.IntegrityError: return jsonify(error=["This document is already attached to the job"]), 409

def insert_source(c, i, name, raw):
    """Store a scanned sheet with its fingerprint. Raises IntegrityError if the same file is already attached to the job."""
    mime = sniff(raw); sha = hashlib.sha256(raw).hexdigest()
    cur = c.execute("INSERT INTO sources(job_id,filename,mime,sha256,content,at) VALUES(?,?,?,?,?,?)", (i, name, mime, sha, raw, now()))
    log(c, i, f"Source document attached: {name} (SHA-256 {sha[:12]}...)"); return cur.lastrowid

def source_row(sid):
    with db() as c: r = c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    if not r: abort(404)
    return r

@app.get("/api/sources/<int:sid>")
def get_source(sid):
    r = source_row(sid); resp = send_file(io.BytesIO(r["content"]), mimetype=r["mime"], download_name=r["filename"])
    resp.headers["X-Content-Type-Options"] = "nosniff"; return resp

@app.delete("/api/sources/<int:sid>")
def del_source(sid):
    r = source_row(sid)
    with db() as c: c.execute("DELETE FROM sources WHERE id=?", (sid,)); log(c, r["job_id"], f"Source document removed: {r['filename']}")
    return jsonify(ok=True)

@app.post("/api/sources/<int:sid>/extract")
def extract(sid):
    """Ask Gemini for a proposal for one section. Nothing is saved until the engineer reviews it and posts it to /section."""
    r = source_row(sid); b = body(); k = b.get("section")
    if k not in NAMES and k != "other": return jsonify(error=["Choose which document this is"]), 400
    example = vision.OTHER_LAYOUT if k == "other" else load_demo().get(k, {})
    with db() as c:
        out = vision.extract(c, r["content"], r["mime"], k, NAMES.get(k, "Other laboratory log sheet"), example, app.config.get("VISION_TRANSPORT"),
                             sha=r["sha256"], cache_path=AI_CACHE, fresh=bool(b.get("fresh")),
                             part=b.get("part") if isinstance(b.get("part"), int) else None)
        log(c, r["job_id"], f"AI reading {'reused from cache' if out['cached'] else 'requested'} for {r['filename']} as {NAMES.get(k, 'other log sheet')} (proposal only, not saved)")
    return jsonify(out)

# ---- validate, generate, approve
@app.post("/api/jobs/<int:i>/validate")
def val(i):
    j = getjob(i); F, _ = safe_validate(j["data"]); fails = sum(f["level"] == "fail" for f in F)
    done = {(f["check"], f["detail"]) for f in j["findings"] if f.get("reviewed")}  # unchanged items keep their review
    for f in F:
        if f["level"] == "warn" and (f["check"], f["detail"]) in done: f["reviewed"] = True
    save(i, findings=F, stage=max(j["stage"], 2) if not fails else min(j["stage"], 1))
    with db() as c: log(c, i, f"Validation run: {sum(f['level'] == 'pass' for f in F)} pass, {sum(f['level'] == 'warn' for f in F)} warn, {fails} fail")
    return jsonify(findings=F)

@app.post("/api/jobs/<int:i>/review")
def review(i):
    """Mark one flagged check as reviewed by the engineer (failed checks cannot be: they must be fixed)."""
    j = getjob(i); b = body(); F = j["findings"]; n = b.get("index")
    if not isinstance(n, int) or not 0 <= n < len(F): return jsonify(error=["No such check"]), 400
    if F[n]["level"] == "fail": return jsonify(error=["A failed check cannot be marked as reviewed: correct the data and run the checks again"]), 409
    if F[n]["level"] != "warn": return jsonify(error=["Only flagged items need review"]), 400
    F[n]["reviewed"] = bool(b.get("reviewed", True)); save(i, findings=F)
    with db() as c: log(c, i, f"{'Reviewed' if F[n]['reviewed'] else 'Review withdrawn'}: {F[n]['check']} - {F[n]['detail'][:90]}")
    return jsonify(findings=F)

@app.post("/api/jobs/<int:i>/generate")
def gen(i):
    j = getjob(i)
    if j["stage"] < 2: return jsonify(error=["Validate data (no failures) before generating"]), 409
    left = [f["check"] for f in j["findings"] if f["level"] == "warn" and not f.get("reviewed")]
    if left: return jsonify(error=[f"Review every flagged item before the report is built ({len(left)} left)"]), 409
    t = dt.datetime.now()
    try: v, sha = freeze(j)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=[f"The report could not be built from this data ({type(e).__name__}: {e}). Correct the data and run the checks again."]), 400
    ms = int((dt.datetime.now() - t).total_seconds() * 1000)
    save(i, stage=max(j["stage"], 3))
    with db() as c: log(c, i, f"Report generated in {ms} ms (version {v}, SHA-256 {sha[:12]}...)")
    return jsonify(ms=ms, version=v, sha256=sha)

@app.post("/api/jobs/<int:i>/approve")
def approve(i):
    """The approver's name and employee ID are both required; both are printed on the report and kept with each version."""
    j = getjob(i); b = body(); name, emp = str(b.get("name") or "").strip(), str(b.get("employee_id") or "").strip().upper()
    if j["stage"] < 3: return jsonify(error=["Generate the report before approving it"]), 409
    err = ([] if name else ["Enter the approver's name"]) + (
        ["Enter the approver's employee ID"] if not emp else [] if re.fullmatch(EMP_RE, emp) else ["Employee ID must be 2-20 letters, digits, '-' or '/'"])
    if err: return jsonify(error=err), 400
    save(i, stage=4, approver=name, approver_id=emp); v, sha = freeze(getjob(i))
    with db() as c: log(c, i, f"Approved by {signed(name, emp)}; released for export (version {v}, SHA-256 {sha[:12]}...)")
    return jsonify(ok=True, version=v)

def latest(i):
    with db() as c: return c.execute("SELECT * FROM reports WHERE job_id=? ORDER BY version DESC LIMIT 1", (i,)).fetchone()

@app.get("/api/jobs/<int:i>/report.pdf")
def pdf(i):
    j = getjob(i, False); r = latest(i) if j["stage"] >= 3 else None
    if not r: return jsonify(error=["Report not generated yet"]), 409
    return send_file(io.BytesIO(r["pdf"]), mimetype="application/pdf", as_attachment=request.args.get("dl") == "1", download_name=f"TestReport_{j['series']}_v{r['version']}.pdf")

@app.get("/api/verify/<token>")
def verify(token):
    with db() as c:
        r = c.execute("SELECT * FROM reports WHERE token=?", (token,)).fetchone()
        if not r: return jsonify(error=["Unknown report code"]), 404
        j = c.execute("SELECT series,sample,customer,stage FROM jobs WHERE id=?", (r["job_id"],)).fetchone()
        newest = c.execute("SELECT MAX(version) FROM reports WHERE job_id=?", (r["job_id"],)).fetchone()[0]
    intact = hashlib.sha256(r["pdf"]).hexdigest() == r["sha256"]; current = r["version"] == newest and j["stage"] >= 3
    return jsonify(series=j["series"], sample=j["sample"], customer=j["customer"], version=r["version"], sha256=r["sha256"], generated=r["at"],
                   approver=r["approver"], approver_id=r["approver_id"], intact=intact, current=current, approved=bool(r["approver"]) and current and j["stage"] == 4)

@app.get("/verify/<token>")
def verify_page(token): return send_from_directory(app.static_folder, "index.html")

@app.post("/api/jobs/<int:i>/edit")
def edit(i):
    """Edit record details. A generated report is rebuilt as a new version; an approved one goes back for re-approval."""
    j = getjob(i); b = body(); err = check_ids(b)
    if err: return jsonify(error=err), 400
    d = j["data"]; rq = d.setdefault("request", {})
    for k in REQ_KEYS:
        if k in b: rq[k] = str(b[k]).strip()
    try:
        save(i, series=b["series"], sample=b["sample"], customer=b["customer"].strip(), rating=b["rating"].strip(), data=d,
             stage=3 if j["stage"] == 4 else j["stage"], approver=None if j["stage"] == 4 else j["approver"],
             approver_id=None if j["stage"] == 4 else j.get("approver_id"))
    except sqlite3.IntegrityError: return jsonify(error=["Series number already exists"]), 409
    note = ""
    if j["stage"] >= 3:
        try: note = f" - report rebuilt as version {freeze(getjob(i))[0]}" + (", re-approval needed" if j["stage"] == 4 else "")
        except Exception: save(i, stage=1, findings=[]); note = " - report withdrawn, run the checks again"  # noqa: BLE001
    with db() as c: log(c, i, "Record details edited" + note)
    return jsonify(ok=True)

@app.post("/api/jobs/<int:i>/discard")
def discard(i):
    """Withdraw the generated report; record and imported data are kept (stage returns to 'Validated'). Stored versions stay verifiable as superseded."""
    j = getjob(i)
    if j["stage"] < 3: return jsonify(error=["No generated report to delete"]), 409
    save(i, stage=2, approver=None, approver_id=None)
    with db() as c: log(c, i, "Generated report withdrawn (record kept)")
    return jsonify(ok=True)

@app.delete("/api/jobs/<int:i>")
def delete(i):
    """Delete the whole record: job, imports, source documents, report versions and history."""
    getjob(i, False)
    with db() as c:
        for t in ("imports", "audit", "sources", "reports"): c.execute(f"DELETE FROM {t} WHERE job_id=?", (i,))
        c.execute("DELETE FROM jobs WHERE id=?", (i,))
    return jsonify(ok=True)

@app.get("/api/stats")
def stats():
    with db() as c:
        by = [0] * 5
        for r in c.execute("SELECT stage,COUNT(*) n FROM jobs GROUP BY stage"): by[r[0]] = r[1]
        ms = [int(m.group(1)) for r in c.execute("SELECT event FROM audit WHERE event LIKE 'Report generated in%'") if (m := re.search(r"in (\d+) ms", r[0]))]
        kinds = {r[0] or "json": r[1] for r in c.execute("SELECT kind,COUNT(*) FROM imports GROUP BY kind")}
        ai = vision.status(c)
    return jsonify(total=sum(by), by_stage=by, stages=STAGES, avg_gen_ms=int(mean(ms)) if ms else None, imports=kinds,
                   ai={k: ai[k] for k in ("configured", "model", "provider", "kind", "calls_today", "daily_limit")}, sections=NAMES)

@app.post("/api/demo")
def demo():
    """Load the demo job with its scanned sheets. If it is already loaded, attach any scans it is missing and return it."""
    data = load_demo(); w = data["work"]
    with db() as c: old = c.execute("SELECT id FROM jobs WHERE series=?", (w["series"],)).fetchone()
    if old: i = old[0]
    else:
        r = app.test_client()
        i = r.post("/api/jobs", json=dict(series=w["series"], sample=w["sample"], customer=data["request"]["customer"], rating=data["request"]["rating"], request=data["request"])).get_json()["id"]
        r.post(f"/api/jobs/{i}/import", json=dict(filename=os.path.basename(DEMO), content={k: v for k, v in data.items() if k != "request"}))
    added = attach_demo_scans(i)
    return jsonify(id=i, existing=bool(old), scans_added=added), 200 if old else 201

def attach_demo_scans(i):
    """The form page matches each section to its scan by file name (e.g. 'Logsheet for temp. rise' -> temperature rise)."""
    names = sorted(f for f in os.listdir(DEMO_SCANS) if os.path.splitext(f)[1].lower() in (".pdf", ".png", ".jpg", ".jpeg", ".webp")) if os.path.isdir(DEMO_SCANS) else []
    with db() as c:
        have = {r[0] for r in c.execute("SELECT sha256 FROM sources WHERE job_id=?", (i,))}
        n = 0
        for f in names:
            with open(os.path.join(DEMO_SCANS, f), "rb") as fh: raw = fh.read()
            if hashlib.sha256(raw).hexdigest() not in have: insert_source(c, i, f, raw); n += 1
    return n

init()
if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5000)))
