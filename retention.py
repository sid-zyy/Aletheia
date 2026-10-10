"""Retention for 10+ years (docs/NEXT_STEPS.md section 6.6).

* Backups: a consistent copy of the database (SQLite online backup) with a SHA-256 file beside it, made on request and
  once a day by a background timer. The newest N are kept, plus the first backup of every month, which are never removed.
* Each backup also writes the audit chain's tip hash to a small text file: copy it to another medium (or write it in the
  paper register) daily, so that even removing the newest audit entries can be detected later.
* Backup check (the restore drill without stopping the lab): integrity check, counts, audit chain, report fingerprints,
  all inside the backup file.
* Export package per job: every released version of the report, its manifest, the source files, the section history and
  the audit extract, with a README on how to verify them. It is self-contained: readable without Aletheia.
"""
import csv, datetime as dt, glob, hashlib, io, json, os, re, sqlite3, threading, zipfile
from flask import jsonify, request, send_file, abort
import auth, integrity

A = None
KEEP = int(os.environ.get("ALETHEIA_BACKUP_KEEP", "30"))


def folder():
    d = os.environ.get("ALETHEIA_BACKUP_DIR") or os.path.join(os.path.dirname(os.path.abspath(A.DB)), "backups")
    os.makedirs(d, exist_ok=True); return d


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def backup(reason="manual"):
    """Copy the live database consistently, write its checksum and today's audit tip. Returns the backup's details."""
    d = folder(); t = dt.datetime.now()
    name = f"aletheia-{t:%Y%m%d-%H%M%S}.db"; path = os.path.join(d, name)
    src = sqlite3.connect(A.DB, timeout=30); out = sqlite3.connect(path)
    try: src.backup(out)
    finally: out.close(); src.close()
    digest = sha_file(path)
    with open(path + ".sha256", "w", encoding="utf-8") as f: f.write(f"{digest}  {name}\n")
    with A.db() as c: chain = integrity.verify_chain(c)
    with open(os.path.join(d, f"audit-tip-{t:%Y%m%d}.txt"), "a", encoding="utf-8") as f:
        f.write(f"{t.isoformat(timespec='seconds')}  entries={chain['checked']}  tip={chain.get('tip')}  chain={'intact' if chain['ok'] else 'BROKEN at ' + str(chain.get('broken_at'))}\n")
    prune(d)
    with A.db() as c: A.log(c, None, f"Backup made ({reason}): {name}, SHA-256 {digest[:12]}..., audit tip {str(chain.get('tip'))[:12]}...", kind="admin")
    return dict(name=name, sha256=digest, size=os.path.getsize(path), audit_tip=chain.get("tip"), chain_ok=chain["ok"])


def prune(d):
    """Keep the newest KEEP backups and the first one of each month."""
    files = sorted(glob.glob(os.path.join(d, "aletheia-*.db")))
    months = {}
    for p in files: months.setdefault(os.path.basename(p)[9:15], p)
    keep = set(files[-KEEP:]) | set(months.values())
    for p in files:
        if p not in keep:
            for x in (p, p + ".sha256"):
                try: os.remove(x)
                except OSError: pass


def listing():
    d = folder(); out = []
    for p in sorted(glob.glob(os.path.join(d, "aletheia-*.db")), reverse=True):
        side = p + ".sha256"; want = open(side, encoding="utf-8").read().split()[0] if os.path.exists(side) else None
        out.append(dict(name=os.path.basename(p), size=os.path.getsize(p), at=dt.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds"),
                        sha256=want))
    return out


