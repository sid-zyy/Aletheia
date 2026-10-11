"""Version 2 of the logsheet templates: each test's Excel sheet laid out as its scanned paper logsheet (item 7 of the
feedback of 10-11 Oct 2026). Same order, labels and units as the paper; the header block first, then the readings, then
remarks and signatures. Input cells are light yellow; printed text, row labels and calculated cells are locked and grey;
choices are dropdowns, readings must be numbers, dates must be dates. A hidden first row carries the fingerprint that
recognises the sheet on upload.

The stored data keeps the shape the checks and the report read (app.validate, report.py): every field of version 1 is
read from the new layout, and what the paper adds (time of each reading, voltage applied per shot, instruments used,
signatures...) is stored under new names alongside. Version 1 stays importable (retired), so files filled in earlier still
read. The scans these follow: sample_data/scans/.
"""
from openpyxl.utils import get_column_letter as L

NUM, TXT, DATE = "number", "text", "date"
FOOTER = "Document: FORMS & FORMATS"
# sheet tabs (31 characters at most); inside Aletheia the formal test names are used (excel_routes.titled)
TABS = dict(work="Work Instruction", proforma="Proforma for Transformers", losses="Loss Measurement Datasheet", resistance="Winding Resistance and Loss",
            noload="No-Load Loss and Current", routine="Routine Test Logsheet", sc="Short-Circuit Withstand Test", temp="Temperature-Rise Test",
            pressure="Pressure and Oil-Leakage Test")


