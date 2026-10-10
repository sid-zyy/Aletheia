"""Workflow rules (docs/NEXT_STEPS.md section 3): strict intake validation, test plans, section states and assignment.

Pure functions only (no Flask): app.py calls them from its routes and inside its transactions.

Section states: not_started (no row) -> uploaded -> verified (locked), with side exits returned (needs re-upload, with a
reason) and na (not applicable, with a reason). A verified section is locked until a tester reopens it with a reason.
"""
import datetime as dt, json, re

STATES = ("uploaded", "returned", "verified", "na")
MERGED = ("ids", "request", "other")  # built up by several people; no single owner

# ------------------------------------------------------------------ the customer request form (section 3.6)
# Customer Request Form, Format No. CPRI/QAF/01A (Issue 02). Sheets 1 and 2 are filled in by the customer (online, in the
# form's own order and wording); sheet 3 by the laboratory when the product is received. Only a customer raises a request.
FORM = dict(org="CENTRAL POWER RESEARCH INSTITUTE", unit="Name of the Unit / Division: SHORT CIRCUIT LABORATORY", format_no="CPRI/QAF/01A",
            issue="Issue No. 02", issue_date="Date of Issue: 22-06-2022", title="Customer Request Form")
DECISION_RULES = (
    "(i) Decision on compliance to standard/specification will be based on the requirement mentioned in the standard/specification "
    "and measurement uncertainty will be reported (if required) (informed to customer for agreement)",
    "(ii) For the requirement specified by the customer, same will be considered as decision criteria and measurement uncertainty "
    "will be reported (if required) (informed to customer for agreement)",
    "(iii) If Measurement Uncertainty is to be considered for the decision on compliance for border cases, calculated Measurement "
    "Uncertainty at confidence level of approximately 95% (k=2) will be reported and the decision rule for compliance, if MU is "
    "subtracted the decision is 'PASS' or MU is added the decision is 'FAIL' (informed to customer for agreement)")


def _f(key, label, kind="text", **kw): return dict(key=key, label=label, kind=kind, **kw)


