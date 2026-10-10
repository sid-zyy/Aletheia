# Aletheia - Automated Test Report Generation System

Web prototype for the CPRI Short Circuit Laboratory (Hackathon Track 3). It collects the customer request, work
instruction, proforma and seven lab log sheets from **spreadsheets, CSV files, existing databases, JSON or scans**,
validates them, stores them in a database and produces a printable, verifiable PDF test report.

This is the merged build: the dashboard, validation engine and report layout of the "updated UI" prototype, plus
scan evidence, optional AI reading, frozen report versions with QR verification and automated tests from
"Prototype 3", plus new CSV / Excel / database import.

## Install and run

    pip install -r requirements.txt
    python app.py                 # open http://localhost:5000

Python 3.10 or newer. Records are kept in `aletheia.db` next to `app.py` (set `ALETHEIA_DB` to use another file, `PORT` for another port).

Two-minute demo: **Try the demo data** -> **Run checks** -> **Generate report** -> enter a name -> **Approve and release**.
To show importing instead: **New request**, then drop `sample_data/AP_Transformers_25T1654.csv` (or `.xlsx`, or `_lab.db`) on the job page.
To show historical records: **Records & Search** -> **Import existing register** -> `sample_data/legacy_register.csv` (or `.db`).

## Workflow (matches the problem statement)

1. **Capture request** - "New request" form with ID format checks, or bulk-load an existing register.
2. **Import data** - drop a file on the job page. Data files are read; PDFs and images are kept as source documents.
3. **Validate** - 30 checks: arithmetic re-computation, cross-document ID consistency, IS 1180 limits, thin margins.
4. **Generate** - the PDF template is filled from the database and stored as a numbered, hashed version.
5. **Review and export** - preview, print, download, approve with the reviewer's name and employee ID (both required; printed on the report). Every step is in the job history.

Dashboard: pipeline counts, quality gate, charts against limits, search by series / sample / customer / rating, status filter.

## Importing data

| Source | How |
|---|---|
| CSV (`.csv`, `.tsv`; comma, semicolon or tab) | columns `section, field, value` |
| Excel (`.xlsx`) | one sheet with `section, field, value`, or one sheet per section with `field, value` |
| Existing database (SQLite `.db`) | any table with `section, field, value`, or one table per section with `field, value`. Opened read-only. |
| JSON | one object per section (the original format) |
| Scan or photo (`.pdf`, `.png`, `.jpg`, `.webp`) | stored with a SHA-256 fingerprint; type the values, or use "Scan" |

`section` is one of `request, proforma, work, losses, resistance, noload, routine, sc, temp, pressure, ids`.
`field` is a path: `kva`, `limits.oil`, `hours[0][1]` (dots for names, `[n]` for list positions, counting from 0).
`value` is read as a number when it looks like one; put it in double quotes to keep it as text (serial number `"1098"`).
An optional `series` column lets one file or database hold several jobs; rows for other series are skipped.

The easiest way to get the layout right: open any job and use **Download this job's data** (CSV, Excel, Database, JSON)
or the blank **CSV / Excel template** links. Whatever the app exports, it can import again unchanged.

Importing the same content twice into one job is refused. Importing or editing data sends the job back to
"Data imported", so the checks and the report are always redone on the current data.

**Existing registers** (Records & Search -> Import existing register): a CSV, Excel sheet or SQLite table with at least
`series` and `customer` columns (also read: `sample`, `rating`, `address`, `serial`, `tests`, `standard`, `witness`,
`conformity`; common header variants such as "Test Series No" or "Customer Name" are recognised). Each valid row becomes
a searchable record; invalid or duplicate rows are listed with the reason.

## Reading scans with AI (optional)

On a job, attach a scan, click **Scan**, say which document it is. The answer opens as an editable proposal
with uncertain fields highlighted. Nothing is saved until you review and save it. Without a reader configured, the
button explains that it is not set up; everything else works offline.

Choose one reader (PowerShell shown; set the variables in the same window before `python app.py`):