class Paper:
    """Builds one mapping: printed text (layout) and the fields, row by row from the top of the sheet."""

    def __init__(self, section, prefix, title, org, unit=None, landscape=False, meta=None, note=None):
        self.section, self.prefix, self.title = section, prefix, title
        self.n = 16 if landscape else 12
        self.landscape = landscape
        self.layout, self.fields, self.r = [], [], 1
        self.text("A1", None, f"Aletheia template {section} v2", "fingerprint")
        self.text("A2", L(self.n) + "2", note or ("Fill in the yellow cells as on the paper logsheet. Grey cells are printed text or "
                  "are calculated; they are locked. Choose from the list where a cell offers one; readings must be numbers and dates "
                  "must be dates (dd-mm-yyyy). Leave a cell empty if the value is not on the sheet: it is recorded as NA."), "note", h=30)
        self.r = 3
        self.text(f"A{self.r}", f"{L(self.n)}{self.r}", org, "org", h=18); self.r += 1
        if unit: self.text(f"A{self.r}", f"{L(self.n)}{self.r}", unit, "unit"); self.r += 1
        if meta:  # format number, revision and issue as printed on the sheet
            half = self.n // 2
            self.text(f"A{self.r}", f"{L(half)}{self.r}", meta[0], "meta", h=40)
            self.text(f"{L(half + 1)}{self.r}", f"{L(self.n)}{self.r}", meta[1], "meta_r"); self.r += 1
        self.text(f"A{self.r}", f"{L(self.n)}{self.r}", title, "title", h=20); self.r += 2

    # ---- printed text
    def text(self, at, to, text, style="label", h=None):
        it = dict(at=at, text=text, style=style)
        if to and to != at: it["to"] = to
        if h: it["h"] = h
        self.layout.append(it)

    def section_head(self, text):
        self.text(f"A{self.r}", f"{L(self.n)}{self.r}", text, "section"); self.r += 1

    def para(self, text, h=40):
        self.text(f"A{self.r}", f"{L(self.n)}{self.r}", text, "text", h=h); self.r += 1

    def gap(self, n=1): self.r += n

    # ---- fields
    def _name(self, path):
        if path.startswith("@ids."): return f"{self.prefix}_{'SERIES' if path.endswith('[0]') else 'SAMPLE'}"
        return f"{self.prefix}_" + "".join(ch if ch.isalnum() else "_" for ch in path).strip("_").upper()

    def field(self, path, cell, typ, label=None, req=False, to=None, title=None, **kw):
        f = dict(field=path, cell=cell, name=self._name(path), type=typ, required=req)
        if to and to != cell: f["to"] = to
        if label: f["label"] = label
        if title or label: f["title"] = title or label
        f.update(kw)
        self.fields.append(f); return f

    def row(self, label, path, typ=TXT, req=False, also=None, h=None, **kw):
        """Label : value, one per line (the label on the left third, the value across the rest)."""
        lc = 5 if self.landscape else 4
        self.text(f"A{self.r}", f"{L(lc)}{self.r}", label, "label", h=h)
        if also: self.field(also, f"{L(lc + 1)}{self.r}", typ, None, False, title=label + " (as written)", by=["cell"])  # first: the main value is drawn last
        self.field(path, f"{L(lc + 1)}{self.r}", typ, label, req, to=f"{L(self.n)}{self.r}", **kw)
        self.r += 1

    def pair(self, a, b):
        """Two label : value pairs on one line, as in the header blocks of the paper sheets. a, b = (label, path, type[, opts])."""
        q = self.n // 4  # label q columns, value q columns, twice
        for k, spec in enumerate((a, b)):
            if not spec: continue
            label, path, typ, *rest = spec; opts = rest[0] if rest else {}
            c = 1 + k * 2 * q
            self.text(f"{L(c)}{self.r}", f"{L(c + q - 1)}{self.r}", label, "label")
            self.field(path, f"{L(c + q)}{self.r}", typ, label, opts.pop("req", False), to=f"{L(c + 2 * q - 1)}{self.r}", **opts)
        self.r += 1

    def grid(self, caption, cols, rows, typ=NUM, label_cols=None):
        """A small grid of single values (Before / After STC test, BT / AT). rows = [(row label, [path per column], opts)]."""
        lc = label_cols or (5 if self.landscape else 4)
        w = (self.n - lc) // len(cols)
        self.text(f"A{self.r}", f"{L(lc)}{self.r}", caption, "head")
        for k, c in enumerate(cols):
            a = lc + 1 + k * w
            self.text(f"{L(a)}{self.r}", f"{L(a + w - 1 if k < len(cols) - 1 else self.n)}{self.r}", c, "head")
        self.r += 1
        for label, paths, *rest in rows:
            opts = rest[0] if rest else {}
            self.text(f"A{self.r}", f"{L(lc)}{self.r}", label, "label")
            for k, p in enumerate(paths):
                if not p: continue
                a = lc + 1 + k * w
                self.field(p, f"{L(a)}{self.r}", opts.get("type", typ), None, False, to=f"{L(a + w - 1 if k < len(cols) - 1 else self.n)}{self.r}",
                           title=f"{label} ({cols[k]})", by=["name", "cell"], **{x: v for x, v in opts.items() if x != "type"})
            self.r += 1

    def bt_at(self, group, rows, h=None):
        """One block of the routine-test sheet: a group label down the left, a sub-label, then the BT and AT values."""
        start = self.r
        for sub, bt, at, typ, *rest in rows:
            opts = rest[0] if rest else {}
            self.text(f"C{self.r}", f"E{self.r}", sub, "label")
            for p, a, b in ((bt, "F", "H"), (at, "I", "L")):
                if p: self.field(p, f"{a}{self.r}", typ, None, False, to=f"{b}{self.r}", title=f"{group}: {sub} ({'BT' if a == 'F' else 'AT'})", by=["name", "cell"], **opts)
            self.r += 1
        self.text(f"A{start}", f"B{self.r - 1}", group, "label_b")

    def table(self, path, columns, caption=None, rows=None, row_labels=None, col=1, gap=1, share=None, **kw):
        """A readings table: header row(s), then one row per reading. share: further fields reading the same table."""
        if caption: self.r += 1
        at = f"{L(col)}{self.r}"
        f = dict(field=path, type="table", at=at, columns=columns, **kw)
        if caption: f["caption"] = caption
        if row_labels: f["row_labels"] = row_labels
        f["rows"] = len(row_labels) if row_labels else (rows or 5)
        self.fields.append(f)
        for s in share or []:
            g = dict(field=s.pop("field"), type="table", at=at, columns=columns, caption=None, rows=f["rows"], **s)
            if row_labels: g["row_labels"] = row_labels
            self.fields.append(g)
        two = any("group" in c for c in columns)
        self.r += (2 if two else 1) + f["rows"] + gap
        return f

    def tgrid(self, path, columns, records, row_labels=None, caption=None, share=None, **kw):
        """A table drawn sideways (titles down the left, one record per column), as the paper draws reference points."""
        if caption: self.section_head(caption)
        at = f"A{self.r}"
        f = dict(field=path, type="table", orient="columns", at=at, columns=columns, records=records, **kw)
        if row_labels: f["row_labels"] = row_labels
        self.fields.append(f)
        for s in share or []:
            g = dict(field=s.pop("field"), type="table", orient="columns", at=at, columns=columns, records=records, **s)
            if row_labels: g["row_labels"] = row_labels
            self.fields.append(g)
        self.r += len(columns) + 1

    def instruments(self, names, path="instruments"):
        self.table(path, [dict(label="Instruments / Equipment used", type=TXT, w=26), dict(label="Serial Number", type=TXT, w=18)],
                   row_labels=names, rows_as="dict", caption=None)

    def signatures(self, labels):
        """Signature lines at the foot of the sheet: the name (and date) written under each printed caption."""
        w = self.n // len(labels)
        for k, (label, path) in enumerate(labels):
            a, b = 1 + k * w, (k + 1) * w if k < len(labels) - 1 else self.n
            self.field(path, f"{L(a)}{self.r}", TXT, None, False, to=f"{L(b)}{self.r}", title=label, by=["name", "cell"])
            self.text(f"{L(a)}{self.r + 1}", f"{L(b)}{self.r + 1}", label, "sig")
        self.r += 3

    def footer(self, text):
        self.text(f"A{self.r}", f"{L(self.n)}{self.r}", text, "foot"); self.r += 1

    def mapping(self, consts=()):
        # a label printed more than once on the sheet cannot find its value: those fields are found by name or cell only
        seen = {}
        for it in self.layout:
            if isinstance(it.get("text"), str): k = it["text"].strip().lower(); seen[k] = seen.get(k, 0) + 1
        for f in self.fields:
            if f.get("label") and seen.get(f["label"].strip().lower(), 0) > 1: f.pop("label"); f["by"] = ["name", "cell"]
        widths = {L(c): (9.5 if self.landscape else 10.5) for c in range(1, self.n + 1)}
        return dict(section=self.section, title=self.title, sheet_title=TABS.get(self.section, self.title)[:31], version=2, kind="logsheet", style="paper",
                    fingerprint=dict(contains=f"Aletheia template {self.section} v2", within="A1:P3"),
                    page=dict(orientation="landscape" if self.landscape else "portrait", widths=widths),
                    layout=self.layout, fields=self.fields + [dict(c) for c in consts])


def ids(section): return f"@ids.{section}[0]", f"@ids.{section}[1]"


