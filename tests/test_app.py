"""Run from the project folder:  python -m unittest discover -s tests -v"""
import base64, io, json, os, sqlite3, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.TemporaryDirectory()
os.environ["ALETHEIA_DB"] = os.path.join(_tmp.name, "test.db")
for _v in ("GEMINI_API_KEY", "GEMINI_MODEL", "AI_BASE_URL", "AI_MODEL", "AI_API_KEY", "AI_PROVIDER", "AI_NUM_CTX", "AI_IMAGE_PX"): os.environ.pop(_v, None)
import app as aletheia, importers, vision  # noqa: E402

SD = os.path.join(ROOT, "sample_data")
DEMO = json.load(open(os.path.join(SD, "AP_Transformers_25T1654.json")))
raw = lambda n: open(os.path.join(SD, n), "rb").read()
up = lambda name, data: dict(filename=name, b64=base64.b64encode(data).decode())
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class Base(unittest.TestCase):
    def setUp(self):
        with aletheia.db() as c:
            for t in ("jobs", "imports", "audit", "sources", "reports", "vision_calls"): c.execute(f"DELETE FROM {t}")
        self.c = aletheia.app.test_client(); aletheia.app.config.pop("VISION_TRANSPORT", None)

    def gen(self, i):
        """Review every flagged item one by one, as the engineer does, then build the report."""
        for n, f in enumerate(self.get(i)["findings"]):
            if f["level"] == "warn" and not f.get("reviewed"): self.c.post(f"/api/jobs/{i}/review", json=dict(index=n))
        return self.c.post(f"/api/jobs/{i}/generate")

    def job(self, series="CPRIBLRSCL25T1654"):
        r = self.c.post("/api/jobs", json=dict(series=series, sample="HVD25S0847", customer="A.P. Transformers", rating="250 kVA", request=DEMO["request"]))
        self.assertEqual(r.status_code, 201, r.json); return r.json["id"]

    def get(self, i): return self.c.get(f"/api/jobs/{i}").json


