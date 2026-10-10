"""Several people at once (NEXT_STEPS.md phase 7: "load test with 5+ simultaneous users").

Eight sessions run together against one database: three testers uploading (each to their own job, and all three into one
shared job, different tests), two verifiers verifying whatever is waiting, a customer reloading the portal and an
administrator reading the audit log. Afterwards: no request failed with a server error, nothing uploaded was lost, every
section's history is complete, and the audit chain is intact.
"""
import os, sys, threading, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Base, DEMO, PW, aletheia, integrity, signed_in  # noqa: E402

PARTS = {k: v for k, v in DEMO.items() if k not in ("request", "ids", "other")}
ROUNDS = 6


def users():
    from werkzeug.security import generate_password_hash
    h = generate_password_hash(PW)
    with aletheia.db() as c:
        for n in range(3):
            if not c.execute("SELECT 1 FROM users WHERE username=?", (f"load.t{n}",)).fetchone():
                c.execute("INSERT INTO users(username,full_name,employee_id,roles,password_hash,must_change_password,created_at) VALUES(?,?,?,?,?,0,'x')",
                          (f"load.t{n}", f"Load Tester {n}", f"E80{n}", "tester", h))
        if not c.execute("SELECT 1 FROM users WHERE username='load.v1'").fetchone():
            c.execute("INSERT INTO users(username,full_name,employee_id,roles,password_hash,must_change_password,created_at) VALUES('load.v1','Load Verifier','E809','verifier',?,0,'x')", (h,))


class Load(Base):
    def test_eight_people_at_once(self):
        users(); errors, lock, accepted, n_ok = [], threading.Lock(), {}, [0]
        shared = self.job("CPRIBLRSCL25T1800")
        own = [self.job(f"CPRIBLRSCL25T181{n}") for n in range(3)]
        keys = list(PARTS)
        def record(who, r):
            if r.status_code >= 500:
                with lock: errors.append(f"{who}: {r.status_code} {r.get_data(as_text=True)[:200]}")
        def tester(n):
            c = signed_in(f"load.t{n}"); mine = keys[n::3]  # each owns different tests of the shared job
            for rnd in range(ROUNDS):
                for k in mine:
                    d = dict(PARTS[k]) if isinstance(PARTS[k], dict) else PARTS[k]
                    if isinstance(d, dict): d = dict(d, _round=rnd)  # a new revision each round
                    r = c.post(f"/api/jobs/{shared}/import", json=dict(filename=f"{k}_{rnd}.json", content={k: d})); record(f"t{n}", r)
                    if r.status_code == 200:
                        accepted[k] = rnd
                        with lock: n_ok[0] += 1
                    elif r.status_code != 409:  # 409: a verifier had verified it meanwhile, so it is locked (correct)
                        with lock: errors.append(f"t{n}: import {k} {r.status_code} {r.get_json()}")
                record(f"t{n}", c.post(f"/api/jobs/{own[n]}/import", json=dict(filename=f"own_{rnd}.json", content={"sc": dict(DEMO["sc"], _round=rnd)})))
                record(f"t{n}", c.get(f"/api/jobs/{shared}"))
        def verifier(un):
            c = signed_in(un)
            for _ in range(ROUNDS * 2):
                w = c.get("/api/my-work"); record(un, w)
                for x in (w.get_json() or {}).get("to_verify", [])[:3]:
                    m = c.get(f"/api/jobs/{x['id']}").get_json()["meta"].get(x["key"]) or {}
                    r = c.post(f"/api/jobs/{x['id']}/sections/{x['key']}/verify", json=dict(revision=m.get("revision", 0)))
                    record(un, r)
                    if r.status_code not in (200, 409):
                        with lock: errors.append(f"{un}: verify {r.status_code} {r.get_json()}")
                time.sleep(0.01)
        def reader(c, path, who):
            for _ in range(ROUNDS * 2): record(who, c.get(path)); time.sleep(0.01)
        threads = [threading.Thread(target=tester, args=(n,)) for n in range(3)] + \
                  [threading.Thread(target=verifier, args=(u,)) for u in ("s.iyer", "load.v1")] + \
                  [threading.Thread(target=reader, args=(signed_in("admin"), "/api/audit", "admin")),
                   threading.Thread(target=reader, args=(signed_in("t.rao"), "/api/today", "t.rao")),
                   threading.Thread(target=reader, args=(signed_in("r.viewer"), "/api/jobs", "approver"))]
        t0 = time.time()
        for t in threads: t.start()
        for t in threads: t.join(timeout=300)
        self.assertEqual(errors, []); self.assertLess(time.time() - t0, 300)
        d = self.get(shared)
        for k in keys:  # every test holds the last upload that was accepted (later ones were refused once it was verified)
            self.assertEqual(d["data"][k].get("_round"), accepted[k], k)
        self.assertTrue(any(m["state"] == "verified" for m in d["meta"].values()))  # the verifiers really worked alongside
        with aletheia.db() as c:
            for k in keys:
                revs = [r[0] for r in c.execute("SELECT revision FROM section_history WHERE job_id=? AND key=? ORDER BY id", (shared, k))]
                self.assertEqual(revs, list(range(1, len(revs) + 1)), k)  # no revision lost or duplicated
            self.assertTrue(integrity.verify_chain(c)["ok"])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM imports WHERE job_id=?", (shared,)).fetchone()[0], n_ok[0])  # one per accepted upload


if __name__ == "__main__":
    unittest.main()
