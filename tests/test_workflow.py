"""Workflow: strict intake, per-section verification, ownership, sign-off, assignment notifications, "My work" (NEXT_STEPS.md sections 3, 4, 11)."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import LAB, REQUEST, Base, DEMO, PNG, PW, aletheia, signed_in, up  # noqa: E402

PARTS = {k: v for k, v in DEMO.items() if k != "request"}


def extra_users():
    from werkzeug.security import generate_password_hash
    h = generate_password_hash(PW)
    with aletheia.db() as c:
        for un, name, roles, emp, tests in (("w.das", "W. Das", "tester", "E1003", None), ("sc.only", "S. C. Only", "tester", "E1004", "sc"),
                                            ("both", "B. Oth", "tester", "E1005", None)):
            if not c.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone():
                c.execute("INSERT INTO users(username,full_name,employee_id,roles,test_types,password_hash,must_change_password,created_at) VALUES(?,?,?,?,?,?,0,'2026-01-01')",
                          (un, name, emp, roles, tests, h))


def uid(un):
    with aletheia.db() as c: return c.execute("SELECT id FROM users WHERE username=?", (un,)).fetchone()[0]


class Flow(Base):
    def setUp(self):
        super().setUp(); extra_users(); self.v = signed_in("s.iyer")

    def intake_body(self, **kw):
        """The laboratory's part of the intake (sheet 3) for a fresh customer request."""
        return dict(LAB, customer_form_id=kw.pop("customer_form_id", None) or self.request(), plan=["proforma", "temp", "sc"], **kw)


