"""Accounts, login and permissions (docs/NEXT_STEPS.md section 2).

Roles: admin, tester, customer (the verifier and approver roles were removed). Testers enter data, run the checks and verify
tests, their own uploads included; the administrator approves a job once every test is verified, generates the
report and signs it off. Admin is never combined with tester, and customer is never combined with anything.

Every route must name its permission with @require(...) (or @public). A request to a route that names none is refused,
so a new route cannot ship unprotected; tests/test_auth.py walks every route to keep it that way.

Sessions are Flask's signed cookie (HttpOnly, SameSite=Lax). The key is generated on first run and kept in a file next to
the database, outside git. State-changing requests need the X-CSRF-Token header that /api/me hands out.
"""
import datetime as dt, os, re, secrets
from flask import Blueprint, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ("admin", "tester", "customer")
LEGACY = {"verifier": "tester", "approver": "admin"}  # roles of earlier versions, converted by migrate_roles()
STAFF = ("admin", "tester")
# permission -> roles holding it. Server-enforced; the page only hides what a role cannot use.
PERMS = {
    "jobs.view":        STAFF + ("customer",),  # customers are further limited to their organisation's jobs
    "job.create":       ("tester",),
    "request.receive":  ("tester", "admin"),     # open the inbox of customer requests, accept (capture) or return one
    "job.edit":         ("tester",),
    "job.delete":       ("admin",),             # only records that never had a released report
    "data.write":       ("tester",),            # import, enter / correct / remove sections, attach scans, AI reading
    "data.check":       ("tester",),           # run checks, mark flagged items reviewed
    "section.verify":   ("tester",),           # verify, return, reopen, not applicable: never a test the tester uploaded
    "job.signoff":      ("admin",),            # approve the job once every test is verified or not applicable
    "report.generate":  ("admin",),
    "report.approve":   ("admin",),            # sign off and release: an administrator who did not upload, check or verify the data
    "report.amend":     ("admin",),            # with a second administrator as second signer
    "report.view":      STAFF + ("customer",),  # customers: released or partial reports of their own jobs only
    "data.export":      STAFF,
    "sources.view":     STAFF,
    "register.import":  ("admin", "tester"),
    "stats":            STAFF,
    "users.manage":     ("admin",),
    "audit.read":       ("admin",),
    "settings.manage":  ("admin",),
    "templates.manage": ("admin",),
    "notifications":    STAFF + ("customer",),
    "job.assign":       ("admin", "tester"),     # admin assigns anyone; a test engineer only takes an unassigned test themselves
    "staff.view":       STAFF,                   # the list of testers, the "My work" queues
    "tickets.raise":    ("customer",),           # a customer raises a ticket and follows it up
    "tickets.manage":   ("admin",),              # tickets go to the administrators, who answer and close them
}
# Testing phase: no passwords anywhere (sign in with the username only, no re-entry at release or amendment). Set
# ALETHEIA_PASSWORDS=1 to switch every password rule back on.
PASSWORDS = os.environ.get("ALETHEIA_PASSWORDS", "0") == "1"
LOCK_AFTER, LOCK_MINUTES = 5, 15
IDLE_MINUTES, ABSOLUTE_HOURS = 30, 12
MIN_PASSWORD = 10
COMMON = {"password", "password1", "password123", "1234567890", "qwertyuiop", "aletheia123", "administrator", "letmein123",
          "welcome123", "cpri123456", "changeme123", "0123456789", "iloveyou12", "abcdefghij", "passw0rd12"}
EMP_RE = r"[A-Z0-9][A-Z0-9/-]{1,19}"
USER_RE = r"[a-z0-9][a-z0-9._-]{1,39}"
LOCAL = {"127.0.0.1", "::1", "localhost"}

bp = Blueprint("auth", __name__)
_db = None  # the app's db() context manager, set by setup()
_log = None  # the app's audit writer: log(c, job_id, event, kind=..., detail=...)
now = lambda: dt.datetime.now().isoformat(timespec="seconds")


