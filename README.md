# Aletheia - Automated Test Report Generation System

Web application for the CPRI Short Circuit Laboratory. Customers raise their test request online on the **Customer Request
Form CPRI/QAF/01A**; test engineers receive it when the sample arrives, upload each test's **Excel logsheet** (several testers
on one job, in any order) and a second tester checks every value against its source cell; the administrator then
approves the job, generates and signs off a signed, hash-verifiable PDF test report in the lab's **Transformer Test report format**. Customers follow their jobs in a
portal (what is approved, what is pending, a partial report built from approved tests only) and raise **tickets** to the
laboratory's administrators.

> **This is currently the dummy (demonstration) version.** Passwords are switched off (`ALETHEIA_PASSWORDS` is `0` by
> default), so nobody signs in: the page opens straight away and the **View as: Customer / Tester / Admin** menu at the
> top right shows each end of the system. Anyone who can open the address can act as any role, so it must not hold real
> customer data or be used to release real reports. To make it the real system, start it with `ALETHEIA_PASSWORDS=1`:
> sign-in with passwords, lock-out and password re-entry at release come back, and the View as menu disappears.

It runs on one ordinary lab PC (Flask + SQLite, no other services) and is used over the lab's local network.
The plan this build follows, with the status of every phase, is in [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md).

## Install and run

    python -m venv .venv && .venv\Scriptsctivate     # Windows (Linux / macOS: source .venv/bin/activate)
    pip install -r requirements.txt
    copy .env.example .env                              # optional: change the settings (see Configuration)
    python app.py                                       # open http://localhost:5000 on the server PC

Python 3.10 or newer. `python app.py` serves the app with **Waitress**, a production WSGI server that runs on Windows (Flask's
own development server is used only if Waitress is missing, with a warning). By default it listens on this computer only;
set `ALETHEIA_HOST=0.0.0.0` to open it to the lab network, and put it behind a reverse proxy with a certificate (then set
`ALETHEIA_HTTPS=1`) if it is reached over HTTPS. Before real use set `ALETHEIA_PASSWORDS=1`; the server warns at start-up
while passwords are off. Records are kept in `aletheia.db` next to `app.py`; backups go to `backups/` beside it.
Browsers re-check the page and its scripts on every load and never cache API answers, so an update shows at once
(no need to clear the browser cache).

**First start:** the page asks for the first administrator account. This works only on the server PC itself and closes for
good once the account exists. The administrator then creates the staff accounts (*New staff user*), the customers (*New
customer*: just a username; its organisation is made for it).

**Testing phase: no passwords.** Everyone signs in with the username only, and approval and amendments ask for no password.
Set `ALETHEIA_PASSWORDS=1` to switch every password rule back on (temporary passwords, lock-out, re-entry at release).

**Showing each end: the *View as* switch.** While there are no passwords, the page opens without a sign-in screen, and a
**View as: Customer / Tester / Admin** menu at the top right of every page switches to that end at once (the first active
account of that role; the browser remembers the last view chosen). Each switch is in the audit log, and every permission of
the account switched to still applies. The switch is off as soon as `ALETHEIA_PASSWORDS=1`, or with `ALETHEIA_ROLE_SWITCH=0`.

**Upgrading an existing database:** on the first start of this version the database is copied to
`aletheia.db.pre-v2-<date>.bak`, then converted (one row per test section, audit trail sealed into a hash chain).

## Who does what