| Reader | Settings |
|---|---|
| Qwen on this computer (offline) via [Ollama](https://ollama.com) | `ollama pull qwen2.5vl:7b`, then `$env:AI_BASE_URL = "http://localhost:11434/v1"`, `$env:AI_MODEL = "qwen2.5vl:7b"` |
| Hosted Qwen or any OpenAI-compatible service (e.g. OpenRouter) | `$env:AI_BASE_URL = "https://openrouter.ai/api/v1"`, `$env:AI_MODEL = "qwen/qwen2.5-vl-72b-instruct"`, `$env:AI_API_KEY = "..."` |
| Google Gemini | `$env:GEMINI_API_KEY = "..."`, optionally `$env:GEMINI_MODEL` (default `gemini-3.8-flash`) |

`AI_BASE_URL` takes priority over Gemini. Optional: `AI_TIMEOUT` (seconds per request, default 300; a local model on a
laptop without a graphics card can take minutes per page), `ALETHEIA_DAILY_CALL_LIMIT` (default 15).
PDFs are sent to Gemini as they are; for OpenAI-compatible readers each page (up to 4) is converted to an image first.
Busy or rate-limited answers are retried automatically after 2, 5 and 10 seconds.

**Saved readings.** Every successful reading is stored in `ai_cache.db` (next to the database, kept when the job
database is deleted), keyed by the scan's SHA-256, the document type and the model. Reading the same scan again returns
the saved reading instantly, without contacting the AI, and says so. Tick "Read again" in the dialog to force a new
reading. For a demo, read each scan once beforehand; on stage the readings then work offline.

**Tested with stand-ins only** - requests, retries, PDF conversion and the cache are covered by tests, but no live
model has been run yet. Check that sending lab records to an outside service is acceptable before using it on real data.

## Report versions and verification

Each generated or approved report is stored once, with a version number and SHA-256 fingerprint, and never rebuilt.
The PDF carries a QR code to `/verify/<code>`, which shows whether that exact PDF is intact, current and approved.
The QR link uses the address the app is opened with, so phones can only follow it when the app runs on a reachable host.

## Tests

    python -m unittest discover -s tests -v

15 tests: exact round trip of the tabular layout, CSV / Excel / database import against the JSON reference, full
CSV-to-approved-report run, bad-file rejection, per-job duplicates, incomplete data, register import, frozen versions and
tamper detection, source documents, and the AI reader (mocked): Gemini and OpenAI-compatible requests, PDF-to-image conversion and saved readings.

## Files

`app.py` API, database, validation, PDF | `importers.py` CSV / Excel / SQLite / JSON readers and exporters |
`vision.py` optional Gemini reader | `static/index.html` UI | `static/assistant.js` rule-based help assistant (no AI) | `sample_data/` demo job in every format, its scanned sheets (`sample_data/scans/`, attached when the demo is loaded) and two legacy registers |
`tests/` | `docs/ARCHITECTURE.md`

## Limits to know about

- Demo values were typed by hand from handwritten scans; the validator flags the doubtful ones (IDs read as 4/6/H, a
  watts sum, correction factor 0.275 vs 0.475, 0.3 K winding-rise margin). Confirm against the sheets before relying on them.
- Series and sample codes must match the CPRI patterns (`CPRIBLRSCL25T1654`, `HVD25S0847`), also for register rows.
- Database import reads SQLite files. Other databases (Access, SQL Server, PostgreSQL) need a CSV or Excel export first.
  Legacy `.xls` must be saved as `.xlsx`.
- No user accounts: the reviewer is a typed name and employee ID, not checked against a staff list. Run it on a trusted machine or network only.
- Not an official CPRI system; reports are prototypes.

## Validity

Thresholds live in `rules.py`, each with its source and a status (`secondary` / `unconfirmed`); no lab engineer has confirmed any of them. See [docs/VALIDITY.md](docs/VALIDITY.md) for what is and is not established, and `tests/test_validity.py` for the mutation tests.