# ------------------------------------------------------------------ the nine logsheets
def work():
    p = Paper("work", "WI2", "Work Instruction", "CENTRAL POWER RESEARCH INSTITUTE", "Name of the Unit / Division : SHORT CIRCUIT LABORATORY",
              meta=("Format No. : CPRI/QAF/02\nRevision No. 02\nRevision Date : 28/10/2019", "Issue No. 01\nDate of Issue : 15-11-2005\nSheet 1 of 1"))
    s, m = ids("work")
    p.row("Test series Number (Where applicable)", "series", TXT, True, also=s)
    p.row("Sample Code Number", "sample", TXT, True, also=m)
    p.row("Name of Customer", "customer")
    p.row("Customer Reference Number", "customer_ref")
    p.row("Description of Test Sample", "description")
    p.row("Specific Instructions for mounting and Connections, if any", "mounting", h=28)
    p.row("Special Instructions", "special")
    p.row("Date of Test", "start", DATE)
    p.row("Customer Requirement", "requirement")
    p.row("Name of Test or Tests Required", "tests_required")
    p.row("Reference Standard for the Test", "standard")
    p.row("Whether Standard used is latest", "standard_latest", choices=["Yes", "No"])
    p.row("Deviation / Change from Standard", "deviation")
    p.row("Work Allotted to", "allotted")
    p.signatures([("Signature Test In Charge / HOD with Date", "sig.hod")])
    p.row("Work Completed on", "completed", DATE)
    p.row("Name & Signature of the Test Engineer who performed the work", "performed_by", h=28)
    p.row("Test Engineer Responsible for Report", "engineer", TXT, True)
    p.row("Deviations Noticed during the Testing / Calibration", "deviations_noticed", h=28)
    p.row("Recording of sorting out the discrepancies", "discrepancies")
    p.signatures([("Name & signature of Test Engineer with Date", "sig.engineer")])
    return p.mapping()


def proforma():
    p = Paper("proforma", "PF2", "PROFORMA FOR TRANSFORMERS", "SHORT CIRCUIT LABORATORY", "CENTRAL POWER RESEARCH INSTITUTE, BENGALURU")
    s, m = ids("proforma")
    p.pair(("Test Series No.", s, TXT), ("Sample Code Number", m, TXT)); p.gap()
    p.section_head("DESCRIPTION OF THE SAMPLE TO BE FILLED BY MANUFACTURER")
    p.row("TYPE (tick where applicable): Sealed / Non-sealed", "type_seal", choices=["Sealed", "Non-sealed"])
    p.row("TYPE: Oil immersed / Dry Type", "type_insulation", choices=["Oil immersed", "Dry Type"])
    p.row("TYPE: Indoor / Outdoor", "type_location", choices=["Indoor", "Outdoor"])
    p.row("SERIAL NUMBER", "serial")
    p.row("DESCRIPTION OF THE SAMPLE", "description")
    p.row("RATED POWER (kVA)", "kva", NUM, True, min=1, max=100000)
    p.row("RATED VOLTAGE HV (V)", "hv", NUM, True, min=1, max=1000000)
    p.row("RATED VOLTAGE LV (V)", "lv", NUM, True, min=1, max=1000000)
    p.row("HIGHEST VOLTAGE OF THE EQUIPMENT (kV)", "hv_max_kv", NUM, min=0, max=1200)
    p.row("BASIC INSULATION LEVELS (BIL)", "bil")
    p.row("HV LI / AC", "bil_hv")
    p.row("LV LI / AC", "bil_lv")
    p.row("IMPEDANCE VOLTAGE AT 75 °C / ...°C (dry type) (%)", "z_pct", NUM, True, min=0, max=100)
    p.row("NUMBER OF PHASES", "phases", NUM, choices=[1, 3])
    p.row("RATED FREQUENCY (Hz)", "freq", NUM, min=1, max=1000)
    p.row("VECTOR GROUP / POLARITY", "vector")
    p.row("ENERGY EFFICIENCY", "efficiency")
    p.row("TYPE OF COOLING", "cooling", choices=["ONAN", "ONAF", "OFAF", "AN", "AF"], other=True)
    p.row("NUMBER OF TAPS & PERCENTAGE", "taps")
    p.row("NO-LOAD LOSS AT RATED VOLTAGE AND AT RATED FREQUENCY (W)", "nll_guar", NUM, min=0, max=1e7, h=28)
    p.row("LOAD LOSS AT RATED CURRENT AT PRINCIPAL TAPPING AT 75 °C / ...°C (dry type) (W)", "ll_guar", NUM, min=0, max=1e7, h=28)
    p.row("MAXIMUM TOTAL LOSS AT 50% RATED LOAD (W)", "loss50", NUM, min=0, max=1e7)
    p.row("MAXIMUM TOTAL LOSS AT 100% RATED LOAD (W)", "loss100", NUM, min=0, max=1e7)
    p.row("GUARANTEED NOISE LEVEL LIMIT", "noise")
    p.row("VOLUME OF OIL (litres)", "oil_l")
    p.row("MONTH & YEAR OF MANUFACTURE", "mfg")
    p.signatures([("CUSTOMER'S SIGNATURE WITH DATE (sheet 1 of 2)", "sig.customer_1")])
    p.section_head("WINDING DETAILS (sheet 2 of 2)")
    p.row("Material: Copper / Aluminium", "material", choices=["Copper", "Aluminium"])
    p.row("Coil Shape: Circular / Non-circular", "coil", choices=["Circular", "Non-circular"], other=True)
    p.row("Core: CRGO / Amorphous", "core", choices=["CRGO", "Amorphous"], other=True)
    p.row("L.V. WINDING", "lv_winding")
    p.row("H.V. WINDING", "hv_winding")
    p.table("tests", [dict(label="Sl.No.", type=TXT, w=7), dict(label="DETAILS OF TESTS REQUIRED", type=TXT, w=40), dict(label="IN ACCORDANCE WITH", type=TXT, w=20)],
            row_labels=[str(n) for n in range(1, 13)], take=[1], rows_as="values",
            share=[dict(field="tests_std", take=[0, 2], rows_as="dict")])
    p.row("CUSTOMER'S INSTRUCTIONS / OTHER INFORMATION IF ANY", "instructions", h=30)
    p.section_head("Additional data")
    p.row("Class of Insulation (in case of Dry type transformer)", "insulation_class")
    p.row("Tank Construction: Plain / Corrugated", "tank", choices=["Plain", "Corrugated"], other=True)
    p.row("Other construction details", "construction")
    p.grid("Guaranteed Maximum temperature rise limits (if any)", ["Top oil (K)", "Winding (K)"], [("Limit", ["limits.oil", "limits.wdg"], dict(min=0, max=200))])
    p.signatures([("CUSTOMER'S SIGNATURE WITH DATE (sheet 2 of 2)", "sig.customer_2")])
    p.footer(f"{FOOTER}   SECTION : 12   ISSUE NO.: 4   DATE: 01.04.2018   REVISION NO.: 00")
    return p.mapping()


