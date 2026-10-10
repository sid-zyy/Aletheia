"""Customer portal, partial reports and notifications (NEXT_STEPS.md section 7, test plan in 11)."""
import datetime as dt, io, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import LAB, REQUEST, Base, DEMO, PW, aletheia, pdf_text, signed_in, up  # noqa: E402
import notify, seed_templates as S, xltemplates as X  # noqa: E402

PARTS = {k: v for k, v in DEMO.items() if k != "request"}


class Portal(Base):
    def setUp(self):
        super().setUp()
        with aletheia.db() as c:  # the customer (ap.portal, A.P. Transformers) comes from test_app
            c.execute("UPDATE users SET email=? WHERE username='s.iyer'", ("s.iyer@lab.example",))
            c.execute("UPDATE users SET email_opt_out=0")
            c.execute("DELETE FROM notifications"); c.execute("DELETE FROM outbox"); c.execute("DELETE FROM settings")
            from test_app import integrity; integrity.drop_triggers(c); c.execute("DELETE FROM partials"); integrity.install_triggers(c)
        self.v = signed_in("s.iyer")
        aletheia.app.config.pop("MAIL_TRANSPORT", None)

    def job_for_customer(self):
        i = self.receive()
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
        shots = next(x for x in vals[0]["items"] if x["label"] == "S.C. Test results"); self.assertIn("Peak (kA)", shots["columns"]); self.assertEqual(shots["rows"][1][0], "S002")
        self.assertIn({"label": "Date of Test", "value": "31-10-2025"}, vals[0]["items"])
        self.assertFalse([x for x in vals[0]["items"] if x["label"] in ("Test Engineer", "Customer's Signature")])  # no staff names
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
        self.assertFalse(self.notes("t.rao", "uploaded"))  # not about one's own upload
        self.assertEqual({n["kind"] for n in self.notes("ap.portal")}, {"progress"})  # only "your request was received": no progress notices
        self.v.post(f"/api/jobs/{i}/sections/temp/return", json=dict(revision=self.get(i)["meta"]["temp"]["revision"], reason="hour 7 top oil differs"))
        self.assertIn("hour 7 top oil differs", self.notes("t.rao", "returned")[0]["message"])
        self.verify(i, "sc"); self.assertFalse(self.notes("ap.portal", "approved"))  # an approved test is not announced to the customer
        n = self.c.get("/api/notifications").json; self.assertGreaterEqual(n["unread"], 1)
        r = next(x for x in n["items"] if x["kind"] == "returned"); self.assertTrue(r["action"]); self.assertEqual(r["target"], f"job/{i}")
        self.c.post("/api/notifications/read", json=dict(all=True)); self.assertEqual(self.c.get("/api/notifications").json["unread"], 0)

    def test_customer_hears_once_when_the_report_is_released(self):
        i = self.job_for_customer(); self.c.post(f"/api/jobs/{i}/validate"); self.assertEqual(self.gen(i).status_code, 200)
        self.assertFalse(self.notes("ap.portal", "released"))  # generated, not yet signed off: not complete
        self.assertTrue(self.notes("r.viewer", "approve"))  # the other administrators are asked to sign it off
        self.assertEqual(self.approve(i).status_code, 200)
        rel = [x for x in self.cust.get("/api/notifications").json["items"] if x["kind"] == "released"]
        self.assertEqual(len(rel), 1); self.assertEqual(rel[0]["target"], f"my/{i}"); self.assertFalse(rel[0]["action"])
        self.assertIn(f"Test report {self.get(i)['series']} is ready", rel[0]["message"])

    def test_new_request_notification_opens_the_request(self):
        fid = self.request()
        n = next(x for x in self.admin.get("/api/notifications").json["items"] if x["kind"] == "form")
        self.assertEqual(n["target"], f"intake/r{fid}"); self.assertTrue(n["action"])
        self.assertEqual(self.admin.post("/api/notifications/read", json=dict(ids=[n["id"]])).status_code, 200)
        self.c.post("/api/intake", json=dict(LAB, customer_form_id=fid, plan=["proforma", "temp", "sc"]))  # accepted by someone else meanwhile
        r = self.admin.post(f"/api/request-forms/{fid}/read", json={}); self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["status"], "used"); self.assertTrue(r.json["job"]["series"].startswith("CPRIBLRSCL"))

    def test_repeats_for_one_job_become_one_row(self):
        i = self.job_for_customer(); before = self.notes("s.iyer", "uploaded")
        self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=dict(DEMO["temp"], tap="X"), revision=self.get(i)["meta"]["temp"]["revision"]))
        after = self.notes("s.iyer", "uploaded"); self.assertEqual(len(after), len(before)); self.assertEqual(after[-1]["count"], 2)

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


