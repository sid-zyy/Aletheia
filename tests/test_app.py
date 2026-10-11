"""Run from the project folder:  python -m unittest discover -s tests -v"""
import base64, io, json, os, sqlite3, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.TemporaryDirectory()
os.environ["ALETHEIA_DB"] = os.path.join(_tmp.name, "test.db")
os.environ["ALETHEIA_FEATURE_SCAN"] = "1"  # the scanning tests below need the (optional) feature on
os.environ["ALETHEIA_AUTO_BACKUP"] = "0"
os.environ["ALETHEIA_PASSWORDS"] = "1"  # the password rules are tested; the app runs without them while testing
os.environ["ALETHEIA_DEMO"] = "1"  # the demo loader is a test fixture; a real job starts from a customer's request
for _v in ("GEMINI_API_KEY", "GEMINI_MODEL", "AI_BASE_URL", "AI_MODEL", "AI_API_KEY", "AI_PROVIDER", "AI_NUM_CTX", "AI_IMAGE_PX"): os.environ.pop(_v, None)
import app as aletheia, importers, integrity, vision  # noqa: E402

SD = os.path.join(ROOT, "sample_data")
DEMO = json.load(open(os.path.join(SD, "AP_Transformers_25T1654.json")))
raw = lambda n: open(os.path.join(SD, n), "rb").read()
up = lambda name, data: dict(filename=name, b64=base64.b64encode(data).decode())
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def pdf_text(data):
    import pypdfium2
    doc = pypdfium2.PdfDocument(data)
    try: return " ".join(" ".join(p.get_textpage().get_text_range() for p in doc).split())  # line wrapping removed
    finally: doc.close()


PW = "lab-test-password-1"
# t.rao uploads and checks; s.iyer is the second tester who verifies; admin approves the job and generates the report;
# r.viewer and p.naveen are administrators who sign off and release (and second-sign amendments)
STAFF = {"t.rao": ("T. Rao", "tester", "E1001"), "s.iyer": ("S. Iyer", "tester", "E1002"), "r.viewer": ("R. Viewer", "admin", "E2001"),
         "p.naveen": ("P. Naveenkumar", "admin", "E2002"), "admin": ("Lab Admin", "admin", "E0001")}
_HASH = None


def ensure_users():
    """Accounts shared by every test (hashing a password is slow, so they are made once)."""
    global _HASH
    from werkzeug.security import generate_password_hash
    _HASH = _HASH or generate_password_hash(PW)
    with aletheia.db() as c:
        for un, (name, role, emp) in STAFF.items():
            if not c.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone():
                c.execute("INSERT INTO users(username,full_name,employee_id,roles,password_hash,must_change_password,created_at) VALUES(?,?,?,?,?,0,'2026-01-01')",
                          (un, name, emp, role, _HASH))
        if not c.execute("SELECT 1 FROM orgs WHERE name=?", (CUSTOMER[2],)).fetchone():
            c.execute("INSERT INTO orgs(name,created_at) VALUES(?,'2026-01-01')", (CUSTOMER[2],))
        org = c.execute("SELECT id FROM orgs WHERE name=?", (CUSTOMER[2],)).fetchone()[0]
        if not c.execute("SELECT 1 FROM users WHERE username=?", (CUSTOMER[0],)).fetchone():
            c.execute("INSERT INTO users(username,full_name,roles,org_id,email,password_hash,must_change_password,created_at) VALUES(?,?,?,?,?,?,0,'x')",
                      (CUSTOMER[0], CUSTOMER[1], "customer", org, "buyer@ap.example", _HASH))
    return org


def signed_in(username, password=PW):
    """A test client signed in as this user, sending the CSRF token on every request."""
    c = aletheia.app.test_client()
    r = c.post("/api/login", json=dict(username=username, password=password))
    assert r.status_code == 200, r.json
    c.environ_base["HTTP_X_CSRF_TOKEN"] = c.get("/api/me").json["csrf"]
    return c


# The demo customer's request as they fill it in online (Customer Request Form CPRI/QAF/01A, sheets 1 and 2; Chennai PIN
# 600058, Tamil Nadu), and the laboratory's part on receipt (sheet 3). See workflow.REQUEST_FIELDS and LAB_FIELDS.
REQUEST = dict(customer="A.P. Transformers", address=DEMO["request"]["address"], city="Chennai", state="Tamil Nadu", pin="600058",
               contact="V. Krishna", phone="+91 9876543210", email="qa@aptransformers.example", sample=DEMO["request"]["sample"],
               rating="250 kVA / 11 kV / 433 V", description=DEMO["request"]["rating"], type=DEMO["request"]["type"], serial="1098",
               manufacturer="A.P. Transformers", drawings=DEMO["request"]["drawings"], requirement="", criteria=DEMO["request"]["criteria"],
               samples="1", take_back="Yes", scrap="No", tests="Type test", mounting="", witness=DEMO["request"]["witness"], witness_other="",
               dispatch="Handed over to person", dispatch_mode="", additional_reports="Not required", msme="Not Applicable", conformity="Yes",
               decision_rule="(i)", declare_drawings=True, declare_terms=True, signed_name="V. Krishna")
LAB = dict(condition="Suitable for Testing", capability="Yes", external="", arrived_at="2026-10-10T09:00")
CUSTOMER = ("ap.portal", "AP Portal", "A.P. Transformers")  # the demo customer's portal account


