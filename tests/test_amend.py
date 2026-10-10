"""Integrity after release: manifest, amendments that supersede, retention packages, backups (NEXT_STEPS.md 6.2, 6.5, 6.6)."""
import hashlib, io, json, os, sqlite3, sys, unittest, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Base, DEMO, PW, _tmp, aletheia, integrity, pdf_text, signed_in, up  # noqa: E402

os.environ["ALETHEIA_BACKUP_DIR"] = os.path.join(_tmp.name, "backups")


class Released(Base):
    def released(self):
        i = self.c.post("/api/demo").json["id"]; self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        self.assertEqual(self.approve(i).status_code, 200); return i

    def open_amendment(self, i, sections=("temp",), reason="Hot resistance HV misread at hour 12"):
        return signed_in("r.viewer").post(f"/api/jobs/{i}/amend", json=dict(reason=reason, sections=list(sections), password=PW,
                                                                              second=dict(username="p.naveen", password=PW)))


class Manifest(Released):
    def test_every_version_carries_a_printed_manifest(self):
        i = self.released(); r = self.get(i)["reports"][0]
        v = self.c.get("/api/verify/" + r["token"]).json
        self.assertTrue(v["manifest_ok"]); self.assertEqual(v["manifest_sha256"], r["manifest_sha256"])
        temp = next(s for s in v["sections"] if s["test"] == "Temperature-Rise Test Logsheet")
        self.assertEqual((temp["uploaded_by"], temp["verified_by"]), ("T. Rao", "S. Iyer")); self.assertEqual(len(temp["data_sha256"]), 64)
        text = pdf_text(self.c.get(f"/api/jobs/{i}/report.pdf").data)
        self.assertIn("Traceability of this report", text); self.assertIn(r["manifest_sha256"][:40], text.replace(" ", ""))
        with aletheia.db() as c: m = c.execute("SELECT manifest FROM reports WHERE job_id=? AND approver IS NOT NULL", (i,)).fetchone()[0]
        self.assertEqual(integrity.sha(m), r["manifest_sha256"])


class Amendment(Released):
    def test_opening_needs_reason_tests_own_password_and_a_second_approver(self):
        i = self.released(); ap = signed_in("r.viewer")
        base = dict(reason="Hot resistance HV misread at hour 12", sections=["temp"], password=PW, second=dict(username="p.naveen", password=PW))
        for change, status in ((dict(reason="typo"), 400), (dict(sections=[]), 400), (dict(password="wrong password"), 403),
                               (dict(second=dict(username="r.viewer", password=PW)), 403), (dict(second=dict(username="s.iyer", password=PW)), 403),  # a tester cannot second-sign
                               (dict(second=dict(username="p.naveen", password="nope nope")), 403)):
            self.assertEqual(ap.post(f"/api/jobs/{i}/amend", json=dict(base, **change)).status_code, status, change)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/amend", json=base).status_code, 403)  # testers cannot amend
        self.assertTrue(self.get(i)["released"])
        with aletheia.db() as c: self.assertEqual(c.execute("SELECT failed_attempts FROM users WHERE username='p.naveen'").fetchone()[0], 1)

    def test_amendment_reopens_only_the_named_tests_and_supersedes_on_release(self):
        i = self.released(); old = self.get(i)["reports"][0]
        self.assertEqual(self.open_amendment(i).status_code, 200)
        j = self.get(i)
        self.assertFalse(j["released"]); self.assertEqual(j["amend"]["sections"], ["temp"])
        self.assertEqual(j["meta"]["temp"]["state"], "returned"); self.assertEqual(j["meta"]["sc"]["state"], "verified")
        self.assertEqual(self.c.post(f"/api/jobs/{i}/import", json=dict(filename="sc.json", content={"sc": DEMO["sc"]})).status_code, 409)  # not amended
        with self.assertRaises(sqlite3.IntegrityError):  # outside the amendment, also refused by the database
            with aletheia.db() as c: c.execute("UPDATE sections SET note='x' WHERE job_id=? AND key='sc'", (i,))
        with self.assertRaises(sqlite3.IntegrityError):  # what was released stays: files, history, the job itself
            with aletheia.db() as c: c.execute("DELETE FROM files WHERE job_id=?", (i,))
        self.assertEqual(self.drop(i).status_code, 409)
        v = self.c.get("/api/verify/" + old["token"]).json
        self.assertTrue(v["approved"]); self.assertIsNone(v["superseded_by"])  # the released version stands until replaced
        t = dict(DEMO["temp"], rhv_hot=4.0412)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t, revision=j["meta"]["temp"]["revision"])).status_code, 200)
        self.c.post(f"/api/jobs/{i}/validate"); self.assertEqual(self.gen(i).status_code, 200)
        self.assertEqual(self.approve(i, "p.naveen").status_code, 403)  # P. Naveenkumar is the engineer on the work instruction
        ok = self.approve(i, "r.viewer")  # opening the amendment is not working on the data: r.viewer may release it
        self.assertEqual(ok.status_code, 200, ok.json)
        j = self.get(i); self.assertTrue(j["released"]); self.assertIsNone(j["amend"]); self.assertIsNotNone(j["amendments"][0]["closed_at"])
        v = self.c.get("/api/verify/" + old["token"]).json
        self.assertFalse(v["approved"]); self.assertEqual(v["superseded_by"], ok.json["version"]); self.assertIn("misread", v["amendment"]["reason"])
        d = self.c.get(f"/api/verify/{old['token']}/report.pdf"); self.assertEqual(d.status_code, 200)
        self.assertIn("_SUPERSEDED", d.headers["Content-Disposition"]); self.assertEqual(hashlib.sha256(d.data).hexdigest(), old["sha256"])
        text = pdf_text(self.c.get(f"/api/jobs/{i}/report.pdf").data); self.assertIn("supersedes version", text)

    def test_approver_who_opened_it_may_still_release_and_customers_see_both_versions(self):
        oid = self.admin.post("/api/orgs", json=dict(name="A.P. Transformers")).json["id"]
        with aletheia.db() as c:
            from werkzeug.security import generate_password_hash
            if not c.execute("SELECT 1 FROM users WHERE username='ap.c2'").fetchone():
                c.execute("INSERT INTO users(username,full_name,roles,org_id,password_hash,must_change_password,created_at) VALUES('ap.c2','AP','customer',?,?,0,'x')",
                          (oid, generate_password_hash(PW)))
        i = self.released(); self.open_amendment(i, ["request"], reason="Customer address PIN was wrong on the form")
        self.assertIsNone(self.get(i)["intake"]["checked_by"])  # the intake must be read back again
        plan = self.get(i)["plan"] or ["temp"]  # the customer sends a corrected request; the laboratory links it to the job
        r = self.c.post(f"/api/jobs/{i}/intake", json=dict(__import__("test_app").LAB, customer_form_id=self.request(plan), plan=plan)); self.assertEqual(r.status_code, 200, r.json)
        self.c.post(f"/api/jobs/{i}/validate")
        for n, f in enumerate(self.get(i)["findings"]):
            if f["level"] == "warn" and not f.get("advisory"): self.c.post(f"/api/jobs/{i}/review", json=dict(index=n))
        self.admin.post(f"/api/jobs/{i}/signoff"); self.assertEqual(self.admin.post(f"/api/jobs/{i}/generate").status_code, 200)
        r = self.approve(i); self.assertEqual(r.status_code, 409); self.assertIn("checked against", " ".join(r.json["error"]))  # intake not read back
        self.c.post(f"/api/jobs/{i}/intake/checked"); self.assertEqual(self.approve(i).status_code, 200)
        cust = signed_in("ap.c2").get(f"/api/jobs/{i}").json
        self.assertEqual([v["superseded"] for v in cust["versions"]], [False, True])
        self.assertIn("PIN", cust["versions"][1]["amendment_reason"])
        self.assertEqual(signed_in("ap.c2").get(f"/api/jobs/{i}/report.pdf?v={cust['versions'][1]['version']}").status_code, 200)


