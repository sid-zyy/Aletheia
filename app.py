"""Aletheia - Automated Test Report Generation System (CPRI Short Circuit Laboratory).
Run:  pip install -r requirements.txt && python app.py   ->  http://localhost:5000
Modules: Data Collection (importers.py: JSON / CSV / Excel / SQLite, registers; vision.py: optional scan reading)
         | Database (SQLite) | Validation (thresholds in rules.py) | Report Engine (PDF from report_template.json,
         frozen versions + QR verification, customer download) | Dashboard (static/index.html)
Settings, API and the data model: README.md and docs/ARCHITECTURE.md.
"""
import base64, json, hashlib, io, math, os, re, secrets, sqlite3, sys, datetime as dt
import importers, vision
import rules, report
import auth, integrity, workflow, excel_routes, retention, notify, portal, tickets
from integrity import Conflict, Locked
from rules import val as rule, nll_limits, ratio_tolerance, classify_observation
from statistics import mean
from xml.sax.saxutils import escape as xesc
from flask import Flask, request, jsonify, send_file, send_from_directory, abort, has_request_context

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ALETHEIA_DB") or os.path.join(HERE, "aletheia.db")
AI_CACHE = os.path.join(os.path.dirname(os.path.abspath(DB)), "ai_cache.db")  # survives deleting the job database
DEMO = os.path.join(HERE, "sample_data", "AP_Transformers_25T1654.json")
DEMO_SCANS = os.path.join(HERE, "sample_data", "scans")  # the scanned sheets the demo data was typed from

def load_demo():
    with open(DEMO, encoding="utf-8") as f: return json.load(f)

app = Flask(__name__, static_folder=os.path.join(HERE, "static"))
STAGES = ["Request Captured", "Data Imported", "Validated", "Report Generated", "Approved & Exported"]
# The formal name of every test record: the one list the pages, notifications, audit entries, Excel titles and the report
# use. Only display names: the keys stored with the data never change.
NAMES = {"request": "Customer Request Form", "proforma": "Proforma for Transformers", "work": "Work Instruction",
         "losses": "Loss Measurement Datasheet", "resistance": "Winding Resistance and Loss Logsheet",
         "noload": "No-Load Loss and Current Logsheet", "routine": "Routine Test Logsheet",
         "sc": "Short-Circuit Withstand Test Logsheet", "temp": "Temperature-Rise Test Logsheet",
         "pressure": "Pressure and Oil-Leakage Test Logsheet"}
EXTRA_NAMES = {"ids": "Sample Identification Record", "other": "Supplementary Test Records"}
ALL_NAMES = {**NAMES, **EXTRA_NAMES}
def name(k): return ALL_NAMES.get(k, k)
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
        # archived: a historical record from an existing register, not a job in progress; verdict: outcome of the checks
        # (or as stated in the register); tested: date of test from the register, ISO when it could be read
        have = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        for col, ddl in (("archived", "INTEGER DEFAULT 0"), ("verdict", "TEXT"), ("tested", "TEXT")):
            if col not in have: c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
        # sections: JSON {document: true, or [keys] for the merged ones (ids, other)}, so an import can be undone
        if "sections" not in {r[1] for r in c.execute("PRAGMA table_info(imports)")}: c.execute("ALTER TABLE imports ADD COLUMN sections TEXT")
        auth.init_db(c)
        # who did it: every row that records an action carries the signed-in user (accounts are never deleted)
        for t, cols in (("jobs", (("org_id", "INT"), ("created_by", "INT"))), ("imports", (("user_id", "INT"),)), ("sources", (("user_id", "INT"), ("section", "TEXT"))),
                        ("reports", (("approver_user_id", "INT"), ("generated_by", "INT"))),
                        ("audit", (("user_id", "INT"), ("actor", "TEXT"), ("role", "TEXT"), ("ip", "TEXT"), ("kind", "TEXT")))):
            have = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
            for col, ddl in cols:
                if col not in have: c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {ddl}")
        integrity.init_db(c)
        # plan: the tests this job needs (JSON list of section keys; empty = whatever is uploaded); intake: the receiving
        # engineer's record (arrival, opened by, validity, read-back check); signed_off: the administrator's approval (every test verified)
        have = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        for col, ddl in (("plan", "TEXT"), ("intake", "TEXT"), ("signed_off_by", "INT"), ("signed_off_at", "TEXT")):
            if col not in have: c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
        saved = integrity.migrate(c, DB)
        if saved: print(f"Database migrated to schema {integrity.SCHEMA_VERSION}; backup kept at {saved}")
        integrity.install_triggers(c)
        clash = auth.migrate_roles(c, log)
        if clash: raise SystemExit("The verifier and approver roles were removed. These accounts would combine Admin with Tester, which is not "
                                   "allowed: split each into two accounts, then start again: " + ", ".join(clash))

def actor():
    """(user id, display name, roles, workstation) of whoever is acting; 'system' outside a signed-in request."""
    u = auth.current() if has_request_context() else None
    if not u: return None, "system", None, (request.remote_addr if has_request_context() else None)
    return u["id"], f"{u['full_name']} ({u['username']})", ",".join(u["roles"]), request.remote_addr

def log(c, jid, ev, kind="event"):
    """Audit entry. kind: job, data, check, verify, report, approve, admin, auth, denied, notify, ticket, event."""
    uid, name, roles, ip = actor()
    cur = c.execute("INSERT INTO audit(job_id,event,at,user_id,actor,role,ip,kind) VALUES(?,?,?,?,?,?,?,?)", (jid, ev, now(), uid, name, roles, ip, kind))
    integrity.seal(c, cur.lastrowid)  # hash chain: changing or removing any entry later is detectable

def me(): return actor()[0]

def getjob(jid, full=True):
    with db() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not r or not may_see(r): abort(404)  # a customer guessing another organisation's job id learns nothing
        j = dict(r); j["data"] = integrity.job_data(c, jid); j["findings"] = json.loads(j["findings"])
        j["meta"] = integrity.section_meta(c, jid)  # per section: state, revision, who uploaded / verified it and from which file
        j["plan"] = workflow.loads(j.get("plan"), []); j["intake"] = workflow.loads(j.get("intake"), {})
        j["assign"] = integrity.assignments(c, jid)
        j["progress"], j["counts"] = workflow.progress(c, jid, NAMES, j["plan"])
        j["signoff"] = {"by": c.execute("SELECT full_name FROM users WHERE id=?", (j["signed_off_by"],)).fetchone()[0], "at": j["signed_off_at"]} if j.get("signed_off_by") else None
        j["signoff_blockers"] = workflow.ready_for_signoff(c, jid, ALL_NAMES, j["plan"])
        j["amend"] = workflow.loads(j.get("amend"), None)
        j["amendments"] = [dict(a) for a in c.execute("SELECT a.id, a.from_version, a.new_version, a.reason, a.sections, a.opened_at, a.closed_at, "
                                                       "o.full_name AS opened_by, s.full_name AS second_signer FROM amendments a LEFT JOIN users o ON o.id=a.opened_by "
                                                       "LEFT JOIN users s ON s.id=a.second_signer WHERE a.job_id=? ORDER BY a.id", (jid,))]
        for a in j["amendments"]: a["sections"] = json.loads(a["sections"])
        j["ever_released"] = bool(c.execute("SELECT 1 FROM reports WHERE job_id=? AND approver IS NOT NULL", (jid,)).fetchone())
        j["stage_name"] = "Historical record" if j.get("archived") else STAGES[j["stage"]]
        j["released"] = j["stage"] == 4 and not j.get("archived")
        if full:
            j["audit"] = [dict(a) for a in c.execute("SELECT event,at,actor,kind FROM audit WHERE job_id=? ORDER BY id", (jid,))]
            j["imports"] = [dict(a, sections=json.loads(a["sections"]) if a["sections"] else None)
                            for a in c.execute("SELECT i.id,i.source,i.kind,i.sha256,i.at,i.sections,i.file_id,f.sha256 AS file_sha256,u.full_name AS by "
                                               "FROM imports i LEFT JOIN files f ON f.id=i.file_id LEFT JOIN users u ON u.id=i.user_id WHERE i.job_id=? ORDER BY i.id", (jid,))]
            j["sources"] = [dict(a) for a in c.execute("SELECT id,filename,mime,sha256,at,section FROM sources WHERE job_id=? ORDER BY id", (jid,))]
            j["reports"] = [dict(a) for a in c.execute("SELECT version,token,sha256,approver,approver_id,at,manifest_sha256 FROM reports WHERE job_id=? ORDER BY version DESC", (jid,))]
        return j

def may_see(row):
    """Staff see every job; a customer only their own organisation's."""
    if not has_request_context() or not auth.is_customer(): return True
    return row["org_id"] is not None and row["org_id"] == auth.current().get("org_id")

