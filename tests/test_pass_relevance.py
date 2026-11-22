"""The board passes, the handoff and task checks ask the same rules of a task, every new consultation answers
the concerns question (issue 09 of the second audit), and a pass prints the packs its subject brings (issue 10)."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.project import load_profile
from openguildkit.relevance import pack_relevance
from openguildkit.storage import write_json

# A project on personal data with the GDPR pattern, and the regulations and methods a task on secrets, money or AI
# brings, so that the concerns answer changes what is asked.
PROJECT = {"name": "Support portal", "sector": "general", "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16"],
           "personal_data": "yes", "norms": {"gdpr-personal-data": "yes"}, "host": "other", "guard": "off",
           "research": "local-only", "checks": []}
BUG = {"kind": "bug", "surface": ["service"], "data": "personal", "research": "local", "concerns": ["none"],
       "outcome": "The export shows each request's date in the customer's time zone."}
RULES_HEADING = "## Rules of this board's packs that concern the task"


def printed_rules(text: str) -> set[str]:
    """PACK/RULE of each rule a pass prints under its rules heading."""
    rules, pack = set(), None
    for line in text[text.index(RULES_HEADING):].splitlines()[1:]:
        if line.startswith(("Also concern", "Not concerned", "No rule")) or line.endswith("(AGENTS.md)."):
            break
        heading = re.search(r"\(([\w-]+)@[^)]*\):$", line)
        if heading:
            pack = heading.group(1)
        elif line.startswith("- ") and pack:
            rules.add(f"{pack}/{line[2:].split(':', 1)[0]}")
    return rules


class ProjectCase(unittest.TestCase):
    """A project in a temporary folder, driven through the CLI, with an approval recorded at a terminal."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def cli(self, *arguments, code=0) -> str:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue() + stdout.getvalue())
        return stdout.getvalue() + stderr.getvalue() if code else stdout.getvalue()

    def init(self, answers: dict | None = None, **changes) -> None:
        write_json(self.root / "init.json", {**(answers or PROJECT), **changes})
        self.cli("init", "--answers", self.root / "init.json")

    def consult(self, task_id: str, brief: str, answers: dict) -> dict:
        self.cli("task", "new", brief, "--id", task_id)
        write_json(self.root / f"{task_id}.json", answers)
        self.cli("task", "consult", task_id, "--answers", self.root / f"{task_id}.json")
        return json.loads(self.cli("task", "show", task_id))

    def approve(self, task_id: str) -> None:
        """Record one entry per board from the template, then approve at a terminal."""
        template = json.loads(self.cli("task", "template", task_id))
        for entry in template["boards"]:
            entry["recommendation"] = f"{entry['id']} recommends going ahead."
            entry["evidence"] = [{"source": "project-file", "ref": ".openguildkit/project.json",
                                  "supports": f"{entry['id']} read the project profile."}]
            challenge = entry["challenge"]
            for lens in challenge["specialists"]:
                lens.update(finding=f"{entry['id']} {lens['id']}: no concern found.", basis="observed",
                            evidence_refs=[1])
            challenge.update(verdict="proceed", confidence="medium", alternative="None.", failure_mode="None.",
                             verification=f"{entry['id']}: run the tests.")
        template["summary"] = "Every board agrees."
        for key in ("evidence_item", "blocker_item"):
            template.pop(key, None)
        write_json(self.root / "review.json", template)
        self.cli("task", "review", task_id, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=task_id):
            self.cli("task", "decide", task_id, "--approve", "--by", "Camille Martin", "--reason", "Agreed")

    def asked(self, task_id: str, packs: set[str] | None = None) -> set[str]:
        checks = json.loads(self.cli("task", "checks", task_id, "--json"))
        return {check["id"][len("rule:"):] for check in checks if check["kind"] in ("rule", "machine")
                and check["concerned"] and (packs is None or check["pack"] in packs)}

    def board_packs(self, task: dict, board: str) -> set[str]:
        data = task["consultation"]["board_briefs"][board]
        named = {item.partition("/")[0] for group in data["not_concerned"] for item in group["items"]}
        return {pack["pack"].split("@")[0] for pack in data["rules"]} | named