| Role | Does | Cannot |
|---|---|---|
| **Admin** | **approves** a job once every test is verified or not applicable, **generates** the report and **signs it off** (releases it, re-entering the password); with a second administrator, amends a released report; receives customer requests like a test engineer; assigns tests (or a whole job); answers customer tickets; users, customer organisations, Excel templates, backups, audit log | enter, check or verify data |
| **Tester** (test engineer) | intake: receives a customer's request (records sheet 3 of the form, the test plan; series and sample numbers are assigned) or returns it with the reason; takes unassigned tests, uploads the logsheets of their tests, corrects returned tests; **runs the checks**, marks flagged items reviewed; **verifies** tests (their own or colleagues'): verify, return (with reason), reopen, not applicable | raise or change a customer's request, take a test assigned to someone else, approve, generate or sign off |
| **Customer** | the only one who raises a test request: fills in the Customer Request Form (CPRI/QAF/01A, sheets 1-2) online and corrects it when returned; raises **tickets** to the laboratory (questions or problems, optionally about a job); sees their organisation's jobs: progress, approved values, partial report, released reports | see other customers' jobs, values of tests not yet approved, staff names |

Each account has one role: Admin, Tester or Customer (the Verifier and Approver roles were removed; on the first start an
old Verifier becomes a Tester and an old Approver an Admin, and an account that would combine Admin with Tester stops the
start-up with a list, to be split into two accounts). A tester may verify their own upload. Because an amendment needs a second signature, a laboratory needs **at least two
administrators**. Every rule is enforced by the server (a route without a permission rule is refused) and every refusal
is recorded in the audit log.

## Workflow

1. **Request** (Customer): only a customer raises a test request. They fill in the **Customer Request Form CPRI/QAF/01A**
   online, laid out as the printed form (sheet 1: customer, sample, rating, description, type, serial, manufacturer,
   drawings, requirement, standard, number of samples, storage / disposal, tests, mounting, witnesses, despatch; sheet 2:
   MSME discount, statement of conformity and decision rule (i)/(ii)/(iii), the two declarations, name and date), and tick
   the tests they need. Every value is checked as they type (PIN code, phone, email, state, rating...; "NA" only where the
   form allows it, with a reason). The request lands in the laboratory's inbox (**Customer requests**).
2. **Intake** (Tester): when the sample arrives the engineer opens the request (shown exactly as the customer sent it; the
   laboratory never edits it), records **sheet 3** (physical condition on receipt, the customer's concurrence if not
   suitable, capability, externally provided products/services; later the deviations noticed during testing), chooses the
   test plan and may take tests. *Accept request* assigns the series and sample numbers; a request with something missing or
   wrong is **returned** to the customer with the reason, and they correct it and send it again.
3. **Assignment and testing**: the administrator assigns tests (or the whole job), or an engineer takes an unassigned
   test. The engineer gets one notification per assignment, however many tests it covers; the same test assigned on several
   jobs at once is one notification listing the jobs. Testers, in any order, upload each test's Excel logsheet (or CSV). The upload preview shows every value with
   the cell it was read from; a required empty cell blocks the test (never stored as NA). Each test keeps its full history.
4. **Checks and verification** (Testers): the checks (`validate`) run on the data (recomputations of logged figures are
   advisory only) and flagged items are reviewed in place, with an optional note. A second tester compares each test's
   values with its source file, then verifies it, or returns it with a reason. A verified test is locked.
5. **Approval and report** (Admin): when every planned test is verified or not applicable, the administrator **approves** the
   job, then **generates** the report: a numbered, hashed version with a printed manifest of everything it was built from.
6. **Sign-off and release** (Admin): re-enter the password to sign; the report is released, locked (also in the database)
   and the customer is notified, once. Corrections after release are **amendments**: a new version that supersedes the old one, which stays
   verifiable.

Pages for staff: **Dashboard** (each person's tasks: for testers what to verify, test or take; for Admin what is ready to
approve, ready for sign-off, not assigned, and the customer tickets to answer), **My work** (what waits on you, oldest first), **Customer requests**
(test engineers and the admin: the intake inbox), **Report Workflow**, **Records & Search** (with Excel export of many jobs), **Report
Preview**; for Admin also **Users & customers**, **Templates**, **Audit log**, **Customer tickets**, **Backups**.
The job page has one list, **Tests and verification**: every test the job needs (its plan, and anything uploaded), then the sample identification record and the supplementary records. Each row carries its files (*Blank sheet*, *Upload*, *Enter* or *Edit*, *Remove*) under the name, and its state and workflow actions (take, assign, verify, not applicable) on the right.
Every file is uploaded from the row of the test it belongs to (*Upload* on that row): a data file only fills that test,
a scan is attached to that test. Nothing is assigned to a test by itself (no general drop area, no workbook routed to several jobs).
Pages for customers: **Open requests** (their jobs and their test requests, *New test request*), **Tickets**, **Notifications**.
Required fields on every form are marked with a red asterisk.

