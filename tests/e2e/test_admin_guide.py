"""Issue #477: docs/admin-guide.md replayed from step 2 to step 8 on two toy Git repositories.

Each command of the guide's code blocks is run as the guide writes it, with its placeholders filled in; the commands an
incident row names are run on the second repository, where `guard --ci` must first accept and then refuse the change.
Step 1 (installing a release with its hash) is not replayed: it downloads a wheel. The test puts an `openguildkit`
launcher on the PATH instead, as pipx would.
"""

import contextlib
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openguildkit.storage import write_json
from tests.support import openguildkit_on_path, run_cli

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "docs" / "admin-guide.md"
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"
# What a person types in place of each placeholder of the guide.
FILLED = {"INITIALS": "CM", "WHY": "Rollout", "ID": TASK}
# The commands of the incident table this test runs, as the guide writes them.
INCIDENT = ("openguildkit task revoke ID --by INITIALS --reason WHY", "openguildkit task export ID")


def guide_commands() -> list[str]:
    """The commands of the code blocks of the guide, in their order."""
    blocks = re.findall(r"```bash\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.DOTALL)
    return [line.strip() for block in blocks for line in block.splitlines() if line.startswith("openguildkit ")]


def filled(command: str, code: Path) -> list[str]:
    words = shlex.split(command.replace("~/code", str(code)))[1:]
    return [FILLED.get(word, word) for word in words]


@unittest.skipIf(shutil.which("git") is None or shutil.which("ssh-keygen") is None, "needs git and ssh-keygen")
class AdminGuideReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ogk-admin-")
        self.addCleanup(temporary.cleanup)
        self.code = Path(temporary.name).resolve() / "code"
        self.first, self.second = self.code / "portal", self.code / "billing"
        for root in (self.first, self.second):
            root.mkdir(parents=True)
            self.git(root, "init", "-q", "-b", "main")
        openguildkit_on_path(self)

    def git(self, root: Path, *arguments: str) -> None:
        subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.org", *arguments],
                       check=True, capture_output=True)

    def typed_by_person(self, root: Path, command: str, expect=0, typed=None):
        """The command run from the repository's folder, as the person types it there."""
        with contextlib.chdir(root):
            return run_cli(root, *filled(command, self.code), expect=expect, typed=typed)

    def test_the_test_replays_every_command_of_the_guide(self):
        self.assertEqual(guide_commands(), [
            "openguildkit init", "openguildkit host apply", "openguildkit check",
            "openguildkit profile export > answers.json", "openguildkit init --answers answers.json",
            ("openguildkit profile set approval signed --signers .openguildkit/allowed_signers --approver CM "
            "--by INITIALS --reason WHY"),
            "openguildkit host apply", "openguildkit projects ~/code",
            "openguildkit update", "openguildkit update --apply", "openguildkit check",
        ])
        page = GUIDE.read_text(encoding="utf-8")
        for command in (*INCIDENT, "openguildkit guard --ci", "openguildkit check"):
            self.assertIn(f"`{command}`", page)

    def test_the_guide_from_the_first_repository_to_the_incident(self):
        commands = iter(guide_commands())
        # 2. Set up the first repository: init asks its questions at a terminal; a person gives the same answers here.
        answers = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
        write_json(self.code / "setup.json", {**answers, "host": "claude-code", "guard": "observe"})
        self.assertEqual(next(commands), "openguildkit init")
        run_cli(self.first, "init", "--answers", self.code / "setup.json")
        self.assertIn("Wrote .claude/settings.json", self.typed_by_person(self.first, next(commands)).stdout)
        self.typed_by_person(self.first, next(commands))
        # 3. Give the same profile to N repositories.
        exported = self.typed_by_person(self.first, next(commands).removesuffix(" > answers.json")).stdout
        (self.second / "answers.json").write_text(exported, encoding="utf-8")
        self.typed_by_person(self.second, next(commands))
        self.typed_by_person(self.second, "openguildkit host apply")
        self.typed_by_person(self.second, "openguildkit check")
        for name in ("host", "guard", "packs", "patterns", "conventions"):
            self.assertEqual(json.loads((self.second / ".openguildkit" / "project.json").read_text())[name],
                             json.loads((self.first / ".openguildkit" / "project.json").read_text())[name], name)
        # 5. Make approvals verifiable: the key of the approver CM in the signers file, then the setting, typed.
        keys = self.code / "keys"
        keys.mkdir()
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "cm")], check=True)
        signers = self.first / ".openguildkit" / "allowed_signers"
        signers.write_text(f"CM {(keys / 'cm.pub').read_text().strip()}\n", encoding="utf-8")
        signed = next(commands)
        refused = self.typed_by_person(self.first, signed, expect=1)
        self.assertIn("terminal", refused.stderr)
        self.typed_by_person(self.first, signed, typed="signed")
        profile = json.loads((self.first / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["approval"], {"mode": "signed", "allowed_signers": ".openguildkit/allowed_signers",
                                               "approvers": ["CM"]})
        # The host settings then deny the agent an edit of the signers file: check fails until host apply writes it.
        self.assertIn("allowed_signers", self.typed_by_person(self.first, "openguildkit check", expect=1).stderr
                      + self.typed_by_person(self.first, "openguildkit host check", expect=1).stdout)
        self.assertIn("Wrote .claude/settings.json", self.typed_by_person(self.first, next(commands)).stdout)
        self.typed_by_person(self.first, "openguildkit check")
        # 6. See all the repositories.
        listing = self.typed_by_person(self.code, next(commands)).stdout
        self.assertIn("portal: guard observe; approvals signed", listing)
        self.assertIn("billing: guard observe; approvals not signed", listing)
        # 7. Upgrade, with the release already installed: nothing to adopt, and check still passes.
        for root in (self.first, self.second):
            self.assertIn("The project's rules match the installed catalog.", self.typed_by_person(root, "openguildkit update").stdout)
        self.typed_by_person(self.first, next(commands))
        self.typed_by_person(self.first, next(commands))
        self.typed_by_person(self.first, next(commands))
        self.assertIsNone(next(commands, None))
        # 4 and 8, on the second repository: guard --ci accepts an approved change, then refuses it once revoked.
        self.typed_by_person(self.second, "openguildkit profile set guard enforce --by CM --reason Rollout")
        self.git(self.second, "add", "-A")
        self.git(self.second, "commit", "-q", "-m", "OpenGuildKit")
        self.git(self.second, "checkout", "-q", "-b", "feature")
        self.approve(self.second)
        (self.second / "status.py").write_text("STATUS = 1\n", encoding="utf-8")
        self.git(self.second, "add", "-A")
        self.git(self.second, "commit", "-q", "-m", "work")
        self.typed_by_person(self.second, "openguildkit task export ID")
        self.git(self.second, "add", "-A")
        self.git(self.second, "commit", "-q", "-m", "record")
        accepted = json.loads(run_cli(self.second, "guard", "--ci", "--base", "main", "--json").stdout)
        self.assertTrue(accepted["ok"], accepted)
        revoke, export = INCIDENT
        self.typed_by_person(self.second, revoke, typed=TASK)
        self.typed_by_person(self.second, export)
        self.git(self.second, "add", "-A")
        self.git(self.second, "commit", "-q", "-m", "revoked")
        refused = json.loads(run_cli(self.second, "guard", "--ci", "--base", "main", "--json", expect=1).stdout)
        self.assertFalse(refused["ok"])
        self.assertIn("the approval of request-status was withdrawn by CM", " ".join(refused["problems"]))

    def approve(self, root: Path) -> None:
        """A task consulted and approved by CM at a terminal, as docs/workflow.md has it."""
        run_cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        run_cli(root, "task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(run_cli(root, "task", "template", TASK).stdout)
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(root / ".openguildkit" / "work" / "review.json", review)
        run_cli(root, "task", "review", TASK, "--file", root / ".openguildkit" / "work" / "review.json")
        run_cli(root, "task", "decide", TASK, "--approve", "--by", "CM", "--reason", "Agreed", typed=TASK)


if __name__ == "__main__":
    unittest.main()