def save(jid, **kw):
    if "data" in kw: raise ValueError("job data lives in the sections table; use integrity.write_section")
    kw["updated"] = now()
    with db() as c:
        c.execute(f"UPDATE jobs SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*[json.dumps(v) if isinstance(v, (dict, list)) else v for v in kw.values()], jid))

# --------------------------------------------------------------- validation
def validate(d, plan=None):
    """Returns (findings, calc). Levels: pass / warn (needs reviewer attention) / fail (blocks).
    plan: the job's required tests (section keys); documents outside it are neither expected nor reported missing."""
    F, C = [], {}
    def add(l, c, t, src=None, found=None, exp=None, fix=None, na=False, basis=None, inconclusive=False, cause=None, blocks=False, advisory=False):
        """src: document(s) checked; found / exp: observed vs required value; fix: what the engineer should do.
        cause: technical reason a check was skipped, for the engineer only; never printed in the report.
        blocks: the data itself is wrong (e.g. a logged average that does not match its readings), so no report can be built
        until it is corrected. Other failures are results: the sample does not meet a requirement, and the report says so.
        advisory: Aletheia re-did arithmetic the lab already logged (an average, a sum, a maximum). Values are taken as logged
        (faculty note F5), so this only points at a possible slip: it never blocks, needs no review and is never printed."""
        f = dict(level=l, check=c, detail=t, **({"na": True} if na else {}), **({"inconclusive": True} if inconclusive else {}),
                 **({"blocks": True} if blocks and l == "fail" and not advisory else {}), **({"advisory": True} if advisory else {}))
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
    need = required(plan)
    miss = [NAMES[k] for k in need if k not in d]
    # Missing documents do not block the report: checks run on what is present, and the report says what was not evaluated.
    add("warn" if miss else "pass", "Completeness of source documents",
        f"Missing: {', '.join(miss)}. Checks that need them were skipped; the report marks those tests as not evaluated." if miss
        else f"All {len(need)} required documents imported",
        src="Required documents", found=f"{len(need) - len(miss)} of {len(need)} required documents imported", exp=f"All {len(need)} required documents",
        fix=("Upload the missing documents from their rows on the job page, or mark a test not applicable (with a reason) if it "
             "was not performed.") if miss else None)
    if "proforma" in need and "proforma" not in d and any(k in d for k in ("noload", "losses", "routine", "temp")):
        add("warn", "Limits not available", "The proforma is missing, so loss, impedance, no-load current, ratio and temperature-rise "
            "results could not be compared with their limits.", src=NAMES["proforma"], found="Proforma not imported",
            exp="Proforma with rating, guaranteed losses, impedance and temperature-rise limits",
            fix="Import the proforma to evaluate these results against their limits.")
    # 1. identifiers must agree across documents (handwriting: 4 can read as H or 6)
    norm = lambda s: s.upper().replace("H", "4")
    ids = d.get("ids", {})
    with na('Identifier consistency', name("ids")):
        two = lambda v: (list(v) + [None, None])[:2] if isinstance(v, (list, tuple)) else [None, None]
        written = lambda x: x is not None and str(x).strip() not in ("", "NA")  # an identifier left off a sheet is not compared
        if "work" in ids and written(two(ids["work"])[0]):
            w0, w1 = two(ids["work"])
            ws, wm = norm(str(w0))[-7:], norm(str(w1))[-4:] if written(w1) else None
            bad = [(k, s, m) for k, v in ids.items() for s, m in [two(v)] if (k in d or k == "work")
                   and ((written(s) and norm(str(s))[-7:] != ws) or (written(m) and wm and norm(str(m))[-4:] != wm))]  # sheets uploaded only
            for k, s, m in bad:
                add("warn", "Identifier consistency", f"{name(k)}: transcribed '{s}' / '{m}' but work instruction = {ws} / {wm}. Verify handwriting (4/6/H).",
                    src=name(k), found=f"Series {s}, sample {m}", exp=f"Series ...{ws}, sample ...{wm} (as on the work instruction)",
                    fix=f"Look at the IDs on the scanned {name(k).lower()}; handwritten 4, 6 and H are easy to confuse. If it was mistyped, correct it under '{name('ids')}'.")
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
                if abs(mean(I) - Ia) > .005: add("warn", "No-load current average", f"{lb}: mean of {I} = {mean(I):.3f}, logged {Ia} (the logged average is used)",
                    src=NAMES["noload"], found=f"{lb}: logged average {Ia} A", exp=f"Mean of I1, I2, I3 = {mean(I):.3f} A",
                    fix="Check the average on the log sheet, or the phase current that may have been misread.", advisory=True)
                if abs(sum(W) - Wa) > .1: add("warn", "No-load watts sum", f"{lb}: W1+W2+W3 = {sum(W):.2f} but logged average/sum {Wa} (check reading)",
                    src=NAMES["noload"], found=f"{lb}: logged total {Wa} W", exp=f"W1 + W2 + W3 = {' + '.join(map(str, W))} = {sum(W):.2f} W",
                    fix="Check the three wattmeter readings and the total on the scan; one of them was probably misread or mis-added.", advisory=True)
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
                    fix="Check the average for this shot on the short-circuit log.", advisory=True)
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
        logged = lambda k: T.get(k) if isinstance(T.get(k), (int, float)) and not isinstance(T.get(k), bool) else None
        rises = None
        with na(None):  # hourly rises: for the steady-state criterion and the advisory comparison only
            rises = [h[1] - mean(h[3:6]) for h in T["hours"]]
        with na('Top-oil temperature rise', NAMES["temp"]):
            oil_v = logged("oil_rise_reported") if logged("oil_rise_reported") is not None else rises[-1]
            C.update(oil_rise=oil_v, oil_rise_src="logged" if logged("oil_rise_reported") is not None else "calculated"); temp_ok = True
        with na('Winding temperature rise', NAMES["temp"]):
            if logged("hv_rise") is not None and logged("lv_rise") is not None:
                hv, lv = logged("hv_rise"), logged("lv_rise"); C["wdg_src"] = "logged"
            else:  # nothing logged: the IS formula on the logged resistances (Q11: should the lab log the rise instead?)
                k, ca, cf = T["material_k"], T["amb_cold"], T["corr"]
                hv = T["rhv_hot"] / T["rhv_cold"] * (k + ca) - k - T["amb_sd"] + cf
                lv = T["rlv_hot"] / T["rlv_cold"] * (k + ca) - k - T["amb_sd"] + cf
                C["wdg_src"] = "calculated"
            C.update(hv_rise=hv, lv_rise=lv); wdg_ok = True
        if temp_ok:
            with na('Top-oil temperature rise', NAMES["temp"]):
                oil = P["limits"]["oil"]; ov = C["oil_rise"]; how = "as logged" if C["oil_rise_src"] == "logged" else "calculated from the last hour (no rise logged)"
                um = rule("temp_margin_inconclusive_k"); thin = 0 <= oil - ov < um
                add("fail" if ov > oil else "warn" if thin else "pass", "Top-oil temperature rise", f"{ov:.2f} K {how} (limit {oil} K" + (f", margin {oil - ov:.1f} K: inconclusive)" if thin else ")"),
                    src=NAMES["temp"], found=f"{ov:.2f} K ({how})", exp=f"{oil} K or less", basis=("oil_limit_k / wdg_limit_k", "temp_margin_inconclusive_k"), inconclusive=thin,
                    fix=None if ov <= oil else "Top-oil rise exceeds the limit; the sample fails this test unless a reading is wrong.")
        if wdg_ok:
            with na('Winding temperature rise', NAMES["temp"]):
                w = P["limits"]["wdg"]
                for nm, v in (("HV", hv), ("LV", lv)):
                    um = rule("temp_margin_inconclusive_k"); thin = 0 <= w - v < um
                    add("fail" if v > w else "warn" if thin else "pass", f"{nm} winding temperature rise", f"{v:.1f} K {'as logged' if C['wdg_src'] == 'logged' else 'calculated'} (limit {w} K, margin {w - v:.1f} K" + (": inconclusive)" if thin else ")"),
                        src=NAMES["temp"], found=f"{v:.1f} K (margin {w - v:.1f} K)", exp=f"{w} K or less", basis=("oil_limit_k / wdg_limit_k", "temp_margin_inconclusive_k"), inconclusive=thin,
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
                    fix="Check which hour's readings the written figure was taken from. The report uses the logged value.", advisory=True)
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
                    fix=None if iok else "The injected loss does not equal the sum of losses; check the figures on the log sheet.", advisory=True)
    # 8. pressure / vacuum / leakage
    Pr = d.get("pressure")
    if Pr:
        with na('Pressure and vacuum deflection', NAMES["pressure"]):
            for nm in ("pressure", "vacuum"):
                x = Pr["type"][nm]; m = max(abs(b - a) for a, b in x["pts"])
                dok = abs(m - x["max"]) < .01
                add("pass" if dok else "warn", f"{nm.title()} test deflection", f"Logged maximum {x['max']} mm (largest before/after difference {m:.2f} mm); {x['obs']}",
                    src=NAMES["pressure"], found=f"{x['max']} mm logged as maximum", exp=f"{m:.2f} mm, the largest before/after difference",
                    fix=None if dok else "Re-check the deflection readings and the maximum written on the log.", advisory=True)
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
        with na("Supplementary test record", "Supplementary test record"):
            t = str(o.get("title") or "Supplementary test record"); src = f"Supplementary test record: {t}"
            vals = [f.get("value") for f in o.get("fields") or []] + [c for tb in o.get("tables") or [] for r in tb.get("rows") or [] for c in r]
            empty = sum(v is None or (isinstance(v, str) and not v.strip()) for v in vals)
            add("warn" if empty or not vals else "pass", f"Supplementary test record: {t}",
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

def required(plan):
    """The documents a job needs: the customer's request and the tests in its plan (every document when it has no plan)."""
    return [k for k in NAMES if k == "request" or k in plan] if plan else list(NAMES)

def safe_validate(d, plan=None):
    """validate() for data that may be incomplete or mis-shaped (hand-edited spreadsheets): never raises.
    If one document's layout breaks the checks, it is named in a blocking finding and the other documents are still checked."""
    try:
        return validate(d, plan)
    except Exception as e:  # noqa: BLE001 - any shape problem becomes a blocking finding the user can act on
        err = e
    culprits = []
    for k in [k for k in d if k != "request"]:
        try: validate({x: v for x, v in d.items() if x != k}, plan)
        except Exception: continue  # noqa: BLE001 - still failing without k, so k alone is not the cause
        culprits.append(k)
    what = lambda x: f"missing field {x}" if isinstance(x, KeyError) else f"{type(x).__name__}: {x}"
    if not culprits:
        return [dict(level="fail", blocks=True, check="Data structure", detail=f"Imported data is incomplete or not in the expected layout ({what(err)}). "
                     "Compare with a downloaded template, correct the file and import it again.")], {}
    try: F, C = validate({x: v for x, v in d.items() if x not in culprits}, plan)
    except Exception: F, C = [], {}  # noqa: BLE001
    F = [f for f in F if not (f["check"] == "Completeness of source documents")]
    for k in culprits:
        nm = name(k)
        F.insert(0, dict(level="fail", blocks=True, check=f"Data structure: {nm}", source=nm,
                         detail=f"The {nm.lower()} is not in the expected layout ({what(err)}), so it could not be checked.",
                         found="Fields or table shape differ from the standard layout", expected="Same layout as the downloadable template",
                         action=f"Open the {nm.lower()} (Edit under Sources) and correct it, re-import it from a corrected file, "
                                "or remove it from this job (Remove under Sources) if it should not be part of the report."))
    return F, C

def blocking(F):
    """Failures that mean the data is wrong (no report until corrected), as opposed to a sample that failed a requirement."""
    return [f for f in F if f["level"] == "fail" and f.get("blocks")]

def verdict_of(F):
    """Outcome stored with the job for search and the dashboard; None while the data still has errors."""
    if not F or blocking(F): return None
    if any(f["level"] == "fail" for f in F): return "Does not comply"
    partly = any(f.get("na") for f in F) or any(f["check"] == "Completeness of source documents" and f["level"] != "pass" for f in F)
    return "Complies (partly evaluated)" if partly else "Complies"

# Wording and laboratory details of the report: edit report_template.json (or point ALETHEIA_TEMPLATE at another file); see report.py.
TEMPLATE_FILE = os.environ.get("ALETHEIA_TEMPLATE") or os.path.join(HERE, "report_template.json")

# ------------------------------------------------------------------ report
def build_pdf(j, version=None, verify_url=None, manifest=None, partial=None):
    """The test report in the laboratory's format (report.py). partial=dict(version, approved=[names], pending=[names],
    sections=[(name, revision, sha)]) builds the customer's partial report instead: approved tests' values only, no conclusion,
    no signatures, a PARTIAL - NOT FINAL watermark on every page (NEXT_STEPS.md 7.1)."""
    return report.build(sys.modules[__name__], j, version, verify_url, manifest, partial)

# --------------------------------------------------------------------- API
SERIES_RE, SAMPLE_RE = r"CPRIBLRSCL\d{2}T\d{4}", r"HVD\d{2}S\d{4}"
EMP_RE = r"[A-Z0-9][A-Z0-9/-]{1,19}"  # the lab's employee ID format is not known, so only its shape is checked
def signed(name, emp): return f"{name} (Employee ID {emp})" if name and emp else name  # reports approved before IDs were recorded show the name only
REQ_KEYS = ("customer", "address", "serial", "tests", "criteria", "witness", "conformity", "rating")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

@app.errorhandler(importers.ImportError_)
@app.errorhandler(vision.VisionError)
def bad_file(e): return jsonify(error=[str(e)]), 400

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"): return jsonify(error=["Not found, or not visible to your account"]), 404
    return e

@app.errorhandler(413)
def too_big(e): return jsonify(error=["File is too large (20 MB maximum)"]), 413

def body(): return request.get_json(force=True, silent=True) or {}

def upload(b):
    """Uploaded files arrive as base64 inside JSON: {filename, b64}."""
    try: raw = base64.b64decode(b.get("b64") or "", validate=True)
    except ValueError: raise importers.ImportError_("Upload was not readable") from None
    if not raw: raise importers.ImportError_("The file is empty")
    return str(b.get("filename") or "upload")[:200], raw

def check_ids(b, auto=False):
    """Only the series number is required (it identifies the record), unless it is to be allocated (auto). Other fields may be
    left empty and are stored as NA; a sample code that is given must still have the CPRI format."""
    err = []
    if auto: b["series"] = "CPRIBLRSCL00T0000"  # placeholder, replaced inside the insert transaction
    if not str(b.get("series") or "").strip(): err.append("Test series number is required (it identifies the record)")
    elif not re.fullmatch(SERIES_RE, str(b["series"]).strip()): err.append("Series must look like CPRIBLRSCL25T1654")
    sample = str(b.get("sample") or "").strip()
    if sample and sample.upper() != "NA" and not re.fullmatch(SAMPLE_RE, sample): err.append("Sample code must look like HVD25S0847, or be left empty")
    if not err:
        b["series"] = str(b["series"]).strip()
        for f in ("sample", "customer", "rating"): b[f] = str(b.get(f) or "").strip() or "NA"
    return err

def org_problem(b):
    """The customer organisation a job belongs to (whose customer accounts may follow it). Optional until intake is tightened."""
    o = b.get("org_id")
    if o in (None, ""): b["org_id"] = None; return []
    with db() as c: ok = isinstance(o, int) and c.execute("SELECT 1 FROM orgs WHERE id=?", (o,)).fetchone()
    return [] if ok else ["Unknown customer organisation"]

def after_change(c, jid, event):
    """Inside the write transaction that changed some sections: the checks and any generated report must be redone, and
    record details left as NA are filled from the imported documents (request form, work instruction)."""
    r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone(); d = integrity.job_data(c, jid)
    rq, wk = d.get("request") or {}, d.get("work") or {}
    found = dict(customer=rq.get("customer") or wk.get("customer"), rating=rq.get("rating"), sample=wk.get("sample"))
    fill = {k: str(v).strip() for k, v in found.items() if r[k] in (None, "", "NA") and v and str(v).strip()
            and (k != "sample" or re.fullmatch(SAMPLE_RE, str(v).strip()))}
    has_data = any(k != "request" for k in d)
    sets = dict(stage=1 if has_data else 0, findings="[]", approver=None, approver_id=None, verdict=None,
                archived=0 if has_data else r["archived"], updated=now(), signed_off_by=None, signed_off_at=None, **fill)
    c.execute(f"UPDATE jobs SET {','.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), jid))
    log(c, jid, event + (" - earlier report is now out of date" if r["stage"] >= 3 else ""), kind="data")

def locked(j):
    """A released report and everything it was built from are frozen (corrections go through an amendment)."""
    if j.get("released"): return jsonify(error=["This report has been released: its record and data are locked and cannot be changed"]), 409
    return None

def refuse(c, jid, msg, status=403):
    """A workflow rule said no: tell the user why and keep the refusal in the audit trail (rule 2.4.6)."""
    log(c, jid, f"Refused: {msg}", kind="denied")
    return jsonify(error=[msg[0].upper() + msg[1:]]), status

def write_check(c, i, keys):
    """None, or (reason, status) refusing this user's write to one of these sections: 403 when it is not theirs to write
    (ownership, certification), 409 when the section is verified and locked."""
    u = auth.current()
    am = workflow.loads(c.execute("SELECT amend FROM jobs WHERE id=?", (i,)).fetchone()[0], None)
    for k in keys:
        if am and k not in am["sections"] and k != "ids":
            return f"{name(k)} is not part of the open amendment (only {', '.join(name(x) for x in am['sections'])} may change)", 409
        why = workflow.may_write(c, i, k, u)
        if why: return f"{name(k)}: {why}", 403
        row = c.execute("SELECT state FROM sections WHERE job_id=? AND key=?", (i, k)).fetchone()
        if row and row["state"] == "verified" and k not in workflow.MERGED:
            return f"{name(k)} has been verified and is locked; a tester must reopen it (with a reason) first", 409
    return None

def bay_of(b):
    """Test bays were removed: uploads record none (older sections keep the bay they were recorded in)."""
    return None

def conflict(e):
    r = e.row
    if r is None: return jsonify(error=["This section was removed by someone else in the meantime. Reload the page; your changes were not saved."]), 409
    with db() as c: who = c.execute("SELECT full_name FROM users WHERE id=?", (r["uploaded_by"],)).fetchone()
    return jsonify(error=[f"This section was changed by {who[0] if who else 'someone else'} at {str(r['uploaded_at'])[11:16]} "
                          f"(now revision {r['revision']}). Reload the page and check their change; yours was not saved."]), 409

def manifest(j, version):
    """What this report version was built from: each section's revision and data hash, its source file's hash, the template
    version that read it, who uploaded and verified it, plus the intake, sign-off, signer and software. Its own SHA-256 is
    printed on the report, so a reader can check later that nothing behind the report changed (NEXT_STEPS.md 6.2)."""
    with db() as c:
        secs = [dict(test=name(r["key"]), key=r["key"],
                     revision=r["revision"], state=r["state"], data_sha256=r["data_sha256"], file=r["fname"], file_sha256=r["fsha"],
                     template=f"{r['tkey']} v{r['tver']}" if r["tkey"] else None, uploaded_by=r["up"], verified_by=r["ver"], bay=r["bay"])
                for r in c.execute("""SELECT s.*, f.name AS fname, f.sha256 AS fsha, t.key AS tkey, t.version AS tver, u.full_name AS up, v.full_name AS ver
                                      FROM sections s LEFT JOIN files f ON f.id=s.file_id LEFT JOIN templates t ON t.id=s.template_id
                                      LEFT JOIN users u ON u.id=s.uploaded_by LEFT JOIN users v ON v.id=s.verified_by
                                      WHERE s.job_id=? ORDER BY s.key""", (j["id"],))]
        prev = c.execute("SELECT MAX(version) FROM reports WHERE job_id=? AND approver IS NOT NULL", (j["id"],)).fetchone()[0]
    it = j.get("intake") or {}
    am = j.get("amend")
    return dict(series=j["series"], sample=j["sample"], report_version=version, built_at=now(), software=dict(code=code_id(), schema=integrity.SCHEMA_VERSION),
                sections=secs, intake=dict(received_by=it.get("received_by"), arrived_at=it.get("arrived_at"), checked_by=it.get("checked_by")),
                signed_off_by=(j.get("signoff") or {}).get("by"), approver=j.get("approver"), approver_id=j.get("approver_id"),
                supersedes=dict(version=prev, reason=am["reason"]) if am and prev else None)

def freeze(j):
    """Build the PDF once and store it: every generated/approved report is an immutable, hash-verifiable version."""
    with db() as c: v = (c.execute("SELECT MAX(version) FROM reports WHERE job_id=?", (j["id"],)).fetchone()[0] or 0) + 1
    token = secrets.token_urlsafe(12)
    m = manifest(j, v); msha = integrity.sha(integrity.canon(m))
    pdf = build_pdf(j, v, request.host_url + "verify/" + token, manifest=(m, msha)).getvalue()
    sha = hashlib.sha256(pdf).hexdigest()
    with db() as c: c.execute("INSERT INTO reports(job_id,version,token,sha256,pdf,approver,approver_id,at,approver_user_id,generated_by,manifest,manifest_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         (j["id"], v, token, sha, pdf, j.get("approver"), j.get("approver_id"), now(), me() if j.get("approver") else None, me(), integrity.canon(m), msha))
    return v, sha

@app.get("/")
@auth.public
def index(): return send_from_directory(app.static_folder, "index.html")

@app.after_request
def no_stale_pages(r):
    """The page and its scripts are revalidated on every load (cheap: 304 when unchanged), so a browser never keeps running
    an old script after an update. API responses are never cached."""
    if request.path == "/" or request.path.startswith(("/static/", "/verify/")): r.headers["Cache-Control"] = "no-cache"
    elif request.path.startswith("/api/") and "Cache-Control" not in r.headers: r.headers["Cache-Control"] = "no-store"
    return r

# Searched text: record details plus what the request and work instruction say (tests, standard, engineer, dates) and the outcome
RQ, WK = (f"(SELECT data FROM sections WHERE job_id=jobs.id AND key='{k}')" for k in ("request", "work"))
SEARCHED = ("series", "sample", "customer", "rating", "verdict", "tested", f"json_extract({RQ},'$.tests')", f"json_extract({RQ},'$.criteria')",
            f"json_extract({RQ},'$.address')", f"json_extract({WK},'$.standard')", f"json_extract({WK},'$.engineer')",
            f"json_extract({WK},'$.start')", f"json_extract({WK},'$.completed')", "approver")
DAY = "COALESCE(NULLIF(tested,''), substr(created,1,10))"  # test date from a register, else the day the request was captured

@app.get("/api/jobs")
@auth.require("jobs.view")
def jobs():
    """One query for the whole list (no per-job lookups). Filters: q (text), stage (0-4, or 'h' for historical records),
    verdict ('comply', 'not', 'none'), from / to (YYYY-MM-DD)."""
    a = request.args; q, s, v = f"%{a.get('q', '').strip()}%", a.get("stage", ""), a.get("verdict", "")
    where, args = ["(" + " OR ".join(f"COALESCE({x},'') LIKE ?" for x in SEARCHED) + ")"], [q] * len(SEARCHED)
    if s == "h": where.append("archived=1")
    elif s.isdigit(): where.append("archived=0 AND stage=?"); args.append(int(s))
    if v in ("comply", "not", "none"):
        where.append({"comply": "verdict LIKE 'Complies%'", "not": "verdict='Does not comply'", "none": "verdict IS NULL"}[v])
    for k, op in (("from", ">="), ("to", "<=")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get(k, "")): where.append(f"{DAY} {op} ?"); args.append(a[k])
    cust = auth.is_customer()
    if cust: where.append("org_id IS NOT NULL AND org_id=? AND archived=0"); args.append(auth.current().get("org_id") or -1)
    sql = (f"SELECT id,series,sample,customer,rating,stage,approver,approver_id,created,updated,archived,verdict,tested,"
           f"(SELECT group_concat(key) FROM sections WHERE job_id=jobs.id AND data IS NOT NULL) AS secs,"
           + ",".join(f"(SELECT COUNT(*) FROM json_each(jobs.findings) WHERE json_extract(value,'$.level')='{l}') AS n_{l}" for l in ("pass", "warn", "fail"))
           + " FROM jobs WHERE " + " AND ".join(where) + " ORDER BY updated DESC, id DESC")
    with db() as c: rows = [dict(r) for r in c.execute(sql, args)]
    for j in rows:
        j["sections"] = (j.pop("secs") or "").split(",") if j.get("secs") else []
        j["counts"] = {l: j.pop("n_" + l) for l in ("pass", "warn", "fail")}
        j["stage_name"] = "Historical record" if j["archived"] else STAGES[j["stage"]]
    if cust: rows = [{k: j[k] for k in ("id", "series", "sample", "customer", "rating", "stage", "stage_name", "created", "updated", "verdict")}
                     | {"verdict": j["verdict"] if j["stage"] == 4 else None} for j in rows]
    return jsonify(rows)

def insert_job(c, b, event, archived=False):
    rq = {**(b.get("request") or {})}
    # never reuse the id of a deleted job: its audit entries keep pointing at that id for good
    nid = c.execute("SELECT MAX(x) + 1 FROM (SELECT MAX(id) x FROM jobs UNION ALL SELECT MAX(job_id) FROM audit UNION ALL SELECT 0)").fetchone()[0]
    cur = c.execute("INSERT INTO jobs(id,series,sample,customer,rating,data,created,updated,archived,verdict,tested,org_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (nid, b["series"], b["sample"], b["customer"].strip(), b["rating"].strip(), "{}", now(), now(),
                     int(archived), b.get("verdict") or None, b.get("tested") or None, b.get("org_id"), me()))
    integrity.write_section(c, cur.lastrowid, "request", rq, me(), event)
    log(c, cur.lastrowid, event, kind="job"); return cur.lastrowid

def iso_day(s):
    """A register's test date as YYYY-MM-DD when it can be read (2024-03-18, 18-03-2024, 18/03/2024, 18.03.2024); otherwise kept as written."""
    s = str(s or "").strip()
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y", "%d %b %Y"):
        try: return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError: pass
    return s

def register_verdict(s):
    """The register's own wording of the result, mapped onto the app's outcomes when it is clear."""
    t = str(s or "").strip()
    if not t: return None
    if re.search(r"\b(not|non|fail|failed|does not)\b", t, re.I): return "Does not comply"
    if re.search(r"\b(pass|passed|compl(y|ies|ied)|ok|satisfactory)\b", t, re.I): return "Complies"
    return t

@app.post("/api/jobs")
@auth.require("job.create")
def create():
    """New job for a customer's waiting request (customer_form_id): only a customer raises a request. With auto_ids the series
    number (and the sample code, if not typed) is allocated by the system, atomically. The laboratory's part of the intake
    (sheet 3) is recorded afterwards on the job page."""
    b = body(); auto = bool(b.get("auto_ids"))
    err = check_ids(b, auto=auto)
    if err: return jsonify(error=err), 400
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")  # numbering and insert in one write transaction: two people cannot get the same number
            f, req, _, rerr, _ = customer_request(c, b.get("customer_form_id"))
            if rerr: c.execute("ROLLBACK"); return jsonify(error=rerr), 400
            if auto:
                b["series"] = integrity.allocate(c, "series")
                if b["sample"] == "NA": b["sample"] = integrity.allocate(c, "sample")
            i = insert_job(c, dict(b, customer=req["customer"], rating=req["rating"], request={}, org_id=f["org_id"]),
                           "Job opened for the customer's request" + (f"; series {b['series']} and sample {b['sample']} assigned" if auto else ""))
            use_request(c, i, f, req)
        return jsonify(id=i, series=b["series"], sample=b["sample"]), 201
    except sqlite3.IntegrityError: return jsonify(error=["Series number already exists"]), 409

@app.post("/api/jobs/from-file")
@auth.require("job.create")
def create_from_file():
    """New job for a customer's waiting request (customer_form_id), with its test data from a file: the series number comes
    from the file (or the form, if typed). The request itself is always the customer's; a request section in the file is ignored."""
    b = body(); name, raw = upload(b)
    with db() as c: f, req, _, rerr, _ = customer_request(c, b.get("customer_form_id"))
    if rerr: return jsonify(error=rerr), 400
    typed = str(b.get("series") or "").strip().upper() or None
    content, kind, notes, used = excel_routes.load_any(name, raw, typed)
    if not isinstance(content, dict) or not content: return jsonify(error=["No test data found in this file"]), 400
    content.pop("request", None); wk = content.get("work") or {}
    ids = (content.get("ids") or {}).get("work") or [None, None]
    series = typed or str(wk.get("series") or ids[0] or "").strip().upper()
    new = dict(series=series, sample=str(wk.get("sample") or ids[1] or "").strip().upper(), customer=req["customer"], rating=req["rating"],
               request={}, org_id=f["org_id"])
    if not series: return jsonify(error=["This file has no test series number. Type it in the form, then drop the file again."]), 400
    if new["sample"] and not re.fullmatch(SAMPLE_RE, new["sample"]): new["sample"] = ""  # a misread sample code must not block the job
    err = check_ids(new)
    if err: return jsonify(error=err + ["Type the correct test series number in the form and drop the file again."]), 400
    try:
        with db() as c:
            if c.execute("SELECT status FROM customer_forms WHERE id=?", (f["id"],)).fetchone()[0] != "received": return jsonify(error=["This customer request was taken meanwhile"]), 409
            i = insert_job(c, new, f"Job opened for the customer's request, test data from {name}"); use_request(c, i, f, req)
    except sqlite3.IntegrityError: return jsonify(error=[f"Series {series} already exists. Open that job, or type a different series number."]), 409
    r = apply_import(getjob(i), i, name, content, kind, notes, raw, templates=used)
    if isinstance(r, tuple): return jsonify(id=i, warning=r[0].get_json().get("error")), 201  # job exists; import problem shown on its page
    return jsonify(id=i, **r.get_json()), 201

@app.post("/api/read-scan")
@auth.require("job.create")
def read_scan():
    """AI reading of a customer request form or work instruction before the job exists (pre-fills the New request form)."""
    if not scan_on(): return scan_off()
    b = body(); k = b.get("section") if b.get("section") in ("request", "work") else "request"
    name, raw = upload(b)
    if len(raw) > importers.MAX_BYTES: raise importers.ImportError_("File is too large (20 MB maximum)")
    with db() as c:
        out = vision.extract(c, raw, sniff(raw), k, NAMES[k], load_demo().get(k, {}), app.config.get("VISION_TRANSPORT"),
                             sha=hashlib.sha256(raw).hexdigest(), cache_path=AI_CACHE, fresh=bool(b.get("fresh")))
    return jsonify(out)

@app.get("/api/jobs/<int:i>")
@auth.require("jobs.view")
def one(i):
    j = getjob(i)
    return jsonify(customer_view(j) if auth.is_customer() else j)

def partial_list(i):
    with db() as c: return [dict(version=r[0], at=r[1], sha256=r[2]) for r in c.execute("SELECT version, at, sha256 FROM partials WHERE job_id=? ORDER BY version DESC", (i,))]

def customer_view(j):
    """What a customer sees of their own job: progress per test and the released report. No values, findings, files or
    names of laboratory staff (values only appear once a report section is approved)."""
    rels = [r for r in j["reports"] if r["approver"]]
    rel = rels[0] if rels else None
    reasons = {a["from_version"]: a["reason"] for a in j["amendments"]}
    versions = [dict(version=r["version"], at=r["at"], token=r["token"], sha256=r["sha256"], superseded=n > 0,
                     amendment_reason=reasons.get(r["version"]) if n > 0 else None) for n, r in enumerate(rels)]
    return dict(id=j["id"], series=j["series"], sample=j["sample"], customer=j["customer"], rating=j["rating"], created=j["created"], versions=versions,
                amendment_open=bool(j.get("amend")), amendment_reason=(j.get("amend") or {}).get("reason"),
                partials=partial_list(j["id"]),
                stage=j["stage"], stage_name=j["stage_name"], released=bool(rel), verdict=j.get("verdict") if rel else None,
                progress=[{k: p[k] for k in ("key", "name", "state")} for p in j["progress"]], counts=j["counts"],
                report=dict(version=rel["version"], token=rel["token"], at=rel["at"], sha256=rel["sha256"]) if rel else None)

# ---- data collection: JSON, CSV, Excel, SQLite database
@app.post("/api/jobs/<int:i>/import")
@auth.require("data.write")
def imp(i):
    j = getjob(i); b = body(); notes = []
    if locked(j): return locked(j)
    bay = bay_of(b)
    if isinstance(b.get("content"), dict):
        name, content, kind = str(b.get("filename") or "upload"), b["content"], "json"; raw = integrity.canon(content).encode()
    else:
        name, raw = upload(b); content, kind, notes, used = excel_routes.load_any(name, raw, j["series"])
        if b.get("section"): content, notes = for_test(content, b["section"]), notes + [f"uploaded for {NAMES.get(b['section'], b['section'])}"]
        return apply_import(j, i, name, content, kind, notes, raw, bay, templates=used)
    if b.get("section"): content = for_test(content, b["section"])
    return apply_import(j, i, name, content, kind, notes, raw, bay)

def test_key(k):
    """A test a file can be uploaded for: one of the job's documents (not the customer's request) or an additional log sheet."""
    if k not in NAMES and k != "other" or k == "request": raise importers.ImportError_("Choose the test this file belongs to")
    return k

def for_test(content, k):
    """Only what a file brings for the test it was uploaded for (nothing is allocated to other tests by itself)."""
    k = test_key(k)
    if not isinstance(content, dict) or k not in content:
        raise importers.ImportError_(f"This file holds no data for {NAMES.get(k, 'an additional log sheet')}; upload it from the row of the test it belongs to")
    out = {k: content[k]}
    ids = (content.get("ids") or {}) if isinstance(content.get("ids"), dict) else {}
    if k in ids: out["ids"] = {k: ids[k]}
    return out

MIMES = {"json": "application/json", "csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "sqlite": "application/vnd.sqlite3"}

def apply_import(j, i, name, content, kind, notes, raw, bay=None, templates=None):
    """Write the imported sections (also used when a job is created from a file). The file is kept byte-for-byte with its
    SHA-256; each section it brings becomes a new revision of that section only, so other people's sections are untouched."""
    ok = set(NAMES) | {"ids", "other"}
    if not isinstance(content, dict) or not content or not set(content) <= ok:
        return jsonify(error=["Unrecognised file: expected sections " + ", ".join(NAMES)]), 400
    bad = [k for k, v in content.items() if not isinstance(v, dict)]
    if bad: return jsonify(error=[f"Section '{k}' must contain named fields" for k in bad]), 400
    if "request" in content:  # the request is the customer's own (raised online); a data file never changes it
        content = {k: v for k, v in content.items() if k != "request"}; notes = list(notes) + ["customer request section in the file ignored"]
        if not content: return jsonify(error=["This file holds only a customer request: the customer raises the request online"]), 400
    sha = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    if isinstance(content.get("other"), dict):  # additional log sheets: cleaned, added alongside any already on the job
        content["other"] = {str(k): clean_other(v) for k, v in content["other"].items() if isinstance(v, dict)}
    brought = {k: (sorted(map(str, v)) if k in ("ids", "other") else True) for k, v in content.items() if k != "request"}
    label = {"json": "JSON", "csv": "CSV", "xlsx": "Excel", "sqlite": "database"}[kind]
    event = f"Imported {label} file {name} ({', '.join(content)})" + (f" [{'; '.join(notes)}]" if notes else "")
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            why = write_check(c, i, list(content))
            if why: return refuse(c, i, *why)
            fid = integrity.store_file(c, i, name, raw, MIMES[kind], me())
            imp_id = c.execute("INSERT INTO imports(job_id,source,kind,sha256,at,sections,user_id,file_id) VALUES(?,?,?,?,?,?,?,?)",
                               (i, name, kind, sha, now(), json.dumps(brought), me(), fid)).lastrowid
            for k, v in content.items():
                if k in integrity.MERGED: v = {**(integrity.read_section(c, i, k) or {}), **v}  # read and write in one transaction
                integrity.write_section(c, i, k, v, me(), f"Imported from {name}", file_id=fid, import_id=imp_id, template_id=(templates or {}).get(k))
            after_change(c, i, event + f" (file SHA-256 {integrity.sha(raw)[:12]}...)")
            notify.on_uploaded(c, i, list(content))
    except sqlite3.IntegrityError: return jsonify(error=["Duplicate file - identical content already imported for this job"]), 409
    return jsonify(ok=True, kind=kind, sections=list(content), notes=notes)

@app.delete("/api/jobs/<int:i>/imports/<int:imp>")
@auth.require("data.write")
def remove_import(i, imp):
    """Undo one imported data file: the documents it brought in are taken out of the job (the customer request stays, and
    a document edited by hand since then goes too). The same file can then be imported again. Checks and report are redone.
    The stored file and every earlier revision of the sections stay in the history."""
    j = getjob(i)
    if locked(j): return locked(j)
    if j["stage"] >= 3: return jsonify(error=["A report has been generated from this data. Withdraw the report first, then remove the file."]), 409
    row = next((x for x in j["imports"] if x["id"] == imp), None)
    if not row: return jsonify(error=["This file is not part of the job"]), 404
    secs = row["sections"]
    if secs is None:  # imported before the app recorded what each file brought in
        if len(j["imports"]) > 1: return jsonify(error=["This file was imported before the app recorded which documents it contained. "
                                                        "Remove its documents one by one under Sources instead."]), 409
        secs = {k: True for k in j["data"] if k != "request"}  # the only import: everything but the request came from it or was typed
    what = ', '.join(name(k) for k in secs if k != 'request') or 'no documents'
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        why = write_check(c, i, [k for k in secs if k != "request"])
        if why: return refuse(c, i, *why)
        for k, sub in secs.items():
            if k == "request": continue
            if sub is True: integrity.write_section(c, i, k, None, me(), f"Removed with imported file {row['source']}")
            else:
                cur = integrity.read_section(c, i, k)
                if isinstance(cur, dict):
                    for x in sub: cur.pop(x, None)
                    integrity.write_section(c, i, k, cur or None, me(), f"Removed with imported file {row['source']}")
        c.execute("DELETE FROM imports WHERE id=? AND job_id=?", (imp, i))
        after_change(c, i, f"Imported file {row['source']} removed ({what})")
    return jsonify(ok=True, stage=getjob(i, False)["stage"])

@app.post("/api/jobs/<int:i>/section")
@auth.require("data.write")
def section(i):
    """Save one section typed or corrected by hand (also used to accept an AI reading after review).
    revision: the section revision the editor started from. If someone changed it since, nothing is saved (409)."""
    j = getjob(i); b = body(); k = b.get("section")
    if locked(j): return locked(j)
    if k == "other": return save_other(j, b)
    if k not in set(NAMES) | {"ids"} or not isinstance(b.get("data"), dict): return jsonify(error=["Choose a section and provide its fields"]), 400
    how = 'entered from AI reading of ' + str(b['source'])[:120] + ' after review' if b.get('source') else 'edited by hand'
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            why = write_check(c, i, [k])
            if why: return refuse(c, i, *why)
            integrity.write_section(c, i, k, b["data"], me(), f"{name(k)} {how}", expect=expected(c, i, k, b), bay=bay_of(b))
            after_change(c, i, f"{name(k)} {how}")
            notify.on_uploaded(c, i, [k])
    except Conflict as e: return conflict(e)
    return jsonify(ok=True)

def expected(c, i, k, b):
    """The revision an edit must start from. A section that already exists cannot be overwritten blind."""
    rev = b.get("revision")
    if isinstance(rev, int) and not isinstance(rev, bool): return rev
    row = c.execute("SELECT * FROM sections WHERE job_id=? AND key=?", (i, k)).fetchone()
    if row: raise Conflict(k, row)
    return 0

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
    return dict(title=txt(o.get("title")) or "Supplementary test record", fields=fields, tables=tables)

def save_other(j, b):
    if not isinstance(b.get("data"), dict): return jsonify(error=["Provide the sheet's fields"]), 400
    i = j["id"]; sheet = clean_other(b["data"])
    how = f"entered from AI reading of {str(b['source'])[:120]} after review" if b.get("source") else "edited by hand"
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            exp = expected(c, i, "other", b)
            others = integrity.read_section(c, i, "other") or {}
            key = str(b.get("key") or "")
            if not re.fullmatch(r"x\d{1,4}", key):
                n = 1
                while f"x{n}" in others: n += 1
                key = f"x{n}"
            others[key] = sheet
            integrity.write_section(c, i, "other", others, me(), f"Supplementary test record '{sheet['title']}' {how}", expect=exp)
            after_change(c, i, f"Supplementary test record '{sheet['title']}' {how}")
    except Conflict as e: return conflict(e)
    return jsonify(ok=True, key=key)

@app.delete("/api/jobs/<int:i>/section/<k>")
@auth.require("data.write")
def remove_section(i, k):
    """Detach one document's data from the job; the checks and the report must be redone. The customer request stays.
    The removed data stays in the section history."""
    j = getjob(i)
    if locked(j): return locked(j)
    if k.startswith("other:"):
        key = k[6:]
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            others = integrity.read_section(c, i, "other") or {}
            if key not in others: return jsonify(error=["This log sheet is not part of the job"]), 404
            title = others.pop(key).get("title", "Supplementary test record")
            integrity.write_section(c, i, "other", others or None, me(), f"Supplementary test record '{title}' removed")
            after_change(c, i, f"Supplementary test record '{title}' removed from the job")
        return jsonify(ok=True)
    if k not in set(NAMES) - {"request"} | {"ids"}: return jsonify(error=["This document cannot be removed"]), 400
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        why = write_check(c, i, [k])
        if why: return refuse(c, i, *why)
        if integrity.write_section(c, i, k, None, me(), f"{name(k)} removed") is None:
            return jsonify(error=["This document is not part of the job"]), 404
        after_change(c, i, f"{name(k)} removed from the job")
    return jsonify(ok=True)

@app.get("/api/jobs/<int:i>/export/<fmt>")
@auth.require("data.export")
def export(i, fmt):
    j = getjob(i, False); return send_export(j["data"], fmt, j["series"])

@app.get("/api/template/<fmt>")
@auth.require("data.export")
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
@auth.require("register.import")
def register():
    name, raw = upload(body()); recs, table = importers.load_register(name, raw); made, skipped = [], []
    for n, r in enumerate(recs, 1):
        r["series"], r["sample"] = r["series"].upper(), r["sample"].upper()
        err = check_ids(r)
        if err: skipped.append(dict(row=n, series=r["series"], reason="; ".join(err))); continue
        r["request"] = {k: r[k] for k in REQ_KEYS if r.get(k)}
        r["verdict"], r["tested"] = register_verdict(r.get("verdict")), iso_day(r.get("tested")) or None
        try:  # a historical record: searchable, but not a job in progress (it does not appear in the pipeline or work queue)
            with db() as c: made.append(insert_job(c, r, f"Historical record imported from existing register {name}", archived=True))
        except sqlite3.IntegrityError: skipped.append(dict(row=n, series=r["series"], reason="Series number already exists"))
    return jsonify(created=len(made), ids=made, skipped=skipped, table=table, rows=len(recs))

@app.get("/api/register-template.csv")
@auth.require("register.import")
def register_template():
    rows = ("series,sample,customer,rating,address,serial,tests,standard,witness,conformity,test date,result\n"
            "CPRIBLRSCL25T1601,HVD25S0801,Example Transformers Pvt Ltd,100 kVA / 11 kV / 433 V,\"Plot 1, Industrial Area, Bengaluru\",2201,Type test,IS 1180,,,2025-01-14,Complies\n")
    return send_file(io.BytesIO(rows.encode("utf-8-sig")), mimetype="text/csv", as_attachment=True, download_name="ALETHEIA_register_template.csv")

# ---- source documents (scans / photographs kept as evidence) and optional AI reading
# Scanning (AI reading of photographed sheets) is an optional fallback since Excel became the primary input (NEXT_STEPS.md 8).
scan_on = lambda: app.config.get("FEATURE_SCAN", os.environ.get("ALETHEIA_FEATURE_SCAN", "0") == "1")
def scan_off(): return jsonify(error=["Scanning (AI reading of sheets) is turned off on this server; set ALETHEIA_FEATURE_SCAN=1 to enable it"]), 404

def sniff(raw):
    if raw.startswith(b"%PDF-"): return "application/pdf"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if raw.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP": return "image/webp"
    raise importers.ImportError_("Source documents must be PDF, PNG, JPEG or WebP")

@app.post("/api/jobs/<int:i>/sources")
@auth.require("data.write")
def add_source(i):
    j = getjob(i, False)
    if locked(j): return locked(j)
    b = body(); sec = test_key(b.get("section")); name, raw = upload(b)
    if len(raw) > importers.MAX_BYTES: raise importers.ImportError_("File is too large (20 MB maximum)")
    try:
        with db() as c: return jsonify(id=insert_source(c, i, name, raw, sec)), 201
    except sqlite3.IntegrityError: return jsonify(error=["This document is already attached to the job"]), 409

def insert_source(c, i, name, raw, section=None):
    """Store a scanned sheet with its fingerprint, attached to one test. Raises IntegrityError if the same file is already
    attached to the job."""
    mime = sniff(raw); sha = hashlib.sha256(raw).hexdigest()
    cur = c.execute("INSERT INTO sources(job_id,filename,mime,sha256,content,at,user_id,section) VALUES(?,?,?,?,?,?,?,?)", (i, name, mime, sha, raw, now(), me(), section))
    log(c, i, f"Source document attached to {NAMES.get(section, 'the job') if section else 'the job'}: {name} (SHA-256 {sha[:12]}...)", kind="data"); return cur.lastrowid

def source_row(sid):
    with db() as c: r = c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    if not r: abort(404)
    getjob(r["job_id"], False)  # same visibility rule as the job itself
    return r

@app.get("/api/sources/<int:sid>")
@auth.require("sources.view")
def get_source(sid):
    r = source_row(sid); resp = send_file(io.BytesIO(r["content"]), mimetype=r["mime"], download_name=r["filename"])
    resp.headers["X-Content-Type-Options"] = "nosniff"; return resp

@app.delete("/api/sources/<int:sid>")
@auth.require("data.write")
def del_source(sid):
    r = source_row(sid)
    if locked(getjob(r["job_id"], False)): return locked(getjob(r["job_id"], False))
    with db() as c: c.execute("DELETE FROM sources WHERE id=?", (sid,)); log(c, r["job_id"], f"Source document removed: {r['filename']}", kind="data")
    return jsonify(ok=True)

@app.post("/api/sources/<int:sid>/extract")
@auth.require("data.write")
def extract(sid):
    """Ask Gemini for a proposal for one section. Nothing is saved until the engineer reviews it and posts it to /section."""
    if not scan_on(): return scan_off()
    r = source_row(sid); b = body(); k = b.get("section")
    if k not in NAMES and k != "other": return jsonify(error=["Choose which document this is"]), 400
    example = vision.OTHER_LAYOUT if k == "other" else load_demo().get(k, {})
    with db() as c:
        out = vision.extract(c, r["content"], r["mime"], k, NAMES.get(k, "Other laboratory log sheet"), example, app.config.get("VISION_TRANSPORT"),
                             sha=r["sha256"], cache_path=AI_CACHE, fresh=bool(b.get("fresh")),
                             part=b.get("part") if isinstance(b.get("part"), int) else None)
        log(c, r["job_id"], f"AI reading {'reused from cache' if out['cached'] else 'requested'} for {r['filename']} as {NAMES.get(k, 'other log sheet')} (proposal only, not saved)", kind="data")
    return jsonify(out)

# ---- validate, generate, approve
@app.post("/api/jobs/<int:i>/validate")
@auth.require("data.check")
def val(i):
    j = getjob(i)
    if locked(j): return locked(j)
    F, _ = safe_validate(j["data"], j.get("plan")); fails = sum(f["level"] == "fail" for f in F); blocks = len(blocking(F))
    done = {(f["check"], f["detail"]): f.get("note") for f in j["findings"] if f.get("reviewed")}  # unchanged items keep their review
    for f in F:
        if f["level"] in ("warn", "fail") and not f.get("blocks") and (f["check"], f["detail"]) in done:
            f["reviewed"] = True; f.update({"note": done[(f["check"], f["detail"])]} if done[(f["check"], f["detail"])] else {})
    # only data errors hold the job back; a sample that fails a requirement goes on to a "does not comply" report
    save(i, findings=F, stage=max(j["stage"], 2) if not blocks else min(j["stage"], 1), verdict=verdict_of(F))
    with db() as c: log(c, i, f"Validation run: {sum(f['level'] == 'pass' for f in F)} pass, {sum(f['level'] == 'warn' for f in F)} warn, {fails} fail"
                         + (f" ({blocks} data error{'s' if blocks > 1 else ''} to correct)" if blocks else ""), kind="check")
    return jsonify(findings=F)

@app.post("/api/jobs/<int:i>/review")
@auth.require("data.check")
def review(i):
    """Mark one flagged check as reviewed, or confirm a failed requirement as a genuine result (it is then reported as not met).
    Data errors (blocks) cannot be reviewed: they must be corrected."""
    j = getjob(i); b = body(); F = j["findings"]; n = b.get("index")
    if locked(j): return locked(j)
    if not isinstance(n, int) or not 0 <= n < len(F): return jsonify(error=["No such check"]), 400
    if F[n].get("blocks"): return jsonify(error=["This is a data error and cannot be marked as reviewed: correct the data and run the checks again"]), 409
    if F[n]["level"] not in ("warn", "fail"): return jsonify(error=["Only flagged items need review"]), 400
    F[n]["reviewed"] = bool(b.get("reviewed", True))
    note = re.sub(r"\s+", " ", str(b.get("note") or "")).strip()[:500]
    if F[n]["reviewed"] and note: F[n]["note"] = note
    elif not F[n]["reviewed"]: F[n].pop("note", None)
    save(i, findings=F)
    what = ("Failure confirmed" if F[n]["reviewed"] else "Failure confirmation withdrawn") if F[n]["level"] == "fail" else ("Reviewed" if F[n]["reviewed"] else "Review withdrawn")
    with db() as c: log(c, i, f"{what}: {F[n]['check']} - {F[n]['detail'][:90]}" + (f" (note: {note})" if F[n]["reviewed"] and note else ""), kind="check")
    return jsonify(findings=F)

@app.post("/api/jobs/<int:i>/generate")
@auth.require("report.generate")
def gen(i):
    j = getjob(i)
    if locked(j): return locked(j)
    if j["stage"] < 2: return jsonify(error=["Run the checks and correct any data errors before generating"]), 409
    left = [f["check"] for f in j["findings"] if f["level"] in ("warn", "fail") and not f.get("reviewed") and not f.get("advisory")]
    if left: return jsonify(error=[f"Review every flagged item before the report is built ({len(left)} left)"]), 409
    if j["signoff_blockers"]: return jsonify(error=["Every test must be verified (or marked not applicable) first:"] + j["signoff_blockers"]), 409
    if not j["signoff"]: return jsonify(error=["An administrator must approve the job (every test verified) before the report is built"]), 409
    t = dt.datetime.now()
    try: v, sha = freeze(j)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=[f"The report could not be built from this data ({type(e).__name__}: {e}). Correct the data and run the checks again."]), 400
    ms = int((dt.datetime.now() - t).total_seconds() * 1000)
    save(i, stage=max(j["stage"], 3))
    with db() as c:
        log(c, i, f"Report generated in {ms} ms (version {v}, SHA-256 {sha[:12]}...)", kind="report")
        notify.on_ready_to_approve(c, i)
    return jsonify(ms=ms, version=v, sha256=sha)

@app.post("/api/jobs/<int:i>/approve")
@auth.require("report.approve")
def approve(i):
    """Sign off and release. The administrator signing is the signed-in account: name and employee ID come from the user
    record and are printed on the report ("Approved by"). They re-enter their password to sign. The administrator who
    approved the job and generated the report may sign it off; an administrator cannot enter, check or verify data at all."""
    j = getjob(i); b = body(); u = auth.current()
    if j["stage"] < 3: return jsonify(error=["Generate the report before signing it off"]), 409
    if not u.get("employee_id"): return jsonify(error=["Your account has no employee ID; ask an administrator to add it"]), 400
    gaps = workflow.intake_complete(j)
    if gaps: return jsonify(error=gaps + ["Complete the intake (Intake details on the job page) before release: the report is a legal document"]), 409
    if app.config.get("REAUTH_ON_RELEASE", True) and not auth.reauth(b.get("password")):
        with db() as c: log(c, i, "Release signature refused: password not confirmed", kind="denied")
        return jsonify(error=["Re-enter your password to sign the release"]), 403
    person = lambda s: re.sub(r"[^a-z]", "", str(s or "").lower())
    if person(u["full_name"]) and person(u["full_name"]) == person((j["data"].get("work") or {}).get("engineer")):
        return jsonify(error=["The test engineer who prepared this report cannot also sign it off; a second person must sign"]), 403
    name, emp = u["full_name"], u["employee_id"]
    try: v, sha = freeze(dict(j, approver=name, approver_id=emp, stage=4))
    except Exception as e:  # noqa: BLE001
        return jsonify(error=[f"The report could not be built ({type(e).__name__}: {e}); nothing was released"]), 400
    with db() as c:
        done = now()
        c.execute("UPDATE jobs SET stage=4, approver=?, approver_id=?, amend=NULL, updated=?, completed_at=COALESCE(completed_at, ?) WHERE id=?",
                  (name, emp, done, done, i))
        notify.on_released(c, i, v)
        if j.get("amend"):
            c.execute("UPDATE amendments SET closed_at=?, new_version=? WHERE job_id=? AND closed_at IS NULL", (now(), v, i))
        log(c, i, f"Approved by {signed(name, emp)}: report signed off and released (version {v}, SHA-256 {sha[:12]}...)"
                  + (f"; supersedes the earlier release (amendment: {j['amend']['reason']})" if j.get("amend") else ""), kind="approve")
    return jsonify(ok=True, version=v)

@app.post("/api/jobs/<int:i>/amend")
@auth.require("report.amend")
def amend(i):
    """Correct a released report by superseding it (NEXT_STEPS.md 6.5). An administrator and a second administrator sign the
    reason; only the named tests reopen; the usual upload, verification, approval and sign-off give version n+1. The released version
    stays stored, downloadable and verifiable, marked superseded once the new one is released."""
    j = getjob(i); b = body(); u = auth.current()
    if not j["released"]: return jsonify(error=["Only a released report is amended; an unreleased job is simply corrected"]), 409
    reason = re.sub(r"\s+", " ", str(b.get("reason") or "")).strip()
    keys = [k for k in (b.get("sections") or []) if isinstance(k, str)]
    err = ([] if len(reason) >= 10 else ["Give the reason for the amendment (it is printed on the new version)"]) + \
          ([] if keys else ["Name the tests that must be corrected"]) + \
          [f"Unknown test: {k}" for k in keys if k not in NAMES and k not in ("ids", "other")]
    if err: return jsonify(error=err), 400
    if not auth.reauth(b.get("password")): return jsonify(error=["Re-enter your password to sign the amendment"]), 403
    second, why = auth.second_signer((b.get("second") or {}).get("username"), (b.get("second") or {}).get("password"), "admin")
    if not second: return jsonify(error=[why]), 403
    rel = next(r for r in j["reports"] if r["approver"])
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        am = dict(reason=reason, sections=keys, opened_by=u["full_name"], second_signer=second["full_name"], opened_at=now(), from_version=rel["version"])
        c.execute("UPDATE jobs SET amend=?, stage=1, approver=NULL, approver_id=NULL, findings='[]', verdict=NULL, signed_off_by=NULL, signed_off_at=NULL, updated=? WHERE id=?",
                  (json.dumps(am), now(), i))
        c.execute("INSERT INTO amendments(job_id,from_version,reason,sections,opened_by,second_signer,opened_at) VALUES(?,?,?,?,?,?,?)",
                  (i, rel["version"], reason, json.dumps(keys), u["id"], second["id"], now()))
        for k in keys:
            if k == "request":  # the intake must be read back against the original again
                it = workflow.loads(c.execute("SELECT intake FROM jobs WHERE id=?", (i,)).fetchone()[0], {})
                c.execute("UPDATE jobs SET intake=? WHERE id=?", (json.dumps(dict(it, checked_by=None, checked_at=None)), i)); continue
            if c.execute("SELECT 1 FROM sections WHERE job_id=? AND key=?", (i, k)).fetchone():
                integrity.set_state(c, i, k, "returned", u["id"], f"Reopened by amendment: {reason}", note=f"Amendment: {reason}")
        log(c, i, f"Amendment of version {rel['version']} opened by {u['full_name']} with {second['full_name']} as second signer; "
                  f"tests reopened: {', '.join(name(k) for k in keys)}; reason: {reason}", kind="approve")
    return jsonify(ok=True, from_version=rel["version"])

def latest(i):
    with db() as c: return c.execute("SELECT * FROM reports WHERE job_id=? ORDER BY version DESC LIMIT 1", (i,)).fetchone()

@app.get("/api/jobs/<int:i>/report.pdf")
@auth.require("report.view")
def pdf(i):
    j = getjob(i, False); r = latest(i) if j["stage"] >= 3 else None
    if auth.is_customer():  # the newest released version, or an earlier one asked for by number
        with db() as c:
            q = "SELECT * FROM reports WHERE job_id=? AND approver IS NOT NULL" + (" AND version=?" if request.args.get("v", "").isdigit() else "") + " ORDER BY version DESC LIMIT 1"
            r = c.execute(q, (i, int(request.args["v"])) if request.args.get("v", "").isdigit() else (i,)).fetchone()
        if not r: return jsonify(error=["The report has not been released yet"]), 409
    elif request.args.get("v", "").isdigit():
        with db() as c: r = c.execute("SELECT * FROM reports WHERE job_id=? AND version=?", (i, int(request.args["v"]))).fetchone()
    if not r: return jsonify(error=["Report not generated yet"]), 409
    return send_file(io.BytesIO(r["pdf"]), mimetype="application/pdf", as_attachment=request.args.get("dl") == "1", download_name=f"TestReport_{j['series']}_v{r['version']}.pdf")

@app.get("/api/verify/<token>")
@auth.public
def verify(token):
    with db() as c:
        r = c.execute("SELECT * FROM reports WHERE token=?", (token,)).fetchone()
        if not r: return jsonify(error=["Unknown report code"]), 404
        j = c.execute("SELECT series,sample,customer,stage FROM jobs WHERE id=?", (r["job_id"],)).fetchone()
        newest = c.execute("SELECT MAX(version) FROM reports WHERE job_id=?", (r["job_id"],)).fetchone()[0]
        later = c.execute("SELECT MIN(version) FROM reports WHERE job_id=? AND approver IS NOT NULL AND version>?", (r["job_id"], r["version"])).fetchone()[0]
        am = c.execute("SELECT reason, opened_at FROM amendments WHERE job_id=? AND from_version=? ORDER BY id DESC LIMIT 1", (r["job_id"], r["version"])).fetchone()
    intact = hashlib.sha256(r["pdf"]).hexdigest() == r["sha256"]
    released = bool(r["approver"])
    current = (released and later is None) or (not released and r["version"] == newest and j["stage"] in (3,))
    m = json.loads(r["manifest"]) if r["manifest"] else None
    return jsonify(series=j["series"], sample=j["sample"], customer=j["customer"], version=r["version"], sha256=r["sha256"], generated=r["at"],
                   approver=r["approver"], approver_id=r["approver_id"], intact=intact, current=current, approved=released and later is None,
                   superseded_by=later, amendment=dict(reason=am["reason"], opened_at=am["opened_at"]) if am else None,
                   manifest_sha256=r["manifest_sha256"], manifest_ok=(integrity.sha(r["manifest"]) == r["manifest_sha256"]) if r["manifest"] else None,
                   sections=[{k: s.get(k) for k in ("test", "revision", "data_sha256", "file_sha256", "template", "uploaded_by", "verified_by")} for s in m["sections"] if s["key"] != "request"] if m else None)

@app.get("/api/verify/<token>/report.pdf")
@auth.public
def verify_pdf(token):
    """The customer's copy: anyone holding the link (or the QR code) can download a released version. A superseded version
    is still handed out (it is part of the record); the verification page says it was superseded and why."""
    with db() as c:
        r = c.execute("SELECT * FROM reports WHERE token=?", (token,)).fetchone()
        if not r: return jsonify(error=["Unknown report code"]), 404
        j = c.execute("SELECT series,stage FROM jobs WHERE id=?", (r["job_id"],)).fetchone()
        newest = c.execute("SELECT MAX(version) FROM reports WHERE job_id=?", (r["job_id"],)).fetchone()[0]
    if not r["approver"]: return jsonify(error=["This version was never released (a draft)"]), 409
    resp = send_file(io.BytesIO(r["pdf"]), mimetype="application/pdf", as_attachment=True,
                     download_name=f"TestReport_{j['series']}_v{r['version']}{'' if r['version'] == newest and j['stage'] == 4 else '_SUPERSEDED'}.pdf")
    return resp

@app.get("/verify/<token>")
@auth.public
def verify_page(token): return send_from_directory(app.static_folder, "index.html")

@app.post("/api/jobs/<int:i>/edit")
@auth.require("job.edit")
def edit(i):
    """Correct the job's identifiers (series, sample code) before release. The customer's details come from their request and
    are not edited by the laboratory. A generated (unreleased) report is rebuilt as a new version."""
    j = getjob(i); b = dict(body(), customer=j["customer"], rating=j["rating"]); err = check_ids(b)
    if locked(j): return locked(j)
    if err: return jsonify(error=err), 400
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE jobs SET series=?, sample=?, updated=? WHERE id=?", (b["series"], b["sample"], now(), i))
    except sqlite3.IntegrityError: return jsonify(error=["Series number already exists"]), 409
    note = ""
    if j["stage"] >= 3:
        try: note = f" - report rebuilt as version {freeze(getjob(i))[0]}"
        except Exception: save(i, stage=1, findings=[]); note = " - report withdrawn, run the checks again"  # noqa: BLE001
    with db() as c: log(c, i, "Record details edited" + note, kind="job")
    return jsonify(ok=True)

@app.post("/api/jobs/<int:i>/discard")
@auth.require("report.approve")
def discard(i):
    """Withdraw a generated report that has not been released; record and data are kept (stage returns to 'Validated').
    Stored versions stay verifiable as superseded. A released report cannot be withdrawn: it is superseded by an amendment."""
    j = getjob(i)
    if locked(j): return jsonify(error=["A released report cannot be withdrawn or deleted. Open an amendment to supersede it."]), 409
    if j["stage"] < 3: return jsonify(error=["No generated report to delete"]), 409
    save(i, stage=2, approver=None, approver_id=None)
    with db() as c: log(c, i, "Generated report withdrawn (record kept)", kind="report")
    return jsonify(ok=True)

@app.delete("/api/jobs/<int:i>")
@auth.require("job.delete")
def delete(i):
    """Delete a record that never had a released report (a job created by mistake). Released records are kept for good:
    the database refuses to delete them even if this check were bypassed."""
    getjob(i, False)
    with db() as c:
        if c.execute("SELECT 1 FROM reports WHERE job_id=? AND approver IS NOT NULL", (i,)).fetchone():
            return jsonify(error=["A report for this record has been released. It is kept for as long as records are retained, "
                                  "so the customer's copy can always be verified."]), 409
        series = c.execute("SELECT series FROM jobs WHERE id=?", (i,)).fetchone()[0]
        c.execute("DELETE FROM jobs WHERE id=?", (i,))  # first, so the verified-section lock (which needs the job) lets go
        for t in ("imports", "sources", "reports", "sections", "section_history", "files", "assignments"): c.execute(f"DELETE FROM {t} WHERE job_id=?", (i,))
        log(c, None, f"Unreleased record {series} (job {i}) deleted with its data, files and report drafts; its audit entries are kept", kind="admin")
    return jsonify(ok=True)

@app.get("/api/audit")
@auth.require("audit.read")
def audit_log():
    """The audit trail across all jobs. Filters: job (series or id), user (name or username), kind, from / to (YYYY-MM-DD)."""
    a = request.args; where, args = ["1=1"], []
    if a.get("job", "").strip():
        t = a["job"].strip(); where.append("(j.series LIKE ? OR a.job_id=?)"); args += [f"%{t}%", int(t) if t.isdigit() else -1]
    if a.get("user", "").strip(): where.append("a.actor LIKE ?"); args.append(f"%{a['user'].strip()}%")
    if a.get("kind", "").strip(): where.append("COALESCE(a.kind,'event')=?"); args.append(a["kind"].strip())
    for k, op in (("from", ">="), ("to", "<=")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get(k, "")): where.append(f"substr(a.at,1,10) {op} ?"); args.append(a[k])
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT a.id,a.job_id,j.series,a.event,a.at,a.actor,a.role,a.ip,a.kind FROM audit a LEFT JOIN jobs j ON j.id=a.job_id "
                                           "WHERE " + " AND ".join(where) + " ORDER BY a.id DESC LIMIT 501", args)]
    return jsonify(rows=rows[:500], more=len(rows) > 500)

