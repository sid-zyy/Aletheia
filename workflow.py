"""Workflow rules (docs/NEXT_STEPS.md section 3): strict intake validation, test plans, section states and assignment.

Pure functions only (no Flask): app.py calls them from its routes and inside its transactions.

Section states: not_started (no row) -> uploaded -> verified (locked), with side exits returned (needs re-upload, with a
reason) and na (not applicable, with a reason). A verified section is locked until a verifier reopens it with a reason.
"""
import datetime as dt, json, re

STATES = ("uploaded", "returned", "verified", "na")
MERGED = ("ids", "request", "other")  # built up by several people; no single owner

# ------------------------------------------------------------------ intake (section 3.6)
# The exact list of mandatory fields on the lab's request form is still open (Q14): adjust here.
# (key, label, kind, may be "not applicable" with a reason)
INTAKE_FIELDS = (
    ("customer", "Customer name", "text", False),
    ("address", "Address (street, area)", "text", False),
    ("city", "City / town", "text", False),
    ("state", "State / union territory", "state", False),
    ("pin", "PIN code", "pin", False),
    ("contact", "Contact person", "text", False),
    ("phone", "Phone", "phone", False),
    ("email", "Email (for notifications)", "email", False),
    ("sample", "Product description", "text", False),
    ("rating", "Rating", "rating", False),
    ("serial", "Serial number", "text", False),
    ("manufacturer", "Manufacturer", "text", True),
    ("drawings", "Drawing numbers", "text", True),
    ("tests", "Tests requested", "text", False),
    ("criteria", "Reference standard", "text", False),
    ("witness", "Witness present (yes / no)", "yesno", False),
    ("witness_name", "Witness name and organisation", "text", True),
    ("conformity", "Statement of conformity / decision rule", "text", False),
)
LABEL = {k: l for k, l, _, _ in INTAKE_FIELDS}
EMPTYISH = {"", "na", "n/a", "n.a.", "nil", "none", "-", "--", "not applicable", "nan", "null", "tbd", "?"}
STATES_UT = ("Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
             "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
             "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
             "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
             "Ladakh", "Lakshadweep", "Puducherry")
# First two digits of a PIN code -> states / UTs served (India Post postal circles). Approximate by design: a mismatch is
# flagged for the receiving engineer to confirm, never silently corrected. Shipped offline, no internet needed.
_P = {11: "Delhi", 12: "Haryana", 13: "Haryana|Punjab", 14: "Punjab", 15: "Punjab", 16: "Punjab|Chandigarh|Haryana", 17: "Himachal Pradesh",
      18: "Jammu and Kashmir", 19: "Jammu and Kashmir|Ladakh", 20: "Uttar Pradesh", 21: "Uttar Pradesh", 22: "Uttar Pradesh",
      23: "Uttar Pradesh", 24: "Uttar Pradesh|Uttarakhand", 25: "Uttar Pradesh", 26: "Uttar Pradesh|Uttarakhand", 27: "Uttar Pradesh",
      28: "Uttar Pradesh", 30: "Rajasthan", 31: "Rajasthan", 32: "Rajasthan", 33: "Rajasthan", 34: "Rajasthan", 36: "Gujarat",
      37: "Gujarat", 38: "Gujarat", 39: "Gujarat|Dadra and Nagar Haveli and Daman and Diu", 40: "Maharashtra|Goa", 41: "Maharashtra",
      42: "Maharashtra", 43: "Maharashtra", 44: "Maharashtra", 45: "Madhya Pradesh", 46: "Madhya Pradesh", 47: "Madhya Pradesh",
      48: "Madhya Pradesh", 49: "Chhattisgarh", 50: "Telangana|Andhra Pradesh", 51: "Andhra Pradesh|Telangana", 52: "Andhra Pradesh",
      53: "Andhra Pradesh", 56: "Karnataka", 57: "Karnataka", 58: "Karnataka", 59: "Karnataka", 60: "Tamil Nadu|Puducherry",
      61: "Tamil Nadu", 62: "Tamil Nadu", 63: "Tamil Nadu", 64: "Tamil Nadu", 67: "Kerala", 68: "Kerala|Lakshadweep", 69: "Kerala",
      70: "West Bengal", 71: "West Bengal", 72: "West Bengal", 73: "West Bengal|Sikkim", 74: "West Bengal|Andaman and Nicobar Islands",
      75: "Odisha", 76: "Odisha", 77: "Odisha", 78: "Assam", 79: "Arunachal Pradesh|Nagaland|Manipur|Mizoram|Meghalaya|Tripura|Assam",
      80: "Bihar", 81: "Bihar|Jharkhand", 82: "Bihar|Jharkhand", 83: "Jharkhand", 84: "Bihar", 85: "Bihar"}
