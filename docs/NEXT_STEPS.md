# Aletheia: next steps (post-briefing plan)

Source: lab briefing + faculty notes. Written against the code as it stands (`app.py`, `importers.py`, `vision.py`, `static/index.html`).
Direction change: **Excel data is now the primary input; scanning (`vision.py`) is demoted to an optional fallback.**
Main focus of this plan: **the workflow, the roles, and login.**

---

## Decisions confirmed after the briefing follow-up (these override anything below that disagrees)

| # | Decision | Effect on the plan |
|---|---|---|
| D1 | **Intake is done by the test engineer** who receives the filled customer request form. No separate Intake/Security role. | Roles reduced to Admin, Tester, Verifier, Approver, Customer. "Create job" is a Tester permission (§2, §3). |
| D2 | **The 15-day limit is ignored.** ~~Target is same day / that evening.~~ Superseded by D7. | ~~SLA clock becomes a same-day cut-off (§7.2).~~ |
| D3 | **Customer sees how much is approved, what is pending, and the partial report so far.** | Progress view + a continuously updated *partial report* built from approved sections (§7.1). |
| D4 | **"Pin code" meant location (postal PIN code)**, only as an example that **nothing may be missing or wrong**. It is not a sign-off PIN. | No sign-off PIN. Instead: strict required-field and format validation at intake (§3.6), plus the integrity rules (§6). Re-entering the password at release stays optional. |
| D5 | **All customers are on localhost.** The system **sends a mail/notification when something is uploaded.** | Customer portal is on the same LAN host, no external exposure. Notification centre + optional SMTP email (§7.3). |
| D6 | **The test report follows the lab's "Transformer Test report format"** (Word file, 11 sheets). | `report.py` lays the PDF out sheet by sheet; laboratory details, clauses and notes in `report_template.json` (Q7 answered: PDF in the lab's layout). |
| D7 | **No same-day target.** The cut-off was an exaggeration to stay on time. | Today board, cut-off, carry-over and same-day flag removed; release still records `completed_at`. |
| D8 | **Only the customer raises a new test request**, filled in **exactly as the printed Customer Request Form CPRI/QAF/01A**, and it is received by the CPRI side. | Online form = sheets 1-2; the laboratory records sheet 3 at intake, or returns the request with the reason. Staff cannot create a job without a customer's request (Q14 answered by the form). |
| D9 | **Customers can raise tickets, which go to the admin.** | `tickets.py`: thread, open / answered / closed, notifications; customers see only their own, never staff names. |
| D10 | **Roles are Admin, Tester and Customer** (feedback 10-11 Oct 2026). The Verifier and Approver roles are removed. | Testers run the checks and verify tests (their own uploads included, from 11 Oct 2026); the administrator approves the job once every test is verified or not applicable, generates the report and signs it off; an amendment needs a second administrator. Old accounts are converted on start-up (Verifier -> Tester, Approver -> Admin; an account that would be Admin + Tester stops start-up with a list). Released reports and old audit entries keep their wording. |
| D11 | **The customer is notified only when the final report is released** (plus *request received* and *request returned*). | No progress or per-test notices to customers; one release notice per released version, linking to the report. Every notification stores the page it opens and whether it needs action. |
| D12 | **Formal test names from one list** (`NAMES` in `app.py`). | Display names only; stored keys unchanged. |
| D13 | **Excel templates mirror the scanned logsheets** (11 Oct 2026). | Version 2 of every logsheet template (`paper_templates.py`): paper order and labels, locked printed and calculated cells, dropdowns, number and date limits, hidden fingerprint; version 1 retired and still importable. |

Still assumed (flag if wrong): the customer sees **values only for approved sections**; sections that are uploaded but not yet verified show as *Pending verification* with no numbers, so a customer never sees data that may later be corrected.

---

## Implementation progress (updated after each phase)

Priorities set on 2026-10-10: **data integrity**, **separate roles (customer first)**, **Excel extraction across multiple test reports**.

| Phase | Status | What landed | Tests |
|---|---|---|---|
| 1. Accounts and login | **Done 2026-10-10** | See below | 75 pass (60 existing, updated to sign in by role, + 15 new in `tests/test_auth.py`) |
| 2. Audit v2 + data model (+ the lock rules of phase 5) | **Done 2026-10-10** | See below | 86 pass (+ 11 in `tests/test_integrity.py`) |
| 3. Workflow engine | **Done 2026-10-10** | See below | 101 pass (+ 15 in `tests/test_workflow.py`) |
| 4. Excel templates (+ F5 audit) | **Done 2026-10-10** | See below | 119 pass (+ 17 in `tests/test_excel.py`; validity and app tests updated for F5) |
| 5. Integrity (amendments, manifest, retention) | **Done 2026-10-10** | See below | 125 pass (+ 6 in `tests/test_amend.py`) |
| 6. Customer portal, partial report, notifications | **Done 2026-10-10** | See below | 133 pass (+ 8 in `tests/test_portal.py`) |
| 7. Hardening | **Done 2026-10-10** | See below | 135 pass (+ load test, + scan switch test) |
| 8. Report format, customer-only requests, tickets, no same-day target | **Done 2026-10-10** | See *Follow-up 2026-10-10 (evening)* | 143 pass (+ format, caching, request form, return and correction, tickets) |

### Phase 1 (done): what changed