# ---- workflow: per-section verification, assignment, sign-off (NEXT_STEPS.md section 3)
def section_action(i, k, state, verb, need_reason=False, need_data=True, allowed_from=("uploaded", "returned")):
    j = getjob(i); b = body(); u = auth.current()
    if locked(j): return locked(j)
    if k not in NAMES and k not in ("ids", "other") or k == "request": return jsonify(error=["Unknown test"]), 404
    reason = str(b.get("reason") or "").strip()
    if need_reason and len(reason) < 4: return jsonify(error=["Give the reason (it is recorded and shown to the tester)"]), 400
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM sections WHERE job_id=? AND key=?", (i, k)).fetchone()
            if need_data and (not row or row["data"] is None): return jsonify(error=[f"{name(k)} has no data to {verb}"]), 409
            if row and row["state"] not in allowed_from: return jsonify(error=[f"{name(k)} is {row['state']}; it cannot be {verb} now"]), 409
            rev = b.get("revision") if isinstance(b.get("revision"), int) and not isinstance(b.get("revision"), bool) else None
            if state in ("verified", "returned") and rev is None: return jsonify(error=["Reload the page: the revision you checked is missing"]), 400
            integrity.set_state(c, i, k, state, u["id"], f"{name(k)} {verb}" + (f": {reason}" if reason else ""), note=reason or None, expect=rev)
            c.execute("UPDATE jobs SET signed_off_by=NULL, signed_off_at=NULL, updated=? WHERE id=?", (now(), i))
            log(c, i, f"{name(k)} {verb}"
                + (f" (revision {rev})" if rev else "") + (f": {reason}" if reason else ""), kind="verify")
            notify.on_section(c, i, k, state, reason)
    except Conflict as e: return conflict(e)
    portal.refresh(i)  # the customer's partial report follows the approved tests
    return jsonify(ok=True)

