# Validity of the checks

This page says what has and has not been established about Aletheia's engineering checks. The rules table below mirrors
`rules.py`, which is what the code uses: change a rule there first, then update the table.

## What has been shown

- Each check detects the fault it is meant to detect (`tests/test_validity.py`: one injected error per test, exactly one finding changes).
- On complete data no check is silently skipped, and a skipped check now reports its cause.
- Verdicts no longer depend on a stray word (`"no" in text`): unclear wording gives a warning, never a pass.
- Limits that vary with the job (temperature rise) come from the proforma, and no-load limits depend on the rating.
- A sample that fails a requirement gets a "does not comply" report listing what was not met; only a broken data layout
  blocks the report. Recomputed averages that disagree with the logged ones are advisory (F5) and never block
  (`test_failing_sample_gets_a_does_not_comply_report`, `test_broken_layout_still_blocks_the_report`,
  `test_recomputed_average_that_disagrees_is_advisory_only`).
- The report never shows PASS for a test whose checks did not all run: one check skipped for NA values makes the line
  NOT FULLY EVALUATED, and the statement of conformity lists the skipped checks as well as missing documents
  (`test_summary_never_passes_a_test_that_was_not_fully_evaluated`).

## What has NOT been shown

- **No lab engineer has reviewed any threshold.** No rule is marked as confirmed by the lab.
- No rule has been checked against the text of IS 1180 or IS 2026 itself. `secondary` means it matches a published specification or summary that was read; `unconfirmed` means it comes from general practice or memory.
- The regression numbers in the tests (e.g. 39.7 K) use the same formula as the code, so they show stability, not correctness.

## Calculable parameters (faculty note F5, NEXT_STEPS.md section 5.5)

Values are taken **as logged**. Where the lab's sheet already states a figure (an average, a total, a rise), Aletheia uses
that figure; its own arithmetic on the same readings is **advisory**: shown to the engineer as a possible slip, never
blocking, never needing review, never printed in the report.

| Check | Class | What it uses |
|---|---|---|
| Completeness of source documents, Limits not available | keep | presence |
| Identifier consistency (all sheets, additional sheets) | keep | logged identifiers compared |
| Winding resistance phase imbalance | keep (plausibility) | spread of the logged readings |
| Cold resistance cross-check | keep | two logged values compared |
| No-load current average | **advisory** (was a blocking data error) | mean of logged phases vs logged average |
| No-load watts sum | **advisory** | sum of logged phases vs logged total |
| No-load current at 100% / 112.5% | keep, **derived** (Q11) | logged average current as % of rated current (rated current from the proforma) |
| Total loss at 100% / 50% | keep | logged totals vs guaranteed values |
| Impedance voltage, Reactance change | keep | logged values vs declared / limit |
| Voltage ratio, all taps | keep, **derived** (Q11) | logged ratios vs theoretical ratio from the proforma voltages |
| Dielectric routine tests, Post-test inspection, Oil leakage | keep | logged observations |
| SC RMS average | **advisory** | mean of logged phases vs logged average |
| SC current at each tap | keep, **derived** (Q11) | mean of the logged shot averages vs required current |
| SC shot-by-shot, Thermal ability | keep | logged values vs required |
| Top-oil temperature rise | keep, **logged value** | `oil_rise_reported`; only when nothing was logged: last hour top oil minus mean ambient, marked "calculated" |
| HV / LV winding temperature rise | keep, **logged value when present** | `hv_rise` / `lv_rise` from the logsheet; otherwise the IS formula on logged resistances, marked "calculated" (Q11) |
| Steady-state criterion | keep, **derived** (Q11) | hourly change of top-oil minus ambient |
| Reported vs computed oil rise | **advisory** | logged rise vs last-hour calculation |
| Correction factor | keep | two logged values compared |
| Injected loss = NLL + FLL | **advisory** | sum of logged losses vs logged total |
| Pressure / vacuum test deflection | **advisory** | logged maximum vs largest logged before/after difference |
| Additional record | keep | presence of logged values |

The report prints logged values only: the hourly temperature table shows the logged readings (no computed mean ambient or
rise column), the summary marks each rise "as logged" or "calculated", and a calculated winding rise states its formula.

Open (Q11): whether the lab logs the derived figures marked **derived** above (then they become logged values too), or
whether the standard's own calculation is acceptable as printed.

## Rules and their status