def losses():
    p = Paper("losses", "LS2", "CPRI SCL Transformer Loss Measurement v2.17", "SHORT CIRCUIT LABORATORY", landscape=True)
    s, m = ids("losses")
    p.pair(("Series No :", s, TXT), ("Sample No :", m, TXT))
    p.row("Sample Details :", "sample_details")
    p.row("EEL limits", "eel_limits")
    V = lambda lab: dict(label=lab)
    p.table("nl_meas", [dict(label="No Load Loss", type=TXT), V("V"), V("I"), V("P"), V("f")], caption="No Load Loss", row_labels=["BT", "AT"],
            take=[0, 1, 2, 4], share=[dict(field="nll_bt", take=[0, 3], rows_as="row", key="BT"), dict(field="nll_at", take=[0, 3], rows_as="row", key="AT")])
    p.table("ll50_meas", [V("V (50%)"), V("I (50%)"), V("P (50%)"), V("f (50%)")], caption="50% Load Loss", rows=1, rows_as="first")
    p.table("lv_res", [dict(label="LV Resistance", type=TXT), V("LVR1"), V("LVR2"), V("LVR3"), V("Temp")], caption="LV Resistance (milliOhm)",
            row_labels=["BT", "AT"], rows_as="dict")
    TAPS = ["NTBT", "NTAT", "HTBT", "HTAT", "LTBT", "LTAT"]
    p.table("ll_meas", [dict(label="Load Loss", type=TXT), V("V1"), V("V2"), V("V3"), V("I1"), V("I2"), V("I3"), V("P1"), V("P2"), V("P3"), V("f ")],
            caption="Load Loss Measurement", row_labels=TAPS)
    p.table("hv_res", [dict(label="HV Resistance", type=TXT), V("HVR1"), V("HVR2"), V("HVR3")], caption="HV Resistance (Ohm)", row_labels=TAPS, rows_as="dict")
    p.table("rows", [dict(label="Tap", type=TXT), V("%Z-75deg"), V("%X-50Hz"), V("%X Change"), V("Rhv-Ohm"), V("Rlv-mOhm"), V("100% LoadLoss"), V("X/R-75deg"),
                     V("Isc-pk"), V("Isc-rms"), V("Stray Loss"), V("50% LoadLoss"), V("50% TotalLoss"), V("100% TotalLoss")],
            caption="Load Loss Results (Ref Temp : 75 degC)", row_labels=TAPS, required=True)
    p.signatures([("TEST ENGINEER", "sig.engineer")])
    return p.mapping(consts=[dict(field="cols", by="const", value=["tap", "z", "x", "xchg", "rhv", "rlv", "ll100", "xr", "ipk", "irms", "stray", "ll50", "t50", "t100"])])


def loss_header(p, section):
    """The header of the LOG-SHEET FOR LOSS MEASUREMENT ON TRANSFORMER (shared by the resistance and no-load parts)."""
    s, m = ids(section)
    p.pair(("Test Series No", s, TXT), ("Before STC test : Date", "date_bt", DATE))
    p.pair(("Sample no", m, TXT), ("After STC test : Date", "date_at", DATE))
    p.pair(("Serial no.", "serial", TXT), ("Rated kVA", "kva", NUM))
    p.pair(("Customer", "customer", TXT), ("Winding Material: Copper / Aluminium", "material", TXT, dict(choices=["Copper", "Aluminium"])))
    p.pair(("Manufacturer", "manufacturer", TXT), ("Rated voltage (HV / LV)", "rated_v", TXT))
    p.gap()


def resistance():
    p = Paper("resistance", "RS2", "LOG-SHEET FOR LOSS MEASUREMENT ON TRANSFORMER: Measurement of Resistance", "SHORT CIRCUIT LABORATORY")
    loss_header(p, "resistance")
    p.grid("Measurement of Resistance", ["Before STC test", "After STC test"],
           [("Temperature top oil - °C", ["oil_top[0]", "oil_top[1]"], dict(min=-20, max=150)), ("Temperature bottom oil - °C", ["oil_bot[0]", "oil_bot[1]"], dict(min=-20, max=150))])
    hv = [dict(label="Tap Pos.", type=TXT), dict(label="Voltage ratio", type=TXT), dict(group=["1U1V", "1V1W", "1W1U"], title="Before STC Test"),
          dict(group=["1U1V ", "1V1W ", "1W1U "], title="After STC Test")]
    p.table("hv", hv, caption="Resistance of H.V. winding in Ohms / milli-Ohms / micro-Ohms", row_labels=["N", "H", "L"], take=[0, 2, 3], rows_as="dict",
            required=True, share=[dict(field="hv_ratio", take=[0, 1], rows_as="dict")])
    lv = [dict(group=["2u2v", "2v2w", "2w2u"], title="Before STC Test"), dict(group=["2u2v ", "2v2w ", "2w2u "], title="After STC Test")]
    p.table("lv", lv, caption="Resistance of L.V. winding in Ohms / milli-Ohms / micro-Ohms", rows=3, rows_as="first", required=True)
    p.signatures([("Customer's Signature", "sig.customer"), ("Test Engineer", "sig.engineer")])
    p.footer(f"APPROVED BY:          {FOOTER}   SECTION : 56   PAGE NO. 1 OF 1   ISSUE NO. 01   REVISION NO.: 00   DATE : 01.06.2019")
    return p.mapping()


