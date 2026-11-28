"""The setup questionnaire: tools, host, guard and norms, defaults that hold in every mode, additive packs."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.cli import _interactive_init, main
from openguildkit.guard import guard_mode
from openguildkit.project import load_profile, validate_profile
from openguildkit.project_setup import init_questions, setup_profile
from openguildkit.storage import read_json, write_json

from tests.support import CapturedCli

NEXTJS = ["Next.js 14.2", "React 18.3", "TypeScript"]
FASTAPI = '[project]\nname = "svc"\ndependencies = ["fastapi>=0.115", "sqlalchemy>=2.0"]\n'


class QuestionnaireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def questions(self, **extra):
        return {question["id"]: question for question in init_questions(self.catalog, "Ledger", **extra)}

    def test_the_questionnaire_asks_tools_host_guard_and_each_norm(self):
        questions = self.questions(tools=[{"tool": "github", "signals": [".github/workflows/*.yml"]}])
        order = list(questions)
        for question_id in ("tools", "host", "guard", "norms"):
            self.assertIn(question_id, questions)
        self.assertLess(order.index("personal_data"), order.index("norms"))
        self.assertLess(order.index("norms"), order.index("patterns"))
        self.assertEqual(questions["tools"]["default"], ["github"])
        self.assertEqual(questions["tools"]["detected"][0]["tool"], "github")
        self.assertEqual([choice["id"] for choice in questions["host"]["choices"]], ["claude-code", "codex", "gemini-cli", "other"])
        self.assertEqual(questions["host"]["default"], "other")
        detected = self.questions(host="codex")["host"]
        self.assertEqual((detected["default"], detected["detected"]), ("other", "codex"))
        self.assertIn("Codex files", detected["prompt"])
        guard = questions["guard"]
        self.assertEqual(guard["default"], "observe")
        labels = {choice["id"]: choice["label"] for choice in guard["choices"]}
        self.assertEqual(set(labels), {"off", "observe", "enforce"})
        self.assertIn("signed", labels["enforce"])
        norms = {norm["id"]: norm for norm in questions["norms"]["norms"]}
        self.assertEqual(norms["dora-financial-entity"]["when"], {"sectors": ["financial-services", "insurance"]})
        self.assertEqual(norms["gdpr-personal-data"]["when"], {"sectors": ["financial-services"], "personal_data": True})
        self.assertIn("nis2-essential-entity", norms)
        # The AI Act and PCI DSS are norms too: decisions about people and a card payment provider propose them.
        self.assertEqual(norms["eu-ai-act-system"]["when"], {"people_decisions": True})
        self.assertIn("Stripe", norms["pci-dss-cardholder-data"]["when"]["stack"][0])
        self.assertTrue(all(norm["prompt"].endswith("?") for norm in norms.values()))

    def test_every_question_says_what_enter_keeps(self):
        for question in self.questions().values():
            with self.subTest(question=question["id"]):
                self.assertTrue(
                    "default" in question or "default_label" in question or question.get("required"), question
                )
        boards = self.questions()["boards"]
        self.assertEqual(boards["default"], [])
        self.assertIn("all", boards["default_label"])
        self.assertNotIn("Enter to enable all", boards["prompt"])
        self.assertEqual(self.questions()["packs"]["default"], [])

    def test_norm_answers_keep_or_decline_each_preselected_regulation(self):
        no = {"answer": "no", "by": "Camille Martin", "reason": "Not a financial entity under DORA Art. 2"}
        answers = {"name": "Ledger", "sector": "financial-services", "personal_data": "yes",
                   "norms": {"dora-financial-entity": no, "gdpr-personal-data": "yes", "european-accessibility-act": "yes"}}
        with patch.dict("os.environ", {"SOURCE_DATE_EPOCH": "1795219200"}):
            profile, _ = setup_profile(answers, self.catalog, init_questions(self.catalog, "Ledger"))
        self.assertEqual(profile["declined"], [{"id": "dora-financial-entity", "by": "Camille Martin",
                                                "on": "2026-11-21", "reason": no["reason"]}])
        self.assertIn("gdpr-personal-data", profile["patterns"])
        self.assertNotIn("dora-financial-entity", profile["patterns"])
        no_bank = {"answer": "no", "by": "Camille Martin", "reason": "No consumer banking service"}
        with_patterns = {**answers, "patterns": [], "norms": {"gdpr-personal-data": True, "dora-financial-entity": no,
                                                              "european-accessibility-act": no_bank}}
        profile, _ = setup_profile(with_patterns, self.catalog, init_questions(self.catalog, "Ledger"))
        self.assertEqual(profile["patterns"], ["gdpr-personal-data"])
        for norms, message in (({"gdpr-personal-data": "maybe"}, "yes or no"), ({"python-development": "yes"}, "norm"),
                               ({"gdpr-personal-data": "no"}, "who and why"),
                               ({"gdpr-personal-data": {"answer": "no", "by": "Camille"}}, "who and why"),
                               (["gdpr-personal-data"], "norms")):
            with self.subTest(norms=norms), self.assertRaisesRegex(ValueError, message):
                setup_profile({"name": "Ledger", "norms": norms}, self.catalog, init_questions(self.catalog, "Ledger"))


class AdditivePackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def profile(self, **answers):
        return setup_profile({"name": "Shop", **answers}, self.catalog, init_questions(self.catalog, "Shop"))[0]

    def test_adding_gdpr_to_a_nextjs_stack_keeps_the_recommended_packs_and_the_stack_patterns(self):
        baseline = self.profile(stack=NEXTJS)
        with_gdpr = self.profile(stack=NEXTJS, packs=["gdpr"])
        self.assertTrue({"secure-sdlc", "typescript", "react"} <= set(baseline["packs"]))
        self.assertEqual(with_gdpr["packs"], [*baseline["packs"], "gdpr"])
        self.assertEqual(with_gdpr["patterns"], baseline["patterns"])
        self.assertTrue(any("next" in pattern for pattern in baseline["patterns"]))

    def test_the_answers_can_still_replace_the_default_packs(self):
        profile = self.profile(stack=NEXTJS, packs=["gdpr"], replace_default_packs=True)
        self.assertEqual(profile["packs"], ["agent-workflow", "gdpr"])
        self.assertTrue(profile["patterns"])
        with self.assertRaisesRegex(ValueError, "replace_default_packs"):
            self.profile(stack=NEXTJS, replace_default_packs="yes")

    def test_a_saved_profile_keeps_its_packs_on_load(self):
        saved = {"personal_data": "no", "name": "Shop", "stack": NEXTJS, "packs": ["agent-workflow", "gdpr"]}
        self.assertEqual(validate_profile(saved, self.catalog)["packs"], ["agent-workflow", "gdpr"])
        self.assertNotIn("patterns", validate_profile(saved, self.catalog))


class InitCommandTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ledger"
        self.root.mkdir()
        self.answers = Path(temporary.name) / "answers.json"

    def init(self, answers):
        write_json(self.answers, answers)
        return self.run_cli("init", "--answers", self.answers)

    def profile(self):
        return read_json(self.root / ".openguildkit" / "project.json")

    def test_answers_without_personal_data_are_refused_with_the_question_named(self):
        for answers in ({}, {"name": "X", "sector": "general", "stack": ["Python"]}):
            with self.subTest(answers=answers):
                write_json(self.answers, answers)
                _, error = self.run_cli("init", "--answers", self.answers, code=1)
                self.assertIn("personal_data", error)
                self.assertIn("Does the project process personal data", error)
                self.assertIn("Nothing was written", error)
                self.assertFalse((self.root / ".openguildkit").exists())
        # "unsure" is an answer: the protective one, which proposes the laws on personal data.
        write_json(self.answers, {"name": "X", "stack": ["Python"], "personal_data": "unsure"})
        _, error = self.run_cli("init", "--answers", self.answers, code=1)
        self.assertIn("gdpr-personal-data", error)
        self.init({"name": "X", "stack": ["Python"], "personal_data": "no"})
        self.assertIs(self.profile()["personal_data"], False)

    def test_empty_answers_take_every_documented_default(self):
        (self.root / "pyproject.toml").write_text(FASTAPI, encoding="utf-8")
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions")[0])}
        self.init({"personal_data": "no"})
        profile = self.profile()
        self.assertEqual(profile["name"], "ledger")
        self.assertEqual(profile["components"], questions["components"]["default"])
        self.assertIn("FastAPI", " ".join(profile["stack"]))
        self.assertEqual((profile["sector"], profile["research"], profile["host"], profile["guard"]),
                         ("general", "local-only", "other", "observe"))
        self.assertEqual(profile["boards"], [])
        self.assertIn("python", " ".join(item if isinstance(item, str) else item["id"] for item in profile["patterns"]))

    def test_init_warns_about_the_detected_components_the_answers_leave_aside(self):
        for folder in ("api", "worker"):
            (self.root / folder).mkdir()
            (self.root / folder / "pyproject.toml").write_text(FASTAPI, encoding="utf-8")
        _, error = self.init({"personal_data": "no", "name": "svc", "stack": ["Python"]})
        self.assertIn("components", error)
        self.assertIn("FastAPI", error)
        self.assertNotIn("components", self.profile())

    def test_init_keeps_a_single_detected_root_with_the_written_stack(self):
        (self.root / "pyproject.toml").write_text(FASTAPI, encoding="utf-8")
        _, error = self.init({"personal_data": "no", "name": "svc", "stack": ["Python"]})
        self.assertNotIn("left aside", error)
        [component] = self.profile()["components"]
        self.assertEqual(component["path"], ".")
        self.assertTrue(any(item.startswith("FastAPI") for item in component["stack"]), component)
        self.assertTrue(any(item.startswith("Python") for item in component["stack"]), component)

    def test_a_new_project_without_a_guard_answer_brings_the_board_without_blocking(self):
        output, _ = self.init({"name": "svc", "personal_data": "no"})
        self.assertEqual(self.profile()["guard"], "observe")
        self.assertIn("observe", output)
        self.assertIn("not blocked", output)
        context = json.loads(self.run_cli("guard", "--hook", "prompt", stdin="")[0])
        self.assertIn("no approved task", context["hookSpecificOutput"]["additionalContext"])
        edit = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "app.py")}})
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=edit)
        self.assertIn("flagged, not blocked", json.loads(output)["hookSpecificOutput"]["additionalContext"])

    def test_an_existing_profile_without_a_guard_stays_off(self):
        self.init({"personal_data": "no", "name": "svc", "guard": "off"})
        profile = self.profile()
        del profile["guard"]
        write_json(self.root / ".openguildkit" / "project.json", profile)
        self.run_cli("sync")
        self.assertNotIn("guard", self.profile())
        self.assertEqual(guard_mode(load_profile(self.root / ".openguildkit", load_catalog())), "off")
        self.assertEqual(self.run_cli("guard", "--hook", "prompt", stdin=""), ("", ""))

    def test_init_prints_only_the_next_steps_that_apply(self):
        output, error = self.init({"personal_data": "no", "name": "svc", "host": "claude-code", "tools": ["Jira", "Acme Timesheets"]})
        self.assertIn("openguildkit host apply", output)
        self.assertIn("openguildkit tools plan jira", output)
        self.assertIn("Acme Timesheets", output)
        self.assertEqual(self.profile()["tools"], ["Jira", "Acme Timesheets"])
        other = Path(self.root.parent / "plain")
        other.mkdir()
        self.root = other
        output, _ = self.init({"name": "plain", "personal_data": "no"})
        self.assertNotIn("host apply", output)
        self.assertNotIn("tools plan", output)

    def test_preview_applies_the_same_defaults_as_init(self):
        (self.root / "pyproject.toml").write_text(FASTAPI, encoding="utf-8")
        write_json(self.answers, {"personal_data": "no", "name": "svc", "packs": ["gdpr"]})
        plan = json.loads(self.run_cli("preview", "--answers", self.answers, "--json")[0])
        packs = [pack["id"] for pack in plan["packs"]]
        self.assertIn("gdpr", packs)
        self.assertIn("secure-sdlc", packs)
        self.assertIn("python", packs)


class InteractiveInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def run_init(self, replies, **extra):
        questions = init_questions(self.catalog, "Ledger", **extra)
        errors = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=replies), \
                contextlib.redirect_stderr(errors):
            answers = _interactive_init(questions, self.catalog)
        return answers, errors.getvalue(), questions

    def test_each_norm_is_confirmed_or_declined_with_its_reason(self):
        # name, sector, stack, roles, personal data, decisions about people, DORA (no, who, why), the European
        # Accessibility Act, GDPR, patterns, packs, boards, tools, host, guard, research, conventions, checks.
        replies = ["Ledger", "financial-services", "Python", "", "yes", "", "n", "Camille Martin",
                   "Not a financial entity", "", "", "", "gdpr", "",
                   "Jira, Acme Timesheets", "", "", "", "", ""]
        answers, text, questions = self.run_init(replies)
        self.assertIn("dora-financial-entity", text)
        self.assertIn("sector financial-services", text)
        self.assertIn("personal data", text)
        self.assertIn("Default: all boards", text)
        self.assertIn("Default: observe", text)
        self.assertIn("Default: other", text)
        self.assertIn("Not in the registry, kept as written: Acme Timesheets", text)
        profile, _ = setup_profile(answers, self.catalog, questions)
        self.assertEqual([(entry["id"], entry["by"]) for entry in profile["declined"]],
                         [("dora-financial-entity", "Camille Martin")])
        self.assertIn("gdpr-personal-data", profile["patterns"])
        self.assertIn("python-development", profile["patterns"])
        self.assertTrue({"secure-sdlc", "python", "gdpr"} <= set(profile["packs"]))
        self.assertEqual(profile["boards"], [])
        self.assertEqual((profile["guard"], profile["host"]), ("observe", "other"))
        self.assertEqual(profile["tools"], ["Jira", "Acme Timesheets"])

    def test_the_packs_prompt_shows_the_recommended_packs_that_enter_keeps(self):
        replies = ["Ledger", "general", "Python", "", "no", "", "", "", "", "", "", "", "", "", ""]
        answers, text, questions = self.run_init(replies)
        line = next(line for line in text.splitlines() if "Default:" in line and "secure-sdlc" in line)
        self.assertIn("python", line)
        profile, _ = setup_profile(answers, self.catalog, questions)
        self.assertTrue({"agent-workflow", "secure-sdlc", "python"} <= set(profile["packs"]))

    def test_a_dash_on_packs_replaces_the_recommended_packs(self):
        replies = ["Ledger", "general", "Python", "", "no", "-", "-", "", "", "", "", "", "", ""]
        answers, _, questions = self.run_init(replies)
        profile, _ = setup_profile(answers, self.catalog, questions)
        self.assertEqual(profile["packs"], ["agent-workflow"])
        self.assertNotIn("patterns", profile)


class SkillSetupTests(unittest.TestCase):
    def test_the_skill_asks_the_questions_in_the_questionnaire_order_and_never_answers_for_the_user(self):
        # The setup procedure is a reference file of the skill: SKILL.md says when to read it.
        folder = Path(__file__).resolve().parents[1] / "integrations" / "skills" / "openguildkit"
        self.assertRegex((folder / "SKILL.md").read_text(encoding="utf-8"), r"references/setup\.md[^\n]*\bwhen\b")
        setup = (folder / "references" / "setup.md").read_text(encoding="utf-8")
        self.assertIn("Never answer a question for the user", setup)
        order = [question["id"] for question in init_questions(load_catalog(), "Ledger")]
        positions = [setup.index(f"`{question_id}`") for question_id in order]
        self.assertEqual(positions, sorted(positions), order)


if __name__ == "__main__":
    unittest.main()