def init_db(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS orgs(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, email TEXT, created_by INT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL, employee_id TEXT,
        roles TEXT NOT NULL, org_id INT REFERENCES orgs(id), email TEXT, test_types TEXT, password_hash TEXT NOT NULL,
        active INTEGER DEFAULT 1, must_change_password INTEGER DEFAULT 1, failed_attempts INTEGER DEFAULT 0, locked_until TEXT,
        session_epoch INTEGER DEFAULT 0, created_by INT, created_at TEXT, last_login TEXT);""")


def migrate_roles(c, log=None):
    """One-time conversion of the removed roles: a verifier becomes a tester, an approver an administrator. A user whose
    roles would then combine admin with tester cannot be converted (separation of duties): nothing is changed and the
    list of those users is returned, so the laboratory splits each into two accounts first. Returns [] when done."""
    rows = [r for r in c.execute("SELECT id, username, roles FROM users") if any(x in LEGACY for x in user_roles(r))]
    plan, clash = [], []
    for r in rows:
        new = sorted({LEGACY.get(x, x) for x in user_roles(r)})
        if "admin" in new and len(new) > 1: clash.append(f"{r['username']} ({r['roles']})")
        plan.append((r, new))
    if clash: return clash
    for r, new in plan:
        c.execute("UPDATE users SET roles=?, session_epoch=session_epoch+1 WHERE id=?", (",".join(new), r["id"]))
        if log: log(c, None, f"Role of {r['username']} converted: {r['roles']} -> {','.join(new)} (verifier and approver roles removed)", kind="admin")
    return []


def setup(app, db, log, key_folder):
    """Wire accounts into the app: secret key, cookie settings, the permission gate and the auth routes."""
    global _db, _log
    _db, _log = db, log
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_NAME="aletheia_session")
    app.secret_key = app.secret_key or secret_key(key_folder)
    app.before_request(gate)
    app.register_blueprint(bp)


def secret_key(folder):
    path = os.path.join(folder, ".aletheia_secret")
    try:
        with open(path, "rb") as f:
            k = f.read()
            if len(k) >= 32: return k
    except OSError: pass
    k = secrets.token_bytes(48)
    with open(path, "wb") as f: f.write(k)
    try: os.chmod(path, 0o600)
    except OSError: pass
    return k


# ------------------------------------------------------------------ route policy
def require(*perms):
    """The signed-in user must hold one of these permissions (see PERMS)."""
    for p in perms:
        if p not in PERMS: raise ValueError(f"unknown permission {p}")
    def deco(f):
        f._policy = ("perm", perms); return f
    return deco


def public(f):
    f._policy = ("public", ()); return f


def signed_in(f):
    """Any signed-in user, whatever the role (own account, notifications)."""
    f._policy = ("login", ()); return f


def policy_of(endpoint):
    if endpoint == "static": return ("public", ())
    view = current_app.view_functions.get(endpoint)
    return getattr(view, "_policy", None)


def holds(user, perm):
    return bool(user) and any(r in PERMS[perm] for r in user["roles"])


def user_roles(u): return [r for r in str(u["roles"] or "").split(",") if r]


def load_user(uid):
    with _db() as c: r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not r: return None
    u = dict(r); u["roles"] = user_roles(r); u.pop("password_hash", None); return u


def ip(): return request.remote_addr or "-"


def deny(status, msg, job_id=None, audit=True):
    if audit and status == 403:
        with _db() as c: _log(c, job_id, f"Permission denied: {request.method} {request.path} ({msg})", kind="denied")
    return jsonify(error=[msg]), status


def gate():
    """Runs before every request: resolve the session, then apply the route's policy."""
    g.user = None
    if request.endpoint is None: return None  # unknown URL: Flask answers 404 / 405
    pol = policy_of(request.endpoint)
    u = session_user()
    g.user = u
    if pol is None:
        return jsonify(error=["This action has no permission rule and is refused"]), 403
    kind, perms = pol
    if kind == "public":
        if request.method not in ("GET", "HEAD", "OPTIONS") and not request.is_json:
            return jsonify(error=["Send this request as JSON"]), 415  # forces a CORS preflight for cross-site attempts
        return None
    if not u: return jsonify(error=["Please sign in"], login=True), 401
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        tok = request.headers.get("X-CSRF-Token", "")
        if not tok or not secrets.compare_digest(tok, session.get("csrf", "")):
            return deny(403, "Missing or wrong security token; reload the page", audit=True)
    if PASSWORDS and u["must_change_password"] and request.endpoint not in ("auth.me", "auth.change_password", "auth.logout"):
        return jsonify(error=["Change your temporary password first"], change_password=True), 403
    if kind == "perm" and not any(holds(u, p) for p in perms):
        jid = (request.view_args or {}).get("i")
        return deny(403, f"Your role ({', '.join(u['roles'])}) does not allow this", job_id=jid)
    return None


def session_user():
    uid = session.get("uid")
    if not uid: return None
    t = dt.datetime.now()
    try:
        started, seen = dt.datetime.fromisoformat(session["started"]), dt.datetime.fromisoformat(session["seen"])
    except (KeyError, ValueError):
        session.clear(); return None
    if t - seen > dt.timedelta(minutes=IDLE_MINUTES) or t - started > dt.timedelta(hours=ABSOLUTE_HOURS):
        session.clear(); return None
    u = load_user(uid)
    if not u or not u["active"] or u["session_epoch"] != session.get("epoch"):
        session.clear(); return None
    session["seen"] = t.isoformat(timespec="seconds")
    return u


def current(): return getattr(g, "user", None)


def is_customer(u=None):
    u = u or current()
    return bool(u) and "customer" in u["roles"]


# ------------------------------------------------------------------ validation of account fields
def password_problem(pw, username=""):
    if not PASSWORDS: return None
    pw = str(pw or "")
    if len(pw) < MIN_PASSWORD: return f"Password must be at least {MIN_PASSWORD} characters"
    if len(pw) > 200: return "Password is too long"
    if pw.lower() in COMMON or len(set(pw)) < 4: return "This password is too easy to guess; choose another"
    if username and username.lower() in pw.lower(): return "Password must not contain the username"
    return None


def clean_roles(roles):
    roles = sorted({str(r).strip().lower() for r in (roles or []) if str(r).strip()})
    if not roles: return None, "Choose at least one role"
    bad = [r for r in roles if r not in ROLES]
    if bad: return None, f"Unknown role: {', '.join(bad)}"
    if "customer" in roles and len(roles) > 1: return None, "A customer account cannot hold a laboratory role"
    if "admin" in roles and len(roles) > 1:
        return None, "Admin cannot also be a tester (separation of duties); create a second account"
    return roles, None


def account_problems(b, creating):
    err = []
    if creating:
        un = str(b.get("username") or "").strip().lower()
        if not re.fullmatch(USER_RE, un): err.append("Username: 2-40 lower-case letters, digits, '.', '_' or '-'")
    if creating or "full_name" in b:
        if not str(b.get("full_name") or "").strip(): err.append("Full name is required")
    roles = None
    if creating or "roles" in b:
        roles, e = clean_roles(b.get("roles"))
        if e: err.append(e)
    staff = roles and "customer" not in roles
    if creating or "employee_id" in b or roles:
        emp = str(b.get("employee_id") or "").strip().upper()
        if staff and not emp: err.append("Employee ID is required for laboratory staff (it is printed on reports)")
        elif emp and not re.fullmatch(EMP_RE, emp): err.append("Employee ID must be 2-20 letters, digits, '-' or '/'")
    if roles and "customer" in roles and not b.get("org_id"): err.append("A customer account must belong to a customer organisation")
    em = str(b.get("email") or "").strip()
    if em and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em): err.append("Email address is not valid")
    return err, roles


