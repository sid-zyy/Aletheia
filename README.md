# Aletheia - Automated Test Report Generation System

Web application for the CPRI Short Circuit Laboratory. Test engineers receive the customer's request, upload each test's
**Excel logsheet** (several testers on one job, in any order, from any bay), verifiers check every value against its source
cell, and an approver releases a signed, hash-verifiable PDF test report. Customers follow their jobs in a portal: what is
approved, what is pending, and a partial report built from approved tests only.

It runs on one ordinary lab PC (Flask + SQLite, no other services) and is used over the lab's local network.
The plan this build follows, with the status of every phase, is in [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md).

## Install and run

    pip install -r requirements.txt
    python app.py                 # open http://localhost:5000 on the server PC

Python 3.10 or newer. Records are kept in `aletheia.db` next to `app.py`; backups go to `backups/` beside it.

**First start:** the page asks for the first administrator account. This works only on the server PC itself and closes for
good once the account exists. The administrator then creates the other accounts (each with a temporary password the person
changes at first sign-in), the customer organisations and the test bays.

**Upgrading an existing database:** on the first start of this version the database is copied to
`aletheia.db.pre-v2-<date>.bak`, then converted (one row per test section, audit trail sealed into a hash chain).

## Who does what

| Role | Does | Cannot |
|---|---|---|
| **Admin** | assigns tests (or a whole job) to test engineers with the bay; users, customer organisations, test bays, Excel templates, settings, backups, audit log; sees what waits for approval | enter or verify data, sign reports |
| **Tester** (test engineer) | intake (receives the customer's request, allocates series/sample number), takes unassigned tests and chooses the bay, uploads the logsheets of their tests, corrects returned tests | take a test assigned to someone else, verify their own upload, sign off or approve a job they worked on |
| **Verifier** | checks each uploaded test against its source cells: verify, return (with reason), reopen, not applicable; signs the job off ("all data correct") | verify their own upload |
| **Approver** | approves and releases the report (re-enters password); with a second approver, amends a released report | approve a job they uploaded, entered or verified data on |
| **Customer** | fills in the test request online (or sends the Excel form); sees their organisation's jobs: progress, approved values, partial report, released reports | see other customers' jobs, values of tests not yet approved, staff names |

Tester, Verifier and Approver may be combined on one account; the rules above still apply per job. Admin and Customer
accounts stand alone. Every rule is enforced by the server (a route without a permission rule is refused) and every refusal
is recorded in the audit log.

## Workflow

1. **Intake** (Tester): the customer's request, filled in online by the customer (checked as they type), their Excel form, the
   form on screen, or a data file. Every required field is checked (PIN code, phone, email, state, rating...;
   "NA" only with a reason); the series and sample numbers are allocated only when nothing is missing or wrong. The engineer
   records arrival time and who opened the box, chooses the test plan and may assign each test to a tester.
2. **Assignment and testing**: the administrator assigns tests (or the whole job) with the bay, or an engineer takes an
   unassigned test and chooses the bay. Testers, in any order and bay, upload each test's Excel logsheet. The upload preview shows every value with
   the cell it was read from; a required empty cell blocks the test (never stored as NA). Each test keeps its full history.
3. **Verification** (Verifier): compare each test's values with its source file, then verify, or return it with a reason.
   A verified test is locked. Checks (`validate`) run on the data; recomputations of logged figures are advisory only.
4. **Sign-off and report** (Verifier, then Tester): when every planned test is verified or not applicable, the verifier signs
   the job off; the report is generated as a numbered, hashed version with a printed manifest of everything it was built from.
5. **Approval** (Approver): re-enter the password to sign; the report is released, locked (also in the database) and the
   customer is notified. Corrections after release are **amendments**: a new version that supersedes the old one, which stays
   verifiable.

Pages: **Dashboard** (with each person's tasks: what to test, take, verify, approve; for Admin what waits for approval and what is not assigned), **My work** (what waits on you, oldest first), **Report Workflow**,
**Records & Search** (with Excel export of many jobs), **Report Preview**; for Admin: **Users & customers**, **Templates**,
**Audit log**, **Backups**, **Settings**; for customers: **My jobs** and **Notifications**.

### Demo

| Show | Steps |
|---|---|
| Whole chain | Sign in as a customer: *New request*. Sign in as a tester: open the request, complete the intake, take each test, upload its logsheet (`sample_data/`), run checks, review flagged items. Sign in as a verifier: verify each test, sign off. Tester: generate. Sign in as an approver (not anyone who uploaded or verified): approve. |
| Excel logsheets | Job page -> *This job as filled logsheets*, or a test's blank logsheet from Templates (Admin): drop the workbook on a job to see the preview with source cells |
| Several jobs in one workbook | Report Workflow -> *Upload a workbook for several jobs* |
| Failing sample | `test-files/3 - failing job (top-oil rise over limit).csv`: the logged top-oil rise is over its limit, so the report says the sample does NOT comply |
| Customer | Create a customer account for the job's organisation, sign in: progress, approved values, partial report |

## Excel logsheets and templates

Each test has an Excel **template**: a mapping, stored in the database, from cells to fields. One mapping both draws the blank
logsheet (yellow input cells, named cells) and reads a filled one: by defined name, then label (also slightly reworded), then
fixed cell; tables by their header labels, so inserted rows or columns do not break them. Formulas are taken as the value the
sheet shows (a formula never recalculated is refused), decimal commas only by explicit rule, units never guessed.
Administrators make a new template version when a sheet changes, test it on a sample and on past uploads, compare it with the
active one and activate it; versions that read stored data are kept. See `xltemplates.py` for the mapping format.

The original flat layout (`section, field, value` in CSV, Excel, SQLite or JSON) is still read; any job can be downloaded in it.

## The test report

The PDF follows the lab's **Transformer Test report format**: CPRI header, report number and date, the ULR / laboratory footer
with *Sheet n of N* and the test engineer's signature line on every sheet. Sheets: cover (with the documents constituting the
report, in words), description of the sample, summary of tests conducted (IS 1180 clause and sheet of each test), list of
drawings, routine test results, short-circuit withstand, reactance / inspection / oil leakage / routine pressure, temperature
rise, type pressure / vacuum and no-load current at 112.5 %, with the conclusion; the last sheet carries the notes, the
accreditation mark, the verification QR code and the traceability annex. A full job gives 11 sheets; sheets without data are
left out and the sheet references follow. Values are printed as logged. Laboratory details, clause numbers and notes are in
`report_template.json`. Energy efficiency, coil, core and winding details (proforma) and the atmospheric pressure (pressure
logsheet) are optional template fields; when a logsheet does not carry them the report prints NA or the construction text.

## Integrity

- One database row per test section, with revisions: concurrent uploads to different tests never overwrite each other, and an
  edit from an out-of-date page is refused with who changed it.
- Every revision of every test and every uploaded file is kept, with SHA-256 fingerprints.
- The audit log records who did what, from which workstation, and is a hash chain (Admin -> Audit log -> *Check the chain*);
  write down the daily chain tip shown on the Backups page.
- Released reports, their data and files are locked by the application and by database triggers.
- Each report version prints a manifest hash; the verification page (QR code on the report) checks the PDF and the manifest.
- Daily backups with checksums; *Check* on a backup verifies it without stopping the lab. A **record package** (zip) per
  released job holds every version, its manifest, source files, history and audit, with checksums.
- Checks take values **as logged** (faculty note F5): see [docs/VALIDITY.md](docs/VALIDITY.md).

## Settings

Environment variables, read when the app starts. Email is set in the app (Admin -> Settings).

| Variable | Default | Purpose |
|---|---|---|
| `ALETHEIA_DB` | `aletheia.db` next to `app.py` | Records database (`ai_cache.db`, `.aletheia_secret` and `backups/` go in the same folder) |
| `PORT` | `5000` | Port of the web app |
| `ALETHEIA_TEMPLATE` | `report_template.json` | Report wording and laboratory details (ULR prefix, address, clause numbers, notes) |
| `ALETHEIA_BACKUP_DIR`, `ALETHEIA_BACKUP_KEEP` | `backups/`, `30` | Backup folder; how many daily backups to keep (the first of each month is always kept) |
| `ALETHEIA_AUTO_BACKUP`, `ALETHEIA_WORKER` | `1`, `1` | Daily backup; email outbox (`0` turns off) |
| `ALETHEIA_SMTP_PASSWORD` | unset | SMTP password (server, port, sender, user are set in the app) |
| `ALETHEIA_FEATURE_SCAN` | `0` | `1` turns on the optional AI reading of scanned sheets (below) |
| `GEMINI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY`, `AI_*` | unset | AI reader for scans (only with `ALETHEIA_FEATURE_SCAN=1`) |

`.aletheia_secret` holds the key that signs session cookies; keep it with the database, out of git.

## Scans and AI reading (optional, off by default)

Scans and photos (PDF, PNG, JPEG, WebP) can always be attached to a job as evidence, with their SHA-256. Reading them with an
AI model (Gemini, Ollama or any OpenAI-compatible reader) was the original input path and is now an optional fallback: set
`ALETHEIA_FEATURE_SCAN=1` and a reader (see `vision.py` and [docs/NOTES.md](docs/NOTES.md) for measured accuracy). Every
reading is a proposal that must be checked by hand.

## API

JSON API; uploads are `{filename, b64}`. Every route names its permission (`auth.require`); state-changing calls need the
`X-CSRF-Token` header from `GET /api/me`. Main groups:

| Area | Endpoints |
|---|---|
| Accounts | `/api/setup`, `/api/login`, `/api/logout`, `/api/me`, `/api/password`, `/api/users[...]`, `/api/orgs` |
| Intake | `/api/intake/check`, `/api/intake`, `/api/jobs/<id>/intake`, `/api/jobs/<id>/intake/checked`, `/api/intake/from-excel`, `/api/request-forms[...]` |
| Data | `/api/jobs/<id>/import`, `/api/jobs/<id>/excel/preview|import`, `/api/excel/preview|import` (several jobs), `/api/jobs/<id>/section`, `/api/jobs/<id>/history`, `/api/files/<id>` |
| Verification | `/api/jobs/<id>/sections/<test>/verify|return|reopen|na`, `/api/jobs/<id>/assign`, `/api/jobs/<id>/signoff` |
| Reports | `/api/jobs/<id>/validate|review|generate|approve|amend`, `/api/jobs/<id>/report.pdf`, `/api/verify/<code>` |
| Customer | `/api/jobs/<id>/approved-values`, `/api/jobs/<id>/partials`, `/api/jobs/<id>/partial.pdf`, `/api/customer/request-forms` |
| Excel | `/api/templates[...]`, `/api/logsheets/<test|all>.xlsx`, `/api/request-form.xlsx`, `/api/jobs/<id>/logsheets.xlsx`, `/api/records.xlsx` |
| Operations | `/api/my-work`, `/api/notifications`, `/api/settings`, `/api/outbox`, `/api/audit[/verify|/tip]`, `/api/admin/backups[...]`, `/api/jobs/<id>/package.zip` |

## Tests

    python -m unittest discover -s tests

| File | Covers |
|---|---|
| `test_app.py` | import formats, checks, reports, sources, registers (run through the full workflow) |
| `test_validity.py` | one mutation test per engineering check |
| `test_auth.py` | every route x every role, CSRF, lock-out, timeouts, first run, customers, separation of duties |
| `test_integrity.py` | concurrent uploads, revisions, atomic numbering, audit chain, release locks, schema migration |
| `test_workflow.py` | intake rules, verify / return / reopen, ownership, sign-off, bays, My work |
| `test_excel.py` | template round trips, preview, layout drift, formulas, refused files, several jobs per workbook, template versions |
| `test_amend.py` | manifest, amendments, record packages, backups and tamper detection |
| `test_portal.py` | approved values only, partial reports, notifications and email, customers' forms, no same-day board |
| `test_load.py` | eight people at once on one database |

## Files

| Path | Contents |
|---|---|
| `app.py` | API, database, the checks (`validate`), workflow routes, release and amendment |
| `report.py` | the test report PDF in the lab's *Transformer Test report format* (and the customer's partial report) |
| `auth.py` | accounts, sessions, CSRF, roles and the permission gate |
| `integrity.py` | sections and history, files, numbering, audit hash chain, database triggers, migrations |
| `workflow.py` | intake rules (PIN-code table), ownership, progress, sign-off readiness |
| `xltemplates.py`, `seed_templates.py`, `excel_routes.py` | Excel template engine, version-1 templates, template registry and Excel routes |
| `retention.py` | backups, backup check, audit tip, record packages |
| `notify.py`, `portal.py` | notifications, email outbox, settings; partial reports, approved values, customer forms |
| `rules.py` | every engineering threshold with its source and status |
| `importers.py`, `vision.py` | flat-layout readers and exporters, registers; optional AI scan reader |
| `static/` | web UI: `index.html` plus `auth.js`, `workflow.js`, `excel.js`, `portal.js`, `assistant.js` |
| `docs/` | [NEXT_STEPS.md](docs/NEXT_STEPS.md) (plan and progress), [ARCHITECTURE.md](docs/ARCHITECTURE.md), [VALIDITY.md](docs/VALIDITY.md), [NOTES.md](docs/NOTES.md) |
| `sample_data/`, `test-files/` | demo job in every format with its scans, legacy registers; three CSV demo jobs |

## Limits to know about

- No engineering threshold has been confirmed by the lab or checked against the text of IS 1180 / IS 2026 (see Validity).
- The report's "Limit as per the standard" column for temperature rise (35 / 40 C) and the clause numbers come from
  `report_template.json` and are to be confirmed by the lab; the checks themselves use the limits on the proforma.
- The version-1 logsheet templates are Aletheia's own layouts; the lab's real sheets (Q8 in NEXT_STEPS) become new template
  versions when they arrive. The intake field list (Q14) is an assumption to confirm.
- Demo values were typed from handwritten scans; the validator flags the doubtful ones.
- The development web server is used; on a lab network, run it on the server PC behind the lab's firewall (customers on the
  same network only, as agreed).
- Reports are not yet PDF/A; the record package keeps the PDF with its manifest and source data instead.
- Not an official CPRI system.

## Validity

Thresholds live in `rules.py`, each with its source and a status (`secondary` / `unconfirmed`). See
[docs/VALIDITY.md](docs/VALIDITY.md) for what is and is not established, including which checks are advisory under F5.