PIN_STATES = {k: tuple(v.split("|")) for k, v in _P.items()}
RATING_RE = re.compile(r"^\s*\d+(\.\d+)?\s*(kva|mva|va|kv|v|a|ka|kw|mw)\b", re.I)


def norm_state(s):
    t = re.sub(r"[^a-z]", "", str(s or "").lower().replace("&", "and"))
    return next((x for x in STATES_UT if re.sub(r"[^a-z]", "", x.lower()) == t), None)


def check_intake(b, now=None, lab=True):
    """Every required intake value present and well-formed (D4: nothing missing, nothing wrong).
    Returns (errors, warnings, clean). Warnings must be confirmed (confirm_warnings) before a job is created.
    lab=False: the customer's own request, without what only the laboratory records (arrival, who opened the box)."""
    errs, warns, clean = [], [], {}
    na = b.get("na") if isinstance(b.get("na"), dict) else {}
    witness_yes = str(b.get("witness") or "").strip().lower() in ("yes", "y", "true")
    for k, label, kind, na_ok in INTAKE_FIELDS:
        v = str(b.get(k) if b.get(k) is not None else "").strip()
        reason = str(na.get(k) or "").strip()
        if k == "witness_name" and not witness_yes:
            clean[k] = "Not applicable: no witness"; continue
        if reason:
            if not na_ok: errs.append(f"{label}: cannot be marked not applicable"); continue
            if len(reason) < 4: errs.append(f"{label}: give the reason it does not apply"); continue
            clean[k] = f"Not applicable: {reason}"; continue
        if v.lower() in EMPTYISH:
            errs.append(f"{label}: required" + (" (or mark it not applicable, with a reason)" if na_ok else "") +
                        (f" - '{v}' is not accepted" if v else "")); continue
        if kind == "pin":
            v = v.replace(" ", "")
            if not re.fullmatch(r"[1-9]\d{5}", v): errs.append(f"{label}: must be 6 digits, not starting with 0 (got '{v}')"); continue
        elif kind == "phone":
            digits = re.sub(r"[\s()-]", "", v)
            if not re.fullmatch(r"(\+\d{1,3})?\d{10,12}", digits): errs.append(f"{label}: 10-12 digits, optionally with +country code (got '{v}')"); continue
            v = digits
        elif kind == "email":
            if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}", v): errs.append(f"{label}: not a valid address (got '{v}')"); continue
        elif kind == "state":
            s = norm_state(v)
            if not s: errs.append(f"{label}: '{v}' is not an Indian state or union territory"); continue
            v = s
        elif kind == "rating":
            if not RATING_RE.match(v): errs.append(f"{label}: a number with its unit, like '250 kVA' (got '{v}')"); continue
        elif kind == "yesno":
            if v.lower() not in ("yes", "no", "y", "n"): errs.append(f"{label}: answer yes or no"); continue
            v = "Yes" if v.lower() in ("yes", "y") else "No"
        clean[k] = v
    if "pin" in clean and "state" in clean and clean["pin"][:2].isdigit():
        served = PIN_STATES.get(int(clean["pin"][:2]))
        if served is None: warns.append(f"PIN code {clean['pin']}: this prefix is not a known postal circle")
        elif clean["state"] not in served:
            warns.append(f"PIN code {clean['pin']} belongs to {' / '.join(served)}, but the state is {clean['state']}")
    if not lab: return errs, warns, clean
    t = now or dt.datetime.now()
    arr = str(b.get("arrived_at") or "").strip()
    try:
        a = dt.datetime.fromisoformat(arr)
        if a > t + dt.timedelta(minutes=5): errs.append("Arrival time: cannot be in the future")
        elif a < t - dt.timedelta(days=60): warns.append(f"Arrival time {arr[:16]} is more than 60 days ago")
        clean["arrived_at"] = a.isoformat(timespec="minutes")
    except ValueError:
        errs.append("Arrival time: required, as date and time")
    opened = str(b.get("opened_by") or "").strip()
    if opened.lower() in EMPTYISH: errs.append("Box opened by: required (name of the person who opened the packing)")
    else: clean["opened_by"] = opened
    return errs, warns, clean


