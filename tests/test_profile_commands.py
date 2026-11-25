"""The profile changes after setup through openguildkit profile, with who, when and why, never by hand."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json
from tests.support import run_cli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
DAY = {"SOURCE_DATE_EPOCH": "1795219200"}  # 2026-11-21


class ProfileCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"]})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def run_cli(self, *arguments, code=0):
        result = run_cli(self.root, *arguments, expect=code, env=DAY)
        return result.stdout, result.stderr

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def agents(self) -> str:
        return (self.root / "AGENTS.md").read_text(encoding="utf-8")

    def test_a_second_init_fails_and_names_the_profile_command(self):
        _, error = self.run_cli("init", "--answers", self.root / "answers.json", code=1)
        self.assertIn("already initialized", error)
        self.assertIn("openguildkit profile", error)

    def test_adopt_records_who_when_and_why_and_rewrites_the_instructions(self):
        output, _ = self.run_cli("profile", "adopt", "gdpr-personal-data", "--by", "Camille Martin",
                                 "--reason", "The sign-up form stores emails")
        self.assertIn("Profile changed: adopt gdpr-personal-data, by Camille Martin on 2026-11-21", output)
        self.assertIn("gdpr-personal-data", self.profile()["patterns"])
        self.assertEqual(self.profile()["changes"][-1], {"change": "adopt gdpr-personal-data", "by": "Camille Martin",
                                                         "on": "2026-11-21", "reason": "The sign-up form stores emails"})
        self.assertIn("Adopted `gdpr-personal-data` by Camille Martin on 2026-11-21", self.agents())
        preview, _ = self.run_cli("preview")
        self.assertRegex(preview, r"gdpr-personal-data \(\d+ rules\)")
        self.assertIn("adopted by Camille Martin on 2026-11-21: The sign-up form stores emails", preview)
        self.run_cli("check")

    def test_declining_a_regulation_is_typed_at_a_terminal_and_shows_everywhere(self):
        self.run_cli("profile", "adopt", "gdpr-personal-data", "--by", "Camille", "--reason", "Emails")
        arguments = ("profile", "decline", "gdpr-personal-data", "--by", "Camille Martin", "--reason", "No personal data")
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli(*arguments, code=1)
        self.assertIn("weakens a protection", error)
        self.assertIn("gdpr-personal-data", self.profile()["patterns"])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="gdpr-personal-data"):
            self.run_cli(*arguments)
        profile = self.profile()
        self.assertNotIn("gdpr-personal-data", profile.get("patterns", []))
        self.assertEqual(profile["declined"], [{"id": "gdpr-personal-data", "by": "Camille Martin", "on": "2026-11-21",
                                                "reason": "No personal data"}])
        self.assertIn("Declined `gdpr-personal-data` by Camille Martin on 2026-11-21: No personal data", self.agents())
        preview, _ = self.run_cli("preview")
        self.assertIn("Declined, not active: gdpr-personal-data by Camille Martin", preview)
        recommend, _ = self.run_cli("recommend")
        self.assertIn("gdpr-personal-data by Camille Martin on 2026-11-21: No personal data", recommend)
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        consultation, _ = self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        self.assertIn("- Declined, not active: gdpr-personal-data by Camille Martin on 2026-11-21: No personal data.",
                      consultation)
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        record = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertEqual(record["declined"], profile["declined"])
        self.run_cli("check")

    def test_a_tool_or_the_guard_leaves_an_approval_and_a_pack_voids_it(self):
        self.approved_task()
        self.run_cli("profile", "add", "tool", "jira", "--by", "Sam", "--reason", "Team practice")
        self.run_cli("profile", "set", "guard", "enforce", "--by", "Sam", "--reason", "The guard enforces")
        listed, _ = self.run_cli("task", "list")
        self.assertIn(TASK, listed)
        self.assertNotIn("no longer holds", listed)
        self.run_cli("profile", "add", "pack", "api-design", "--by", "Sam", "--reason", "Public API")
        listed, _ = self.run_cli("task", "list")
        self.assertIn("approval no longer holds", listed)

    def test_lowering_the_guard_or_allowing_public_research_needs_a_terminal(self):
        for field, value in (("guard", "off"), ("research", "public-sources")):
            with self.subTest(field=field), patch("sys.stdin.isatty", return_value=False):
                _, error = self.run_cli("profile", "set", field, value, "--by", "Sam", "--reason", "Demo", code=1)
                self.assertIn("is the person's decision", error)
        output, _ = self.run_cli("profile", "set", "guard", "enforce", "--by", "Sam", "--reason", "Audit")
        self.assertIn("openguildkit host apply", output)
        self.assertEqual(self.profile()["guard"], "enforce")

    def test_every_weakening_needs_a_terminal_and_names_what_it_weakens(self):
        setup = [("add", "pack", "gdpr", "gdpr"), ("add", "pack", "llm-evaluations", "llm-evaluations"),
                 ("set", "personal-data", "yes", "yes"), ("set", "host", "claude-code", "claude-code")]
        for action, field, value, _ in setup:
            self.run_cli("profile", action, field, value, "--by", "Sam", "--reason", "Setup")
        cases = (
            (("remove", "pack", "gdpr"), "protective pack gdpr removed", "gdpr"),
            (("remove", "pack", "secure-sdlc"), "protective pack secure-sdlc removed", "secure-sdlc"),
            (("remove", "pack", "llm-evaluations"), "protective pack llm-evaluations removed", "llm-evaluations"),
            (("set", "personal-data", "no"), "personal data set to no", "no"),
            (("set", "host", "other"), "host claude-code -> other, whose settings enforce less", "other"),
        )
        for arguments, weakened, target in cases:
            with self.subTest(arguments=arguments):
                before = self.profile()
                with patch("sys.stdin.isatty", return_value=False):
                    _, error = self.run_cli("profile", *arguments, "--by", "Sam", "--reason", "Lighter", code=1)
                self.assertIn(weakened, error)
                self.assertEqual(self.profile(), before)
                with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=target):
                    self.run_cli("profile", *arguments, "--by", "Sam", "--reason", "Lighter")
        self.run_cli("profile", "remove", "pack", "python", "--by", "Sam", "--reason", "Not a protection")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="security legal"):
            self.run_cli("profile", "add", "board", "security", "legal", "--by", "Sam", "--reason", "Both")
        for board in ("security", "legal"):
            with self.subTest(board=board), patch("sys.stdin.isatty", return_value=False):
                _, error = self.run_cli("profile", "remove", "board", board, "--by", "Sam", "--reason", "x", code=1)
                self.assertIn(f"board {board} no longer advises", error)

    def test_lists_change_by_command_and_refuse_what_is_unknown_or_already_there(self):
        self.run_cli("profile", "add", "check", "python -m unittest", "--by", "Sam", "--reason", "Tests exist")
        self.run_cli("profile", "add", "tool", "Jira", "--by", "Sam", "--reason", "Tracker")
        self.run_cli("profile", "add", "role", "backend", "--by", "Sam", "--reason", "API team")
        self.run_cli("profile", "add", "pack", "api-design", "--by", "Sam", "--reason", "Public API")
        # From every board to the security board alone: legal stops advising, which the person types.
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="security"):
            _, error = self.run_cli("profile", "add", "board", "security", "--by", "Sam", "--reason", "Always")
        self.assertIn("board legal no longer advises", error)
        self.run_cli("profile", "add", "convention", "Branches are named feature/X", "--by", "Sam", "--reason", "Team")
        profile = self.profile()
        self.assertEqual(profile["checks"], ["python -m unittest"])
        self.assertEqual((profile["tools"], profile["roles"], profile["boards"]), (["Jira"], ["backend"], ["security"]))
        self.assertIn("api-design", profile["packs"])
        # A check command removed is a protection less: the person types it at a terminal.
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="python -m unittest"):
            self.run_cli("profile", "remove", "check", "python -m unittest", "--by", "Sam", "--reason", "Moved to CI")
        self.assertEqual(self.profile()["checks"], [])
        self.run_cli("profile", "set", "host", "codex", "--by", "Sam", "--reason", "Team moved")
        self.assertEqual(self.profile()["host"], "codex")
        for arguments, message in ((("add", "pack", "no-such-pack"), "Unknown pack"),
                                   (("add", "tool", "Jira"), "already in"),
                                   (("remove", "pack", "agent-workflow"), "required"),
                                   (("set", "guard", "strict"), "guard must be one of")):
            with self.subTest(arguments=arguments):
                _, error = self.run_cli("profile", *arguments, "--by", "Sam", "--reason", "x", code=1)
                self.assertIn(message, error)
        self.assertEqual(len(self.profile()["changes"]), 8)

    def test_a_change_names_the_tasks_it_touches_as_update_and_sync_do(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        output, _ = self.run_cli("profile", "add", "pack", "api-design", "--by", "Sam", "--reason", "Public API")
        self.assertIn("Tasks consulted under the previous rules:", output)
        self.assertIn(f"  {TASK} (consulting): ", output)

    def test_a_stale_approval_names_the_setting_that_changed(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        # The guard and the tools change no rule, check or board of the task: the approval stands.
        self.run_cli("profile", "set", "guard", "enforce", "--by", "Sam", "--reason", "Audit")
        self.run_cli("profile", "add", "tool", "Jira", "--by", "Sam", "--reason", "Tracker")
        self.assertNotIn("earlier rules", self.run_cli("check")[1])
        self.run_cli("profile", "set", "personal-data", "yes", "--by", "Sam", "--reason", "Accounts")
        _, error = self.run_cli("check", code=1)
        self.assertIn("personal data", error)
        self.assertNotIn("guard observe -> enforce", error)
        self.assertNotIn("the boards or the project settings changed", error)

    def typed(self, *arguments, confirm: str):
        """A profile command a person types at a terminal, confirming with the word asked."""
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=confirm):
            return self.run_cli("profile", *arguments)

    def test_signed_approvals_waivers_and_required_reviews_have_their_commands(self):
        signers = ("--signers", ".openguildkit/allowed_signers", "--approver", "camille@example.test")
        self.run_cli("profile", "add", "required-board", "security", "--by", "Sam", "--reason", "Audit")
        self.run_cli("profile", "add", "required-rule", "secure-sdlc", "--by", "Sam", "--reason", "Audit")
        self.run_cli("profile", "set", "ask-every-rule", "yes", "--by", "Sam", "--reason", "Audit")
        self.typed("set", "approval", "signed", *signers, "--by", "Camille", "--reason", "Guard enforced", confirm="signed")
        self.typed("set", "waivers", "allowed", "--allowed-by", "Camille Martin", "--max-days", "30", "--by", "Camille",
                   "--reason", "Pilot", confirm="allowed")
        profile = self.profile()
        self.assertEqual((profile["required_boards"], profile["required_rules"], profile["ask_every_rule"]),
                         (["security"], ["secure-sdlc"], True))
        self.assertEqual(profile["approval"], {"mode": "signed", "allowed_signers": ".openguildkit/allowed_signers",
                                               "approvers": ["camille@example.test"]})
        self.assertEqual(profile["waivers"], {"allowed_by": ["Camille Martin"], "max_days": 30})
        self.assertEqual([entry["change"] for entry in profile["changes"]], [
            "add required-board security", "add required-rule secure-sdlc", "set ask-every-rule yes",
            "set approval signed (signers .openguildkit/allowed_signers; approvers camille@example.test)",
            "set waivers allowed (by Camille Martin; up to 30 days)"])
        self.assertIn("Approvals must be signed by camille@example.test", self.agents())
        # Tightening needs no terminal: fewer waivers, then no waiver at all.
        self.run_cli("profile", "set", "waivers", "allowed", "--allowed-by", "Camille Martin", "--max-days", "10",
                     "--by", "Sam", "--reason", "Shorter")
        self.run_cli("profile", "set", "waivers", "none", "--by", "Sam", "--reason", "No waiver")
        self.assertNotIn("waivers", self.profile())
        for arguments, message in (
                (("set", "approval", "signed", "--signers", "keys"), "needs --signers PATH and at least one --approver"),
                (("set", "waivers", "allowed", "--max-days", "5"), "needs at least one --allowed-by NAME"),
                (("set", "guard", "enforce", "--approver", "Sam"), "--approver belongs to profile set approval signed"),
                (("set", "waivers", "none"), "waivers is already none"),
                (("add", "required-rule", "no-such-pack"), "Unknown required rule")):
            with self.subTest(arguments=arguments):
                _, error = self.run_cli("profile", *arguments, "--by", "Sam", "--reason", "x", code=1)
                self.assertIn(message, error)

    def test_each_protection_of_the_profile_is_lowered_only_at_a_terminal(self):
        signers = ("--signers", ".openguildkit/allowed_signers", "--approver", "camille@example.test")
        self.run_cli("profile", "add", "check", "python -m unittest", "--by", "Sam", "--reason", "Tests")
        self.run_cli("profile", "add", "required-board", "security", "--by", "Sam", "--reason", "Audit")
        self.run_cli("profile", "add", "required-rule", "secure-sdlc", "--by", "Sam", "--reason", "Audit")
        self.run_cli("profile", "set", "ask-every-rule", "yes", "--by", "Sam", "--reason", "Audit")
        self.typed("set", "approval", "signed", *signers, "--by", "Camille", "--reason", "Audit", confirm="signed")
        self.typed("set", "waivers", "allowed", "--allowed-by", "Camille", "--max-days", "30", "--by", "Camille",
                   "--reason", "Pilot", confirm="allowed")
        cases = (
            (("set", "approval", "local"), "signed approvals turned off", "local"),
            (("set", "approval", "signed", *signers, "--approver", "agent@example.test"),
             "approver agent@example.test added", "signed"),
            (("set", "approval", "signed", "--signers", "keys/signers", "--approver", "camille@example.test"),
             "allowed signers moved from .openguildkit/allowed_signers to keys/signers", "signed"),
            (("set", "waivers", "allowed", "--allowed-by", "Camille", "--allowed-by", "agent", "--max-days", "30"),
             "waivers widened: agent may waive", "allowed"),
            (("set", "waivers", "allowed", "--allowed-by", "Camille", "--max-days", "366"),
             "waivers widened: a waiver lasts up to 366 days instead of 30", "allowed"),
            (("remove", "required-rule", "secure-sdlc"), "required rule secure-sdlc removed", "secure-sdlc"),
            (("remove", "required-board", "security"), "required board security removed", "security"),
            (("remove", "check", "python -m unittest"), "check command python -m unittest removed", "python -m unittest"),
            (("set", "ask-every-rule", "no"), "every rule no longer asked", "no"),
        )
        for arguments, weakened, target in cases:
            with self.subTest(arguments=arguments):
                before = self.profile()
                with patch("sys.stdin.isatty", return_value=False):
                    _, error = self.run_cli("profile", *arguments, "--by", "agent", "--reason", "Faster", code=1)
                self.assertIn(weakened, error)
                self.assertIn("is the person's decision", error)
                self.assertEqual(self.profile(), before)
                with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="wrong"):
                    _, error = self.run_cli("profile", *arguments, "--by", "Camille", "--reason", "Agreed", code=1)
                self.assertIn("cancelled", error)
                self.assertEqual(self.profile(), before)
        self.typed("set", "approval", "local", "--by", "Camille", "--reason", "Pilot over", confirm="local")
        self.assertNotIn("approval", self.profile())
        # Signing turned on decides who approves without a terminal: a person sets it up.
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("profile", "set", "approval", "signed", *signers, "--by", "agent", "--reason", "x",
                                    code=1)
        self.assertIn("signed approvals turned on: camille@example.test approve with a key listed in "
                      ".openguildkit/allowed_signers", error)

    def approved_task(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

    def test_the_approvals_a_change_voids_are_named_before_it_is_written(self):
        self.run_cli("profile", "add", "check", "python -m unittest", "--by", "Sam", "--reason", "Tests")
        self.approved_task()
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("profile", "remove", "check", "python -m unittest", "--by", "agent", "--reason",
                                    "Slow", code=1)
        self.assertIn(f"It also voids the approval of {TASK}. Nothing was written.", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="wrong"):
            _, prompt = self.run_cli("profile", "remove", "check", "python -m unittest", "--by", "Sam", "--reason",
                                     "Slow", code=1)
        self.assertIn(f"It also voids the approval of {TASK}. Type python -m unittest to confirm", prompt)
        output, _ = self.run_cli("profile", "add", "check", "python -m compileall -q .", "--by", "Sam", "--reason",
                                 "Syntax")
        announced = output.index(f"This change voids the approval of {TASK}")
        self.assertLess(announced, output.index("Profile changed: add check"))

    def test_a_new_tool_or_convention_announces_no_voided_approval(self):
        self.approved_task()
        for words in (("add", "tool", "jira"), ("add", "convention", "Write commit messages in English.")):
            output, error = self.run_cli("profile", *words, "--by", "Sam", "--reason", "Team practice")
            self.assertNotIn("voids the approval", output + error)
        self.run_cli("task", "verify", TASK)

    def test_no_page_of_the_docs_asks_to_edit_the_profile_by_hand(self):
        """A change a profile command makes is documented with that command, not as an edit of project.json."""
        repo = Path(__file__).resolve().parents[1]
        pages = sorted([*(repo / "docs").glob("*.md"), *(repo / "web" / "docs").glob("*.md"), repo / "README.md",
                        repo / "README.fr.md", repo / "CONTRIBUTING.md"])
        edit = re.compile(r"\b(edit|add|adds|remove|set)\b[^.]*`?\.openguildkit/project\.json", re.I)
        # A setting written as JSON for the reader to put in the profile: "with `"required_boards": [...]` in its
        # profile", "set `"ask_every_rule": true`". A sentence that only says what the profile holds is fine.
        snippet = r'`"(?:approval|waivers|required_boards|required_rules|ask_every_rule|checks|packs|tools|sector)"[^`]*`'
        key = re.compile(rf"\b(?:with|set) {snippet}|{snippet}\s+in (?:its|the) profile"
                         rf"|{snippet}\s+in `?\.openguildkit/project\.json")
        # No command reads a profile that names a sector the catalog lacks: that one is fixed by hand.
        by_hand_only = "no command can read a profile whose sector is unknown"
        found = []
        for page in pages:
            for sentence in re.split(r"(?<=[.!?])\s+|\n", page.read_text(encoding="utf-8")):
                asks = edit.search(sentence) or key.search(sentence)
                if asks and "openguildkit profile" not in sentence and by_hand_only not in sentence:
                    found.append(f"{page.relative_to(repo).as_posix()}: {sentence.strip()[:120]}")
        self.assertEqual(found, [])

    def test_a_new_condition_names_the_norm_it_brings(self):
        output, _ = self.run_cli("profile", "set", "personal-data", "yes", "--by", "Sam", "--reason", "Accounts")
        self.assertIn("Norm gdpr-personal-data now concerns the project", output)
        self.assertNotIn("gdpr-personal-data", self.profile().get("patterns", []))
        self.assertIn("No open task was consulted under the previous profile.", output)


if __name__ == "__main__":
    unittest.main()
