"""Aletheia - Automated Test Report Generation System (CPRI Short Circuit Laboratory).
Run:  pip install -r requirements.txt && python app.py   ->  http://localhost:5000
Modules: Data Collection (importers.py: JSON / CSV / Excel / SQLite; vision.py: optional scan reading) | Database (SQLite)
         | Validation | Report Engine (PDF, frozen versions + QR verification) | Dashboard (static/index.html)
"""
import base64, json, hashlib, io, math, os, re, secrets, sqlite3, datetime as dt
import importers, vision
from statistics import mean
from flask import Flask, request, jsonify, send_file, send_from_directory, abort
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ALETHEIA_DB") or os.path.join(HERE, "aletheia.db")
DEMO = os.path.join(HERE, "sample_data", "AP_Transformers_25T1654.json")

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
            stage INTEGER DEFAULT 0, data TEXT DEFAULT '{}', findings TEXT DEFAULT '[]', approver TEXT, created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, job_id INT, source TEXT, kind TEXT, sha256 TEXT, at TEXT, UNIQUE(job_id, sha256));
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, job_id INT, filename TEXT, mime TEXT, sha256 TEXT, content BLOB, at TEXT, UNIQUE(job_id, sha256));
        CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, job_id INT, version INT, token TEXT UNIQUE, sha256 TEXT, pdf BLOB, approver TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS vision_calls(id INTEGER PRIMARY KEY, day TEXT, model TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, job_id INT, event TEXT, at TEXT);""")

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
            j["reports"] = [dict(a) for a in c.execute("SELECT version,token,sha256,approver,at FROM reports WHERE job_id=? ORDER BY version DESC", (jid,))]
        return j

def save(jid, **kw):
    kw["updated"] = now()
    with db() as c:
        c.execute(f"UPDATE jobs SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*[json.dumps(v) if isinstance(v, (dict, list)) else v for v in kw.values()], jid))

# --------------------------------------------------------------- validation
def validate(d):
    """Returns (findings, calc). Levels: pass / warn (needs reviewer attention) / fail (blocks)."""
    F, C = [], {}
    add = lambda l, c, t: F.append(dict(level=l, check=c, detail=t))
    miss = [v for k, v in NAMES.items() if k not in d]
    add("fail" if miss else "pass", "Completeness vs tests required in proforma",
        "Missing: " + ", ".join(miss) if miss else "All 10 source documents imported")
    # 1. identifiers must agree across documents (handwriting: 4 can read as H or 6)
    norm = lambda s: s.upper().replace("H", "4")
    ids = d.get("ids", {})
    if "work" in ids:
        ws, wm = norm(ids["work"][0])[-7:], norm(ids["work"][1])[-4:]
        bad = [(k, s, m) for k, (s, m) in ids.items() if norm(s)[-7:] != ws or norm(m)[-4:] != wm]
        for k, s, m in bad:
            add("warn", "Identifier consistency", f"{NAMES.get(k, k)}: transcribed '{s}' / '{m}' but work instruction = {ws} / {wm}. Verify handwriting (4/6/H).")
        if not bad: add("pass", "Identifier consistency", f"Series {ws} / sample {wm} agree in all documents")
    P = d.get("proforma", {})
    if P:
        irat = P["kva"] * 1000 / (math.sqrt(3) * P["lv"]); C["irat"] = irat
    # 2. resistance
    R = d.get("resistance")
    if R:
        worst = 0
        for ph in list(R["hv"].values()) + [R["lv"]]:
            for row in ph: worst = max(worst, (max(row) - min(row)) / mean(row) * 100)
        add("pass" if worst <= 2 else "fail", "Winding resistance phase imbalance", f"Max imbalance {worst:.2f}% (limit 2%)")
        T = d.get("temp")
        if T:
            ok = abs(R["lv"][1][1] - T["rlv_cold"]) < 1e-4 and abs(R["hv"]["L"][1][1] - T["rhv_cold"]) < 1e-4
            add("pass" if ok else "warn", "Cold resistance cross-check", "Temp-rise cold R equals after-STC resistance at lowest tap" if ok else "Cold R in temp-rise log differs from resistance log")
    # 3. no-load
    N = d.get("noload")
    if N and P:
        for lb, V, Va, I, Ia, W, Wa, f, Pc in N["rows"]:
            if abs(mean(I) - Ia) > .005: add("fail", "No-load current average", f"{lb}: mean of {I} = {mean(I):.3f}, logged {Ia}")
            if abs(sum(W) - Wa) > .1: add("warn", "No-load watts sum", f"{lb}: W1+W2+W3 = {sum(W):.2f} but logged average/sum {Wa} (check reading)")
        i100, i112 = N["rows"][0][4], N["rows"][2][4]
        for nm, i, lim in (("100%", i100, 2), ("112.5%", i112, 5)):
            pc = i / C["irat"] * 100
            add("pass" if pc <= lim else "fail", f"No-load current at {nm} voltage", f"{i} A = {pc:.2f}% of rated {C['irat']:.1f} A (limit {lim}%)")
    # 4. losses / impedance (IS 1180 limits from proforma, +/-10% impedance)
    L = d.get("losses")
    if L and P:
        rows = L["rows"]
        t100 = max(r[13] for r in rows); t50 = max(r[12] for r in rows if r[12])
        C["t100"], C["t50"] = t100, t50
        add("pass" if t100 <= P["loss100"] else "fail", "Total loss at 100% load (75 C)", f"Max {t100} W vs limit {P['loss100']} W")
        add("pass" if t50 <= P["loss50"] else "fail", "Total loss at 50% load", f"Max {t50} W vs limit {P['loss50']} W")
        zs = [r[1] for r in rows]; lo, hi = P["z_pct"] * .9, P["z_pct"] * 1.1
        add("pass" if all(lo <= z <= hi for z in zs) else "fail", "Impedance voltage (+/-10%)", f"%Z {min(zs)}-{max(zs)} vs declared {P['z_pct']} (band {lo:.2f}-{hi:.2f})")
        xc = max(abs(r[3]) for r in rows if r[3] is not None)
        add("pass" if xc <= 2 else "fail", "Reactance change before/after short circuit", f"Max {xc}% (limit 2%) - no winding displacement indicated")
    # 5. voltage ratio, 7 taps +5% .. -10%
    Rt = d.get("routine")
    if Rt and P:
        vph = P["lv"] / math.sqrt(3); dev = 0
        for side in Rt["ratio"].values():
            for i, row in enumerate(side):
                th = P["hv"] * (1 + (5 - 2.5 * i) / 100) / vph
                dev = max(dev, max(abs(x - th) / th * 100 for x in row))
        C["ratio_dev"] = dev
        add("pass" if dev <= .5 else "fail", "Voltage ratio, all taps", f"Max deviation from theoretical {dev:.2f}% (tolerance 0.5%)")
        ok = all(Rt[k].get("obs", "").lower().startswith("no disruptive") for k in ("induced", "hvac", "lvac"))
        add("pass" if ok else "fail", "Dielectric routine tests", "Induced over-voltage, HV (28 kV) and LV (3 kV) power-frequency: withstood")
    # 6. short circuit
    S = d.get("sc")
    if S:
        for s in S["shots"]:
            if abs(mean(s[4:7]) - s[7]) > .01: add("warn", "SC RMS average", f"{s[0]}: mean {mean(s[4:7]):.3f} vs logged {s[7]}")
        C["sc"] = {}
        for tap, (ir, ip) in S["required"].items():
            sh = [s for s in S["shots"] if s[1] == tap and s[9] == ""]
            mi, mp = mean(s[7] for s in sh), mean(s[3] for s in sh)
            C["sc"][tap] = (round(mi, 2), round(mp, 2))
            e = (mi - ir) / ir * 100
            add("pass" if abs(e) <= 10 else "fail", f"SC current at {tap} tap", f"{len(sh)} shots: mean {mi:.2f} kA rms (req {ir}, {e:+.1f}%), peak {mp:.2f} kA (req {ip})")
        th = [s for s in S["shots"] if s[9] == "thermal"]
        if th: add("pass" if th[0][8] >= 2 else "fail", "Thermal ability of SC", f"Duration {th[0][8]} s (min 2 s)")
        add("pass" if "no" in S["after"].lower() else "fail", "Post-test inspection", S["inspection"])
    # 7. temperature rise
    T = d.get("temp")
    if T and P:
        k, ca, cf = T["material_k"], T["amb_cold"], T["corr"]
        hv = T["rhv_hot"] / T["rhv_cold"] * (k + ca) - k - T["amb_sd"] + cf
        lv = T["rlv_hot"] / T["rlv_cold"] * (k + ca) - k - T["amb_sd"] + cf
        rises = [h[1] - mean(h[3:6]) for h in T["hours"]]
        C.update(hv_rise=hv, lv_rise=lv, oil_rise=rises[-1])
        add("pass" if rises[-1] <= P["limits"]["oil"] else "fail", "Top-oil temperature rise", f"{rises[-1]:.2f} K (limit {P['limits']['oil']} K)")
        w = P["limits"]["wdg"]
        for nm, v in (("HV", hv), ("LV", lv)):
            add("fail" if v > w else "warn" if w - v < 1 else "pass", f"{nm} winding temperature rise", f"{v:.1f} K (limit {w} K, margin {w - v:.1f} K)")
        dd = [abs(rises[i + 1] - rises[i]) for i in range(len(rises) - 5, len(rises) - 1)]
        add("pass" if max(dd) <= 1 else "warn", "Steady-state criterion (<=1 K/h)", f"Last-4-hour change in oil rise: max {max(dd):.2f} K")
        if abs(T["oil_rise_reported"] - rises[-1]) > .1: add("warn", "Reported vs computed oil rise", f"Logsheet reports {T['oil_rise_reported']} K, last-hour computed {rises[-1]:.2f} K")
        if abs(T["corr_written"] - cf) > 1e-6: add("warn", "Correction factor", f"Written as {T['corr_written']} at top of page 2 but {cf} used in the formula - confirm")
        add("pass" if abs(T["total"] - T["nll"] - T["fll"]) < .05 else "warn", "Injected loss = NLL + FLL", f"{T['nll']} + {T['fll']} = {T['nll'] + T['fll']:.2f} W vs {T['total']} W")
    # 8. pressure / vacuum / leakage
    Pr = d.get("pressure")
    if Pr:
        for nm in ("pressure", "vacuum"):
            x = Pr["type"][nm]; m = max(abs(b - a) for a, b in x["pts"])
            add("pass" if abs(m - x["max"]) < .01 else "warn", f"{nm.title()} test deflection", f"Max permanent deflection {m:.2f} mm (logged {x['max']}); {x['obs']}")
        add("pass" if "no" in Pr["leak"]["obs"].lower() else "fail", "Oil leakage test", f"{Pr['leak']['kpa']} kPa for {Pr['leak']['hrs']} h: {Pr['leak']['obs']}")
    return F, C

def safe_validate(d):
    """validate() for data that may be incomplete or mis-shaped (hand-edited spreadsheets): never raises."""
    try:
        return validate(d)
    except Exception as e:  # noqa: BLE001 - any shape problem becomes a blocking finding the user can act on
        what = f"missing field {e}" if isinstance(e, KeyError) else f"{type(e).__name__}: {e}"
        return [dict(level="fail", check="Data structure", detail=f"Imported data is incomplete or not in the expected layout ({what}). "
                     "Compare with a downloaded template, correct the file and import it again.")], {}

class Soft(dict):
    """Header fields that may be absent on hand-entered requests print as '-' instead of breaking the report."""
    def __missing__(self, k): return "-"

# ------------------------------------------------------------------ report
def build_pdf(j, version=None, verify_url=None):
    d = j["data"]; F, C = validate(d); P, W, Rq = Soft(d["proforma"]), Soft(d["work"]), Soft(d["request"])
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
    Rt0, Pr0 = d["routine"], d["pressure"]
    diel = "; ".join(dict.fromkeys(str(Rt0[k].get("obs", "-")) for k in ("induced", "hvac", "lvac")))
    mech = f"Leakage: {Pr0['leak']['obs']}; deflection {Pr0['type']['pressure']['max']} mm (pressure), {Pr0['type']['vacuum']['max']} mm (vacuum)"
    rank = {"pass": 0, "warn": 1, "fail": 2}
    def res(*keys):
        ls = [f["level"] for f in F if any(k in f["check"] for k in keys)]
        return verdict(max(ls, key=rank.get)) if ls else "-"
    E = [Paragraph("CENTRAL POWER RESEARCH INSTITUTE, BENGALURU", st["Title"]),
         Paragraph("Short Circuit Laboratory - TEST REPORT", st["Heading2"]),
         kv([("Test report / series no.", j["series"]), ("Sample code no.", j["sample"]), ("Customer", f"{Rq['customer']}, {Rq['address']}"),
             ("Date(s) of test", f"{W['start']} to {W['completed']}"), ("Reference standard", W["standard"]),
             ("Tests performed", Rq["tests"] + " (" + "; ".join(P["tests"]) + "), plus routine tests"),
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
              ["Short-circuit withstand (dynamic + thermal)", "; ".join(f"{t}: {a} kA rms / {b} kA pk" for t, (a, b) in C.get("sc", {}).items()), "Within +/-10% of required; no abnormality", res("SC", "Thermal", "Post-test", "Reactance")],
              ["Temperature rise", f"Top oil {C.get('oil_rise', 0):.1f} K; HV wdg {C.get('hv_rise', 0):.1f} K; LV wdg {C.get('lv_rise', 0):.1f} K", f"Oil {P['limits']['oil']} K; winding {P['limits']['wdg']} K", res("rise", "Steady")],
              ["Total loss (75 C)", f"{C.get('t100')} W (100%); {C.get('t50')} W (50%)", f"{P['loss100']} W; {P['loss50']} W", res("Total loss")],
              ["Impedance", "see section 3.2", f"{P['z_pct']} % +/-10%", res("Impedance")],
              ["No-load current at 100% / 112.5%", f"{d['noload']['rows'][0][4]} A / {d['noload']['rows'][2][4]} A", "<=2% / <=5% of rated", res("No-load current")],
              ["Voltage ratio (7 taps)", f"max dev. {C.get('ratio_dev', 0):.2f}%", "+/-0.5%", res("Voltage ratio")],
              ["Dielectric routine tests", diel, "no disruptive discharge", res("Dielectric")],
              ["Pressure / vacuum / oil leakage", mech, "No leakage; deflection as logged", res("deflection", "leakage")]],
             [48 * mm, 62 * mm, 45 * mm, 25 * mm])]
    L = d["losses"]
    E += [Paragraph("3. Detailed results", h), Paragraph("3.1 Winding resistance (HV ohm / LV milli-ohm), before / after short circuit", n)]
    R = d["resistance"]
    E.append(tbl([["Tap/winding", "Before: R1, R2, R3", "After: R1, R2, R3"]] + [[f"HV tap {t}", ", ".join(map(str, r[0])), ", ".join(map(str, r[1]))] for t, r in R["hv"].items()] + [["LV", ", ".join(map(str, R["lv"][0])), ", ".join(map(str, R["lv"][1]))]]))
    E += [Paragraph("3.2 Losses and impedance (reference temperature 75 C)", n),
          tbl([["Tap", "%Z", "%X", "%X chg", "Load loss W", "Stray W", "Total 100% W", "Total 50% W", "Isc rms/pk kA"]] +
              [[r[0], r[1], r[2], r[3] if r[3] is not None else "-", r[6], r[10], r[13], r[12] or "-", f"{r[9]}/{r[8]}" if r[9] else "-"] for r in L["rows"]]),
          Paragraph(f"No-load loss: {L['nll_bt']} W (before), {L['nll_at']} W (after).", n),
          Paragraph("3.3 No-load current / loss", n),
          tbl([["Condition", "Avg V", "I1, I2, I3 (A)", "Avg I", "Watts", "f Hz"]] + [[r[0], r[2], ", ".join(map(str, r[3])), r[4], r[6], r[7]] for r in d["noload"]["rows"]]),
          Paragraph("3.4 Routine tests (before / after short circuit)", n)]
    Rt = d["routine"]
    E.append(tbl([["Test", "Before", "After"]] + [[f"IR {k} (Gohm)", a, b] for k, (a, b) in Rt["ir"].items()] +
                 [["Induced over-voltage", f"{Rt['induced']['v']} V, {Rt['induced']['f']} Hz, {Rt['induced']['t']} s, {Rt['induced']['i'][0]} A", f"{Rt['induced']['i'][1]} A - {Rt['induced']['obs']}"],
                  ["HV / LV power-frequency", f"{Rt['hvac']['kv']} kV / {Rt['lvac']['kv']} kV for 60 s", Rt["hvac"]["obs"]],
                  ["Ambient / RH", f"{Rt['amb'][0]} C / {Rt['rh'][0]}%", f"{Rt['amb'][1]} C / {Rt['rh'][1]}%"]] +
                 [[f"Voltage ratio tap {i + 1}", ", ".join(map(str, Rt["ratio"]["BT"][i])), ", ".join(map(str, Rt["ratio"]["AT"][i]))] for i in range(7)]))
    S = d["sc"]
    E += [Paragraph(f"3.5 Short-circuit test ({S['date']}; {S['condition']})", n),
          tbl([["Osc", "Tap", "Peak kA", "RMS U", "RMS V", "RMS W", "Avg", "Dur s", "Note"]] + [[s[0], s[1], s[3] or "-", s[4], s[5], s[6], s[7], s[8], s[9]] for s in S["shots"]]),
          Paragraph(f"During / after test: {S['during']} / {S['after']}. Untanking: {S['inspection']}.", n)]
    T = d["temp"]
    E += [Paragraph(f"3.6 Temperature rise ({T['dates']}; short-circuit method, {T['tap']} tap, {T['current']} A, injected {T['total']} W)", n),
          tbl([["Hour", "Top oil C", "Bottom oil C", "Mean ambient C", "Oil rise K"]] + [[x[0], x[1], x[2], f"{mean(x[3:6]):.2f}", f"{x[1] - mean(x[3:6]):.2f}"] for x in T["hours"]]),
          Paragraph(f"Winding rise = (R2/R1)(235+{T['amb_cold']}) - 235 - {T['amb_sd']} + {T['corr']}: HV {C['hv_rise']:.1f} K, LV {C['lv_rise']:.1f} K.", n)]
    Pr = d["pressure"]; ty = Pr["type"]
    E += [Paragraph("3.7 Pressure, vacuum and oil-leakage tests", n),
          tbl([["Test", "Condition", "Result"], ["Routine pressure", f"{Pr['routine']['kpa']} kPa, {Pr['routine']['min']} min ({Pr['routine']['date']})", Pr["routine"]["obs"]],
               ["Type pressure", f"{ty['pressure']['kpa']} kPa, {ty['pressure']['min']} min", f"Max deflection {ty['pressure']['max']} mm - {ty['pressure']['obs']}"],
               ["Vacuum", f"{ty['vacuum']['mmhg']} mmHg, {ty['vacuum']['min']} min", f"Max deflection {ty['vacuum']['max']} mm - {ty['vacuum']['obs']}"],
               ["Oil leakage", f"{Pr['leak']['kpa']} kPa (2 x {Pr['leak']['head_kpa']} kPa head), {Pr['leak']['hrs']} h ({Pr['leak']['date']})", Pr["leak"]["obs"]]])]
    fails = [f for f in F if f["level"] == "fail"]; warns = [f for f in F if f["level"] == "warn"]
    E += [Paragraph("4. Statement of conformity", h),
          Paragraph(f"Decision rule requested by the customer: {Rq['conformity']}. <b>" +
                    ("The sample does NOT comply: " + "; ".join(f["check"] for f in fails) if fails else
                     f"The sample complied with all {sum(f['level'] == 'pass' for f in F)} automatically evaluated requirements ({W['standard']}).") + "</b>", n)]
    if warns:
        E += [Paragraph("* Items flagged by automated validation and accepted by the reviewer at approval:" if j.get("approver") else
                        "* Items flagged by automated validation - to be confirmed by the reviewer before approval:", n), tbl([["Check", "Detail"]] + [[f["check"], f["detail"]] for f in warns])]
    E += [Spacer(1, 14), tbl([["Test Engineer: " + W["engineer"], f"Approved by: {j['approver'] or '(pending)'}"]], head=False),
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
    err = []
    if not re.fullmatch(SERIES_RE, str(b.get("series", ""))): err.append("Series must look like CPRIBLRSCL25T1654")
    if not re.fullmatch(SAMPLE_RE, str(b.get("sample", ""))): err.append("Sample code must look like HVD25S0847")
    for f in ("customer", "rating"):
        if not str(b.get(f, "")).strip(): err.append(f"{f} is required")
    return err

def data_changed(j, d, event):
    """Any change to test data sends the job back to 'Data Imported': checks and the report must be redone."""
    stale = j["stage"] >= 3
    save(j["id"], data=d, stage=max(min(j["stage"], 1), 1), findings=[], approver=None)
    with db() as c: log(c, j["id"], event + (" - earlier report is now out of date" if stale else ""))

def freeze(j):
    """Build the PDF once and store it: every generated/approved report is an immutable, hash-verifiable version."""
    with db() as c: v = (c.execute("SELECT MAX(version) FROM reports WHERE job_id=?", (j["id"],)).fetchone()[0] or 0) + 1
    token = secrets.token_urlsafe(12)
    pdf = build_pdf(j, v, request.host_url + "verify/" + token).getvalue()
    sha = hashlib.sha256(pdf).hexdigest()
    with db() as c: c.execute("INSERT INTO reports(job_id,version,token,sha256,pdf,approver,at) VALUES(?,?,?,?,?,?,?)", (j["id"], v, token, sha, pdf, j.get("approver"), now()))
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

@app.get("/api/jobs/<int:i>")
def one(i): return jsonify(getjob(i))

# ---- data collection: JSON, CSV, Excel, SQLite database
@app.post("/api/jobs/<int:i>/import")
def imp(i):
    j = getjob(i); b = body(); notes = []
    if isinstance(b.get("content"), dict): name, content, kind = str(b.get("filename") or "upload"), b["content"], "json"
    else:
        name, raw = upload(b); content, kind, notes = importers.load_test_data(name, raw, j["series"])
    ok = set(NAMES) | {"ids"}
    if not isinstance(content, dict) or not content or not set(content) <= ok:
        return jsonify(error=["Unrecognised file: expected sections " + ", ".join(NAMES)]), 400
    bad = [k for k, v in content.items() if not isinstance(v, dict)]
    if bad: return jsonify(error=[f"Section '{k}' must contain named fields" for k in bad]), 400
    sha = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    try:
        with db() as c: c.execute("INSERT INTO imports(job_id,source,kind,sha256,at) VALUES(?,?,?,?,?)", (i, name, kind, sha, now()))
    except sqlite3.IntegrityError: return jsonify(error=["Duplicate file - identical content already imported for this job"]), 409
    d = j["data"]
    for k, v in content.items(): d[k] = {**d.get(k, {}), **v} if k in ("ids", "request") else v
    label = {"json": "JSON", "csv": "CSV", "xlsx": "Excel", "sqlite": "database"}[kind]
    data_changed(j, d, f"Imported {label} file {name} ({', '.join(content)})" + (f" [{'; '.join(notes)}]" if notes else ""))
    return jsonify(ok=True, kind=kind, sections=list(content), notes=notes)

@app.post("/api/jobs/<int:i>/section")
def section(i):
    """Save one section typed or corrected by hand (also used to accept an AI reading after review)."""
    j = getjob(i); b = body(); k = b.get("section")
    if k not in set(NAMES) | {"ids"} or not isinstance(b.get("data"), dict): return jsonify(error=["Choose a section and provide its fields"]), 400
    d = j["data"]; d[k] = b["data"]
    data_changed(j, d, f"{NAMES.get(k, 'Identifiers')} {'entered from AI reading of ' + str(b['source'])[:120] + ' after review' if b.get('source') else 'edited by hand'}")
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
        r["rating"] = r["rating"] or "Not recorded"; err = check_ids(r)
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
    mime = sniff(raw); sha = hashlib.sha256(raw).hexdigest()
    try:
        with db() as c:
            cur = c.execute("INSERT INTO sources(job_id,filename,mime,sha256,content,at) VALUES(?,?,?,?,?,?)", (i, name, mime, sha, raw, now()))
            log(c, i, f"Source document attached: {name} (SHA-256 {sha[:12]}...)"); return jsonify(id=cur.lastrowid), 201
    except sqlite3.IntegrityError: return jsonify(error=["This document is already attached to the job"]), 409

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
    r = source_row(sid); k = body().get("section")
    if k not in NAMES: return jsonify(error=["Choose which document this is"]), 400
    example = load_demo().get(k, {})
    with db() as c:
        out = vision.extract(c, r["content"], r["mime"], k, NAMES[k], example, app.config.get("VISION_TRANSPORT"))
        log(c, r["job_id"], f"AI reading requested for {r['filename']} as {NAMES[k]} (proposal only, not saved)")
    return jsonify(out)

# ---- validate, generate, approve
@app.post("/api/jobs/<int:i>/validate")
def val(i):
    j = getjob(i); F, _ = safe_validate(j["data"]); fails = sum(f["level"] == "fail" for f in F)
    save(i, findings=F, stage=max(j["stage"], 2) if not fails else min(j["stage"], 1))
    with db() as c: log(c, i, f"Validation run: {sum(f['level'] == 'pass' for f in F)} pass, {sum(f['level'] == 'warn' for f in F)} warn, {fails} fail")
    return jsonify(findings=F)

@app.post("/api/jobs/<int:i>/generate")
def gen(i):
    j = getjob(i)
    if j["stage"] < 2: return jsonify(error=["Validate data (no failures) before generating"]), 409
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
    j = getjob(i); name = str(body().get("name") or "").strip()
    if j["stage"] < 3 or not name: return jsonify(error=["Generate the report and enter reviewer name first"]), 409
    save(i, stage=4, approver=name); v, sha = freeze(getjob(i))
    with db() as c: log(c, i, f"Approved by {name}; released for export (version {v}, SHA-256 {sha[:12]}...)")
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
                   approver=r["approver"], intact=intact, current=current, approved=bool(r["approver"]) and current and j["stage"] == 4)

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
             stage=3 if j["stage"] == 4 else j["stage"], approver=None if j["stage"] == 4 else j["approver"])
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
    save(i, stage=2, approver=None)
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
                   ai={k: ai[k] for k in ("configured", "model", "calls_today", "daily_limit")}, sections=NAMES)

@app.post("/api/demo")
def demo():
    data = load_demo(); w = data["work"]
    with db() as c:
        if c.execute("SELECT id FROM jobs WHERE series=?", (w["series"],)).fetchone(): return jsonify(error=["Demo job already loaded"]), 409
    r = app.test_client()
    i = r.post("/api/jobs", json=dict(series=w["series"], sample=w["sample"], customer=data["request"]["customer"], rating=data["request"]["rating"], request=data["request"])).get_json()["id"]
    r.post(f"/api/jobs/{i}/import", json=dict(filename=os.path.basename(DEMO), content={k: v for k, v in data.items() if k != "request"}))
    return jsonify(id=i), 201

init()
if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5000)))