class Intake(Flow):
    def test_nothing_missing_nothing_wrong(self):
        # the customer's sheets 1 and 2, checked as they type
        for bad, expect in ((dict(pin="56001"), "PIN code: must be 6 digits"), (dict(pin="5600011"), "PIN code: must be 6 digits"),
                            (dict(pin="56OO01"), "PIN code: must be 6 digits"), (dict(pin="060001"), "PIN code: must be 6 digits"),
                            (dict(pin="NA"), "PIN code: required"), (dict(customer=" "), "Name of the Customer: required"),
                            (dict(manufacturer="N/A"), "Manufacturer's Details: required (or mark it not applicable"), (dict(phone="12345"), "Phone"),
                            (dict(email="qa@nowhere"), "Email"), (dict(rating="big"), "Rating"), (dict(state="Atlantis"), "not an Indian state"),
                            (dict(samples="one"), "Number of Samples: a whole number"), (dict(take_back="maybe"), "answer yes or no"),
                            (dict(msme="perhaps"), "MSME Discount: choose one"), (dict(signed_name=""), "Customers Name (signature): required"),
                            (dict(declare_drawings=False), "Declaration not accepted")):
            r = self.cust.post("/api/customer/requests/check", json=dict(REQUEST, plan=["sc"], **bad))
            self.assertFalse(r.json["ok"], bad); self.assertTrue(any(expect in e for e in r.json["errors"]), (bad, r.json["errors"]))
            self.assertEqual(self.cust.post("/api/customer/requests", json=dict(REQUEST, plan=["sc"], **bad)).status_code, 400)
        # the laboratory's sheet 3
        fid = self.request()
        for bad, expect in ((dict(arrived_at="2099-01-01T10:00"), "future"), (dict(condition=""), "Physical Condition of Sample on receipt: required"),
                            (dict(condition="Not suitable for Testing"), "concurrence"), (dict(condition="Not suitable for Testing", **{"continue": "Not to continue Testing"}), "cannot be accepted"),
                            (dict(capability="No"), "no capability"), (dict(plan=[]), "Test plan"), (dict(customer_form_id=None), "only a customer can raise")):
            b = dict(LAB, customer_form_id=fid, plan=["sc"]); b.update(bad)
            r = self.c.post("/api/intake/check", json=b)
            self.assertFalse(r.json["ok"], bad); self.assertTrue(any(expect in e for e in r.json["errors"]), (bad, r.json["errors"]))
            self.assertEqual(self.c.post("/api/intake", json=b).status_code, 400)
        with aletheia.db() as c: self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)  # no number allocated
        with aletheia.db() as c: self.assertEqual(c.execute("SELECT COUNT(*) FROM counters").fetchone()[0], 0)

    def test_arrival_and_organisation_are_filled_in_by_themselves(self):
        r = self.c.post("/api/intake", json={k: v for k, v in self.intake_body().items() if k != "arrived_at"}); self.assertEqual(r.status_code, 201, r.json)
        j = self.get(r.json["id"])
        self.assertEqual(j["org_id"], self.org)  # the organisation of the customer who raised the request
        self.assertTrue(j["intake"]["arrived_at"]); self.assertEqual(j["intake"]["external"], "Nil")

    def test_the_whole_list_at_once(self):
        r = self.cust.post("/api/customer/requests/check", json=dict(plan=["sc"]))
        self.assertGreaterEqual(len(r.json["errors"]), 25)

    def test_pin_and_state_must_agree_or_be_confirmed(self):
        b = self.intake_body(customer_form_id=self.request(state="Karnataka"))  # 600058 is Chennai
        r = self.c.post("/api/intake", json=b); self.assertEqual(r.status_code, 400)
        self.assertIn("belongs to Tamil Nadu", " ".join(r.json["error"]))
        r = self.c.post("/api/intake", json=dict(b, confirm_warnings=True)); self.assertEqual(r.status_code, 201)
        self.assertIn("confirmed: PIN code", " ".join(a["event"] for a in self.get(r.json["id"])["audit"]))

    def test_not_applicable_needs_a_reason_and_is_recorded(self):
        chk = lambda **kw: " ".join(self.cust.post("/api/customer/requests/check", json=dict(REQUEST, plan=["sc"], **kw)).json["errors"])
        self.assertIn("give the reason", chk(na=dict(manufacturer="ok")))
        self.assertIn("cannot be marked not applicable", chk(na=dict(pin="customer did not say")))
        fid = self.request(witness="", na=dict(manufacturer="imported unit, maker not declared"))
        rq = self.get(self.c.post("/api/intake", json=self.intake_body(customer_form_id=fid)).json["id"])["data"]["request"]
        self.assertEqual(rq["manufacturer"], "Not applicable: imported unit, maker not declared")
        self.assertEqual(rq["witness"], "")  # optional on the form: left empty

    def test_valid_intake_allocates_numbers_and_records_who_received_it(self):
        r = self.c.post("/api/intake", json=self.intake_body(assign=dict(sc=uid("t.rao"), temp=uid("sc.only")), external="Crane hire: Bengaluru Cranes"))
        self.assertEqual(r.status_code, 201, r.json)
        j = self.get(r.json["id"])
        self.assertRegex(j["series"], r"CPRIBLRSCL\d{2}T0001"); self.assertRegex(j["sample"], r"HVD\d{2}S0001")
        self.assertEqual(j["plan"], ["proforma", "sc", "temp"])
        self.assertEqual(j["intake"]["received_by"], "T. Rao"); self.assertEqual(j["intake"]["external"], "Crane hire: Bengaluru Cranes")
        self.assertEqual(j["assign"]["sc"]["name"], "T. Rao"); self.assertNotIn("temp", j["assign"])  # an engineer takes tests only for themselves
        self.assertEqual(j["data"]["request"]["pin"], "600058"); self.assertEqual(j["org_id"], self.org)
        self.assertEqual(j["data"]["request"]["decision_rule"][:3], "(i)"); self.assertTrue(j["data"]["request"]["signed_at"])
        self.assertIsNone(j["intake"]["checked_by"])
        self.assertEqual(self.c.post(f"/api/jobs/{j['id']}/intake/checked").status_code, 200)
        self.assertEqual(self.get(j["id"])["intake"]["checked_by"], "T. Rao")

    def test_release_needs_a_checked_intake(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content=PARTS))
        self.c.post(f"/api/jobs/{i}/validate")
        for n, f in enumerate(self.get(i)["findings"]):
            if f["level"] == "warn": self.c.post(f"/api/jobs/{i}/review", json=dict(index=n))
        for k, m in self.get(i)["meta"].items():
            if k != "request": self.v.post(f"/api/jobs/{i}/sections/{k}/verify", json=dict(revision=m["revision"]))
        self.admin.post(f"/api/jobs/{i}/signoff"); self.assertEqual(self.admin.post(f"/api/jobs/{i}/generate").status_code, 200)
        r = self.approve(i); self.assertEqual(r.status_code, 409); self.assertIn("Intake", " ".join(r.json["error"]))