@app.post("/api/jobs/<int:i>/sections/<k>/verify")
@auth.require("section.verify")
def verify_section(i, k):
    """A tester (the one who uploaded it, or a colleague) confirms the data in the app is what is in the source file.
    revision: the one they looked at."""
    return section_action(i, k, "verified", "verified")

@app.post("/api/jobs/<int:i>/sections/<k>/return")
@auth.require("section.verify")
def return_section(i, k):
    """Send a section back to its tester with the reason; they correct and upload again."""
    return section_action(i, k, "returned", "returned", need_reason=True)

@app.post("/api/jobs/<int:i>/sections/<k>/reopen")
@auth.require("section.verify")
def reopen_section(i, k):
    """Unlock a verified (or not-applicable) section so it can be corrected; the reason is recorded."""
    return section_action(i, k, "uploaded", "reopened", need_reason=True, need_data=False, allowed_from=("verified", "na"))

@app.post("/api/jobs/<int:i>/sections/<k>/na")
@auth.require("section.verify")
def na_section(i, k):
    """This test does not apply to this job (recorded with the reason, and listed as such)."""
    return section_action(i, k, "na", "marked not applicable", need_reason=True, need_data=False, allowed_from=("uploaded", "returned"))

@app.post("/api/jobs/<int:i>/assign")
@auth.require("job.assign")
def assign(i):
    """Who does which test.
    Admin: assign or reassign any test (key) or every unstarted, unassigned test of the job (all=true) to a tester.
    Tester: take a test nobody is assigned to and nobody has started (user_id is themselves); or give back a test they took
    and have not started. The tester gets one notification per assignment, however many tests or jobs it covers."""
    j = getjob(i, False); b = body(); u = auth.current(); admin = "admin" in u["roles"]
    if locked(j): return locked(j)
    uid = b.get("user_id") if admin else (b.get("user_id") or u["id"])
    if b.get("all"):
        if not admin: return jsonify(error=["Only an administrator assigns a whole job"]), 403
        keys = [k for k in (j["plan"] or [p["key"] for p in j["progress"]]) if k in NAMES and k != "request"]
    else:
        keys = [b.get("key")]
        if keys[0] not in NAMES or keys[0] == "request": return jsonify(error=["Unknown test"]), 400
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        t = None
        if uid not in (None, ""):
            t = c.execute("SELECT id, full_name, roles, test_types, active FROM users WHERE id=?", (uid,)).fetchone()
            if not t or not t["active"] or "tester" not in t["roles"].split(","): return jsonify(error=["Choose an active test engineer"]), 400
        if not admin and uid != u["id"]: return refuse(c, i, "test engineers can only take tests themselves; an administrator assigns others")
        done, skipped = [], []
        for k in keys:
            cur = c.execute("SELECT user_id FROM assignments WHERE job_id=? AND key=?", (i, k)).fetchone()
            started = c.execute("SELECT 1 FROM sections WHERE job_id=? AND key=? AND data IS NOT NULL", (i, k)).fetchone()
            if b.get("all") and (cur or started): skipped.append(f"{NAMES[k]} (already {'assigned' if cur else 'started'})"); continue
            if not admin:
                if started: return refuse(c, i, f"{NAMES[k]} has already been started")
                if cur and cur[0] != u["id"]: return refuse(c, i, f"{NAMES[k]} is assigned to someone else; only an administrator can reassign it")
            if t is None:
                if not cur: continue
                c.execute("DELETE FROM assignments WHERE job_id=? AND key=?", (i, k)); log(c, i, f"{NAMES[k]}: assignment removed", kind="job"); done.append(k); continue
            tt = [x for x in str(t["test_types"] or "").split(",") if x]
            if tt and k not in tt:
                if b.get("all"): skipped.append(f"{NAMES[k]} (not certified)"); continue
                return jsonify(error=[f"{t['full_name']} is not certified for {NAMES[k]}"]), 400
            c.execute("INSERT INTO assignments(job_id,key,user_id,assigned_by,at) VALUES(?,?,?,?,?) ON CONFLICT(job_id,key) DO UPDATE SET "
                      "user_id=excluded.user_id, assigned_by=excluded.assigned_by, at=excluded.at", (i, k, t["id"], u["id"], now()))
            how = "taken by" if t["id"] == u["id"] and not admin else "reassigned to" if cur else "assigned to"
            log(c, i, f"{NAMES[k]} {how} {t['full_name']}", kind="job")
            done.append(k)
        if t is not None and t["id"] != u["id"] and done: notify_assigned(c, t["id"], i, j["series"], done)
    return jsonify(ok=True, assigned=done, skipped=skipped)

