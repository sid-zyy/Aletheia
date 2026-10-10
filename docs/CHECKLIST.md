# Aletheia: build checklist

Status 2026-10-10 (evening). Ticked items are implemented and covered by tests (`python -m unittest discover -s tests`).

**Login and roles**
- [x] Users table, first-run admin setup, login/logout, session timeout, lockout after failed attempts
- [x] Roles: Admin, Tester, Verifier, Approver, Customer
- [x] Permission check on every route (server-side), plus a test that runs every route against every role
- [x] Approver identity comes from the login, not typed name/ID
- [x] Same person cannot upload and verify, or verify and approve, on one job
- [x] Admin manages users but cannot edit, verify or approve test data

**Customer request and intake**
- [x] Only a customer raises a test request
- [x] The customer fills in the Customer Request Form CPRI/QAF/01A online, laid out and worded as the printed form (sheets 1-2)
- [x] Required fields enforced, no "NA" except where the form allows it with a reason (PIN code = 6 digits, valid email and phone)
- [x] The laboratory receives the request (inbox), sees it as sent and never edits it; records sheet 3 and the test plan
- [x] A request with something missing or wrong is returned with the reason; the customer corrects it and sends it again
- [x] Series and sample number allocated automatically, only once everything is complete, safe with simultaneous users
- [x] Record arrival time and who received the product

**Shared report, many testers**
- [x] One record per test section (not one JSON blob), so simultaneous uploads never overwrite each other
- [x] Each section stores uploader, test bay, time, file name and file hash
- [x] Each section stores verifier and time
- [x] Sections can be done in any order
- [x] Section states: Not started, Uploaded, Returned, Verified (locked)

**Excel extraction**
- [x] Template stored as data and versioned, not hard-coded
- [x] Find values by named cell or label, not only fixed cell addresses
- [x] Read tables with a variable number of rows
- [x] Preview shows each value with its source cell; empty required cell blocks the upload
- [x] Admin screen to map or update a template when the layout changes
- [x] Extracted values fill the report's required cells
- [x] Existing CSV/Excel import keeps working
- [ ] The lab's own logsheets as new template versions (waiting for the `.xlsx` files, Q8)

**Test report**
- [x] Report in the lab's "Transformer Test report format": header, report number box, ULR footer, Sheet n of N, signature lines
- [x] Cover, description, summary with clauses and sheet references, drawings, result sheets, conclusion, notes, accreditation
- [x] Verification QR and traceability annex kept on the last sheet
- [ ] Confirm the temperature-rise "Limit as per the standard" and the clause numbers with the lab (Q15)

**No calculated values**
- [x] List the 30 checks in `validate()` as keep / remove / advisory
- [x] Report prints logged values only (stop using the computed oil rise and other derived numbers)

**Integrity**
- [x] Released report and its inputs are read-only: remove edit, withdraw and delete for released jobs
- [x] Database triggers block changes to released data
- [x] Corrections only through a new linked revision with a reason
- [x] Audit log records who, what, when and which file hash on every action, and can detect tampering

**Customer view, tickets and notifications**
- [x] Customer login sees only their own jobs
- [x] Progress shown as approved vs pending
- [x] Partial report built from approved sections only, watermarked, regenerated on each approval
- [x] Pending sections show status only, no values
- [x] Notification on upload, verification and release (in-app first, optional email)
- [x] Customers raise tickets; the administrators answer and close them
- [x] No same-day target (removed by decision D7)

**Cleanup**
- [x] Scanning hidden behind a setting, off by default
- [x] Back up `aletheia.db` before changing the data model
- [x] Update tests for the new roles, sections and locks
- [x] Pages and scripts never served stale from the browser cache
- [ ] Move `trocr-env/` and the stray `.db` file out of `ATRG-Merged/` (outside the repository; needs the owner's go-ahead)
