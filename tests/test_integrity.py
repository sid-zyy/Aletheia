"""Data integrity: sections, concurrency, numbering, audit chain, release locks, migration (NEXT_STEPS.md sections 4, 6, 11)."""
import glob, hashlib, json, os, sqlite3, sys, threading, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Base, DEMO, PW, _tmp, aletheia, integrity, raw, signed_in, up  # noqa: E402

PARTS = {k: v for k, v in DEMO.items() if k != "request"}


def together(fns):
    """Run the calls at the same moment from separate threads; returns their results in order."""
    out, gate = [None] * len(fns), threading.Barrier(len(fns))
    def run(n):
        gate.wait(); out[n] = fns[n]()
    ts = [threading.Thread(target=run, args=(n,)) for n in range(len(fns))]
    for t in ts: t.start()
    for t in ts: t.join()
    return out


class Concurrency(Base):
    def test_two_testers_upload_different_sections_at_once(self):
        i = self.job(); a, b = signed_in("t.rao"), signed_in("t.rao")
        halves = [{k: PARTS[k] for k in ("proforma", "losses", "noload", "sc")}, {k: PARTS[k] for k in ("temp", "pressure", "routine", "resistance")}]
        rs = together([lambda: a.post(f"/api/jobs/{i}/import", json=dict(filename="a.json", content=halves[0])),
                       lambda: b.post(f"/api/jobs/{i}/import", json=dict(filename="b.json", content=halves[1]))])
        self.assertEqual([r.status_code for r in rs], [200, 200])
        d = self.get(i)["data"]
        for k in list(halves[0]) + list(halves[1]): self.assertEqual(d[k], DEMO[k], k)  # neither upload overwrote the other

    def test_merged_sections_keep_both_writers(self):
        i = self.job(); a, b = signed_in("t.rao"), signed_in("t.rao")
        rs = together([lambda: a.post(f"/api/jobs/{i}/import", json=dict(filename="x.json", content={"ids": {"work": DEMO["ids"]["work"]}})),
                       lambda: b.post(f"/api/jobs/{i}/import", json=dict(filename="y.json", content={"ids": {"sc": DEMO["ids"]["sc"]}}))])
        self.assertEqual([r.status_code for r in rs], [200, 200])
        self.assertEqual(sorted(self.get(i)["data"]["ids"]), ["sc", "work"])

    def test_same_section_edited_twice_from_the_same_revision(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content=PARTS))
        rev = self.get(i)["meta"]["temp"]["revision"]; a, b = signed_in("t.rao"), signed_in("t.rao")
        t1, t2 = dict(DEMO["temp"], tap="A"), dict(DEMO["temp"], tap="B")
        rs = together([lambda: a.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t1, revision=rev)),
                       lambda: b.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t2, revision=rev))])
        self.assertEqual(sorted(r.status_code for r in rs), [200, 409])
        lost = next(r for r in rs if r.status_code == 409); self.assertIn("changed by T. Rao", lost.json["error"][0])
        self.assertEqual(self.get(i)["meta"]["temp"]["revision"], rev + 1)

    def test_parallel_job_creation_gets_distinct_numbers(self):
        self.c.post("/api/jobs", json=dict(series="CPRIBLRSCL26T0041", customer_form_id=self.request()))  # typed earlier: allocation continues after it
        cs = [(signed_in("t.rao"), self.request()) for _ in range(6)]
        rs = together([lambda c=c, f=f: c.post("/api/jobs", json=dict(auto_ids=True, customer_form_id=f)) for c, f in cs])
        self.assertEqual([r.status_code for r in rs], [201] * 6)
        series = sorted(r.json["series"] for r in rs); samples = {r.json["sample"] for r in rs}
        self.assertEqual(series, [f"CPRIBLRSCL26T{n:04d}" for n in range(42, 48)])
        self.assertEqual(len(samples), 6)
        self.assertEqual(self.c.post("/api/jobs", json=dict(auto_ids=True, sample="HVD26S0900", customer_form_id=self.request())).json["sample"], "HVD26S0900")  # typed sample kept


