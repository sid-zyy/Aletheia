"""Excel extraction with changeable templates (docs/NEXT_STEPS.md section 5).

A template is data, not code: a JSON mapping stored in the database. When the lab changes a sheet, an administrator updates
the mapping and the Python does not change. One mapping does two jobs:

* read a filled sheet: every mapped value comes back with the cell it was read from and a status, so the tester (and later
  the verifier) can see exactly where each number came from;
* write a blank sheet (and fill one from stored data), so testers always start from the current layout, with named cells.

Mapping (one sheet):

    {"section": "noload", "title": "Losses logsheet (no-load)",
     "fingerprint": {"contains": "Aletheia template noload", "within": "A1:L3"},
     "fields": [
       {"field": "v100", "label": "Rated voltage V (100%)", "cell": "C5", "name": "NL_V100", "type": "number", "required": true},
       {"field": "@ids.noload[0]", "label": "Test series no.", "cell": "C3", "name": "NL_SERIES", "type": "text"},
       {"field": "rows", "type": "table", "at": "A9", "rows": 6, "required": true,
        "columns": [{"label": "Condition", "type": "text"}, {"group": ["V1", "V2", "V3"]}, {"label": "Avg V"}, ...]}]}

Where a value is looked for, in order (a field may restrict this with "by"): the workbook's defined name, the label (the
first cell after the label, skipping merged cells; "direction": "down" looks below), then the fixed cell. Labels match
after normalising case, spaces and punctuation, and fuzzily (renamed slightly) when no exact match exists; a label found
twice is reported as ambiguous instead of guessed.

Tables are found by their header labels anywhere on the sheet, so inserted rows or reordered columns do not break them.
Rows are read until the first completely blank row. Options: "rows_as": "list" (default) | "dict" (first column is the key) |
"values" (one column, a plain list) | "row" with "key" (one row picked by its first column); "pick": n returns only column n
of every row; "keys": [...] keeps only rows whose first column is listed.

Field paths are those of importers.flatten ("limits.oil", "amb[0]"); "@ids.<section>[n]" writes into the identifiers section.

Values are taken as logged (F5): a formula cell gives the value the lab's sheet shows. A formula with no saved value (the file
was never recalculated) is an error, never a guess. Dates become dd-mm-yyyy text. Decimal commas are converted only when the
template says so ("decimal": ","). Units are never guessed.
"""
import datetime as dt, difflib, io, re, zipfile
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries
from openpyxl.workbook.defined_name import DefinedName

MAX_ROWS = 2000


class TemplateError(ValueError):
    """A file or mapping problem the user can fix."""


# ------------------------------------------------------------------ opening a workbook
class Book:
    """A workbook opened twice: cached values (what the sheet shows) and formulas (to spot never-recalculated cells)."""
    def __init__(self, raw, name="upload.xlsx"):
        low = name.lower()
        if low.endswith(".xls") or raw[:4] == b"\xd0\xcf\x11\xe0":
            raise TemplateError("Old .xls workbooks cannot be read; open the file in Excel and save it as .xlsx")
        if not raw.startswith(b"PK"): raise TemplateError("This is not an Excel workbook (.xlsx)")
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if any(n.lower().endswith("vbaproject.bin") for n in z.namelist()) or low.endswith(".xlsm"):
                    raise TemplateError("Macro-enabled workbooks (.xlsm) are refused; save a copy as .xlsx without macros")
            self.v = load_workbook(io.BytesIO(raw), data_only=True)
            self.f = load_workbook(io.BytesIO(raw), data_only=False)
        except TemplateError: raise
        except Exception as e:  # noqa: BLE001 - zip / XML damage
            raise TemplateError(f"The workbook could not be opened ({type(e).__name__}); it may be damaged") from None
        self.names = {}
        for n, dn in self.v.defined_names.items():
            for title, coord in dn.destinations: self.names[n.lower()] = (title, coord.replace("$", ""))
        for ws in self.v.worksheets:  # names scoped to one sheet
            for n, dn in getattr(ws, "defined_names", {}).items():
                for title, coord in dn.destinations: self.names.setdefault(n.lower(), (title or ws.title, coord.replace("$", "")))

    def sheets(self, hidden=False):
        return [ws for ws in self.v.worksheets if hidden or ws.sheet_state == "visible"]