### Demo

| Show | Steps |
|---|---|
| Whole chain | Sign in as a customer: *New test request*, fill in the form, send it. Sign in as a tester: *Customer requests*, open it, record sheet 3, accept; take each test, upload its logsheet (`sample_data/`), run checks, review flagged items. Sign in as a second tester: verify each test. Sign in as the admin: *Approve*, *Generate report*, then *Sign off and release*. |
| Excel logsheets | Job page -> *This job as filled logsheets*, or a test's blank logsheet from Templates (Admin): drop the workbook on a job to see the preview with source cells |
| Failing sample | `test-files/3 - failing job (top-oil rise over limit).csv`: the logged top-oil rise is over its limit, so the report says the sample does NOT comply |
| Customer | Create a customer account for the job's organisation, sign in: progress, approved values, partial report |
| Tickets | As the customer: *Tickets* -> *Raise a ticket*. As the admin: *Customer tickets*, answer, close |

## Notifications

Every notification opens the job, test or request it is about (the target is stored with it) and is marked read when
clicked. The **Notifications** page shows *Needs your action* (a test assigned or returned to you, a test to verify, a
request to accept, a job to approve, a report to sign off) above *For information*, grouped by day, with the tabs Unread
(default), Needs action and All. The bell shows the latest five unread. Repeats of one kind for one job within 30 minutes
become one row ("3 updates"). **Customers** hear only: request received, request returned for correction, and the final
report released (once per released version, with a link to it); nothing while the tests are in progress. Aletheia sends no
email: every notice is in the portal.

## Test names

One list (`NAMES` and `EXTRA_NAMES` in `app.py`) names every test record on every page, in notifications, audit entries,
Excel titles and the report: Customer Request Form, Proforma for Transformers, Work Instruction, Loss Measurement Datasheet,
Winding Resistance and Loss Logsheet, No-Load Loss and Current Logsheet, Routine Test Logsheet, Short-Circuit Withstand Test
Logsheet, Temperature-Rise Test Logsheet, Pressure and Oil-Leakage Test Logsheet, Sample Identification Record,
Supplementary Test Records. Only display names: stored keys never change, and older audit entries keep their wording.

## Customer tickets

A customer raises a ticket from **Tickets** (or *Raise a ticket* on one of their jobs): what it is about (test request,
test report, partial report or values, sample handling or despatch, account, other), a subject and the message. It goes
to the administrators (notification, dashboard task *Customer tickets to answer*). The administrator answers in the same
thread; the customer sees the answer signed *CPRI Short Circuit Laboratory* (never a staff name) and is notified. Status:
**open** (waiting for the laboratory) -> **answered** -> **closed**; a customer's reply re-opens it. Customers see only
their organisation's tickets; messages cannot be changed or removed, and every step is in the audit log (kind `ticket`).

## Excel logsheets and templates

Each test has an Excel **template**: a mapping, stored in the database, from cells to fields. One mapping both draws the blank
logsheet (yellow input cells, named cells) and reads a filled one: by defined name, then label (also slightly reworded), then
fixed cell; tables by their header labels, so inserted rows or columns do not break them. Formulas are taken as the value the
sheet shows (a formula never recalculated is refused), decimal commas only by explicit rule, units never guessed.
Administrators make a new template version when a sheet changes, test it on a sample and on past uploads, compare it with the
active one and activate it; versions that read stored data are kept. See `xltemplates.py` for the mapping format.