def noload():
    p = Paper("noload", "NL2", "LOG-SHEET FOR LOSS MEASUREMENT ON TRANSFORMER: No-load loss and current", "SHORT CIRCUIT LABORATORY")
    loss_header(p, "noload")
    avg = lambda a, b: f'=IF(COUNT({{{a}}}:{{{b}}})=0,"",AVERAGE({{{a}}}:{{{b}}}))'
    cols = [dict(label="Level", type=TXT), dict(group=["V12", "V23", "V31"], title="Applied voltage (V)"), dict(label="Avg V", calc=avg("V12", "V31"), read=True),
            dict(group=["I1", "I2", "I3"], title="No-load current (A)"), dict(label="Avg I", calc=avg("I1", "I3"), read=True),
            dict(group=["W1", "W2", "W3"], title="Watts (W)"), dict(label="Total W", calc='=IF(COUNT({W1}:{W3})=0,"",SUM({W1}:{W3}))', read=True),
            dict(label="Freq -Hz", min=40, max=70), dict(label="Vrr")]
    p.table("rows", cols, caption="Measurement of No-load loss", row_labels=["BT", "AT", "90%", "110%", "112.5%"], required=True)
    p.section_head("No Load Current at 112.5 % Rated Voltage")
    p.grid("", ["At 100 % voltage", "At 112.5 % voltage"], [
        ("Voltage (V)", ["v100", "v1125"], dict(min=0, max=1e6)),
        ("Measured Current (A)", ["i100", "i1125"], dict(type=TXT)),
        ("Permissible Value & percentage", ["perm100", "perm1125"], dict(type=TXT)),
        ("Observation", ["obs100", "obs1125"], dict(type=TXT))])
    p.row("Remarks", "remarks")
    p.grid("Measurement of 50% Load loss", ["Voltage (V)", "Current (A)", "Watts (W)", "Freq. Hz"], [("50% load", ["ll50.v", "ll50.i", "ll50.w", "ll50.f"])], label_cols=4)
    lcols = [dict(label="Tap pos.", type=TXT), dict(group=["V12 ", "V23 ", "V31 "], title="Voltage (V)"), dict(label="Avg V ", calc=avg("V12 ", "V31 "), read=True),
             dict(group=["I1 ", "I2 ", "I3 "], title="Current (A)"), dict(label="Avg I ", calc=avg("I1 ", "I3 "), read=True),
             dict(group=["W1 ", "W2 ", "W3 "], title="Watts (W)"), dict(label="Avg W ", calc=avg("W1 ", "W3 "), read=True), dict(label="Hz")]
    p.table("load_meas", lcols, caption="Measurement of Load loss", row_labels=["Nor. BT", "Nor. AT", "Hig. BT", "Hig. AT", "Low. BT", "Low. AT"])
    p.signatures([("Customer's Signature", "sig.customer"), ("Test Engineer", "sig.engineer")])
    p.footer(f"APPROVED BY:          {FOOTER}   SECTION : 56   PAGE NO. 1 OF 1   ISSUE NO. 01   REVISION NO.: 00   DATE : 01.06.2019")
    return p.mapping()


def routine():
    p = Paper("routine", "RT2", "Log sheet for routine tests on Transformers", "SHORT CIRCUIT LABORATORY")
    s, m = ids("routine")
    p.pair(("Test Series Number", s, TXT), ("Sample Number", m, TXT))
    p.row("Customer / Manufacturer", "customer")
    p.grid("Date", ["BT", "AT"], [("Date of test", ["date_bt", "date_at"], dict(type=DATE))])
    p.row("Sample details", "sample_details")
    p.row("In accordance with (Customer's instructions / IEC / IS / ANSI)", "standard")
    p.row("Serial Number", "serial")
    p.row("Condition of the sample (New / Re-conditioned / After test / Good)", "condition", choices=["New", "Re-conditioned", "After test", "Good"], other=True)
    p.grid("Atmospheric conditions", ["BT", "AT"], [("Amb °C", ["amb[0]", "amb[1]"], dict(min=-20, max=60)), ("RH - %", ["rh[0]", "rh[1]"], dict(min=0, max=100))])
    p.row("Type", "type")
    p.gap()
    p.text(f"A{p.r}", f"E{p.r}", "Description of test", "head"); p.text(f"F{p.r}", f"H{p.r}", "BT", "head"); p.text(f"I{p.r}", f"L{p.r}", "AT", "head"); p.r += 1
    p.bt_at("Vector Group", [("Vector Group", "vector", "vector_at", TXT)])
    p.bt_at("I/R test (GΩ)", [("H.V. to Earth", "ir.HV-Earth[0]", "ir.HV-Earth[1]", NUM, dict(min=0, max=1e6)),
                              ("L.V. to Earth", "ir.LV-Earth[0]", "ir.LV-Earth[1]", NUM, dict(min=0, max=1e6)),
                              ("H.V. to L.V.", "ir.HV-LV[0]", "ir.HV-LV[1]", NUM, dict(min=0, max=1e6))])
    p.bt_at("Induced over voltage test", [("Voltage - V", "induced.v", "induced.v_at", NUM), ("Current - A", "induced.i[0]", "induced.i[1]", NUM),
                                          ("Frequency - Hz", "induced.f", "induced.f_at", NUM, dict(min=40, max=500)), ("Duration - Seconds", "induced.t", "induced.t_at", NUM),
                                          ("Observation", "induced.obs", "induced.obs_at", TXT)])
    p.bt_at("High voltage power frequency test", [("H.V. test voltage - kV", "hvac.kv", "hvac.kv_at", NUM), ("H.V. duration - seconds", "hvac.t", "hvac.t_at", NUM),
                                                  ("H.V. current - mA", "hvac.ma", "hvac.ma_at", NUM), ("H.V. observation", "hvac.obs", "hvac.obs_at", TXT),
                                                  ("L.V. test voltage - kV", "lvac.kv", "lvac.kv_at", NUM), ("L.V. duration - seconds", "lvac.t", "lvac.t_at", NUM),
                                                  ("L.V. current - mA", "lvac.ma", "lvac.ma_at", NUM), ("L.V. observation", "lvac.obs", "lvac.obs_at", TXT)])
    ratio = [dict(label="Tap number", type=TXT), dict(group=["A(U)", "B(V)", "C(W)"], title="BT"), dict(group=["A(U) ", "B(V) ", "C(W) "], title="AT")]
    p.table("ratio.BT", ratio, caption="Voltage ratio", row_labels=[str(n) for n in range(1, 8)], pick=1, share=[dict(field="ratio.AT", pick=2)])
    p.signatures([("Customer's Signature", "sig.customer"), ("Tested by", "sig.tested_by"), ("Test Engineer", "sig.engineer")])
    p.instruments(["I/R test kit", "DTM / RH Indicator", "Turns ratio meter", "H.V. Test kit", "DVDF Test kit", "Time interval meter", "DMM (1)", "DMM (2)"])
    p.footer(f"APPROVED BY:          {FOOTER}   SECTION : 45   PAGE NO.: 1 of 1   ISSUE NO.: 2   REVISION No.: 00   DATE : 01-08-2014")
    return p.mapping()