def norm(s): return re.sub(r"[^a-z0-9%]+", " ", str(s or "").lower()).strip()


class Sheet:
    """One worksheet with merged-cell awareness and a record of which cells the mapping used."""
    def __init__(self, book, ws):
        self.b, self.ws, self.wf = book, ws, book.f[ws.title]
        self.used = set()
        self.merged = {}
        for r in ws.merged_cells.ranges:
            c1, r1, c2, r2 = r.min_col, r.min_row, r.max_col, r.max_row
            for rr in range(r1, r2 + 1):
                for cc in range(c1, c2 + 1): self.merged[(rr, cc)] = (r1, c1, r2, c2)
        self._labels = None

    def top_left(self, r, c):
        m = self.merged.get((r, c)); return (m[0], m[1]) if m else (r, c)

    def raw(self, r, c):
        r, c = self.top_left(r, c); return self.ws.cell(r, c).value

    def formula_unsaved(self, r, c):
        r, c = self.top_left(r, c)
        f = self.wf.cell(r, c).value
        return isinstance(f, str) and f.startswith("=") and self.ws.cell(r, c).value is None

    def is_formula(self, r, c):
        r, c = self.top_left(r, c); f = self.wf.cell(r, c).value
        return isinstance(f, str) and f.startswith("=")

    def ref(self, r, c): return f"{self.ws.title}!{get_column_letter(c)}{r}"

    def labels(self):
        """Text cells by normalised text -> [(row, col)]."""
        if self._labels is None:
            self._labels = {}
            for row in self.ws.iter_rows(max_row=min(self.ws.max_row, MAX_ROWS)):
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.strip():
                        self._labels.setdefault(norm(cell.value), []).append((cell.row, cell.column))
        return self._labels

    def find_label(self, label, near=None):
        """(row, col) of the label, or raises LookupError('missing' | 'ambiguous') with detail."""
        L = self.labels(); key = norm(label)
        hits = L.get(key)
        if not hits:  # tolerate small renames ("Rated volt. (100%)" for "Rated voltage (100%)")
            best = difflib.get_close_matches(key, list(L), n=2, cutoff=0.86)
            if best: hits = L[best[0]]
            if len(best) == 2 and difflib.SequenceMatcher(None, key, best[1]).ratio() == difflib.SequenceMatcher(None, key, best[0]).ratio():
                raise LookupError("ambiguous", f"'{label}' is close to both '{best[0]}' and '{best[1]}'")
        if not hits: raise LookupError("missing", f"label '{label}' not found")
        if len(hits) > 1:
            if near:  # prefer the occurrence nearest the template's own cell
                hits = sorted(hits, key=lambda h: abs(h[0] - near[0]) + abs(h[1] - near[1]))
                if abs(hits[0][0] - near[0]) + abs(hits[0][1] - near[1]) < abs(hits[1][0] - near[0]) + abs(hits[1][1] - near[1]): return hits[0]
            raise LookupError("ambiguous", f"label '{label}' appears {len(hits)} times ({', '.join(self.ref(*h) for h in hits[:4])})")
        return hits[0]

    def after(self, r, c, direction="right"):
        """The value cell next to a label: past the label's merged area."""
        m = self.merged.get((r, c))
        if direction == "down": return ((m[2] if m else r) + 1, c)
        return (r, (m[3] if m else c) + 1)


def addr(cell):
    """'Sheet!C5' or 'C5' -> (sheet or None, row, col)."""
    sh, _, a = cell.rpartition("!")
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", a.strip())
    if not m: raise TemplateError(f"Not a cell reference: {cell}")
    return (sh.strip("'") or None), int(m.group(2)), column_index_from_string(m.group(1).upper())


