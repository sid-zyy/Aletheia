"""The test report, laid out as the laboratory's "Transformer Test report format" (11 sheets for a full job).

Sheets: 1 cover, 2 description of the sample, 3 summary of tests conducted (clauses and sheet numbers), 4 list of drawings,
5-10 test results (routine, special, type), last sheet the notes, accreditation, verification QR and traceability annex.
Every page carries the CPRI header, the report number and date, the ULR / laboratory footer with "Sheet n of N" and the
test engineer's signature line. Sheet numbers are learnt by laying the report out twice.

Values are printed as logged (F5). A value Aletheia had to work out for the format (the no-load current as a percentage of
rated current, the tapping percentages) uses the same arithmetic as the checks in validate(). Wording, clause numbers, notes
and laboratory details come from report_template.json; keys left out fall back to DEFAULTS below.
"""
import io, json, os, re
from contextlib import contextmanager
from xml.sax.saxutils import escape as xesc
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO, ACCREDITATION = os.path.join(HERE, "static", "cpri-logo.png"), os.path.join(HERE, "static", "accreditation.png")

DEFAULTS = {
    "organisation": "CENTRAL POWER RESEARCH INSTITUTE", "member_line": "(Member of STL)", "title": "TEST REPORT",
    "laboratory": "SHORT CIRCUIT LABORATORY",
    "address": ["P.B.NO.8066, SADASHIVANAGAR POST OFFICE", "SIR C.V. RAMAN ROAD, BENGALURU - 560 080 (INDIA)", "Phone: +91 (0) 80 - 22072365"],
    "discipline": "Discipline: Electrical Testing", "group": "Group: Inductors & Transformers",
    "ulr_prefix": "ULR-TC5452", "ulr_location": "0", "ulr_lab": "SCLT", "accreditation": "TC-5452",
    "engineer_label": "Test Engineer", "approver_label": "Reviewed and Authorized by",
    "headings": {"description": "DESCRIPTION OF SAMPLE TESTED", "description_note": "(As assigned by the manufacturer)",
                 "summary": "SUMMARY OF TESTS CONDUCTED", "drawings": "LIST OF DRAWINGS", "results": "TEST RESULTS",
                 "routine": "ROUTINE TESTS", "special": "SPECIAL TEST", "type": "TYPE TEST", "conclusion": "Conclusion",
                 "annex": "ADDITIONAL TEST RECORDS"},
    "sampling_plan": "Not applicable", "customer_requirement": "Nil", "deviations": "Nil", "other_witness": "None", "subcontracted": "None",
    "sc_circuit": "CRTL/SC/TR-07B",
    "clauses": {"sc": "21.4 b)", "nl112": "21.4 c)", "temp": "21.3 b)", "pressure_type": "21.3 d)", "resistance": "21.2 a)", "ratio": "21.2 b)",
                "impedance": "21.2 c)", "noload": "21.2 d)", "ir": "21.2 e)", "induced": "21.2 f)", "separate": "21.2 g)",
                "pressure_routine": "21.2 h)", "leak": "21.2 j)", "sc_dynamic": "Sub-clause 4.2 of IS: 2026 (Part-5):2011",
                "sc_thermal": "Sub-clause 4.1 of IS: 2026 (Part-5):2011"},
    "temperature_limits_standard": {"oil": "35", "winding": "40"},
    "notes": ["The Test results relate only to the sample(s) tested.",
              "Publication or reproduction of this Test Report in any form other than by complete set of the whole Test Report and in the "
              "language written is not permitted without the written consent of CPRI.",
              "Any Corrections / erasure invalidate the Test Report.",
              "Any anomaly / discrepancy in the Test Report should be brought to notice of CPRI within 45 days from the date of issue.",
              "All documents constituting the Test Report are stitched together with a continuous silk thread, the two ends of which have "
              "been brought over the front sheet of the Test Report and sealed with a CPRI logo printed paper sticker",
              "NABL has Accredited this laboratory as per ISO/IEC 17025-2017 vide Report no.TC-5452 for the tests carried out."],
    "drawing_statement": "It is verified that these drawings adequately represent the sample tested. Verification of this drawing by "
                         "CPRI is limited to dimensional check only wherever possible.",
    "generator": "Aletheia",
}


def template(path):
    """DEFAULTS overlaid with the template file; a missing or broken file falls back to the defaults."""
    t = json.loads(json.dumps(DEFAULTS))
    try:
        with open(path, encoding="utf-8") as f: own = json.load(f)
    except (OSError, ValueError): return t
    for k, v in own.items():
        if isinstance(v, dict) and isinstance(t.get(k), dict): t[k].update({a: str(b) for a, b in v.items()})
        elif isinstance(v, list) and isinstance(t.get(k), list): t[k] = [str(x) for x in v]
        elif isinstance(v, str) and (k in t or not k.startswith("_")): t[k] = v
    return t


# ------------------------------------------------------------------ small helpers
_ONES = "Nil One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen".split()
_TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def words(n):
    """Count in words, as the cover sheet writes it: 0 -> Nil, 11 -> Eleven, 23 -> Twenty Three."""
    if not isinstance(n, int) or n < 0: return "NA"
    if n < 20: return _ONES[n]
    if n < 100: return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    return str(n)


def ddmmyyyy(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{m[3]}-{m[2]}-{m[1]}" if m else str(iso or "NA")


def isna(v): return v is None or (isinstance(v, str) and v.strip().upper() in ("", "NA"))


def s(v):
    """A value as printed: as logged, NA when empty."""
    return "NA" if isna(v) else str(v)


def ulr(t, series, partial):
    """ULR-TC5452 + year + location + lab + job number + F (full report), e.g. ULR-TC5452250SCLT1654F."""
    m = re.match(r"CPRIBLRSCL(\d{2})T(\d{4})", str(series or ""))
    if partial or not m: return ""
    return f"{t['ulr_prefix']}{m[1]}{t['ulr_location']}{t['ulr_lab']}{m[2]}F"


def taps_of(P):
    """Tapping percentages and the tap numbers of principal / highest / lowest, from the proforma's tapping range
    ("+5% to -10% in steps of 2.5%"). Only labels: no reported value depends on it. None when the range is not in that form."""
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%\s*to\s*([+-]?\d+(?:\.\d+)?)\s*%.*?(\d+(?:\.\d+)?)\s*%", str(P.get("taps") or ""), re.I | re.S)
    if not m: return None
    hi, lo, step = float(m[1]), float(m[2]), float(m[3])
    if step <= 0 or hi <= lo: return None
    n = round((hi - lo) / step) + 1
    pct = [hi - i * step for i in range(n)]
    zero = next((i for i, p in enumerate(pct) if abs(p) < 1e-9), None)
    return dict(pct=["0" if abs(p) < 1e-9 else f"{p:+g}" for p in pct], N=None if zero is None else zero + 1, H=1, L=n)


class Mark(Flowable):
    """Records the sheet on which it lands, for the sheet references ("Refer Sheet 3 of 11")."""
    def __init__(self, key, store):
        super().__init__(); self.key, self.store = key, store; self.width = self.height = 0
    def wrap(self, *_): return 0, 0
    def draw(self): self.store.setdefault(self.key, self.canv.getPageNumber())


# ------------------------------------------------------------------ styles
BASE = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=12)
SMALL = ParagraphStyle("s", parent=BASE, fontSize=8.5, leading=10.5)
CELL = ParagraphStyle("c", parent=BASE, fontSize=8.5, leading=10)
CELLC = ParagraphStyle("cc", parent=CELL, alignment=TA_CENTER)
HEADC = ParagraphStyle("hc", parent=CELLC, fontName="Helvetica-Bold")
H1 = ParagraphStyle("h1", parent=BASE, fontName="Helvetica-Bold", fontSize=11, leading=14, alignment=TA_CENTER, spaceBefore=2, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=BASE, fontName="Helvetica-Bold", fontSize=10, leading=13, spaceBefore=6, spaceAfter=3)
H3 = ParagraphStyle("h3", parent=BASE, fontName="Helvetica-Bold", fontSize=9.5, leading=12, spaceBefore=6, spaceAfter=2)
NOTE = ParagraphStyle("n", parent=SMALL, alignment=TA_JUSTIFY)
W = A4[0] - 40 * mm  # text width
IND = " " * 5  # indent kept by Paragraph (ordinary spaces are collapsed)