def sc():
    p = Paper("sc", "SC2", "LOG-SHEET FOR SHORT CIRCUIT TEST ON TRANSFORMERS", "SHORT CIRCUIT LABORATORY")
    s, m = ids("sc")
    p.pair(("Test Series No", s, TXT), ("CPRI Sample Code No.", m, TXT))
    p.pair(("Condition of the transformer before SC test", "condition", TXT), ("Date of Test", "date", DATE))
    p.row("Other details (rating, bay, setting)", "notes")
    p.table("required", [dict(label="Short-circuit current required on LV side", type=TXT), dict(label="kA rms", min=0, max=500), dict(label="kA peak", min=0, max=1500)],
            row_labels=["1) Normal tap", "2) Highest tap", "3) Lowest tap"], rows_as="dict", keys_as={"1) Normal tap": "NT", "2) Highest tap": "HT", "3) Lowest tap": "LT"}, required=True)
    rms = '=IF(COUNT({RMS (U)}:{RMS (W)})=0,"",AVERAGE({RMS (U)}:{RMS (W)}))'
    cols = [dict(label="Osc. no.", type=TXT), dict(label="Dial"), dict(group=["U (kV)", "V (kV)", "W (kV)"], title="Voltage Applied"),
            dict(label="Max. Peak on / Tap", type=TXT, choices=["NT", "HT", "LT"], other=True), dict(label="Peak (kA)"),
            dict(group=["RMS (U)", "RMS (V)", "RMS (W)"], title="S.C. Current (kA)"), dict(label="RMS (Avg)", calc=rms, read=True), dict(label="Duration in (s)", min=0, max=10),
            dict(label="S.E.", type=TXT), dict(label="Remarks (calibration / thermal)", type=TXT, blank="", choices=["calibration", "thermal"], other=True, w=18)]
    p.table("shots", cols, caption="S.C. Test results", rows=20, required=True, take=[0, 3, 1, 4, [5, 0], [5, 1], [5, 2], 6, 7, 9],
            share=[dict(field="shots_extra", take=[0, [2, 0], [2, 1], [2, 2], 8])])
    p.row("During test", "during")
    p.row("After test", "after")
    p.section_head("Physical inspection of transformer after untanking")
    p.row("Finding after untanking (summary)", "inspection")
    p.row("Conductor, Core & clampings", "insp_core")
    p.row("Spacers / Support blocks", "insp_spacers")
    p.row("Oil", "insp_oil")
    p.signatures([("Customer's Signature", "sig.customer"), ("Test Engineer", "sig.engineer")])
    p.footer(f"APPROVED BY          {FOOTER}   SECTION : 55   PAGE NO. 1 OF 1   ISSUE NO.: 04   REVISION NO. : 00   DATE : 01.06.19")
    return p.mapping()