def notify_assigned(c, uid, jid, series, keys):
    """One notification for an assignment, however many tests it covers. When the same tests are assigned to the same tester
    on several jobs at the same time (within two minutes, still unread), that one notification is extended with the job."""
    tests, sec = ", ".join(NAMES[k] for k in keys), ",".join(keys)
    since = (dt.datetime.now() - dt.timedelta(minutes=2)).isoformat(timespec="seconds")
    old = c.execute("SELECT id, message FROM notifications WHERE user_id=? AND kind='assigned' AND section_key=? AND read_at IS NULL AND created_at>=? "
                    "ORDER BY id DESC LIMIT 1", (uid, sec, since)).fetchone()
    if old:
        jobs = old["message"].split(": ", 1)[0]
        if series not in jobs.split(", "): c.execute("UPDATE notifications SET message=?, created_at=? WHERE id=?", (f"{jobs}, {series}: {tests} assigned to you", now(), old["id"]))
        return
    notify.notify(c, [uid], jid, "assigned", f"{series}: {tests} assigned to you", section=sec)

@app.post("/api/jobs/<int:i>/signoff")
@auth.require("job.signoff")
def signoff(i):
    """The administrator approves the job: every test verified by a tester or not applicable, and
    the checks run without data errors. Only then can the report be generated, signed off and released."""
    j = getjob(i); u = auth.current()
    if locked(j): return locked(j)
    if j["signoff_blockers"]: return jsonify(error=["Not ready for sign-off:"] + j["signoff_blockers"]), 409
    if j["stage"] < 2: return jsonify(error=["Run the checks (without data errors) before signing off"]), 409
    with db() as c:
        if c.execute("SELECT 1 FROM sections WHERE job_id=? AND uploaded_by=? AND key!='request' AND data IS NOT NULL", (i, u["id"])).fetchone():
            return refuse(c, i, "you uploaded data on this job, so another administrator must approve it")
        c.execute("UPDATE jobs SET signed_off_by=?, signed_off_at=?, updated=? WHERE id=?", (u["id"], now(), now(), i))
        log(c, i, "Job approved by the administrator: every test verified or not applicable", kind="approve")
    return jsonify(ok=True)