# ------------------------------------------------------------------ values
def convert(v, typ, opts, sheet=None, rc=None):
    """Cell value -> (value, problem). Never invents a value: anything it cannot read as the declared type is a problem."""
    if isinstance(v, str): v = v.strip()
    if v is None or v == "": return (opts.get("blank", None), None)
    if typ in (None, "any"):
        if isinstance(v, (dt.datetime, dt.date)): return v.strftime("%d-%m-%Y"), None
        return v, None
    if typ == "number":
        if isinstance(v, bool): return None, f"expected a number, found {v}"
        if isinstance(v, (int, float)):
            if sheet is not None and opts.get("scale"): v = v * opts["scale"]
            return (int(v) if isinstance(v, float) and v.is_integer() and opts.get("int") else v), None
        s = str(v).replace("−", "-").replace(" ", "")
        if opts.get("decimal") == ",": s = s.replace(".", "").replace(",", ".")
        if re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", s):
            x = float(s); return (int(x) if x.is_integer() and "." not in s and "e" not in s.lower() else x), None
        return None, f"expected a number, found '{v}'" + (" (a decimal comma? the template does not allow it)" if re.fullmatch(r"[-+]?\d+,\d+", s) else "")
    if typ == "text":
        if isinstance(v, float) and v.is_integer(): v = int(v)
        if isinstance(v, (dt.datetime, dt.date)): return v.strftime("%d-%m-%Y"), None
        return str(v), None
    if typ == "date":
        if isinstance(v, (dt.datetime, dt.date)): return v.strftime("%d-%m-%Y"), None
        s = str(v)
        for f in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
            try: return dt.datetime.strptime(s, f).strftime("%d-%m-%Y"), None
            except ValueError: pass
        return s, None  # free-text dates ("09-11-2025 to 10-11-2025") are kept as written
    if typ == "bool":
        t = str(v).strip().lower()
        if t in ("yes", "y", "true", "1"): return True, None
        if t in ("no", "n", "false", "0"): return False, None
        return None, f"expected yes or no, found '{v}'"
    raise TemplateError(f"Unknown type '{typ}' in the template")


# ------------------------------------------------------------------ paths
_TOK = re.compile(r"\[(\d+)\]|([^.\[\]]+)")


def tokens(path):
    t = [int(i) if i != "" else k for i, k in _TOK.findall(str(path))]
    if not t: raise TemplateError(f"Empty field path in the template")
    return t


def put(root, path, value):
    toks = tokens(path); cur = root
    for i, t in enumerate(toks):
        last = i == len(toks) - 1
        nxt = value if last else ([] if isinstance(toks[i + 1], int) else {})
        if isinstance(t, int):
            if not isinstance(cur, list): raise TemplateError(f"Field path '{path}' mixes list positions and names")
            while len(cur) <= t: cur.append(None)
            if last or cur[t] is None: cur[t] = nxt
            cur = cur[t]
        else:
            if not isinstance(cur, dict): raise TemplateError(f"Field path '{path}' mixes list positions and names")
            if last or t not in cur: cur[t] = nxt
            cur = cur[t]


def get(root, path):
    cur = root
    for t in tokens(path):
        try: cur = cur[t]
        except (KeyError, IndexError, TypeError): return None
    return cur


# ------------------------------------------------------------------ fingerprint / detection
def matches(sheet, fp):
    """Does this worksheet carry the template's fingerprint?"""
    if not fp: return False
    if fp.get("sheet") and norm(fp["sheet"]) != norm(sheet.ws.title): return False
    if "contains" in fp or "equals" in fp:
        c1, r1, c2, r2 = range_boundaries(fp.get("within") or "A1:Z10")
        want = norm(fp.get("contains") or fp.get("equals"))
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                t = norm(sheet.ws.cell(r, c).value) if isinstance(sheet.ws.cell(r, c).value, str) else ""
                if t and ((want in t) if "contains" in fp else t == want): return True
        return False
    if "label" in fp:
        try: sheet.find_label(fp["label"]); return True
        except LookupError: return False
    return bool(fp.get("sheet"))


def detect(book, templates):
    """[(worksheet, template)] for every visible sheet that one of the templates recognises (first match wins)."""
    out = []
    for ws in book.sheets():
        sh = Sheet(book, ws)
        t = next((t for t in templates if matches(sh, t["mapping"].get("fingerprint"))), None)
        if t: out.append((ws, t))
    return out