**Version 2: the paper layout** (`paper_templates.py`). Each test's sheet is laid out as its scanned paper logsheet
(`sample_data/scans/`): the header block first, then the readings in the paper's row and column order, then remarks,
instruments and signatures, with the same labels and units, so a tester copies values straight across. Input cells are
light yellow; printed text, row labels and calculated cells (averages, average ambient, top-oil rise, deflection) are grey
and locked (the sheet is protected without a password). Choices are dropdowns, readings must be numbers within sensible
limits, dates must be dates, and a short note at the top says how to fill it in. A hidden first row carries the fingerprint
that recognises the sheet on upload. The stored data keeps the shape the checks and the report read; what the paper adds
(time of each temperature reading, voltage applied per shot, instruments, signatures...) is stored alongside under new
names, and signatures are never shown to customers. On the first start of this version, version 2 becomes active and
version 1 is retired (an administrator's own active version is kept, and version 2 is offered as a draft). Files filled in
on version 1 still import: an upload is matched against the active version first, then the retired ones.
`sample_data/tests/*.xlsx` are the demo job's values in the paper layout. Testers get the blank sheets from the job page:
**Blank sheet** on each test's row (Tests and verification) downloads that test's logsheet with the job's series number, sample code and customer
already written in; they fill in the readings and upload it with **Upload** on the same row.

The original flat layout (`section, field, value` in CSV, Excel, SQLite or JSON) is still read; any job can be downloaded in it.

## The test report

The PDF follows the lab's **Transformer Test report format**: CPRI header, report number and date, the ULR / laboratory footer
with *Sheet n of N* and the test engineer's signature line on every sheet. Sheets: cover (with the documents constituting the
report, in words), description of the sample, summary of tests conducted (IS 1180 clause and sheet of each test), list of
drawings, routine test results, short-circuit withstand, reactance / inspection / oil leakage / routine pressure, temperature
rise, type pressure / vacuum and no-load current at 112.5 %, with the conclusion; the last sheet carries the notes, the
accreditation mark, the verification QR code and the traceability annex. A full job gives 11 sheets; sheets without data are
left out and the sheet references follow. Values are printed as logged. The cover takes the customer, sample, witnesses and
requirement from the customer's request, and the deviations from sheet 3 of the request form. Laboratory details, clause numbers and notes are in
`report_template.json`. Energy efficiency, coil, core and winding details (proforma) and the atmospheric pressure (pressure
logsheet) are optional template fields; when a logsheet does not carry them the report prints NA or the construction text.

## Integrity

- One database row per test section, with revisions: concurrent uploads to different tests never overwrite each other, and an
  edit from an out-of-date page is refused with who changed it.
- Every revision of every test and every uploaded file is kept, with SHA-256 fingerprints.
- The customer's request is kept exactly as sent (with its SHA-256) and is never edited by the laboratory; a data file never
  changes it. A correction is a new request from the customer, linked to the one it replaces.
- The audit log records who did what, from which workstation, and is a hash chain (Admin -> Audit log -> *Check the chain*);
  write down the daily chain tip shown on the Backups page.
- Released reports, their data and files are locked by the application and by database triggers.
- Each report version prints a manifest hash; the verification page (QR code on the report) checks the PDF and the manifest.
- Daily backups with checksums; *Check* on a backup verifies it without stopping the lab. A **record package** (zip) per
  released job holds every version, its manifest, source files, history and audit, with checksums.
- Checks take values **as logged** (faculty note F5): see [docs/VALIDITY.md](docs/VALIDITY.md).

## Configuration

Environment variables, read when the app starts; they may also be written in a `.env` file next to `app.py` (start from
`.env.example`, which lists every setting with its default). A variable set in the environment wins over the file.