# ---- intake (NEXT_STEPS.md section 3.6): a customer's request (CPRI/QAF/01A sheets 1-2), received by the laboratory (sheet 3).
# Only a customer raises a request. The laboratory never edits the customer's answers: it records sheet 3 and the test
# plan, or returns the request to the customer with the reason.
def customer_request(c, fid):
    """(form row, the customer's values validated again, the tests they ticked, errors, warnings) of a waiting request."""
    f = c.execute("SELECT * FROM customer_forms WHERE id=?", (fid,)).fetchone() if str(fid or "").isdigit() else None
    if not f: return None, {}, [], ["Choose the customer's request: only a customer can raise a test request"], []
    if f["status"] != "received": return f, {}, [], [f"This customer request is {f['status']}, not waiting for intake"], []
    if f["kind"] != "web": return f, {}, [], ["This request was not filled in online: ask the customer to send it through the portal"], []
    errs, warns, clean = workflow.check_request(json.loads(f["data"] or "{}"))
    clean["signed_at"] = json.loads(f["data"] or "{}").get("signed_at") or f["at"]
    return f, clean, json.loads(f["plan"] or "[]"), [f"Customer request: {e} (return it to the customer to correct)" for e in errs], warns

def intake_problems(c, b, job=None):
    """Everything wrong with an intake, at once: (errors, warnings, request values, lab values, plan, form row, org)."""
    errs, warns, lab = workflow.check_lab(b)
    f, req, fplan, rerr, rwarn = None, {}, [], [], []
    if b.get("customer_form_id") or job is None:
        f, req, fplan, rerr, rwarn = customer_request(c, b.get("customer_form_id"))
    else:  # an existing job: the request it already holds, as the customer sent it
        rerr, rwarn, req = workflow.check_request(integrity.read_section(c, job["id"], "request") or {})
        rerr = [f"Customer request: {e} (the customer must send a corrected request)" for e in rerr]
        req["signed_at"] = (integrity.read_section(c, job["id"], "request") or {}).get("signed_at")
    plan, perr = workflow.check_plan(b.get("plan") if b.get("plan") is not None else fplan, NAMES)
    errs = rerr + errs + perr; warns = rwarn + warns
    org = f["org_id"] if f else (job or {}).get("org_id")
    if warns and not b.get("confirm_warnings"): errs += [f"Confirm: {w}" for w in warns]
    return errs, warns, req, lab, plan, f, org

