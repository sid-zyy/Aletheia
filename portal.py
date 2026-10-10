"""Customer portal (docs/NEXT_STEPS.md section 7.1): the partial report, approved values, and request forms sent in by customers.

* A customer sees numbers only for approved (verified) tests. Everything else is shown by status alone, so a customer never
  sees a figure that may still be corrected.
* The partial report is rebuilt whenever the set of approved tests changes; every version is stored with its hash, so what a
  customer saw at a given time can be reproduced. It is watermarked, unsigned and carries no verdict.
* Customers can send their filled request form (Excel) into the laboratory's intake inbox; the receiving engineer reads it,
  checks it against the original and creates the job.
"""
import hashlib, io, json, sqlite3, threading
from flask import jsonify, request, send_file, abort
import auth, integrity, xltemplates as X

A = None


def init_db(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS partials(id INTEGER PRIMARY KEY, job_id INT NOT NULL, version INT NOT NULL, sections TEXT NOT NULL, fingerprint TEXT NOT NULL,
        sha256 TEXT NOT NULL, pdf BLOB NOT NULL, at TEXT NOT NULL, UNIQUE(job_id, version));
    CREATE TABLE IF NOT EXISTS customer_forms(id INTEGER PRIMARY KEY, org_id INT NOT NULL, user_id INT NOT NULL, filename TEXT, sha256 TEXT, content BLOB,
        at TEXT, status TEXT DEFAULT 'received', job_id INT);""")
    have = {r[1] for r in c.execute("PRAGMA table_info(customer_forms)")}
    for col, ddl in (("kind", "TEXT DEFAULT 'excel'"), ("data", "TEXT"), ("plan", "TEXT")):
        if col not in have: c.execute(f"ALTER TABLE customer_forms ADD COLUMN {col} {ddl}")
    for name, body in (("partials_no_update", "BEFORE UPDATE ON partials BEGIN SELECT RAISE(ABORT, 'a partial report version cannot be changed'); END"),
                       ("partials_no_delete", f"BEFORE DELETE ON partials WHEN {integrity.EVER.format(j='OLD.job_id')} BEGIN SELECT RAISE(ABORT, 'partial reports of a released job are kept'); END")):
        c.execute(f"DROP TRIGGER IF EXISTS {name}"); c.execute(f"CREATE TRIGGER {name} {body}")


def approved_keys(j):
    return [k for k, m in j["meta"].items() if m["state"] == "verified" and k != "request" and k in j["data"]]


_building = threading.Lock()


def refresh(i):
    """Store a new partial report if the approved tests (or their revisions) changed since the last one. Returns its version.
    Two verifiers approving tests of one job at the same moment must not both claim the next version number: rebuilds are
    serialised, and a version taken by another process meanwhile (UNIQUE) makes it re-read the job and try again."""
    with _building:
        for _ in range(3):
            try: return _refresh(i)
            except sqlite3.IntegrityError: continue
    return None


def _refresh(i):
    j = A.getjob(i, False)
    if j["released"] or j.get("archived"): return None
    keys = approved_keys(j)
    fp = integrity.sha(integrity.canon(sorted((k, j["meta"][k]["revision"], j["meta"][k]["data_sha256"]) for k in keys)))
    with A.db() as c:
        last = c.execute("SELECT version, fingerprint FROM partials WHERE job_id=? ORDER BY version DESC LIMIT 1", (i,)).fetchone()
    if last and last["fingerprint"] == fp: return last["version"]
    if not keys and not last: return None  # nothing approved yet, and nothing shown before: no partial report
    # (a test reopened after approval produces a new version without it, so the customer no longer sees its values)
    v = (last["version"] if last else 0) + 1
    name = lambda k: A.NAMES.get(k, {"ids": "Identifiers on each sheet", "other": "Additional log sheets"}.get(k, k))
    plan = [p["key"] for p in j["progress"]]
    part = dict(version=v, approved=[name(k) for k in keys if k in A.NAMES or k == "other"],
                pending=[p["name"] for p in j["progress"] if p["key"] not in keys and p["state"] != "na"],
                sections=[(name(k), j["meta"][k]["revision"], j["meta"][k]["data_sha256"] or "") for k in keys])
    data = {k: v_ for k, v_ in j["data"].items() if k in keys or k == "request"}
    pdf = A.build_pdf(dict(j, data=data), partial=part).getvalue()
    sha = hashlib.sha256(pdf).hexdigest()
    with A.db() as c:
        c.execute("INSERT INTO partials(job_id,version,sections,fingerprint,sha256,pdf,at) VALUES(?,?,?,?,?,?,?)",
                  (i, v, json.dumps([dict(key=k, revision=j["meta"][k]["revision"], data_sha256=j["meta"][k]["data_sha256"]) for k in keys]), fp, sha, pdf, A.now()))
        A.log(c, i, f"Partial report version {v} built from {len(keys)} approved test{'s' if len(keys) > 1 else ''} (SHA-256 {sha[:12]}...)", kind="event")
    return v


def labelled(c, j, key):
    """An approved test's values with the labels of the template that read it (or the current one), for the customer."""
    tid = (j["meta"].get(key) or {}).get("template_id")
    r = c.execute("SELECT mapping FROM templates WHERE id=?", (tid,)).fetchone() if tid else None
    r = r or c.execute("SELECT mapping FROM templates WHERE section=? AND status='active' AND kind='logsheet'", (key,)).fetchone()
    data = j["data"].get(key) or {}
    if not r: return [dict(label=f, value=v) for _, f, v in A.importers.flatten({key: data})]
    m = json.loads(r[0]); out = []; done = set()
    for f in m.get("fields") or []:
        if f["field"].startswith("@") or f.get("by") == "const": continue
        if f.get("type") == "table":
            if f["at"] in done: continue
            done.add(f["at"])
            group = [g for g in m["fields"] if g.get("type") == "table" and g.get("at") == f["at"]]
            rows = []
            if any("pick" in g for g in group):
                merged = {}
                for g in group:
                    for n, x in enumerate(X.get(data, g["field"]) or []): merged.setdefault(n, [None] * len(f["columns"]))[g["pick"]] = x
                rows = [merged[n] for n in sorted(merged)]
            else:
                for g in group: rows += X.table_rows(g, X.get(data, g["field"]))
            specs = X.col_specs(f)
            cols = [(cs.get("title") + " " if cs.get("title") else "") + lab for _, _, lab, _, cs in specs]
            flat = [[(r_[pos] if j_ is None else (r_[pos][j_] if isinstance(r_[pos], list) and j_ < len(r_[pos]) else None)) for pos, j_, *_ in specs] for r_ in rows]
            out.append(dict(label=f.get("caption") or f["field"], columns=cols, rows=flat))
        else:
            out.append(dict(label=f.get("label") or f["field"], value=X.get(data, f["field"])))
    return out


def install(app_module):
    global A
    A = app_module; app = A.app
    with A.db() as c: init_db(c)

    @app.get("/api/jobs/<int:i>/partials")
    @auth.require("jobs.view")
    def partials(i):
        A.getjob(i, False)
        with A.db() as c:
            return jsonify([dict(version=r["version"], at=r["at"], sha256=r["sha256"], sections=json.loads(r["sections"]))
                            for r in c.execute("SELECT version, at, sha256, sections FROM partials WHERE job_id=? ORDER BY version DESC", (i,))])

    @app.get("/api/jobs/<int:i>/partial.pdf")
    @auth.require("report.view")
    def partial_pdf(i):
        j = A.getjob(i, False); v = request.args.get("v", "")
        with A.db() as c:
            r = c.execute("SELECT * FROM partials WHERE job_id=?" + (" AND version=?" if v.isdigit() else "") + " ORDER BY version DESC LIMIT 1",
                          (i, int(v)) if v.isdigit() else (i,)).fetchone()
        if not r: return jsonify(error=["No test has been approved yet, so there is no partial report"]), 404
        return send_file(io.BytesIO(r["pdf"]), mimetype="application/pdf", as_attachment=request.args.get("dl") == "1",
                         download_name=f"PartialReport_{j['series']}_p{r['version']}.pdf")

    @app.get("/api/jobs/<int:i>/approved-values")
    @auth.require("jobs.view")
    def approved_values(i):
        """Values of the approved tests only, labelled as on the logsheet. A test not yet approved shows no numbers."""
        j = A.getjob(i, False)
        with A.db() as c: return jsonify([dict(key=k, name=A.NAMES.get(k, k), items=labelled(c, j, k)) for k in approved_keys(j) if k in A.NAMES])

    # ---- request forms sent in by customers
    @app.post("/api/customer/request-forms")
    @auth.require("jobs.view")
    def customer_form_upload():
        u = auth.current()
        if not auth.is_customer(): return jsonify(error=["This is for customers; staff record the intake directly"]), 403
        name, raw = A.upload(A.body())
        if len(raw) > 5 * 1024 * 1024: return jsonify(error=["The form is too large (5 MB maximum)"]), 400
        try: X.Book(raw, name)
        except X.TemplateError as e: return jsonify(error=[str(e)]), 400
        with A.db() as c:
            fid = c.execute("INSERT INTO customer_forms(org_id,user_id,filename,sha256,content,at) VALUES(?,?,?,?,?,?)",
                            (u["org_id"], u["id"], name[:200], hashlib.sha256(raw).hexdigest(), raw, A.now())).lastrowid
            org = c.execute("SELECT name FROM orgs WHERE id=?", (u["org_id"],)).fetchone()
            A.log(c, None, f"Request form {name} received from customer {org[0] if org else ''}", kind="job")
            A.notify.notify(c, A.notify.users_with(c, "tester"), None, "form", f"New customer request form from {org[0] if org else 'a customer'}: {name}")
        return jsonify(id=fid), 201

    def customer_request(check_only):
        u = auth.current()
        if not auth.is_customer(): return jsonify(error=["This is for customers; staff record the intake directly"]), 403
        b = A.body(); errs, warns, clean = A.workflow.check_intake(b, lab=False)
        plan = [k for k in (b.get("plan") or []) if k in A.NAMES and k != "request"]
        if not plan: errs.append("Tests requested: tick at least one test")
        if check_only: return jsonify(errors=errs, warnings=warns, ok=not errs)
        if errs: return jsonify(error=errs, warnings=warns), 400
        body = integrity.canon(dict(values=clean, plan=plan, warnings=warns)).encode()
        with A.db() as c:
            fid = c.execute("INSERT INTO customer_forms(org_id,user_id,filename,sha256,content,at,kind,data,plan) VALUES(?,?,?,?,?,?,?,?,?)",
                            (u["org_id"], u["id"], "Online request form", hashlib.sha256(body).hexdigest(), body, A.now(), "web",
                             json.dumps(clean), json.dumps(plan))).lastrowid
            org = c.execute("SELECT name FROM orgs WHERE id=?", (u["org_id"],)).fetchone()
            A.log(c, None, f"Online test request received from customer {org[0] if org else ''} ({len(plan)} tests)", kind="job")
            A.notify.notify(c, A.notify.users_with(c, "tester") + A.notify.users_with(c, "admin"), None, "form",
                            f"New test request from {org[0] if org else 'a customer'} (filled online)")
        return jsonify(id=fid), 201

    @app.post("/api/customer/requests/check")
    @auth.require("jobs.view")
    def customer_request_check():
        """The customer's form, checked as they type: everything missing or malformed at once."""
        return customer_request(True)

    @app.post("/api/customer/requests")
    @auth.require("jobs.view")
    def customer_request_send():
        """The customer fills in the request themselves; it waits in the laboratory's intake inbox until the product arrives."""
        return customer_request(False)

    @app.get("/api/customer/request-forms")
    @auth.require("jobs.view")
    def customer_forms_mine():
        u = auth.current()
        if not auth.is_customer(): return jsonify([])
        with A.db() as c:
            return jsonify([dict(r) for r in c.execute("SELECT f.id, f.filename, f.at, f.status, f.kind, j.series FROM customer_forms f LEFT JOIN jobs j ON j.id=f.job_id "
                                                       "WHERE f.org_id=? ORDER BY f.id DESC", (u["org_id"],))])

    @app.get("/api/request-forms")
    @auth.require("job.create")
    def forms_inbox():
        with A.db() as c:
            return jsonify([dict(r) for r in c.execute("SELECT f.id, f.filename, f.at, f.status, f.org_id, f.kind, o.name AS org, u.full_name AS sent_by, j.series "
                                                       "FROM customer_forms f LEFT JOIN orgs o ON o.id=f.org_id LEFT JOIN users u ON u.id=f.user_id "
                                                       "LEFT JOIN jobs j ON j.id=f.job_id ORDER BY (f.status='received') DESC, f.id DESC LIMIT 100")])

    @app.get("/api/request-forms/<int:fid>/file")
    @auth.require("job.create")
    def form_file(fid):
        with A.db() as c: r = c.execute("SELECT * FROM customer_forms WHERE id=?", (fid,)).fetchone()
        if not r: abort(404)
        web = r["kind"] == "web"
        return send_file(io.BytesIO(r["content"]), as_attachment=True, download_name="online_request.json" if web else r["filename"],
                         mimetype="application/json" if web else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/request-forms/<int:fid>/read")
    @auth.require("job.create")
    def form_read(fid):
        """Values of a customer's form for the intake page (still validated and read back by the receiving engineer)."""
        with A.db() as c:
            r = c.execute("SELECT * FROM customer_forms WHERE id=?", (fid,)).fetchone()
            if not r: abort(404)
            ts = A.excel_routes.active(c, "request_form")
        if r["kind"] == "web":  # filled in online: already validated, read as it was sent
            return jsonify(values=json.loads(r["data"]), plan=json.loads(r["plan"] or "[]"), org_id=r["org_id"], fields=[], warnings=[])
        if not ts: return jsonify(error=["No active request form template"]), 409
        bk = X.Book(r["content"], r["filename"]); m = ts[0]["mapping"]
        hits = [ws for ws in bk.sheets() if X.matches(X.Sheet(bk, ws), m.get("fingerprint"))]
        res = X.extract(bk, m, hits[0] if hits else None)
        return jsonify(values={k: v for k, v in res["data"].items() if v not in (None, "")}, org_id=r["org_id"], fields=res["fields"], warnings=res["warnings"])