ADDR, STORE, WIT = "Name and Address of the Customer", "Sample storage / Handling / Disposal", "Name of the witnessing persons"
REQUEST_FIELDS = (  # sheets 1 and 2, in the order of the printed form
    _f("customer", "Name of the Customer", group=ADDR, sheet=1), _f("address", "Address (street, area)", group=ADDR, sheet=1),
    _f("city", "City / town", group=ADDR, sheet=1), _f("state", "State / union territory", "state", group=ADDR, sheet=1),
    _f("pin", "PIN code", "pin", group=ADDR, sheet=1), _f("contact", "Contact person", group=ADDR, sheet=1),
    _f("phone", "Phone", "phone", group=ADDR, sheet=1), _f("email", "Email (for notifications)", "email", group=ADDR, sheet=1),
    _f("sample", "Sample(s) to be tested", sheet=1), _f("rating", "Rating of the sample(s) to be tested", "rating", sheet=1),
    _f("description", "Description of the test sample(s)", sheet=1, wide=True), _f("type", "Type", sheet=1),
    _f("serial", "Serial Number(s)", sheet=1), _f("manufacturer", "Manufacturer's Details", sheet=1, na_ok=True, wide=True),
    _f("drawings", "Drawing Number(s)", sheet=1, na_ok=True), _f("requirement", "Customers Requirement", sheet=1, optional=True, wide=True),
    _f("criteria", "Criteria for Evaluation (Standard/Specification)", sheet=1), _f("samples", "Number of Samples", "count", sheet=1),
    _f("take_back", "a) Taking back the sample after testing", "yesno", group=STORE, sheet=1),
    _f("scrap", "b) Will not take back the sample, CPRI can scrap and dispose it off", "yesno", group=STORE, sheet=1,
       note="If samples are not collected as in (a) within 15 days from the date of testing it will be automatically scrapped."),
    _f("tests", "Details of test(s) requested", sheet=1, wide=True),
    _f("mounting", "Specific instructions (if any) for mounting and connection", sheet=1, optional=True, wide=True),
    _f("witness", "Customers Representative", group=WIT, sheet=1, optional=True),
    _f("witness_other", "Other than Customer", group=WIT, sheet=1, optional=True),
    _f("dispatch", "Test Report to be despatched to", sheet=1), _f("dispatch_mode", "Test report Despatch mode", sheet=1, optional=True),
    _f("additional_reports", "Number of Additional Test Reports (Required / not required)", sheet=1, optional=True),
    _f("msme", "MSME Discount", "choice", options=["Applicable", "Not Applicable"], sheet=2,
       note="If applicable, the customer provides the necessary documents before testing. Billing to be done accordingly."),
    _f("conformity", "Whether statement of conformity is required in the test report", "yesno", sheet=2,
       note="a) If No, then only the observed results will be reported. b) If Yes, please select any one of (i) OR (ii) OR (iii)."),
    _f("decision_rule", "Decision rule (if Yes)", "choice", options=list(DECISION_RULES), when=("conformity", "Yes"), sheet=2,
       note="Deviations requested by the customer in the customer requirement shall be above the requirements of the standard/specification "
            "and wherever the requirements need to be specified by the customers or not specified in the standard/specification. Deviations "
            "requested by the customer shall not impact the integrity of the laboratory or the validity of the results. "
            "Decision criteria cannot be changed after the start of the test."),
    _f("declare_drawings", "I/We guarantee that the sample submitted for the test(s) has been manufactured in accordance with the drawings submitted.",
       "agree", sheet=2),
    _f("declare_terms", "I/We have read & understood the terms and condition for testing at CPRI and agree to the conditions stipulated there in.",
       "agree", sheet=2, note="CPRI Website will publish information on manufacturers' name, products tested, test report number & date of issue and "
                              "corresponding unique sample code number. The terms & Condition document is made available while making the offer "
                              "from CPRI for testing; it is also available on www.cpri.in."),
    _f("signed_name", "Customers Name (signature)", sheet=2, note="Dated automatically when the request is sent."),
)
DURING = "Filled during testing, if applicable"
LAB_FIELDS = (  # sheet 3: to be filled by the laboratory
    _f("condition", "Physical Condition of Sample on receipt", "choice", options=["Suitable for Testing", "Not suitable for Testing"]),
    _f("continue", "Communication to Customer for his concurrence on the Physical Condition of the sample (if not suitable)", "choice",
       options=["Continue Testing", "Not to continue Testing"], when=("condition", "Not suitable for Testing"), note="Deviation to be reported."),
    _f("capability", "Whether laboratory has capability to take up the work", "yesno"),
    _f("external", "Name and Address of the Externally Provided Product/Services", optional=True),
    _f("deviations", "Deviations/Discrepancies if any noticed during testing", optional=True, wide=True, group=DURING),
    _f("discrepancy_comm", "Communication to Customer for his approval of the Discrepancies (record of the discussion)", optional=True, wide=True,
       group=DURING),
)
LABEL = {f["key"]: f["label"] for f in REQUEST_FIELDS + LAB_FIELDS}
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