| Variable | Default | Purpose |
|---|---|---|
| `ALETHEIA_HOST`, `PORT` | `127.0.0.1`, `5000` | Address and port the server listens on (`0.0.0.0`: the lab network) |
| `ALETHEIA_THREADS`, `ALETHEIA_LOG_LEVEL` | `8`, `INFO` | Waitress worker threads; logging level |
| `ALETHEIA_HTTPS` | `0` | `1` when served over HTTPS: the session cookie is sent encrypted only |
| `ALETHEIA_DB` | `aletheia.db` next to `app.py` | Records database (`ai_cache.db`, `.aletheia_secret` and `backups/` go in the same folder) |
| `ALETHEIA_TEMPLATE` | `report_template.json` | Report wording and laboratory details (ULR prefix, address, clause numbers, notes) |
| `ALETHEIA_BACKUP_DIR`, `ALETHEIA_BACKUP_KEEP` | `backups/`, `30` | Backup folder; how many daily backups to keep (the first of each month is always kept) |
| `ALETHEIA_AUTO_BACKUP` | `1` | Daily backup (`0` turns off) |
| `ALETHEIA_PASSWORDS` | `0` | `1` turns passwords on: the real system (off: the dummy version, no sign-in) |
| `ALETHEIA_ROLE_SWITCH` | `1` | `0` turns the *View as* menu off even while passwords are off |
| `ALETHEIA_DEMO` | `0` | `1` enables `/api/demo` (loads the demo job; used by the tests). A real job always starts from a customer's request |
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
| Accounts | `/api/setup`, `/api/login`, `/api/logout`, `/api/me`, `/api/switch` (dummy version only), `/api/password`, `/api/users[...]`, `/api/customers`, `/api/orgs` |
| Intake | `/api/intake/check`, `/api/intake`, `/api/jobs/<id>/intake`, `/api/jobs/<id>/intake/checked`, `/api/request-forms[...]`, `/api/request-forms/<id>/return`, `/api/customer/requests[/check|/<id>]` |
| Data | `/api/jobs/<id>/import`, `/api/jobs/<id>/excel/preview|import`, `/api/jobs/<id>/section`, `/api/jobs/<id>/history`, `/api/files/<id>`, `/api/files/<id>/preview` |
| Verification | `/api/jobs/<id>/sections/<test>/verify|return|reopen|na`, `/api/jobs/<id>/assign`, `/api/jobs/<id>/signoff` |
| Reports | `/api/jobs/<id>/validate|review|generate|approve|amend`, `/api/jobs/<id>/report.pdf`, `/api/verify/<code>` |
| Tickets | `/api/tickets[?status=]`, `/api/tickets/<id>`, `/api/tickets/<id>/messages|close|reopen` |
| Customer | `/api/jobs/<id>/approved-values`, `/api/jobs/<id>/partials`, `/api/jobs/<id>/partial.pdf`, `/api/customer/request-forms` |
| Excel | `/api/templates[...]`, `/api/logsheets/<test|all>.xlsx`, `/api/jobs/<id>/logsheets/<test>.xlsx`, `/api/request-form.xlsx`, `/api/jobs/<id>/logsheets.xlsx`, `/api/records.xlsx` |
| Operations | `/api/my-work`, `/api/notifications`, `/api/audit[/verify|/tip]`, `/api/admin/backups[...]`, `/api/jobs/<id>/package.zip` |

## Tests

    python -m unittest discover -s tests
    pip install -r requirements-dev.txt && python -m pyflakes *.py     # lint

| File | Covers |
|---|---|
| `test_app.py` | import formats, checks, reports, sources, registers (run through the full workflow) |
| `test_validity.py` | one mutation test per engineering check |
| `test_auth.py` | every route x every role, CSRF, lock-out, timeouts, first run, customers, separation of duties |
| `test_integrity.py` | concurrent uploads, revisions, atomic numbering, audit chain, release locks, schema migration |
| `test_workflow.py` | request form and sheet 3 rules, verify / return / reopen, ownership, sign-off, assignment notifications, My work |
| `test_excel.py` | template round trips, preview, layout drift, formulas, refused files, template versions |
| `test_paper.py` | the paper-layout templates (version 2): round trips, protection and validation, calculated cells, rollout, version 1 still importable, blank sheets per job, file preview |
| `test_amend.py` | manifest, amendments, record packages, backups and tamper detection |
| `test_portal.py` | approved values only, partial reports, notifications (in-app only, no email), customer-only requests, return and correction, no same-day board |
| `test_tickets.py` | customers raise tickets, administrators answer and close them; who sees what |
| `test_load.py` | eight people at once on one database |

