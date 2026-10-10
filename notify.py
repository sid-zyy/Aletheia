"""Notifications and lab settings (docs/NEXT_STEPS.md section 7.3).

* In-app notifications first (works on any lab PC). Optional email: queued in an outbox and sent by a background worker
  with retries; a failed email never blocks an upload, and the upload, not the email, is the record.
* Emails carry the job number, what changed and a link to the portal page: never result values, never attachments.
"""
import datetime as dt, json, os, smtplib, threading
from email.message import EmailMessage
from flask import jsonify, request
import auth

A = None
DEFAULTS = {"smtp_host": "", "smtp_port": "587", "smtp_tls": "1", "smtp_user": "",
            "smtp_sender": "", "portal_url": ""}
CRITICAL = {"returned", "released"}  # always sent; others respect the user's email opt-out


def init_db(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT, updated_by INT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INT NOT NULL, job_id INT, section_key TEXT, kind TEXT NOT NULL,
        message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT, email_status TEXT DEFAULT 'none');
    CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id, read_at);
    CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, notification_id INT, to_addr TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
        attempts INT DEFAULT 0, last_error TEXT, created_at TEXT, next_try TEXT, sent_at TEXT);""")
    have = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    for col, ddl in (("completed_at", "TEXT"),):  # when the report was released
        if col not in have: c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
    have = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "email_opt_out" not in have: c.execute("ALTER TABLE users ADD COLUMN email_opt_out INTEGER DEFAULT 0")


def setting(c, k):
    r = c.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r[0] if r and r[0] is not None else os.environ.get("ALETHEIA_" + k.upper(), DEFAULTS.get(k, ""))


# ------------------------------------------------------------------ sending notifications
def users_with(c, role, org_id=None):
    q = "SELECT id, email, email_opt_out FROM users WHERE active=1 AND (',' || roles || ',') LIKE ?"
    a = [f"%,{role},%"]
    if org_id is not None: q += " AND org_id=?"; a.append(org_id)
    return [dict(r) for r in c.execute(q, a)]


def notify(c, recipients, job_id, kind, message, section=None, subject=None):
    """One notification per recipient (inside the caller's transaction), plus an email in the outbox for those with an
    address. recipients: user dicts or ids. The acting user is never notified of their own action."""
    me = (auth.current() or {}).get("id") if A and A.has_request_context() else None
    with_email = setting(c, "smtp_host") != ""
    job = c.execute("SELECT series, org_id FROM jobs WHERE id=?", (job_id,)).fetchone() if job_id else None
    seen, n = set(), 0
    for u in recipients:
        u = u if isinstance(u, dict) else dict(c.execute("SELECT id, email, email_opt_out FROM users WHERE id=?", (u,)).fetchone() or {"id": None})
        if not u.get("id") or u["id"] == me or u["id"] in seen: continue
        seen.add(u["id"])
        mail = with_email and u.get("email") and (kind in CRITICAL or not u.get("email_opt_out"))
        nid = c.execute("INSERT INTO notifications(user_id,job_id,section_key,kind,message,created_at,email_status) VALUES(?,?,?,?,?,?,?)",
                        (u["id"], job_id, section, kind, message, A.now(), "queued" if mail else "none")).lastrowid
        if mail:
            link = (setting(c, "portal_url") or (request.host_url if A.has_request_context() else "")).rstrip("/")
            body = (f"{message}\n\nOpen Aletheia to see the details: {link}/#/{'my' if job and job['org_id'] else 'job'}/{job_id}\n\n"
                    "This message is a notice only; it does not contain test results. The record is in Aletheia.\n"
                    "CPRI Short Circuit Laboratory") if job_id else f"{message}\n\nCPRI Short Circuit Laboratory"
            c.execute("INSERT INTO outbox(notification_id,to_addr,subject,body,created_at,next_try) VALUES(?,?,?,?,?,?)",
                      (nid, u["email"], subject or (f"[{job['series']}] " if job else "") + message[:80], body, A.now(), A.now()))
        n += 1
    if n: A.log(c, job_id, f"Notification ({kind}) to {n} recipient{'s' if n > 1 else ''}: {message[:120]}", kind="notify")
    return n


def customers_of(c, job_id):
    r = c.execute("SELECT org_id FROM jobs WHERE id=?", (job_id,)).fetchone()
    return users_with(c, "customer", r[0]) if r and r[0] else []


def on_uploaded(c, job_id, keys):
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    names = ", ".join(A.NAMES.get(k, k) for k in keys if k in A.NAMES and k != "request")
    if not names: return
    notify(c, users_with(c, "admin"), job_id, "uploaded", f"{series}: {names} uploaded and waiting for verification")
    notify(c, customers_of(c, job_id), job_id, "progress", f"{series}: test data received ({names}); pending verification")


def on_section(c, job_id, key, state, reason=None):
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]; name = A.NAMES.get(key, key)
    if state == "returned":
        up = c.execute("SELECT uploaded_by FROM sections WHERE job_id=? AND key=?", (job_id, key)).fetchone()
        if up and up[0]: notify(c, [up[0]], job_id, "returned", f"{series}: {name} returned for correction: {reason}", section=key)
    elif state == "verified":
        notify(c, customers_of(c, job_id), job_id, "approved", f"{series}: {name} approved; the partial report has been updated", section=key)
        plan = json.loads(c.execute("SELECT plan FROM jobs WHERE id=?", (job_id,)).fetchone()[0] or "[]")
        if not A.workflow.ready_for_signoff(c, job_id, A.NAMES, plan):
            notify(c, users_with(c, "admin"), job_id, "signoff", f"{series}: every test is verified; ready for the verifier's sign-off")


def on_released(c, job_id, version):
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    testers = [r[0] for r in c.execute("SELECT DISTINCT uploaded_by FROM sections WHERE job_id=? AND uploaded_by IS NOT NULL", (job_id,))]
    notify(c, customers_of(c, job_id), job_id, "released", f"{series}: the final test report (version {version}) has been released")
    notify(c, testers, job_id, "released", f"{series}: report version {version} released")


def on_ready_to_approve(c, job_id):
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    notify(c, users_with(c, "approver"), job_id, "approve", f"{series}: report generated and waiting for approval")


# ------------------------------------------------------------------ email outbox
def smtp_transport(c):
    host = setting(c, "smtp_host")
    def send(msg):
        with smtplib.SMTP(host, int(setting(c, "smtp_port") or 587), timeout=20) as s:
            if setting(c, "smtp_tls") == "1": s.starttls()
            if setting(c, "smtp_user"): s.login(setting(c, "smtp_user"), os.environ.get("ALETHEIA_SMTP_PASSWORD", ""))
            s.send_message(msg)
    return send


def send_pending(limit=20):
    """Send what is due in the outbox; failures are retried with growing delays (5 attempts), then left for the admin."""
    with A.db() as c:
        if not setting(c, "smtp_host") and not A.app.config.get("MAIL_TRANSPORT"): return 0
        send = A.app.config.get("MAIL_TRANSPORT") or smtp_transport(c)
        sender = setting(c, "smtp_sender") or "aletheia@localhost"
        due = c.execute("SELECT * FROM outbox WHERE sent_at IS NULL AND attempts<5 AND next_try<=? ORDER BY id LIMIT ?", (A.now(), limit)).fetchall()
    sent = 0
    for m in due:
        msg = EmailMessage(); msg["From"], msg["To"], msg["Subject"] = sender, m["to_addr"], m["subject"]; msg.set_content(m["body"])
        try:
            send(msg); ok, err = True, None
        except Exception as e:  # noqa: BLE001 - recorded and retried; never raised into the lab's work
            ok, err = False, f"{type(e).__name__}: {e}"[:300]
        with A.db() as c:
            if ok:
                c.execute("UPDATE outbox SET sent_at=?, attempts=attempts+1, last_error=NULL WHERE id=?", (A.now(), m["id"]))
                c.execute("UPDATE notifications SET email_status='sent' WHERE id=?", (m["notification_id"],)); sent += 1
            else:
                nxt = (dt.datetime.now() + dt.timedelta(minutes=5 * 2 ** m["attempts"])).isoformat(timespec="seconds")
                c.execute("UPDATE outbox SET attempts=attempts+1, last_error=?, next_try=? WHERE id=?", (err, nxt, m["id"]))
                c.execute("UPDATE notifications SET email_status=? WHERE id=?", ("failed" if m["attempts"] + 1 >= 5 else "retrying", m["notification_id"]))
            A.log(c, None, f"Email to {m['to_addr']} {'sent' if ok else 'failed (' + err + ')'}: {m['subject'][:80]}", kind="notify")
    return sent


def worker():
    """Background: send the email outbox every minute."""
    if os.environ.get("ALETHEIA_WORKER", "1") == "0": return
    def run():
        try:
            send_pending()
        except Exception as e:  # noqa: BLE001
            try:
                with A.db() as c: A.log(c, None, f"Notification worker error: {type(e).__name__}: {e}", kind="admin")
            except Exception: pass  # noqa: BLE001
        t = threading.Timer(60, run); t.daemon = True; t.start()
    t = threading.Timer(15, run); t.daemon = True; t.start()


# ------------------------------------------------------------------ routes
def install(app_module):
    global A
    A = app_module; app = A.app
    with A.db() as c: init_db(c)

    @app.get("/api/notifications")
    @auth.require("notifications")
    def notifications():
        u = auth.current(); only = request.args.get("unread") == "1"
        with A.db() as c:
            rows = [dict(r) for r in c.execute("SELECT n.id, n.job_id, j.series, n.section_key, n.kind, n.message, n.created_at, n.read_at, n.email_status "
                                               "FROM notifications n LEFT JOIN jobs j ON j.id=n.job_id WHERE n.user_id=?" + (" AND n.read_at IS NULL" if only else "") +
                                               " ORDER BY n.id DESC LIMIT 100", (u["id"],))]
            unread = c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (u["id"],)).fetchone()[0]
        return jsonify(items=rows, unread=unread)

    @app.post("/api/notifications/read")
    @auth.require("notifications")
    def notifications_read():
        b = A.body(); u = auth.current(); ids = [int(x) for x in b.get("ids") or [] if str(x).isdigit()]
        with A.db() as c:
            if b.get("all"): c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (A.now(), u["id"]))
            elif ids: c.execute(f"UPDATE notifications SET read_at=? WHERE user_id=? AND id IN ({','.join('?' * len(ids))})", (A.now(), u["id"], *ids))
        return jsonify(ok=True)

    @app.post("/api/me/preferences")
    @auth.signed_in
    def preferences():
        """Opt out of non-critical emails (returns and releases are always sent)."""
        v = int(bool(A.body().get("email_opt_out")))
        with A.db() as c:
            c.execute("UPDATE users SET email_opt_out=? WHERE id=?", (v, auth.current()["id"]))
            A.log(c, None, f"Email notices {'reduced to critical only' if v else 'all on'}", kind="auth")
        return jsonify(ok=True)

    @app.get("/api/settings")
    @auth.require("staff.view")
    def settings_get():
        with A.db() as c: return jsonify({k: setting(c, k) for k in DEFAULTS} | {"smtp_password_set": bool(os.environ.get("ALETHEIA_SMTP_PASSWORD"))})

    @app.post("/api/settings")
    @auth.require("settings.manage")
    def settings_set():
        b = A.body(); err = []
        if "smtp_port" in b and not str(b["smtp_port"]).isdigit(): err.append("SMTP port must be a number")
        if err: return jsonify(error=err), 400
        with A.db() as c:
            for k in DEFAULTS:
                if k in b:
                    c.execute("INSERT INTO settings(key,value,updated_by,updated_at) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                              "updated_by=excluded.updated_by, updated_at=excluded.updated_at", (k, str(b[k]).strip(), auth.current()["id"], A.now()))
            A.log(c, None, "Settings changed: " + ", ".join(f"{k}={str(b[k])[:40]}" for k in DEFAULTS if k in b), kind="admin")
        return jsonify(ok=True)

    @app.get("/api/outbox")
    @auth.require("settings.manage")
    def outbox():
        with A.db() as c:
            return jsonify([dict(r) for r in c.execute("SELECT id, to_addr, subject, attempts, last_error, created_at, next_try, sent_at FROM outbox ORDER BY id DESC LIMIT 200")])

    @app.post("/api/outbox/send")
    @auth.require("settings.manage")
    def outbox_send(): return jsonify(sent=send_pending(100))