def temp():
    p = Paper("temp", "TR2", "Log Sheet for temperature - rise test on Oil immersed / Dry type transformers", "SHORT CIRCUIT LABORATORY", landscape=True)
    s, m = ids("temp")
    p.pair(("Test Series Number", s, TXT), ("Sample Number", m, TXT))
    p.row("Name of the Customer / Manufacturer", "customer")
    p.pair(("Rating: kVA", "kva", NUM), ("No. of Phases", "phases", NUM, dict(choices=[1, 3])))
    p.pair(("Voltage Class: HV (V)", "hv", NUM), ("Rated HV Current (A)", "i_hv", NUM))
    p.pair(("Voltage Class: LV (V)", "lv", NUM), ("Rated LV Current (A)", "i_lv", NUM))
    p.pair(("Type: Oil Cooled / Dry Type", "type", TXT, dict(choices=["Oil Cooled", "Dry Type"])), ("In Accordance with (IS / IEC / Other)", "standard", TXT))
    p.pair(("Customers Instructions", "instructions", TXT), ("Condition of Sample", "condition", TXT))
    p.row("Test Date(s)", "dates")
    p.row("Source Utilized for Temperature Rise Test", "source", choices=["Single Phase Source", "Three Phase Source"])
    p.row("Test Method Employed: Short Circuit Method", "method", choices=["No Load Run (in case of Dry Type)", "Load Run (in case of Dry type)", "Total loss injection"], other=True)
    p.row("Connections (supply side connected to 3 phase AC supply; other side shorted)", "connections")
    p.section_head("Step 1")
    p.row("Oil Cooled: Total loss injection (No load loss + Full load loss) at °C up to steady state", "inj_temp", NUM, min=0, max=200)
    p.pair(("NLL (W)", "nll", NUM, dict(min=0, max=1e7)), ("FLL (W)", "fll", NUM, dict(min=0, max=1e7)))
    p.row("Total Loss (W)", "total", NUM, min=0, max=1e7)
    p.row("Dry Type: Applying Rated No-load Voltage on LV / HV side", "dry_note")
    p.pair(("Number of Taps", "n_taps", NUM), ("Tap Position for TR Test", "tap", TXT, dict(choices=["NT", "HT", "LT"], other=True)))
    p.row("Current at Selected Tap (A)", "current", NUM, min=0, max=1e6)
    p.pair(("HV winding Resistance (Ω or mΩ)", "rhv_cold", NUM), ("LV winding Resistance (mΩ or µΩ)", "rlv_cold", NUM))
    p.row("Ambient during Cold Resistance Measurement (°C)", "amb_cold", NUM, min=-20, max=60)
    amb = '=IF(COUNT({Ambient 1}:{Ambient 3})=0,"",AVERAGE({Ambient 1}:{Ambient 3}))'
    rise = '=IF(OR({Top oil}="",{Average Ambient Temp (°C)}=""),"",{Top oil}-{Average Ambient Temp (°C)})'
    cols = [dict(label="Hr"), dict(label="Time of starting test (AM/PM)", type=TXT, w=12), dict(label="Applied Total Losses NLV / FLC (W)", w=12),
            dict(group=["Top oil", "Bottom oil"], title="Temperature on °C for steady state prediction"),
            dict(group=["Ambient 1", "Ambient 2", "Ambient 3"], title="Ambient Temperature (°C)"),
            dict(label="Average Ambient Temp (°C)", calc=amb, w=12), dict(label="Top oil temperature Rise (°C)", calc=rise, w=12)]
    p.table("hours", cols, caption="Readings during Temperature Rise Test", row_labels=list(range(17)), required=True,
            take=[0, [3, 0], [3, 1], [4, 0], [4, 1], [4, 2]], share=[dict(field="hours_log", take=[0, 1, 2])])
    p.row("Observation / Result: Top oil Temperature - Rise (K)", "oil_rise_reported", NUM, min=0, max=200)
    p.signatures([("Customer Signature", "sig.customer"), ("Tested by", "sig.tested_by"), ("Test Engineer", "sig.engineer")])
    p.section_head("Step 2 (sheet 2 of 2)")
    p.row("After top oil reached steady state temperature, injection of rated current (A) on supply side for one hour", "rated_inj_a", NUM, h=28)
    p.row("Measurement of winding resistance on HV / LV side", "hot_side")
    p.pair(("Winding material: Copper / Aluminium", "material", TXT, dict(choices=["Copper", "Aluminium"])),
           ("Thermal Co-efficient: 225 / 235 / 234.5", "material_k", NUM, dict(choices=[225, 235, 234.5])))
    p.row("Correction Factor (if applicable)", "corr_written", NUM)
    p.pair(("Time of Shutdown", "t_shutdown", TXT), ("Ambient at shut-down (°C)", "amb_sd", NUM, dict(min=-20, max=60)))
    tg = [dict(label="Reading", type=TXT), dict(label="Time in Sec./min.", type=TXT), dict(label="Resistance in Ω / mΩ")]
    p.tgrid("hv_hot_readings", tg, 10, row_labels=[str(n) for n in range(1, 11)])
    p.row("HV hot resistance at shut-down (Ω, extrapolated)", "rhv_hot", NUM)
    p.row("Correction used in the winding-rise formula (K)", "corr", NUM)
    p.row("Temperature Rise of HV winding (K)", "hv_rise", NUM, min=0, max=200)
    p.row("Observations / Result & Remarks (HV)", "hv_obs")
    p.section_head("Step 3: after the measurement of resistance on HV, rated current injected for one more hour before taking the resistance of the other winding")
    p.row("Correction Factor (if applicable) (LV)", "corr_lv", NUM)
    p.row("Time of Shutdown (LV)", "t_shutdown_lv")
    p.tgrid("lv_hot_readings", [dict(label="Reading ", type=TXT), dict(label="Time in Sec./min. ", type=TXT), dict(label="Resistance in Ω / mΩ ")], 10,
            row_labels=[str(n) for n in range(1, 11)])
    p.row("LV hot resistance at shut-down (mΩ, extrapolated)", "rlv_hot", NUM)
    p.row("Temperature Rise of LV winding (K)", "lv_rise", NUM, min=0, max=200)
    p.row("Observations / Result & Remarks (LV)", "lv_obs")
    p.instruments(["Power Analyzer", "Resistance Meter", "Timer", "DTM", "Data Logger"])
    p.signatures([("Customer Signature", "sig.customer_2"), ("Test Engineer", "sig.engineer_2")])
    p.footer(f"Approved BY          {FOOTER}   SECTION : 44   PAGE NO. 1 & 2 of 2   ISSUE NO. : 2   REVISION NO. : 00   DATE : 01-08-2018")
    return p.mapping()