def P_(text, style=BASE): return Paragraph(xesc(str(text)).replace("\n", "<br/>"), style)


def grid(rows, widths, head=1, spans=(), center=True, bold_rows=(), label_col=True):
    """A results table: thin black grid; header rows bold and centred; values centred (first column left when it holds labels)."""
    out = []
    for r, row in enumerate(rows):
        out.append([c if isinstance(c, Flowable) else P_(c, HEADC if r < head or r in bold_rows else CELLC if (center and (k or not label_col)) else CELL)
                    for k, c in enumerate(row)])
    t = Table(out, colWidths=widths, repeatRows=head)
    st = [("GRID", (0, 0), (-1, -1), .5, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    st += [("BACKGROUND", (0, r), (-1, r), colors.HexColor("#eeeeee")) for r in range(head)]
    st += [("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f5f5f5")) for r in bold_rows]
    st += [("SPAN", a, b) for a, b in spans]
    t.setStyle(TableStyle(st)); return t


def kv(pairs, widths=(62 * mm, 6 * mm, W - 68 * mm), style=BASE):
    """Label : value lines without a grid, as on the cover and the description sheet."""
    rows = [[P_(a, style), P_(":" if a and b is not None else "", style), P_("" if b is None else b, style)] for a, b in pairs]
    t = Table(rows, colWidths=list(widths))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
    return t


# ------------------------------------------------------------------ the report
def build(A, j, version=None, verify_url=None, manifest=None, partial=None):
    """A = the app module (validate, NAMES, signed, report_template file). Returns a BytesIO with the PDF.
    partial=dict(version, approved, pending, sections) builds the customer's partial report: approved tests only, no
    conclusion, no signatures, no ULR, watermark on every page."""
    t = template(A.TEMPLATE_FILE)
    try: F, C = A.validate(j["data"], j.get("plan"), j)
    except Exception: F, C = [], {}  # noqa: BLE001 - the report shows what it can
    prev, buf = {}, None
    for _ in range(3):  # lay out until the sheet numbers no longer move (normally twice)
        seen = {}
        buf = _render(A, t, j, F, C, version, verify_url, manifest, partial, prev, seen)
        if seen == prev: break
        prev = seen
    return buf


def _render(A, t, j, F, C, version, verify_url, manifest, partial, prev, seen):
    d = j["data"]; hd = t["headings"]
    Rq, P, Wk = d.get("request") or {}, d.get("proforma") or {}, d.get("work") or {}
    has = lambda *ks: all(isinstance(d.get(k), dict) and d.get(k) for k in ks)
    total = prev.get("_total")
    sheet = lambda key: f"{prev[key]} of {total}" if key in prev and total else "-"
    mark = lambda key: Mark(key, seen)
    taps = taps_of(P) or {}
    TAPNAME = {"N": "Principal", "H": "Highest", "L": "Lowest"}
    tapl = lambda k: f"{TAPNAME[k]} ({taps[k]})" if taps.get(k) else TAPNAME[k]
    date = ddmmyyyy(A.now())
    series = j.get("series") or Wk.get("series") or "NA"
    engineer = s(Wk.get("engineer"))
    clause = t["clauses"]

    def outcome(*names, ok="Within limits", bad="Not within limits"):
        """Observation from the checks behind a table row: a failure decides; a check that could not run says so."""
        fs = [f for f in F if any(n in f["check"] for n in names) and not f.get("advisory")]
        if not fs: return "-"
        if any(f["level"] == "fail" for f in fs): return bad
        if any(f.get("na") for f in fs): return "Not fully evaluated"
        if any(f.get("inconclusive") for f in fs): return "Inconclusive (close to the limit)"
        return ok

    story = []

    @contextmanager
    def part(name):
        """One block of results; if its data is too incomplete to lay out, say so instead of failing the whole report."""
        n = len(story)
        try: yield
        except Exception:  # noqa: BLE001
            del story[n:]; story.append(P_(f"{name}: data incomplete (NA values); see the source document.", SMALL))

    # ---------------------------------------------------------- sheet 1: cover
    rating = ", ".join(x for x in (f"{s(P.get('kva'))} kVA" if not isna(P.get("kva")) else "",
                                  f"{s(P.get('hv'))} / {s(P.get('lv'))} V" if not isna(P.get("hv")) else "",
                                  {3: "Three Phase", 1: "Single Phase"}.get(P.get("phases"), "")) if x)
    product = re.sub(r"^\s*\d\s*(?:phase|ph)\s*", "", s(Rq.get("sample")), flags=re.I) if not isna(Rq.get("sample")) else ""
    particulars = "\n".join(x for x in (rating, product) if x) or s(Rq.get("rating"))
    address = ", ".join(x for x in (Rq.get("customer") or Wk.get("customer"), Rq.get("address"), Rq.get("city"), Rq.get("state"), Rq.get("pin")) if not isna(x)) or "NA"
    kinds = [k for k, keys in (("Type Tests", ("temp", "pressure")), ("All Routine Tests", ("resistance", "losses", "noload", "routine")),
                                ("Special Test", ("sc", "noload"))) if any(has(x) for x in keys)]
    shots = [x for x in ((d.get("sc") or {}).get("shots") or []) if isinstance(x, list) and str(x[9] if len(x) > 9 else "").lower() != "calibration"]
    drawings = [x.strip() for x in re.split(r"[,;\n]+", str(Rq.get("drawings") or "")) if x.strip() and not isna(x)]
    graphs = 2 if has("temp") else 0
    witness = Rq.get("witness") if not isna(Rq.get("witness")) else Rq.get("witness_name")  # older requests named it witness_name
    lab = j.get("intake") or {}  # the laboratory's part of the request form (sheet 3)
    cover = [("Test Report Number", f"{series}" + " " * 12 + f"Date: {date}"), ("", None),
             ("Name and Address of the Customer", address), ("", None),
             ("Name and Address of the Manufacturer", s(Rq.get("manufacturer"))), ("", None),
             ("Particulars of sample tested", particulars), ("", None),
             ("Type", s(Rq.get("type") if not isna(Rq.get("type")) else P.get("cooling"))),
             ("Description of test sample", f"Refer Sheet {sheet('description')}"),
             ("Serial Number", s(Rq.get("serial"))),
             ("Number of samples tested", words(int(Rq["samples"])) if str(Rq.get("samples") or "").isdigit() else words(1) if not isna(Rq.get("serial")) else "NA"),
             ("", None), ("Date(s) of Test (s)", " to ".join(x for x in (s(Wk.get("start")), s(Wk.get("completed"))) if x != "NA") or "NA"), ("", None),
             ("CPRI Sample Code Number (s)", s(j.get("sample"))), ("", None),
             ("Particulars of tests conducted", (", ".join(kinds[:-1]) + " & " + kinds[-1] if len(kinds) > 1 else "".join(kinds) or "NA") + f"\n(Refer Sheet {sheet('summary')})"),
             ("", None), ("Test in accordance with Standard / specification", s(Wk.get("standard") if not isna(Wk.get("standard")) else Rq.get("criteria"))), ("", None),
             ("Sampling plan", t["sampling_plan"]), ("", None),
             ("Customer's requirement", s(Rq.get("requirement")) if not isna(Rq.get("requirement")) else t["customer_requirement"]),
             ("Deviations if any", s(lab.get("deviations")) if not isna(lab.get("deviations")) else t["deviations"]), ("", None),
             ("Name of the witnessing persons", None),
             ("Customer's representative", s(witness) if not isna(witness) else "None"),
             ("Other than customer's representative", s(Rq.get("witness_other")) if not isna(Rq.get("witness_other")) else t["other_witness"]), ("", None),
             ("Test subcontracted with address of the laboratory", t["subcontracted"]), ("", None)]
    story += [mark("cover"), kv(cover), Spacer(1, 4), P_("Documents constituting this Report (In words)", H3),
              kv([("Number of Sheet(s)", words(total) if total else "-"), ("Number of Oscillogram (s)", words(len(shots)) if has("sc") else "Nil"),
                  ("Number of Graph (s)", words(graphs)), ("Number of Photograph(s)", "Nil"),
                  ("Number of Test Circuit Diagram(s)", words(1) if has("sc") else "Nil"), ("Number of Drawing(s)", words(len(drawings)))])]
    if partial:
        story += [Spacer(1, 6), P_("Status of the tests", H3),
                  grid([["Test", "Status"]] + [[x, "Approved: values below"] for x in partial["approved"]] +
                       [[x, "Pending: not yet approved"] for x in partial["pending"]], [110 * mm, W - 110 * mm]),
                  Spacer(1, 4), P_("This partial report shows the values of the approved tests only. It is not a test report: it carries no verdict, "
                                   "no conclusion and no signature, and may change until the final report is released.", NOTE)]

    # ---------------------------------------------------------- sheet 2: description of the sample
    bil = [x.strip() for x in re.split(r";", str(P.get("bil") or "")) if x.strip()]
    hv_bil = next((x for x in bil if x.upper().startswith("HV")), bil[0] if bil else "NA")
    lv_bil = next((x for x in bil if x.upper().startswith("LV")), bil[1] if len(bil) > 1 else "NA")
    strip = lambda x, p: re.sub(rf"^\s*{p}\s*", "", x, flags=re.I)
    unit = lambda v, u: f"{v} {u}" if not isna(v) else "NA"
    desc = [("Test sample", s(Rq.get("sample"))), ("Type", s(Rq.get("type") if not isna(Rq.get("type")) else P.get("cooling"))),
            ("Serial number", s(Rq.get("serial"))), ("Rated power", unit(P.get("kva"), "kVA")),
            ("Rated voltage - HV / LV", f"{s(P.get('hv'))} / {s(P.get('lv'))} V"), ("Highest voltage of the equipment - Um", unit(P.get("hv_max_kv"), "kV")),
            ("Insulation levels", None), ("HV    LI / AC", strip(hv_bil, "HV")), ("LV    LI / AC", strip(lv_bil, "LV")),
            ("Impedance (Percent)", unit(P.get("z_pct"), "%")), ("Number of phases", s(P.get("phases"))), ("Rated frequency", unit(P.get("freq"), "Hz")),
            ("Vector group", s(P.get("vector"))), ("Tappings", s(P.get("taps"))), ("Energy efficiency", s(P.get("efficiency"))),
            ("Type of cooling", s(P.get("cooling"))), ("Maximum total loss at 50% load", unit(P.get("loss50"), "W")),
            ("Maximum total loss at 100% load", unit(P.get("loss100"), "W"))]
    if any(not isna(P.get(k)) for k in ("coil", "core")) or isna(P.get("construction")):
        desc += [("Coil", s(P.get("coil"))), ("Core material", s(P.get("core")))]
    else:
        desc += [("Construction", s(P.get("construction")))]
    desc += [("Month & Year of Manufacture", s(P.get("mfg"))), ("Volume of oil", unit(P.get("oil_l"), "litres")), ("", None)]
    if any(not isna(P.get(k)) for k in ("lv_winding", "hv_winding")):
        desc += [("Winding details", None), ("L.V. winding", s(P.get("lv_winding"))), ("H.V. winding", s(P.get("hv_winding")))]
    story += [PageBreak(), mark("description"), P_(hd["description"], H1), P_(hd["description_note"], ParagraphStyle("dn", parent=BASE, alignment=TA_CENTER)),
              Spacer(1, 6), kv(desc)]

    # ---------------------------------------------------------- results (laid out first, referenced by the summary)
    R = []  # results story; sheet breaks inside it
    L = d.get("losses") if has("losses") else None
    cols = (L or {}).get("cols") or ["tap", "z", "x", "xchg", "rhv", "rlv", "ll100", "xr", "ipk", "irms", "stray", "ll50", "t50", "t100"]
    ix = {c: n for n, c in enumerate(cols)}
    lrow = {str(r[0]).upper(): r for r in ((L or {}).get("rows") or []) if isinstance(r, list) and r}

    def lv_(tap, cond, col):
        r = lrow.get(f"{tap}T{cond}T")  # rows are named NTBT, HTAT, ... (tap, before / after test)
        return s(r[ix[col]]) if r is not None and ix.get(col, 99) < len(r) else "NA"

    def results_head(sub, key):
        return [mark(key), P_(hd["results"], H1)] + ([P_(sub, H2)] if sub else [])

    routine1 = []
    if L:
        with part("Measurement of winding resistance"):
            routine1 += [mark("resistance"), grid([["Measurement of winding resistance"] + [""] * 6,
                                                   ["", "Before SCW test", "", "", "After SCW test", "", ""],
                                                   ["Tap switch position"] + [tapl(k) for k in "NHL"] * 2,
                                                   ["HV winding resistance at 75 °C (Ω) - average"] + [lv_(k, c, "rhv") for c in ("B", "A") for k in "NHL"],
                                                   ["LV winding resistance at 75 °C (mΩ) - average", lv_("N", "B", "rlv"), "", "", lv_("N", "A", "rlv"), "", ""]],
                                                  [52 * mm] + [(W - 52 * mm) / 6] * 6, head=3,
                                                  spans=[((0, 0), (-1, 0)), ((1, 1), (3, 1)), ((4, 1), (6, 1)), ((1, 4), (3, 4)), ((4, 4), (6, 4))]), Spacer(1, 6)]
    if has("routine"):
        Rt = d["routine"]
        with part("Measurement of voltage ratio"):
            bt, at = Rt["ratio"]["BT"], Rt["ratio"]["AT"]
            pct = taps.get("pct") or []
            rows = [[str(i + 1), pct[i] if i < len(pct) else "-"] + [s(x) for x in bt[i]] + [s(x) for x in (at[i] if i < len(at) else ["", "", ""])] for i in range(len(bt))]
            routine1 += [mark("ratio"), grid([["Measurement of voltage ratio"] + [""] * 7, ["Tap switch position", "Tapping %", "Before SCW test", "", "", "After SCW test", "", ""],
                                              ["", "", "U", "V", "W", "U", "V", "W"]] + rows,
                                             [26 * mm, 22 * mm] + [(W - 48 * mm) / 6] * 6, head=3,
                                             spans=[((0, 0), (-1, 0)), ((0, 1), (0, 2)), ((1, 1), (1, 2)), ((2, 1), (4, 1)), ((5, 1), (7, 1))]), Spacer(1, 6),
                         grid([["Check of phase displacement"], [f"Vector group was found to be {s(Rt.get('vector'))}"]], [W], center=False), Spacer(1, 6)]
    if L:
        with part("Measurement of short-circuit impedance and load loss"):
            routine1 += [mark("impedance"), grid([["Measurement of short circuit impedance and load loss at 50% and 100% load"] + [""] * 6,
                                                  ["", "Before SCW test", "", "", "After SCW test", "", ""],
                                                  ["Tap switch position"] + [tapl(k) for k in "NHL"] * 2,
                                                  ["% Impedance at 75 °C"] + [lv_(k, c, "z") for c in ("B", "A") for k in "NHL"],
                                                  ["Load loss at 75 °C (W)"] + [lv_(k, c, "ll100") for c in ("B", "A") for k in "NHL"],
                                                  ["Load loss at 50% of full load at 75 °C (W)", lv_("N", "B", "ll50"), "---", "---", lv_("N", "A", "ll50"), "---", "---"]],
                                                 [52 * mm] + [(W - 52 * mm) / 6] * 6, head=3,
                                                 spans=[((0, 0), (-1, 0)), ((1, 1), (3, 1)), ((4, 1), (6, 1))]), Spacer(1, 6)]
    if has("noload"):
        N = d["noload"]
        with part("Measurement of no-load loss and current"):
            row = lambda lab: next(r for r in N["rows"] if str(r[0]).upper() == lab)
            nl = [[cond, s(N.get("v100")), s(row(k)[7]), s(row(k)[4]), s(row(k)[8])] for cond, k in (("Before SCW test", "BT"), ("After SCW test", "AT"))]
            routine1 += [mark("noload"), P_("Measurement of no-load loss and current", H3),
                         grid([["Condition of the sample", "Voltage (V)", "Frequency (Hz)", "No-load current (A)", "No-load loss (W)"]] + nl,
                              [44 * mm] + [(W - 44 * mm) / 4] * 4), Spacer(1, 4)]
    if routine1:
        R += [PageBreak()] + results_head(hd["routine"], "routine1") + routine1 + [P_("SCW - Short-Circuit Withstand", SMALL)]

    routine2 = []
    if L:
        with part("Check of energy efficiency level"):
            routine2 += [P_("Check of Energy Efficiency Level", H3),
                         grid([["", "Before SCW test", "After SCW test"], ["Total loss at 50% load (W)", lv_("N", "B", "t50"), lv_("N", "A", "t50")],
                               ["Total loss at 100% load (W)", lv_("N", "B", "t100"), lv_("N", "A", "t100")]], [80 * mm, (W - 80 * mm) / 2, (W - 80 * mm) / 2]), Spacer(1, 6)]
    if has("routine"):
        Rt = d["routine"]
        IRL = {"HV-EARTH": "HV winding with respect to LV winding & tank connected together and earthed.",
               "LV-EARTH": "LV winding with respect to HV winding & tank connected together and earthed.",
               "HV-LV": "HV winding with respect to LV winding with tank earthed."}
        with part("Measurement of insulation resistance"):
            routine2 += [mark("ir"), P_("Measurement of insulation resistance", H3),
                         grid([["Insulation resistance of", "Before SCW test (GΩ)", "After SCW test (GΩ)"]] +
                              [[IRL.get(str(k).upper().replace(" ", ""), str(k)), s(v[0]), s(v[1])] for k, v in Rt["ir"].items()],
                              [100 * mm, (W - 100 * mm) / 2, (W - 100 * mm) / 2]), Spacer(1, 6)]
        with part("Induced over-voltage withstand test"):
            ind = Rt["induced"]; cur = ind.get("i") or [None, None]
            txt = lambda n: f"{s(ind.get('v'))} V, {s(ind.get('f'))} Hz, {s(ind.get('t'))} s; current {s(cur[n] if len(cur) > n else None)} A\n{s(ind.get('obs'))}"
            routine2 += [mark("induced"), P_("Induced over-voltage withstand test", H3),
                         grid([["Test on", "Before SCW test", "After SCW test"], ["LV winding by keeping HV winding open circuit", txt(0), txt(1)]],
                              [70 * mm, (W - 70 * mm) / 2, (W - 70 * mm) / 2]), Spacer(1, 6)]
        with part("Separate source voltage withstand test"):
            hv, lv = Rt["hvac"], Rt["lvac"]
            routine2 += [mark("separate"), P_("Separate source voltage withstand test", H3),
                         grid([["Test on", "Result (as logged)", ""],
                               ["a) HV winding and all terminals of LV winding & tank connected together to earth", f"{s(hv.get('kv'))} kV for {s(hv.get('t'))} s: {s(hv.get('obs'))}", ""],
                               ["b) LV winding and all terminals of HV winding & tank connected together to earth", f"{s(lv.get('kv'))} kV for {s(lv.get('t'))} s: {s(lv.get('obs'))}", ""]],
                              [70 * mm, (W - 70 * mm) / 2, (W - 70 * mm) / 2], spans=[((1, 0), (2, 0)), ((1, 1), (2, 1)), ((1, 2), (2, 2))])]
    if routine2:
        R += [PageBreak()] + results_head(hd["routine"] + " (Contd...)", "routine2") + routine2 + [Spacer(1, 4), P_("SCW - Short-Circuit Withstand", SMALL)]

    if has("sc"):
        S = d["sc"]; req = S.get("required") or {}
        with part("Short-circuit withstand test"):
            cond = [("Test conditions", ""), ("Source", "Short-circuit generator"), ("Phases", "Three"), ("Frequency", "50 Hz"),
                    ("Test sample", ""), ("Condition before test", "Transformer as after routine tests" if isna(S.get("condition")) else f"Transformer {S['condition'].lower()}"),
                    ("Mounting", "Transformer tank isolated and grounded through the protection current transformer"),
                    ("Connection", ""), ("LV terminals", "Shorted"), ("HV terminals", "Connected to source"),
                    ("Test details", ""), ("Test circuit drawing number", t["sc_circuit"]),
                    ("Short-circuit", ""), ("Type", "Pre-set"), ("Applied on", "LV terminals through non-inductive current measuring shunt"), ("Short-circuit point", "Grounded")]
            ct = Table([[P_(a, ParagraphStyle("x", parent=CELL, fontName="Helvetica-Bold") if b == "" else CELL), P_(b, CELL)] for a, b in cond], colWidths=[60 * mm, W - 60 * mm])
            ct.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5)]))
            calc = [[tapl(k), lv_(k, "B", "xr"), s((req.get(k + "T") or [None, None])[0]), s((req.get(k + "T") or [None, None])[1])] for k in "NHL"]
            sc_page = [P_(hd["special"], H2), P_("SHORT-CIRCUIT WITHSTAND TEST", H3), ct, Spacer(1, 6), P_("Short-circuit current calculation", H3),
                       grid([["Tap switch position", "X/R at 75 °C", "Required short-circuit current on LV side (kA)", ""], ["", "", "rms", "peak"]] + calc,
                            [50 * mm, 30 * mm, (W - 80 * mm) / 2, (W - 80 * mm) / 2], head=2,
                            spans=[((0, 0), (0, 1)), ((1, 0), (1, 1)), ((2, 0), (3, 0))])]
            obs = lambda x: s(x[9]) if len(x) > 9 and not isna(x[9]) and str(x[9]).lower() not in ("thermal",) else ("No abnormality" if A.classify_observation(S.get("during")) else s(S.get("during")))
            rows, spans, bold = [[f"Ability to Withstand the Dynamic Effects of Short-Circuit [{clause['sc_dynamic']}]", "", "", "", ""],
                                 ["Oscillogram number", "Current peak (kA)", "Current rms (kA) (Average)", "Duration (s)", "Observation"]], [((0, 0), (-1, 0))], []
            for k in "NHL":
                group = [x for x in shots if str(x[1]).upper() == k + "T" and str(x[9] if len(x) > 9 else "").lower() != "thermal"]
                if not group: continue
                bold.append(len(rows)); spans.append(((0, len(rows)), (-1, len(rows))))
                rows.append([f"Tap switch position no. {tapl(k)}", "", "", "", ""])
                rows += [[f"{series}{x[0]}", s(x[3]), s(x[7]), s(x[8]), obs(x)] for x in group]
            therm = [x for x in shots if str(x[9] if len(x) > 9 else "").lower() == "thermal"]
            if therm:
                bold.append(len(rows)); spans.append(((0, len(rows)), (-1, len(rows))))
                rows.append([f"Thermal Ability to Withstand Short-Circuit [{clause['sc_thermal']}] Tap switch position no. {tapl(str(therm[0][1])[:1].upper()) if str(therm[0][1])[:1].upper() in TAPNAME else s(therm[0][1])}", "", "", "", ""])
                rows += [[f"{series}{x[0]}", "---", s(x[7]), s(x[8]), obs(x)] for x in therm]
            sc_page += [Spacer(1, 6), mark("sc_dynamic"), grid(rows, [52 * mm, 24 * mm, 30 * mm, 22 * mm, W - 128 * mm], head=2, spans=spans, bold_rows=bold)]
            R += [PageBreak()] + results_head(None, "sc") + sc_page

    page8 = []
    if L and has("sc"):
        with part("Reactance values"):
            S = d["sc"]
            page8 += [grid([["Reactance values after transformer attains ambient temperature", "", "", ""],
                            ["Tap switch position", "% X before SCW test", "% X after SCW test", "% change in X"]] +
                           [[tapl(k), lv_(k, "B", "x"), lv_(k, "A", "x"), lv_(k, "A", "xchg")] for k in "NHL"] +
                           [[("Variation of reactance is within limits" if outcome("Reactance change") == "Within limits"
                              else "Variation of reactance: " + outcome("Reactance change").lower()), "", "", ""],
                            ["Negative value of % change in reactance indicates increase in the value & vice versa", "", "", ""]],
                           [50 * mm] + [(W - 50 * mm) / 3] * 3, head=2,
                           spans=[((0, 0), (-1, 0)), ((0, 5), (-1, 5)), ((0, 6), (-1, 6))]),
                      P_("SCW - Short-Circuit Withstand", SMALL), Spacer(1, 4), P_("Physical Inspection:", H3)]
            parts = [x.strip() for x in str(S.get("inspection") or "").split(";") if x.strip()]
            page8 += [P_(x[0].upper() + x[1:], BASE) for x in parts] or [P_(s(S.get("after")), BASE)]
    elif has("sc"):
        S = d["sc"]
        page8 += [P_("Physical Inspection:", H3)] + [P_(x.strip(), BASE) for x in str(S.get("inspection") or "NA").split(";") if x.strip()]
    if has("pressure"):
        Pr = d["pressure"]
        with part("Oil leakage test"):
            lk = Pr["leak"]
            page8 += [mark("leak"), P_(hd["routine"], H2), P_("OIL LEAKAGE TEST", H3),
                      kv([("Test Procedure", "Transformer with all fittings including bushings in position, Air pressure was applied through breather connecting pipe."),
                          ("Atmospheric pressure", unit(Pr.get("atm_kpa"), "kPa")), ("Ambient temperature", unit(Pr.get("amb"), "°C"))], (45 * mm, 4 * mm, W - 49 * mm)),
                      grid([["Head pressure calculated at base of the tank kPa (g)", "Test Pressure at base of tank kPa (g)", "Test duration (Hours)", "Observations"],
                            [s(lk.get("head_kpa")), s(lk.get("kpa")), s(lk.get("hrs")), s(lk.get("obs"))]], [W / 4] * 4, label_col=False), Spacer(1, 6)]
        with part("Pressure test (routine)"):
            ro = Pr["routine"]
            page8 += [mark("pressure_routine"), P_("Pressure (ROUTINE Test)", H3),
                      kv([("Test Procedure", "Transformer tank fixed with all fittings including bushings in position, Air pressure applied through breather connecting pipe."),
                          ("Atmospheric Pressure", unit(Pr.get("atm_kpa"), "kPa")), ("Ambient temperature", unit(Pr.get("amb"), "°C"))], (45 * mm, 4 * mm, W - 49 * mm)),
                      grid([["Air pressure above atmospheric pressure (kPa)", "Duration (Minutes)", "Observations"],
                            [s(ro.get("kpa")), s(ro.get("min")), s(ro.get("obs"))]], [W / 3] * 3, label_col=False)]
    if page8:
        R += [PageBreak()] + results_head(None, "page8") + page8

    if has("temp"):
        T = d["temp"]
        with part("Temperature-rise test"):
            tapn = {"LT": "Lowest Tap", "NT": "Principal Tap", "HT": "Highest Tap"}.get(str(T.get("tap")).upper(), s(T.get("tap")))
            lim = (P.get("limits") or {}) if isinstance(P.get("limits"), dict) else {}
            std = t["temperature_limits_standard"]
            fm = lambda v, spec: format(v, spec) if isinstance(v, (int, float)) else "NA"
            how = lambda src: " (as logged)" if src == "logged" else " (calculated)" if src else ""
            g = graphs and [f"{series}G01", f"{series}G02"]
            rise = [["Measured Points", "Temperature-rise (°C)", "Guaranteed Limit declared by the manufacturer (°C)", "Limit as per the standard (°C)", "Observations"],
                    ["Top oil", fm(C.get("oil_rise"), ".2f") + how(C.get("oil_rise_src")), s(lim.get("oil")), std.get("oil", "-"), outcome("Top-oil temperature rise")],
                    ["HV winding", fm(C.get("hv_rise"), ".1f") + how(C.get("wdg_src")), s(lim.get("wdg")), std.get("winding", "-"), outcome("HV winding temperature rise")],
                    ["LV winding", fm(C.get("lv_rise"), ".1f") + how(C.get("wdg_src")), s(lim.get("wdg")), std.get("winding", "-"), outcome("LV winding temperature rise")]]
            R += [PageBreak()] + results_head(hd["type"], "temp") + [
                P_("Temperature-rise test", H3),
                kv([("Test method", "Short-circuit"), ("Test conditions", None), ("Source", None), (IND + "Phases", "Three"), (IND + "Frequency (Hz)", "50"),
                    ("Sample", None), (IND + "HV terminals", "Connected to three phase source"), (IND + "LV terminals", "Shorted through copper links of negligible resistance"),
                    (IND + "Tap position", tapn)], (45 * mm, 4 * mm, W - 49 * mm)),
                P_("Measured Losses", H3),
                grid([["No load loss at rated voltage and at rated frequency (W)", s(T.get("nll"))],
                      [f"Load loss at rated current at 75 °C at {tapn.lower()} (W)", s(T.get("fll"))]], [120 * mm, W - 120 * mm], head=0),
                P_("Test Procedure:", H3),
                P_(f"Step 1 - Total loss ({s(T.get('total'))} W) is injected until a steady state of oil temperature rise is established", BASE),
                P_(f"Step 2 - The rated current ({s(T.get('current'))} A) is injected for one hour, immediately after step-1.", BASE),
                P_(f"The values of hot resistance of HV and LV windings at the time of shutdown are given in graphs {g[0]} & {g[1]} respectively.", BASE),
                P_(f"Ambient temperature: {unit(T.get('amb_sd'), '°C')}", BASE), Spacer(1, 4),
                grid(rise, [26 * mm, 34 * mm, 42 * mm, 30 * mm, W - 132 * mm])]
            if C.get("wdg_src") == "calculated":
                R.append(P_("Winding temperature rise not logged; calculated from the logged hot and cold resistances.", SMALL))

    page10 = []
    if has("pressure"):
        Pr = d["pressure"]
        with part("Pressure test (type)"):
            ty = Pr["type"]
            page10 += [mark("pressure_type"), P_("Pressure (TYPE TEST)", H3),
                       kv([("Test Procedure", "Transformer tank fixed with all fittings including bushings in position. First air and then vacuum applied through breather connecting pipe."),
                           ("Atmospheric Pressure", unit(Pr.get("atm_kpa"), "kPa")), ("Ambient temperature", unit(Pr.get("amb"), "°C"))], (45 * mm, 4 * mm, W - 49 * mm)),
                       P_("Air Pressure test:", H3),
                       grid([["Air pressure above atmospheric pressure (kPa)", "Duration (Minutes)", "Permanent deflection of flat plate after release of air pressure (mm)", "Observations"],
                             [s(ty["pressure"].get("kpa")), s(ty["pressure"].get("min")), s(ty["pressure"].get("max")), s(ty["pressure"].get("obs"))]], [W / 4] * 4, label_col=False),
                       P_("Vacuum test:", H3),
                       grid([["Vacuum in level of mm of Mercury", "Duration (Minutes)", "Permanent deflection of flat plate after release of vacuum (mm)", "Observations"],
                             [s(ty["vacuum"].get("mmhg")), s(ty["vacuum"].get("min")), s(ty["vacuum"].get("max")), s(ty["vacuum"].get("obs"))]], [W / 4] * 4, label_col=False), Spacer(1, 6)]
    if has("noload"):
        N = d["noload"]
        with part("No load current at 112.5 percent voltage"):
            lim100, lim112 = A.nll_limits(P["kva"]) if not isna(P.get("kva")) else ("NA", "NA")
            irat = C.get("irat")
            def pc(lab112):
                rows = [r for r in N["rows"] if ("112" in str(r[0])) == lab112]
                i = max((r[4] for r in rows if isinstance(r[4], (int, float))), default=None)
                return f"{i / irat * 100:.2f}" if irat and isinstance(i, (int, float)) else "NA"
            page10 += [mark("nl112"), P_("SPECIAL TESTS", H2), P_("No load current at 112.5 percent voltage", H3),
                       grid([["Test Procedure", "No-load current of transformer was measured at rated voltage and 112.5 % rated voltage at 50 Hz on LV side. Values are given below."]],
                            [40 * mm, W - 40 * mm], head=0, center=False), Spacer(1, 4),
                       grid([["Average no-load current (Percentage of rated full load current)", "", "", ""],
                             [f"At 100 percent rated voltage ({s(N.get('v100'))} V)", "", f"At 112.5 percent rated voltage ({s(N.get('v1125'))} V)", ""],
                             ["Permissible value given in the standard", "Measured value", "Permissible value given in the standard", "Measured value"],
                             [f"{lim100:g}" if isinstance(lim100, (int, float)) else lim100, pc(False), f"{lim112:g}" if isinstance(lim112, (int, float)) else lim112, pc(True)]],
                            [W / 4] * 4, head=3, spans=[((0, 0), (-1, 0)), ((0, 1), (1, 1)), ((2, 1), (3, 1))], label_col=False)]
    if page10:
        R += [PageBreak()] + results_head(None, "page10") + page10

    if not partial and R:  # the conclusion follows the last results sheet
        fails = [f for f in F if f["level"] == "fail"]
        missing = [A.NAMES[k] for k in A.required(j.get("plan")) if k not in d]
        skipped = list(dict.fromkeys(f["check"] for f in F if f.get("na")))
        scope = ""
        if missing or skipped:
            scope = (" This conclusion covers only what could be evaluated. Not evaluated: "
                     + "; ".join(filter(None, [("documents not provided - " + ", ".join(missing)) if missing else "",
                                               ("checks with NA values - " + ", ".join(skipped)) if skipped else ""])) + ".")
        std_txt = s(Wk.get("standard") if not isna(Wk.get("standard")) else Rq.get("criteria"))
        concl = (f"The sample tested does NOT comply with the requirement(s) of Clause(s) referred of {std_txt} for the tests conducted. "
                 f"Requirements not met: " + "; ".join(f["check"] for f in fails) + "." if fails else
                 f"The sample tested complies with the requirement(s) of Clause(s) referred of {std_txt} for the tests conducted.")
        R += [Spacer(1, 8), mark("conclusion"), Paragraph(f"<b>{xesc(hd['conclusion'])}:</b> " + xesc(concl) + xesc(scope), NOTE)]
        if fails:
            R += [Spacer(1, 4), grid([["Requirement", "Result obtained", "Required"]] + [[f["check"], f.get("found", f["detail"]), f.get("expected", "-")] for f in fails],
                                     [60 * mm, (W - 60 * mm) / 2, (W - 60 * mm) / 2])]
        warns = [f for f in F if f["level"] == "warn" and not f.get("na") and not f.get("advisory")]
        if warns:
            R += [Spacer(1, 4), P_("* Items flagged by automated validation and accepted by the reviewer at approval:" if j.get("approver") else
                                   "* Items flagged by automated validation - to be confirmed by the reviewer before approval:", SMALL),
                  grid([["Check", "Detail"]] + [[f["check"], f["detail"]] for f in warns], [50 * mm, W - 50 * mm], center=False)]

    others = list((d.get("other") or {}).values())
    if others:
        R += [PageBreak(), mark("annex"), P_(hd["annex"], H1)]
        for o in others:
            with part(A.name("other")):
                R.append(P_(f"{o.get('title') or 'Supplementary test record'} (recorded values; no limits evaluated)", H3))
                if o.get("fields"): R.append(kv([(f.get("label") or "-", s(f.get("value"))) for f in o["fields"]]))
                for tb in o.get("tables") or []:
                    if tb.get("title"): R.append(P_(tb["title"], SMALL))
                    cols_ = tb.get("columns") or [""] * len(tb["rows"][0])
                    R.append(grid([cols_] + [[s(c) for c in r] for r in tb.get("rows", [])], [W / len(cols_)] * len(cols_)))

    # ---------------------------------------------------------- sheet 3: summary of tests conducted
    TESTS = [("Special Tests", [("Short-circuit withstand test\n(Ability to withstand the Dynamic Effects of Short circuit and Thermal Ability to withstand Short Circuit)",
                                 "sc", ("sc", "page8") if L else ("sc",), "sc"),
                                ("No load current at 112.5 percent voltage", "nl112", ("nl112",), "noload")]),
             ("Type Tests", [("Temperature-rise test", "temp", ("temp",), "temp"), ("Pressure test", "pressure_type", ("pressure_type",), "pressure")]),
             ("All Routine Tests", [("Measurement of winding resistance", "resistance", ("resistance",), "losses"),
                                    ("Measurement of voltage ratio and check of phase displacement", "ratio", ("ratio",), "routine"),
                                    ("Measurement of short-circuit impedance and load loss at 50% and 100% load", "impedance", ("impedance",), "losses"),
                                    ("Measurement of no-load loss and current", "noload", ("noload",), "noload"),
                                    ("Measurement of insulation resistance", "ir", ("ir",), "routine"),
                                    ("Induced over-voltage withstand test", "induced", ("induced",), "routine"),
                                    ("Separate source voltage withstand test", "separate", ("separate",), "routine"),
                                    ("Pressure test", "pressure_routine", ("pressure_routine",), "pressure"),
                                    ("Oil leakage test", "leak", ("leak",), "pressure")])]
    srows, sspans, sbold = [["Tests Conducted", "Clause Number (s)", "Sheet"]], [], []
    for group, items in TESTS:
        items = [x for x in items if has(x[3])]
        if not items: continue
        sbold.append(len(srows)); sspans.append(((0, len(srows)), (-1, len(srows)))); srows.append([group, "", ""])
        for name, ck, keys, _src in items:
            srows.append([name, clause.get(ck, "-"), "\n&\n".join(sheet(k) for k in keys)])
    first_res = next((k for k in ("routine1", "routine2", "sc", "page8", "temp", "page10") if k in prev), None)
    last_res = next((k for k in ("page10", "temp", "page8", "sc", "routine2", "routine1") if k in prev), None)
    osc = [f"{series}{x[0]}" for x in shots]
    lst = lambda xs: (", ".join(xs[:-1]) + " & " + xs[-1]) if len(xs) > 1 else (xs[0] if xs else "Nil")
    summary = [PageBreak(), mark("summary"), P_(hd["summary"], H1),
               kv([("1. Tests conducted", "Refer the below table"),
                   ("2. Rating for which tested", f"Refer Sheet {sheet(first_res)} to Sheet {sheet(last_res)}" if first_res else "NA"),
                   ("3. Schedule of tests", None)], (62 * mm, 6 * mm, W - 68 * mm)),
               P_(f"The clause numbers of the standard {s(Wk.get('standard') if not isna(Wk.get('standard')) else Rq.get('criteria'))} pertain to the test(s) "
                  "conducted are detailed in the following table.", NOTE), Spacer(1, 4),
               grid(srows, [W - 60 * mm, 32 * mm, 28 * mm], spans=sspans, bold_rows=sbold) if len(srows) > 1 else P_("No test data.", SMALL),
               Spacer(1, 6),
               kv([("4. Oscillogram number(s)", lst(osc) if has("sc") else "Nil"),
                   ("5. Graph number(s)", lst([f"{series}G01", f"{series}G02"]) if graphs else "Nil"),
                   ("6. Photograph number(s)", "Nil"),
                   ("7. Test circuit diagram number(s)", t["sc_circuit"] if has("sc") else "Nil"),
                   ("8. Drawing Numbers", f"Refer Sheet {sheet('drawings')}")], (62 * mm, 6 * mm, W - 68 * mm))]

    # ---------------------------------------------------------- sheet 4: list of drawings
    dr = [PageBreak(), mark("drawings"), P_(hd["drawings"], H1), P_("Drawing Numbers", H3),
          P_("Manufacturer has guaranteed that the sample submitted for the test (s) has been manufactured in accordance with the following drawings.", NOTE),
          Spacer(1, 4),
          grid([["Sl. No.", "Drawing Number", "Sheet Number", "Revision Number"]] + [[str(n + 1), x, "-", "-"] for n, x in enumerate(drawings)] +
               ([] if drawings else [["1", "NA", "-", "-"]]), [18 * mm, W - 78 * mm, 30 * mm, 30 * mm]),
          Spacer(1, 6), P_(t["drawing_statement"], NOTE)]

    story += summary + dr + R

    # ---------------------------------------------------------- last sheet: notes, accreditation, verification, traceability
    if partial:
        story += [Spacer(1, 10), P_("Approved data in this partial report", H3),
                  grid([["Test", "Revision", "Data SHA-256"]] + [[a, str(b), c[:32]] for a, b, c in partial["sections"]], [70 * mm, 20 * mm, W - 90 * mm])]
    else:
        notes = [[P_("NOTE", HEADC)]] + [[P_(f"{n + 1}. {x}", NOTE)] for n, x in enumerate(t["notes"])]
        nt = Table(notes, colWidths=[W]); nt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .5, colors.black), ("LINEBELOW", (0, 0), (-1, 0), .5, colors.black)]))
        tail = [PageBreak(), mark("notes"), nt, Spacer(1, 8)]
        acc = []
        if os.path.exists(ACCREDITATION):
            acc = [Image(ACCREDITATION, width=34 * mm, height=34 * mm * 103 / 193), P_(t["accreditation"], CELLC)]
        if verify_url:
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing
            w = QrCodeWidget(verify_url); b = w.getBounds(); size = 24 * mm
            q = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0]); q.add(w)
            vt = P_(f"Verify this report (version {version}): scan the code or open {verify_url}. The page shows the SHA-256 fingerprint of this exact PDF "
                    "and whether it is the current, approved version.", SMALL)
            row = Table([[acc or "", q, vt]], colWidths=[40 * mm, 28 * mm, W - 68 * mm])
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])); tail.append(row)
        elif acc:
            tail += acc
        if manifest:  # traceability annex: what the report was built from
            m, msha = manifest
            tail += [Spacer(1, 8), P_("Traceability of this report", H3)]
            if m.get("supersedes"):
                tail.append(P_(f"This version supersedes version {m['supersedes']['version']}. Reason for the amendment: {m['supersedes']['reason']}", SMALL))
            tail.append(grid([["Test", "Rev.", "Data SHA-256", "Source file SHA-256", "Template", "Uploaded by", "Verified by"]] +
                             [[x["test"], str(x["revision"]), (x["data_sha256"] or "-")[:16], (x["file_sha256"] or "-")[:16], x["template"] or "-",
                               (x["uploaded_by"] or "-") + (f" ({x['bay']})" if x.get("bay") else ""), x["verified_by"] or ("not applicable" if x["state"] == "na" else "-")]
                              for x in m["sections"] if x["key"] != "request"], [34 * mm, 9 * mm, 26 * mm, 26 * mm, 22 * mm, 27 * mm, W - 144 * mm]))
            tail.append(P_(f"Intake received by {m['intake']['received_by'] or '-'}, checked against the original form by {m['intake']['checked_by'] or '-'}; "
                           f"data signed off by {m['signed_off_by'] or '-'}. Software {m['software']['code']}, schema {m['software']['schema']}. "
                           f"Manifest SHA-256: {msha}", SMALL))
        tail += [Spacer(1, 10), P_("-" * 40 + "End of Test Report" + "-" * 40, ParagraphStyle("e", parent=SMALL, alignment=TA_CENTER))]
        story += tail

    # ---------------------------------------------------------- page furniture
    approver = A.signed(j.get("approver"), j.get("approver_id")) if j.get("approver") else ""
    code = ulr(t, series, partial)
    title = t["title"] + (" - PARTIAL REPORT, NOT FINAL" if partial else "")

    def page(cv, doc):
        n = cv.getPageNumber(); seen["_total"] = n
        pw, ph = A4; cv.saveState()
        top = ph - 12 * mm
        if os.path.exists(LOGO): cv.drawImage(LOGO, 20 * mm, top - 13 * mm, width=14 * mm, height=14 * mm, preserveAspectRatio=True, mask="auto")
        cv.setFont("Helvetica-Bold", 14); cv.drawCentredString(pw / 2, top - 5 * mm, t["organisation"])
        cv.setFont("Helvetica", 8.5); cv.drawCentredString(pw / 2, top - 9.5 * mm, t["member_line"])
        cv.setFont("Helvetica-Bold", 12); cv.drawCentredString(pw / 2, top - 17 * mm, title)
        tw = cv.stringWidth(title, "Helvetica-Bold", 12); cv.setLineWidth(.6); cv.line(pw / 2 - tw / 2, top - 18 * mm, pw / 2 + tw / 2, top - 18 * mm)
        if n > 1:
            y = top - 26 * mm; cv.setLineWidth(.5); cv.rect(20 * mm, y - 2 * mm, pw - 40 * mm, 7 * mm)
            cv.setFont("Helvetica-Bold", 9); cv.drawString(22 * mm, y, f"Test Report Number: {series}"); cv.drawRightString(pw - 22 * mm, y, f"Date: {date}")
        # signature line(s) of the sheet
        if not partial:
            cv.setFont("Helvetica", 9); y = 34 * mm
            if n == 1:
                cv.drawString(22 * mm, y + 4 * mm, f"({engineer})"); cv.drawString(22 * mm, y, t["engineer_label"])
                if approver: cv.drawRightString(pw - 22 * mm, y + 4 * mm, f"({approver})")
                cv.drawRightString(pw - 22 * mm, y, t["approver_label"])
            else:
                cv.drawRightString(pw - 22 * mm, y + 4 * mm, f"({engineer})"); cv.drawRightString(pw - 22 * mm, y, t["engineer_label"])
        # footer
        cv.setLineWidth(.6); cv.line(20 * mm, 27 * mm, pw - 20 * mm, 27 * mm); cv.setFont("Helvetica", 7.5)
        for k, line in enumerate([code, t["discipline"], t["group"]]): cv.drawString(20 * mm, 23 * mm - k * 3.4 * mm, line)
        cv.setFont("Helvetica-Bold", 8); cv.drawCentredString(pw / 2, 23 * mm, t["laboratory"]); cv.setFont("Helvetica", 7.5)
        for k, line in enumerate(t["address"]): cv.drawCentredString(pw / 2, 19.6 * mm - k * 3.4 * mm, line)
        cv.setFont("Helvetica-Bold", 8.5); cv.drawRightString(pw - 20 * mm, 23 * mm, f"Sheet {n} of {total or '-'}")
        if partial:
            cv.setFont("Helvetica-Bold", 54); cv.setFillColorRGB(.8, .15, .15, alpha=.13)
            cv.translate(pw / 2, ph / 2); cv.rotate(40); cv.drawCentredString(0, 0, "PARTIAL - NOT FINAL")
        cv.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=44 * mm, bottomMargin=42 * mm,
                            title=f"Test Report {series}", author=t["generator"], invariant=1)
    doc.build(story, onFirstPage=page, onLaterPages=page)
    buf.seek(0); return buf