class Base(unittest.TestCase):
    def setUp(self):
        self.org = ensure_users()
        with aletheia.db() as c:  # the integrity triggers forbid exactly this, so the wipe between tests lifts them briefly
            integrity.drop_triggers(c)
            for t in ("jobs", "imports", "audit", "sources", "reports", "vision_calls", "sections", "section_history", "files", "counters", "assignments", "bays",
                      "customer_forms"):
                c.execute(f"DELETE FROM {t}")
            c.execute("UPDATE users SET failed_attempts=0, locked_until=NULL")
            integrity.install_triggers(c)
        self.c = signed_in("t.rao"); aletheia.app.config.pop("VISION_TRANSPORT", None)
        self.admin = signed_in("admin"); self.cust = signed_in(CUSTOMER[0])

    def request(self, plan=("proforma", "temp", "sc"), **kw):
        """The customer raises a test request online; returns its id (it waits in the laboratory's inbox)."""
        r = self.cust.post("/api/customer/requests", json=dict(REQUEST, plan=list(plan), **kw)); self.assertEqual(r.status_code, 201, r.json)
        return r.json["id"]

    def receive(self, plan=("proforma", "temp", "sc"), **kw):
        """The laboratory receives a fresh customer request (sheet 3 recorded, numbers allocated); returns the job id."""
        r = self.c.post("/api/intake", json=dict(LAB, customer_form_id=self.request(plan), plan=list(plan), **kw)); self.assertEqual(r.status_code, 201, r.json)
        return r.json["id"]

    def approve(self, i, who="r.viewer"):
        return signed_in(who).post(f"/api/jobs/{i}/approve", json=dict(password=PW))

    def drop(self, i):
        """Delete a never-released record (an admin action)."""
        return self.admin.delete(f"/api/jobs/{i}")

    def intake(self, i):
        """Complete and check the intake (required before release), with the tests that have data as the test plan."""
        j = self.get(i)
        plan = [k for k in j["data"] if k in aletheia.NAMES and k != "request"] or ["proforma"]
        b = dict(LAB, plan=plan)
        if not (j["data"].get("request") or {}).get("signed_name"): b["customer_form_id"] = self.request(plan)  # e.g. the demo job: no request yet
        r = self.c.post(f"/api/jobs/{i}/intake", json=b)
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/intake/checked").status_code, 200)

    def gen(self, i):
        """The whole route to a report, in order: intake completed (if it was not), checks run, every flagged item reviewed
        by the engineer, every section verified by a second tester, the job approved and the report built by an administrator."""
        j = self.get(i)
        if not j["intake"].get("checked_by"):
            ran = j["stage"] >= 2; self.intake(i)
            if ran: self.c.post(f"/api/jobs/{i}/validate")  # the intake changed the request, so the checks run again
        for n, f in enumerate(self.get(i)["findings"]):
            if f["level"] == "warn" and not f.get("reviewed"): self.c.post(f"/api/jobs/{i}/review", json=dict(index=n))
        v = signed_in("s.iyer"); j = self.get(i)
        for k, m in j["meta"].items():
            if k != "request" and m["state"] in ("uploaded", "returned") and k in j["data"]:
                r = v.post(f"/api/jobs/{i}/sections/{k}/verify", json=dict(revision=m["revision"])); self.assertEqual(r.status_code, 200, (k, r.json))
        if j["stage"] >= 2: self.admin.post(f"/api/jobs/{i}/signoff")
        return self.admin.post(f"/api/jobs/{i}/generate")

    def job(self, series="CPRIBLRSCL25T1654"):
        r = self.c.post("/api/jobs", json=dict(series=series, sample="HVD25S0847", customer_form_id=self.request()))
        self.assertEqual(r.status_code, 201, r.json); return r.json["id"]

    def get(self, i): return self.c.get(f"/api/jobs/{i}").json