## Files

| Path | Contents |
|---|---|
| `app.py` | API, database, the checks (`validate`), workflow routes, release and amendment; `serve()` starts the server |
| `config.py`, `.env.example` | settings from the environment or a `.env` file; every setting with its default |
| `requirements.txt`, `requirements-dev.txt` | pinned runtime packages; plus the linter for development |
| `report.py` | the test report PDF in the lab's *Transformer Test report format* (and the customer's partial report) |
| `auth.py` | accounts, sessions, CSRF, roles and the permission gate |
| `integrity.py` | sections and history, files, numbering, audit hash chain, database triggers, migrations |
| `workflow.py` | the Customer Request Form CPRI/QAF/01A (fields, sheet 3) and its rules (PIN-code table), ownership, progress, sign-off readiness |
| `xltemplates.py`, `seed_templates.py`, `paper_templates.py`, `excel_routes.py` | Excel template engine, version-1 templates, version-2 templates (the paper logsheets), template registry and Excel routes |
| `retention.py` | backups, backup check, audit tip, record packages |
| `tickets.py` | customer tickets to the administrators: thread, status, notifications |
| `notify.py`, `portal.py` | in-app notifications; partial reports, approved values, customers' test requests |
| `rules.py` | every engineering threshold with its source and status |
| `importers.py`, `vision.py` | flat-layout readers and exporters, registers; optional AI scan reader |
| `static/` | web UI: `index.html` plus `auth.js`, `workflow.js`, `excel.js`, `portal.js`, `request.js` (customer request form, intake inbox), `tickets.js`, `assistant.js` |
| `docs/` | [NEXT_STEPS.md](docs/NEXT_STEPS.md) (plan and progress), [ARCHITECTURE.md](docs/ARCHITECTURE.md), [VALIDITY.md](docs/VALIDITY.md), [LAB_WORKFLOW.md](docs/LAB_WORKFLOW.md), [CHECKLIST.md](docs/CHECKLIST.md), [NOTES.md](docs/NOTES.md) |
| `sample_data/tests/` | the demo job's data per test, as a CSV and as a filled Excel logsheet (paper layout, version 2, read by the upload preview) (proforma, work instruction, losses, resistance, no-load, routine, short circuit, temperature rise, pressure), to upload test by test |
| `sample_data/`, `test-files/` | demo job in every format with its scans (including the scanned CPRI/QAF/01A request form), the sample report, legacy registers; three CSV demo jobs |

## Limits to know about

- No engineering threshold has been confirmed by the lab or checked against the text of IS 1180 / IS 2026 (see Validity).
- The report's "Limit as per the standard" column for temperature rise (35 / 40 C) and the clause numbers come from
  `report_template.json` and are to be confirmed by the lab; the checks themselves use the limits on the proforma.
- The version-1 logsheet templates are Aletheia's own layouts; the lab's real sheets (Q8 in NEXT_STEPS) become new template
  versions when they arrive. The request form follows CPRI/QAF/01A (Issue 02); the address, contact, phone and email lines
  are asked separately so they can be checked (and used for notifications).
- Demo values were typed from handwritten scans; the validator flags the doubtful ones.
- The development web server is used; on a lab network, run it on the server PC behind the lab's firewall (customers on the
  same network only, as agreed).
- Reports are not yet PDF/A; the record package keeps the PDF with its manifest and source data instead.
- Not an official CPRI system.

## Validity

Thresholds live in `rules.py`, each with its source and a status (`secondary` / `unconfirmed`). See
[docs/VALIDITY.md](docs/VALIDITY.md) for what is and is not established, including which checks are advisory under F5.