class Retention(Released):
    def test_package_contains_everything_needed_to_verify(self):
        i = self.released(); r = self.get(i)["reports"][0]
        self.assertEqual(self.c.get(f"/api/jobs/{self.job('CPRIBLRSCL25T1700')}/package.zip").status_code, 409)  # never released
        z = zipfile.ZipFile(io.BytesIO(self.c.get(f"/api/jobs/{i}/package.zip").data)); names = z.namelist()
        pdf = next(n for n in names if n.startswith("report/") and n.endswith(".pdf"))
        self.assertEqual(hashlib.sha256(z.read(pdf)).hexdigest(), r["sha256"])
        self.assertEqual(hashlib.sha256(z.read(f"report/manifest_v{r['version']}.json")).hexdigest(), r["manifest_sha256"])
        self.assertTrue(any(n.startswith("source-data/") for n in names)); self.assertTrue(any(n.startswith("source-documents/") for n in names))
        self.assertIn("record/audit.csv", names); self.assertIn("README.txt", names)
        for line in z.read("SHA256SUMS.txt").decode().splitlines():
            h, n = line.split("  ", 1); self.assertEqual(hashlib.sha256(z.read(n)).hexdigest(), h, n)

    def test_backup_check_and_tamper_detection(self):
        i = self.released()
        self.assertEqual(self.c.post("/api/admin/backups").status_code, 403)
        b = self.admin.post("/api/admin/backups"); self.assertEqual(b.status_code, 201); b = b.json
        self.assertTrue(b["chain_ok"]); self.assertEqual(len(b["audit_tip"]), 64)
        self.assertIn(b["name"], [x["name"] for x in self.admin.get("/api/admin/backups").json["backups"]])
        ok = self.admin.get(f"/api/admin/backups/{b['name']}/check").json
        self.assertTrue(ok["ok"], ok); self.assertEqual(ok["counts"]["jobs"], 1)
        tips = [f for f in os.listdir(os.environ["ALETHEIA_BACKUP_DIR"]) if f.startswith("audit-tip-")]; self.assertTrue(tips)
        path = os.path.join(os.environ["ALETHEIA_BACKUP_DIR"], b["name"])
        c = sqlite3.connect(path)
        try:
            integrity.drop_triggers(c); c.execute("UPDATE reports SET pdf=? WHERE approver IS NOT NULL", (b"%PDF forged",)); c.commit()
        finally: c.close()
        bad = self.admin.get(f"/api/admin/backups/{b['name']}/check").json
        self.assertFalse(bad["ok"]); self.assertFalse(bad["checksum_matches"]); self.assertTrue(bad["reports_altered"])
        self.assertEqual(self.admin.get("/api/admin/backups/../aletheia.db/check").status_code, 404)
        t = self.admin.get("/api/audit/tip").json; self.assertTrue(t["chain_ok"])


if __name__ == "__main__":
    unittest.main()