- **`auth.py` (new):** `users` and `orgs` tables; roles Admin / Tester / Verifier / Approver / Customer; `PERMS` permission map; `@require(...)`, `@public`, `@signed_in`. A `before_request` gate refuses any route that names no permission, so a new route cannot ship unprotected.
- **Login:** werkzeug password hashes; Flask signed cookie (`HttpOnly`, `SameSite=Lax`); secret key generated on first run into `.aletheia_secret` next to the DB (git-ignored); 30-min idle and 12-h absolute timeout; lock for 15 min after 5 failures; every failed attempt audited with the workstation IP; equal-time check for unknown usernames.
- **First run:** `/api/setup` creates the first Admin, only from the server PC itself (localhost), then closes for good.
- **CSRF:** every state-changing call needs `X-CSRF-Token` (handed out by `/api/me`); public POSTs must be JSON (forces a CORS preflight cross-site).
- **Accounts:** Admin creates users with a temporary password; the user must change it at first sign-in. Password rules: 10+ chars, common-password list, no username inside. Accounts are disabled, never deleted. Role or active changes and password resets end that user's sessions (`session_epoch`). The last active Admin cannot be removed.
- **Role combinations:** Tester/Verifier/Approver may be combined; **Admin and Customer stand alone** (Admin cannot hold a data role: rule §2.4.3).
- **Customer organisations:** `orgs` table; `jobs.org_id`; a customer account belongs to one organisation and sees only its jobs (another organisation's job id returns 404, not 403, so ids reveal nothing).
- **Customer view:** progress per test and the released report only. No values, findings, files, audit or staff names in any API response. Report PDF only once released.
- **Approval:** identity comes from the session (name + employee ID from the user record); typed names are ignored. Approver **re-enters their password** to sign (`REAUTH_ON_RELEASE`, on by default). An approver who imported, entered or checked data on the job (any audit entry of kind `data`/`check`/`verify` by them) is refused. The old "engineer name on the work instruction" check stays. `ALETHEIA_APPROVERS` env list is retired (the Approver role replaces it).
- **Audit:** every entry now records `user_id`, actor name, role(s), IP and a `kind` (`job, data, check, verify, report, approve, admin, auth, denied`). Permission denials are audited (§2.4.6). Admin audit viewer at `/api/audit` with filters (job, user, kind, dates).
- **Page:** `static/auth.js` (new): sign-in, first-run set-up, forced password change, user menu, role-based navigation, Admin "Users & customers" and "Audit log" pages, customer "My jobs" with a progress bar per test. The staff assistant is hidden from customers.
- **Demo loader** no longer calls the app through an internal test client (that would bypass/break the permission gate).

Deviations / decisions taken (flag if wrong):
- Admin may import historical **registers** (not test data) and create customer organisations; testers may also create organisations at intake.
- Approver password re-entry is **on** by default (plan said optional).
- Separation of duties is computed from the audit trail (who did what on the job), which keeps working when the section model of Phase 2 lands.

### Phase 2 (done): what changed

Data integrity was the top priority, so the **lock rules from phase 5 (§6.1) were pulled forward** into this phase. The amendment flow (§6.5) is still to come.

- **`integrity.py` (new).**
- **One row per section** (`sections`: state, data, data SHA-256, file, uploader, upload time, verifier, `revision`). The job's `data` dict is assembled from these rows at read time, so `validate()` and `build_pdf()` are unchanged. Imports write only the sections they bring, inside one `BEGIN IMMEDIATE` transaction. Merged sections (`ids`, `request`, `other`) are read and written in the same transaction. Two testers uploading different tests to one job at the same moment both persist (tested with threads).
- **Optimistic locking:** a hand edit must name the revision it started from. A stale or missing revision on an existing section returns 409 "changed by X at hh:mm, reload". The page sends the revision.
- **Append-only history:** every write, replacement and removal of a section is copied into `section_history` (who, when, file, data hash). `GET /api/jobs/<id>/history` returns it.
- **Raw files kept:** every uploaded data file (Excel/CSV/JSON/DB) is stored byte-for-byte in `files` with its SHA-256 (`GET /api/files/<id>`); `imports.file_id` links it.
- **Atomic numbering:** `auto_ids: true` on `POST /api/jobs` allocates the next `CPRIBLRSCL{yy}T{nnnn}` and `HVD{yy}S{nnnn}` inside the insert transaction (`counters` table, continues after the highest number already used). 6 parallel creations give 6 distinct consecutive numbers. The New request form allocates by default; typing a number is still possible.
- **Audit hash chain:** each entry stores `prev_hash` + `entry_hash`, sealed in the same write transaction as the insert (no fork under concurrency). `GET /api/audit/verify` (Admin) recomputes it, reports the first changed or removed entry, and returns the **tip** hash. Removing the *newest* entries can only be detected against a recorded tip, so the tip should be written down or exported daily (§6.3).
- **Database triggers** (defence in depth, `integrity.TRIGGERS`): audit rows cannot be deleted or changed once sealed. Stored reports, files and section history cannot be changed. For a released job: its sections, files, sources, history, approved reports and the job row itself cannot be changed or deleted.
- **Lock rules in the API (§6.1):** after release, import, section edit/remove, record edit, checks, review, generate, attach/remove sources, remove import and withdraw (`discard`) all return 409. `delete` was already refused for released jobs. The page hides those controls on a released job.
- **Delete of an unreleased job** removes its data and files but **keeps its audit entries** (audit is append-only), and logs the deletion.
- **Migration (schema 1 → 2):** numbered (`schema_version`). On start-up a schema-1 database is first copied with SQLite's online backup to `aletheia.db.pre-v2-<timestamp>.bak`; then each job's blob is split into sections, and existing audit rows are sealed into the chain. Tested on a synthetic schema-1 DB and on the Phase 1 scratch DB.
- **Page:** each section in the Sources card shows who uploaded it, from which file, and its revision.

Still open from this area: the amendment flow and report manifest (§6.2, §6.5); the daily export of the audit tip and the backup/restore drill (§6.6). Both are planned in phase 5.

### Phase 3 (done): what changed

- **`workflow.py` (new):** intake rules, PIN-code table, ownership, progress and sign-off readiness. Pure functions; `app.py` calls them inside its transactions.
- **Section states** (§3.2): `uploaded → verified` (locked), with side exits `returned` (reason required) and `na` (reason required). Routes: `POST /api/jobs/<id>/sections/<key>/verify | return | reopen | na`.
  - Verify and return must name the **revision** the verifier looked at; a newer upload makes the verification fail (409).
  - Verified sections are locked in the app (409) **and** in the database (trigger `sections_verified_data`). Only a verifier's **reopen with a reason** unlocks one.
  - Every state change goes into the section history with the reason.
- **Separation of duties** (§2.4): nobody verifies or returns a section they uploaded. Nobody signs off a job they uploaded data to. The approver rule from phase 1 now also counts verification. Every refusal is audited (`Refused: ...`, kind `denied`).
- **Ownership and assignment** (§4.3, rule 2.4.5): a test belongs to its assigned tester, else to whoever first uploaded it. Another tester's re-upload is refused (403), and only an Admin can reassign. Testers can be limited to certified test types (`users.test_types`); an uncertified tester can neither upload nor be assigned the test.
- **Whole-job sign-off** (§3.4, B5): `POST /api/jobs/<id>/signoff` (Verifier) needs every uploaded section verified or N/A, every planned test present (or N/A), and checks run without data errors. Any later data change voids it. **Generate now requires the sign-off.**
- **Test plan** per job (`jobs.plan`), chosen at intake. Planned tests that are missing block sign-off; tests outside the plan are listed as such.
- **Strict intake** (§3.6, D4): `POST /api/intake/check` (dry run, the whole list of problems at once) and `POST /api/intake` (create).
  - **Required fields:** customer, address, city, state, PIN, contact, phone, email, product, rating, serial no., manufacturer, drawings, tests, standard, witness yes/no (+ name), decision rule, arrival time, "box opened by", customer organisation, test plan.
  - **Format rules:** PIN = 6 digits, not starting with 0; phone 10-12 digits (+ country code); valid email; Indian state/UT from a list; rating = number + unit; arrival not in the future.
  - **Not applicable:** `NA`, `-`, `nil`, "not applicable" and blanks are refused. Fields that may genuinely not apply take an explicit not-applicable with a reason, stored as "Not applicable: reason".
  - **PIN/state consistency:** an offline table of PIN prefixes; a mismatch must be confirmed and the confirmation is audited.
  - **Numbering:** series and sample numbers are **allocated only when the list is empty**.
  - **What intake records:** arrival, opened-by, received-by, assignments, and the customer's form file kept as a hashed source document.
- **Read-back** (§3.6): `POST /api/jobs/<id>/intake/checked` records who compared the entries with the original form. **Release now requires a valid and checked intake.** Older jobs, and jobs started from a data file, complete theirs via `POST /api/jobs/<id>/intake`.
- **Test bays** (§4.2): `bays` table (Admin adds, retires, never deletes). Uploads record bay id and name (`bay_id` on import / section save). The page remembers the bay per workstation.
- **"My work"** (§2.5): `GET /api/my-work`, oldest first. Testers see returned items with the reason, assigned tests, intakes to complete, and recent uploads. Verifiers see sections to verify and jobs ready for sign-off. Approvers see reports to approve (only jobs they did not work on).
- **Page:** a new "Tests and verification" card on the job page with state, uploader, bay, file link, revision, verifier, reason and assignment per test. It offers the actions the role allows: check-and-verify dialog (values next to the source-file link), return or reopen with reason, N/A, assign, sign-off, section history. Also new: the **Intake** page (live problem list, PIN/state confirmation, plan, assignment, customer form upload), the **My work** page, and **Test bays** on the Admin page. Buttons a role cannot use are hidden (the server refuses them regardless).
- **Fixes found on the way:** deleting a job left its assignments behind; job ids could be **reused** after deleting the newest job, which would have attached the old job's audit trail to a new one. Ids are now never reused, and deletes clear assignments.

Decisions taken (flag if wrong):
- Intake **required-field list** is my reading of the request form (Q14 still open): adjust `workflow.INTAKE_FIELDS`.
- The PIN table maps the **first two digits** to states. It is approximate (shared circles), so a mismatch asks for confirmation instead of blocking.
- "Not applicable" for a test is a **Verifier** decision (Admin does not touch test data).
- Old jobs keep working: the strict intake is enforced **at release**, not at creation of data-file jobs.

### Phase 4 (done): what changed

**"Excel across multiple test reports"** is implemented in four directions: one workbook holding several tests; one workbook holding several jobs; a job exported as filled logsheets; and many jobs exported as one register workbook.

- **`xltemplates.py` (new): the extraction engine.** One JSON mapping both **writes** a blank logsheet (yellow input cells, defined names, table headers) and **reads** a filled one.
  - **Locating single values:** by defined name, then label (exact, then fuzzy, so slightly reworded labels still match), then fixed cell. A name or cell whose neighbour no longer reads as the label is treated as drifted, and the label wins.
  - **Tables:** found by their header labels anywhere on the sheet, including two-row headers with group titles. Rows are read until the first blank row. Options: `rows_as` list / dict / values / row, `pick`, `keys`.
  - **Every value comes back with its cell and a status:** `ok`, `formula` (cached value taken as logged), `formula_unsaved` (refused), `missing`, `type`, `ambiguous` (a label found twice is never guessed), `not_found`, `hidden`. Value cells outside the mapping are listed.
  - **Values:** real Excel dates become dd-mm-yyyy. Decimal commas are converted only when the mapping says so; units are never guessed.
  - **Refused files:** `.xls`, `.xlsm` and damaged workbooks are refused with a reason.
- **`seed_templates.py` (new): version 1 templates.** One for each of the 9 logsheet documents plus the **customer request form**, laid out automatically from compact specs, with a defined name on every value cell. They seed the registry once; after that the mappings live in the database.
- **`excel_routes.py` (new):**
  - **Registry:** `templates` table with versions (draft, active, retired). Admin can create a version, edit a draft, attach a sample, test live (unsaved mapping), **test against past uploads** ("same as stored" / differs / errors), diff two versions, activate (the previous version is retired), and export/import JSON. Database triggers: a non-draft mapping can never change, and templates are retired, never deleted.
  - **Upload with preview:** `POST /api/jobs/<id>/excel/preview` shows every value with its cell, nothing stored. `.../excel/import` stores exactly that. A **required value missing blocks the section**; it is never stored as NA. The sheet's series number is compared with the job.
  - **Ordinary imports recognise logsheet workbooks automatically**, including "new job from a data file". The flat `section,field,value` layout still works (§5.9).
  - **Template version pinned per section** (`sections.template_id`). A new template version never changes stored data, and the job's export uses the version that read it.
  - **One workbook, several jobs:** `POST /api/excel/preview | import` routes each sheet by the series written on it (exact match, or a unique match on the last 7 characters, H read as 4). The user can change the routing. Each job gets its own file copy, audit entry and ownership checks.
  - **Downloads:** a blank logsheet per test or all tests in one workbook (`/api/logsheets/<test|all>.xlsx`); the **customer request form** (`/api/request-form.xlsx`, also allowed for customers); a job as filled logsheets (`/api/jobs/<id>/logsheets.xlsx`, round-trips back in); and the **records workbook** for many jobs (`/api/records.xlsx`, same filters as Records): sheets Jobs, Tests (per-test state) and Key values (as logged; only values from uploaded or verified sections).
  - **Intake from Excel:** `POST /api/intake/from-excel` reads the customer's filled form by its labels (it still works when the customer inserted rows) and pre-fills the intake page, which is still validated and read back.
- **F5 "don't use calculable parameters" (§5.5)** is done; the full classification of every check is in `docs/VALIDITY.md`.
  - Recomputations of logged figures are now **advisory**: no-load average and sum, SC rms average, injected loss, deflection maxima, reported vs computed oil rise. They never block, need no review and are not printed. The no-load average used to *block* the report.
  - Top-oil rise uses the **logged** value. Winding rises use logged `hv_rise`/`lv_rise` when the sheet has them; otherwise the formula, marked "calculated" (Q11).
  - The report prints logged hourly readings only (no computed mean-ambient or rise columns) and labels each rise "as logged" or "calculated".
  - The "failing job" sample file was updated so its *logged* rise is over the limit.
- **Page:** an Excel upload opens the **preview** (value, cell and status per field, errors per sheet) before anything is stored. Other additions:
  - "Upload a workbook for several jobs" on Report Workflow, with editable routing.
  - "Export to Excel" on Records; job page links to the blank logsheets and to the job as filled logsheets.
  - "Fill from the customer's Excel form" and "Blank request form" on Intake.
  - **Templates** page for Admin: versions, sample sheet grid with **click-a-cell-to-bind**, live test, past-upload test, diff, activate/discard, JSON import/export.
  - Advisory findings are tagged as such.

Open: Q8 (the lab's real logsheets). When they arrive, each becomes a new template version: label and table mappings work on sheets Aletheia did not draw, and the past-upload test shows whether a change is safe.

### Phase 5 (done): what changed

The lock rules and triggers of §6.1 landed in phase 2. This phase added the rest of §6.

- **Manifest (§6.2):** every report version stores a manifest.
  - **What it lists:** each section's revision, state, data SHA-256, source-file SHA-256, the template version that read it, uploader (+ bay) and verifier; plus intake received/checked by, sign-off, approver, software code id and schema, and what it supersedes.
  - **Where it appears:** its SHA-256 is stored (`reports.manifest_sha256`) and **printed on the last page** in a "Traceability of this report" annex. The verification page shows the manifest's sections and whether the stored manifest still matches its hash.
- **Approval is atomic:** the release PDF is built first; only if that succeeds is the job marked released. A failed build used to leave a job "released" with no report.
- **Amendments (§6.5):** `POST /api/jobs/<id>/amend`.
  - **Opening:** an Approver gives a reason (≥ 10 chars) and names the tests to correct, re-enters their own password, and a **second approver** confirms with theirs at the same workstation. A wrong second-signer password counts towards that account's lock-out.
  - **Effect:** only the named tests reopen (state *returned*, reason as note). Naming the request/intake clears the read-back, so it must be checked against the form again. Everything else stays verified and locked: in the app (409) and in the database (triggers `sections_amend_*` restrict changes to the named tests).
  - **Release:** the normal chain (upload → verify → sign-off → generate → approve) releases version n+1, which prints "supersedes version n" and the reason. The amendment is closed and kept (`amendments` table, which cannot be deleted or edited once closed).
  - **The earlier version** stays stored, verifiable and downloadable. The verification page says "Superseded by version n+1" with the reason; its download is named `_SUPERSEDED`. **Until the new version is released, the old one remains the valid report.**
  - **Customers** see every released version, with superseded ones listed under "Earlier versions" with the reason, and a "correction in progress" notice while an amendment is open.
- **Stronger triggers:** files, sources, history and the job row of a job that was **ever** released can never be deleted, even while an amendment has it open.
- **Retention (§6.6), `retention.py` (new):**
  - **Backups:** made with SQLite's online backup into `backups/` (or `ALETHEIA_BACKUP_DIR`), with a `.sha256` file. They run once a day automatically while the server runs (`ALETHEIA_AUTO_BACKUP=0` disables), plus "Back up now". The newest 30 (`ALETHEIA_BACKUP_KEEP`) are kept, and the first of each month is kept for good.
  - **Audit tip:** each backup appends the audit chain's **tip hash** to `audit-tip-YYYYMMDD.txt`. The Backups page shows today's tip to write down (§6.3).
  - **Backup check** (the restore drill without stopping the lab): checksum, `PRAGMA integrity_check`, row counts, audit chain, and every report PDF and data file against its stored hash, all inside the backup. Tested with a tampered backup.
  - **Record package** `GET /api/jobs/<id>/package.zip` for a released job contains:
    - every released PDF (superseded ones marked) and each version's manifest (byte-for-byte, so its hash equals the printed one);
    - source data files and documents, section history, amendments, data, and the audit extract with chain hashes;
    - a README on how to verify, and `SHA256SUMS.txt`.
  - **Clock check:** the page warns when the workstation's clock and the server's differ by more than 2 minutes.
- **Page:** "Amend this report" dialog (reason, tests, own password, second approver) and an amendment banner on the job page; a "Record package (zip)" link; a richer **verification page** (valid / superseded / draft, amendment reason, manifest hash check, what the version was built from); version history on the customer's job page; and an Admin **Backups** page (back up now, check, today's audit tip).

Not done (flag if needed): **PDF/A** output. ReportLab does not produce PDF/A without extra colour-profile work, so the record package keeps the PDF, manifest and source data side by side instead. Also no **cancel** of an opened amendment: it must be completed, while the released version stays valid in the meantime.


### Phase 6 (done): what changed

- **Customer portal (§7.1, D3), `portal.py` (new):**
  - **Numbers only for approved (verified) tests**, as assumed in Q3b. `GET /api/jobs/<id>/approved-values` returns them **labelled as on the logsheet** (from the template that read them), tables included. Pending tests show status only, and no API response, PDF or email gives a customer a value from an unapproved test (tested).
  - **Partial report** (`/api/jobs/<id>/partial.pdf`): built from the approved tests only, title "PARTIAL REPORT, NOT FINAL", a watermark on every page, and a status table (approved / pending). It has no verdicts, no statement of conformity, no signatures, no QR and no staff names, plus a list of the approved data with hashes.
  - **Versioning:** a new version is stored whenever the approved set or a revision changes, including when a test is reopened, which removes its values again. Every version is kept with its hash (`partials`, unchangeable), so what a customer saw at any time can be reproduced (`?v=`).
  - **Customer page:** progress, a target time, the partial report and its earlier versions, approved values per test, every released version, and the **request forms** they sent.
  - **Request forms from customers:** a customer downloads the Excel form and sends the filled copy (`POST /api/customer/request-forms`). Testers are notified, the intake page shows an **inbox**, and "Use for this intake" pre-fills the fields and the organisation. The created job keeps the customer's file byte-for-byte, and the customer sees "Used for <series>".
- **Same-day target (§7.2, D2), `notify.py` (new):**
  - **Cut-off:** Admin sets the daily cut-off and the warning window (Settings). Each intake gets a cut-off on its arrival day; arrivals after the cut-off get the next day's (Q12).
  - **Today board** (`/api/today`): every open job with its cut-off, time left, green / amber / red, tests not uploaded / awaiting verification / returned **with their owner**, and sign-off state.
  - **Carried over:** a job past its cut-off is not blocked; it needs a recorded reason (`/carry-over`).
  - **At release:** `completed_at` and `same_day` are stored; stats report "same day: x of y".
- **Notifications (§7.3, D5):**
  - **In-app:** notifications (bell with unread count, Notifications page, mark read). They are triggered by upload (verifiers; customer: progress), return (uploader, with reason), approval of a test (customer: partial updated), everything verified (verifiers: ready for sign-off), report generated (approvers), release (customer and testers) and cut-off approaching (job's testers and verifiers, once). Nobody is notified of their own action.
  - **Email (optional):** SMTP settings in Admin Settings, password only in the `ALETHEIA_SMTP_PASSWORD` environment variable. Mails are queued in an **outbox** and sent by a background worker (every minute) with 5 retries and growing delays. Failures show in the outbox and **never block work** (tested with a failing transport).
  - **Email content:** job number, what changed and a link only. No values, no attachments (tested). Customers can opt out of non-critical mail; returns, releases and cut-off warnings are always sent.
  - Every notification and send attempt is audited (kind `notify`).
- **Page:** Today board, Notifications page and bell, Admin Settings (cut-off, warning window, SMTP, portal address, outbox with "Send now"), the customer additions above, and the request-form inbox on Intake.

### Phase 7 (done): what changed

- **Load test** (`tests/test_load.py`): eight sessions at once on one database, finishing in about 7 s:
  - three testers uploading to their own jobs and, round after round, to one shared job (different tests each);
  - two verifiers verifying whatever is waiting;
  - an administrator reading the audit log, a tester watching Today, an approver listing jobs.

  Result: no server error. Every test of the shared job holds the last upload that was accepted (later ones were correctly
  refused once a verifier had verified the test). Every section's revisions run 1..n with none lost or duplicated, there is
  one import record per accepted upload, and the audit chain is intact.
- **Already covered in earlier phases:** the route × role permission matrix, concurrency tests and template-drift tests.
- **Scanning demoted (§8):** AI reading of scans is now off unless `ALETHEIA_FEATURE_SCAN=1`. The scan routes answer "turned off", the page hides the Scan controls, and attaching scans as evidence still works. The code and its tests stay.
- **Race fixed (found by the load test):** two verifiers approving tests of the same job at the same moment could both claim the next partial-report version (server error). Rebuilds are now serialised and retried.
- **Several-jobs workbook:** every target job is checked before anything is imported, so an unknown job can no longer leave the import half done.
- **Docs:** README rewritten (roles, workflow, integrity, settings, API groups, tests, files); ARCHITECTURE.md (new modules, data model, lifecycle); **`docs/LAB_WORKFLOW.md`** (§9, F10: the lab-facing recommendations, each with how Aletheia supports it); the in-app Architecture page's "production path" updated.

### Follow-up 2026-10-10 (after review)

- **Customers fill in the request themselves:** "New test request" on the customer's page is an online form with the same rules as intake, minus arrival and box opening (which the laboratory records). Problems are checked as they type, and the request lands in the intake inbox; testers and admins are notified. "Use for this intake" pre-fills every field, the organisation and the requested tests. The job keeps the request exactly as submitted (`Customer request (filled online).json`).
- **Assignment:** the Admin assigns a test, or the whole job (every planned test nobody started or took; uncertified ones skipped), to a test engineer, with a bay, and can reassign. A test engineer **takes** an unassigned, unstarted planned test, choosing the bay, and can give it back before starting; they can no longer assign others. Uploads without a bay use the assignment's bay, and assignees are notified.
- **Dashboard "Your tasks"** for every role:
  - Engineers: to test (with bay), available to take ("Take" button), returned, intake to complete, customer requests.
  - Verifiers: to verify, ready for sign-off. Approvers: to approve.
  - Admin: reports to approve, tests not assigned, customer requests waiting, awaiting verification, locked accounts.
- **UI fixes:** the audit filter bar is aligned on one row (a global 300 px select width meant for the Preview page was squeezing forms); all inputs and selects have the same height; the user area is now an avatar menu (name, role, employee ID / organisation, links, change password, sign out).
- **Dashboard emblem:** a seal in the manner of the CPRI emblem (double ring with lettering, lightning, ribbon) around a distribution transformer, over a short-circuit current trace instead of the pylons. The headline matches today's work.
- **Architecture** page and ARCHITECTURE.md rewritten for the current system (roles, modules, data layer, life of a job, who assigns tests).

Not done, by decision: moving `trocr-env/` and the stray `sersenzy…test.db` out of the parent folder (`ATRG-Merged/`). They are outside this repository, and I did not move your files without asking.

### Follow-up 2026-10-10 (evening)

- **Test report in the lab's format (D6), `report.py` (new):** CPRI header, report number and date box, the ULR / laboratory
  footer with *Sheet n of N* and the test engineer's signature line on every sheet. Sheets: cover (documents constituting the
  report, in words), description of the sample, summary of tests conducted (IS 1180 clauses with the sheet of each test),
  list of drawings, routine results (winding resistance and impedance / load loss at 75 C as logged, ratio with tapping %,
  phase displacement, no-load), routine contd. (energy efficiency, IR, induced, separate source), short-circuit withstand
  (conditions, current calculation, oscillograms per tap, thermal shot), reactance and inspection, oil leakage and routine
  pressure, temperature rise, type pressure / vacuum, no-load current at 112.5 % with the conclusion, notes with the
  accreditation mark, verification QR and traceability annex. Sheet numbers are learnt by laying the report out twice. Partial
  reports use the same layout (watermark, no signatures, no ULR). New optional template fields: energy efficiency, coil, core,
  winding details (proforma), atmospheric pressure (pressure logsheet).
- **No same-day target (D7):** `/api/today`, the Today page, carry-over, the cut-off setting and warnings, and the same-day flag
  are gone.
- **Caches:** the page and scripts are revalidated on every load (`Cache-Control: no-cache`), API answers are never cached
  (`no-store`), so a browser never runs an old script after an update.
- **Customer request form (D8):** `workflow.REQUEST_FIELDS` / `LAB_FIELDS` follow CPRI/QAF/01A. The customer fills in sheets 1-2
  online (`static/request.js` lays it out as the printed form, checked as they type, with the tests to tick). The request waits
  in **Customer requests**; the engineer sees it as sent, records sheet 3 and the plan and accepts it (numbers allocated), or
  returns it with the reason (`/api/request-forms/<id>/return`); the customer corrects it and sends it again (the old one is
  marked replaced). `/api/intake`, `/api/jobs` and `/api/jobs/from-file` need a customer's request; data files never change
  the request section; record edits are limited to the identifiers; the staff *New request* page, the assistant's new-request
  flow, the Excel intake and the customers' Excel upload are removed; the demo loader needs `ALETHEIA_DEMO=1`.
- **Customer tickets (D9), `tickets.py` and `static/tickets.js` (new):** customers raise tickets (category, subject, message,
  optionally a job); administrators are notified, see them as a dashboard task, answer, close and re-open them.

---

## 0. Where the code stands today (what the plan builds on)

| Area | Today | Gap against the briefing |
|---|---|---|
| Users | None. No login. The approver types a name and employee ID into a form (`approve()` in `app.py`). `ALETHEIA_APPROVERS` is an optional env-var list. | No identity, no roles, no permissions. Anyone who can open the page can do everything. |
| Audit | `audit(job_id, event, at)`: free text, **no actor**. | Briefing: "who uploaded what, who verified it"; "activity logs should mention all details". |
| Data model | `jobs.data` is **one JSON blob** with a key per document (`request, proforma, work, losses, resistance, noload, routine, sc, temp, pressure`, plus `ids`, `other`). | Several testers write to the same job at once. Whole-blob read-modify-write (`apply_import`: `d[k] = ...` then `save`) means **two simultaneous uploads can overwrite each other**. No per-section owner or status. |
| Import | `importers.py` reads CSV / XLSX / SQLite / JSON, but only in a fixed shape: rows of `section, field, value`. | Real lab Excel sheets are not in that shape. Templates change. Extraction must adapt (VIMP). |
| Validation | `validate()` runs 30 checks. Many **recompute** values: averages, sums, oil rise, loss sums, "reported vs computed". The report uses the computed value in places. | Faculty: **don't use any calculable parameters.** Take the logged value as-is. |
| Release | Stages 0-4. Approver must differ from the test engineer. Released report cannot be deleted but **can be withdrawn** (`discard`) and **edited** (`edit` sends stage 4 back to 3). | Faculty: once submitted, **no changes allowed.** The document is a legal entity kept 10+ years. |
| Report | `report_template.json` holds wording only. Layout is in `build_pdf` code. | Report template can change; layout and cell mapping must be configurable. |
| Auto numbering | Series and sample number are generated/validated (`SERIES_RE`, `SAMPLE_RE`, `check_ids`). | Already done (VIMP #8). Keep; make allocation atomic under concurrent use. |
| Deployment | Flask + SQLite, localhost, runs on a normal PC. | Matches notes 1-3. Keep it that way: no external services, no heavy dependencies. |

---

## 1. Briefing traceability (every point, where it lands)

### 1.1 Lab process (briefing)

| # | Briefing point | Plan |
|---|---|---|
| B1 | Product reaches the designated lab | **Intake step** (§3.1), done by the receiving test engineer: record arrival date/time and who received it. Starts the same-day clock (D2). |
| B2 | Security opens the box (no QR code) | Intake records "opened by" + time. **No QR on the product/box**; the product is identified by the generated sample number. (The report-verification QR is a separate matter: see Q6.) |
| B3 | Customer's test report file is opened (given by the customer) | Intake step attaches the customer's file (Excel/PDF) as a hashed source document. |
| B4 | Customer report form is given to the customer to fill | Intake generates the **customer request form** (Excel template, §5) for download; customer's filled copy is uploaded back. |
| B5 | A testing person verifies all the data is correct | New **Verifier** step per section, then whole-job sign-off (§3.4). |
| B6 | Everything so far is manual | Intake, form issue and verification become tracked steps in the app instead of paper. |
| B7 | The document is a legal entity; nothing can be wrong (pin code) | Integrity model (§6) + strict completeness/format validation at intake (§3.6). The "pin code" was an example of a value that can't be missing or wrong (D4). |
| B8 | Most documents have a tenure of 10+ years | Retention and archive plan (§6.6). |
| B9 | All products must be CPRI tested | Job cannot be created without CPRI test series; no "external lab" path. |
| B10 | Testing is done at multiple places, not in serial order; whichever bay is free is used | **Sections are independent** (no required order); each tracks its own status; record the **test bay** on every upload (§4.2). |
| B11 | Add who uploaded what log and who verified it; add permissions | Core of §2 (roles) and §4 (per-section ownership). |
| B12 | Ministry of Power: 15 days per report maximum | 15-day clock dropped; **same-day target** with a cut-off time and an "at risk" list (§7.2, D2). |
| B13 | Whatever you have tested must also be visible | Customer sees **per-test status, approved vs pending, and a partial report that grows as sections are approved** (§7.1, D3). |
| B14 | Maybe a client-side version to check status and current report | **Customer role + portal** on localhost (§7), with upload notifications (§7.3). |

### 1.2 Faculty notes

| # | Note | Plan |
|---|---|---|
| F1 | Must be localhost-based | Keep Flask on the lab LAN/localhost. No cloud. All customers are on localhost (D5), so the exposure question is closed. |
| F2 | Must work on a normal computer | No new heavy dependencies. Auth uses what Flask/Werkzeug already ship. Excel work stays on `openpyxl`. |
| F3 | Multiple users report at the same time (already done) | Re-verify after the data-model change (§4.1): concurrency was only safe at the job level. Add concurrent-write tests. |
| F4 | Extract data from Excel (done); improve with templates | §5 template registry. |
| F5 | Don't use any calculable parameters | §5.5 and §6.4: audit and strip derived values. |
| F6 | The main thing: Excel extraction, fitted into the required cells | §5 is the centre of the product. Extraction output maps to named fields; report cells are filled from those fields. |
| F7 | Activity logs mention all details | §4.5 / §6.3 audit redesign. |
| F8 | VIMP: automatic sample and test number (done) | Keep. Make allocation atomic; show the number on every screen/printout. |
| F9 | Different people do different tests and upload their own data; the report is common | §4: per-section ownership inside one shared job and one shared report. |
| F10 | Change their workflow to make the process easier (not part of the repo) | §9: separate recommendations document for the lab. |
| F11 | Focus on report integrity (once submitted, no changes) | §6. |
| F12 | VIMP: the report template may change; extraction must be versatile | §5: template-driven extraction with versioned templates and an admin mapping tool. |

---

## 2. Roles, login and permissions (priority 1)

### 2.1 Roles

| Role | Who | Can do | Cannot do |
|---|---|---|---|
| **Admin** | Lab head / system owner | Create and disable users, assign roles, manage templates and test bays, set SLA rules, view every job and the full audit log, run backups/exports, see system health | Edit, approve or delete any test data. **Admin is not a super-tester.** Admin cannot sign off a report (separation of duties). |
| **Tester** | Test engineers (also do **intake**, D1) | Receive the filled customer request form, create the job and allocate series/sample number, upload Excel logs **for the test types they are assigned**, correct their own uploads **until verified**, record test bay and times | Verify their own upload, sign off a report, edit another tester's section, touch anything once locked |
| **Verifier** | "A testing person verifies" (B5) | Review any section uploaded by someone else, mark verified or return with a reason, run the whole-job check | Verify a section they uploaded themselves |
| **Approver** | Authorised signatory (today's `approve()`) | Final sign-off and release of the report | Approve a job they uploaded or verified any section of (see §2.4) |
| **Customer** | Client on the localhost network | See only their own jobs: approved vs pending, the partial report so far, the final report once released, notifications | See other customers' jobs, see values from sections not yet approved, change anything except filling their request form |

Verifier and Approver can be the same *person type* with two permission flags, but never the same person on the same job. Small lab? Fewer people than roles: the rule is "different person per step on a given job", not "different people overall".

### 2.2 Permission matrix (what to enforce on the server)

| Action | Admin | Tester | Verifier | Approver | Customer |
|---|:-:|:-:|:-:|:-:|:-:|
| Intake: create job from a filled request form, allocate series + sample no. | - | yes | - | - | - |
| Upload / replace section data (own assignment, before verification) | - | yes | - | - | - |
| Verify / return a section | - | - | yes (not own) | - | - |
| Generate partial / draft report | - | yes | yes | - | auto (read-only view) |
| Approve / release final report | - | - | - | yes | - |
| Amend a released report (new revision, §6.5) | - | - | - | yes (+ reason, second signer) | - |
| View all jobs | yes | yes | yes | yes | no |
| View own jobs only | - | - | - | - | yes |
| Download released PDF | yes | yes | yes | yes | yes (own) |
| Download partial report | yes | yes | yes | yes | yes (own) |
| Manage users / templates / bays / notification settings | yes | - | - | - | - |
| Read audit log | yes | own jobs | own jobs | own jobs | - |

Every row is enforced in the API, not just hidden in the UI. Add a single `@require(role|permission)` decorator and a test that walks **every route** and asserts a role-to-status-code table, so a new route cannot ship unprotected.

### 2.3 Login design (works on a normal PC, no new services)

- **Storage:** new `users` table: `id, username (unique), full_name, employee_id, role(s), password_hash, active, must_change_password, failed_attempts, locked_until, created_by, created_at, last_login`. Passwords hashed with `werkzeug.security` (already installed with Flask): scrypt/pbkdf2, never stored or logged in clear.
- **Session:** Flask signed cookie (`HttpOnly`, `SameSite=Lax`), secret key generated at first run and kept in a file outside git. Idle timeout (e.g. 30 min), absolute timeout (e.g. 12 h). Explicit logout. One user may have several sessions (several PCs in the lab), and Admin can end them.
- **First run:** no users exist, so the app shows a one-time **create-admin** page (localhost only); afterwards that route is permanently disabled.
- **Admin creates accounts**, sets a temporary password, forces change at first login. No self-registration. Customers are created by Admin (or by the intake tester, with the customer's email taken from the request form) and tied to a **customer organisation**.
- **Brute-force guard:** lock after N failures for M minutes, log every failed attempt (with workstation/IP).
- **CSRF:** all state-changing routes need a token (cookie sessions make this mandatory). Currently every route is a bare `POST`.
- **Replace the typed approver fields:** `approve()` takes identity from the session. The employee ID comes from the user record. The "approver must differ from the test engineer" check becomes a user-ID comparison (today it compares **names as typed**, which is easy to bypass).
- **Re-authentication at sign-off (optional):** the approver re-enters their password at the moment of release. The "pin code" in the briefing turned out to be a location example (D4), so no separate PIN is needed. Implement the re-auth once and reuse it for verification and amendments if the lab wants it.
- **Password rules:** minimum length, no composition theatre, block the obvious list; Admin reset (never "view").
- **Account lifecycle:** disable, never delete (the history must still resolve "user 17" to a name for 10+ years). Role changes are audited.
- **Optional later:** TOTP second factor for Approver/Admin.

### 2.4 Separation-of-duties rules (server-enforced, tested)

1. A user cannot verify a section they uploaded.
2. A user cannot approve a job in which they uploaded **or** verified any section.
3. Admin cannot upload, verify or approve.
4. A Customer sees only jobs linked to their organisation.
5. Re-upload by a different tester than the original owner needs Admin reassignment (logged), not a silent overwrite.
6. Any rule violation returns 403 and writes a "denied" audit entry.

### 2.5 UI changes for login/roles

- Login page; header shows name, role, logout.
- Navigation and buttons rendered per role (and the server still refuses the call).
- **My work** page per role: Tester → my uploads + sections waiting on me; Verifier → sections awaiting verification; Approver → jobs ready for release; Admin → users/templates/audit; Customer → my jobs.
- Admin screens: Users, Test bays, Templates (§5), Audit viewer with filters (job, user, date, event type).

---

## 3. The end-to-end workflow (priority 1)

The 0-4 stage model becomes a **job state** plus **per-section states**, because testing is parallel and out of order (B10).

### 3.1 Job lifecycle

```
1 INTAKE ──> 2 TESTING (parallel sections) ──> 3 VERIFICATION ──> 4 PARTIAL/DRAFT REPORT ──> 5 APPROVAL ──> 6 RELEASED (locked)
 (tester,      (testers upload Excel,           (verifier(s) check   (grows as sections        (approver)        (read-only;
  clock starts) any order, any bay)              each section;        are approved;                            changes only via amendment)
                                                 customer notified)   customer can view)
```

| Step | Who | What happens | Records |
|---|---|---|---|
| **1 Intake** | Tester (the engineer who receives the filled request form) | Product arrives; box opened (no QR); customer's report file opened and attached; filled request form checked against §3.6; series + sample number auto-allocated | Arrival time, opened-by, customer, customer file SHA-256, same-day cut-off (§7.2) |
| **2 Testing** | Testers | Each assigned test is done in whatever bay is free; the tester uploads that test's Excel log into its section | Section owner, bay, upload time, file name + SHA-256, template version |
| **3 Verification** | Verifier | For each uploaded section: compare extracted values with the source file; mark **Verified** or **Returned** with a reason | Verifier, time, outcome, reason |
| **4 Report draft** | Tester/Verifier | Once all required sections are Verified, the report is assembled into the template's cells. Preview available any time with a "DRAFT, not valid" watermark | Template version used |
| **5 Approval** | Approver | Reviews the assembled report, re-authenticates, signs | Approver, time, report SHA-256 |
| **6 Released** | system | Report and all its inputs lock. Customer notified in the portal | Final hash, release time, days elapsed vs 15 |

### 3.2 Section states (per test document)

`Not started → Uploaded → Verified (locked)`, with side exits `Returned (needs re-upload)` and `Not applicable (admin/verifier-recorded reason)`.

- Required sections are defined by the **job's test plan** chosen at intake (not every product needs every test).
- Re-upload while *Uploaded* or *Returned*: allowed for the owner; the old file stays in history (never overwritten). After *Verified*: locked.
- The job can be partly done at any time; the customer-facing view shows that state (B13).

### 3.3 Order independence

No state may require "test A before test B". The only hard gates are: *report draft needs all required sections verified*, *approval needs a draft*. Dashboard shows bay usage and which sections are outstanding.

### 3.4 Verification detail

- Side-by-side view: original Excel values (or cell preview) vs the extracted fields.
- Verifier can **flag**, **return** (with reason, notifies the owner) or **verify**.
- Verification covers the *extraction fidelity* (what is in the app equals what is in the file) plus the tester's recorded values. It does not recompute physics (F5).
- Whole-job sign-off by a Verifier ("all data correct") before the report draft is allowed. This is the digital version of B5.

### 3.5 Notes on today's code that must change

- `data_changed()` resets the job to stage 1 and clears findings and approver on **any** edit. In the new model an edit to one section must not disturb other sections or other testers' work.
- `edit()` (post-approval edit) and `discard()` (withdraw a released report) go away for released reports (§6.5).
- `delete()` stays only for never-released drafts, Admin-only and audited.
- `STAGES` / `stage` int is replaced (or derived) from the section states.

### 3.6 Intake validation: nothing missing, nothing wrong (D4)

The postal PIN code was the example: a record with a missing or malformed PIN code is a wrong record, and the report is a legal document. Today `check_ids()` in `app.py` allows `NA` for everything except the series number. That is too loose for the request form.

- **Required fields at intake** (exact list from the request form, confirm with the lab): customer name, address lines, city, state, **PIN code**, contact person, phone, email, product description/rating, serial number, manufacturer, tests requested, reference standard, witness (yes/no and who).
- **Format rules:** PIN code = 6 digits, first digit 1-9; phone = digits with optional country code; email = valid format (needed for notifications, §7.3); dates real and not in the future; rating numeric with unit; sample code and series in the CPRI formats (existing `SERIES_RE`/`SAMPLE_RE`).
- **No `NA` for a required field.** If something truly doesn't apply, the form has an explicit "Not applicable" choice that needs a reason and is shown on the report.
- **Optional consistency check:** an offline PIN-code to state/district table so a PIN that doesn't match the typed state is flagged. Ship as a small data file, no internet needed.
- **Completeness checklist:** the intake screen lists every missing/invalid field; the series and sample numbers are **not allocated until the list is empty**, so no half-filled job exists.
- **Read-back:** after saving, the screen shows the entered values next to the customer's uploaded form for the receiving engineer to tick "checked against the original".
- Same philosophy applies later: required cells in Excel extraction (§5.4) that are empty block the section; they are not silently stored as `NA`.

---

## 4. Shared report, many testers (F9, B11, B10)

### 4.1 Data model change (do this first; it unblocks everything)

Replace the single `jobs.data` JSON blob with **one row per section**:

```
sections(
  id, job_id, key,                -- e.g. 'noload', 'sc', 'temp'
  state,                          -- not_started | uploaded | returned | verified | na
  data JSON,                      -- extracted fields for this section only
  template_id, template_version,  -- which mapping produced it
  source_file_id,                 -- FK to files (hashed Excel, stored as BLOB)
  bay_id,
  uploaded_by, uploaded_at,
  verified_by, verified_at,
  revision INT                    -- optimistic lock counter
)
files(id, job_id, name, mime, sha256, content BLOB, uploaded_by, at)   -- immutable
```

- Writes use `UPDATE ... WHERE id=? AND revision=?`: a concurrent change returns 409 "changed by X, reload", never a silent overwrite.
- The report reads the sections and assembles `data` at build time, so the current `validate`/`build_pdf` can keep their `data` dict input during migration.
- Migration: a script that splits existing `jobs.data` into sections, with `uploaded_by = 'migrated'`. Take a backup first (the repo already uses `backups/`).
- Series/sample allocation: do it inside one `BEGIN IMMEDIATE` transaction so two intake users cannot get the same number.

### 4.2 Test bays

`bays(id, name, active)`; a section upload records the bay. Admin manages the list. This gives the "which bay was free / used" trail and a utilisation view later.

### 4.3 Assignment

Admin or the intake tester assigns *test → tester* when the job is created (optional; defaults to "any tester with that test permission"). Tester accounts carry a **test-type permission list**, e.g. someone certified for short-circuit but not temperature rise. This implements "different people do different tests".

### 4.4 Uploader/verifier shown everywhere

Section header: `No-load test · uploaded by A. Rao (Bay 3) 10 Oct 10:42 · file noload_v2.xlsx (SHA-256 4f1c…) · verified by S. Iyer 10 Oct 14:05`. The same string appears on the review screen and as a footer line in the final report's traceability annex.

### 4.5 Audit redesign (F7)

`audit(id, job_id, section_key, user_id, role, workstation/IP, action, detail JSON, before_hash, after_hash, prev_audit_hash, entry_hash, at)`
- Actor is mandatory (system actions use a named system user).
- Log: login/failed login/logout, job creation, every upload (file hash, template version, count of fields extracted/unmapped), re-uploads, verify/return (with reason), draft builds, approval, downloads of released PDFs, permission denials, admin actions.
- Each entry stores a hash of the previous entry: tampering is detectable (§6.3).

---

## 5. Excel extraction with changeable templates (priority 2, VIMP F6/F12)

### 5.1 Principle

The Excel **template is data, not code**. When the lab changes a sheet layout, an Admin updates the mapping, the Python does not change. Every extraction records which template version produced it.

### 5.2 Template registry

```
templates(id, kind,               -- 'logsheet' | 'request_form' | 'report'
          test_key,               -- 'noload', 'sc', 'temp', ...
          name, version, status,  -- draft | active | retired
          mapping JSON, sample_file BLOB, created_by, created_at)
```

- A job pins the template versions it was created with. Old jobs keep reproducing from the version they used, so a template change never alters an existing report.
- Retired templates remain readable for 10+ years.

### 5.3 Mapping strategies (a mapping may mix them)

| Strategy | Use when | Robustness |
|---|---|---|
| **Fixed cell** (`Sheet1!C5`) | Sheet layout is rigid | Breaks if a row is inserted |
| **Named range** (workbook defined names) | Lab can edit their own sheets | Survives row/column insertion. **Best option: ship the lab's logsheets with named cells.** |
| **Label anchor** (find the cell reading "Rated voltage", take the cell to its right/below) | Layout drifts between versions | Adapts to moves; needs fuzzy label matching and a conflict report when a label appears twice |
| **Table region** (header row + repeated rows, e.g. hourly temperature readings, SC shots) | Tabular readings | Stop at the first empty row or a sentinel; handles variable row counts |

Mapping entry example:
```json
{ "field": "no_load.current_r", "by": "label", "label": "Current R phase", "direction": "right", "type": "number", "required": true }
{ "field": "temp.readings",    "by": "table", "header_row_label": "Time", "columns": {"Time":"time","Top oil":"top_oil"}, "stop": "blank" }
```

### 5.4 Extraction pipeline

1. Upload `.xlsx` → hash → store as immutable file.
2. Pick the template (auto-detect from the sheet's title/ID cell; tester can override; Admin-defined fingerprint rules).
3. Run the mapping → list of `{field, value, source_cell, status}` with statuses: **ok**, **missing (required)**, **unexpected type**, **ambiguous label**, **extra cell outside the mapping**.
4. Show a **preview with the source cell reference** beside each value. The tester fixes the file and re-uploads, or flags the issue to Admin. They don't hand-type values, so what is in the report is what is in the file.
5. On confirm: write the section (state `Uploaded`) with template version + source file hash.
6. Cells with merged ranges, formulas, hidden sheets, dates stored as serials, percent formats and comma decimals must be handled explicitly and tested. Read `openpyxl` with `data_only=True` for the **cached** value and also detect a formula with no cached value (file never recalculated), which must be rejected with a clear message.
7. Strip leading/trailing spaces, normalise `,` vs `.` decimals only by explicit rule, never guess units.

### 5.5 "Don't use calculable parameters" (F5)

- Extract **only entered values**. If the sheet contains a formula cell (an average, a total), take the value the lab's sheet shows, labelled "as logged", and **do not recompute or compare**.
- Audit `validate()` (30 checks): sort each check into
  - *raw-value checks* (presence, type, plausible range of a recorded value, unit sanity, series/sample match): keep.
  - *recomputation checks* (no-load sums/averages, SC shot averages, "reported vs computed oil rise", loss sums, anything that turns inputs into a derived number): remove from the pipeline, or move behind an **advisory-only** flag that never blocks and never prints in the report.
- `build_pdf` must print logged values only. Today it states "the report uses the computed value" for oil rise; reverse this.
- Document the decision in `docs/VALIDITY.md` and re-state the report disclaimer to match.

### 5.6 Fitting the data into the report's cells

- A **report template** (Excel or PDF layout, §5.7) lists output cells/fields mapped to `section.field` paths. Admin edits the mapping, never the code.
- Fill with `openpyxl` (keeps the lab's formatting). Missing values render as the lab's agreed marker (e.g. "NA"), never blank or `None`.
- Unmapped fields are listed on the Admin template screen so nothing extracted silently disappears.

### 5.7 Open design question for the report format

Today the final report is a PDF built with ReportLab. If the lab's official report is an Excel template, then either (a) keep ReportLab and mirror the layout, or (b) fill the Excel template and convert to PDF, which needs LibreOffice installed (conflicts with F2 "normal computer"). Recommended: **fill the template's cells for the working document and keep ReportLab for the sealed PDF**, unless the lab insists the Excel *is* the report. Raise as Q7.

### 5.8 Template tooling for Admin

- Upload a sample sheet → click a cell to bind a field (or enter a label) → live preview of extraction against the sample → save as draft → "test against N past uploads" → activate.
- Diff view between template versions.
- Export/import mapping as JSON (backup and moving between PCs).
- Ship the **downloadable blank logsheets** (one per test) so testers always start from the current template, which is the best defence against layout drift.

### 5.9 Keep the old formats

The existing `section, field, value` CSV/XLSX/JSON/SQLite importer remains as the "generic template" so current sample data and the 60 tests still work.

---

## 6. Report integrity: submitted means frozen (F11, B7, B8)

### 6.1 Lock rules

- On release, the job, all its sections, source files, template versions and the PDF become **read-only** at the application level *and* in the database.
- **DB triggers** on `sections`, `files`, `reports`, `audit`: `BEFORE UPDATE/DELETE` raises an error when the job is released (and always for `audit`/`files`/`reports`). Defence in depth against a bug or a direct DB edit.
- Remove for released jobs: `edit()`, `discard()`, `delete()`, `remove_import()`, re-upload. These return 409.

### 6.2 Hashing

- Each uploaded file: SHA-256 (exists for imports/sources; keep).
- Report PDF: SHA-256 stored (exists); additionally store a **manifest** (list of section revisions + file hashes + template versions + approver + time) and hash that. The manifest is printed on the final page and re-checkable.
- Verification page recomputes hashes (exists); extend to show the manifest and signers.

### 6.3 Tamper-evident audit

Hash chain: each audit row includes the hash of the previous row. An Admin tool "verify audit chain" reports the first broken link. Optionally, print the day's chain-tip hash on a paper log or export it to a separate medium daily.

### 6.4 Values taken as logged

No recomputation anywhere between upload and report (§5.5) removes the class of "app changed a number" disputes.

### 6.5 Corrections after release

A legal document is not edited; it is **superseded**.
1. Approver (plus a second signer) opens an **amendment** with a mandatory reason.
2. The system creates revision *n+1*, links it to *n*, marks *n* "Superseded by n+1" (still downloadable and verifiable, with a visible banner).
3. Only the sections named in the amendment unlock for correction, and the same upload → verify → approve chain runs again with full audit.
4. Customer sees both versions with the reason.

### 6.6 Retention (10+ years)

- Keep the PDF **and** inputs (original Excel files) together; consider **PDF/A** output for long-term readability.
- Store the app version/commit and template versions on each report so it can be reproduced.
- Backup: scheduled copy of `aletheia.db` (+ files) with checksum, plus a periodic read-only export package per released report (PDF, manifest, source files, audit extract). Test restore; document the procedure.
- Schema migrations are numbered and never destructive; keep a `schema_version` table.
- Time: record server time; display the lab PC clock offset warning if it drifts (a legal timestamp from a wrong clock is a problem).
- Disk and file permissions: only the service account writes to the DB folder.

---

## 7. Customer view, same-day target and notifications (D2, D3, D5)

### 7.1 Customer portal (read-only, localhost)

- Customer logs in (Customer role, linked to an organisation) and sees only their jobs.
- **Progress panel:** for the job's test plan, show how much is **Approved** and what is **Pending**, for example `6 of 10 tests approved · 3 pending verification · 1 not started`, with a bar and a row per test: `Not started / In progress / Pending verification / Approved`. "Approved" here means the section has been **verified** (§3.4).
- **Partial report so far:** a PDF assembled from the approved sections only. Pending sections appear as clearly marked placeholders ("Pending: not yet approved"), never as blank cells or `NA`. It carries a diagonal **PARTIAL, NOT FINAL** watermark, the generation time, the list of approved sections and a hash.
  - Regenerated automatically each time a section is approved; the customer always gets the latest. Each partial is stored with a version number and hash so what the customer saw at a given time can be reproduced later.
  - Partials are **not** legal reports and never carry the approver's signature or the final verification link.
- **Values visibility:** only approved sections show numbers (assumption above). Uploaded-but-unverified sections show status only.
- **Final report:** the released PDF replaces the partial; the partial versions remain listed as history.
- Customer can download the blank request form and upload the filled copy; the receiving test engineer still performs and signs the intake check (§3.6).
- Never exposed: audit log, other customers' data, internal drafts, tester usernames (show only "Test laboratory" unless the lab wants names).

### 7.2 Same-day target (replaces the 15-day clock)

- Job gets a **cut-off time** on the arrival day (configurable by Admin, default end of working day).
- Dashboard shows, per open job: time left today, sections not yet uploaded, sections waiting for verification, and who owns each. Amber when under 2 hours to the cut-off, red when passed.
- A job that crosses the cut-off isn't blocked; it is flagged **carried over** with a reason field, so the exception is visible and reportable.
- On release store `completed_at` and `same_day: yes/no` for statistics (extends today's turnaround figure in `/api/stats`).
- Because everything must finish in one day, **verification is the bottleneck**: verifier queue sorted by oldest upload, verifier notified on every upload (§7.3), and a verifier can verify while other sections are still being tested.

### 7.3 Notifications on upload (D5)

Triggers (each event writes a `notifications` row, then optionally an email):

| Event | Who is notified |
|---|---|
| Section uploaded | Verifiers (need to verify), the customer (progress changed) |
| Section returned by verifier | The uploading tester |
| Section approved (verified) | The customer (new partial report available), the approver when all required sections are approved |
| Final report released | The customer, the testers on the job |
| Same-day cut-off approaching | The job's testers and verifiers |

Design:
- **In-app first:** `notifications(id, user_id, job_id, section_key, kind, message, created_at, read_at, email_status)`, a bell icon with an unread count, and a page listing them. Needs no mail server.
- **Email second (optional):** SMTP settings in an Admin screen (host, port, TLS, sender). Use Python's `smtplib`, no new dependency. Emails are queued in an `outbox` table and sent by a small background worker with retry; failures are shown to Admin and never block an upload.
- **Content rules:** emails contain the job number, what changed and a link to the portal page. They contain **no result values** and no attachments (the portal is the source of truth, values only for approved sections).
- **Recipients:** customer contacts come from the request form email (validated at intake, §3.6); per-user opt-out for non-critical notices; the upload itself, not the email, is the legal record.
- Every notification and every send attempt is audited.
- On a lab PC without SMTP access the in-app notifications still work, which keeps F2 intact.

---

## 8. Scanning pivot: what happens to `vision.py`

- Keep the code and tests, but **hide behind a setting** (`FEATURE_SCAN=0` by default): no nav item, no AI dependency at start-up. `pypdfium2` stays only if the scan feature is enabled.
- Remove scan wording from the main README / demo scripts; keep the notes in `NOTES.md` as history.
- Scans as **evidence attachments** (a photo of the paper log, a signed sheet) remain useful and need no AI: store hashed and attach to a job/section.
- The `trocr-env/` folder (~large) and the stray `sersenzy…test.db` file in the project root are not part of the product; move out of the repo tree.

---

## 9. Workflow improvements for the lab (F10, not part of the repo)

Deliver as a separate short document for the faculty/lab; none of it needs code.

1. **One job card per product**: series/sample number printed once at intake and attached to the product; every bay copies it into the sheet header (kills transcription errors).
2. **Standard Excel logsheets with locked formula-free input cells, data validation (units, ranges, drop-downs for tick boxes) and named cells**; no free-form layout. This is what makes extraction reliable and reduces the verifier's work.
3. **Naming rule** for files: `<series>_<test>_<bay>_<yyyymmdd>.xlsx`.
4. **Bay board**: a visible list of which bay is free/busy and what is waiting, fed from the app dashboard.
5. **Verify daily, not at the end**: verifier clears the Uploaded queue at a fixed time; keeps a verification backlog from eating the same-day target.
6. **Customer form checklist** at intake so missing information is caught on day 0, not day 9.
7. **Single point of intake** (security + a tester) with a fixed handover moment so the clock start is unambiguous.
8. **Weekly SLA review** using the app's overdue/at-risk list.
9. **Template change control**: a short procedure (who may change a sheet, version number in the sheet header, Admin updates the mapping, test on past files, then activate).

---

## 10. Delivery plan

Order is chosen so each phase leaves the app working and testable. Rough sizes are in working days for one developer.

| Phase | Deliverable | Size | Depends on |
|---|---|---|---|
| **0. Decisions** | Q1-Q5 answered (D1-D5). Remaining: Q3b, Q6-Q14 | done / 1 | none |
| **1. Accounts and login** | `users` table, first-run admin, login/logout/session, CSRF, lockout, `@require`, route-permission test, replace typed approver with session identity | 4-5 | 0 |
| **2. Audit v2 + data model** | `sections`/`files` tables, optimistic locking, atomic numbering, audit with actor + hash chain, migration script with backup | 5-6 | 1 |
| **3. Workflow engine** | Intake screen with strict validation (§3.6), job/section states, assignment, bays, upload→verify→draft→approve, separation-of-duties rules, "My work" pages | 6-8 | 2 |
| **4. Excel templates** | Template registry, 4 mapping strategies, preview with source cells, Admin mapping tool, blank-logsheet downloads, remove/advisory-flag recomputation checks | 8-10 | 2 (parallel with 3 once sections exist) |
| **5. Integrity** | Lock rules + DB triggers, manifest, amendment flow, audit-chain verifier, retention/backup/export | 4-5 | 3 |
| **6. Customer portal, partial report, notifications** | Customer scoping, approved/pending view, auto-regenerated partial report, same-day cut-off dashboard, notification centre + optional SMTP outbox | 6-7 | 3 |
| **7. Hardening** | Concurrency tests, permission matrix tests, template-drift tests, load test with 5+ simultaneous users, docs, demo script | 3-4 | all |

Suggested checkpoint demos: end of phase 1 (login + roles), end of phase 3 (two testers upload different sections to one job; a verifier and approver finish it), end of phase 4 (change an Excel layout, update the mapping, extraction still works).

---

## 11. Test plan (additions to the existing 60 tests)

**Auth/roles:** every route × every role → expected status (table-driven); expired session; locked account; CSRF missing; first-run admin route disabled afterwards; customer cannot fetch another organisation's job by guessing the ID.
**Separation of duties:** uploader ≠ verifier; verifier/uploader ≠ approver; Admin cannot approve; name-typing no longer a way around it.
**Concurrency:** two testers upload different sections to the same job in parallel → both persist; two uploads to the same section → one gets 409; two intake users create jobs at once → distinct numbers.
**Excel:** each mapping strategy; inserted row/column; renamed label (fuzzy); duplicate label; merged cells; formula without cached value; hidden sheet; comma decimals; empty required field; wrong template; very large file; macro-enabled `.xlsm` refused; corrupt file.
**Template change:** change mapping, old job still renders identically (hash equal); new job uses the new version.
**Integrity:** after release every mutating route returns 409; direct SQL `UPDATE`/`DELETE` fails via trigger; tampering with an audit row is caught by the chain verifier; amendment creates a linked revision and leaves the original valid.
**Same-day target and notifications:** cut-off arithmetic, carried-over flag, a notification row per trigger, email failure doesn't block an upload, no result values in email bodies, outbox retry.
**Customer view:** a pending section shows no numbers anywhere in the portal, partial PDF or API response; the partial regenerates when a section is approved; the partial is watermarked and unsigned.
**Intake validation:** PIN code with 5 or 7 digits or letters rejected; required field left blank or `NA` rejected; no series/sample number allocated while errors remain.
**Calculations:** a test asserting the report never contains a value that does not appear in a source file.

---

## 12. Questions: resolved and still open

**Resolved**

| # | Answer |
|---|---|
| Q1 | Intake is done by the test engineer who receives the filled customer request form (D1). |
| Q2 | 15-day limit ignored; same-day / that-evening target (D2). |
| Q3 | Customer sees approved vs pending and the partial report so far (D3). Assumption to confirm: numbers only for approved sections (Q3b). |
| Q4 | "Pin code" = location example of nothing missing or wrong (D4). No sign-off PIN. |
| Q5 | All customers are on localhost; notification/email on upload (D5). |
| Q7 | The official report is the PDF in the lab's "Transformer Test report format" (D6). |
| Q12 | Not needed: the same-day target was dropped (D7). |
| Q14 | The request form is CPRI/QAF/01A (Issue 02); its fields are implemented as printed (D8). |

**Still open**

| # | Question | Why it matters |
|---|---|---|
| Q3b | Confirm: should a customer see values from sections that are uploaded but not yet verified, or only approved ones? | Default in the plan is approved only |
| Q6 | Is a QR code on the *report* acceptable (verification link), given there is no QR on the product box? | Today's verify page depends on it |
| Q8 | How many test types, templates and test bays exist today? Can we get every current logsheet as `.xlsx`? Are cells already named? | Template work estimate |
| Q9 | Who may approve (list)? Is a second signer needed for amendments? | Role seeding |
| Q10 | Required retention: how long, and must records be kept in a specific format (PDF/A)? Any regulator audit requirements? | §6.6 |
| Q11 | Is a recalculated figure ever legitimately needed (e.g. the standard demands a derived number)? If so, is it entered as a logged value by the tester? | F5 edge case |
| Q13 | Is there an SMTP server or mail account the lab PC can use, or do we ship in-app notifications only for now? | §7.3 |
| Q15 | Confirm the report's "Limit as per the standard" values (35 / 40 C) and the IS 1180 clause numbers in `report_template.json`. | Printed on every report |
| Q16 | Should address, contact, phone and email stay separate lines on the online form (they are one block on the printed form)? | Checks and notifications use them |

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Lab sheets change constantly | Template-as-data (§5), blank-logsheet distribution, change-control procedure |
| Roles proliferate beyond the number of people | "Different person per step per job", not "different person overall"; one user can hold several roles |
| Data-model migration breaks existing jobs | Backup, scripted migration, run the existing tests on a migrated copy |
| Over-strict locking blocks a genuine correction | Amendment flow (§6.5), not an admin override |
| Customer sees data later corrected | Show numbers only for approved sections; partial is watermarked and versioned (§7.1) |
| Email unreliable on a lab PC | In-app notifications are primary; email is a queued extra that never blocks work |
| Clock drift or lost DB on a single PC | Daily backup, restore drill, clock warning |
| Scope: this is large | Phases 1-3 form a shippable core (login, roles, shared workflow); 4-7 follow |

---

## 14. Immediate next actions

Status 2026-10-10 (evening): phases 1-7 and the evening follow-up (report format, customer-only requests, tickets, no same-day
target) are implemented. What remains needs the lab:

1. **Every current logsheet as `.xlsx`** (Q8): each becomes a new template version (Admin -> Templates: sample, bind cells, test
   on past uploads, activate). The version-1 templates are Aletheia's own layouts until then.
2. Confirm **Q15** (temperature-rise limits and clause numbers printed on the report), **Q16** (address block of the online
   form), **Q3b** (customers see values of approved tests only: implemented that way) and **Q11** (logged winding rise and the
   figures marked *derived* in `docs/VALIDITY.md`).
3. **Q13** (SMTP): in-app notifications work now; set the mail server in Admin -> Settings when one is available.
4. **Q6** (QR code on the report): kept on the last sheet until answered.
5. Before using real data: create the administrator on the lab PC, the testers / verifiers / approvers with their certified
   tests, the customer organisations with a customer account each, and the bays; let one customer raise a request and run the
   job end to end with the lab's own sheets.
6. The `trocr-env/` folder and the stray `.db` file in `ATRG-Merged/` are outside the repository and were left in place.