# ------------------------------------------------------------------ extraction
def extract(book, mapping, ws=None):
    """Read one sheet with one mapping. Returns dict(section, data, ids, fields=[{field, value, cell, status, note}], errors,
    warnings, unmapped). Nothing is stored here; the caller shows the result and saves only on confirmation."""
    section = mapping.get("section") or "other"
    if ws is None:
        hits = [s for s in book.sheets() if matches(Sheet(book, s), mapping.get("fingerprint"))]
        ws = hits[0] if hits else (book.sheets() or [None])[0]
    if ws is None: raise TemplateError("The workbook has no visible sheet")
    sh = Sheet(book, ws)
    data, ids, fields, errors, warnings = {}, {}, [], [], []
    if ws.sheet_state != "visible": warnings.append(f"Sheet '{ws.title}' is hidden")
    for f in mapping.get("fields") or []:
        if f.get("type") == "table": res = read_table(sh, f, book)
        elif f.get("by") == "const": res = dict(field=f["field"], value=f.get("value"), cell=None, status="ok", note="fixed in the template")
        else: res = read_field(sh, f, book)
        fields.append(res)
        st = res["status"]
        if st in ("missing", "ambiguous", "type", "formula_unsaved", "not_found") and (f.get("required") or st != "missing"):
            errors.append(f"{f.get('label') or f['field']}: {res['note']}" + (f" ({res['cell']})" if res.get("cell") else ""))
        if st in ("ok", "formula", "missing", "hidden") and not (st == "missing" and f.get("required")):
            target = f["field"]
            if target.startswith("@ids."): put(ids, target[5:], res["value"])
            else: put(data, target, res["value"])
        if st == "hidden": warnings.append(f"{f.get('label') or f['field']}: read from a hidden row or column ({res['cell']})")
    unmapped = []
    for row in ws.iter_rows(max_row=min(ws.max_row, MAX_ROWS)):
        for cell in row:
            v = cell.value
            if v is None or (isinstance(v, str) and not v.strip()): continue
            if (cell.row, cell.column) in sh.used or isinstance(v, str) and (len(v) > 25 or not re.search(r"\d", v)): continue  # labels and notes
            unmapped.append(dict(cell=sh.ref(cell.row, cell.column), value=v if not isinstance(v, (dt.date, dt.datetime)) else v.isoformat()))
    if unmapped: warnings.append(f"{len(unmapped)} value cell{'s' if len(unmapped) > 1 else ''} outside the mapping were not read (first: {unmapped[0]['cell']})")
    return dict(section=section, sheet=ws.title, data=data, ids=ids, fields=fields, errors=errors, warnings=warnings, unmapped=unmapped[:50])


def locate(sh, f, book):
    """(row, col, how) of a single field's value cell, or raises LookupError. A name or fixed cell whose neighbour no
    longer reads as the field's label has drifted (rows inserted by a tool that does not move names): the label wins."""
    r, c, how = _locate(sh, f, book)
    if how in ("name", "cell") and f.get("label") and "label" in (f.get("by") or ["name", "label", "cell"]):
        left = sh.raw(r, c - 1) if c > 1 else None; up = sh.raw(r - 1, c) if r > 1 else None
        if norm(f["label"]) not in (norm(left), norm(up)):
            try:
                lr, lc = sh.find_label(f["label"]); sh.used.add((lr, lc))
                rr, cc = sh.after(lr, lc, f.get("direction", "right"))
                return rr, cc, "label (the " + how + " has moved away from its label)"
            except LookupError: pass
    return r, c, how


def _locate(sh, f, book):
    order = f.get("by") or ["name", "label", "cell"]
    order = [order] if isinstance(order, str) else order
    notes = []
    for how in order:
        if how == "name" and f.get("name"):
            hit = book.names.get(f["name"].lower())
            if hit:
                title, coord = hit
                if title and title != sh.ws.title: notes.append(f"name {f['name']} points to sheet '{title}'"); continue
                _, r, c = addr(coord.split(":")[0]); return r, c, "name"
            notes.append(f"name {f['name']} not defined")
        elif how == "label" and f.get("label"):
            near = addr(f["cell"])[1:] if f.get("cell") else None
            try:
                r, c = sh.find_label(f["label"], near=near); sh.used.add((r, c))
                rr, cc = sh.after(r, c, f.get("direction", "right"))
                if f.get("offset"): cc += int(f["offset"])
                return rr, cc, "label"
            except LookupError as e:
                if e.args[0] == "ambiguous": raise
                notes.append(e.args[1])
        elif how == "cell" and f.get("cell"):
            s, r, c = addr(f["cell"])
            if s and s != sh.ws.title: notes.append(f"cell {f['cell']} is on another sheet"); continue
            return r, c, "cell"
    raise LookupError("not_found", "; ".join(notes) or "no way to locate this value (give a name, label or cell)")


