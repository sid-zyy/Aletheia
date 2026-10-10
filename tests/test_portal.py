"""Customer portal, partial reports, notifications and the same-day target (NEXT_STEPS.md section 7, test plan in 11)."""
import datetime as dt, io, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Base, DEMO, INTAKE, PW, aletheia, pdf_text, signed_in, up  # noqa: E402
import notify, seed_templates as S, xltemplates as X  # noqa: E402

PARTS = {k: v for k, v in DEMO.items() if k != "request"}


class Portal(Base):
    def setUp(self):
        super().setUp()
        self.org = self.admin.post("/api/orgs", json=dict(name="A.P. Transformers")).json["id"]
        from werkzeug.security import generate_password_hash
        with aletheia.db() as c:
            if not c.execute("SELECT 1 FROM users WHERE username='ap.portal'").fetchone():
                c.execute("INSERT INTO users(username,full_name,roles,org_id,email,password_hash,must_change_password,created_at) VALUES(?,?,?,?,?,?,0,'x')",
                          ("ap.portal", "AP Portal", "customer", self.org, "buyer@ap.example", generate_password_hash(PW)))
            c.execute("UPDATE users SET email=? WHERE username='s.iyer'", ("s.iyer@lab.example",))
            c.execute("UPDATE users SET email_opt_out=0")
            c.execute("DELETE FROM notifications"); c.execute("DELETE FROM outbox"); c.execute("DELETE FROM settings"); c.execute("DELETE FROM customer_forms")
            from test_app import integrity; integrity.drop_triggers(c); c.execute("DELETE FROM partials"); integrity.install_triggers(c)
        self.cust = signed_in("ap.portal"); self.v = signed_in("s.iyer")
        aletheia.app.config.pop("MAIL_TRANSPORT", None)

    def job_for_customer(self):
        r = self.c.post("/api/intake", json=dict(INTAKE, org_id=self.org, plan=["proforma", "temp", "sc"], confirm_warnings=True))
        self.assertEqual(r.status_code, 201, r.json); i = r.json["id"]
        self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content={k: PARTS[k] for k in ("proforma", "temp", "sc")}))
        return i

    def verify(self, i, k): return self.v.post(f"/api/jobs/{i}/sections/{k}/verify", json=dict(revision=self.get(i)["meta"][k]["revision"]))

    def notes(self, username, kind=None):
        with aletheia.db() as c:
            return [dict(r) for r in c.execute("SELECT n.* FROM notifications n JOIN users u ON u.id=n.user_id WHERE u.username=?" + (" AND n.kind=?" if kind else ""),
                                               (username, kind) if kind else (username,))]


class Values(Portal):
    def test_only_approved_tests_show_numbers(self):
        i = self.job_for_customer()
        self.assertEqual(self.cust.get(f"/api/jobs/{i}/approved-values").json, [])
        self.assertEqual(self.cust.get(f"/api/jobs/{i}/partial.pdf").status_code, 404)
        self.assertEqual(self.verify(i, "sc").status_code, 200)
        vals = self.cust.get(f"/api/jobs/{i}/approved-values").json
        self.assertEqual([v["key"] for v in vals], ["sc"])
        shots = next(x for x in vals[0]["items"] if x["label"] == "Oscillograms"); self.assertIn("Peak (kA)", shots["columns"]); self.assertEqual(shots["rows"][1][0], "S002")
        self.assertIn({"label": "Date of test", "value": "31-10-2025"}, vals[0]["items"])
        everything = json.dumps(self.cust.get(f"/api/jobs/{i}").json) + json.dumps(vals)
        self.assertNotIn("26.01", everything); self.assertNotIn("2930", everything)  # temp and proforma are not approved: no numbers
        p = pdf_text(self.cust.get(f"/api/jobs/{i}/partial.pdf").data)
        self.assertIn("PARTIAL REPORT, NOT FINAL", p); self.assertIn("Pending: not yet approved", p); self.assertIn("S002", p)
        self.assertNotIn("Statement of conformity", p); self.assertNotIn("Naveenkumar", p); self.assertNotIn("Approved by", p)
        self.assertNotIn("49.0", p)  # the temperature readings are not approved yet

    def test_partial_report_versions_follow_the_approved_set(self):
        i = self.job_for_customer(); self.verify(i, "sc"); self.verify(i, "proforma")
        ps = self.cust.get(f"/api/jobs/{i}/partials").json; self.assertEqual([p["version"] for p in ps], [2, 1])
        self.assertEqual(len(ps[0]["sections"]), 2)
        self.v.post(f"/api/jobs/{i}/sections/sc/reopen", json=dict(reason="peak column shifted by one row"))
        ps = self.cust.get(f"/api/jobs/{i}/partials").json; self.assertEqual(ps[0]["version"], 3); self.assertEqual([s["key"] for s in ps[0]["sections"]], ["proforma"])
        self.assertNotIn("S002", pdf_text(self.cust.get(f"/api/jobs/{i}/partial.pdf").data))  # reopened: its values are gone again
        self.assertIn("S002", pdf_text(self.cust.get(f"/api/jobs/{i}/partial.pdf?v=1").data))  # what the customer saw then stays reproducible
        self.assertEqual(self.cust.get(f"/api/jobs/{i}").json["partials"][0]["version"], 3)