class Sections(Flow):
    def loaded(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content=PARTS)); return i

    def test_tester_may_verify_their_own_upload_but_not_the_admin(self):
        b = signed_in("both"); i = self.job()
        b.post(f"/api/jobs/{i}/import", json=dict(filename="sc.json", content={"sc": DEMO["sc"]}))
        r = self.admin.post(f"/api/jobs/{i}/sections/sc/verify", json=dict(revision=1)); self.assertEqual(r.status_code, 403)
        self.assertIn("does not allow", r.json["error"][0])  # the administrator never verifies
        self.assertEqual(b.post(f"/api/jobs/{i}/sections/sc/verify", json=dict(revision=1)).status_code, 200)
        m = self.get(i)["meta"]["sc"]; self.assertEqual((m["state"], m["verified_by"], m["revision"]), ("verified", "B. Oth", 2))

    def test_verify_names_the_revision_that_was_checked(self):
        i = self.loaded()
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/temp/verify", json={}).status_code, 400)
        rev = self.get(i)["meta"]["temp"]["revision"]
        self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=dict(DEMO["temp"], tap="X"), revision=rev))  # changed meanwhile
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/temp/verify", json=dict(revision=rev)).status_code, 409)

    def test_return_correct_and_verify(self):
        i = self.loaded(); rev = self.get(i)["meta"]["temp"]["revision"]
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/temp/return", json=dict(revision=rev)).status_code, 400)  # reason needed
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/temp/return", json=dict(revision=rev, reason="hour 7 top-oil does not match the sheet")).status_code, 200)
        m = self.get(i)["meta"]["temp"]; self.assertEqual((m["state"], m["note"]), ("returned", "hour 7 top-oil does not match the sheet"))
        self.assertEqual(self.c.get("/api/my-work").json["returned"][0]["note"], "hour 7 top-oil does not match the sheet")
        self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=dict(DEMO["temp"], tap="fixed"), revision=m["revision"]))
        m = self.get(i)["meta"]["temp"]; self.assertEqual(m["state"], "uploaded")
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/temp/verify", json=dict(revision=m["revision"])).status_code, 200)
        h = [x["state"] for x in self.c.get(f"/api/jobs/{i}/history").json if x["key"] == "temp"]
        self.assertEqual(h, ["uploaded", "returned", "uploaded", "verified"])

    def test_a_verified_section_is_locked_until_reopened(self):
        i = self.loaded(); rev = self.get(i)["meta"]["sc"]["revision"]
        self.v.post(f"/api/jobs/{i}/sections/sc/verify", json=dict(revision=rev))
        self.assertEqual(self.c.post(f"/api/jobs/{i}/import", json=dict(filename="sc2.json", content={"sc": dict(DEMO["sc"], date="x")})).status_code, 409)
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):  # also refused by the database
            with aletheia.db() as c: c.execute("UPDATE sections SET data='{}' WHERE job_id=? AND key='sc'", (i,))
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/sc/reopen", json={}).status_code, 400)
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/sc/reopen", json=dict(reason="customer sent corrected log")).status_code, 200)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/import", json=dict(filename="sc2.json", content={"sc": dict(DEMO["sc"], date="x")})).status_code, 200)

    def test_ownership_and_certification(self):
        i = self.loaded(); k = signed_in("w.das")
        r = k.post(f"/api/jobs/{i}/import", json=dict(filename="t.json", content={"temp": DEMO["temp"]}))
        self.assertEqual(r.status_code, 403); self.assertIn("belongs to T. Rao", r.json["error"][0])
        self.assertEqual(k.post(f"/api/jobs/{i}/assign", json=dict(key="temp", user_id=uid("w.das"))).status_code, 403)  # testers cannot reassign
        self.assertEqual(self.admin.post(f"/api/jobs/{i}/assign", json=dict(key="temp", user_id=uid("w.das"))).status_code, 200)
        self.assertEqual(k.post(f"/api/jobs/{i}/import", json=dict(filename="t.json", content={"temp": DEMO["temp"]})).status_code, 200)
        self.assertEqual(self.c.post(f"/api/jobs/{i}/import", json=dict(filename="t2.json", content={"temp": dict(DEMO["temp"], tap="y")})).status_code, 403)
        s = signed_in("sc.only"); j = self.job("CPRIBLRSCL25T1700")
        r = s.post(f"/api/jobs/{j}/import", json=dict(filename="t.json", content={"temp": DEMO["temp"]})); self.assertEqual(r.status_code, 403)
        self.assertIn("certified for sc only", r.json["error"][0])
        self.assertEqual(s.post(f"/api/jobs/{j}/import", json=dict(filename="s.json", content={"sc": DEMO["sc"]})).status_code, 200)
        self.assertEqual(self.admin.post(f"/api/jobs/{j}/assign", json=dict(key="temp", user_id=uid("sc.only"))).status_code, 400)
        with aletheia.db() as c: self.assertGreaterEqual(c.execute("SELECT COUNT(*) FROM audit WHERE kind='denied' AND event LIKE 'Refused:%'").fetchone()[0], 3)

    def test_sign_off_gate(self):
        i = self.receive()  # plan: proforma, temp, sc
        self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content={k: PARTS[k] for k in ("proforma", "temp")}))
        self.c.post(f"/api/jobs/{i}/validate")
        r = self.admin.post(f"/api/jobs/{i}/signoff"); self.assertEqual(r.status_code, 409)
        errs = " ".join(r.json["error"]); self.assertIn("Short-Circuit Withstand Test Logsheet: not uploaded", errs); self.assertIn("Proforma for Transformers: uploaded", errs)
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/sc/na", json={}).status_code, 400)
        self.assertEqual(self.v.post(f"/api/jobs/{i}/sections/sc/na", json=dict(reason="customer withdrew the SC test")).status_code, 200)
        for k in ("proforma", "temp"): self.v.post(f"/api/jobs/{i}/sections/{k}/verify", json=dict(revision=self.get(i)["meta"][k]["revision"]))
        for n, f in enumerate(self.get(i)["findings"]):
            if f["level"] in ("warn", "fail"): self.c.post(f"/api/jobs/{i}/review", json=dict(index=n))
        r = self.admin.post(f"/api/jobs/{i}/generate"); self.assertEqual(r.status_code, 409); self.assertIn("An administrator must approve", r.json["error"][0])
        self.assertEqual(self.v.post(f"/api/jobs/{i}/signoff").status_code, 403)  # a tester does not approve the job
        self.assertEqual(self.admin.post(f"/api/jobs/{i}/signoff").status_code, 200)
        self.assertEqual(self.get(i)["signoff"]["by"], "Lab Admin")
        n = [x for x in self.admin.get("/api/notifications").json["items"] if x["kind"] == "signoff"]
        self.assertTrue(n and n[0]["action"] and n[0]["target"] == f"job/{i}", n)  # "ready for approval" asks the administrator to act
        p = {x["key"]: x["state"] for x in self.get(i)["progress"]}; self.assertEqual(p, {"proforma": "verified", "temp": "verified", "sc": "na"})
        self.c.post(f"/api/jobs/{i}/import", json=dict(filename="ids.json", content={"ids": {"work": DEMO["ids"]["work"]}}))
        self.assertIsNone(self.get(i)["signoff"])  # new data: the sign-off is void

    def test_only_an_administrator_approves_the_job(self):
        b = signed_in("both"); i = self.job()
        b.post(f"/api/jobs/{i}/import", json=dict(filename="sc.json", content={"sc": DEMO["sc"]}))
        self.v.post(f"/api/jobs/{i}/sections/sc/verify", json=dict(revision=1)); b.post(f"/api/jobs/{i}/validate")
        self.assertEqual(b.post(f"/api/jobs/{i}/signoff").status_code, 403)
        self.assertEqual(self.v.post(f"/api/jobs/{i}/signoff").status_code, 403)
        self.assertEqual(self.admin.post(f"/api/jobs/{i}/signoff").status_code, 200)