def public_user(u):
    keys = ("id", "username", "full_name", "employee_id", "roles", "org_id", "email", "test_types", "active",
            "must_change_password", "locked_until", "created_at", "last_login")
    return {k: u.get(k) for k in keys}


# ------------------------------------------------------------------ routes
def body(): return request.get_json(force=True, silent=True) or {}


@bp.get("/api/me")
@public
def me():
    u = current()
    with _db() as c: setup_needed = c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    if not u: return jsonify(user=None, setup_needed=setup_needed, local=request.remote_addr in LOCAL, passwords=PASSWORDS, switch=switch_on())
    session.setdefault("csrf", secrets.token_urlsafe(24))
    perms = sorted(p for p in PERMS if holds(u, p))
    org = None
    if u.get("org_id"):
        with _db() as c: r = c.execute("SELECT name FROM orgs WHERE id=?", (u["org_id"],)).fetchone()
        org = r[0] if r else None
    return jsonify(user=dict(public_user(u), org=org), csrf=session["csrf"], perms=perms, setup_needed=False, names=current_app.config.get("TEST_NAMES"),
                   idle_minutes=IDLE_MINUTES, passwords=PASSWORDS, switch=switch_on(), features=dict(scan=bool(current_app.config.get("FEATURE_SCAN", os.environ.get("ALETHEIA_FEATURE_SCAN", "0") == "1"))))