def check(name):
    """The restore drill on a copy: is the backup complete, uncorrupted and consistent with what it claims?"""
    if not re.fullmatch(r"aletheia-\d{8}-\d{6}\.db", name or ""): abort(404)
    path = os.path.join(folder(), name)
    if not os.path.exists(path): abort(404)
    side = path + ".sha256"; want = open(side, encoding="utf-8").read().split()[0] if os.path.exists(side) else None
    got = sha_file(path)
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    try:
        ic = c.execute("PRAGMA integrity_check").fetchone()[0]
        n = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("jobs", "sections", "files", "reports", "audit", "users")}
        chain = integrity.verify_chain(c)
        bad = [f"{r['series']} v{r['version']}" for r in c.execute("SELECT r.version, r.sha256, r.pdf, j.series FROM reports r JOIN jobs j ON j.id=r.job_id")
               if hashlib.sha256(r["pdf"]).hexdigest() != r["sha256"]]
        files_bad = [r["name"] for r in c.execute("SELECT name, sha256, content FROM files") if hashlib.sha256(r["content"]).hexdigest() != r["sha256"]]
    finally: c.close()
    ok = ic == "ok" and (want is None or want == got) and chain["ok"] and not bad and not files_bad
    return dict(name=name, ok=ok, checksum_matches=(want == got) if want else None, integrity=ic, counts=n, audit_chain=chain,
                reports_altered=bad, files_altered=files_bad)


def package(j):
    """Zip of everything needed to read and verify a job's report for as long as it must be kept."""
    out = io.BytesIO(); z = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED); i = j["id"]; s = j["series"]
    with A.db() as c:
        reps = c.execute("SELECT version, token, sha256, pdf, approver, approver_id, at, manifest, manifest_sha256 FROM reports WHERE job_id=? AND approver IS NOT NULL ORDER BY version", (i,)).fetchall()
        files = c.execute("SELECT id, name, sha256, content, at FROM files WHERE job_id=? ORDER BY id", (i,)).fetchall()
        srcs = c.execute("SELECT id, filename, sha256, content, at FROM sources WHERE job_id=? ORDER BY id", (i,)).fetchall()
        hist = [dict(r) for r in c.execute("SELECT h.key, h.revision, h.state, h.data, h.data_sha256, h.event, h.at, h.note, u.full_name AS by, f.sha256 AS file_sha256 "
                                           "FROM section_history h LEFT JOIN users u ON u.id=h.user_id LEFT JOIN files f ON f.id=h.file_id WHERE h.job_id=? ORDER BY h.id", (i,))]
        aud = [dict(r) for r in c.execute("SELECT id, at, actor, role, ip, kind, event, prev_hash, entry_hash FROM audit WHERE job_id=? ORDER BY id", (i,))]
        ams = [dict(r) for r in c.execute("SELECT from_version, new_version, reason, sections, opened_at, closed_at FROM amendments WHERE job_id=? ORDER BY id", (i,))]
    sums = []
    def put(name, data):
        b = data if isinstance(data, bytes) else data.encode("utf-8"); z.writestr(name, b); sums.append(f"{hashlib.sha256(b).hexdigest()}  {name}")
    newest = reps[-1]["version"] if reps else None
    for r in reps:
        tag = "" if r["version"] == newest else "_SUPERSEDED"
        put(f"report/TestReport_{s}_v{r['version']}{tag}.pdf", r["pdf"])
        if r["manifest"]: put(f"report/manifest_v{r['version']}.json", r["manifest"])  # byte for byte as hashed
    for f in files: put(f"source-data/{f['id']:04d}_{safe(f['name'])}", f["content"])
    for f in srcs: put(f"source-documents/{f['id']:04d}_{safe(f['filename'])}", f["content"])
    put("record/section_history.json", json.dumps(hist, indent=1))
    put("record/amendments.json", json.dumps(ams, indent=1))
    put("record/data.json", json.dumps(j["data"], indent=1))
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(["id", "at", "actor", "role", "workstation", "kind", "event", "prev_hash", "entry_hash"])
    for a in aud: w.writerow([a["id"], a["at"], a["actor"], a["role"], a["ip"], a["kind"], a["event"], a["prev_hash"], a["entry_hash"]])
    put("record/audit.csv", buf.getvalue())
    put("README.txt", f"""Test report record {s} (sample {j['sample']}), exported {dt.datetime.now():%Y-%m-%d %H:%M} from Aletheia
(software {A.code_id()}, database schema {integrity.SCHEMA_VERSION}).

report/          every released version of the test report; earlier versions are marked _SUPERSEDED (amendments.json says why).
                 manifest_vN.json lists what version N was built from; its SHA-256 is printed on the last page of that PDF.
source-data/     the uploaded data files, exactly as received.
source-documents/ the scans and the customer's request form, exactly as received.
record/          section_history.json (every revision of every test's data, with who and when), audit.csv (the audit trail
                 of this job; entry_hash links each entry to the previous one in the full chain), data.json (the data used).
SHA256SUMS.txt   the SHA-256 of every file in this package.

To verify: the SHA-256 of a report PDF must equal the one on the verification page and in SHA256SUMS.txt; the SHA-256
of manifest_vN.json must equal the "Manifest SHA-256" printed on the last page of version N.
""")
    z.writestr("SHA256SUMS.txt", "\n".join(sums) + "\n"); z.close()
    return out.getvalue()