class NoSameDayBoard(Portal):
    def test_today_board_and_cut_off_are_gone(self):
        # the same-day target was dropped: no board, no carry-over, no cut-off setting; release still records when it finished
        self.assertEqual(self.c.get("/api/today").status_code, 404)
        i = self.c.post("/api/demo").json["id"]
        self.assertEqual(self.c.post(f"/api/jobs/{i}/carry-over", json=dict(reason="SC bay down")).status_code, 404)
        self.assertNotIn("cutoff_time", self.admin.get("/api/settings").json)
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i); self.approve(i)
        j = self.get(i); self.assertIsNotNone(j["completed_at"]); self.assertNotIn("same_day", j)


class RequestForms(Portal):
    def test_only_the_customer_raises_a_request_filled_in_as_the_printed_form(self):
        bad = self.cust.post("/api/customer/requests/check", json=dict(REQUEST, pin="5600", scrap="Yes", declare_terms=False, plan=[])).json
        self.assertFalse(bad["ok"]); e = " ".join(bad["errors"])
        for want in ("PIN", "tick at least one", "exactly one of (a) and (b)", "Declaration not accepted"): self.assertIn(want, e)
        self.assertNotIn("Arrival", e)  # the laboratory records that on receipt
        self.assertIn("Decision rule (if Yes): required", " ".join(self.cust.post("/api/customer/requests/check", json=dict(REQUEST, decision_rule="", plan=["sc"])).json["errors"]))
        self.assertTrue(self.cust.post("/api/customer/requests/check", json=dict(REQUEST, conformity="No", decision_rule="", plan=["sc"])).json["ok"])
        self.assertEqual(self.c.post("/api/customer/requests", json=dict(REQUEST, plan=["sc"])).status_code, 403)  # staff cannot raise one
        self.assertEqual(self.c.post("/api/intake", json=dict(LAB, plan=["sc"])).status_code, 400)  # nor start a job without one
        r = self.cust.post("/api/customer/requests", json=dict(REQUEST, plan=["sc", "temp"])); self.assertEqual(r.status_code, 201, r.json); fid = r.json["id"]
        self.assertTrue(self.notes("t.rao", "form")); self.assertTrue(self.admin.get("/api/my-work").json["requests"])
        inbox = self.c.get("/api/request-forms").json[0]; self.assertEqual((inbox["kind"], inbox["org"], inbox["status"]), ("web", "A.P. Transformers", "received"))
        vals = self.c.post(f"/api/request-forms/{fid}/read").json
        self.assertEqual((vals["values"]["pin"], vals["values"]["decision_rule"][:3], vals["plan"], vals["org_id"]), ("600058", "(i)", ["sc", "temp"], self.org))
        self.assertTrue(vals["values"]["signed_at"])
        # the laboratory records sheet 3; the customer's answers are taken as sent, whatever the engineer's page sends
        self.assertIn("capability", " ".join(self.c.post("/api/intake", json=dict(LAB, capability="No", customer_form_id=fid, plan=["sc"])).json["error"]))
        j = self.c.post("/api/intake", json=dict(LAB, customer="Someone else", customer_form_id=fid, plan=vals["plan"])).json["id"]
        job = self.get(j); self.assertEqual((job["customer"], job["data"]["request"]["serial"], job["intake"]["condition"]), ("A.P. Transformers", "1098", "Suitable for Testing"))
        self.assertEqual(job["intake"]["request_form_id"], fid)
        with aletheia.db() as c: f = c.execute("SELECT name FROM files WHERE job_id=?", (j,)).fetchone()
        self.assertEqual(f["name"], "Customer request (filled online).json")
        mine = self.cust.get("/api/customer/request-forms").json[0]; self.assertEqual((mine["status"], mine["series"]), ("used", job["series"]))
        self.assertEqual(self.c.post("/api/intake", json=dict(LAB, customer_form_id=fid, plan=["sc"])).status_code, 400)  # used once only

    def test_laboratory_returns_a_request_and_the_customer_corrects_it(self):
        fid = self.request(plan=["sc"], drawings="APT/250-11/001")
        self.assertEqual(self.c.post(f"/api/request-forms/{fid}/return", json=dict(reason="")).status_code, 400)
        self.assertEqual(self.c.post(f"/api/request-forms/{fid}/return", json=dict(reason="Drawing APT/250-11/001B is missing")).status_code, 200)
        self.assertIn("returned for correction", self.notes("ap.portal", "returned")[0]["message"])
        self.assertEqual(self.c.post("/api/intake", json=dict(LAB, customer_form_id=fid, plan=["sc"])).status_code, 400)
        mine = self.cust.get(f"/api/customer/requests/{fid}").json; self.assertEqual((mine["status"], mine["note"]), ("returned", "Drawing APT/250-11/001B is missing"))
        r = self.cust.post("/api/customer/requests", json=dict(mine["values"], drawings=REQUEST["drawings"], plan=mine["plan"], replaces=fid))
        self.assertEqual(r.status_code, 201, r.json)
        self.assertEqual(self.cust.get(f"/api/customer/requests/{fid}").json["status"], "replaced")
        self.assertEqual(self.c.post("/api/intake", json=dict(LAB, customer_form_id=r.json["id"], plan=["sc"])).status_code, 201)


if __name__ == "__main__":
    unittest.main()