@app.post("/api/intake/check")
@auth.require("request.receive")
def intake_check():
    """Dry run: every problem with the customer's request and the laboratory's part, so the engineer sees the whole list."""
    with db() as c: errs, warns, *_ = intake_problems(c, body())
    return jsonify(errors=errs, warnings=warns, ok=not errs)

def intake_record(lab, prior=None, form=None):
    u = auth.current()
    return dict(prior or {}, valid=True, **lab, received_by=u["full_name"], received_by_id=u["id"], recorded_at=now(),
                request_form_id=form["id"] if form else (prior or {}).get("request_form_id"), checked_by=None, checked_at=None)

def use_request(c, i, f, req):
    """Link a waiting customer request to job i: its values become the job's request section; the form is kept as sent."""
    integrity.write_section(c, i, "request", req, me(), "Customer request received")
    integrity.store_file(c, i, "Customer request (filled online).json", f["content"], MIMES["json"], me())
    c.execute("UPDATE customer_forms SET status='used', job_id=? WHERE id=?", (i, f["id"]))
    c.execute("UPDATE jobs SET customer=?, rating=?, org_id=? WHERE id=?", (req["customer"], req["rating"], f["org_id"], i))
    log(c, i, f"Customer request {f['id']} (SHA-256 {f['sha256'][:12]}...) used for this job", kind="job")
    notify.notify(c, notify.users_with(c, "customer", f["org_id"]), i, "progress", "Your test request was received by the laboratory")

@app.post("/api/intake")
@auth.require("request.receive")
def intake_create():
    """Receive a customer's request: the series and sample numbers are allocated only when nothing is missing or wrong."""
    b = body()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        errs, warns, req, lab, plan, f, org = intake_problems(c, b)
        if errs: c.execute("ROLLBACK"); return jsonify(error=errs, warnings=warns), 400
        rec = intake_record(lab, form=f)
        series, sample = integrity.allocate(c, "series"), integrity.allocate(c, "sample")
        i = insert_job(c, dict(series=series, sample=sample, customer=req["customer"], rating=req["rating"], request={}, org_id=org),
                       f"Request accepted; series {series} and sample {sample} assigned")
        use_request(c, i, f, req)
        c.execute("UPDATE jobs SET plan=?, intake=? WHERE id=?", (json.dumps(plan), json.dumps(rec), i))
        for k, uid in (b.get("assign") or {}).items():  # at intake an engineer can only take tests themselves
            if k in plan and uid and (uid == me() or "admin" in auth.current()["roles"]):
                t = c.execute("SELECT full_name, roles, test_types, active FROM users WHERE id=?", (uid,)).fetchone()
                tt = [x for x in str(t["test_types"] or "").split(",") if x] if t else []
                if t and t["active"] and "tester" in t["roles"].split(",") and (not tt or k in tt):
                    c.execute("INSERT INTO assignments(job_id,key,user_id,assigned_by,at) VALUES(?,?,?,?,?)", (i, k, uid, me(), now()))
                    log(c, i, f"{NAMES[k]} assigned to {t['full_name']}", kind="job")
        log(c, i, f"Intake recorded: {lab['condition']}, capability {lab['capability']}, received by {rec['received_by']}; "
                  f"test plan: {', '.join(NAMES[k] for k in plan)}" + (f"; confirmed: {'; '.join(warns)}" if warns else ""), kind="job")
    return jsonify(id=i, series=series, sample=sample), 201

@app.post("/api/jobs/<int:i>/intake")
@auth.require("job.edit")
def intake_complete(i):
    """Record or correct the laboratory's part (sheet 3) and the test plan of an existing job. With customer_form_id, a
    waiting customer request is linked to the job (one created from a data file before the request was received)."""
    j = getjob(i, False); b = body()
    if locked(j): return locked(j)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        errs, warns, req, lab, plan, f, org = intake_problems(c, b, j)
        if errs: c.execute("ROLLBACK"); return jsonify(error=errs, warnings=warns), 400
        why = write_check(c, i, ["request"]) if j.get("amend") and f else None
        if why: return refuse(c, i, *why)
        rec = intake_record(lab, {k: v for k, v in j["intake"].items() if k not in ("checked_by", "checked_at")}, f)
        if f: use_request(c, i, f, req)
        c.execute("UPDATE jobs SET plan=?, intake=?, updated=? WHERE id=?", (json.dumps(plan), json.dumps(rec), now(), i))
        log(c, i, "Intake (laboratory's part) recorded" + (" with the customer's request" if f else "") +
                  (f"; confirmed: {'; '.join(warns)}" if warns else ""), kind="job")
    return jsonify(ok=True)

@app.post("/api/jobs/<int:i>/intake/checked")
@auth.require("job.edit")
def intake_checked(i):
    """The receiving engineer has compared the product and the entries with the customer's request."""
    j = getjob(i, False)
    if locked(j): return locked(j)
    if not j["intake"].get("valid"): return jsonify(error=["Complete the intake details first"]), 409
    rec = dict(j["intake"], checked_by=auth.current()["full_name"], checked_at=now())
    with db() as c:
        c.execute("UPDATE jobs SET intake=?, updated=? WHERE id=?", (json.dumps(rec), now(), i))
        log(c, i, "Intake checked against the customer's request and the product", kind="job")
    return jsonify(ok=True)

@app.post("/api/request-forms/<int:fid>/return")
@auth.require("request.receive")
def request_return(fid):
    """Send a customer's request back with the reason (something missing or wrong); the customer corrects it and sends it again."""
    reason = str(body().get("reason") or "").strip()
    if len(reason) < 5: return jsonify(error=["Give the reason, so the customer knows what to correct"]), 400
    with db() as c:
        f = c.execute("SELECT * FROM customer_forms WHERE id=?", (fid,)).fetchone()
        if not f: abort(404)
        if f["status"] != "received": return jsonify(error=[f"This request is {f['status']}"]), 409
        c.execute("UPDATE customer_forms SET status='returned', note=? WHERE id=?", (reason, fid))
        log(c, None, f"Customer request {fid} returned to the customer: {reason}", kind="job")
        notify.notify(c, notify.users_with(c, "customer", f["org_id"]), None, "returned", f"Your test request {fid} was returned for correction: {reason}",
                      target=f"my/request/{fid}")
    return jsonify(ok=True)

@app.get("/api/intake/fields")
@auth.require("request.receive", "jobs.view")  # customers fill in the request form themselves
def intake_fields():
    return jsonify(form=workflow.FORM, fields=list(workflow.REQUEST_FIELDS), lab=list(workflow.LAB_FIELDS), states=workflow.STATES_UT,
                   tests={k: v for k, v in NAMES.items() if k != "request"})