class History(Base):
    def test_every_revision_and_the_original_file_are_kept(self):
        i = self.job(); csv = raw("AP_Transformers_25T1654.csv")
        self.c.post(f"/api/jobs/{i}/import", json=up("lab.csv", csv))
        t = dict(DEMO["temp"], tap="edited"); rev = self.get(i)["meta"]["temp"]["revision"]
        self.c.post(f"/api/jobs/{i}/section", json=dict(section="temp", data=t, revision=rev))
        self.c.delete(f"/api/jobs/{i}/section/temp")
        h = [x for x in self.c.get(f"/api/jobs/{i}/history").json if x["key"] == "temp"]
        self.assertEqual([(x["revision"], x["state"]) for x in h], [(1, "uploaded"), (2, "uploaded"), (3, "removed")])
        self.assertEqual(h[0]["file"], "lab.csv"); self.assertEqual(h[0]["by"], "T. Rao")
        fid = self.get(i)["imports"][0]["file_id"]; f = self.c.get(f"/api/files/{fid}")
        self.assertEqual(f.data, csv); self.assertEqual(self.get(i)["imports"][0]["file_sha256"], hashlib.sha256(csv).hexdigest())
        m = self.get(i)["meta"]["proforma"]
        self.assertEqual((m["uploaded_by"], m["file"], m["revision"]), ("T. Rao", "lab.csv", 1))