class Assignment(Flow):
    def planned(self):
        return self.receive()  # plan: proforma, temp, sc

    def test_engineer_takes_an_unassigned_test(self):
        i = self.planned()
        k = signed_in("w.das")
        self.assertEqual([x["key"] for x in k.get("/api/my-work").json["available"] if x["id"] == i], ["proforma", "sc", "temp"])
        self.assertEqual(k.post(f"/api/jobs/{i}/assign", json=dict(key="sc", user_id=uid("t.rao"))).status_code, 403)  # not for someone else
        self.assertEqual(k.post(f"/api/jobs/{i}/assign", json=dict(key="sc")).status_code, 200)
        self.assertEqual(self.get(i)["assign"]["sc"]["name"], "W. Das")
        self.assertEqual(self.c.post(f"/api/jobs/{i}/assign", json=dict(key="sc")).status_code, 403)  # already taken
        self.assertNotIn("sc", [x["key"] for x in self.c.get("/api/my-work").json["available"] if x["id"] == i])
        self.assertEqual(k.get("/api/my-work").json["assigned"][0]["key"], "sc")
        s = signed_in("sc.only"); self.assertEqual([x["key"] for x in s.get("/api/my-work").json["available"] if x["id"] == i], [])  # certified for sc only

    def test_admin_assigns_a_whole_job_and_reassigns(self):
        i = self.planned(); self.c.post(f"/api/jobs/{i}/assign", json=dict(key="temp"))  # T. Rao took temp himself
        r_at = aletheia.now()
        r = self.admin.post(f"/api/jobs/{i}/assign", json=dict(all=True, user_id=uid("w.das"))).json
        self.assertEqual(sorted(r["assigned"]), ["proforma", "sc"]); self.assertIn("Temperature-Rise Test Logsheet (already assigned)", r["skipped"])
        self.assertEqual(self.c.post(f"/api/jobs/{i}/assign", json=dict(all=True, user_id=uid("t.rao"))).status_code, 403)
        self.assertEqual(self.admin.post(f"/api/jobs/{i}/assign", json=dict(key="temp", user_id=uid("w.das"))).status_code, 200)
        self.assertEqual(self.get(i)["assign"]["temp"]["name"], "W. Das")
        with aletheia.db() as c: c.execute("UPDATE notifications SET read_at='x' WHERE created_at < ?", (r_at,))
        notes = [n["message"] for n in signed_in("w.das").get("/api/notifications?unread=1").json["items"] if n["kind"] == "assigned"]
        self.assertEqual(len(notes), 2, notes)  # one for the whole job (two tests), one for the reassigned test
        self.assertIn("Proforma for Transformers, Short-Circuit Withstand Test Logsheet assigned to you", notes[-1])

    def test_same_test_on_several_jobs_at_once_gives_one_notification(self):
        with aletheia.db() as c: c.execute("DELETE FROM notifications")
        a, b = self.planned(), self.planned()
        for i in (a, b): self.assertEqual(self.admin.post(f"/api/jobs/{i}/assign", json=dict(key="sc", user_id=uid("w.das"))).status_code, 200)
        notes = [n["message"] for n in signed_in("w.das").get("/api/notifications").json["items"] if n["kind"] == "assigned"]
        self.assertEqual(len(notes), 1, notes)
        self.assertEqual(notes[0], f"{self.get(a)['series']}, {self.get(b)['series']}: Short-Circuit Withstand Test Logsheet assigned to you")

    def test_checks_expect_only_the_required_tests(self):
        i = self.receive(plan=("sc",))  # the customer asked for the short-circuit test only
        self.c.post(f"/api/jobs/{i}/import", json=dict(filename="sc.json", content={"sc": DEMO["sc"], "ids": {"sc": DEMO["ids"]["sc"], "resistance": ["25T1656", "HVD25S0847"]}}))
        F = self.c.post(f"/api/jobs/{i}/validate").json["findings"]
        comp = next(f for f in F if f["check"] == "Completeness of source documents")
        self.assertEqual((comp["level"], comp["detail"]), ("pass", "All 2 required documents imported"))  # the request and the SC test
        self.assertFalse([f for f in F if f["check"] == "Limits not available"])  # the proforma was not required
        self.assertFalse([f for f in F if f["check"] == "Identifier consistency" and "resistance" in f["detail"]])  # no resistance sheet uploaded

    def test_admin_dashboard_lists_what_waits(self):
        i = self.planned()
        w = self.admin.get("/api/my-work").json
        self.assertEqual(len([x for x in w["unassigned"] if x["id"] == i]), 3)
        for k in ("to_approve", "requests", "awaiting_verification"): self.assertIn(k, w)
        d = self.c.post("/api/demo").json["id"]; self.c.post(f"/api/jobs/{d}/validate"); self.gen(d)
        self.assertEqual([x["id"] for x in self.admin.get("/api/my-work").json["to_approve"]], [d])