# ---- testers, "My work"
@app.get("/api/testers")
@auth.require("staff.view")
def testers():
    with db() as c:
        return jsonify([dict(id=r["id"], name=r["full_name"], tests=[x for x in str(r["test_types"] or "").split(",") if x])
                        for r in c.execute("SELECT id, full_name, roles, test_types FROM users WHERE active=1 ORDER BY full_name")
                        if "tester" in r["roles"].split(",")])

def unassigned(c, open_jobs):
    """Planned tests nobody is assigned to and nobody has started, oldest job first."""
    out = []
    for r in c.execute(f"SELECT j.id, j.series, j.plan, j.created FROM jobs j WHERE {open_jobs} AND j.plan IS NOT NULL ORDER BY j.created").fetchall():
        for k in workflow.loads(r["plan"], []):
            if c.execute("SELECT 1 FROM assignments WHERE job_id=? AND key=?", (r["id"], k)).fetchone(): continue
            if c.execute("SELECT 1 FROM sections WHERE job_id=? AND key=? AND (data IS NOT NULL OR state='na')", (r["id"], k)).fetchone(): continue
            out.append(dict(id=r["id"], series=r["series"], key=k, at=r["created"]))
    return out

@app.get("/api/my-work")
@auth.require("staff.view")
def my_work():
    """What is waiting on the signed-in person, oldest first."""
    u = auth.current(); out = {}
    open_jobs = "j.archived=0 AND j.stage<4"
    with db() as c:
        q = lambda sql, *a: [dict(r) for r in c.execute(sql, a)]
        if "tester" in u["roles"]:
            out["returned"] = q(f"SELECT j.id, j.series, s.key, s.note, s.uploaded_at AS at FROM sections s JOIN jobs j ON j.id=s.job_id "
                               f"WHERE {open_jobs} AND s.state='returned' AND s.uploaded_by=? ORDER BY s.uploaded_at", u["id"])
            out["assigned"] = q(f"SELECT j.id, j.series, a.key, a.at FROM assignments a JOIN jobs j ON j.id=a.job_id LEFT JOIN sections s ON s.job_id=a.job_id AND s.key=a.key "
                               f"WHERE {open_jobs} AND a.user_id=? AND (s.id IS NULL OR s.data IS NULL) ORDER BY a.at", u["id"])
            out["uploaded"] = q(f"SELECT j.id, j.series, s.key, s.state, s.uploaded_at AS at FROM sections s JOIN jobs j ON j.id=s.job_id "
                               f"WHERE {open_jobs} AND s.uploaded_by=? AND s.key!='request' AND s.data IS NOT NULL ORDER BY s.uploaded_at DESC LIMIT 50", u["id"])
            out["intake"] = q(f"SELECT j.id, j.series, j.created AS at FROM jobs j WHERE {open_jobs} AND (j.intake IS NULL OR json_extract(j.intake,'$.checked_by') IS NULL) ORDER BY j.created")
            tt = [x for x in str(u.get("test_types") or "").split(",") if x]
            out["available"] = [x for x in unassigned(c, open_jobs) if not tt or x["key"] in tt]
            out["requests"] = q("SELECT f.id, o.name AS org, f.filename, f.at FROM customer_forms f LEFT JOIN orgs o ON o.id=f.org_id WHERE f.status='received' ORDER BY f.id")
            out["to_verify"] = q(f"SELECT j.id, j.series, s.key, s.uploaded_at AS at, uu.full_name AS by FROM sections s JOIN jobs j ON j.id=s.job_id LEFT JOIN users uu ON uu.id=s.uploaded_by "
                                f"WHERE {open_jobs} AND s.state='uploaded' AND s.key!='request' AND s.data IS NOT NULL ORDER BY s.uploaded_at")
        if "admin" in u["roles"]:  # the administrator approves, generates and signs off, and sees everything that is waiting
            out["to_signoff"] = [dict(id=j["id"], series=j["series"], at=j["updated"]) for j in
                                 (getjob(r["id"], False) for r in c.execute(f"SELECT j.id FROM jobs j WHERE {open_jobs} AND j.signed_off_by IS NULL AND j.stage>=2"))
                                 if not j["signoff_blockers"]]
            out["to_approve"] = q("SELECT j.id, j.series, j.customer, j.updated AS at FROM jobs j WHERE j.archived=0 AND j.stage=3 ORDER BY j.updated")
            out["unassigned"] = unassigned(c, open_jobs)
            out["requests"] = q("SELECT f.id, o.name AS org, f.filename, f.at FROM customer_forms f LEFT JOIN orgs o ON o.id=f.org_id WHERE f.status='received' ORDER BY f.id")
            out["awaiting_verification"] = q(f"SELECT j.id, j.series, s.key, s.uploaded_at AS at, uu.full_name AS by FROM sections s JOIN jobs j ON j.id=s.job_id "
                                             f"LEFT JOIN users uu ON uu.id=s.uploaded_by WHERE {open_jobs} AND s.state='uploaded' AND s.key!='request' AND s.data IS NOT NULL ORDER BY s.uploaded_at")
            out["locked_accounts"] = q("SELECT id, username AS series, full_name AS name, locked_until AS at FROM users WHERE locked_until > ?", now())
            out["tickets"] = q("SELECT t.id, o.name AS series, t.subject AS name, t.updated_at AS at FROM tickets t LEFT JOIN orgs o ON o.id=t.org_id "
                               "WHERE t.status='open' ORDER BY t.updated_at")
    for lst in out.values():
        for x in lst:
            if "key" in x: x["name"] = name(x["key"])
    return jsonify(out)

@app.get("/api/audit/verify")
@auth.require("audit.read")
def audit_verify():
    """Recompute the audit hash chain. 'tip' is the hash of the newest entry: write it down (or export it) daily, so that even
    removing the newest entries can be detected later."""
    with db() as c: r = integrity.verify_chain(c)
    with db() as c: log(c, None, "Audit chain checked: " + ("intact" if r["ok"] else f"BROKEN at entry {r['broken_at']} ({r['reason']})"), kind="admin")
    return jsonify(r)

@app.get("/api/jobs/<int:i>/history")
@auth.require("sources.view")
def section_history(i):
    """Every revision of every section of the job: who wrote it, when, from which file, and the data's fingerprint."""
    getjob(i, False)
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT h.key,h.revision,h.state,h.data_sha256,h.event,h.at,u.full_name AS by,f.name AS file,f.sha256 AS file_sha256 "
                                           "FROM section_history h LEFT JOIN users u ON u.id=h.user_id LEFT JOIN files f ON f.id=h.file_id "
                                           "WHERE h.job_id=? ORDER BY h.id", (i,))]
    return jsonify(rows)

@app.get("/api/files/<int:fid>")
@auth.require("sources.view")
def get_file(fid):
    """An uploaded data file, exactly as received."""
    with db() as c: r = c.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not r: abort(404)
    getjob(r["job_id"], False)
    resp = send_file(io.BytesIO(r["content"]), mimetype=r["mime"] or "application/octet-stream", as_attachment=True, download_name=r["name"])
    resp.headers["X-Content-Type-Options"] = "nosniff"; return resp

CODE_FILES = ("app.py", "importers.py", "rules.py", "vision.py", "auth.py", "integrity.py", "workflow.py", "xltemplates.py", "paper_templates.py", "excel_routes.py", "retention.py")
def code_id():
    """Fingerprint of the Python code on disk. Taken once at start-up and again on request, it shows whether the running
    server is older than its files (the page is always served fresh, so an unrestarted server and a new page can disagree)."""
    h = hashlib.sha256()
    for f in CODE_FILES:
        try:
            with open(os.path.join(HERE, f), "rb") as fh: h.update(fh.read())
        except OSError: pass
    return h.hexdigest()[:12]
STARTED_CODE = code_id()

@app.get("/api/version")
@auth.public
def version(): return jsonify(running=STARTED_CODE, on_disk=code_id(), stale=STARTED_CODE != code_id())

@app.get("/api/stats")
@auth.require("stats")
def stats():
    """Pipeline counts cover jobs in progress or released here; historical records from registers are counted separately.
    Turnaround = time from capturing the request to approving the report (the first approval of each released job),
    measured from the audit trail, so it reflects the whole preparation, not just building the PDF."""
    with db() as c:
        by = [0] * 5
        for r in c.execute("SELECT stage,COUNT(*) n FROM jobs WHERE archived=0 GROUP BY stage"): by[r[0]] = r[1]
        hist = c.execute("SELECT COUNT(*) FROM jobs WHERE archived=1").fetchone()[0]
        ms = [int(m.group(1)) for r in c.execute("SELECT event FROM audit WHERE event LIKE 'Report generated in%'") if (m := re.search(r"in (\d+) ms", r[0]))]
        kinds = {r[0] or "json": r[1] for r in c.execute("SELECT kind,COUNT(*) FROM imports GROUP BY kind")}
        done = c.execute("SELECT j.created, MIN(a.at) FROM jobs j JOIN audit a ON a.job_id=j.id AND a.event LIKE 'Approved by%' "
                         "WHERE j.archived=0 AND j.stage=4 GROUP BY j.id").fetchall()
        open_ = [r[0] for r in c.execute("SELECT created FROM jobs WHERE archived=0 AND stage<4")]
        verdicts = {r[0]: r[1] for r in c.execute("SELECT COALESCE(verdict,'Not yet checked'),COUNT(*) FROM jobs WHERE archived=0 GROUP BY 1")}
        ai = vision.status(c)
    hours = lambda a, b: (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 3600
    tat = [hours(a, b) for a, b in done if a and b]
    ages = [hours(a, now()) for a in open_ if a]
    return jsonify(total=sum(by), by_stage=by, stages=STAGES, historical=hist, avg_gen_ms=int(mean(ms)) if ms else None, imports=kinds,
                   turnaround_h=dict(avg=round(mean(tat), 2), best=round(min(tat), 2), worst=round(max(tat), 2), n=len(tat)) if tat else None,
                   open_age_h=dict(avg=round(mean(ages), 2), oldest=round(max(ages), 2), n=len(ages)) if ages else None, verdicts=verdicts,
                   ai={k: ai[k] for k in ("configured", "model", "provider", "kind", "calls_today", "daily_limit")}, sections=NAMES)

@app.post("/api/demo")
@auth.require("job.create")
def demo():
    """Load the demo job with its scanned sheets (only when ALETHEIA_DEMO=1: a real job starts from a customer's request).
    If it is already loaded, attach any scans it is missing and return it."""
    if os.environ.get("ALETHEIA_DEMO") != "1": abort(404)
    data = load_demo(); w = data["work"]
    with db() as c: old = c.execute("SELECT id FROM jobs WHERE series=?", (w["series"],)).fetchone()
    if old: i = old[0]
    else:
        with db() as c: i = insert_job(c, dict(series=w["series"], sample=w["sample"], customer=data["request"]["customer"],
                                               rating=data["request"]["rating"], request=data["request"]), "Customer request captured (demo data)")
        content = {k: v for k, v in data.items() if k != "request"}
        apply_import(getjob(i), i, os.path.basename(DEMO), content, "json", [], integrity.canon(content).encode())
    added = attach_demo_scans(i)
    return jsonify(id=i, existing=bool(old), scans_added=added), 200 if old else 201

def attach_demo_scans(i):
    """The demo job's scanned sheets, each attached to the test it belongs to (named after the printed sheet)."""
    by = (("Customer request", "other"), ("Proforma", "proforma"), ("Work instruction", "work"), ("Datasheet for losses", "losses"),
          ("Logsheet for losses", "resistance"), ("no load current", "noload"), ("short circuit", "sc"), ("temp. rise", "temp"), ("pressure", "pressure"))
    names = sorted(f for f in os.listdir(DEMO_SCANS) if os.path.splitext(f)[1].lower() in (".pdf", ".png", ".jpg", ".jpeg", ".webp")) if os.path.isdir(DEMO_SCANS) else []
    with db() as c:
        have = {r[0] for r in c.execute("SELECT sha256 FROM sources WHERE job_id=?", (i,))}
        n = 0
        for f in names:
            with open(os.path.join(DEMO_SCANS, f), "rb") as fh: raw = fh.read()
            sec = next((k for w, k in by if w.lower() in f.lower()), "other")
            if hashlib.sha256(raw).hexdigest() not in have: insert_source(c, i, f, raw, sec); n += 1
    return n

app.config["TEST_NAMES"] = ALL_NAMES
auth.setup(app, db, log, os.path.dirname(os.path.abspath(DB)))
init()
excel_routes.install(sys.modules[__name__])  # template registry and Excel routes (they use this module's helpers)
retention.install(sys.modules[__name__])     # backups, audit tip, export packages
notify.install(sys.modules[__name__])        # notifications, settings, email outbox
portal.install(sys.modules[__name__])        # partial reports, approved values, customers' request forms
tickets.install(sys.modules[__name__])       # customers' tickets to the administrators
if __name__ == "__main__":
    retention.schedule()                     # one backup a day while the server runs
    notify.worker()                          # email outbox
    app.run(debug=False, port=int(os.environ.get("PORT", 5000)))
