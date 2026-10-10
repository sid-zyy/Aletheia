# Working with Aletheia: recommendations for the Short Circuit Laboratory

For the laboratory and faculty (faculty note F10). None of this needs software changes; each point says how Aletheia
supports it. Purpose: reports that are complete and correct (D4), with fewer manual steps.

## 1. One job card per product
Print the series and sample number once at intake (Aletheia allocates them only when the request form is complete) and
attach the card to the product. Every bay copies the number into its logsheet header. *Aletheia:* the series written on each
sheet is compared with the job's on upload, and a workbook holding sheets of several jobs is routed by that number.

## 2. Standard Excel logsheets
Use the blank logsheets downloaded from Aletheia (Templates, or *Excel logsheets* on any job): input cells are marked, every
value cell has a name, and the sheet carries its form name and version. Do not type averages or totals by hand; if the sheet
computes them, save the file in Excel before uploading so the value is stored. *Aletheia:* a formula that was never
calculated is refused; a required empty cell blocks the test instead of being stored as NA.

## 3. File names
`<series>_<test>_<bay>_<yyyymmdd>.xlsx`, for example `CPRIBLRSCL26T0042_noload_bay3_20261010.xlsx`. *Aletheia:* the file is
kept byte-for-byte with its fingerprint; the name helps people, the fingerprint proves which file it was.

## 4. Record the bay
Choose the bay on the job page before uploading (the PC remembers it). *Aletheia:* every test shows which bay it came from,
and the dashboard shows what is outstanding and whose it is.

## 5. Verify during the day, not at the end
Verifiers clear "My work" at fixed times (e.g. 11:00, 14:00, 16:30), so tests do not wait for the end of the day.
*Aletheia:* the verification queue is sorted oldest first, verifiers are notified of every upload, and a test can be verified
while others are still being tested.

## 6. Customer form checklist at intake
Send customers the Excel request form in advance (they can download and return it through the portal). At intake, check the
entered values against the product and the original form before confirming. *Aletheia:* missing or malformed values (PIN
code, phone, email, rating, witness) are listed at once; a PIN that does not match the state needs confirmation; release is
blocked until the intake is confirmed against the original.

## 7. A single point of intake
Security and the receiving engineer hand over at a fixed point, so the arrival time is
unambiguous. *Aletheia:* records arrival time, who opened the box and who received it.

## 8. Weekly review of open jobs
Review the jobs still open and the customers' open tickets. *Aletheia:* release records when each report was finished; the
Records export lists all jobs in one workbook.

## 9. Template change control
Who may change a logsheet: named persons only. Procedure: change the sheet and its version number in the header, the
administrator makes a new template version, tests it on a sample and on past uploads, compares it with the active one, then
activates it. *Aletheia:* a template version that has read data is never changed; old jobs keep the version that read them.

## 10. Corrections after release
Never re-issue a report by editing it. An approver and a second approver open an amendment with the reason; only the named
tests are corrected and re-verified; the new version supersedes the old one, which stays verifiable.

## 11. Daily routine for the administrator
Note the audit chain tip shown on the Backups page in the paper register; copy the `backups` folder to a second disk weekly;
use *Check* on one backup a month (the restore drill).
