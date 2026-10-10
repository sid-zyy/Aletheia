# Aletheia - Automated Test Report Generation System

Web prototype for the CPRI Short Circuit Laboratory (Hackathon Track 3). It collects the customer request, work
instruction, proforma and seven lab log sheets from **spreadsheets, CSV files, existing databases, JSON or scans**,
validates them, stores them in a database and produces a printable, verifiable PDF test report: a pass, or a
"does not comply" report that lists every requirement not met.

This is the merged build: the dashboard, validation engine and report layout of the "updated UI" prototype, plus
scan evidence, optional AI reading, frozen report versions with QR verification and automated tests from
"Prototype 3", plus CSV / Excel / database import.

## Install and run

    pip install -r requirements.txt
    python app.py                 # open http://localhost:5000

Python 3.10 or newer. Records are kept in `aletheia.db` next to `app.py`. All settings are listed under [Settings](#settings).

### Demo scripts

| Show | Steps |
|---|---|
| Passing job (2 min) | **Try the demo data** -> **Run checks** -> **Mark as reviewed** on each flagged item -> **Generate report** -> enter a name and employee ID (not the test engineer, P. Naveenkumar) -> **Approve and release** -> **Copy customer link** |
| Failing sample | **New request**, drop `test-files/3 - failing job (top-oil rise over limit).csv` -> **Run checks** -> **Confirm: requirement not met** on the top-oil item, review the rest -> **Generate report**: section 4 says the sample does NOT comply |
| Missing data | Same with `test-files/2 - partial job (8 documents, 3 values empty).csv`: missing tests read NOT EVALUATED / NOT FULLY EVALUATED, never PASS |
| Importing | **New request**, drop `sample_data/AP_Transformers_25T1654.csv` (or `.xlsx`, or `_lab.db`) |
| Historical records | **Records & Search** -> **Import existing register** -> `sample_data/legacy_register.csv` (or `.db`), then the **Historical** tab, result and date filters |
| Customer view | Open the customer link (or scan the QR code on the PDF): integrity check and download of the approved PDF |

The three files in `test-files/` have different series numbers (`...25T1654`, `...25T1704`, `...25T1714`), so all three can
be loaded side by side.

## Workflow (matches the problem statement)

1. **Capture request** - "New request" form with ID format checks, a request created from a data file, or a scan of the
   request form read by the AI reader.
2. **Import data** - drop a file on the job page. Data files are read; PDFs and images are kept as source documents with a
   SHA-256 fingerprint. Every document also has a labelled form page for typing or correcting values.
3. **Validate** - 30 checks: arithmetic re-computation, cross-document ID consistency, limits from the proforma and
   `rules.py` (IS 1180 / IS 2026 references, see [Validity](#validity)), thin margins. Results:
   - **pass**;
   - **review** - doubtful but not a failure (handwriting 4/6/H, a thin margin, a value left NA); each is marked as reviewed;
   - **data error** - the data itself is wrong (a logged average that does not match its readings, a broken layout); blocks
     the report until it is corrected;
   - **requirement not met** - a test result (e.g. top-oil rise over its limit). The engineer confirms the reading and the
     report states that the sample **does not comply**, with a table of what was not met.
4. **Generate** - the report template is filled from the database and stored as a numbered, hashed version. A test that could
   not be fully evaluated never reads PASS; the statement of conformity lists every document and check left out.
5. **Review and export** - preview, print, download, approve with the reviewer's name and employee ID (both required, printed
   on the report). The test engineer named on the report cannot approve it. Then copy or email the customer link: the
   customer opens the verification page and downloads the approved PDF. Every step is in the job history.

Changing any test data sends the job back to "Data imported", so the checks and the report are always redone on the current data.

**Dashboard:** pipeline counts, average turnaround from request to release (from the audit trail), oldest open job, quality
gate, charts against limits, recent reports with their result.
**Report Workflow:** live pipeline and the jobs waiting, oldest first, with how long each has waited.
**Records & Search:** text search over series, sample, customer, rating, tests, standard, engineer, approver and dates;
filters for status, result (complies / does not comply / not yet checked), date range, and historical records.

## Importing data

| Source | How |
|---|---|
| CSV (`.csv`, `.tsv`; comma, semicolon or tab; any line endings) | columns `section, field, value` |
| Excel (`.xlsx`) | one sheet with `section, field, value`, or one sheet per section with `field, value` |
| Existing database (SQLite `.db`) | any table with `section, field, value`, or one table per section with `field, value`. Opened read-only. |
| JSON | one object per section (the original format) |
| Scan or photo (`.pdf`, `.png`, `.jpg`, `.webp`) | stored with a SHA-256 fingerprint; type the values on the form page, or use "Scan" |

`section` is one of `request, proforma, work, losses, resistance, noload, routine, sc, temp, pressure, ids, other`
(`ids`: series and sample as written on each sheet; `other`: additional log sheets of any type).
`field` is a path: `kva`, `limits.oil`, `hours[0][1]` (dots for names, `[n]` for list positions, counting from 0).
`value` is read as a number when it looks like one; put it in double quotes to keep it as text (serial number `"1098"`).
An optional `series` column lets one file or database hold several jobs; rows for other series are skipped.

The easiest way to get the layout right: open any job and use **Download this job's data** (CSV, Excel, Database, JSON)
or the blank **CSV / Excel template** links. Whatever the app exports, it can import again unchanged.
Importing the same content twice into one job is refused. Files added to a job are listed on the job page where they were
dropped; **Remove** next to an imported file takes the documents it brought in back out (the customer request stays), and
the job returns to step 1 if nothing else is left. Several files can be dropped at once.

**Existing registers** (Records & Search -> Import existing register; template under **Register template**): a CSV, Excel
sheet or SQLite table with at least `series` and `customer` columns (also read: `sample`, `rating`, `address`, `serial`,
`tests`, `standard`, `witness`, `conformity`, `test date`, `result`; common header variants such as "Test Series No",
"Customer Name" or "Date of Test" are recognised). Each valid row becomes a **historical record**: searchable and filterable
by result and test date, but not counted as a job in progress. Results such as "Passed" / "Failed - ..." are read as
complies / does not comply; dates such as 18-03-2024 are stored as 2024-03-18. Importing test data into a historical record
turns it into a live job. Invalid or duplicate rows are listed with the reason.

## Reading scans with AI (optional)

On a job, attach a scan, click **Scan**, say which document it is. The form page fills in part by part as the reader
answers, with uncertain fields highlighted. Nothing is saved until you review and save it, and the saved values are then
checked like any other data. Without a reader configured, the button explains that it is not set up; everything else works offline.

Choose one reader (PowerShell shown; set the variables in the same window before `python app.py`):

| Reader | Settings |
|---|---|
| Qwen on this computer (offline) via [Ollama](https://ollama.com) | `ollama pull qwen2.5vl:7b`, then `$env:AI_BASE_URL = "http://localhost:11434/v1"`, `$env:AI_MODEL = "qwen2.5vl:7b"` |
| Hosted Qwen or any OpenAI-compatible service (e.g. OpenRouter) | `$env:AI_BASE_URL = "https://openrouter.ai/api/v1"`, `$env:AI_MODEL = "qwen/qwen2.5-vl-72b-instruct"`, `$env:AI_API_KEY = "..."` |
| Google Gemini | `$env:GEMINI_API_KEY = "..."`, optionally `$env:GEMINI_MODEL` (default `gemini-3.8-flash`) |

`AI_BASE_URL` takes priority over Gemini. PDFs are sent to Gemini as they are; for other readers each page (up to 4) is
turned upright if needed and converted to a high-contrast image, and large sheets are read in parts (header fields, then each
table). Busy or rate-limited answers are retried after 2, 5 and 10 seconds.

**Saved readings.** Every successful reading is stored in `ai_cache.db` (next to the database, kept when the job
database is deleted), keyed by the scan's SHA-256, the part of the sheet and the model. Reading the same scan again returns
the saved reading instantly, without contacting the AI, and says so. Tick "Read again" to force a new reading. For a demo,
read each scan once beforehand; on stage the readings then work offline.

**Accuracy.** Measured with `qwen2.5vl:3b` on a laptop CPU it gets roughly half the fields right and takes 20-45 s for a short
sheet (details in [docs/NOTES.md](docs/NOTES.md)); every reading must be checked by hand. Check that sending lab records to an
outside service is acceptable before using a hosted reader on real data.

## Report template

The wording of the report (organisation, title, section headings, signature labels, footer) is in `report_template.json`.
Edit it, or point `ALETHEIA_TEMPLATE` at another file; it is read each time a report is built, so no restart is needed.
Keys left out keep the built-in wording. The tables and their layout are defined in `build_pdf` in `app.py`.

## Report versions and verification

Each generated or approved report is stored once, with a version number and SHA-256 fingerprint, and never rebuilt.
The PDF carries a QR code to `/verify/<code>`, which shows whether that exact PDF is intact, current and approved, and lets
the customer download it while it is the current approved version. A record with a released report cannot be deleted, so the
QR code keeps working; withdraw the report instead (the version stays verifiable as withdrawn).
The QR link uses the address the app is opened with, so phones can only follow it when the app runs on a reachable host.

## Settings

Environment variables, read when the app starts (the report template is read on every report).

| Variable | Default | Purpose |
|---|---|---|
| `ALETHEIA_DB` | `aletheia.db` next to `app.py` | Records database. `ai_cache.db` is kept in the same folder. |
| `PORT` | `5000` | Port of the web app |
| `ALETHEIA_TEMPLATE` | `report_template.json` | Report wording file |
| `ALETHEIA_APPROVERS` | (unset: anyone) | Comma-separated employee IDs allowed to approve reports |
| `ALETHEIA_DAILY_CALL_LIMIT` | `15` | AI requests per day to hosted readers (local models are not limited) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | unset, `gemini-3.8-flash` | Google Gemini reader |
| `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY` | unset | Ollama or any OpenAI-compatible reader (port 11434 or `AI_PROVIDER=ollama` uses Ollama's own API) |
| `AI_TIMEOUT` | `300` | Seconds per AI request (a CPU-only local model can take minutes per page) |
| `AI_NUM_CTX`, `AI_MAX_TOKENS` | `8192`, `3000` | Ollama context window and answer length cap |
| `AI_IMAGE_PX`, `AI_AUTOROTATE` | `1024`, `1` | Page image size; set `AI_AUTOROTATE=0` to stop turning sideways pages upright |

## API

The UI uses a JSON API; uploads are sent as `{filename, b64}`.

| Endpoint | Purpose |
|---|---|
| `GET /api/jobs?q=&stage=&verdict=&from=&to=` | List / search records. `stage` 0-4 or `h` (historical); `verdict` `comply`, `not`, `none`; dates `YYYY-MM-DD` |
| `POST /api/jobs`, `POST /api/jobs/from-file` | New request from the form, or from a data file |
| `GET /api/jobs/<id>`, `POST /api/jobs/<id>/edit`, `DELETE /api/jobs/<id>` | One record with history, imports, sources and report versions; edit details; delete (refused once a report is released) |
| `POST /api/jobs/<id>/import`, `DELETE /api/jobs/<id>/imports/<import id>` | Import a data file; undo an import (the documents it brought in are removed; refused once a report is generated) |
| `POST /api/jobs/<id>/section`, `DELETE /api/jobs/<id>/section/<k>` | Save one document typed or read by AI; remove one document |
| `GET /api/jobs/<id>/export/<csv,xlsx,sqlite,json>`, `GET /api/template/<fmt>` | Download a job's data, or the blank layout |
| `POST /api/jobs/<id>/sources`, `GET` / `DELETE /api/sources/<sid>`, `POST /api/sources/<sid>/extract`, `POST /api/read-scan` | Scans: attach, view, remove, read with AI |
| `POST /api/jobs/<id>/validate`, `POST /api/jobs/<id>/review` | Run the checks; mark an item reviewed / confirm a requirement not met (`{index, reviewed}`) |
| `POST /api/jobs/<id>/generate`, `POST /api/jobs/<id>/approve`, `POST /api/jobs/<id>/discard` | Build a report version; approve (`{name, employee_id}`); withdraw the report |
| `GET /api/jobs/<id>/report.pdf` | Latest report version (`?dl=1` to download) |
| `GET /api/verify/<code>`, `GET /api/verify/<code>/report.pdf` | Verification result; customer download of the current approved version |
| `POST /api/import-register`, `GET /api/register-template.csv` | Historical records from a register |
| `GET /api/stats`, `POST /api/demo` | Dashboard figures (pipeline, turnaround, results, AI usage); load the demo job |

## Tests

    python -m unittest discover -s tests -v

60 tests (`tests/test_app.py` 33, `tests/test_validity.py` 27): exact round trip of the tabular layout, CSV / Excel / database
import against the JSON reference (including CSV files saved with Windows line endings), full CSV-to-approved-report run,
"does not comply" reports for failing samples, data errors blocking the report, summary verdicts with NA values, bad-file
rejection, per-job duplicates, incomplete data, historical register import with results and dates, search filters, release
rules (approver not the engineer, approved-staff list, no deletion after release, customer download), undoing an import, report template,
frozen versions and tamper detection, source documents, the AI reader (mocked), and one mutation test per engineering check.

## Files

| Path | Contents |
|---|---|
| `app.py` | API, database, the 30 checks (`validate`), report (`build_pdf`), versions, release rules, statistics |
| `rules.py` | Every engineering threshold with its source and status |
| `importers.py` | CSV / Excel / SQLite / JSON readers and exporters, register import |
| `vision.py` | Optional scan reader (Gemini, Ollama or any OpenAI-compatible model) and its cache |
| `report_template.json` | Report wording |
| `static/index.html`, `static/assistant.js` | Web UI; rule-based help assistant (keyword matching, no AI) |
| `sample_data/` | Demo job in every format, its scanned sheets (`scans/`, attached when the demo is loaded), two legacy registers |
| `tests/` | Unit and mutation tests |
| `docs/` | [ARCHITECTURE.md](docs/ARCHITECTURE.md) (diagram, data model), [VALIDITY.md](docs/VALIDITY.md) (what the checks do and do not establish), [NOTES.md](docs/NOTES.md) (team notes, scanner measurements) |
| `test-files/` | Three CSV jobs for demos: full, partial, failing |

## Limits to know about

- Demo values were typed by hand from handwritten scans; the validator flags the doubtful ones (IDs read as 4/6/H, a
  watts sum, correction factor 0.275 vs 0.475, 0.3 K winding-rise margin). Confirm against the sheets before relying on them.
- No engineering threshold has been confirmed by the lab or checked against the text of IS 1180 / IS 2026 (see Validity).
- Series and sample codes must match the CPRI patterns (`CPRIBLRSCL25T1654`, `HVD25S0847`), also for register rows.
- Database import reads SQLite files. Other databases (Access, SQL Server, PostgreSQL) need a CSV or Excel export first.
  Legacy `.xls` must be saved as `.xlsx`.
- No user accounts: the reviewer is a typed name and employee ID. The test engineer named on the report cannot approve it, and
  `ALETHEIA_APPROVERS` restricts approval to a list of IDs, but nobody logs in. Run it on a trusted machine or network only.
- Getting values off handwritten sheets is still the slow step: they are typed into the form pages, or read by the optional
  AI reader and checked by hand.
- Turnaround is measured from when the request is captured in Aletheia, not from when the sample arrived at the lab.
- Only the report wording is in the template; a different report layout or test type needs code changes in `validate`,
  `build_pdf`, `vision.HINTS` and the UI. Sheets of other types can be added as "Other log sheet" (reported as recorded, no limits).
- Not an official CPRI system; reports are prototypes.

## Validity

Thresholds live in `rules.py`, each with its source and a status (`secondary` / `unconfirmed`); no lab engineer has confirmed
any of them. See [docs/VALIDITY.md](docs/VALIDITY.md) for what is and is not established, and `tests/test_validity.py` for the
mutation tests.
