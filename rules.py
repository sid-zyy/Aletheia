"""Thresholds used by validate() in app.py, in one place, each with its basis and how far it has been checked.

Status values (nothing here is "confirmed by the lab"; no lab engineer has reviewed these):
  secondary    matches a published specification or summary of IS 1180 / IS 2026 that was read, but NOT the
               standard's own text (e.g. a utility tender specification or a BIS summary leaflet).
  unconfirmed  implemented from general practice or memory; no source has been checked.
Update `status` and `source` only after reading the clause in the standard itself.
"""

SECONDARY, UNCONFIRMED = "secondary", "unconfirmed"

RULES = {
    "resistance_imbalance_pct": dict(
        value=2.0, unit="%", status=UNCONFIRMED, source="General practice; not known to be a clause of IS 1180 / IS 2026.",
        note="Phase-to-phase spread of winding resistance readings."),
    "nll_pct_to_200kva": dict(
        value=3.0, unit="% of rated current", status=SECONDARY,
        source="BIS summary of IS 1180 and CEA DT specification (May 2026): no-load current up to 200 kVA not above 3%.",
        note="Applies at rated voltage."),
    "nll_pct_above_200kva": dict(
        value=2.0, unit="% of rated current", status=SECONDARY,
        source="CEA DT specification (May 2026): above 200 kVA and up to 2500 kVA not above 2%.",
        note="Applies at rated voltage."),
    "nll_112_pct_to_200kva": dict(
        value=6.0, unit="% of rated current", status=SECONDARY,
        source="BIS summary of IS 1180: no-load current at 112.5% voltage not above 6% (up to 200 kVA). Wording was ambiguous.",
        note=""),
    "nll_112_pct_above_200kva": dict(
        value=5.0, unit="% of rated current", status=UNCONFIRMED, source="Carried over from the first prototype; no source found.",
        note="Check the 112.5% limit for ratings above 200 kVA."),
    "loss_positive_tolerance_pct": dict(
        value=0.0, unit="%", status=SECONDARY,
        source="CEA DT specification (May 2026): no positive tolerance on no-load or load losses.",
        note="Measured loss must not exceed the guaranteed value in the proforma."),
    "impedance_tolerance_pct": dict(
        value=10.0, unit="% of declared impedance", status=SECONDARY,
        source="Older IS 1180 text (1966) states 4.5% impedance with +/-10% tolerance; IS 2026 Part 1 not read.",
        note="Applied to every tap, which may be stricter than the standard (tolerance is usually stated at the principal tap)."),
    "ratio_tolerance_pct": dict(
        value=0.5, unit="% of declared ratio", status=SECONDARY,
        source="Older IS 1180 text (1966): 0.5% or 10% of the actual impedance, whichever is smaller. IS 2026 Part 1 not read.",
        note="Effective tolerance = min(0.5%, 10% of impedance %). For 4.5% impedance this is 0.45%."),
    "ratio_impedance_fraction": dict(
        value=0.10, unit="fraction of impedance %", status=SECONDARY, source="Same as ratio_tolerance_pct.", note=""),
    "reactance_change_pct": dict(
        value=2.0, unit="%", status=UNCONFIRMED,
        source="IS 2026 Part 5 / IEC 60076-5; the allowed change is believed to depend on transformer category and winding type. Not checked.",
        note="Flat limit used for every rating; may be wrong for some transformers."),
    "sc_rms_tolerance_pct": dict(
        value=10.0, unit="% of required current", status=UNCONFIRMED,
        source="IS 2026 Part 5 / IEC 60076-5 tolerance on applied current. Not checked.", note=""),
    "sc_thermal_min_s": dict(
        value=2.0, unit="s", status=UNCONFIRMED, source="IS 2026 Part 5 thermal ability duration (believed to be 2 s). Not checked.", note=""),
    "steady_state_k_per_h": dict(
        value=1.0, unit="K per hour", status=UNCONFIRMED,
        source="IS 2026 Part 2 / IEC 60076-2 top-oil steady state. Believed to be 1 K/h over 3 consecutive hours; not checked.",
        note="Prototype checks the last 4 hourly changes, which is stricter than 3."),
    "temp_margin_inconclusive_k": dict(
        value=1.0, unit="K", status=UNCONFIRMED,
        source="Prototype choice standing in for measurement uncertainty. Replace with the lab's own uncertainty budget.", note=""),
    "oil_limit_k / wdg_limit_k": dict(
        value=None, unit="K", status=SECONDARY,
        source="Read from the proforma per job. IS 1180 gives several limit sets depending on ambient and efficiency level "
               "(e.g. 35/40 K over 50 C ambient in CEA 2026), so these are deliberately not hardcoded.", note=""),
}


def val(key):
    return RULES[key]["value"]


def nll_limits(kva):
    """(limit at rated voltage %, limit at 112.5% voltage %) for a given rating."""
    if kva <= 200:
        return val("nll_pct_to_200kva"), val("nll_112_pct_to_200kva")
    return val("nll_pct_above_200kva"), val("nll_112_pct_above_200kva")


def ratio_tolerance(z_pct):
    """Voltage ratio tolerance in %: the smaller of 0.5% and 10% of the impedance percentage."""
    return min(val("ratio_tolerance_pct"), val("ratio_impedance_fraction") * z_pct)


def basis(*keys):
    """Short text for a finding: where the threshold comes from and whether it has been confirmed."""
    parts = []
    for k in keys:
        r = RULES[k]
        parts.append(f"{r['status']}: {r['source']}")
    return " | ".join(parts)


# Wording of recorded observations. Verdicts must not depend on the single word "no" appearing somewhere.
import re

_NEG = re.compile(r"\b(?:no|without|nil)\s+(?:visible\s+|any\s+|signs?\s+of\s+)?"
                  r"(?:disruptive\s+)?(?:discharge|flashover|breakdown|abnormalit\w*|damage|deformation|displacement|"
                  r"leak\w*|seepage|oozing|crack\w*|sweating)\b", re.I)
_BAD = re.compile(r"disruptive|flashover|breakdown|punctur|abnormal|damag|deform|displac|crack|leak|seep|ooz|sweat|loose|burn|discolou?r|fail", re.I)
_OK_WORDS = re.compile(r"\b(?:withstood|within limits|normal|intact|satisfactory)\b", re.I)


def classify_observation(text):
    """True = recorded as satisfactory, False = a problem is recorded, None = wording not understood (needs a person).
    'No disruptive discharge' -> True; 'Disruptive discharge at 28 kV' -> False; 'not ok' or '' -> None."""
    s = (text or "").strip()
    if not s:
        return None
    had_negated = bool(_NEG.search(s))
    rest = _NEG.sub(" ", s)
    if re.search(r"\bnot\b", rest, re.I) and not had_negated:
        return None
    if _BAD.search(rest):
        return False
    if had_negated or _OK_WORDS.search(s):
        return True
    return None