def check_plan(plan, names):
    """The tests this job needs (section keys). At least one; only known tests."""
    if not isinstance(plan, list) or not plan: return None, ["Test plan: choose at least one test"]
    bad = [p for p in plan if p not in names or p == "request"]
    if bad: return None, [f"Test plan: unknown test {', '.join(map(str, bad))}"]
    return [k for k in names if k in plan], []


# ------------------------------------------------------------------ sections
def owner(c, jid, key):
    """Who may upload or correct this section: the assigned tester, else the first uploader. None = anyone with the permission."""
    a = c.execute("SELECT user_id FROM assignments WHERE job_id=? AND key=?", (jid, key)).fetchone()
    if a: return a[0]
    r = c.execute("SELECT uploaded_by FROM sections WHERE job_id=? AND key=?", (jid, key)).fetchone()
    return r[0] if r and key not in MERGED else None


def may_write(c, jid, key, user):
    """None if the user may write this section, else the reason they may not."""
    if key in MERGED: return None
    tt = [x for x in str(user.get("test_types") or "").split(",") if x]
    if tt and key not in tt: return f"your account is certified for {', '.join(tt)} only"
    o = owner(c, jid, key)
    if o is not None and o != user["id"]:
        n = c.execute("SELECT full_name FROM users WHERE id=?", (o,)).fetchone()
        return f"this test belongs to {n[0] if n else 'another tester'}; an administrator can reassign it"
    return None


def progress(c, jid, names, plan=None):
    """Per-test state for the job's plan (or every test when no plan was chosen), plus counts."""
    rows = {r["key"]: r for r in c.execute("SELECT key, state FROM sections WHERE job_id=?", (jid,))}
    keys = plan or [k for k in names if k != "request"]
    items = [dict(key=k, name=names.get(k, k), state=rows[k]["state"] if k in rows else "not_started") for k in keys]
    counts = {s: sum(i["state"] == s for i in items) for s in ("not_started",) + STATES}
    return items, counts


def ready_for_signoff(c, jid, names, plan):
    """What still stands between this job and the verifier's whole-job sign-off (empty list = ready)."""
    out = []
    rows = list(c.execute("SELECT key, state FROM sections WHERE job_id=? AND key!='request'", (jid,)))
    for r in rows:
        if r["state"] not in ("verified", "na"):
            out.append(f"{names.get(r['key'], 'Identifiers on each sheet' if r['key'] == 'ids' else 'Additional log sheets' if r['key'] == 'other' else r['key'])}: {r['state'].replace('_', ' ')}")
    have = {r["key"] for r in rows}
    for k in plan or []:
        if k not in have: out.append(f"{names.get(k, k)}: not uploaded (upload it, or mark it not applicable)")
    if not rows and not plan: out.append("No test data uploaded")
    return out


def intake_complete(j):
    """Released reports need a complete, checked intake: required fields valid and read back against the original form."""
    it = j.get("intake") or {}
    if not it.get("valid"): return ["Intake details are incomplete or not in the required format"]
    if not it.get("checked_by"): return ["The intake has not been checked against the customer's original form"]
    return []


def loads(s, default):
    try: return json.loads(s) if s else default
    except ValueError: return default
