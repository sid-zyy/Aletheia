"""Data integrity (docs/NEXT_STEPS.md sections 4.1, 4.5 and 6).

* One row per section (`sections`) instead of one JSON blob per job, so testers working on different tests of the same job
  never overwrite each other. Each row carries a revision counter: a write that names an older revision is refused (409).
* Every write to a section is copied into `section_history` (append-only): nothing a tester uploaded is ever lost.
* Uploaded data files are kept byte-for-byte in `files` with their SHA-256 (append-only).
* The audit log is a hash chain: each entry stores the hash of the one before it, so a changed or deleted entry is detectable.
* Database triggers refuse changes to released jobs, to stored reports, files and history, whatever code (or person with a
  database tool) attempts them.
* Series and sample numbers are allocated inside one write transaction, so two people creating jobs at once cannot get the
  same number.
* Schema changes are numbered (`schema_version`) and the database is backed up before a migration touches existing data.
"""
import datetime as dt, hashlib, json, os, re, sqlite3

SCHEMA_VERSION = 2
now = lambda: dt.datetime.now().isoformat(timespec="seconds")
MERGED = ("ids", "request", "other")  # sections built up from several files (merged); every other section is replaced whole


class Locked(Exception):
    """A verified section: only a tester's reopen (with a reason) makes it writable again."""
    def __init__(self, key, row):
        super().__init__(key); self.key, self.row = key, row


class Conflict(Exception):
    """A section changed since the caller read it."""
    def __init__(self, key, row):
        super().__init__(key); self.key, self.row = key, row


def canon(v): return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def sha(b): return hashlib.sha256(b if isinstance(b, bytes) else str(b).encode("utf-8")).hexdigest()


