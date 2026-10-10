"""Accounts, login, roles and permissions (docs/NEXT_STEPS.md section 2 and the test plan in section 11)."""
import datetime as dt, os, re, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Base, DEMO, PW, STAFF, aletheia, ensure_users, raw, signed_in, up  # noqa: E402  (same temporary database)
import auth  # noqa: E402

ROLE_USER = {"tester": "t.rao", "verifier": "s.iyer", "approver": "r.viewer", "admin": "admin"}


class RoutePolicy(Base):
    def test_every_route_has_a_permission_rule(self):
        with aletheia.app.test_request_context():
            missing = [r.rule for r in aletheia.app.url_map.iter_rules() if auth.policy_of(r.endpoint) is None]
        self.assertEqual(missing, [])

    def test_every_route_for_every_role(self):
        """Walks every route: a role without the permission gets 403 from the gate; with it, the gate lets the call through
        (the route itself may still answer 400/404/409). Anonymous callers get 401 everywhere except public routes."""
        i = self.job()
        clients = {r: signed_in(u) for r, u in ROLE_USER.items()}
        clients["customer"] = self.customer_client()
        anon = aletheia.app.test_client()
        for rule in aletheia.app.url_map.iter_rules():
            if rule.endpoint in ("static", "auth.logout", "auth.change_password"): continue  # these would end the walking session
            # the gate decides before the route looks anything up, so an id that does not exist keeps the walk harmless
            url = re.sub(r"<int:\w+>", "999999", rule.rule); url = re.sub(r"<(?:\w+:)?\w+>", "x", url)
            kind, perms = auth_policy(rule.endpoint)
            for m in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                for role, c in clients.items():
                    r = c.open(url, method=m, json={})
                    js = r.get_json(silent=True); err = " ".join(js.get("error") or []) if isinstance(js, dict) else ""
                    gated = r.status_code == 403 and "does not allow" in err
                    allowed = kind != "perm" or any(role in auth.PERMS[p] for p in perms)
                    self.assertEqual(gated, not allowed, f"{m} {rule.rule} as {role}: {r.status_code} {err[:120]}")
                    if kind != "public": self.assertNotEqual(r.status_code, 401, f"{m} {rule.rule} as {role}: session lost")
                r = anon.open(url, method=m, json={})
                if kind == "public": self.assertTrue(r.status_code != 401 or rule.endpoint == "auth.login", f"{m} {rule.rule}")
                else: self.assertEqual(r.status_code, 401, f"{m} {rule.rule} anonymous")
        self.assertEqual(self.get(i)["series"], "CPRIBLRSCL25T1654")

    def customer_client(self, org_name="A.P. Transformers", username="ap.customer"):
        oid = self.admin.post("/api/orgs", json=dict(name=org_name)).json["id"]
        with aletheia.db() as c:
            if not c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                from werkzeug.security import generate_password_hash
                c.execute("INSERT INTO users(username,full_name,roles,org_id,password_hash,must_change_password,created_at) VALUES(?,?,?,?,?,0,'2026-01-01')",
                          (username, "Customer " + org_name, "customer", oid, generate_password_hash(PW)))
        return signed_in(username)


def auth_policy(endpoint):
    with aletheia.app.test_request_context(): return auth.policy_of(endpoint)


