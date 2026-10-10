"""Customer tickets: a customer raises a ticket (a question or a problem, optionally about one of their jobs); it goes to the
laboratory's administrators, who answer in the same thread and close it.

* A customer sees only their organisation's tickets; staff replies are signed "CPRI Short Circuit Laboratory" (customers
  never see staff names).
* Status: open (waiting for the laboratory) -> answered (waiting for the customer) -> closed. A customer's reply re-opens it.
* Every ticket, message and status change is audited (kind "ticket") and notifies the other side.
"""
from flask import jsonify, request, abort
import auth

A = None
CATEGORIES = ("Test request", "Test report", "Partial report or approved values", "Sample handling or despatch", "Account or sign-in", "Other")
LAB = "CPRI Short Circuit Laboratory"


def init_db(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, org_id INT NOT NULL, user_id INT NOT NULL, job_id INT, category TEXT NOT NULL,
        subject TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT, closed_by INT);
    CREATE TABLE IF NOT EXISTS ticket_messages(id INTEGER PRIMARY KEY, ticket_id INT NOT NULL, user_id INT NOT NULL, from_lab INT NOT NULL DEFAULT 0,
        body TEXT NOT NULL, at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_tickets_org ON tickets(org_id, status);
    CREATE INDEX IF NOT EXISTS ix_ticket_msgs ON ticket_messages(ticket_id);""")
    for name, body in (("ticket_messages_no_update", "BEFORE UPDATE ON ticket_messages BEGIN SELECT RAISE(ABORT, 'a ticket message cannot be changed'); END"),
                       ("ticket_messages_no_delete", "BEFORE DELETE ON ticket_messages BEGIN SELECT RAISE(ABORT, 'a ticket message cannot be removed'); END")):
        c.execute(f"DROP TRIGGER IF EXISTS {name}"); c.execute(f"CREATE TRIGGER {name} {body}")


def text(v, n): return " ".join(str(v or "").split())[:n] if n < 500 else str(v or "").strip()[:n]


def visible(c, tid):
    """The ticket, if the signed-in user may see it (a customer: their organisation's only; 404 otherwise, ids reveal nothing)."""
    t = c.execute("SELECT t.*, o.name AS org, j.series FROM tickets t LEFT JOIN orgs o ON o.id=t.org_id LEFT JOIN jobs j ON j.id=t.job_id WHERE t.id=?", (tid,)).fetchone()
    if not t or (auth.is_customer() and t["org_id"] != auth.current()["org_id"]): abort(404)
    return t


def thread(c, t):
    cust = auth.is_customer()
    msgs = [dict(id=m["id"], body=m["body"], at=m["at"], from_lab=bool(m["from_lab"]),
                 author=LAB if m["from_lab"] and cust else m["name"]) for m in
            c.execute("SELECT m.*, u.full_name AS name FROM ticket_messages m LEFT JOIN users u ON u.id=m.user_id WHERE m.ticket_id=? ORDER BY m.id", (t["id"],))]
    out = {k: t[k] for k in ("id", "category", "subject", "status", "created_at", "updated_at", "closed_at", "job_id", "series", "org")}
    return dict(out, messages=msgs)


def install(app_module):
    global A
    A = app_module; app = A.app
    with A.db() as c: init_db(c)

    def customers_of(c, org): return A.notify.users_with(c, "customer", org)
    def admins(c): return A.notify.users_with(c, "admin")

    @app.get("/api/tickets")
    @auth.require("tickets.raise", "tickets.manage")
    def tickets_list():
        """A customer's tickets, or (administrators) every ticket; ?status=open|answered|closed."""
        st = request.args.get("status"); q, a = [], []
        if auth.is_customer(): q.append("t.org_id=?"); a.append(auth.current()["org_id"])
        if st in ("open", "answered", "closed"): q.append("t.status=?"); a.append(st)
        with A.db() as c:
            rows = c.execute("SELECT t.id, t.category, t.subject, t.status, t.created_at, t.updated_at, t.job_id, j.series, o.name AS org, "
                             "(SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id=t.id) AS messages FROM tickets t "
                             "LEFT JOIN jobs j ON j.id=t.job_id LEFT JOIN orgs o ON o.id=t.org_id" + (" WHERE " + " AND ".join(q) if q else "") +
                             " ORDER BY (t.status='open') DESC, (t.status='answered') DESC, t.updated_at DESC LIMIT 300", a).fetchall()
        return jsonify(tickets=[dict(r) for r in rows], categories=CATEGORIES)

    @app.post("/api/tickets")
    @auth.require("tickets.raise")
    def ticket_raise():
        """A customer raises a ticket; the administrators are notified."""
        b = A.body(); u = auth.current(); err = []
        cat, subj, msg = text(b.get("category"), 80), text(b.get("subject"), 150), text(b.get("message"), 5000)
        if cat not in CATEGORIES: err.append("Choose what the ticket is about")
        if len(subj) < 4: err.append("Subject: say in a few words what it is about")
        if len(msg) < 10: err.append("Message: describe the question or problem (at least 10 characters)")
        jid = b.get("job_id") or None
        with A.db() as c:
            if jid is not None and not (isinstance(jid, int) and c.execute("SELECT 1 FROM jobs WHERE id=? AND org_id=?", (jid, u["org_id"])).fetchone()):
                err.append("That job is not one of your organisation's")
            if err: return jsonify(error=err), 400
            now = A.now()
            tid = c.execute("INSERT INTO tickets(org_id,user_id,job_id,category,subject,status,created_at,updated_at) VALUES(?,?,?,?,?,'open',?,?)",
                            (u["org_id"], u["id"], jid, cat, subj, now, now)).lastrowid
            c.execute("INSERT INTO ticket_messages(ticket_id,user_id,from_lab,body,at) VALUES(?,?,0,?,?)", (tid, u["id"], msg, now))
            A.log(c, jid, f"Ticket {tid} raised by the customer ({cat}): {subj}", kind="ticket")
            A.notify.notify(c, admins(c), jid, "ticket", f"New customer ticket {tid} ({cat}): {subj}")
        return jsonify(id=tid), 201

    @app.get("/api/tickets/<int:tid>")
    @auth.require("tickets.raise", "tickets.manage")
    def ticket_get(tid):
        with A.db() as c: return jsonify(thread(c, visible(c, tid)))

    @app.post("/api/tickets/<int:tid>/messages")
    @auth.require("tickets.raise", "tickets.manage")
    def ticket_reply(tid):
        """Reply in the thread. The laboratory's answer marks it answered; the customer's reply (re)opens it."""
        msg = text(A.body().get("message"), 5000)
        if len(msg) < 2: return jsonify(error=["Write a message"]), 400
        lab = not auth.is_customer()
        with A.db() as c:
            t = visible(c, tid); now = A.now()
            c.execute("INSERT INTO ticket_messages(ticket_id,user_id,from_lab,body,at) VALUES(?,?,?,?,?)", (tid, auth.current()["id"], int(lab), msg, now))
            c.execute("UPDATE tickets SET status=?, updated_at=?, closed_at=NULL, closed_by=NULL WHERE id=?", ("answered" if lab else "open", now, tid))
            A.log(c, t["job_id"], f"Ticket {tid}: {'answered by the laboratory' if lab else 'customer replied'}", kind="ticket")
            if lab: A.notify.notify(c, customers_of(c, t["org_id"]), t["job_id"], "ticket", f"The laboratory answered your ticket {tid}: {t['subject']}")
            else: A.notify.notify(c, admins(c), t["job_id"], "ticket", f"Customer replied on ticket {tid}: {t['subject']}")
        return jsonify(ok=True)

    @app.post("/api/tickets/<int:tid>/close")
    @auth.require("tickets.raise", "tickets.manage")
    def ticket_close(tid):
        with A.db() as c:
            t = visible(c, tid)
            if t["status"] == "closed": return jsonify(error=["This ticket is already closed"]), 409
            c.execute("UPDATE tickets SET status='closed', closed_at=?, closed_by=?, updated_at=? WHERE id=?", (A.now(), auth.current()["id"], A.now(), tid))
            A.log(c, t["job_id"], f"Ticket {tid} closed", kind="ticket")
            if auth.is_customer(): A.notify.notify(c, admins(c), t["job_id"], "ticket", f"Customer closed ticket {tid}: {t['subject']}")
            else: A.notify.notify(c, customers_of(c, t["org_id"]), t["job_id"], "ticket", f"Your ticket {tid} was closed: {t['subject']}")
        return jsonify(ok=True)

    @app.post("/api/tickets/<int:tid>/reopen")
    @auth.require("tickets.raise", "tickets.manage")
    def ticket_reopen(tid):
        with A.db() as c:
            t = visible(c, tid)
            if t["status"] != "closed": return jsonify(error=["This ticket is not closed"]), 409
            c.execute("UPDATE tickets SET status='open', closed_at=NULL, closed_by=NULL, updated_at=? WHERE id=?", (A.now(), tid))
            A.log(c, t["job_id"], f"Ticket {tid} re-opened", kind="ticket")
        return jsonify(ok=True)