class Notifications(Portal):
    def test_who_hears_about_what(self):
        i = self.job_for_customer()
        self.assertTrue([n for n in self.notes("s.iyer", "uploaded") if "waiting for verification" in n["message"]])
        self.assertTrue(self.notes("ap.portal", "progress")); self.assertFalse(self.notes("t.rao", "uploaded"))  # not about one's own upload
        self.v.post(f"/api/jobs/{i}/sections/temp/return", json=dict(revision=self.get(i)["meta"]["temp"]["revision"], reason="hour 7 top oil differs"))
        self.assertIn("hour 7 top oil differs", self.notes("t.rao", "returned")[0]["message"])
        self.verify(i, "sc"); self.assertTrue(self.notes("ap.portal", "approved"))
        n = self.c.get("/api/notifications").json; self.assertGreaterEqual(n["unread"], 1)
        self.c.post("/api/notifications/read", json=dict(all=True)); self.assertEqual(self.c.get("/api/notifications").json["unread"], 0)

    def test_email_outbox_sends_retries_and_never_blocks(self):
        self.admin.post("/api/settings", json=dict(smtp_host="mail.lab.local", smtp_sender="aletheia@lab.local"))
        sent, fail = [], {"on": True}
        def transport(msg):
            if fail["on"]: raise OSError("connection refused")
            sent.append(msg)
        aletheia.app.config["MAIL_TRANSPORT"] = transport
        i = self.job_for_customer()  # the upload works although every email fails
        notify.send_pending()
        with aletheia.db() as c: row = c.execute("SELECT * FROM outbox WHERE to_addr='buyer@ap.example'").fetchone()
        self.assertEqual(row["attempts"], 1); self.assertIn("connection refused", row["last_error"]); self.assertGreater(row["next_try"], aletheia.now())
        fail["on"] = False
        with aletheia.db() as c: c.execute("UPDATE outbox SET next_try=?", (aletheia.now(),))
        self.assertGreaterEqual(notify.send_pending(), 2)
        to_customer = [m for m in sent if m["To"] == "buyer@ap.example"]; self.assertTrue(to_customer)
        body = to_customer[0].get_content()
        self.assertIn(self.get(i)["series"], to_customer[0]["Subject"]); self.assertIn("does not contain test results", body)
        for v in ("433.06", "26.01", "2930"): self.assertNotIn(v, body)
        self.assertFalse(to_customer[0].is_multipart())  # no attachments
        self.assertEqual(self.admin.get("/api/outbox").status_code, 200); self.assertEqual(self.c.get("/api/outbox").status_code, 403)

    def test_customer_can_opt_out_of_non_critical_email(self):
        self.admin.post("/api/settings", json=dict(smtp_host="mail.lab.local"))
        self.cust.post("/api/me/preferences", json=dict(email_opt_out=True))
        i = self.job_for_customer()
        with aletheia.db() as c: self.assertFalse(c.execute("SELECT 1 FROM outbox WHERE to_addr='buyer@ap.example'").fetchone())
        self.assertEqual(self.notes("ap.portal", "progress")[0]["email_status"], "none")  # still told in the portal


class SameDay(Portal):
    def test_cutoff_board_carry_over_and_same_day_flag(self):
        self.assertEqual(self.c.post("/api/settings", json=dict(cutoff_time="17:30")).status_code, 403)
        self.assertEqual(self.admin.post("/api/settings", json=dict(cutoff_time="25:00")).status_code, 400)
        self.admin.post("/api/settings", json=dict(cutoff_time="17:30", warn_minutes="90"))
        with aletheia.db() as c:
            self.assertEqual(notify.cutoff_for(c, "2026-10-10T09:00"), "2026-10-10T17:30")
            self.assertEqual(notify.cutoff_for(c, "2026-10-10T19:10"), "2026-10-11T17:30")  # arrived after the cut-off (Q12)
        i = self.job_for_customer(); self.assertTrue(self.get(i)["cutoff"].endswith("17:30"))
        later = (dt.datetime.now() + dt.timedelta(hours=5)).isoformat(timespec="minutes"); soon = (dt.datetime.now() + dt.timedelta(minutes=30)).isoformat(timespec="minutes")
        past = (dt.datetime.now() - dt.timedelta(minutes=10)).isoformat(timespec="minutes")
        for when, want in ((later, "green"), (soon, "amber"), (past, "red")):
            with aletheia.db() as c: c.execute("UPDATE jobs SET cutoff=? WHERE id=?", (when, i))
            b = next(x for x in self.c.get("/api/today").json["jobs"] if x["id"] == i); self.assertEqual(b["status"], want, when)
        self.assertTrue(b["carried_over"]); self.assertEqual([x["name"] for x in b["awaiting_verification"]], [p["name"] for p in self.get(i)["progress"]])
        self.assertEqual(self.c.post(f"/api/jobs/{i}/carry-over", json=dict(reason="")).status_code, 400)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/carry-over", json=dict(reason="SC bay down after 15:00")).status_code, 200)
        self.assertEqual(next(x for x in self.c.get("/api/today").json["jobs"] if x["id"] == i)["carry_reason"], "SC bay down after 15:00")
        with aletheia.db() as c: c.execute("UPDATE jobs SET cutoff_warned=0 WHERE id=?", (i,))
        notify.cutoff_sweep(); notify.cutoff_sweep()
        self.assertEqual(len(self.notes("s.iyer", "cutoff")), 1)  # warned once
        self.assertEqual(self.cust.get("/api/today").status_code, 403)

    def test_release_records_whether_it_was_same_day(self):
        i = self.c.post("/api/demo").json["id"]
        with aletheia.db() as c: c.execute("UPDATE jobs SET cutoff=? WHERE id=?", ((dt.datetime.now() + dt.timedelta(hours=2)).isoformat(timespec="minutes"), i))
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i); self.approve(i)
        j = self.get(i); self.assertEqual(j["same_day"], 1); self.assertIsNotNone(j["completed_at"])