@bp.post("/api/setup")
@public
def first_admin():
    """First run only: create the first Admin. Allowed from this computer only, and permanently closed afterwards."""
    if request.remote_addr not in LOCAL: return jsonify(error=["The first administrator can only be created on the server computer itself"]), 403
    b = body(); b["roles"] = ["admin"]
    err, roles = account_problems(b, creating=True)
    un = str(b.get("username") or "").strip().lower()
    pe = password_problem(b.get("password"), un)
    if pe: err.append(pe)
    if err: return jsonify(error=err), 400
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return jsonify(error=["Set-up is already done; sign in instead"]), 409
        cur = c.execute("INSERT INTO users(username,full_name,employee_id,roles,email,password_hash,must_change_password,created_at) "
                        "VALUES(?,?,?,?,?,?,0,?)", (un, b["full_name"].strip(), str(b.get("employee_id") or "").strip().upper() or None,
                                                     "admin", str(b.get("email") or "").strip() or None, pw_hash(b.get("password")), now()))
        uid = cur.lastrowid
        g.user = {"id": uid, "full_name": b["full_name"].strip(), "username": un, "roles": ["admin"]}
        _log(c, None, f"First administrator account created: {un}", kind="admin")
    start_session(load_user(uid))
    return jsonify(ok=True), 201


def start_session(u):
    session.clear()
    t = now()
    session.update(uid=u["id"], epoch=u["session_epoch"], started=t, seen=t, csrf=secrets.token_urlsafe(24))
    session.permanent = False


_DUMMY = generate_password_hash("not-a-real-password-x")


def pw_hash(pw):
    """Hash of the given password; without passwords (testing) an unusable random one."""
    return generate_password_hash(str(pw) if PASSWORDS or pw else secrets.token_urlsafe(24))


@bp.post("/api/login")
@public
def login():
    b = body(); un = str(b.get("username") or "").strip().lower(); pw = str(b.get("password") or "")
    with _db() as c: r = c.execute("SELECT * FROM users WHERE username=?", (un,)).fetchone()
    fail = jsonify(error=["Wrong username or password"]), 401
    if not r:
        check_password_hash(_DUMMY, pw)  # same work as a real check, so a wrong username is not faster
        with _db() as c: _log(c, None, f"Failed sign-in for unknown user '{un[:40]}' from {ip()}", kind="auth")
        return fail
    u = dict(r)
    if not u["active"]:
        with _db() as c: _log(c, None, f"Sign-in refused for disabled account {un} from {ip()}", kind="auth")
        return fail
    if u["locked_until"] and u["locked_until"] > now():
        with _db() as c: _log(c, None, f"Sign-in refused for locked account {un} from {ip()}", kind="auth")
        return jsonify(error=[f"Too many failed attempts. Try again after {u['locked_until'][11:16]}, or ask an administrator."]), 423
    if PASSWORDS and not check_password_hash(u["password_hash"], pw):
        n = u["failed_attempts"] + 1
        lock = (dt.datetime.now() + dt.timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds") if n >= LOCK_AFTER else None
        with _db() as c:
            c.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (0 if lock else n, lock, u["id"]))
            _log(c, None, f"Failed sign-in for {un} from {ip()}" + (f"; account locked for {LOCK_MINUTES} minutes" if lock else ""), kind="auth")
        return fail
    with _db() as c:
        c.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? WHERE id=?", (now(), u["id"]))
    lu = load_user(u["id"]); start_session(lu); g.user = lu
    with _db() as c: _log(c, None, f"Signed in from {ip()}", kind="auth")
    return jsonify(ok=True, must_change_password=PASSWORDS and bool(u["must_change_password"]))