class AuditChain(Base):
    def test_chain_detects_a_changed_or_removed_entry(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content=PARTS))
        r = self.admin.get("/api/audit/verify").json; self.assertTrue(r["ok"], r); self.assertGreater(r["checked"], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            with aletheia.db() as c: c.execute("UPDATE audit SET event='nothing happened' WHERE job_id=?", (i,))
        with self.assertRaises(sqlite3.IntegrityError):
            with aletheia.db() as c: c.execute("DELETE FROM audit WHERE job_id=?", (i,))
        with aletheia.db() as c:  # a database tool that drops the triggers first: the chain still shows it
            integrity.drop_triggers(c)
            target = c.execute("SELECT MIN(id) FROM audit WHERE job_id=?", (i,)).fetchone()[0]
            c.execute("UPDATE audit SET event='nothing happened' WHERE id=?", (target,))
        r = self.admin.get("/api/audit/verify").json; self.assertEqual((r["ok"], r["broken_at"]), (False, target)); self.assertIn("changed", r["reason"])
        with aletheia.db() as c:
            c.execute("DELETE FROM audit"); integrity.install_triggers(c)
        i = self.job("CPRIBLRSCL25T1655"); self.c.post(f"/api/jobs/{i}/validate"); self.c.post(f"/api/jobs/{i}/validate")
        tip = self.admin.get("/api/audit/verify").json["tip"]  # removing the newest entries is only visible against a recorded tip
        with aletheia.db() as c:
            integrity.drop_triggers(c)
            ids = [r[0] for r in c.execute("SELECT id FROM audit ORDER BY id")]
            c.execute("DELETE FROM audit WHERE id=?", (ids[1],)); integrity.install_triggers(c)
        r = self.admin.get("/api/audit/verify").json; self.assertEqual((r["ok"], r["broken_at"]), (False, ids[2])); self.assertIn("removed", r["reason"])

    def test_entries_name_the_actor(self):
        i = self.job()
        with aletheia.db() as c: a = c.execute("SELECT actor, kind, ip, entry_hash FROM audit WHERE job_id=?", (i,)).fetchone()
        self.assertEqual((a["actor"], a["kind"], a["ip"]), ("T. Rao (t.rao)", "job", "127.0.0.1")); self.assertEqual(len(a["entry_hash"]), 64)


class ReleaseLock(Base):
    def released(self):
        i = self.c.post("/api/demo").json["id"]; self.c.post(f"/api/jobs/{i}/validate"); self.gen(i)
        self.assertEqual(self.approve(i).status_code, 200); return i

    def test_every_change_to_a_released_job_is_refused(self):
        i = self.released(); before = self.get(i)
        rev = before["meta"]["temp"]["revision"]
        for m, path, b in (("POST", "import", dict(filename="x.json", content={"proforma": DEMO["proforma"]})),
                           ("POST", "section", dict(section="temp", data=DEMO["temp"], revision=rev)), ("DELETE", "section/temp", None),
                           ("POST", "edit", dict(series=before["series"], customer="Changed")), ("POST", "validate", {}), ("POST", "generate", {}),
                           ("POST", "review", dict(index=0)), ("POST", "sources", up("x.png", b"\x89PNG\r\n\x1a\n...")),
                           ("DELETE", f"imports/{before['imports'][0]['id']}", None)):
            r = self.c.open(f"/api/jobs/{i}/{path}", method=m, json=b)
            self.assertEqual(r.status_code, 409, (path, r.json))
        self.assertEqual(self.c.delete(f"/api/sources/{before['sources'][0]['id']}").status_code, 409)
        self.assertEqual(signed_in("r.viewer").post(f"/api/jobs/{i}/discard").status_code, 409)
        self.assertEqual(self.drop(i).status_code, 409)
        after = self.get(i)
        self.assertEqual((after["data"], after["meta"], after["findings"]), (before["data"], before["meta"], before["findings"]))

    def test_the_database_refuses_even_direct_edits(self):
        i = self.released()
        for sql in ("UPDATE sections SET data='{}' WHERE job_id=?", "DELETE FROM sections WHERE job_id=?", "DELETE FROM files WHERE job_id=?",
                    "DELETE FROM sources WHERE job_id=?", "UPDATE jobs SET customer='X' WHERE id=?", "UPDATE jobs SET stage=2 WHERE id=?",
                    "DELETE FROM jobs WHERE id=?", "DELETE FROM reports WHERE job_id=? AND approver IS NOT NULL",
                    "DELETE FROM section_history WHERE job_id=?"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                with aletheia.db() as c: c.execute(sql, (i,))
        with self.assertRaises(sqlite3.IntegrityError):
            with aletheia.db() as c: c.execute("INSERT INTO sections(job_id,key,data) VALUES(?,?,?)", (i, "extra", "{}"))

    def test_unreleased_job_can_still_be_deleted_but_its_audit_stays(self):
        i = self.job(); self.c.post(f"/api/jobs/{i}/import", json=dict(filename="d.json", content=PARTS))
        self.assertEqual(self.drop(i).status_code, 200)
        with aletheia.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sections WHERE job_id=?", (i,)).fetchone()[0], 0)
            self.assertGreater(c.execute("SELECT COUNT(*) FROM audit WHERE job_id=?", (i,)).fetchone()[0], 0)
        self.assertTrue(self.admin.get("/api/audit/verify").json["ok"])


class Migration(unittest.TestCase):
    def test_schema_1_database_is_backed_up_and_split_into_sections(self):
        path = os.path.join(_tmp.name, "schema1.db")
        with sqlite3.connect(path) as c:  # the layout before this change: one JSON blob per job, audit without actors
            c.executescript("""CREATE TABLE jobs(id INTEGER PRIMARY KEY, series TEXT UNIQUE, sample TEXT, customer TEXT, rating TEXT, stage INTEGER DEFAULT 0,
                data TEXT DEFAULT '{}', findings TEXT DEFAULT '[]', approver TEXT, approver_id TEXT, created TEXT, updated TEXT);
                CREATE TABLE audit(id INTEGER PRIMARY KEY, job_id INT, event TEXT, at TEXT);""")
            c.execute("INSERT INTO jobs(series,sample,customer,rating,stage,data,created,updated) VALUES('CPRIBLRSCL25T1654','HVD25S0847','A','B',4,?,'2025-01-01','2025-01-02')",
                      (json.dumps(DEMO),))
            c.execute("INSERT INTO audit(job_id,event,at) VALUES(1,'Customer request captured','2025-01-01T10:00:00')")
        old, aletheia.DB = aletheia.DB, path
        try:
            aletheia.init(); aletheia.init()  # a second start changes nothing
        finally: aletheia.DB = old
        self.assertEqual(len(glob.glob(path + ".pre-v2-*.bak")), 1)
        with sqlite3.connect(path) as c:
            d = {k: json.loads(v) for k, v in c.execute("SELECT key, data FROM sections WHERE job_id=1")}
            self.assertEqual(d, DEMO)
            self.assertEqual(c.execute("SELECT data FROM jobs").fetchone()[0], "{}")
            self.assertEqual(c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 2)
            self.assertTrue(integrity.verify_chain(c)["ok"])
            with self.assertRaises(sqlite3.IntegrityError): c.execute("UPDATE sections SET data='{}'")  # released in schema 1: locked now
        with sqlite3.connect(glob.glob(path + ".pre-v2-*.bak")[0]) as c:  # the backup is the untouched original
            self.assertEqual(json.loads(c.execute("SELECT data FROM jobs").fetchone()[0]), DEMO)


if __name__ == "__main__":
    unittest.main()
