"""A rule whose answer means nothing without a number names the value the task records with it."""

import copy
import unittest

from openguildkit.catalog import CatalogError, _validate_rule, load_catalog
from openguildkit.catalog_queries import recorded_value
from openguildkit.result_form import result_template, validate_result
from openguildkit.results import completion_problems

PACKS = ("llm-evaluations", "nist-ai-risk")


def task_with(packs, status="approved", result=None):
    task = {"id": "billing-answers", "status": status, "answers": {},
            "consultation": {"scope": {"checks": [], "packs": packs}}}
    if result is not None:
        task["result"] = result
    return task


def outcome(check, status="passed", **fields):
    return {"check": check, "status": status, "evidence": "evals/report.md", **fields}


class RecordedValueTests(unittest.TestCase):
    def setUp(self):
        catalog = load_catalog()
        self.packs = [copy.deepcopy(catalog["packs"][pack_id]) for pack_id in PACKS]
        self.task = task_with(self.packs)

    def test_every_model_evaluation_rule_with_a_number_names_the_value_to_record(self):
        named = {f"{pack['id']}/{rule['id']}": rule["records"]["name"]
                 for pack in self.packs for rule in pack["rules"] if "records" in rule}
        self.assertEqual(named, {
            "llm-evaluations/evaluate-user-outcomes": "pass-threshold",
            "llm-evaluations/review-grading-rubric": "grader-agreement",
            "llm-evaluations/compare-evaluation-baselines": "regression-budget",
            "nist-ai-risk/set-risk-evidence": "acceptance-threshold",
        })

    def test_the_result_template_shows_the_value_to_write(self):
        checks = {item["check"]: item for item in result_template(self.task, {})["checks"]}
        budget = checks["rule:llm-evaluations/compare-evaluation-baselines"]
        self.assertTrue(budget["records"].startswith("regression-budget: The largest drop"))
        self.assertEqual(budget["value"], "")
        self.assertNotIn("records", checks["rule:llm-evaluations/record-evaluation-setup"])

    def test_a_passed_or_failed_outcome_needs_the_value_with_its_unit(self):
        check = "rule:llm-evaluations/compare-evaluation-baselines"
        payload = {"revision": "abc1234", "checks": [outcome(check)]}
        with self.assertRaisesRegex(ValueError, "regression-budget.*value"):
            validate_result(self.task, {}, payload)
        payload["checks"] = [outcome(check, value="2")]
        with self.assertRaisesRegex(ValueError, "with its unit"):
            validate_result(self.task, {}, payload)
        payload["checks"] = [outcome(check, status="failed", value=" 2  percentage points ")]
        self.assertEqual(validate_result(self.task, {}, payload)["checks"][0]["value"], "2 percentage points")

    def test_a_recorded_number_must_fall_within_the_bounds_its_rule_declares(self):
        def record(check, value):
            payload = {"revision": "abc1234", "checks": [outcome(check, value=value)]}
            return validate_result(self.task, {}, payload)["checks"][0]["value"]

        threshold = "rule:llm-evaluations/evaluate-user-outcomes"
        for value in ("-5 %", "0 %", "0 % of critical cases", "120 % of cases"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "above 0 and at most 100"):
                record(threshold, value)
        self.assertEqual(record(threshold, "95 % of critical cases"), "95 % of critical cases")
        self.assertEqual(record(threshold, "0,9 pass rate"), "0,9 pass rate")
        budget = "rule:llm-evaluations/compare-evaluation-baselines"
        self.assertEqual(record(budget, "0 percentage points"), "0 percentage points")
        with self.assertRaisesRegex(ValueError, "at least 0 and at most 100"):
            record(budget, "-2 percentage points")
        template = {item["check"]: item for item in result_template(self.task, {})["checks"]}
        self.assertIn("Write a number above 0 and at most 100, with its unit.", template[threshold]["records"])

    def test_the_rules_without_a_recorded_value_answer_without_a_number(self):
        unnamed = sorted(rule["id"] for pack in self.packs for rule in pack["rules"]
                         if pack["id"] == "llm-evaluations" and "records" not in rule)
        self.assertEqual(unnamed, ["check-permitted-tool-use", "record-evaluation-setup"])

    def test_an_outcome_that_does_not_apply_needs_no_value(self):
        payload = {"revision": "abc1234", "checks": [
            {"check": "rule:nist-ai-risk/set-risk-evidence", "status": "not-applicable",
             "reason": "No model change.", "owner": "Camille"}]}
        self.assertNotIn("value", validate_result(self.task, {}, payload)["checks"][0])

    def test_a_task_completed_before_the_attribute_still_loads_and_stays_done(self):
        result = {"revision": "abc1234", "criteria": [], "checks": [
            outcome(f"rule:{pack['id']}/{rule['id']}") for pack in self.packs for rule in pack["rules"]]}
        done = task_with(self.packs, status="done", result=result)
        self.assertEqual(completion_problems(done, {}), [])
        old = copy.deepcopy(self.packs)
        for pack in old:
            for rule in pack["rules"]:
                rule.pop("records", None)
        self.assertEqual(recorded_value(task_with(old), "rule:llm-evaluations/evaluate-user-outcomes"), {})

    def test_the_catalog_refuses_a_malformed_records_attribute(self):
        rule = {"id": "set-threshold", "instruction": "Agree on a threshold.", "verification": "Check it.",
                "records": {"name": "threshold", "description": "The agreed threshold."}}
        _validate_rule(rule, "rules[0]", False)
        for records, message in (({"name": "threshold"}, "missing fields: description"),
                                 ({**rule["records"], "min": 0, "above": 0}, "not both"),
                                 ({**rule["records"], "above": 100, "max": 100}, "greater than"),
                                 ({**rule["records"], "max": "100"}, "must be a number"),
                                 ({"name": "Threshold", "description": "x"}, "lowercase"),
                                 ({"name": "threshold", "description": "two\nlines"}, "single line")):
            with self.subTest(records=records), self.assertRaisesRegex(CatalogError, message):
                _validate_rule({**rule, "records": records}, "rules[0]", False)


if __name__ == "__main__":
    unittest.main()