class ImportFormats(Base):
    def test_flat_layout_round_trips_exactly(self):
        rows = [(s, f, importers._cell(v)) for s, f, v in importers.flatten(DEMO)]
        self.assertEqual(importers.unflatten(rows)[0], DEMO)
        self.assertEqual(DEMO["request"]["serial"], "1098")  # text that looks like a number must stay text

    def test_csv_xlsx_and_database_give_same_data_as_json(self):
        want = {k: v for k, v in DEMO.items()}
        for name in ("AP_Transformers_25T1654.csv", "AP_Transformers_25T1654.xlsx", "AP_Transformers_25T1654_lab.db"):
            i = self.job(); r = self.c.post(f"/api/jobs/{i}/import", json=up(name, raw(name)))
            self.assertEqual(r.status_code, 200, r.json)
            self.assertEqual(self.get(i)["data"], want, name)
            self.c.delete(f"/api/jobs/{i}")

    def test_csv_import_runs_through_to_approved_report(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("lab.csv", raw("AP_Transformers_25T1654.csv")))
        f = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        self.assertFalse([x for x in f if x["level"] == "fail"]); self.assertEqual(len(f), 30)
        g = self.gen(i).json; self.assertEqual(g["version"], 1)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/approve", json=dict(name="Reviewer", employee_id="E1042")).json["version"], 2)
        pdf = self.c.get(f"/api/jobs/{i}/report.pdf"); self.assertTrue(pdf.data.startswith(b"%PDF"))
        j = self.get(i); self.assertEqual(j["stage"], 4); self.assertEqual(j["imports"][0]["kind"], "csv")

    def test_approval_needs_name_and_employee_id(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("lab.csv", raw("AP_Transformers_25T1654.csv")))
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        for b in (dict(name="Reviewer"), dict(name="Reviewer", employee_id="  "), dict(employee_id="E1042"),
                  dict(name="Reviewer", employee_id="E 1042; drop"), dict(name="Reviewer", employee_id="X")):
            r = self.c.post(f"/api/jobs/{i}/approve", json=b)
            self.assertEqual(r.status_code, 400, b); self.assertEqual(self.get(i)["stage"], 3, b)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/approve", json=dict(name="Reviewer", employee_id="cpri/sc-1042")).status_code, 200)
        j = self.get(i); self.assertEqual((j["approver"], j["approver_id"]), ("Reviewer", "CPRI/SC-1042"))
        self.assertEqual(j["reports"][0]["approver_id"], "CPRI/SC-1042")
        self.assertIn("Approved by Reviewer (Employee ID CPRI/SC-1042)", j["audit"][-1]["event"])
        self.assertEqual(self.c.get("/api/verify/" + j["reports"][0]["token"]).json["approver_id"], "CPRI/SC-1042")
        self.c.post(f"/api/jobs/{i}/discard")  # withdrawing the report clears the approval, ID included
        self.assertEqual((self.get(i)["approver"], self.get(i)["approver_id"]), (None, None))

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
        i = self.job(); sid = self.c.post(f"/api/jobs/{i}/sources", json=up("scan.png", PNG)).json["id"]
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
        self.assertTrue([x for x in f if x["check"] == "Additional record: Noise level test" and x["level"] == "warn"])
        self.assertTrue([x for x in f if x["check"] == "Identifier consistency" and "Noise level test" in x["detail"]])  # 25T1656 vs 25T1654
        self.assertEqual(self.gen(i).status_code, 200)
        j2 = self.job("CPRIBLRSCL25T1999")  # exported CSV, including the extra sheet, imports into another job unchanged
        self.c.post(f"/api/jobs/{j2}/import", json=up("x.csv", self.c.get(f"/api/jobs/{i}/export/csv").data))
        self.assertEqual(self.get(j2)["data"]["other"], self.get(i)["data"]["other"])
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/other:{key}").status_code, 200); self.assertNotIn("other", self.get(i)["data"])
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/other:{key}").status_code, 404)

    def test_new_request_from_a_data_file(self):
        csv = raw("AP_Transformers_25T1654.csv")
        r = self.c.post("/api/jobs/from-file", json=up("job.csv", csv)); self.assertEqual(r.status_code, 201, r.json)
        j = self.get(r.json["id"])
        self.assertEqual((j["series"], j["sample"], j["customer"]), ("CPRIBLRSCL25T1654", "HVD25S0847", "A.P. Transformers"))
        self.assertEqual(len([k for k in j["data"] if k != "ids"]), 10)
        self.assertEqual(self.c.post("/api/jobs/from-file", json=up("job.csv", csv)).status_code, 409)  # same series again
        r = self.c.post("/api/jobs/from-file", json=dict(series="CPRIBLRSCL25T2001", **up("job.csv", csv)))  # typed series wins
        self.assertEqual(r.status_code, 201); self.assertEqual(self.get(r.json["id"])["series"], "CPRIBLRSCL25T2001")
        no_series = b"section,field,value" + bytes([10]) + b"proforma,kva,250" + bytes([10])
        self.assertEqual(self.c.post("/api/jobs/from-file", json=up("x.csv", no_series)).status_code, 400)  # no series

    def test_read_a_request_scan_before_the_job_exists(self):
        os.environ.update(GEMINI_API_KEY="test")
        try:
            aletheia.app.config["VISION_TRANSPORT"] = lambda *a: {"candidates": [{"content": {"parts": [{"text": json.dumps({"data": DEMO["request"], "uncertain": []})}]}}]}
            r = self.c.post("/api/read-scan", json=dict(section="request", **up("Customer request form.png", PNG))); self.assertEqual(r.status_code, 200, r.json)
            self.assertEqual(r.json["data"]["customer"], "A.P. Transformers")
        finally:
            os.environ.pop("GEMINI_API_KEY")

    def test_review_one_by_one_before_the_report(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("d.json", raw("AP_Transformers_25T1654.json")))
        F = self.c.post(f"/api/jobs/{i}/validate").json["findings"]; warns = [n for n, f in enumerate(F) if f["level"] == "warn"]
        self.assertEqual(self.c.post(f"/api/jobs/{i}/generate").status_code, 409)  # nothing reviewed yet
        self.c.post(f"/api/jobs/{i}/review", json=dict(index=warns[0]))
        self.assertIn(f"{len(warns) - 1} left", self.c.post(f"/api/jobs/{i}/generate").json["error"][0])
        F = self.c.post(f"/api/jobs/{i}/validate").json["findings"]  # unchanged items keep their review
        self.assertTrue(F[warns[0]].get("reviewed"))
        passed = [n for n, f in enumerate(F) if f["level"] == "pass"][0]
        self.assertEqual(self.c.post(f"/api/jobs/{i}/review", json=dict(index=passed)).status_code, 400)
        self.assertEqual(self.gen(i).status_code, 200)
        d = json.loads(json.dumps(DEMO)); d["temp"]["hours"][-1][1] = 65.2  # top-oil rise over the limit: a failed check
        j = self.job("CPRIBLRSCL25T1998"); self.c.post(f"/api/jobs/{j}/import", json=up("f.json", json.dumps(d).encode()))
        F = self.c.post(f"/api/jobs/{j}/validate").json["findings"]; fail = [n for n, f in enumerate(F) if f["level"] == "fail"][0]
        self.assertEqual(self.c.post(f"/api/jobs/{j}/review", json=dict(index=fail)).status_code, 409)

    def test_remove_a_document(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("d.json", raw("AP_Transformers_25T1654.json")))
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/temp").status_code, 200)
        j = self.get(i); self.assertNotIn("temp", j["data"]); self.assertEqual(j["stage"], 1)  # report withdrawn, checks to redo
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/temp").status_code, 404)
        self.assertEqual(self.c.delete(f"/api/jobs/{i}/section/request").status_code, 400)
        f = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        self.assertIn("Temperature-rise logsheet", [x for x in f if x["check"] == "Completeness of source documents"][0]["detail"])

    def test_only_series_is_required(self):
        r = self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1999")); self.assertEqual(r.status_code, 201, r.json)
        j = self.get(r.json["id"]); self.assertEqual((j["sample"], j["customer"], j["rating"]), ("NA", "NA", "NA"))
        self.assertEqual(self.c.post("/api/jobs", json=dict(customer="X")).status_code, 400)
        self.assertEqual(self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1998", sample="bad")).status_code, 400)
        i = r.json["id"]; self.c.post(f"/api/jobs/{i}/section", json=dict(section="sc", data=DEMO["sc"]))
        self.assertEqual(self.c.post(f"/api/jobs/{i}/validate").status_code, 200)
        self.assertEqual(self.gen(i).status_code, 200)

    def test_export_reimports(self):
        i = self.c.post("/api/demo").json["id"]
        for fmt in ("csv", "xlsx", "sqlite", "json"):
            e = self.c.get(f"/api/jobs/{i}/export/{fmt}"); self.assertEqual(e.status_code, 200)
            n = self.job("CPRIBLRSCL25T1700"); r = self.c.post(f"/api/jobs/{n}/import", json=up("e." + {"sqlite": "db"}.get(fmt, fmt), e.data))
            if fmt == "sqlite":  # database rows carry their series, so they are refused for a different job
                self.assertEqual(r.status_code, 400); self.assertIn("other series", r.json["error"][0])
            else:
                self.assertEqual(r.status_code, 200, (fmt, r.json)); self.assertEqual(self.get(n)["data"], self.get(i)["data"])
            self.c.delete(f"/api/jobs/{n}")


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
        self.c.post(f"/api/jobs/{i}/approve", json=dict(name="R. Viewer", employee_id="E2001"))
        self.assertFalse(self.c.get("/api/verify/" + v1["token"]).json["current"])  # superseded by the approved version
        s2 = self.c.get("/api/verify/" + self.get(i)["reports"][0]["token"]).json; self.assertTrue(s2["approved"]); self.assertEqual(s2["version"], 2)
        with aletheia.db() as c: c.execute("UPDATE reports SET pdf=? WHERE version=2", (b"%PDF tampered",))
        self.assertFalse(self.c.get("/api/verify/" + self.get(i)["reports"][0]["token"]).json["intact"])
        self.assertEqual(self.c.get("/api/verify/nope").status_code, 404)

    def test_editing_data_withdraws_report(self):
        i = self.ready(); t = dict(DEMO["temp"]); t["rhv_hot"] = t["rhv_hot"] * 1.01
        self.assertEqual(self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t)).status_code, 200)
        self.assertEqual(self.get(i)["stage"], 1); self.assertEqual(self.c.get(f"/api/jobs/{i}/report.pdf").status_code, 409)
        f = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        self.assertTrue([x for x in f if x["level"] == "fail" and "HV winding" in x["check"]])  # 0.3 K margin is gone

    def test_report_for_hand_entered_request_without_optional_fields(self):
        i = self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1654", sample="HVD25S0847", customer="X", rating="250 kVA")).json["id"]
        self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content={k: v for k, v in DEMO.items() if k != "request"}))
        self.c.post(f"/api/jobs/{i}/validate"); self.assertEqual(self.gen(i).status_code, 200)

    def test_sources_and_ai_reading(self):
        i = self.job(); r = self.c.post(f"/api/jobs/{i}/sources", json=up("scan.png", PNG)); self.assertEqual(r.status_code, 201); sid = r.json["id"]
        self.assertEqual(self.c.post(f"/api/jobs/{i}/sources", json=up("copy.png", PNG)).status_code, 409)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/sources", json=up("x.exe", b"MZ....")).status_code, 400)
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
        i = self.job(); sid = self.c.post(f"/api/jobs/{i}/sources", json=up("sheet.pdf", buf.getvalue())).json["id"]
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