def safe(n): return re.sub(r"[^A-Za-z0-9._ -]+", "_", str(n or "file"))[:120]


_timer = None
def schedule():
    """One backup a day while the server runs (ALETHEIA_AUTO_BACKUP=0 turns it off)."""
    global _timer
    if os.environ.get("ALETHEIA_AUTO_BACKUP", "1") == "0": return
    def run():
        try:
            today = f"aletheia-{dt.date.today():%Y%m%d}"
            if not any(b["name"].startswith(today) for b in listing()): backup("daily")
        except Exception as e:  # noqa: BLE001 - a failed backup must never stop the lab; it is logged instead
            try:
                with A.db() as c: A.log(c, None, f"Daily backup FAILED: {type(e).__name__}: {e}", kind="admin")
            except Exception: pass  # noqa: BLE001
        schedule_next()
    def schedule_next():
        global _timer
        _timer = threading.Timer(3600, run); _timer.daemon = True; _timer.start()  # checks hourly, backs up once a day
    _timer = threading.Timer(60, run); _timer.daemon = True; _timer.start()


def install(app_module):
    global A
    A = app_module; app = A.app

    @app.get("/api/admin/backups")
    @auth.require("settings.manage")
    def backups(): return jsonify(folder=folder(), keep=KEEP, backups=listing())

    @app.post("/api/admin/backups")
    @auth.require("settings.manage")
    def backup_now(): return jsonify(backup("manual")), 201

    @app.get("/api/admin/backups/<name>/check")
    @auth.require("settings.manage")
    def backup_check(name):
        r = check(name)
        with A.db() as c: A.log(c, None, f"Backup {name} checked: {'OK' if r['ok'] else 'PROBLEM'}", kind="admin")
        return jsonify(r)

    @app.get("/api/audit/tip")
    @auth.require("audit.read")
    def audit_tip():
        with A.db() as c: r = integrity.verify_chain(c)
        return jsonify(at=A.now(), entries=r["checked"], tip=r.get("tip"), chain_ok=r["ok"])

    @app.get("/api/jobs/<int:i>/package.zip")
    @auth.require("data.export")
    def job_package(i):
        j = A.getjob(i)
        if not j["ever_released"]: return jsonify(error=["Export packages are made for released reports"]), 409
        raw = package(j)
        with A.db() as c: A.log(c, i, f"Retention package exported (SHA-256 {hashlib.sha256(raw).hexdigest()[:12]}...)", kind="event")
        return send_file(io.BytesIO(raw), mimetype="application/zip", as_attachment=True, download_name=f"{j['series']}_record_{dt.date.today():%Y%m%d}.zip")

    @app.get("/api/time")
    @auth.public
    def server_time():
        """The server's clock: the page warns when the workstation and the server disagree (legal timestamps)."""
        return jsonify(now=dt.datetime.now().isoformat(timespec="seconds"), utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
