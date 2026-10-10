"""Tests of the validation checks themselves (not of import, storage or reports).

Method: start from the demo job, inject ONE known error, and assert that exactly the expected finding changes
level and nothing else does. This shows each check can detect the fault it is meant to detect and does not
fire for unrelated reasons.

What these tests do NOT show: that the thresholds are right. Every threshold is in rules.py with a status;
none has been confirmed by a lab engineer. Pinned numbers below are regression values, not independent proof.
"""
import copy, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALETHEIA_DB", os.path.join(os.path.dirname(__file__), "_validity_tmp.db"))
import app, rules  # noqa: E402

DEMO = json.load(open(os.path.join(os.path.dirname(__file__), "..", "sample_data", "AP_Transformers_25T1654.json")))


def levels(d):
    F, _ = app.validate(d)
    return {f["check"] + (f" [{f['source']}]" if f["check"] == "Identifier consistency" else ""): f["level"] for f in F}, F


BASE, BASE_F = levels(DEMO)


def changed(mutate):
    d = copy.deepcopy(DEMO)
    mutate(d)
    now, F = levels(d)
    return {k: (BASE.get(k), v) for k, v in now.items() if BASE.get(k) != v}, F


class Baseline(unittest.TestCase):
    def test_demo_has_no_failures_and_the_documented_warnings(self):
        self.assertFalse([f for f in BASE_F if f["level"] == "fail"])
        warns = sorted(f["check"] for f in BASE_F if f["level"] == "warn")
        self.assertEqual(warns, sorted([
            "Identifier consistency", "Identifier consistency", "Identifier consistency", "No-load watts sum",
            "HV winding temperature rise", "Reported vs computed oil rise", "Correction factor"]))

    def test_no_check_is_silently_skipped(self):
        # a coding mistake inside a check would be reported as "not evaluated"; on complete data that must never happen
        self.assertEqual([f["check"] for f in BASE_F if f.get("na")], [])

    def test_hv_winding_rise_value(self):
        # hand calculation: 4.0464/3.554*(235+25.9) - 235 - 22.85 + 0.475 = 39.71 K  (same formula as the code: regression only)
        hv = next(f for f in BASE_F if f["check"] == "HV winding temperature rise")
        self.assertIn("39.7 K", hv["detail"])
        self.assertTrue(hv.get("inconclusive"))