| Rule | Value | Status | Basis | Note |
|---|---|---|---|---|
| `resistance_imbalance_pct` | 2 % | **unconfirmed** | General practice; not known to be a clause of IS 1180 / IS 2026. | Phase-to-phase spread of winding resistance readings. |
| `nll_pct_to_200kva` | 3 % of rated current | **secondary** | BIS summary of IS 1180 and CEA DT specification (May 2026): no-load current up to 200 kVA not above 3%. | Applies at rated voltage. |
| `nll_pct_above_200kva` | 2 % of rated current | **secondary** | CEA DT specification (May 2026): above 200 kVA and up to 2500 kVA not above 2%. | Applies at rated voltage. |
| `nll_112_pct_to_200kva` | 6 % of rated current | **secondary** | BIS summary of IS 1180: no-load current at 112.5% voltage not above 6% (up to 200 kVA). Wording was ambiguous. |  |
| `nll_112_pct_above_200kva` | 5 % of rated current | **unconfirmed** | Carried over from the first prototype; no source found. | Check the 112.5% limit for ratings above 200 kVA. |
| `loss_positive_tolerance_pct` | 0 % | **secondary** | CEA DT specification (May 2026): no positive tolerance on no-load or load losses. | Measured loss must not exceed the guaranteed value in the proforma. |
| `impedance_tolerance_pct` | 10 % of declared impedance | **secondary** | Older IS 1180 text (1966) states 4.5% impedance with +/-10% tolerance; IS 2026 Part 1 not read. | Applied to every tap, which may be stricter than the standard (tolerance is usually stated at the principal tap). |
| `ratio_tolerance_pct` | 0.5 % of declared ratio | **secondary** | Older IS 1180 text (1966): 0.5% or 10% of the actual impedance, whichever is smaller. IS 2026 Part 1 not read. | Effective tolerance = min(0.5%, 10% of impedance %). For 4.5% impedance this is 0.45%. |
| `ratio_impedance_fraction` | 0.1 fraction of impedance % | **secondary** | Same as ratio_tolerance_pct. |  |
| `reactance_change_pct` | 2 % | **unconfirmed** | IS 2026 Part 5 / IEC 60076-5; the allowed change is believed to depend on transformer category and winding type. Not checked. | Flat limit used for every rating; may be wrong for some transformers. |
| `sc_rms_tolerance_pct` | 10 % of required current | **unconfirmed** | IS 2026 Part 5 / IEC 60076-5 tolerance on applied current. Not checked. |  |
| `sc_thermal_min_s` | 2 s | **unconfirmed** | IS 2026 Part 5 thermal ability duration (believed to be 2 s). Not checked. |  |
| `steady_state_k_per_h` | 1 K per hour | **unconfirmed** | IS 2026 Part 2 / IEC 60076-2 top-oil steady state. Believed to be 1 K/h over 3 consecutive hours; not checked. | Prototype checks the last 4 hourly changes, which is stricter than 3. |
| `temp_margin_inconclusive_k` | 1 K | **unconfirmed** | Prototype choice standing in for measurement uncertainty. Replace with the lab's own uncertainty budget. |  |
| `oil_limit_k / wdg_limit_k` | from proforma | **secondary** | Read from the proforma per job. IS 1180 gives several limit sets depending on ambient and efficiency level (e.g. 35/40 K over 50 C ambient in CEA 2026), so these are deliberately not hardcoded. |  |

## Checklist for whoever has the standards (tick when read in the standard itself)

- [ ] IS 1180 (Part 1): no-load current limits by rating, at rated voltage and at 112.5%.
- [ ] IS 1180 (Part 1): temperature-rise limit sets and which one applies to which efficiency level / ambient.
- [ ] IS 1180 (Part 1): loss tables and whether any tolerance applies.
- [ ] IS 2026 (Part 1): impedance tolerance (at which tap?) and voltage-ratio tolerance (the smaller-of rule).
- [ ] IS 2026 (Part 2): steady-state criterion (rate and number of hours) and the winding temperature-rise calculation.
- [ ] IS 2026 (Part 5): reactance-change limit by category, applied-current tolerance, peak-current requirement, thermal duration, number of shots.
- [ ] Ask the lab: their measurement uncertainty for resistance and temperature (replaces `temp_margin_inconclusive_k`).

## Known limits of the checks

- Identifier matching compares only the last 7 / 4 characters (sheets abbreviate IDs) and treats H as 4. Other handwriting confusions (6/4) are flagged as warnings, not resolved.
- Impedance and ratio tolerances are applied at every tap; the standard may state them at the principal tap only.
- The correction factor in the winding temperature-rise formula is typed by the operator and only cross-checked against a second typed value.
- A failed requirement is confirmed by the engineer with one click; the app does not ask for a second reading or apply the
  lab's decision rule (e.g. guard bands for measurement uncertainty). The decision rule the customer chose is printed as written.
- Not covered: a single-phase unit's other checks, ester-filled or dry-type transformers (IS 1180 Part 2/3), and ratings the proforma does not describe.