def pressure():
    p = Paper("pressure", "PR2", "Log sheet for Air Pressure Tests and Oil Leakage Test", "SHORT CIRCUIT LABORATORY", landscape=True)
    s, m = ids("pressure")
    p.pair(("Test Series Number", s, TXT), ("Customer / Manufacturer", "customer", TXT))
    p.pair(("Rating: kVA", "kva", NUM), ("Phase: 1 Phase / 3 Phase", "phase", TXT, dict(choices=["1 Phase", "3 Phase"])))
    p.pair(("Voltage Class: HV (V)", "hv", NUM), ("Tank Construction: Sealed / Non-Sealed", "tank_seal", TXT, dict(choices=["Sealed", "Non-Sealed"])))
    p.pair(("Voltage Class: LV (V)", "lv", NUM), ("Tank Construction: Corrugated / Other", "tank_type", TXT, dict(choices=["Corrugated", "Other"], other=True)))
    p.pair(("In Accordance with (IS / IEC / Other)", "standard", TXT), ("Customers Instructions", "instructions", TXT))
    p.section_head("PRESSURE TEST(S)")
    p.para("Test Procedure: The tank shall be fixed with all fittings including bushings in position and shall be subjected to air pressure / vacuum of "
           "specified value above atmospheric pressure. The permanent deflection of flat plate, after air pressure / vacuum has been released, shall be "
           "measured and reported.")
    p.pair(("Condition of sample", "condition", TXT), ("CPRI Sample code", m, TXT))
    p.pair(("Sl. No.", "sl_no", TXT), ("RH %", "rh", NUM, dict(min=0, max=100)))
    p.pair(("Amb °C", "amb", NUM, dict(min=-20, max=60)), ("Pressure (A) (kPa)", "atm_kpa", NUM, dict(min=0, max=200)))
    p.section_head("Routine Test")
    p.pair(("Date", "routine.date", DATE), ("Applied Air Pressure (15 kPa / 35 kPa / 80 kPa)", "routine.kpa", NUM, dict(choices=[15, 35, 80], other=True)))
    p.pair(("Pressure Applied through", "routine.through", TXT), ("Test Duration (Minutes)", "routine.min", NUM, dict(min=0, max=10000)))
    p.row("Remarks / observation", "routine.obs")
    p.section_head("Type Test")
    p.row("Date(s)", "type.date")
    p.grid("Applied Test Parameter", ["Air (kPa)", "Vacuum (mmHg)"], [
        ("Applied Quantity of Air / Vacuum (25 / 80 / 100 kPa; 250 / 500 / 760 mmHg)", ["type.pressure.kpa", "type.vacuum.mmhg"]),
        ("Air / Vacuum Applied through", ["type.pressure.through", "type.vacuum.through"], dict(type=TXT)),
        ("Test Duration (Minutes)", ["type.pressure.min", "type.vacuum.min"], dict(min=0, max=10000)),
        ("Permanent maximum deflection of flat Plates (mm)", ["type.pressure.max", "type.vacuum.max"], dict(min=0, max=1000)),
        ("Remarks / observations", ["type.pressure.obs", "type.vacuum.obs"], dict(type=TXT))])
    p.row("Flat plate length (m) (≤ 750 mm / 751 - 1250 mm / 1251 - 1750 mm / ≥ 1751 mm)", "plate_m", NUM, min=0, max=20)
    defl = '=IF(OR({Final value (mm)}="",{Initial value (mm)}=""),"",ABS({Final value (mm)}-{Initial value (mm)}))'
    tg = lambda sfx: [dict(label="Reference Point" + sfx, type=TXT), dict(label="Test Description" + sfx, type=TXT), dict(label="Initial value (mm)" + sfx),
                      dict(label="Final value (mm)" + sfx), dict(label="Deflection (mm)" + sfx, calc=defl.replace("(mm)}", "(mm)" + sfx + "}"))]
    p.tgrid("type.pressure.pts", tg(""), 6, row_labels=[str(n) for n in range(1, 7)], caption="Noting during test(s): Pressure test", take=[2, 3],
            share=[dict(field="type.pressure.pts_desc", take=[0, 1], rows_as="dict")])
    p.tgrid("type.vacuum.pts", tg(" "), 6, row_labels=[str(n) for n in range(1, 7)], caption="Noting during test(s): Vacuum test", take=[2, 3],
            share=[dict(field="type.vacuum.pts_desc", take=[0, 1], rows_as="dict")])
    p.section_head("OIL LEAKAGE TEST")
    p.para("Test Procedure: The assembled transformer with all fittings including bushings in position shall be subjected to a pressure equivalent "
           "to twice the normal head measured at the base.", h=28)
    p.pair(("Condition of sample (oil leakage)", "leak.condition", TXT), ("Date (oil leakage)", "leak.date", DATE))
    p.pair(("Sl. No. (oil leakage)", "leak.sl_no", TXT), ("RH % (oil leakage)", "leak.rh", NUM, dict(min=0, max=100)))
    p.pair(("Amb °C (oil leakage)", "leak.amb", NUM, dict(min=-20, max=60)), ("Pressure (A) (kPa) (oil leakage)", "leak.atm_kpa", NUM))
    p.row("Sample & Test Description", "leak.desc")
    p.pair(("Head pressure description & value in kPa", "leak.head_kpa", NUM), ("Measured / Calculated Value at base of the tank - kPa(g)", "leak.base_kpa", NUM))
    p.pair(("Reading in the Gauge fixed at top / bottom - kPa(g)", "leak.gauge", NUM), ("Test pressure at top / bottom of the tank (kPa)", "leak.kpa", NUM))
    p.pair(("Air Applied through", "leak.through", TXT), ("Test Duration (Hrs) (8 hrs / 6 hrs / Specific)", "leak.hrs", NUM, dict(choices=[8, 6], other=True)))
    p.row("Remarks / observations (oil leakage)", "leak.obs")
    p.instruments(["Digital Barometer", "RH / Temp Indicator", "Timer", "Pressure gauge", "Digital Vernier caliper"])
    p.signatures([("Tested by", "sig.tested_by"), ("Test Engineer", "sig.engineer")])
    p.footer("APPROVED BY          DOCUMENT: FORMS & FORMATS   SECTION : 58   PAGE NO: 1 of 1   ISSUE NO.: 3   REVISION NO.:   DATE : 11.07.16")
    return p.mapping()


BUILD = dict(work=work, proforma=proforma, losses=losses, resistance=resistance, noload=noload, routine=routine, sc=sc, temp=temp, pressure=pressure)


def paper(section): return BUILD[section]()