def switch_on():
    """The Customer / Tester / Admin switch for showing each end of the system: only while there are no passwords (testing),
    and not when ALETHEIA_ROLE_SWITCH=0."""
    return not PASSWORDS and os.environ.get("ALETHEIA_ROLE_SWITCH", "1") != "0"


@bp.post("/api/switch")
@public
def switch_role():
    """Become the first active account holding the chosen role (customer, tester or admin), without signing in. The switch
    is recorded in the audit log like a sign-in; every permission still applies to the account switched to."""
    if not switch_on(): return jsonify(error=["Switching roles is turned off on this server; sign in instead"]), 403
    role = str(body().get("role") or "").strip().lower()
    if role not in ROLES: return jsonify(error=["Choose customer, tester or admin"]), 400
    with _db() as c:
        r = c.execute("SELECT id FROM users WHERE active=1 AND (',' || roles || ',') LIKE ? ORDER BY id LIMIT 1", (f"%,{role},%",)).fetchone()
    if not r: return jsonify(error=[f"There is no active {role} account to switch to; an administrator creates one under Users & customers"]), 404
    u = load_user(r["id"]); start_session(u); g.user = u
    with _db() as c:
        c.execute("UPDATE users SET last_login=? WHERE id=?", (now(), u["id"]))
        _log(c, None, f"Switched to the {role} view from {ip()} (no sign-in: testing phase)", kind="auth")
    return jsonify(ok=True, user=u["username"])


@bp.post("/api/logout")
@signed_in
def logout():
    with _db() as c: _log(c, None, "Signed out", kind="auth")
    session.clear(); return jsonify(ok=True)


@bp.post("/api/password")
@signed_in
def change_password():
    u = current(); b = body()
    with _db() as c: h = c.execute("SELECT password_hash FROM users WHERE id=?", (u["id"],)).fetchone()[0]
    if not check_password_hash(h, str(b.get("old") or "")): return jsonify(error=["Current password is wrong"]), 400
    new = str(b.get("new") or "")
    pe = password_problem(new, u["username"])
    if pe: return jsonify(error=[pe]), 400
    if check_password_hash(h, new): return jsonify(error=["Choose a password different from the current one"]), 400
    with _db() as c:
        c.execute("UPDATE users SET password_hash=?, must_change_password=0, session_epoch=session_epoch+1 WHERE id=?",
                  (generate_password_hash(new), u["id"]))
        _log(c, None, "Password changed", kind="auth")
    start_session(load_user(u["id"]))  # other sessions of this account end; this one continues
    return jsonify(ok=True)


def second_signer(username, password, role):
    """A different, active user holding `role`, present at this workstation and confirming with their own password
    (amendments need two signatures). Failures count towards that account's lock-out like a failed sign-in."""
    me_ = current(); un = str(username or "").strip().lower()
    with _db() as c: r = c.execute("SELECT * FROM users WHERE username=?", (un,)).fetchone()
    if not r or r["id"] == me_["id"] or not r["active"] or role not in user_roles(r):
        check_password_hash(_DUMMY, str(password or "")); return None, "The second signer must be another active " + {"admin": "administrator"}.get(role, role)
    if r["locked_until"] and r["locked_until"] > now(): return None, "The second signer's account is locked"
    if PASSWORDS and not check_password_hash(r["password_hash"], str(password or "")):
        n = r["failed_attempts"] + 1
        lock = (dt.datetime.now() + dt.timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds") if n >= LOCK_AFTER else None
        with _db() as c:
            c.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (0 if lock else n, lock, r["id"]))
            _log(c, None, f"Second-signer password wrong for {un} (from {ip()})", kind="auth")
        return None, "The second signer's password is wrong"
    with _db() as c: c.execute("UPDATE users SET failed_attempts=0 WHERE id=?", (r["id"],))
    return dict(r), None