def read_field(sh, f, book):
    try: r, c, how = locate(sh, f, book)
    except LookupError as e:
        return dict(field=f["field"], value=None, cell=None, status="ambiguous" if e.args[0] == "ambiguous" else "not_found", note=e.args[1])
    sh.used.add(sh.top_left(r, c))
    if f.get("label") and c > 1 and norm(sh.raw(r, c - 1)) == norm(f["label"]): sh.used.add(sh.top_left(r, c - 1))  # its label
    ref = sh.ref(*sh.top_left(r, c))
    if sh.formula_unsaved(r, c):
        return dict(field=f["field"], value=None, cell=ref, status="formula_unsaved",
                    note="formula without a saved value: open the file in Excel, let it recalculate, save, and upload again")
    val, prob = convert(sh.raw(r, c), f.get("type"), f, sheet=sh, rc=(r, c))
    if prob: return dict(field=f["field"], value=None, cell=ref, status="type", note=prob, found=str(sh.raw(r, c)))
    hidden = sh.ws.row_dimensions[r].hidden or sh.ws.column_dimensions[get_column_letter(c)].hidden
    st = "missing" if val in (None, "") and sh.raw(r, c) in (None, "") else "hidden" if hidden else "formula" if sh.is_formula(r, c) else "ok"
    note = {"missing": "empty" + (" (required)" if f.get("required") else ", recorded as NA"), "formula": "formula: the value the sheet shows is taken as logged",
            "hidden": "hidden row or column"}.get(st, f"found by {how}")
    return dict(field=f["field"], value=val, cell=ref, status=st, note=note, by=how)


def col_specs(f):
    """Flatten the column specs: [(position in output, index in group or None, label, type, opts)]."""
    out = []
    for i, c in enumerate(f["columns"]):
        if "group" in c:
            for j, lab in enumerate(c["group"]): out.append((i, j, lab, c.get("type", f.get("cell_type", "number")), c))
        else: out.append((i, None, c["label"], c.get("type", f.get("cell_type", "number")), c))
    return out


def find_header(sh, f, specs):
    """Row and column of each header label. Headers may be split over two rows (a group label above V1, V2, V3)."""
    first = specs[0][2]
    try: r0, c0 = sh.find_label(first, near=addr(f["at"])[1:] if f.get("at") else None)
    except LookupError as e:
        if f.get("at"):
            _, r0, c0 = addr(f["at"])
            if norm(sh.raw(r0, c0)) != norm(first): raise LookupError(e.args[0], f"table header '{first}' not found") from None
        else: raise LookupError(e.args[0], f"table header '{first}': {e.args[1]}") from None
    cols = {}
    row_labels = {}
    for cc in range(1, sh.ws.max_column + 1):
        for rr in (r0, r0 + 1):
            v = sh.raw(rr, cc)
            if isinstance(v, str) and v.strip(): row_labels.setdefault(norm(v), []).append((rr, cc))
    hdr_bottom = r0
    for pos, j, lab, typ, c in specs:
        hits = row_labels.get(norm(lab))
        if not hits:
            best = difflib.get_close_matches(norm(lab), list(row_labels), n=1, cutoff=0.86)
            hits = row_labels.get(best[0]) if best else None
        if not hits: raise LookupError("missing", f"column '{lab}' not found next to header '{first}' ({sh.ref(r0, c0)})")
        hits = [h for h in hits if h[1] >= c0] or hits
        rr, cc = hits[0] if len(hits) == 1 else min(hits, key=lambda h: (h[1] - c0) if (h[1] not in cols.values()) else 10 ** 6)
        cols[(pos, j)] = cc; hdr_bottom = max(hdr_bottom, rr)
        sh.used.add((rr, cc))
    sh.used.add((r0, c0))
    return hdr_bottom, cols


