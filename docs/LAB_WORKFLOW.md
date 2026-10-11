# Working with Aletheia: recommendations for the Short Circuit Laboratory

For the laboratory and faculty (faculty note F10). None of this needs software changes; each point says how Aletheia
supports it. Purpose: reports that are complete and correct (D4), with fewer manual steps.

## 1. One job card per product
Print the series and sample number once at intake (Aletheia allocates them only when the request form is complete) and
attach the card to the product. Every bay copies the number into its logsheet header. *Aletheia:* the series written on each
sheet is compared with the job's on upload, and a mismatch is flagged in the preview.

## 2. Standard Excel logsheets
Use the blank logsheets downloaded from Aletheia (**Blank sheet** on each test's row of the job page, with the job's series
number, sample code and customer already written in; or Templates). Each is laid out as the paper logsheet: input cells are
yellow, printed text and calculated cells are locked, choices are dropdowns, and the sheet carries its form name and version. Do not type averages or totals by hand; if the sheet
computes them, save the file in Excel before uploading so the value is stored. *Aletheia:* a formula that was never
calculated is refused; a required empty cell blocks the test instead of being stored as NA.

## 3. File names
`<series>_<test>_<yyyymmdd>.xlsx`, for example `CPRIBLRSCL26T0042_noload_20261010.xlsx`. *Aletheia:* the file is
kept byte-for-byte with its fingerprint; the name helps people, the fingerprint proves which file it was.

## 4. Upload on the test's own row
Upload each file with *Upload* on the row of the test it belongs to, and attach the scan of the paper sheet there too.
*Aletheia:* nothing is assigned to a test by itself; every test shows who uploaded it, from which file and which revision,
and the dashboard shows what is outstanding and whose it is.

## 5. Verify during the day, not at the end
Testers clear their "To verify" queue at fixed times (e.g. 11:00, 14:00, 16:30), so tests do not wait for the end of the day.
*Aletheia:* the verification queue is sorted oldest first, testers are notified of every upload by a colleague, and a test can be verified
while others are still being tested.

## 6. Customers raise their request online
Give each customer organisation a portal account and ask them to raise every test request online, on the Customer Request
Form CPRI/QAF/01A (sheets 1 and 2), before the sample is sent. At intake, compare the request with the product, record
sheet 3 and confirm. *Aletheia:* the form is checked as the customer types (PIN code, phone, email, rating, storage /
disposal, decision rule, declarations); a request with something missing or wrong is returned to the customer with the
reason instead of being corrected by the laboratory; a PIN that does not match the state needs confirmation; release is
blocked until the intake is checked.

## 7. A single point of intake
Security and the receiving engineer hand over at a fixed point, so the arrival time is
unambiguous. *Aletheia:* records the arrival time, the physical condition on receipt and who accepted the job (sheet 3).

## 8. Weekly review of open jobs
Review the jobs still open and the customers' open tickets. *Aletheia:* release records when each report was finished; the
Records export lists all jobs in one workbook.

## 9. Template change control
Who may change a logsheet: named persons only. Procedure: change the sheet and its version number in the header, the
administrator makes a new template version, tests it on a sample and on past uploads, compares it with the active one, then
activates it. *Aletheia:* a template version that has read data is never changed; old jobs keep the version that read them.

## 10. Corrections after release
Never re-issue a report by editing it. An administrator and a second administrator open an amendment with the reason; only the named
tests are corrected and re-verified; the new version supersedes the old one, which stays verifiable.

## 11. Daily routine for the administrator
Answer the open customer tickets (dashboard: *Customer tickets to answer*). Note the audit chain tip shown on the Backups page in the paper register; copy the `backups` folder to a second disk weekly;
use *Check* on one backup a month (the restore drill).