class Login(Base):
    def test_csrf_token_is_required_for_changes(self):
        c = aletheia.app.test_client(); c.post("/api/login", json=dict(username="t.rao", password=PW))
        r = c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1700")); self.assertEqual(r.status_code, 403)
        self.assertIn("security token", r.json["error"][0])
        c.environ_base["HTTP_X_CSRF_TOKEN"] = "forged"
        self.assertEqual(c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1700")).status_code, 403)
        c.environ_base["HTTP_X_CSRF_TOKEN"] = c.get("/api/me").json["csrf"]
        self.assertEqual(c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1700")).status_code, 201)
        with aletheia.db() as d: self.assertTrue(d.execute("SELECT 1 FROM audit WHERE kind='denied' AND event LIKE '%security token%'").fetchone())

    def test_public_posts_must_be_json(self):
        c = aletheia.app.test_client()
        self.assertEqual(c.post("/api/login", data="username=t.rao&password=x", content_type="application/x-www-form-urlencoded").status_code, 415)

    def test_wrong_password_locks_the_account(self):
        c = aletheia.app.test_client()
        for _ in range(auth.LOCK_AFTER):
            self.assertEqual(c.post("/api/login", json=dict(username="s.iyer", password="nope nope nope")).status_code, 401)
        self.assertEqual(c.post("/api/login", json=dict(username="s.iyer", password=PW)).status_code, 423)  # even the right password
        self.assertEqual(c.post("/api/login", json=dict(username="nobody", password=PW)).status_code, 401)
        with aletheia.db() as d:
            ev = [r[0] for r in d.execute("SELECT event FROM audit WHERE kind='auth'")]
        self.assertEqual(sum("Failed sign-in for s.iyer" in e for e in ev), auth.LOCK_AFTER)
        self.assertTrue(any("account locked" in e for e in ev)); self.assertTrue(any("unknown user 'nobody'" in e for e in ev))
        self.admin.post(f"/api/users/{self.uid('s.iyer')}/end-sessions")  # an administrator can unlock it
        self.assertEqual(c.post("/api/login", json=dict(username="s.iyer", password=PW)).status_code, 200)

    def uid(self, un):
        with aletheia.db() as c: return c.execute("SELECT id FROM users WHERE username=?", (un,)).fetchone()[0]

    def test_idle_and_absolute_timeouts(self):
        c = signed_in("t.rao"); self.assertEqual(c.get("/api/jobs").status_code, 200)
        with c.session_transaction() as s: s["seen"] = (dt.datetime.now() - dt.timedelta(minutes=auth.IDLE_MINUTES + 1)).isoformat()
        self.assertEqual(c.get("/api/jobs").status_code, 401)
        c = signed_in("t.rao")
        with c.session_transaction() as s: s["started"] = (dt.datetime.now() - dt.timedelta(hours=auth.ABSOLUTE_HOURS + 1)).isoformat()
        self.assertEqual(c.get("/api/jobs").status_code, 401)

    def test_logout(self):
        c = signed_in("t.rao"); self.assertEqual(c.post("/api/logout").status_code, 200)
        self.assertEqual(c.get("/api/jobs").status_code, 401); self.assertIsNone(c.get("/api/me").json["user"])

    def test_admin_creates_user_who_must_change_password(self):
        bad = self.admin.post("/api/users", json=dict(username="New User", full_name="", roles=["tester", "admin"], password="short"))
        self.assertEqual(bad.status_code, 400); self.assertGreaterEqual(len(bad.json["error"]), 4)
        r = self.admin.post("/api/users", json=dict(username="k.das", full_name="K. Das", employee_id="e3001", roles=["tester", "verifier"],
                                                    password="temporary-pass-1", test_types=["sc", "temp"]))
        self.assertEqual(r.status_code, 201, r.json)
        self.assertEqual(self.admin.post("/api/users", json=dict(username="k.das", full_name="K", employee_id="E3", roles=["tester"],
                                                                 password="temporary-pass-1")).status_code, 409)
        c = aletheia.app.test_client(); self.assertTrue(c.post("/api/login", json=dict(username="k.das", password="temporary-pass-1")).json["must_change_password"])
        c.environ_base["HTTP_X_CSRF_TOKEN"] = c.get("/api/me").json["csrf"]
        r = c.get("/api/jobs"); self.assertEqual(r.status_code, 403); self.assertTrue(r.json["change_password"])
        self.assertEqual(c.post("/api/password", json=dict(old="temporary-pass-1", new="password123")).status_code, 400)  # too common
        self.assertEqual(c.post("/api/password", json=dict(old="temporary-pass-1", new="k.das-is-me-123")).status_code, 400)  # has username
        self.assertEqual(c.post("/api/password", json=dict(old="wrong", new="a-good-long-phrase")).status_code, 400)
        self.assertEqual(c.post("/api/password", json=dict(old="temporary-pass-1", new="a-good-long-phrase")).status_code, 200)
        c.environ_base["HTTP_X_CSRF_TOKEN"] = c.get("/api/me").json["csrf"]
        self.assertEqual(c.get("/api/jobs").status_code, 200)
        me = c.get("/api/me").json; self.assertEqual(me["user"]["roles"], ["tester", "verifier"]); self.assertEqual(me["user"]["employee_id"], "E3001")
        self.assertIn("section.verify", me["perms"]); self.assertNotIn("report.approve", me["perms"])

    def test_disabling_or_role_change_ends_sessions(self):
        c = signed_in("s.iyer"); uid = self.uid("s.iyer")
        self.assertEqual(self.admin.post(f"/api/users/{uid}", json=dict(roles=["verifier", "approver"])).status_code, 200)
        self.assertEqual(c.get("/api/jobs").status_code, 401)  # signed out by the change
        c = signed_in("s.iyer"); self.assertIn("report.approve", c.get("/api/me").json["perms"])
        self.admin.post(f"/api/users/{uid}", json=dict(active=False))
        self.assertEqual(c.get("/api/jobs").status_code, 401)
        self.assertEqual(aletheia.app.test_client().post("/api/login", json=dict(username="s.iyer", password=PW)).status_code, 401)
        self.admin.post(f"/api/users/{uid}", json=dict(active=True, roles=["verifier"]))

    def test_last_admin_cannot_be_removed_and_admin_is_not_a_tester(self):
        uid = self.uid("admin")
        self.assertEqual(self.admin.post(f"/api/users/{uid}", json=dict(roles=["tester"])).status_code, 409)
        self.assertEqual(self.admin.post(f"/api/users/{uid}", json=dict(roles=["admin", "approver"])).status_code, 400)
        self.assertEqual(self.admin.post("/api/users", json=dict(username="mix", full_name="Mix", roles=["customer", "tester"], employee_id="E1",
                                                                 password="a-good-long-phrase")).status_code, 400)

    def test_first_run_creates_one_admin_from_this_computer_only(self):
        with aletheia.db() as c:
            saved = [dict(r) for r in c.execute("SELECT * FROM users")]; c.execute("DELETE FROM users")
        try:
            a = aletheia.app.test_client(); self.assertTrue(a.get("/api/me").json["setup_needed"])
            body = dict(username="head", full_name="Lab Head", employee_id="E9000", password="a-good-long-phrase")
            remote = aletheia.app.test_client(); remote.environ_base["REMOTE_ADDR"] = "192.168.1.50"
            self.assertEqual(remote.post("/api/setup", json=body).status_code, 403)
            self.assertEqual(a.post("/api/setup", json=dict(body, password="short")).status_code, 400)
            self.assertEqual(a.post("/api/setup", json=body).status_code, 201)
            self.assertEqual(a.get("/api/me").json["user"]["roles"], ["admin"])  # signed in straight away
            self.assertEqual(aletheia.app.test_client().post("/api/setup", json=dict(body, username="second")).status_code, 409)  # closed for good
        finally:
            with aletheia.db() as c:
                c.execute("DELETE FROM users")
                for u in saved: c.execute(f"INSERT INTO users({','.join(u)}) VALUES({','.join('?' * len(u))})", tuple(u.values()))


class Features(Base):
    def test_scanning_is_off_unless_switched_on(self):
        aletheia.app.config["FEATURE_SCAN"] = False
        try:
            self.assertFalse(self.c.get("/api/me").json["features"]["scan"])
            r = self.c.post("/api/read-scan", json=dict(section="request", filename="x.png", b64="aGk="))
            self.assertEqual(r.status_code, 404); self.assertIn("turned off", r.json["error"][0])
        finally:
            aletheia.app.config.pop("FEATURE_SCAN")
        self.assertTrue(self.c.get("/api/me").json["features"]["scan"])  # the test suite switches it on


class SeparationOfDuties(Base):
    def ready(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=up("d.json", raw("AP_Transformers_25T1654.json")))
        self.c.post(f"/api/jobs/{i}/validate"); self.gen(i); return i

    def test_admin_cannot_touch_test_data_or_sign(self):
        i = self.ready()
        for path in ("import", "validate", "generate", "approve"):
            self.assertEqual(self.admin.post(f"/api/jobs/{i}/{path}", json={}).status_code, 403, path)
        with aletheia.db() as c: self.assertGreaterEqual(c.execute("SELECT COUNT(*) FROM audit WHERE kind='denied' AND job_id=?", (i,)).fetchone()[0], 4)

    def test_someone_who_worked_on_the_data_cannot_approve(self):
        i = self.ready()
        uid = Login.uid(self, "s.iyer")
        self.admin.post(f"/api/users/{uid}", json=dict(roles=["verifier", "approver"]))
        try:
            v = signed_in("s.iyer"); v.post(f"/api/jobs/{i}/validate")  # the verifier ran the checks on this job
            r = v.post(f"/api/jobs/{i}/approve", json=dict(password=PW)); self.assertEqual(r.status_code, 403)
            self.assertIn("different person", r.json["error"][0])
            self.assertEqual(self.approve(i).status_code, 200)  # someone who did not
        finally:
            self.admin.post(f"/api/users/{uid}", json=dict(roles=["verifier"]))

    def test_typed_name_no_longer_gets_around_it(self):
        i = self.ready()
        r = signed_in("p.naveen").post(f"/api/jobs/{i}/approve", json=dict(name="Somebody Else", password=PW))
        self.assertEqual(r.status_code, 403)  # P. Naveenkumar is the engineer on the work instruction, whatever is typed


class Customers(Base):
    customer_client = RoutePolicy.customer_client

    def test_customer_sees_only_their_own_jobs_and_no_values(self):
        cust = self.customer_client()
        oid = self.admin.get("/api/orgs").json[0]["id"]
        mine = self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL25T1654", sample="HVD25S0847", customer="A.P. Transformers", rating="250 kVA",
                                                  request=DEMO["request"], org_id=oid)).json["id"]
        other = self.job("CPRIBLRSCL25T1655")
        self.c.post(f"/api/jobs/{mine}/import", json=up("d.json", raw("AP_Transformers_25T1654.json")))
        self.assertEqual([j["id"] for j in cust.get("/api/jobs").json], [mine])
        self.assertEqual(cust.get(f"/api/jobs/{other}").status_code, 404)  # guessing an id reveals nothing
        v = cust.get(f"/api/jobs/{mine}").json
        for k in ("data", "findings", "audit", "imports", "sources"): self.assertNotIn(k, v)
        self.assertEqual({p["state"] for p in v["progress"]}, {"uploaded"})  # pending verification
        self.assertEqual(cust.get(f"/api/jobs/{mine}/report.pdf").status_code, 409)
        self.c.post(f"/api/jobs/{mine}/validate"); self.gen(mine)
        self.assertEqual(cust.get(f"/api/jobs/{mine}/report.pdf").status_code, 409)  # generated but not released
        self.approve(mine)
        self.assertTrue(cust.get(f"/api/jobs/{mine}/report.pdf").data.startswith(b"%PDF"))
        self.assertTrue(cust.get(f"/api/jobs/{mine}").json["released"])
        self.assertEqual(cust.get(f"/api/jobs/{other}/report.pdf").status_code, 404)
        for path in (f"/api/jobs/{mine}/export/json", "/api/stats", "/api/template/csv"): self.assertEqual(cust.get(path).status_code, 403, path)


if __name__ == "__main__":
    unittest.main()