def read_table(sh, f, book):
    specs = col_specs(f)
    try: hdr, cols = find_header(sh, f, specs)
    except LookupError as e:
        return dict(field=f["field"], value=None, cell=None, status="ambiguous" if e.args[0] == "ambiguous" else "not_found", note=e.args[1])
    rows, problems, first_ref, r = [], [], None, hdr + 1
    while r <= min(sh.ws.max_row, hdr + MAX_ROWS):
        cells = {k: (r, cc) for k, cc in cols.items()}
        raw = {k: sh.raw(*rc) for k, rc in cells.items()}
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in raw.values()): break
        if f.get("stop_label") and norm(raw.get((0, None))) == norm(f["stop_label"]): break
        out = []
        for i, c in enumerate(f["columns"]):
            if "group" in c:
                vals = []
                for j in range(len(c["group"])):
                    rc = cells[(i, j)]; sh.used.add(rc)
                    if sh.formula_unsaved(*rc): problems.append(f"{sh.ref(*rc)}: formula without a saved value")
                    v, p = convert(raw[(i, j)], c.get("type", f.get("cell_type", "number")), c)
                    if p: problems.append(f"{sh.ref(*rc)}: {p}")
                    vals.append(v)
                out.append(vals)
            else:
                rc = cells[(i, None)]; sh.used.add(rc)
                if sh.formula_unsaved(*rc): problems.append(f"{sh.ref(*rc)}: formula without a saved value")
                v, p = convert(raw[(i, None)], c.get("type", f.get("cell_type", "number")), c)
                if p: problems.append(f"{sh.ref(*rc)}: {p}")
                out.append(v)
        first_ref = first_ref or sh.ref(r, min(cols.values()))
        rows.append(out); r += 1
    ref = f"{first_ref}..{sh.ref(r - 1, max(cols.values()))}" if rows else sh.ref(hdr, min(cols.values()))
    if problems:
        return dict(field=f["field"], value=None, cell=ref, status="type", note="; ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""))
    if not rows:
        return dict(field=f["field"], value=None, cell=ref, status="missing", note="table is empty" + (" (required)" if f.get("required") else ""))
    if f.get("keys"): rows = [x for x in rows if x[0] in f["keys"]]
    how = f.get("rows_as", "list")
    if "pick" in f: val = [x[f["pick"]] for x in rows]
    elif how == "dict": val = {str(x[0]): (x[1] if len(x) == 2 else x[1:]) for x in rows}
    elif how == "values": val = [x[0] for x in rows]
    elif how == "row":
        hit = [x for x in rows if str(x[0]) == str(f.get("key"))]
        if not hit: return dict(field=f["field"], value=None, cell=ref, status="missing", note=f"no row '{f.get('key')}' in the table")
        val = hit[0][1] if len(hit[0]) == 2 else hit[0][1:]
    else: val = rows
    return dict(field=f["field"], value=val, cell=ref, status="ok", note=f"{len(rows)} row{'s' if len(rows) != 1 else ''}")


# ------------------------------------------------------------------ writing: blank sheets and filled sheets
THIN = Side(style="thin", color="9AA8BD")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD = PatternFill("solid", fgColor="DFE7F1")
INPUT = PatternFill("solid", fgColor="FFFBEA")


def draw(ws, mapping, data=None, ids=None, wb=None):
    """Lay out one sheet from its mapping (labels, input cells, named cells, table headers); fill it from data if given."""
    ws["A1"] = mapping.get("title") or mapping.get("section"); ws["A1"].font = Font(bold=True, size=13)
    fp = mapping.get("fingerprint") or {}
    if fp.get("contains"):
        ws["A2"] = f"CPRI Short Circuit Laboratory - form: {fp['contains']} (version {mapping.get('version', 1)}). Fill the yellow cells only; do not move or rename them."
        ws["A2"].font = Font(italic=True, size=9, color="56667F")
    ws.column_dimensions["A"].width = 30
    tables = {}
    for f in mapping.get("fields") or []:
        if f.get("by") == "const": continue
        if f.get("type") == "table": tables.setdefault(f["at"], []).append(f); continue
        _, r, c = addr(f["cell"])
        if f.get("label") and not ws.cell(r, c - 1).value:
            lc = ws.cell(r, c - 1, f["label"]); lc.alignment = Alignment(wrap_text=True, vertical="top")
        vc = ws.cell(r, c); vc.fill = INPUT; vc.border = BOX
        w = ws.column_dimensions[get_column_letter(c)].width or 0
        ws.column_dimensions[get_column_letter(c)].width = max(w, 24 if f.get("type") == "text" else 14)
        if data is not None or ids is not None:
            v = get(ids or {}, f["field"][5:]) if f["field"].startswith("@ids.") else get(data or {}, f["field"])
            if v is not None: vc.value = v if not isinstance(v, (list, dict)) else str(v)
            if f.get("type") == "text" and isinstance(vc.value, str): vc.number_format = "@"
        if f.get("name") and wb is not None:
            wb.defined_names[f["name"]] = DefinedName(f["name"], attr_text=f"'{ws.title}'!${get_column_letter(c)}${r}")
    for at, fs in tables.items(): draw_table(ws, at, fs, data)


def draw_table(ws, at, fs, data):
    """One table region (possibly read by several fields): headers once, then the rows of all its fields."""
    f0 = fs[0]; _, r0, c0 = addr(at); specs = col_specs(f0)
    two = any(cs.get("title") for *_, cs in specs)
    if f0.get("caption"): ws.cell(r0 - 1, c0, f0["caption"]).font = Font(bold=True)
    c, done = c0, set()
    for pos, j, lab, typ, cs in specs:
        hr = r0 + 1 if (two and j is not None) else r0
        cell = ws.cell(hr, c, lab); cell.font = Font(bold=True); cell.fill = HEAD; cell.border = BOX
        cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        if two and j is None: ws.merge_cells(start_row=r0, start_column=c, end_row=r0 + 1, end_column=c)
        if two and j == 0 and pos not in done:
            n = len(f0["columns"][pos]["group"]); done.add(pos)
            t = ws.cell(r0, c, cs.get("title") or ""); t.font = Font(bold=True); t.fill = HEAD; t.alignment = Alignment(horizontal="center")
            if n > 1: ws.merge_cells(start_row=r0, start_column=c, end_row=r0, end_column=c + n - 1)
        w = ws.column_dimensions[get_column_letter(c)].width or 0
        ws.column_dimensions[get_column_letter(c)].width = max(w, 12)
        c += 1
    first = r0 + (2 if two else 1)
    rows = []
    if data is not None:
        if any("pick" in f for f in fs):
            merged = {}
            for f in fs:
                for i, x in enumerate(get(data, f["field"]) or []): merged.setdefault(i, [None] * len(f0["columns"]))[f["pick"]] = x
            rows = [merged[i] for i in sorted(merged)]
        else:
            for f in fs: rows += table_rows(f, get(data, f["field"]))
    for i in range(max(max(f.get("rows", 5) for f in fs), len(rows))):
        out = rows[i] if i < len(rows) else None
        cc = c0
        for pos, j, lab, typ, cs in specs:
            cell = ws.cell(first + i, cc); cell.border = BOX; cell.fill = INPUT
            if out is not None:
                v = out[pos] if j is None else (out[pos][j] if isinstance(out[pos], list) and j < len(out[pos]) else None)
                if v is not None: cell.value = v
            cc += 1


def table_rows(f, val):
    """Stored value -> rows in the table's column order (the inverse of read_table)."""
    if val is None: return []
    how, wide = f.get("rows_as", "list"), len(f["columns"]) > 2
    if how == "dict": return [[k] + (list(v) if wide else [v]) for k, v in val.items()]
    if how == "values": return [[x] for x in val]
    if how == "row": return [[f.get("key")] + (list(val) if wide else [val])]
    return [list(x) for x in val]


def workbook(sheets):
    """[(mapping, data or None, ids or None)] -> .xlsx bytes, one sheet per mapping (blank when data is None)."""
    wb = Workbook(); wb.remove(wb.active)
    for mapping, data, ids in sheets:
        title = re.sub(r"[\\/*?:\[\]]", "", mapping.get("sheet_title") or mapping.get("title") or mapping.get("section") or "Sheet")[:31]
        n, base = 2, title
        while title in wb.sheetnames: title = f"{base[:28]} {n}"; n += 1
        draw(wb.create_sheet(title), mapping, data, ids, wb)
    out = io.BytesIO(); wb.save(out); return out.getvalue()


# ------------------------------------------------------------------ comparing template versions
def diff(a, b):
    """Field-level differences between two mappings (for the administrator's review before activating)."""
    fa = {f["field"]: f for f in a.get("fields") or []}; fb = {f["field"]: f for f in b.get("fields") or []}
    out = [dict(field=k, change="removed") for k in fa if k not in fb] + [dict(field=k, change="added") for k in fb if k not in fa]
    for k in fa.keys() & fb.keys():
        ch = {x: (fa[k].get(x), fb[k].get(x)) for x in set(fa[k]) | set(fb[k]) if fa[k].get(x) != fb[k].get(x)}
        if ch: out.append(dict(field=k, change="changed", what=ch))
    if a.get("fingerprint") != b.get("fingerprint"): out.append(dict(field="(fingerprint)", change="changed", what={"fingerprint": (a.get("fingerprint"), b.get("fingerprint"))}))
    return sorted(out, key=lambda x: x["field"])


def validate_mapping(m):
    """Problems in a mapping an administrator wrote, before it is saved."""
    err = []
    if not isinstance(m, dict): return ["The mapping must be a JSON object"]
    if not isinstance(m.get("fields"), list) or not m["fields"]: err.append("The mapping needs a list of fields")
    seen = set()
    for n, f in enumerate(m.get("fields") or [], 1):
        if not isinstance(f, dict) or not f.get("field"): err.append(f"Field {n}: needs a 'field' path"); continue
        try: tokens(f["field"].lstrip("@"))
        except TemplateError as e: err.append(f"Field {n}: {e}")
        if f["field"] in seen and "pick" not in f: err.append(f"Field {n}: '{f['field']}' is mapped twice")
        seen.add(f["field"])
        if f.get("type") == "table":
            if not f.get("columns"): err.append(f"Field {n} ({f['field']}): a table needs columns")
            for c in f.get("columns") or []:
                if not isinstance(c, dict) or not (c.get("label") or c.get("group")): err.append(f"Field {n} ({f['field']}): every column needs a label or a group of labels")
            if f.get("at"):
                try: addr(f["at"])
                except TemplateError as e: err.append(f"Field {n}: {e}")
        elif f.get("by") != "const":
            if not (f.get("cell") or f.get("label") or f.get("name")): err.append(f"Field {n} ({f['field']}): give a cell, a label or a defined name")
            if f.get("cell"):
                try: addr(f["cell"])
                except TemplateError as e: err.append(f"Field {n}: {e}")
            if f.get("type") not in (None, "any", "number", "text", "date", "bool"): err.append(f"Field {n}: unknown type '{f.get('type')}'")
    fp = m.get("fingerprint")
    if not isinstance(fp, dict) or not any(k in fp for k in ("contains", "equals", "label", "sheet")):
        err.append("The mapping needs a fingerprint (contains / equals / label / sheet) so uploads can be recognised")
    return err


def grid(raw, name="sample.xlsx", max_rows=60, max_cols=26):
    """Cells of each sheet for the administrator's click-to-bind view."""
    b = Book(raw, name); out = []
    for ws in b.sheets(hidden=True):
        sh = Sheet(b, ws)
        rows = []
        for r in range(1, min(ws.max_row, max_rows) + 1):
            row = []
            for c in range(1, min(ws.max_column, max_cols) + 1):
                v = ws.cell(r, c).value
                row.append(None if v is None else v.strftime("%d-%m-%Y") if isinstance(v, (dt.date, dt.datetime)) else v if isinstance(v, (int, float, str)) else str(v))
            rows.append(row)
        names = {n: coord for n, (t, coord) in b.names.items() if t == ws.title}
        out.append(dict(name=ws.title, hidden=ws.sheet_state != "visible", rows=rows, merged=[str(m) for m in ws.merged_cells.ranges], names=names,
                        formulas=[sh.ref(c.row, c.column).split("!")[1] for row in b.f[ws.title].iter_rows(max_row=max_rows, max_col=max_cols) for c in row
                                  if isinstance(c.value, str) and c.value.startswith("=")]))
    return out