class PassRelevanceTests(ProjectCase):
    def test_the_legal_pass_of_a_bug_on_personal_data_prints_only_the_rules_task_checks_asks(self):
        self.init()
        task = self.consult("pd-bug", "Fix the date column of the support requests export: it ignores the time zone.",
                            BUG)
        legal = self.cli("task", "pass", "pd-bug", "legal")
        printed = printed_rules(legal)
        self.assertIn("gdpr/minimise-collected-fields", printed)
        self.assertNotIn("gdpr/update-processing-record", printed)
        footer = legal[legal.index("Not concerned by this task"):]
        self.assertIn("update-processing-record", footer)
        self.assertIn("kind bug", footer)
        self.assertNotIn("task checks", legal)
        self.approve("pd-bug")
        self.assertEqual(printed, self.asked("pd-bug", self.board_packs(task, "legal")))

    def test_a_board_brief_and_task_checks_give_the_same_rules_for_a_log_migration(self):
        self.init()
        task = self.consult("log-move", "Move the application logs, which hold customer e-mails and IP addresses, to a "
                            "log platform hosted in the United States.",
                            {**BUG, "kind": "maintenance", "outcome": "Logs reach the new platform and nothing is lost."})
        legal = self.cli("task", "brief", "log-move", "--board", "legal")
        self.approve("log-move")
        self.assertEqual(printed_rules(legal), self.asked("log-move", self.board_packs(task, "legal")))

    def test_the_handoff_lists_the_rules_asked_then_one_line_for_the_others(self):
        self.init()
        self.consult("pd-bug", "Fix the date column of the support requests export: it ignores the time zone.", BUG)
        self.approve("pd-bug")
        handoff = self.cli("task", "handoff", "pd-bug")
        section = handoff[handoff.index("## Rules to apply"):handoff.index("## Advisory review")]
        listed = {f"{line[2:].split('@')[0]}/{rule}" for line in section.splitlines() if line.startswith("- ")
                  for rule in line.split(": ", 1)[1].split(", ")}
        self.assertEqual(listed, self.asked("pd-bug"))
        self.assertIn("gdpr@", section)
        self.assertNotIn("update-processing-record", section)
        self.assertEqual(len([line for line in section.splitlines() if line.startswith("Not concerned")]), 1)
        self.assertRegex(section, r"Not concerned by this task, so not asked \(each reason: openguildkit task checks "
                                  r"pd-bug\): .*gdpr \(\d+ of \d+ rules\)")

    def test_the_handoff_of_a_decision_task_has_no_rules_to_apply(self):
        self.init()
        self.consult("export-mode", "Decide whether the export should be a CSV download or an e-mailed report.",
                     {**BUG, "kind": "decision", "options": "CSV download or e-mailed report."})
        self.approve("export-mode")
        handoff = self.cli("task", "handoff", "export-mode")
        self.assertNotIn("Rules to apply", handoff)
        self.assertEqual(self.asked("export-mode"), set())

    def test_every_command_a_pass_names_runs_while_the_task_is_consulted(self):
        self.init(patterns=["threat-modeling", "owasp-asvs-review"])
        task = self.consult("export-none", "Let signed-in customers export their own support requests as a CSV file.",
                            {**BUG, "kind": "feature", "surface": ["customer", "service"], "data": "internal",
                             "outcome": "A customer downloads a CSV with only the requests they opened.",
                             "affected": "Customers of the support portal"})
        self.assertEqual(task["status"], "consulting")
        pack = task["consultation"]["scope"]["packs"][0]["id"]
        for board in task["consultation"]["boards"]:
            text = self.cli("task", "pass", "export-none", board)
            self.assertNotIn("task checks", text)
            for group in task["consultation"]["board_briefs"][board]["not_concerned"]:
                self.assertTrue(group["reason"])
                self.assertIn(f": {group['reason']}.", text)
            for command in re.findall(r"openguildkit ((?:task|brains) [^.\n`]*?)(?:\.|$|`|\))", text, re.M):
                words = command.replace("PACK", pack).replace("BOARD", board).split()
                if "pass" in words or "submit" in words or "ID" in words:
                    continue
                with self.subTest(board=board, command=command):
                    self.cli(*words)

    def test_a_new_consultation_needs_the_concerns_answer(self):
        self.init()
        self.cli("task", "new", "Fix the date column of the support requests export.", "--id", "no-concerns")
        answers = {key: value for key, value in BUG.items() if key != "concerns"}
        write_json(self.root / "answers.json", answers)
        questions = json.loads(self.cli("task", "questions", "no-concerns", "--answers", self.root / "answers.json"))
        follow_up = next(item for item in questions["follow_ups"] if item["id"] == "concerns")
        self.assertEqual([choice["id"] for choice in follow_up["choices"]],
                         ["money", "ai", "people-decisions", "credentials", "none", "unsure"])
        self.assertEqual(follow_up["type"], "multi-select")
        for action in ("consult", "route"):
            with self.subTest(action=action):
                refusal = self.cli("task", action, "no-concerns", "--answers", self.root / "answers.json", code=1)
                self.assertIn("Answer concerns", refusal)
                self.assertIn("money, ai, people-decisions, credentials, none, unsure", refusal)
        write_json(self.root / "answers.json", BUG)
        questions = json.loads(self.cli("task", "questions", "no-concerns", "--answers", self.root / "answers.json"))
        self.assertNotIn("concerns", [item["id"] for item in questions["follow_ups"]])
        self.cli("task", "consult", "no-concerns", "--answers", self.root / "answers.json")

    def test_a_task_consulted_without_concerns_keeps_its_recorded_answers(self):
        self.init()
        task = self.consult("old", "Fix the date column of the support requests export.", BUG)
        record = self.root / ".openguildkit" / "tasks" / "old.json"
        task["answers"].pop("concerns")
        task["consultation"]["scope"]["answers"].pop("concerns")
        write_json(record, task)
        self.assertIn("engineering", self.cli("task", "route", "old"))
        self.cli("task", "brief", "old", "--board", "legal")

    def test_unsure_concerns_consult_the_boards_of_every_topic_and_cover_every_rule_asked(self):
        self.init(patterns=["gdpr-personal-data", "eu-ai-act-system", "pci-dss-cardholder-data", "threat-modeling",
                            "iso-27001-isms", "finops"])
        task = self.consult("unsure", "Change how the scheduler picks the next support request.",
                            {**BUG, "concerns": ["unsure"]})
        routing = task["consultation"]["routing"]
        self.assertLessEqual({"legal", "data", "security", "finance", "devops"}, set(routing))
        self.assertTrue(any(reason.startswith("Concerns unsure") for reason in routing["finance"]))
        profile = load_profile(self.root / ".openguildkit", self.catalog)
        relevance = pack_relevance(task, profile, self.catalog, None)
        asked = {pack for pack, entry in relevance.items() if entry["concerned"]} - {"agent-workflow"}
        self.assertLessEqual({"eu-ai-act", "threat-modeling", "iso-27001", "incident-notification"}, asked)
        covered = {pack["pack"].split("@")[0] for brief in task["consultation"]["board_briefs"].values()
                   for pack in brief["rules"]}
        self.assertEqual(asked - covered, set())

    def test_a_report_button_asks_the_notice_and_action_rules_in_the_trust_and_safety_pass(self):
        self.init(patterns=["notice-and-action"])
        task = self.consult("report-button", "Let users report illegal content in community forum posts and let "
                            "moderators remove them.",
                            {**BUG, "kind": "feature", "surface": ["customer", "service"],
                             "outcome": "A reported post reaches a moderator, who can remove it.",
                             "affected": "Forum members and moderators"})
        self.assertIn("trust-and-safety", task["consultation"]["boards"])
        rules = printed_rules(self.cli("task", "brief", "report-button", "--board", "trust-and-safety"))
        self.assertLessEqual({"notice-and-action/offer-reporting", "notice-and-action/send-statement-of-reasons"},
                             rules)

    def test_unsure_is_offered_at_the_terminal_and_recorded_as_an_answer(self):
        self.init()
        self.cli("task", "new", "Fix the date column of the support requests export: it ignores the time zone.",
                 "--id", "typed")
        typed = iter(["bug", "service", "personal", "local", "?", "Dates follow the customer's time zone.",
                      "Customers who export their requests", ""])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=lambda: next(typed)):
            self.cli("task", "consult", "typed")
        self.assertEqual(json.loads(self.cli("task", "show", "typed"))["answers"]["concerns"], ["unsure"])


if __name__ == "__main__":
    unittest.main()
