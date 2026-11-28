"""One rule set aside by the person, with who, when and why, and restored the same way (RFC #447).

`openguildkit profile decline rule PACK/RULE` is typed at a terminal: the rule is no longer asked of a task, checked by
task verify or listed with its pack in AGENTS.md, which names it under the profile decisions. `profile adopt rule`
restores it. A project that never declines a rule reads, writes and fingerprints exactly what it did before.
"""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.profile_changes import check_proposal
from openguildkit.project import rules_in_force, validate_profile
from openguildkit.project_instructions import render_instructions
from openguildkit.project_rules import profile_fingerprint, rule_plan
from openguildkit.results import expected_checks
from openguildkit.storage import write_json
from tests.support import run_cli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
DAY = {"SOURCE_DATE_EPOCH": "1795219200"}  # 2026-11-21
RULE = "python/declare-package-metadata"
DECLINE = ("profile", "decline", "rule", RULE, "--by", "Camille Martin", "--reason", "Not a published package")


class RuleDeclineCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"]})
        self.cli("init", "--answers", self.root / "answers.json")

    def cli(self, *arguments, code=0, typed=None):
        result = run_cli(self.root, *arguments, expect=code, typed=typed, env=DAY)
        return result.stdout, result.stderr

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def agents(self) -> str:
        return (self.root / "AGENTS.md").read_text(encoding="utf-8")

    def test_declining_a_rule_is_typed_at_a_terminal_and_recorded_with_who_when_and_why(self):
        before = self.profile()
        _, error = self.cli(*DECLINE, code=1)
        self.assertIn(f"rule {RULE} declined", error)
        self.assertIn("interactive terminal", error)
        self.assertEqual(self.profile(), before)
        output, _ = self.cli(*DECLINE, typed=RULE)
        self.assertIn(f"Profile changed: decline rule {RULE}, by Camille Martin on 2026-11-21", output)
        self.assertIn(f"openguildkit profile adopt rule {RULE}", output)
        profile = self.profile()
        self.assertEqual(profile["declined_rules"], [{"id": RULE, "by": "Camille Martin", "on": "2026-11-21",
                                                      "reason": "Not a published package"}])
        self.assertEqual(profile["changes"][-1]["change"], f"decline rule {RULE}")
        self.cli("check")

    def test_agents_md_leaves_the_rule_out_of_its_pack_and_names_it_with_its_reason(self):
        self.assertIn("`declare-package-metadata`", self.agents())
        self.cli(*DECLINE, typed=RULE)
        agents = self.agents()
        pack_line = next(line for line in agents.splitlines() if line.startswith("`follow-python-style`"))
        self.assertNotIn("declare-package-metadata", pack_line)
        self.assertIn(f"Declined rule `{RULE}` by Camille Martin on 2026-11-21: Not a published package.", agents)
        self.assertIn(f"openguildkit profile adopt rule {RULE}", agents)

    def test_a_task_consulted_after_the_decline_is_neither_asked_nor_checked_the_rule(self):
        self.cli(*DECLINE, typed=RULE)
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "after")
        consultation, _ = self.cli("task", "consult", "after", "--answers", EXAMPLE / "answers.json")
        self.assertIn(f"Rules declined, asked of no task: {RULE} by Camille Martin on 2026-11-21: "
                      "Not a published package.", consultation)
        task = json.loads((self.root / ".openguildkit" / "tasks" / "after.json").read_text(encoding="utf-8"))
        python = next(pack for pack in task["consultation"]["scope"]["packs"] if pack["id"] == "python")
        self.assertNotIn("declare-package-metadata", [rule["id"] for rule in python["rules"]])
        # What task checks, task result and task verify ask: the checks of the approved scope.
        ids = {check["id"] for check in expected_checks(task, self.profile())}
        self.assertIn("rule:python/follow-python-style", ids)
        self.assertNotIn(f"rule:{RULE}", ids)

    def test_a_task_consulted_before_the_decline_is_told_the_rule_was_removed(self):
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "before")
        self.cli("task", "consult", "before", "--answers", EXAMPLE / "answers.json")
        output, _ = self.cli(*DECLINE, typed=RULE)
        self.assertIn("before", output)

    def test_restoring_the_rule_gives_back_the_same_instructions_and_fingerprint(self):
        # OGK-PROFILE-009
        agents, catalog = self.agents(), load_catalog()
        fingerprint = profile_fingerprint(self.profile(), catalog)
        self.cli(*DECLINE, typed=RULE)
        self.assertNotEqual(profile_fingerprint(self.profile(), catalog), fingerprint)
        _, error = self.cli("profile", "adopt", "rule", "python/follow-python-style", "--by", "Sam", "--reason", "x",
                            code=1)
        self.assertIn("is not declined", error)
        output, _ = self.cli("profile", "adopt", "rule", RULE, "--by", "Sam", "--reason", "We publish it now")
        self.assertIn(f"Profile changed: adopt rule {RULE}", output)
        profile = self.profile()
        self.assertNotIn("declined_rules", profile)
        self.assertEqual(profile_fingerprint(profile, catalog), fingerprint)
        self.assertEqual(self.agents(), agents)

    def test_an_unknown_rule_is_refused_with_the_closest_one(self):
        # OGK-PROFILE-002
        before = self.profile()
        _, error = self.cli("profile", "decline", "rule", "python/declare-package-metadat", "--by", "S", "--reason", "x",
                            code=1, typed="x")
        # OGK-PROFILE-003
        self.assertIn("Unknown rule python/declare-package-metadat", error)
        self.assertIn(f"Did you mean {RULE}?", error)
        _, error = self.cli("profile", "decline", "rule", "python", "--by", "S", "--reason", "x", code=1)
        self.assertIn("PACK/RULE", error)
        self.assertEqual(self.profile(), before)

    def test_the_rule_id_of_a_check_is_accepted_as_written_by_task_checks(self):
        self.cli("profile", "decline", "rule", f"rule:{RULE}", "--by", "S", "--reason", "x", typed=RULE)
        self.assertEqual([entry["id"] for entry in self.profile()["declined_rules"]], [RULE])

    def test_a_rule_not_in_force_already_declined_or_of_the_workflow_is_refused(self):
        # OGK-PROFILE-004, OGK-PROFILE-005, OGK-PROFILE-006
        cases = (("gdpr/update-processing-record", "not in force"),
                 ("agent-workflow/scope-before-edits", "required by OpenGuildKit"))
        for rule, words in cases:
            with self.subTest(rule=rule):
                _, error = self.cli("profile", "decline", "rule", rule, "--by", "S", "--reason", "x", code=1, typed=rule)
                self.assertIn(words, error)
        self.cli(*DECLINE, typed=RULE)
        _, error = self.cli(*DECLINE, code=1, typed=RULE)
        self.assertIn("already declined", error)

    def test_the_last_rule_of_a_pack_in_force_is_not_declined_one_by_one(self):
        # OGK-PROFILE-008
        for rule in ("python/follow-python-style", "python/type-public-interfaces"):
            self.cli("profile", "decline", "rule", rule, "--by", "S", "--reason", "x", typed=rule)
        _, error = self.cli(*DECLINE, code=1, typed=RULE)
        self.assertIn("last rule of pack python", error)

    def test_a_required_rule_is_removed_from_the_required_rules_before_it_is_declined(self):
        # OGK-PROFILE-007
        for required in ("python", RULE):
            with self.subTest(required=required):
                self.cli("profile", "add", "required-rule", required, "--by", "S", "--reason", "Audit")
                _, error = self.cli(*DECLINE, code=1, typed=RULE)
                self.assertIn(f"openguildkit profile remove required-rule {required}", error)
                self.assertNotIn("declined_rules", self.profile())
                self.cli("profile", "remove", "required-rule", required, "--by", "S", "--reason", "x", typed=required)
        self.cli(*DECLINE, typed=RULE)
        for required in ("python", RULE):
            with self.subTest(required=required):
                _, error = self.cli("profile", "add", "required-rule", required, "--by", "S", "--reason", "x", code=1)
                self.assertIn(f"openguildkit profile adopt rule {RULE}", error)

    def test_the_web_page_cannot_decline_a_rule(self):
        # OGK-PROFILE-034
        from openguildkit.profile_changes import Weakening, save_edited
        edited = {**self.profile(), "declined_rules": [{"id": RULE, "by": "S", "on": "2026-11-21", "reason": "x"}]}
        with self.assertRaises(Weakening):
            save_edited(self.root, self.root / ".openguildkit", edited, "S", "x")
        self.assertNotIn("declined_rules", self.profile())

    def test_the_export_does_not_carry_a_declined_rule_and_says_how_to_decline_it_again(self):
        self.cli(*DECLINE, typed=RULE)
        answers, notes = self.cli("profile", "export")
        self.assertNotIn("declined_rules", answers)
        self.assertNotIn("Camille", answers + notes)
        self.assertIn(f"openguildkit profile decline rule {RULE} --by INITIALS --reason WHY", notes)


class NothingChangesWithoutADeclinedRuleTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.profile = validate_profile(json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")),
                                        self.catalog)

    def test_a_profile_without_a_declined_rule_has_no_new_field_and_the_packs_are_the_catalogs(self):
        self.assertNotIn("declined_rules", self.profile)
        self.assertNotIn("declined_rules", validate_profile({**self.profile, "declined_rules": []}, self.catalog))
        for pack_id in rule_plan(self.profile, self.catalog)["packs"]:
            pack = self.catalog["packs"][pack_id["id"]]
            self.assertIs(rules_in_force(pack, self.profile), pack)

    def test_who_and_why_do_not_change_the_fingerprint_but_the_rule_does(self):
        def declined(by: str) -> dict:
            entry = {"id": RULE, "by": by, "on": "2026-11-21", "reason": by}
            return validate_profile({**self.profile, "declined_rules": [entry]}, self.catalog)
        self.assertEqual(profile_fingerprint(declined("A"), self.catalog),
                         profile_fingerprint(declined("B"), self.catalog))
        self.assertNotEqual(profile_fingerprint(declined("A"), self.catalog),
                            profile_fingerprint(self.profile, self.catalog))
        self.assertNotIn("declare-package-metadata`,", render_instructions(declined("A"), self.catalog))
        plan = rule_plan(declined("A"), self.catalog)
        self.assertEqual(plan["rule_count"], rule_plan(self.profile, self.catalog)["rule_count"] - 1)
        self.assertEqual([entry["id"] for entry in plan["declined_rules"]], [RULE])

    def test_a_profile_refuses_a_rule_both_required_and_declined_or_written_without_its_pack(self):
        # OGK-PROJECT-009, OGK-PROJECT-010, OGK-PROJECT-011
        entry = {"id": RULE, "by": "S", "on": "2026-11-21", "reason": "x"}
        with self.assertRaisesRegex(ValueError, "both required and declined"):
            validate_profile({**self.profile, "required_rules": ["python"], "declined_rules": [entry]}, self.catalog)
        with self.assertRaisesRegex(ValueError, "PACK/RULE"):
            validate_profile({**self.profile, "declined_rules": [{**entry, "id": "python"}]}, self.catalog)
        with self.assertRaisesRegex(ValueError, "declined_rules"):
            validate_profile({**self.profile, "declined_rules": [{"id": RULE}]}, self.catalog)

    def test_the_proposal_check_knows_the_rule_decline(self):
        updated, weakens = check_proposal(self.profile, self.catalog, "decline", "rule", RULE)
        self.assertEqual([entry["id"] for entry in updated["declined_rules"]], [RULE])
        self.assertEqual(weakens, [f"rule {RULE} declined"])
        self.assertNotIn("declined_rules", self.profile)


if __name__ == "__main__":
    unittest.main()