def _check(fields, b):
    """Every value of these fields present and well-formed (D4: nothing missing, nothing wrong). (errors, warnings, clean)."""
    errs, warns, clean = [], [], {}
    na = b.get("na") if isinstance(b.get("na"), dict) else {}
    for f in fields:
        k, label, kind = f["key"], f["label"], f["kind"]
        raw = b.get(k)
        if f.get("when") and str(clean.get(f["when"][0], "")) != f["when"][1]:
            clean[k] = ""; continue  # only asked when the earlier answer calls for it
        if kind == "agree":
            if raw is True or str(raw).strip().lower() in ("yes", "true", "on", "1", "agreed"): clean[k] = "Agreed"
            else: errs.append(f"Declaration not accepted: {label}")
            continue
        v = str(raw if raw is not None else "").strip()
        reason = str(na.get(k) or "").strip()
        if reason:
            if not f.get("na_ok"): errs.append(f"{label}: cannot be marked not applicable"); continue
            if len(reason) < 4: errs.append(f"{label}: give the reason it does not apply"); continue
            clean[k] = f"Not applicable: {reason}"; continue
        if v.lower() in EMPTYISH and not (kind == "choice" and any(o.lower() == v.lower() for o in f["options"])):  # "Not Applicable" is an answer here
            if f.get("optional"): clean[k] = ""; continue
            errs.append(f"{label}: required" + (" (or mark it not applicable, with a reason)" if f.get("na_ok") else "") +
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
            st = norm_state(v)
            if not st: errs.append(f"{label}: '{v}' is not an Indian state or union territory"); continue
            v = st
        elif kind == "rating":
            if not RATING_RE.match(v): errs.append(f"{label}: a number with its unit, like '250 kVA' (got '{v}')"); continue
        elif kind == "count":
            if not re.fullmatch(r"[1-9]\d{0,2}", v): errs.append(f"{label}: a whole number, 1 or more (got '{v}')"); continue
        elif kind == "yesno":
            if v.lower() not in ("yes", "no", "y", "n"): errs.append(f"{label}: answer yes or no"); continue
            v = "Yes" if v.lower() in ("yes", "y") else "No"
        elif kind == "choice":  # the option's text, or its number for the decision rules: "(i)", "(ii)", "(iii)"
            hit = next((o for o in f["options"] if o.lower() == v.lower() or (v.startswith("(") and o.startswith(v.split(")")[0] + ")"))), None)
            if not hit: errs.append(f"{label}: choose one of the options"); continue
            v = hit
        clean[k] = v
    return errs, warns, clean


def check_request(b):
    """The customer's request (sheets 1 and 2 of CPRI/QAF/01A). (errors, warnings, clean)."""
    errs, warns, clean = _check(REQUEST_FIELDS, b)
    if clean.get("take_back") and clean.get("scrap") and clean["take_back"] == clean["scrap"]:
        errs.append("Sample storage / Handling / Disposal: answer Yes to exactly one of (a) and (b)")
    if "pin" in clean and "state" in clean and clean["pin"][:2].isdigit():
        served = PIN_STATES.get(int(clean["pin"][:2]))
        if served is None: warns.append(f"PIN code {clean['pin']}: this prefix is not a known postal circle")
        elif clean["state"] not in served:
            warns.append(f"PIN code {clean['pin']} belongs to {' / '.join(served)}, but the state is {clean['state']}")
    return errs, warns, clean


def check_lab(b, now=None):
    """What the laboratory records on receipt (sheet 3), plus the arrival time. (errors, warnings, clean)."""
    errs, warns, clean = _check(LAB_FIELDS, b)
    if clean.get("continue") == "Not to continue Testing":
        errs.append("The customer did not agree to continue with the sample in this condition: the job cannot be accepted")
    if clean.get("capability") == "No":
        errs.append("The laboratory has no capability to take up the work: the request cannot be accepted")
    if "external" in clean and not clean["external"]: clean["external"] = "Nil"
    t = now or dt.datetime.now()
    arr = str(b.get("arrived_at") or "").strip()  # recorded as the moment of intake unless given
    try:
        a = dt.datetime.fromisoformat(arr) if arr else t
        if a > t + dt.timedelta(minutes=5): errs.append("Arrival time: cannot be in the future")
        elif a < t - dt.timedelta(days=60): warns.append(f"Arrival time {arr[:16]} is more than 60 days ago")
        clean["arrived_at"] = a.isoformat(timespec="minutes")
    except ValueError:
        errs.append("Arrival time: not a date and time")
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
    """What still stands between this job and the administrator's approval (empty list = ready). names: every display name,
    including the sample identification record and supplementary records."""
    out = []
    rows = list(c.execute("SELECT key, state FROM sections WHERE job_id=? AND key!='request'", (jid,)))
    for r in rows:
        if r["state"] not in ("verified", "na"):
            out.append(f"{names.get(r['key'], r['key'])}: {r['state'].replace('_', ' ')}")
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