def init_db(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL, at TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS sections(id INTEGER PRIMARY KEY, job_id INT NOT NULL, key TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'uploaded',
        data TEXT, data_sha256 TEXT, file_id INT, import_id INT, bay TEXT, uploaded_by INT, uploaded_at TEXT, verified_by INT, verified_at TEXT,
        note TEXT, revision INTEGER NOT NULL DEFAULT 1, UNIQUE(job_id, key));
    CREATE TABLE IF NOT EXISTS section_history(id INTEGER PRIMARY KEY, job_id INT NOT NULL, key TEXT NOT NULL, revision INT NOT NULL,
        state TEXT, data TEXT, data_sha256 TEXT, file_id INT, user_id INT, event TEXT, at TEXT);
    CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, job_id INT NOT NULL, name TEXT, mime TEXT, sha256 TEXT NOT NULL, size INT,
        content BLOB NOT NULL, uploaded_by INT, at TEXT);
    CREATE TABLE IF NOT EXISTS counters(name TEXT NOT NULL, year INT NOT NULL, last INT NOT NULL, PRIMARY KEY(name, year));
    CREATE TABLE IF NOT EXISTS assignments(job_id INT NOT NULL, key TEXT NOT NULL, user_id INT NOT NULL, assigned_by INT, at TEXT, PRIMARY KEY(job_id, key));
    CREATE TABLE IF NOT EXISTS bays(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, active INTEGER DEFAULT 1, created_at TEXT);
    CREATE TABLE IF NOT EXISTS amendments(id INTEGER PRIMARY KEY, job_id INT NOT NULL, from_version INT NOT NULL, reason TEXT NOT NULL, sections TEXT NOT NULL,
        opened_by INT NOT NULL, second_signer INT NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT, new_version INT);
    CREATE INDEX IF NOT EXISTS ix_sections_job ON sections(job_id);
    CREATE INDEX IF NOT EXISTS ix_history_job ON section_history(job_id, key);
    CREATE INDEX IF NOT EXISTS ix_audit_job ON audit(job_id);""")
    for t, cols in (("audit", (("prev_hash", "TEXT"), ("entry_hash", "TEXT"))), ("imports", (("file_id", "INT"),)), ("assignments", (("bay_id", "INT"),)),
                    ("jobs", (("amend", "TEXT"),)), ("reports", (("manifest", "TEXT"), ("manifest_sha256", "TEXT"))), ("sections", (("bay_id", "INT"), ("template_id", "INT"))),
                    ("section_history", (("note", "TEXT"), ("template_id", "INT")))):
        have = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
        for col, ddl in cols:
            if col not in have: c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {ddl}")


def version(c):
    r = c.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return r[0] or 1


# ------------------------------------------------------------------ migration
def backup(db_path, tag):
    """Consistent copy of the database next to it (SQLite's online backup), before a migration changes anything."""
    if not db_path or not os.path.exists(db_path): return None
    dst = f"{db_path}.{tag}-{dt.datetime.now():%Y%m%d-%H%M%S}.bak"
    src = sqlite3.connect(db_path); out = sqlite3.connect(dst)
    try: src.backup(out)
    finally: out.close(); src.close()
    return dst


def migrate(c, db_path):
    """Version 2: split each job's JSON blob into section rows and seal the audit trail into a hash chain."""
    v = version(c)
    if v >= SCHEMA_VERSION: return None
    has_blob = "data" in {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    legacy = c.execute("SELECT COUNT(*) FROM jobs WHERE data IS NOT NULL AND data NOT IN ('', '{}')").fetchone()[0] if has_blob else 0
    audit_rows = c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    saved = None
    if legacy or audit_rows:
        c.commit()  # the backup must see everything written so far
        saved = backup(db_path, "pre-v2")
    t = now()
    for jid, data in (c.execute("SELECT id, data FROM jobs WHERE data IS NOT NULL AND data NOT IN ('', '{}')").fetchall() if has_blob else []):
        try: d = json.loads(data)
        except ValueError: continue
        for k, val in d.items():
            if c.execute("SELECT 1 FROM sections WHERE job_id=? AND key=?", (jid, k)).fetchone(): continue
            body = canon(val)
            c.execute("INSERT INTO sections(job_id,key,state,data,data_sha256,uploaded_at,revision,note) VALUES(?,?,?,?,?,?,1,'migrated')",
                      (jid, k, "uploaded", body, sha(body), t))
            c.execute("INSERT INTO section_history(job_id,key,revision,state,data,data_sha256,event,at) VALUES(?,?,1,'uploaded',?,?,?,?)",
                      (jid, k, body, sha(body), "Migrated from the single-record format (schema 1)", t))
        c.execute("UPDATE jobs SET data='{}' WHERE id=?", (jid,))
    seal_unsealed(c)
    c.execute("INSERT INTO schema_version(version,at,note) VALUES(?,?,?)",
              (2, t, f"sections split from jobs.data ({legacy} jobs); audit hash chain started" + (f"; backup {os.path.basename(saved)}" if saved else "")))
    return saved


# ------------------------------------------------------------------ sections
def job_data(c, jid):
    """The job's data as one dict, assembled from its sections (what validation and the report read)."""
    return {k: json.loads(d) for k, d in c.execute("SELECT key, data FROM sections WHERE job_id=? AND data IS NOT NULL AND state!='na' ORDER BY id", (jid,))}


def section_meta(c, jid):
    rows = c.execute("""SELECT s.key, s.state, s.revision, s.uploaded_at, s.verified_at, s.data_sha256, s.note, s.bay, s.file_id, s.template_id,
                               s.uploaded_by AS uploaded_by_id, s.verified_by AS verified_by_id,
                               u.full_name AS uploaded_by, v.full_name AS verified_by, f.name AS file, f.sha256 AS file_sha256
                        FROM sections s LEFT JOIN users u ON u.id=s.uploaded_by LEFT JOIN users v ON v.id=s.verified_by
                        LEFT JOIN files f ON f.id=s.file_id WHERE s.job_id=? ORDER BY s.id""", (jid,))
    return {r["key"]: {k: r[k] for k in r.keys() if k != "key"} for r in rows}


def assignments(c, jid):
    return {r["key"]: dict(user_id=r["user_id"], name=r["full_name"], bay_id=r["bay_id"], bay=r["bay"], self=r["user_id"] == r["assigned_by"]) for r in
            c.execute("SELECT a.key, a.user_id, a.assigned_by, a.bay_id, b.name AS bay, u.full_name FROM assignments a LEFT JOIN users u ON u.id=a.user_id "
                      "LEFT JOIN bays b ON b.id=a.bay_id WHERE a.job_id=?", (jid,))}


def write_section(c, jid, key, data, user_id, event, expect=None, file_id=None, import_id=None, state="uploaded", template_id=None):
    """Create, replace or (data=None) remove one section, inside the caller's transaction.
    expect: the revision the caller last read; if the row has moved on since, Conflict is raised and nothing is written.
    A verified section raises Locked, except the merged ones (identifiers, request, additional sheets), which many files
    add to: new content simply needs verifying again. (Test bays were removed: the bay columns keep what older records were recorded with.)"""
    row = c.execute("SELECT * FROM sections WHERE job_id=? AND key=?", (jid, key)).fetchone()
    if expect is not None and (row["revision"] if row else 0) != expect: raise Conflict(key, row)
    if row and row["state"] == "verified":
        if key not in MERGED: raise Locked(key, row)
        c.execute("UPDATE sections SET state='uploaded' WHERE id=?", (row["id"],))  # unlock first (the trigger checks the old state)
    t = now(); bay_id, bay_name = None, None
    if data is None:
        if not row: return None
        rev = row["revision"] + 1
        c.execute("DELETE FROM sections WHERE id=?", (row["id"],))
        c.execute("INSERT INTO section_history(job_id,key,revision,state,data,data_sha256,file_id,user_id,event,at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (jid, key, rev, "removed", None, None, None, user_id, event, t))
        return rev
    body = canon(data); h = sha(body)
    if row:
        rev = row["revision"] + 1
        c.execute("UPDATE sections SET state=?, data=?, data_sha256=?, file_id=?, import_id=?, uploaded_by=?, uploaded_at=?, verified_by=NULL, "
                  "verified_at=NULL, note=NULL, revision=?, bay_id=?, bay=?, template_id=? WHERE id=?",
                  (state, body, h, file_id, import_id, user_id, t, rev, bay_id, bay_name, template_id, row["id"]))
    else:
        rev = 1
        c.execute("INSERT INTO sections(job_id,key,state,data,data_sha256,file_id,import_id,uploaded_by,uploaded_at,revision,bay_id,bay,template_id) VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?)",
                  (jid, key, state, body, h, file_id, import_id, user_id, t, bay_id, bay_name, template_id))
    c.execute("INSERT INTO section_history(job_id,key,revision,state,data,data_sha256,file_id,user_id,event,at,template_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (jid, key, rev, state, body, h, file_id, user_id, event, t, template_id))
    return rev


def set_state(c, jid, key, state, user_id, event, note=None, expect=None):
    """Verify / return / reopen / mark not applicable: the data stays as it is, the state changes and is recorded."""
    row = c.execute("SELECT * FROM sections WHERE job_id=? AND key=?", (jid, key)).fetchone()
    if expect is not None and (row["revision"] if row else 0) != expect: raise Conflict(key, row)
    t = now()
    if row is None:  # only "not applicable" can be recorded for a test that has no data
        c.execute("INSERT INTO sections(job_id,key,state,uploaded_by,uploaded_at,note,revision) VALUES(?,?,?,?,?,?,1)", (jid, key, state, user_id, t, note))
        rev = 1
    else:
        rev = row["revision"] + 1
        if state == "verified":
            c.execute("UPDATE sections SET state=?, verified_by=?, verified_at=?, note=?, revision=? WHERE id=?", (state, user_id, t, note, rev, row["id"]))
        else:
            c.execute("UPDATE sections SET state=?, verified_by=NULL, verified_at=NULL, note=?, revision=? WHERE id=?", (state, note, rev, row["id"]))
    c.execute("INSERT INTO section_history(job_id,key,revision,state,data,data_sha256,file_id,user_id,event,at,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (jid, key, rev, state, row["data"] if row else None, row["data_sha256"] if row else None, row["file_id"] if row else None, user_id, event, t, note))
    return rev


def read_section(c, jid, key):
    r = c.execute("SELECT data FROM sections WHERE job_id=? AND key=?", (jid, key)).fetchone()
    return json.loads(r[0]) if r and r[0] else None


def store_file(c, jid, name, raw, mime, user_id):
    cur = c.execute("INSERT INTO files(job_id,name,mime,sha256,size,content,uploaded_by,at) VALUES(?,?,?,?,?,?,?,?)",
                    (jid, name, mime, sha(raw), len(raw), raw, user_id, now()))
    return cur.lastrowid


# ------------------------------------------------------------------ numbering
SERIES_FMT, SAMPLE_FMT = "CPRIBLRSCL{yy:02d}T{n:04d}", "HVD{yy:02d}S{n:04d}"


def allocate(c, kind, year=None):
    """Next free series ('series') or sample code ('sample') for the year. Call inside a BEGIN IMMEDIATE transaction."""
    yy = (year or dt.date.today().year) % 100
    fmt, col = (SERIES_FMT, "series") if kind == "series" else (SAMPLE_FMT, "sample")
    row = c.execute("SELECT last FROM counters WHERE name=? AND year=?", (kind, yy)).fetchone()
    if row is None:  # first allocation this year: continue after the highest number already used (typed in or imported)
        pat = re.compile(re.escape(fmt.split("{")[0]) + f"{yy:02d}" + ("T" if kind == "series" else "S") + r"(\d{4})$")
        used = [int(m.group(1)) for (v,) in c.execute(f"SELECT {col} FROM jobs WHERE {col} IS NOT NULL") if (m := pat.match(str(v)))]
        last = max(used, default=0)
        c.execute("INSERT INTO counters(name,year,last) VALUES(?,?,?)", (kind, yy, last))
    else: last = row[0]
    while True:
        last += 1
        if last > 9999: raise ValueError(f"No {kind} numbers left for 20{yy:02d}")
        val = fmt.format(yy=yy, n=last)
        if not c.execute(f"SELECT 1 FROM jobs WHERE {col}=?", (val,)).fetchone(): break
    c.execute("UPDATE counters SET last=? WHERE name=? AND year=?", (last, kind, yy))
    return val


# ------------------------------------------------------------------ audit hash chain
AUDIT_FIELDS = ("id", "job_id", "event", "at", "user_id", "actor", "role", "ip", "kind")


def entry_hash(prev, row): return sha(canon([prev or ""] + [row[k] for k in AUDIT_FIELDS]))


def seal(c, rowid):
    """Link a new audit row to the chain. Runs in the same transaction as the INSERT, which already holds SQLite's write lock,
    so no other entry can slip in between reading the previous hash and writing this one."""
    prev = c.execute("SELECT entry_hash FROM audit WHERE id<? ORDER BY id DESC LIMIT 1", (rowid,)).fetchone()
    row = c.execute(f"SELECT {','.join(AUDIT_FIELDS)} FROM audit WHERE id=?", (rowid,)).fetchone()
    p = prev[0] if prev else None
    c.execute("UPDATE audit SET prev_hash=?, entry_hash=? WHERE id=?", (p, entry_hash(p, dict(zip(AUDIT_FIELDS, row))), rowid))


def seal_unsealed(c):
    for (rid,) in c.execute("SELECT id FROM audit WHERE entry_hash IS NULL ORDER BY id").fetchall(): seal(c, rid)


def verify_chain(c):
    """Recompute the whole chain. Reports the first entry whose content or link no longer matches."""
    prev, n = None, 0
    for r in c.execute(f"SELECT {','.join(AUDIT_FIELDS)}, prev_hash, entry_hash FROM audit ORDER BY id"):
        row = dict(zip(AUDIT_FIELDS + ("prev_hash", "entry_hash"), r)); n += 1
        if row["entry_hash"] is None: return dict(ok=False, checked=n, broken_at=row["id"], reason="entry was never sealed")
        if row["prev_hash"] != prev: return dict(ok=False, checked=n, broken_at=row["id"], reason="link to the previous entry is broken (an entry was removed or inserted)")
        if entry_hash(prev, row) != row["entry_hash"]: return dict(ok=False, checked=n, broken_at=row["id"], reason="entry content was changed")
        prev = row["entry_hash"]
    return dict(ok=True, checked=n, tip=prev)


# ------------------------------------------------------------------ triggers (defence in depth)
RELEASED = "(SELECT stage FROM jobs WHERE id={j})=4 AND (SELECT archived FROM jobs WHERE id={j})=0"
EVER = "EXISTS(SELECT 1 FROM reports WHERE job_id={j} AND approver IS NOT NULL)"  # a report was released at some point
# while an amendment is open, only the sections it names may change
OUTSIDE = ("(SELECT amend FROM jobs WHERE id={j}) IS NOT NULL AND NOT EXISTS(SELECT 1 FROM json_each(json_extract((SELECT amend FROM jobs WHERE id={j}),"
           "'$.sections')) WHERE value={k})")
TRIGGERS = {
    "audit_no_delete": "BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit entries cannot be deleted'); END",
    "audit_no_update": "BEFORE UPDATE ON audit WHEN OLD.entry_hash IS NOT NULL BEGIN SELECT RAISE(ABORT, 'audit entries cannot be changed'); END",
    "files_no_update": "BEFORE UPDATE ON files BEGIN SELECT RAISE(ABORT, 'stored files cannot be changed'); END",
    "files_no_delete_released": f"BEFORE DELETE ON files WHEN {EVER.format(j='OLD.job_id')} BEGIN SELECT RAISE(ABORT, 'files of a released report cannot be deleted'); END",
    "history_no_update": "BEFORE UPDATE ON section_history BEGIN SELECT RAISE(ABORT, 'section history cannot be changed'); END",
    "history_no_delete_released": f"BEFORE DELETE ON section_history WHEN {EVER.format(j='OLD.job_id')} BEGIN SELECT RAISE(ABORT, 'history of a released report cannot be deleted'); END",
    "reports_no_update": "BEFORE UPDATE ON reports BEGIN SELECT RAISE(ABORT, 'stored reports cannot be changed'); END",
    "reports_no_delete_released": "BEFORE DELETE ON reports WHEN OLD.approver IS NOT NULL BEGIN SELECT RAISE(ABORT, 'a released report cannot be deleted'); END",
    "sources_no_update": "BEFORE UPDATE OF content, sha256, filename ON sources BEGIN SELECT RAISE(ABORT, 'source documents cannot be changed'); END",
    "sources_no_delete_released": f"BEFORE DELETE ON sources WHEN {EVER.format(j='OLD.job_id')} BEGIN SELECT RAISE(ABORT, 'source documents of a released report cannot be deleted'); END",
    "sections_amend_update": f"BEFORE UPDATE ON sections WHEN {OUTSIDE.format(j='OLD.job_id', k='OLD.key')} BEGIN SELECT RAISE(ABORT, 'only the sections named in the amendment can change'); END",
    "sections_amend_insert": f"BEFORE INSERT ON sections WHEN {OUTSIDE.format(j='NEW.job_id', k='NEW.key')} BEGIN SELECT RAISE(ABORT, 'only the sections named in the amendment can change'); END",
    "sections_amend_delete": f"BEFORE DELETE ON sections WHEN {OUTSIDE.format(j='OLD.job_id', k='OLD.key')} BEGIN SELECT RAISE(ABORT, 'only the sections named in the amendment can change'); END",
    "sections_locked_update": f"BEFORE UPDATE ON sections WHEN {RELEASED.format(j='OLD.job_id')} BEGIN SELECT RAISE(ABORT, 'the report is released: its data is locked'); END",
    "sections_locked_delete": f"BEFORE DELETE ON sections WHEN {RELEASED.format(j='OLD.job_id')} BEGIN SELECT RAISE(ABORT, 'the report is released: its data is locked'); END",
    "sections_locked_insert": f"BEFORE INSERT ON sections WHEN {RELEASED.format(j='NEW.job_id')} BEGIN SELECT RAISE(ABORT, 'the report is released: its data is locked'); END",
    "sections_verified_data": "BEFORE UPDATE OF data ON sections WHEN OLD.state='verified' AND NEW.data IS NOT OLD.data "
                              "BEGIN SELECT RAISE(ABORT, 'a verified section cannot be changed; a tester must reopen it'); END",
    "sections_verified_delete": "BEFORE DELETE ON sections WHEN OLD.state='verified' AND EXISTS(SELECT 1 FROM jobs WHERE id=OLD.job_id) "
                                "BEGIN SELECT RAISE(ABORT, 'a verified section cannot be removed; a tester must reopen it'); END",
    # a released job changes only by opening an amendment (amend set in the same update)
    "jobs_released_locked": "BEFORE UPDATE OF series, sample, customer, rating, stage, approver, approver_id, findings, org_id, data, plan, intake, signed_off_by ON jobs "
                            "WHEN OLD.stage=4 AND OLD.archived=0 AND NEW.amend IS NULL BEGIN SELECT RAISE(ABORT, 'the report is released: the record is locked'); END",
    "jobs_released_no_delete": f"BEFORE DELETE ON jobs WHEN OLD.archived=0 AND {EVER.format(j='OLD.id')} BEGIN SELECT RAISE(ABORT, 'a released record cannot be deleted'); END",
    "amendments_no_delete": "BEFORE DELETE ON amendments BEGIN SELECT RAISE(ABORT, 'amendments are part of the record'); END",
    "amendments_closed": "BEFORE UPDATE ON amendments WHEN OLD.closed_at IS NOT NULL BEGIN SELECT RAISE(ABORT, 'a closed amendment cannot be changed'); END",
}


def install_triggers(c):
    """(Re)create every trigger, so a changed definition takes effect on the next start."""
    for name, body in TRIGGERS.items():
        c.execute(f"DROP TRIGGER IF EXISTS {name}"); c.execute(f"CREATE TRIGGER {name} {body}")


def drop_triggers(c):
    """Maintenance only (tests, an approved repair): the triggers come back with install_triggers or the next start."""
    for name in TRIGGERS: c.execute(f"DROP TRIGGER IF EXISTS {name}")
