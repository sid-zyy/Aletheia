# Aletheia: build checklist (now)

**Login and roles**
- [ ] Users table, first-run admin setup, login/logout, session timeout, lockout after failed attempts
- [ ] Roles: Admin, Tester, Verifier, Approver, Customer
- [ ] Permission check on every route (server-side), plus a test that runs every route against every role
- [ ] Approver identity comes from the login, not typed name/ID
- [ ] Same person cannot upload and verify, or verify and approve, on one job
- [ ] Admin manages users but cannot edit, verify or approve test data

**Intake (test engineer)**
- [ ] Intake screen for the filled customer request form
- [ ] Required fields enforced, no "NA" (PIN code = 6 digits, valid email and phone)
- [ ] Series and sample number allocated automatically, only once the form is complete, safe with simultaneous users
- [ ] Record arrival time and who received the product

**Shared report, many testers**
- [ ] One record per test section (not one JSON blob), so simultaneous uploads never overwrite each other
- [ ] Each section stores uploader, test bay, time, file name and file hash
- [ ] Each section stores verifier and time
- [ ] Sections can be done in any order
- [ ] Section states: Not started, Uploaded, Returned, Verified (locked)

**Excel extraction**
- [ ] Template stored as data and versioned, not hard-coded
- [ ] Find values by named cell or label, not only fixed cell addresses
- [ ] Read tables with a variable number of rows
- [ ] Preview shows each value with its source cell; empty required cell blocks the upload
- [ ] Admin screen to map or update a template when the layout changes
- [ ] Extracted values fill the report's required cells
- [ ] Existing CSV/Excel import keeps working

**No calculated values**
- [ ] List the 30 checks in `validate()` as keep / remove / advisory
- [ ] Report prints logged values only (stop using the computed oil rise and other derived numbers)

**Integrity**
- [ ] Released report and its inputs are read-only: remove edit, withdraw and delete for released jobs
- [ ] Database triggers block changes to released data
- [ ] Corrections only through a new linked revision with a reason
- [ ] Audit log records who, what, when and which file hash on every action, and can detect tampering

**Customer view and notifications**
- [ ] Customer login sees only their own jobs
- [ ] Progress shown as approved vs pending
- [ ] Partial report built from approved sections only, watermarked, regenerated on each approval
- [ ] Pending sections show status only, no values
- [ ] Notification on upload, verification and release (in-app first, optional email)

**Cleanup**
- [ ] Scanning hidden behind a setting, off by default
- [ ] Move `trocr-env/` and the stray `.db` file out of the project
- [ ] Back up `aletheia.db` before changing the data model
- [ ] Update tests for the new roles, sections and locks