class Mutations(unittest.TestCase):
    def only(self, mutate, check, level):
        diff, _ = changed(mutate)
        self.assertEqual(diff, {check: (BASE[check], level)}, diff)

    def test_resistance_phase_misread(self):
        self.only(lambda d: d["resistance"]["lv"][0].__setitem__(0, d["resistance"]["lv"][0][0] * 1.05),
                  "Winding resistance phase imbalance", "fail")

    def test_noload_average_wrong(self):
        def m(d): d["noload"]["rows"][0][3][0] += 0.5
        diff, _ = changed(m)
        self.assertEqual(diff.get("No-load current average"), (None, "fail"))

    def test_noload_current_over_limit_uses_rating(self):
        def m(d): d["noload"]["rows"][2][4] = 20.0; d["noload"]["rows"][2][3] = [20.0] * 3
        diff, _ = changed(m)
        self.assertEqual(diff["No-load current at 112.5% voltage"], ("pass", "fail"))

    def test_noload_limit_depends_on_rating(self):
        self.assertEqual(rules.nll_limits(100)[0], 3.0)
        self.assertEqual(rules.nll_limits(250)[0], 2.0)

    def test_noload_rows_found_by_label_not_position(self):
        def m(d): d["noload"]["rows"].reverse()
        diff, F = changed(m)
        self.assertFalse([f for f in F if f["level"] == "fail"])
        self.assertEqual([f["check"] for f in F if f.get("na")], [])

    def test_loss_over_guaranteed(self):
        self.only(lambda d: d["proforma"].__setitem__("loss100", 2400), "Total loss at 100% load (75 C)", "fail")

    def test_loss_exactly_at_limit_passes(self):
        t100 = max(r[13] for r in DEMO["losses"]["rows"])
        d = copy.deepcopy(DEMO); d["proforma"]["loss100"] = t100
        self.assertEqual(levels(d)[0]["Total loss at 100% load (75 C)"], "pass")
        d["proforma"]["loss100"] = t100 - 0.01
        self.assertEqual(levels(d)[0]["Total loss at 100% load (75 C)"], "fail")

    def test_impedance_out_of_band(self):
        self.only(lambda d: d["proforma"].__setitem__("z_pct", 5.5), "Impedance voltage (+/-10%)", "fail")

    def test_ratio_tolerance_is_smaller_of_half_percent_and_tenth_of_impedance(self):
        self.assertAlmostEqual(rules.ratio_tolerance(4.5), 0.45)
        self.assertAlmostEqual(rules.ratio_tolerance(7.0), 0.5)
        # a reading 0.47% off passed under the old flat 0.5% and must now fail for a 4.5% impedance unit
        def m(d):
            side = d["routine"]["ratio"]["BT"]
            vph = d["proforma"]["lv"] / 3 ** .5
            th = d["proforma"]["hv"] * 1.05 / vph
            side[0][0] = th * 1.0047
        diff, _ = changed(m)
        self.assertEqual(diff.get("Voltage ratio, all taps"), ("pass", "fail"))

    def test_dielectric_wording(self):
        for text, want in (("Disruptive discharge at 28 kV", "fail"), ("", "warn"), ("not ok", "warn"),
                           ("No disruptive discharge, withstood", "pass")):
            d = copy.deepcopy(DEMO); d["routine"]["hvac"]["obs"] = text
            self.assertEqual(levels(d)[0]["Dielectric routine tests"], want, text)

    def test_post_test_inspection_wording(self):
        for text, want in (("Cracked winding insulation", "fail"), ("Winding displaced, spacers loose", "fail"),
                           ("not ok", "warn"), ("No abnormalities", "pass"), ("no visible damage", "pass")):
            d = copy.deepcopy(DEMO); d["sc"]["after"] = text
            self.assertEqual(levels(d)[0]["Post-test inspection"], want, text)

    def test_leakage_wording(self):
        for text, want in (("Oil leakage at gasket", "fail"), ("No leakage at any point", "pass"), ("seepage observed", "fail"), ("n/a", "warn")):
            d = copy.deepcopy(DEMO); d["pressure"]["leak"]["obs"] = text
            self.assertEqual(levels(d)[0]["Oil leakage test"], want, text)

    def test_one_bad_sc_shot_is_not_hidden_by_the_mean(self):
        def m(d):
            sh = [s for s in d["sc"]["shots"] if s[1] == "HT" and not s[9]]
            sh[0][7] = 8.5; sh[1][7] = 6.6   # mean unchanged at ~7.5, but two shots are >10% off
            sh[0][4:7] = [8.5] * 3; sh[1][4:7] = [6.6] * 3
        diff, F = changed(m)
        self.assertEqual(diff.get("SC shot-by-shot at HT tap"), (None, "warn"))
        self.assertEqual(levels(copy.deepcopy(DEMO))[0].get("SC current at HT tap"), "pass")

    def test_peak_below_required_is_flagged(self):
        def m(d): [s.__setitem__(3, 15.0) for s in d["sc"]["shots"] if s[1] == "LT"]
        diff, _ = changed(m)
        self.assertEqual(diff.get("SC shot-by-shot at LT tap"), (None, "warn"))

    def test_thermal_shot_too_short(self):
        def m(d): [s.__setitem__(8, 1.5) for s in d["sc"]["shots"] if s[9] == "thermal"]
        diff, _ = changed(m)
        self.assertEqual(diff["Thermal ability of SC"], ("pass", "fail"))

    def test_reactance_change(self):
        def m(d): d["losses"]["rows"][1][3] = 3.0
        diff, _ = changed(m)
        self.assertEqual(diff["Reactance change before/after short circuit"], ("pass", "fail"))

    def test_oil_rise_over_limit_and_thin_margin(self):
        d = copy.deepcopy(DEMO); d["proforma"]["limits"]["oil"] = 20
        self.assertEqual(levels(d)[0]["Top-oil temperature rise"], "fail")
        d["proforma"]["limits"]["oil"] = 26.5      # 26.15 K computed: 0.35 K margin
        F = app.validate(d)[0]
        f = next(x for x in F if x["check"] == "Top-oil temperature rise")
        self.assertEqual((f["level"], f.get("inconclusive")), ("warn", True))

    def test_winding_rise_boundaries(self):
        for limit, want in ((39.0, "fail"), (39.9, "warn"), (41.0, "pass")):
            d = copy.deepcopy(DEMO); d["proforma"]["limits"]["wdg"] = limit
            F = app.validate(d)[0]
            self.assertEqual(next(x for x in F if x["check"] == "HV winding temperature rise")["level"], want, limit)

    def test_correction_factor_changes_the_verdict(self):
        # the demo's 0.275-vs-0.475 doubt matters: with 0.475 the HV rise is 39.7 K, with 0.275 it is 39.5 K
        d = copy.deepcopy(DEMO); d["temp"]["corr"] = 0.275
        hv = next(f for f in app.validate(d)[0] if f["check"] == "HV winding temperature rise")
        self.assertIn("39.5 K", hv["detail"])

    def test_steady_state_not_reached(self):
        def m(d): d["temp"]["hours"][-1][1] += 3
        diff, _ = changed(m)
        self.assertEqual(diff["Steady-state criterion (<=1 K/h)"], ("pass", "warn"))

    def test_missing_value_is_reported_with_its_cause(self):
        d = copy.deepcopy(DEMO); d["temp"]["rhv_hot"] = None
        F = app.validate(d)[0]
        f = next(x for x in F if x["check"] == "Winding temperature rise")
        self.assertTrue(f.get("na")); self.assertIn("TypeError", f["cause"])
        # the technical cause is for the engineer only: it must not reach text that is printed in the report
        self.assertNotIn("TypeError", f["detail"] + f["found"])


class Rules(unittest.TestCase):
    def test_every_rule_states_its_status_and_source(self):
        for k, r in rules.RULES.items():
            self.assertIn(r["status"], (rules.SECONDARY, rules.UNCONFIRMED), k)
            self.assertTrue(r["source"], k)

    def test_nothing_claims_lab_confirmation(self):
        self.assertFalse([k for k, r in rules.RULES.items() if "lab" in r["status"]])

    def test_findings_carry_their_basis(self):
        f = next(f for f in BASE_F if f["check"] == "Reactance change before/after short circuit")
        self.assertIn("unconfirmed", f["basis"])


if __name__ == "__main__":
    unittest.main()