class ImportFormats(Base):
    def test_flat_layout_round_trips_exactly(self):
        rows = [(s, f, importers._cell(v)) for s, f, v in importers.flatten(DEMO)]
        self.assertEqual(importers.unflatten(rows)[0], DEMO)
        self.assertEqual(DEMO["request"]["serial"], "1098")  # text that looks like a number must stay text

    def test_csv_xlsx_and_database_give_same_data_as_json(self):
        want = {k: v for k, v in DEMO.items() if k != "request"}  # the request is the customer's: a file never changes it
        for name in ("AP_Transformers_25T1654.csv", "AP_Transformers_25T1654.xlsx", "AP_Transformers_25T1654_lab.db"):
            i = self.job(); r = self.c.post(f"/api/jobs/{i}/import", json=up(name, raw(name)))
            self.assertEqual(r.status_code, 200, r.json)
            got = self.get(i)["data"]; self.assertEqual(got["request"]["signed_name"], REQUEST["signed_name"], name)
            self.assertEqual({k: v for k, v in got.items() if k != "request"}, want, name)
            self.drop(i)

    def test_csv_import_runs_through_to_approved_report(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("lab.csv", raw("AP_Transformers_25T1654.csv")))
        f = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        self.assertFalse([x for x in f if x["level"] == "fail"]); self.assertEqual(len(f), 30)
        g = self.gen(i).json; self.assertEqual(g["version"], 1)
        self.assertEqual(self.approve(i).json["version"], 2)
        pdf = self.c.get(f"/api/jobs/{i}/report.pdf"); self.assertTrue(pdf.data.startswith(b"%PDF"))
        j = self.get(i); self.assertEqual(j["stage"], 4); self.assertEqual(j["imports"][0]["kind"], "csv")

    def test_approver_identity_comes_from_the_signed_in_account(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("lab.csv", raw("AP_Transformers_25T1654.csv")))
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/approve", json=dict(password=PW)).status_code, 403)  # a tester cannot approve
        ap = signed_in("r.viewer")
        self.assertEqual(ap.post(f"/api/jobs/{i}/approve", json=dict(password="wrong password!")).status_code, 403)  # signature not confirmed
        self.assertEqual(ap.post(f"/api/jobs/{i}/approve", json=dict(name="Somebody Else", employee_id="X9", password=PW)).status_code, 200)
        j = self.get(i); self.assertEqual((j["approver"], j["approver_id"]), ("R. Viewer", "E2001"))  # typed fields are ignored
        self.assertEqual(j["reports"][0]["approver_id"], "E2001")
        self.assertIn("Approved by R. Viewer (Employee ID E2001)", j["audit"][-1]["event"])
        self.assertEqual(j["audit"][-1]["actor"], "R. Viewer (r.viewer)")
        self.assertEqual(self.c.get("/api/verify/" + j["reports"][0]["token"]).json["approver_id"], "E2001")
        self.assertEqual(ap.post(f"/api/jobs/{i}/discard").status_code, 409)  # a released report cannot be withdrawn
        self.assertEqual((self.get(i)["approver"], self.get(i)["approver_id"]), ("R. Viewer", "E2001"))

    def test_older_database_gains_the_employee_id_column(self):
        path = os.path.join(_tmp.name, "old.db")
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, series TEXT UNIQUE, approver TEXT)")
            c.execute("CREATE TABLE reports(id INTEGER PRIMARY KEY, job_id INT, approver TEXT)")
        old, aletheia.DB = aletheia.DB, path
        try:
            aletheia.init()
            with sqlite3.connect(path) as c:
                for t in ("jobs", "reports"): self.assertIn("approver_id", [r[1] for r in c.execute(f"PRAGMA table_info({t})")], t)
        finally: aletheia.DB = old

    def test_csv_saved_with_windows_line_endings(self):
        # Excel on Windows saves CRLF. The CSV sniffer then guessed "no doubled quotes", so an empty note written as """"""
        # arrived as the text """" and every normal short-circuit shot was skipped (SC current "not evaluated").
        body = raw("AP_Transformers_25T1654.csv").decode("utf-8-sig").replace("\r\n", "\n")
        for nl in ("\n", "\r\n"):
            d = importers.load_test_data("x.csv", ("﻿" + body.replace("\n", nl)).encode("utf-8"))[0]
            self.assertEqual(d, DEMO, repr(nl))

    def test_semicolon_csv_and_series_column(self):
        text = "series;section;field;value\nCPRIBLRSCL25T1654;proforma;kva;250\nCPRIBLRSCL25T9999;proforma;kva;999\nCPRIBLRSCL25T1654;proforma;limits.oil;35\n"
        i = self.job(); r = self.c.post(f"/api/jobs/{i}/import", json=up("a.csv", text.encode()))
        self.assertEqual(r.status_code, 200, r.json); self.assertIn("1 rows for other series skipped", r.json["notes"])
        self.assertEqual(self.get(i)["data"]["proforma"], {"kva": 250, "limits": {"oil": 35}})

    def test_bad_files_are_rejected_with_a_reason(self):
        i = self.job()
        for name, data in (("x.csv", b"a,b\n1,2\n"), ("x.csv", b"section,field,value\nnonsense,a,1\n"), ("x.xlsx", b"PK not a workbook"),
                           ("x.db", b"not a database"), ("x.xls", b"\xd0\xcf\x11\xe0"), ("x.csv", b"section,field,value\nproforma,a..b,1\n")):
            r = self.c.post(f"/api/jobs/{i}/import", json=up(name, data)); self.assertEqual(r.status_code, 400, (name, r.json)); self.assertTrue(r.json["error"][0])
        self.assertEqual(self.get(i)["stage"], 0)

    def test_duplicate_is_per_job(self):
        a, b = self.job(), self.job("CPRIBLRSCL25T1655"); f = up("lab.csv", raw("AP_Transformers_25T1654.csv"))
        self.assertEqual(self.c.post(f"/api/jobs/{a}/import", json=f).status_code, 200)
        self.assertEqual(self.c.post(f"/api/jobs/{a}/import", json=f).status_code, 409)
        self.assertEqual(self.c.post(f"/api/jobs/{b}/import", json=f).status_code, 200)

    def test_incomplete_data_is_not_evaluated_instead_of_blocking(self):
        i = self.job(); part = {k: v for k, v in DEMO.items() if k != "request"}; part["temp"] = {"tap": "LT"}
        part["noload"] = json.loads(json.dumps(DEMO["noload"])); part["noload"]["rows"][2][4] = None  # one reading left empty (NA)
        self.c.post(f"/api/jobs/{i}/import", json=up("part.csv", importers.export_csv(part)))
        r = self.c.post(f"/api/jobs/{i}/validate"); self.assertEqual(r.status_code, 200)
        f = r.json["findings"]; na = {x["check"] for x in f if x.get("na")}
        self.assertFalse([x for x in f if x["check"] == "Data structure"])
        self.assertIn("Top-oil temperature rise", na); self.assertIn("No-load current limits", na)
        self.assertTrue([x for x in f if x["check"] == "Total loss at 100% load (75 C)" and x["level"] == "pass"])  # other checks still run
        self.assertEqual(self.get(i)["stage"], 2)
        self.assertEqual(self.gen(i).status_code, 200)

    def test_ollama_reader_uses_native_api_with_json_and_context(self):
        i = self.job(); sid = self.c.post(f"/api/jobs/{i}/sources", json=dict(section="work", **up("scan.png", PNG))).json["id"]
        os.environ.update(AI_BASE_URL="http://localhost:11434/v1", AI_MODEL="qwen2.5vl:3b", AI_NUM_CTX="6000"); sent = []
        try:
            def fake(model, key, body):
                sent.append(body); return {"message": {"content": json.dumps({"data": DEMO["work"], "uncertain": []})}}
            aletheia.app.config["VISION_TRANSPORT"] = fake
            r = self.c.post(f"/api/sources/{sid}/extract", json=dict(section="work")); self.assertEqual(r.status_code, 200, r.json)
            self.assertEqual(r.json["data"], DEMO["work"])
            b = sent[0]; self.assertEqual((b["stream"], b["options"]["num_ctx"]), (False, 6000))
            self.assertEqual(b["format"]["properties"]["data"]["required"], list(DEMO["work"]))  # answer constrained to the layout
            self.assertEqual(len(b["messages"][0]["images"]), 1)
        finally:
            for v in ("AI_BASE_URL", "AI_MODEL", "AI_NUM_CTX"): os.environ.pop(v)

    def test_other_log_sheet(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("d.json", raw("AP_Transformers_25T1654.json")))
        sheet = {"title": "Noise level test", "fields": [{"label": "Test series no.", "value": "25T1656"}, {"label": "Ambient", "value": 31.2},
                 {"label": "", "value": None}], "tables": [{"title": "Readings", "columns": ["Point", "dB(A)"], "rows": [[1, 52.1], [2], [None, None]]}]}
        r = self.c.post(f"/api/jobs/{i}/section", json=dict(section="other", data=sheet)); self.assertEqual(r.status_code, 200); key = r.json["key"]
        o = self.get(i)["data"]["other"][key]
        self.assertEqual(len(o["fields"]), 2); self.assertEqual(o["tables"][0]["rows"], [[1, 52.1], [2, None]])  # empty rows dropped, short rows padded
        f = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        self.assertTrue([x for x in f if x["check"] == "Supplementary test record: Noise level test" and x["level"] == "warn"])
        self.assertTrue([x for x in f if x["check"] == "Identifier consistency" and "Noise level test" in x["detail"]])  # 25T1656 vs 25T1654
        self.assertEqual(self.gen(i).status_code, 200)
        j2 = self.job("CPRIBLRSCL25T1999")  # exported CSV, including the extra sheet, imports into another job unchanged
        self.c.post(f"/api/jobs/{j2}/import", json=up("x.csv", self.c.get(f"/api/jobs/{i}/export/csv").data))
        self.assertEqual(self.get(j2)["data"]["other"], self.get(i)["data"]["other"])
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/other:{key}").status_code, 200); self.assertNotIn("other", self.get(i)["data"])
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/other:{key}").status_code, 404)

    def test_review_one_by_one_before_the_report(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("d.json", raw("AP_Transformers_25T1654.json")))
        F = self.c.post(f"/api/jobs/{i}/validate").json["findings"]; warns = [n for n, f in enumerate(F) if f["level"] == "warn" and not f.get("advisory")]
        self.assertEqual(self.admin.post(f"/api/jobs/{i}/generate").status_code, 409)  # nothing reviewed yet
        self.c.post(f"/api/jobs/{i}/review", json=dict(index=warns[0]))
        self.assertIn(f"{len(warns) - 1} left", self.admin.post(f"/api/jobs/{i}/generate").json["error"][0])
        F = self.c.post(f"/api/jobs/{i}/validate").json["findings"]  # unchanged items keep their review
        self.assertTrue(F[warns[0]].get("reviewed"))
        passed = [n for n, f in enumerate(F) if f["level"] == "pass"][0]
        self.assertEqual(self.c.post(f"/api/jobs/{i}/review", json=dict(index=passed)).status_code, 400)
        self.assertEqual(self.gen(i).status_code, 200)
        d = json.loads(json.dumps(DEMO)); d["temp"]["oil_rise_reported"] = 42.35  # logged top-oil rise over the limit: a failed check
        j = self.job("CPRIBLRSCL25T1998"); self.c.post(f"/api/jobs/{j}/import", json=up("f.json", json.dumps(d).encode()))
        F = self.c.post(f"/api/jobs/{j}/validate").json["findings"]; fail = [n for n, f in enumerate(F) if f["level"] == "fail"][0]
        self.assertFalse(F[fail].get("blocks"))  # a sample failing a limit is a result, not a data error
        self.assertEqual(self.get(j)["stage"], 2)
        self.assertEqual(self.admin.post(f"/api/jobs/{j}/generate").status_code, 409)  # the failure must be confirmed first
        self.assertEqual(self.c.post(f"/api/jobs/{j}/review", json=dict(index=fail)).status_code, 200)

    def test_failing_sample_gets_a_does_not_comply_report(self):
        d = json.loads(json.dumps(DEMO)); d["temp"]["oil_rise_reported"] = 42.35  # the logged rise decides (F5), not a recomputation
        j = self.job(); self.c.post(f"/api/jobs/{j}/import", json=up("f.json", json.dumps(d).encode()))
        self.c.post(f"/api/jobs/{j}/validate"); self.assertEqual(self.get(j)["verdict"], "Does not comply")
        for n, f in enumerate(self.get(j)["findings"]):
            if f["level"] == "fail": self.c.post(f"/api/jobs/{j}/review", json=dict(index=n))
        self.assertEqual(self.gen(j).status_code, 200)
        text = pdf_text(self.c.get(f"/api/jobs/{j}/report.pdf").data)
        self.assertIn("does NOT comply", text); self.assertIn("Top-oil temperature rise", text)
        self.assertEqual(self.approve(j).status_code, 200)
        self.assertEqual([x["series"] for x in self.c.get("/api/jobs?verdict=not").json], ["CPRIBLRSCL25T1654"])

    def test_recomputed_average_that_disagrees_is_advisory_only(self):
        # F5: the logged average is the value; Aletheia's own arithmetic only points at a possible slip
        d = json.loads(json.dumps(DEMO)); d["noload"]["rows"][0][4] = 1.70  # logged average; the mean of its readings is 1.689
        j = self.job(); self.c.post(f"/api/jobs/{j}/import", json=up("f.json", json.dumps(d).encode()))
        F = self.c.post(f"/api/jobs/{j}/validate").json["findings"]
        f = next(x for x in F if x["check"] == "No-load current average")
        self.assertEqual((f["level"], f.get("advisory"), f.get("blocks")), ("warn", True, None))
        self.assertEqual(self.get(j)["stage"], 2); self.assertIsNotNone(self.get(j)["verdict"])
        self.assertEqual(self.gen(j).status_code, 200)
        text = pdf_text(self.c.get(f"/api/jobs/{j}/report.pdf").data)
        self.assertNotIn("No-load current average", text); self.assertNotIn("Reported vs computed", text)  # advisory: never printed
        self.assertIn("as logged", text)

    def test_broken_layout_still_blocks_the_report(self):
        j = self.job(); d = {k: v for k, v in DEMO.items() if k != "request"}
        self.c.post(f"/api/jobs/{j}/import", json=dict(filename="d.json", content=d))
        self.c.post(f"/api/jobs/{j}/section", json=dict(section="ids", data={"work": 5}, revision=self.get(j)["meta"]["ids"]["revision"]))
        F = self.c.post(f"/api/jobs/{j}/validate").json["findings"]; bad = [n for n, f in enumerate(F) if f.get("blocks")]
        self.assertTrue(bad, F[:3]); self.assertEqual(self.get(j)["stage"], 1); self.assertIsNone(self.get(j)["verdict"])
        self.assertEqual(self.c.post(f"/api/jobs/{j}/review", json=dict(index=bad[0])).status_code, 409)
        self.assertEqual(self.admin.post(f"/api/jobs/{j}/generate").status_code, 409)

    def test_summary_never_passes_a_test_that_was_not_fully_evaluated(self):
        d = json.loads(json.dumps(DEMO)); d["sc"]["shots"][3][7] = None; d["noload"]["rows"][2][4] = None; d["losses"]["rows"][0][13] = None
        j = self.job(); self.c.post(f"/api/jobs/{j}/import", json=up("f.json", json.dumps(d).encode()))
        self.c.post(f"/api/jobs/{j}/validate"); self.assertEqual(self.gen(j).status_code, 200)
        text = pdf_text(self.c.get(f"/api/jobs/{j}/report.pdf").data)
        # "None" is the format's own wording for two cover lines; anything else would be a Python None leaking into the report
        self.assertNotIn("None", text.replace("representative : None", "").replace("laboratory : None", ""))
        concl = text.split("Conclusion:")[1]  # short circuit and no-load: some checks passed, one could not run
        self.assertIn("covers only what could be evaluated", concl); self.assertIn("checks with NA values", concl); self.assertIn("SC current", concl)
        self.assertIn("NA", text.split("At 112.5 percent rated voltage")[1][:200])  # the missing 112.5% current prints as NA, the table stays
        self.assertEqual(self.get(j)["verdict"], "Complies (partly evaluated)")

    def test_remove_an_imported_file(self):
        i = self.job()
        self.c.post(f"/api/jobs/{i}/import", json=up("lab.csv", raw("AP_Transformers_25T1654.csv")))
        extra = {"other": {"x1": {"title": "Extra sheet", "fields": [{"label": "a", "value": 1}]}}}
        self.c.post(f"/api/jobs/{i}/import", json=dict(filename="extra.json", content=extra))
        self.c.post(f"/api/jobs/{i}/validate")
        imp = {x["source"]: x["id"] for x in self.get(i)["imports"]}
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/imports/{imp['lab.csv']}").status_code, 200)
        j = self.get(i)
        self.assertEqual(sorted(j["data"]), ["other", "request"])  # the other file's sheet and the request stay
        self.assertEqual((j["stage"], j["findings"]), (1, []))
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/imports/{imp['extra.json']}").status_code, 200)
        self.assertEqual(sorted(self.get(i)["data"]), ["request"]); self.assertEqual(self.get(i)["stage"], 0)  # back to step 1
        r = self.c.post(f"/api/jobs/{i}/import", json=up("lab.csv", raw("AP_Transformers_25T1654.csv")))
        self.assertEqual(r.status_code, 200)  # the same file can be imported again
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/imports/99999").status_code, 404)
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        last = self.get(i)["imports"][-1]["id"]
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/imports/{last}").status_code, 409)  # report built from it: withdraw first

    def test_remove_a_document(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("d.json", raw("AP_Transformers_25T1654.json")))
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/temp").status_code, 409)  # verified: locked
        self.assertEqual(signed_in("s.iyer").post(f"/api/jobs/{i}/sections/temp/reopen", json=dict(reason="wrong sheet attached")).status_code, 200)
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/temp").status_code, 200)
        j = self.get(i); self.assertNotIn("temp", j["data"]); self.assertEqual(j["stage"], 1)  # report withdrawn, checks to redo
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/temp").status_code, 404)
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/request").status_code, 400)
        f = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        self.assertIn("Temperature-Rise Test Logsheet", [x for x in f if x["check"] == "Completeness of source documents"][0]["detail"])

    def test_only_series_is_required(self):
        self.assertEqual(self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1999")).status_code, 400)  # only for a customer's request
        r = self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1999", customer_form_id=self.request())); self.assertEqual(r.status_code, 201, r.json)
        j = self.get(r.json["id"]); self.assertEqual((j["sample"], j["customer"], j["rating"]), ("NA", "A.P. Transformers", REQUEST["rating"]))
        self.assertEqual(self.c.post("/api/jobs", json=dict(customer="X")).status_code, 400)
        self.assertEqual(self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1998", sample="bad")).status_code, 400)
        i = r.json["id"]; self.c.post(f"/api/jobs/{i}/section", json=dict(section="sc", data=DEMO["sc"]))
        self.assertEqual(self.c.post(f"/api/jobs/{i}/validate").status_code, 200)
        self.assertEqual(self.gen(i).status_code, 200)

    def test_demo_job_comes_with_its_scans(self):
        r = self.c.post("/api/demo"); self.assertEqual(r.status_code, 201); i = r.json["id"]
        names = sorted(x["filename"] for x in self.get(i)["sources"])
        self.assertEqual(len(names), 9); self.assertIn("Logsheet for temp. rise.pdf", names)
        again = self.c.post("/api/demo")  # loading it again opens the same job and attaches nothing twice
        self.assertEqual((again.status_code, again.json["id"], again.json["scans_added"]), (200, i, 0))
        with aletheia.db() as c: c.execute("DELETE FROM sources WHERE job_id=?", (i,))  # a demo job loaded before scans were bundled
        self.assertEqual(self.c.post("/api/demo").json["scans_added"], 9)

    def test_export_reimports(self):
        i = self.c.post("/api/demo").json["id"]
        for fmt in ("csv", "xlsx", "sqlite", "json"):
            e = self.c.get(f"/api/jobs/{i}/export/{fmt}"); self.assertEqual(e.status_code, 200)
            n = self.job("CPRIBLRSCL25T1700"); r = self.c.post(f"/api/jobs/{n}/import", json=up("e." + {"sqlite": "db"}.get(fmt, fmt), e.data))
            if fmt == "sqlite":  # database rows carry their series, so they are refused for a different job
                self.assertEqual(r.status_code, 400); self.assertIn("other series", r.json["error"][0])
            else:
                self.assertEqual(r.status_code, 200, (fmt, r.json))
                strip = lambda d: {k: v for k, v in d.items() if k != "request"}  # each job keeps its own customer's request
                self.assertEqual(strip(self.get(n)["data"]), strip(self.get(i)["data"]))
            self.drop(n)


class Caching(Base):
    def test_browsers_never_keep_a_stale_page_or_api_answer(self):
        self.assertEqual(self.c.get("/").headers["Cache-Control"], "no-cache")
        self.assertEqual(self.c.get("/static/workflow.js").headers["Cache-Control"], "no-cache")
        self.assertEqual(self.c.get("/api/me").headers["Cache-Control"], "no-store")


class Register(Base):
    def test_register_from_csv_and_database(self):
        r = self.c.post("/api/import-register", json=up("legacy_register.csv", raw("legacy_register.csv"))).json
        self.assertEqual((r["created"], len(r["skipped"])), (4, 1)); self.assertIn("Series must look like", r["skipped"][0]["reason"])
        r = self.c.post("/api/import-register", json=up("legacy_register.db", raw("legacy_register.db"))).json
        self.assertEqual(r["created"], 3); self.assertEqual(r["table"], "test_register")
        again = self.c.post("/api/import-register", json=up("legacy_register.csv", raw("legacy_register.csv"))).json
        self.assertEqual(again["created"], 0)
        hits = self.c.get("/api/jobs?q=Kaveri").json; self.assertEqual(len(hits), 2)
        self.assertEqual(self.get(hits[0]["id"])["data"]["request"]["criteria"], "IS 1180")
        # historical records are searchable but are not jobs in progress
        self.assertTrue(all(j["archived"] for j in self.c.get("/api/jobs").json))
        s = self.c.get("/api/stats").json; self.assertEqual((s["total"], s["historical"]), (0, 7))
        self.assertEqual(len(self.c.get("/api/jobs?stage=0").json), 0); self.assertEqual(len(self.c.get("/api/jobs?stage=h").json), 7)

    def test_register_reads_result_and_test_date(self):
        csv = (b"Test Series No,Customer Name,Test Date,Result\n"
               b"CPRIBLRSCL24T1102,Southern Electricals,18-03-2024,Passed\nCPRIBLRSCL24T1103,Deccan Power,2024-05-02,Failed - oil leakage\n")
        self.assertEqual(self.c.post("/api/import-register", json=up("r.csv", csv)).json["created"], 2)
        l = {j["series"]: j for j in self.c.get("/api/jobs?stage=h").json}
        self.assertEqual((l["CPRIBLRSCL24T1102"]["verdict"], l["CPRIBLRSCL24T1102"]["tested"]), ("Complies", "2024-03-18"))
        self.assertEqual(l["CPRIBLRSCL24T1103"]["verdict"], "Does not comply")
        self.assertEqual([j["series"] for j in self.c.get("/api/jobs?from=2024-04-01&to=2024-12-31").json], ["CPRIBLRSCL24T1103"])
        self.assertEqual(len(self.c.get("/api/jobs?verdict=comply").json), 1)

    def test_register_needs_series_and_customer(self):
        r = self.c.post("/api/import-register", json=up("x.csv", b"name,value\na,1\n")); self.assertEqual(r.status_code, 400)


class ReportsAndSources(Base):
    def ready(self):
        i = self.c.post("/api/demo").json["id"]; self.c.post(f"/api/jobs/{i}/validate"); self.gen(i); return i

    def test_versions_are_frozen_and_verifiable(self):
        i = self.ready(); v1 = self.get(i)["reports"][0]
        a = self.c.get(f"/api/jobs/{i}/report.pdf").data; self.assertEqual(a, self.c.get(f"/api/jobs/{i}/report.pdf").data)
        import hashlib; self.assertEqual(hashlib.sha256(a).hexdigest(), v1["sha256"])
        s = self.c.get("/api/verify/" + v1["token"]).json; self.assertTrue(s["intact"] and s["current"]); self.assertFalse(s["approved"])
        self.approve(i)
        self.assertFalse(self.c.get("/api/verify/" + v1["token"]).json["current"])  # superseded by the approved version
        s2 = self.c.get("/api/verify/" + self.get(i)["reports"][0]["token"]).json; self.assertTrue(s2["approved"]); self.assertEqual(s2["version"], 2)
        with self.assertRaises(sqlite3.IntegrityError):  # the database itself refuses to change a stored report
            with aletheia.db() as c: c.execute("UPDATE reports SET pdf=? WHERE version=2", (b"%PDF tampered",))
        with aletheia.db() as c:  # someone who removes the trigger with a database tool is still caught by the fingerprint
            c.execute("DROP TRIGGER reports_no_update"); c.execute("UPDATE reports SET pdf=? WHERE version=2", (b"%PDF tampered",))
            integrity.install_triggers(c)
        self.assertFalse(self.c.get("/api/verify/" + self.get(i)["reports"][0]["token"]).json["intact"])
        self.assertEqual(self.c.get("/api/verify/nope").status_code, 404)

    def test_release_rules_and_customer_copy(self):
        i = self.ready(); tok = self.get(i)["reports"][0]["token"]
        self.assertEqual(self.c.get(f"/api/verify/{tok}/report.pdf").status_code, 409)  # not approved yet: nothing to hand out
        self.assertEqual(self.approve(i, "p.naveen").status_code, 403)  # the test engineer named on the report
        self.assertEqual(self.approve(i).status_code, 200)
        tok = self.get(i)["reports"][0]["token"]
        self.assertTrue(self.c.get(f"/api/verify/{tok}/report.pdf").data.startswith(b"%PDF"))
        self.assertEqual(self.drop(i).status_code, 409)  # released: kept so the QR code keeps working
        self.assertEqual(self.c.get(f"/api/verify/{tok}").status_code, 200)
        s = self.c.get("/api/stats").json; self.assertEqual(s["turnaround_h"]["n"], 1); self.assertEqual(s["verdicts"], {"Complies": 1})
        self.assertEqual(len(self.c.get("/api/jobs?q=Naveenkumar").json), 1)  # search covers the engineer, tests and standard
        self.assertEqual(len(self.c.get("/api/jobs?q=Type test").json), 1)

    def test_report_wording_comes_from_the_template(self):
        i = self.ready(); path = os.path.join(_tmp.name, "tpl.json")
        with open(path, "w", encoding="utf-8") as f: json.dump({"title": "HIGH POWER LAB - CERTIFICATE <draft>", "headings": {"summary": "2. Results at a glance"}}, f)
        aletheia.TEMPLATE_FILE, old = path, aletheia.TEMPLATE_FILE
        try:
            text = pdf_text(aletheia.build_pdf(self.get(i)).getvalue())
        finally:
            aletheia.TEMPLATE_FILE = old
        self.assertIn("HIGH POWER LAB - CERTIFICATE <draft>", text); self.assertIn("2. Results at a glance", text)
        self.assertIn("DESCRIPTION OF SAMPLE TESTED", text)  # keys left out keep the default wording
        self.assertIn("Sheet 1 of", text); self.assertIn("ULR-TC5452250SCLT1654F", text)  # the format's footer on every sheet

    def test_report_follows_the_lab_format(self):
        # "Transformer Test report format": 11 sheets for a full job, cross-referenced by sheet number, values as logged
        text = pdf_text(aletheia.build_pdf(self.get(self.ready())).getvalue())
        for s in ("DESCRIPTION OF SAMPLE TESTED", "SUMMARY OF TESTS CONDUCTED", "LIST OF DRAWINGS", "ROUTINE TESTS", "SPECIAL TEST",
                  "TYPE TEST", "OIL LEAKAGE TEST", "No load current at 112.5 percent voltage", "NOTE", "End of Test Report"):
            self.assertIn(s, text)
        self.assertIn("Sheet 11 of 11", text); self.assertNotIn("Sheet 12", text)
        self.assertIn("Number of Sheet(s) : Eleven", text); self.assertIn("Refer Sheet 2 of 11", text)
        self.assertIn("Short-circuit withstand", text); self.assertIn("21.4 b) 7 of 11 & 8 of 11", text)  # clause and sheets of the SC test
        self.assertIn("CPRIBLRSCL25T1654S011", text); self.assertNotIn("CPRIBLRSCL25T1654S001", text)  # calibration shot not reported
        self.assertIn("- average 7.101 7.504 6.346 7.098 7.502 6.343", text)  # HV at 75 C as logged: principal / highest / lowest, before / after
        self.assertIn("26.01 (as logged)", text)

    def test_editing_data_withdraws_report(self):
        i = self.ready(); t = dict(DEMO["temp"]); t["rhv_hot"] = t["rhv_hot"] * 1.01
        self.assertEqual(self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t)).status_code, 409)  # verified: locked
        self.assertEqual(signed_in("s.iyer").post(f"/api/jobs/{i}/sections/temp/reopen", json=dict(reason="hot resistance misread")).status_code, 200)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t)).status_code, 409)  # blind overwrite
        rev = self.get(i)["meta"]["temp"]["revision"]
        self.assertEqual(self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t, revision=rev)).status_code, 200)
        self.assertEqual(self.get(i)["stage"], 1); self.assertEqual(self.c.get(f"/api/jobs/{i}/report.pdf").status_code, 409)
        f = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        self.assertTrue([x for x in f if x["level"] == "fail" and "HV winding" in x["check"]])  # 0.3 K margin is gone

    def test_report_for_hand_entered_request_without_optional_fields(self):
        i = self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1654", sample="HVD25S0847", customer_form_id=self.request(
            requirement="", mounting="", witness="", witness_other="", dispatch_mode="", additional_reports=""))).json["id"]
        self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content={k: v for k, v in DEMO.items() if k != "request"}))
        self.c.post(f"/api/jobs/{i}/validate"); self.assertEqual(self.gen(i).status_code, 200)

    def test_files_are_uploaded_for_one_test_only(self):
        i = self.job(); full = raw("AP_Transformers_25T1654.csv")
        r = self.c.post(f"/api/jobs/{i}/import", json=dict(section="sc", **up("lab.csv", full))); self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(sorted(k for k in self.get(i)["data"] if k not in ("request", "ids")), ["sc"])  # nothing allocated to other tests
        self.assertEqual(self.c.post(f"/api/jobs/{i}/import", json=dict(section="request", **up("lab2.csv", full))).status_code, 400)
        only_temp = b"section,field,value" + bytes([10]) + b"temp,tap,LT" + bytes([10])
        self.assertIn("no data for", self.c.post(f"/api/jobs/{i}/import", json=dict(section="sc", **up("t.csv", only_temp))).json["error"][0])
        self.assertEqual(self.c.post(f"/api/jobs/{i}/sources", json=dict(section="sc", **up("scan.png", PNG))).status_code, 201)
        self.assertEqual(self.get(i)["sources"][0]["section"], "sc")

    def test_sources_and_ai_reading(self):
        i = self.job()
        self.assertEqual(self.c.post(f"/api/jobs/{i}/sources", json=up("scan.png", PNG)).status_code, 400)  # no test chosen: refused
        r = self.c.post(f"/api/jobs/{i}/sources", json=dict(section="temp", **up("scan.png", PNG))); self.assertEqual(r.status_code, 201); sid = r.json["id"]
        self.assertEqual(self.c.post(f"/api/jobs/{i}/sources", json=dict(section="temp", **up("copy.png", PNG))).status_code, 409)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/sources", json=dict(section="temp", **up("x.exe", b"MZ...."))).status_code, 400)
        self.assertEqual(self.c.get(f"/api/sources/{sid}").data, PNG)
        r = self.c.post(f"/api/sources/{sid}/extract", json=dict(section="work")); self.assertEqual(r.status_code, 400); self.assertIn("not set up", r.json["error"][0])
        os.environ["GEMINI_API_KEY"] = "test"; os.environ["ALETHEIA_DAILY_CALL_LIMIT"] = "2"; sent = []
        try:
            def fake(model, key, body):
                sent.append(body); return {"candidates": [{"content": {"parts": [{"text": json.dumps({"data": DEMO["work"], "uncertain": ["engineer"], "notes": "n"})}]}}]}
            aletheia.app.config["VISION_TRANSPORT"] = fake
            r = self.c.post(f"/api/sources/{sid}/extract", json=dict(section="work")); self.assertEqual(r.status_code, 200, r.json)
            self.assertEqual(r.json["data"], DEMO["work"]); self.assertEqual(r.json["uncertain"], ["engineer"])
            self.assertEqual(sent[0]["contents"][0]["parts"][1]["inlineData"]["mimeType"], "image/png")
            self.assertNotIn("work", self.get(i)["data"])  # a reading is a proposal, never saved by itself
            self.assertFalse(r.json["cached"])
            aletheia.app.config["VISION_TRANSPORT"] = lambda *a: self.fail("a saved reading must not call the AI")
            r = self.c.post(f"/api/sources/{sid}/extract", json=dict(section="work"))  # same scan again: from the cache
            self.assertEqual(r.status_code, 200); self.assertTrue(r.json["cached"]); self.assertEqual(r.json["data"], DEMO["work"])
            self.assertEqual(len(sent), 1)
            aletheia.app.config["VISION_TRANSPORT"] = lambda *a: {"candidates": []}
            self.assertEqual(self.c.post(f"/api/sources/{sid}/extract", json=dict(section="work", fresh=True)).status_code, 400)
            self.assertIn("limit", self.c.post(f"/api/sources/{sid}/extract", json=dict(section="work", fresh=True)).json["error"][0])
        finally:
            os.environ.pop("GEMINI_API_KEY"); os.environ.pop("ALETHEIA_DAILY_CALL_LIMIT")
        self.assertEqual(self.c.delete(f"/api/sources/{sid}").status_code, 200); self.assertEqual(self.get(i)["sources"], [])


    def test_openai_compatible_reader_renders_pdf_pages(self):
        from reportlab.pdfgen import canvas
        buf = io.BytesIO(); pdf = canvas.Canvas(buf)
        for t in ("page one", "page two"): pdf.drawString(72, 720, t); pdf.showPage()
        pdf.save()
        i = self.job(); sid = self.c.post(f"/api/jobs/{i}/sources", json=dict(section="work", **up("sheet.pdf", buf.getvalue()))).json["id"]
        os.environ.update(AI_BASE_URL="http://localhost:8000/v1", AI_MODEL="qwen2.5vl:7b"); sent = []
        try:
            def fake(model, key, body):
                sent.append(body)
                fenced = "```json\n" + json.dumps({"data": DEMO["work"], "uncertain": []}) + "\n```"  # models often wrap JSON in fences
                return {"choices": [{"message": {"content": fenced}}]}
            aletheia.app.config["VISION_TRANSPORT"] = fake
            r = self.c.post(f"/api/sources/{sid}/extract", json=dict(section="work")); self.assertEqual(r.status_code, 200, r.json)
            self.assertEqual(r.json["data"], DEMO["work"])
            imgs = [p for p in sent[0]["messages"][0]["content"] if p["type"] == "image_url"]
            self.assertEqual(len(imgs), 2); self.assertTrue(imgs[0]["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertEqual(sent[0]["model"], "qwen2.5vl:7b")
        finally:
            for v in ("AI_BASE_URL", "AI_MODEL"): os.environ.pop(v)


if __name__ == "__main__":
    unittest.main()
