"""In-app notifications. Aletheia sends no email: every notice is in the portal, where it
opens the job, test or request it is about. (The settings and outbox tables of earlier versions are left in the database,
unused.)
"""
import datetime as dt, json
from flask import jsonify, request
import auth

A = None
# kinds that ask the recipient to do something (shown under "Needs your action"); the rest are for information
ACTION = {"assigned", "returned", "uploaded", "signoff", "approve", "form"}
COMBINE_MINUTES = 30  # repeats of one kind for one job, still unread, within this time become one row


def init_db(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INT NOT NULL, job_id INT, section_key TEXT, kind TEXT NOT NULL,
        message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT);
    CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id, read_at);""")
    have = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    for col, ddl in (("completed_at", "TEXT"),):  # when the report was released
        if col not in have: c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
    have = {r[1] for r in c.execute("PRAGMA table_info(notifications)")}
    for col, ddl in (("target", "TEXT"), ("count", "INTEGER DEFAULT 1")):  # target: the page it opens (#/...), kept with it
        if col not in have: c.execute(f"ALTER TABLE notifications ADD COLUMN {col} {ddl}")


# ------------------------------------------------------------------ sending notifications
def users_with(c, role, org_id=None):
    q = "SELECT id FROM users WHERE active=1 AND (',' || roles || ',') LIKE ?"
    a = [f"%,{role},%"]
    if org_id is not None: q += " AND org_id=?"; a.append(org_id)
    return [dict(r) for r in c.execute(q, a)]


def target_of(job_id, customer):
    return (f"my/{job_id}" if customer else f"job/{job_id}") if job_id else None


def notify(c, recipients, job_id, kind, message, section=None, target=None):
    """One notification per recipient (inside the caller's transaction). recipients: user dicts or ids. The acting user is
    never notified of their own action. target: the page the
    notification opens (without '#/'); by default the job (a customer's own job page for customers). A repeat of the same
    kind for the same job, still unread and recent, updates that row (count + 1) instead of adding another."""
    me = (auth.current() or {}).get("id") if A and A.has_request_context() else None
    seen, n = set(), 0
    for u in recipients:
        u = u if isinstance(u, dict) else {"id": u}
        if not u.get("id") or u["id"] == me or u["id"] in seen: continue
        seen.add(u["id"])
        roles = c.execute("SELECT roles FROM users WHERE id=?", (u["id"],)).fetchone()
        tg = target or target_of(job_id, "customer" in str(roles[0] if roles else "").split(","))
        since = (dt.datetime.now() - dt.timedelta(minutes=COMBINE_MINUTES)).isoformat(timespec="seconds")
        old = c.execute("SELECT id FROM notifications WHERE user_id=? AND kind=? AND job_id=? AND read_at IS NULL AND created_at>=? AND kind!='assigned' "
                        "ORDER BY id DESC LIMIT 1", (u["id"], kind, job_id, since)).fetchone() if job_id else None
        if old:
            nid = old[0]
            c.execute("UPDATE notifications SET message=?, section_key=?, target=?, created_at=?, count=COALESCE(count,1)+1 WHERE id=?",
                      (message, section, tg, A.now(), nid))
        else:
            c.execute("INSERT INTO notifications(user_id,job_id,section_key,kind,message,created_at,target) VALUES(?,?,?,?,?,?,?)",
                      (u["id"], job_id, section, kind, message, A.now(), tg))
        n += 1
    if n: A.log(c, job_id, f"Notification ({kind}) to {n} recipient{'s' if n > 1 else ''}: {message[:120]}", kind="notify")
    return n


def customers_of(c, job_id):
    r = c.execute("SELECT org_id FROM jobs WHERE id=?", (job_id,)).fetchone()
    return users_with(c, "customer", r[0]) if r and r[0] else []


def on_uploaded(c, job_id, keys):
    """Test data uploaded: the testers are asked to verify it (never the one who uploaded it: the actor is skipped). The
    customer hears nothing until the final report is released."""
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    names = ", ".join(A.NAMES.get(k, k) for k in keys if k in A.NAMES and k != "request")
    if not names: return
    notify(c, users_with(c, "tester"), job_id, "uploaded", f"{series}: {names} uploaded and waiting for verification")


def on_section(c, job_id, key, state, reason=None):
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]; name = A.name(key)
    if state == "returned":
        up = c.execute("SELECT uploaded_by FROM sections WHERE job_id=? AND key=?", (job_id, key)).fetchone()
        if up and up[0]: notify(c, [up[0]], job_id, "returned", f"{series}: {name} returned for correction: {reason}", section=key)
    elif state in ("verified", "na"):
        plan = json.loads(c.execute("SELECT plan FROM jobs WHERE id=?", (job_id,)).fetchone()[0] or "[]")
        if not A.workflow.ready_for_signoff(c, job_id, A.ALL_NAMES, plan):
            notify(c, users_with(c, "admin"), job_id, "signoff", f"{series}: every test is verified; ready for approval")


def on_released(c, job_id, version):
    """The one notification a customer gets for a job: the final report released (once per released version)."""
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    testers = [r[0] for r in c.execute("SELECT DISTINCT uploaded_by FROM sections WHERE job_id=? AND uploaded_by IS NOT NULL", (job_id,))]
    amended = c.execute("SELECT 1 FROM reports WHERE job_id=? AND approver IS NOT NULL AND version<?", (job_id, version)).fetchone()
    notify(c, customers_of(c, job_id), job_id, "released", f"Test report {series} is ready" + (f" (corrected version {version})" if amended else "") +
           ". View and download it here.")
    notify(c, testers, job_id, "released", f"{series}: report version {version} signed off and released")


def on_ready_to_approve(c, job_id):
    series = c.execute("SELECT series FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    notify(c, users_with(c, "admin"), job_id, "approve", f"{series}: report generated and waiting for sign-off")


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
            lim = min(int(request.args["limit"]), 200) if str(request.args.get("limit", "")).isdigit() else 100
            rows = [dict(r) for r in c.execute("SELECT n.id, n.job_id, j.series, n.section_key, n.kind, n.message, n.created_at, n.read_at, "
                                               "n.target, COALESCE(n.count,1) AS count FROM notifications n LEFT JOIN jobs j ON j.id=n.job_id WHERE n.user_id=?"
                                               + (" AND n.read_at IS NULL" if only else "") + " ORDER BY n.created_at DESC, n.id DESC LIMIT ?", (u["id"], lim))]
            unread = c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (u["id"],)).fetchone()[0]
        for r in rows:  # needs action and the page it opens come from the server, not guessed from the text
            r["action"] = r["kind"] in ACTION
            r["target"] = r["target"] or target_of(r["job_id"], auth.is_customer(u))
        return jsonify(items=rows, unread=unread)

    @app.post("/api/notifications/read")
    @auth.require("notifications")
    def notifications_read():
        b = A.body(); u = auth.current(); ids = [int(x) for x in b.get("ids") or [] if str(x).isdigit()]
        with A.db() as c:
            if b.get("all"): c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (A.now(), u["id"]))
            elif ids: c.execute(f"UPDATE notifications SET read_at=? WHERE user_id=? AND id IN ({','.join('?' * len(ids))})", (A.now(), u["id"], *ids))
        return jsonify(ok=True)