class Queues(Flow):
    def test_my_work_queues(self):
        a = self.job(); self.c.post(f"/api/jobs/{a}/import", json=dict(filename="a.json", content={"sc": DEMO["sc"]}))
        b = self.job("CPRIBLRSCL25T1700"); self.c.post(f"/api/jobs/{b}/import", json=dict(filename="b.json", content={"temp": DEMO["temp"]}))
        w = self.v.get("/api/my-work").json
        self.assertEqual([(x["series"], x["name"]) for x in w["to_verify"]], [("CPRIBLRSCL25T1654", "Short-Circuit Withstand Test Logsheet"), ("CPRIBLRSCL25T1700", "Temperature-Rise Test Logsheet")])
        self.assertNotIn("to_approve", w)  # a tester verifies; approving is the administrator's
        t = self.c.get("/api/my-work").json; self.assertEqual(len(t["uploaded"]), 2); self.assertEqual(len(t["intake"]), 2)
        self.assertEqual(len(t["to_verify"]), 2)  # own uploads can be verified too
        a_w = self.admin.get("/api/my-work").json
        for k in ("to_signoff", "to_approve", "awaiting_verification", "unassigned", "requests"): self.assertIn(k, a_w)
        self.assertNotIn("to_verify", a_w)
        self.admin.post(f"/api/jobs/{b}/assign", json=dict(key="sc", user_id=uid("w.das")))
        self.assertEqual(signed_in("w.das").get("/api/my-work").json["assigned"][0]["series"], "CPRIBLRSCL25T1700")
        i = self.c.post("/api/demo").json["id"]; self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        self.assertEqual([x["id"] for x in signed_in("r.viewer").get("/api/my-work").json["to_approve"]], [i])


if __name__ == "__main__":
    unittest.main()