def reauth(password):
    """True when the signed-in user's password matches (re-authentication at release)."""
    if not PASSWORDS: return True
    u = current()
    with _db() as c: h = c.execute("SELECT password_hash FROM users WHERE id=?", (u["id"],)).fetchone()[0]
    return check_password_hash(h, str(password or ""))


@bp.post("/api/customers")
@require("users.manage")
def create_customer():
    """A customer account from just a username (the display name defaults to it). Its organisation, which the customer's
    requests and jobs belong to, is created with the same name; no separate organisation step."""
    b = body(); un = str(b.get("username") or "").strip().lower()
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip() or un
    if not re.fullmatch(USER_RE, un): return jsonify(error=["Username: 2-40 lower-case letters, digits, '.', '_' or '-'"]), 400
    with _db() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone(): return jsonify(error=["That username is taken"]), 409
        org = c.execute("SELECT id FROM orgs WHERE lower(name)=lower(?)", (name,)).fetchone()
        oid = org[0] if org else c.execute("INSERT INTO orgs(name,created_by,created_at) VALUES(?,?,?)", (name, current()["id"], now())).lastrowid
        cur = c.execute("INSERT INTO users(username,full_name,roles,org_id,password_hash,must_change_password,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (un, name, "customer", oid, pw_hash(b.get("password")), int(PASSWORDS), current()["id"], now()))
        _log(c, None, f"Customer {un} created ({name})", kind="admin")
    return jsonify(id=cur.lastrowid, org_id=oid), 201


# ---- admin: users and customer organisations. Accounts are disabled, never deleted (history must resolve names for 10+ years).
@bp.get("/api/users")
@require("users.manage")
def users():
    with _db() as c:
        us = [dict(public_user(dict(r)), roles=user_roles(r)) for r in c.execute("SELECT * FROM users ORDER BY active DESC, username")]
    return jsonify(us)


def active_admins(c, without=None):
    return c.execute("SELECT COUNT(*) FROM users WHERE active=1 AND roles='admin' AND id IS NOT ?", (without,)).fetchone()[0]


@bp.post("/api/users")
@require("users.manage")
def create_user():
    b = body(); err, roles = account_problems(b, creating=True)
    un = str(b.get("username") or "").strip().lower()
    pe = password_problem(b.get("password"), un)
    if pe: err.append("Temporary password: " + pe)
    org = b.get("org_id") if roles and "customer" in roles else None
    with _db() as c:
        if org and not c.execute("SELECT 1 FROM orgs WHERE id=?", (org,)).fetchone(): err.append("Unknown customer organisation")
        if err: return jsonify(error=err), 400
        try:
            cur = c.execute("INSERT INTO users(username,full_name,employee_id,roles,org_id,email,test_types,password_hash,must_change_password,created_by,created_at) "
                            "VALUES(?,?,?,?,?,?,?,?,1,?,?)",
                            (un, b["full_name"].strip(), str(b.get("employee_id") or "").strip().upper() or None, ",".join(roles), org,
                             str(b.get("email") or "").strip() or None, clean_tests(b.get("test_types")),
                             pw_hash(b.get("password")), current()["id"], now()))
        except Exception as e:  # noqa: BLE001 - sqlite3.IntegrityError without importing sqlite3 here
            if "UNIQUE" in str(e): return jsonify(error=["That username is taken"]), 409
            raise
        _log(c, None, f"User {un} created with role(s) {', '.join(roles)}", kind="admin")
    return jsonify(id=cur.lastrowid), 201


def clean_tests(v):
    """Test types a tester is certified for; empty means any."""
    if not v: return None
    ks = [str(x).strip() for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()]
    return ",".join(sorted(set(ks))) or None


@bp.post("/api/users/<int:uid>")
@require("users.manage")
def update_user(uid):
    b = body()
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not r: return jsonify(error=["No such user"]), 404
        merged = dict(r); merged.update({k: v for k, v in b.items() if k in ("full_name", "employee_id", "roles", "org_id", "email")})
        if "roles" not in b: merged["roles"] = user_roles(r)
        err, roles = account_problems(merged, creating=False)
        if err: return jsonify(error=err), 400
        active = int(bool(b.get("active", r["active"])))
        if r["roles"] == "admin" and (roles != ["admin"] or not active) and not active_admins(c, without=uid):
            return jsonify(error=["At least one active administrator must remain"]), 409
        if uid == current()["id"] and not active: return jsonify(error=["You cannot disable your own account"]), 409
        org = merged.get("org_id") if "customer" in roles else None
        changes = []
        for k, new in (("full_name", str(merged["full_name"]).strip()), ("employee_id", str(merged.get("employee_id") or "").strip().upper() or None),
                       ("roles", ",".join(roles)), ("org_id", org), ("email", str(merged.get("email") or "").strip() or None),
                       ("active", active), ("test_types", clean_tests(b["test_types"]) if "test_types" in b else r["test_types"])):
            if new != r[k]: changes.append((k, r[k], new))
        if not changes: return jsonify(ok=True)
        c.execute("UPDATE users SET " + ",".join(f"{k}=?" for k, _, _ in changes) + (", session_epoch=session_epoch+1" if any(k in ("roles", "active") for k, _, _ in changes) else "")
                  + " WHERE id=?", (*[n for _, _, n in changes], uid))
        _log(c, None, f"User {r['username']} changed: " + "; ".join(f"{k} {o!r} -> {n!r}" for k, o, n in changes), kind="admin")
    return jsonify(ok=True)


@bp.post("/api/users/<int:uid>/reset-password")
@require("users.manage")
def reset_password(uid):
    b = body()
    with _db() as c:
        r = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        if not r: return jsonify(error=["No such user"]), 404
        pe = password_problem(b.get("password"), r[0])
        if pe: return jsonify(error=["Temporary password: " + pe]), 400
        c.execute("UPDATE users SET password_hash=?, must_change_password=1, failed_attempts=0, locked_until=NULL, session_epoch=session_epoch+1 WHERE id=?",
                  (generate_password_hash(b["password"]), uid))
        _log(c, None, f"Password of {r[0]} reset by administrator; their sessions ended", kind="admin")
    return jsonify(ok=True)


@bp.post("/api/users/<int:uid>/end-sessions")
@require("users.manage")
def end_sessions(uid):
    with _db() as c:
        r = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        if not r: return jsonify(error=["No such user"]), 404
        c.execute("UPDATE users SET session_epoch=session_epoch+1, locked_until=NULL, failed_attempts=0 WHERE id=?", (uid,))
        _log(c, None, f"All sessions of {r[0]} ended by administrator", kind="admin")
    return jsonify(ok=True)


@bp.get("/api/orgs")
@require("users.manage", "job.create")
def orgs():
    with _db() as c: return jsonify([dict(r) for r in c.execute("SELECT id,name,email FROM orgs ORDER BY name")])


@bp.post("/api/orgs")
@require("users.manage", "job.create")
def create_org():
    b = body(); name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()
    em = str(b.get("email") or "").strip()
    if not name: return jsonify(error=["Organisation name is required"]), 400
    if em and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em): return jsonify(error=["Email address is not valid"]), 400
    with _db() as c:
        old = c.execute("SELECT id FROM orgs WHERE lower(name)=lower(?)", (name,)).fetchone()
        if old: return jsonify(id=old[0], existing=True)
        cur = c.execute("INSERT INTO orgs(name,email,created_by,created_at) VALUES(?,?,?,?)", (name, em or None, current()["id"], now()))
        _log(c, None, f"Customer organisation created: {name}", kind="admin")
    return jsonify(id=cur.lastrowid), 201