class RequestForms(Portal):
    def test_customer_sends_the_form_and_intake_uses_it(self):
        blank = self.cust.get("/api/request-form.xlsx").data
        filled = X.workbook([(S.request_form(), {"customer": "A.P. Transformers", "pin": "600058", "city": "Chennai"}, None)])
        self.assertEqual(self.c.post("/api/customer/request-forms", json=up("form.xlsx", filled)).status_code, 403)  # staff record intake directly
        self.assertEqual(self.cust.post("/api/customer/request-forms", json=up("form.pdf", b"%PDF-1.4")).status_code, 400)
        r = self.cust.post("/api/customer/request-forms", json=up("our request.xlsx", filled)); self.assertEqual(r.status_code, 201); fid = r.json["id"]
        self.assertTrue(blank.startswith(b"PK"))
        self.assertTrue(self.notes("t.rao", "form"))
        inbox = self.c.get("/api/request-forms").json; self.assertEqual((inbox[0]["org"], inbox[0]["status"]), ("A.P. Transformers", "received"))
        vals = self.c.post(f"/api/request-forms/{fid}/read").json; self.assertEqual(vals["values"]["pin"], "600058"); self.assertEqual(vals["org_id"], self.org)
        j = self.c.post("/api/intake", json=dict(INTAKE, org_id=self.org, plan=["sc"], customer_form_id=fid, confirm_warnings=True)).json["id"]
        mine = self.cust.get("/api/customer/request-forms").json; self.assertEqual((mine[0]["status"], mine[0]["series"]), ("used", self.get(j)["series"]))
        with aletheia.db() as c:  # the customer's file is kept with the record, byte for byte
            f = c.execute("SELECT name, content FROM files WHERE job_id=?", (j,)).fetchone()
        self.assertEqual((f["name"], f["content"]), ("Customer request form - our request.xlsx", filled))
    def test_customer_fills_in_the_request_online(self):
        body = {k: v for k, v in INTAKE.items() if k not in ("arrived_at", "opened_by")}
        bad = self.cust.post("/api/customer/requests/check", json=dict(body, pin="5600", plan=[])).json
        self.assertFalse(bad["ok"]); self.assertTrue(any("PIN" in e for e in bad["errors"])); self.assertTrue(any("tick at least one" in e for e in bad["errors"]))
        self.assertFalse(any("Arrival" in e or "opened" in e for e in bad["errors"]))  # the laboratory records those
        self.assertEqual(self.cust.post("/api/customer/requests", json=dict(body, pin="5600", plan=["sc"])).status_code, 400)
        self.assertEqual(self.c.post("/api/customer/requests", json=dict(body, plan=["sc"])).status_code, 403)
        r = self.cust.post("/api/customer/requests", json=dict(body, plan=["sc", "temp"])); self.assertEqual(r.status_code, 201, r.json)
        inbox = self.c.get("/api/request-forms").json[0]; self.assertEqual(inbox["kind"], "web")
        vals = self.c.post(f"/api/request-forms/{inbox['id']}/read").json
        self.assertEqual((vals["values"]["pin"], vals["plan"], vals["org_id"]), ("600058", ["sc", "temp"], self.org))
        self.assertTrue(self.admin.get("/api/my-work").json["requests"])
        j = self.c.post("/api/intake", json=dict(INTAKE, org_id=self.org, plan=vals["plan"], customer_form_id=inbox["id"], confirm_warnings=True)).json["id"]
        with aletheia.db() as c: f = c.execute("SELECT name FROM files WHERE job_id=?", (j,)).fetchone()
        self.assertEqual(f["name"], "Customer request (filled online).json")
        self.assertEqual(self.cust.get("/api/customer/request-forms").json[0]["status"], "used")


if __name__ == "__main__":
    unittest.main()
