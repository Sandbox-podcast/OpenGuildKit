"""A project written by the code before delivered-diff reviews, task dependencies and evidence fingerprints (#431,
#432, #433) reads the same with this code.

tests/fixtures/upgrade/before-delivered-review.json holds the files the code of commit afb2d7f wrote (a task closed
after two blockers were cleared with evidence, its exported record, an approved task with the same clearances, a
draft) and what each command printed then.
"""

import json
import re
import shlex
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
NO_FINGERPRINT = "no fingerprint: cleared before OpenGuildKit recorded one"
BEFORE = json.loads((REPO / "tests" / "fixtures" / "upgrade" / "before-delivered-review.json").read_text(encoding="utf-8"))


class BeforeDeliveredReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, content in BEFORE["files"].items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        clock = patch("openguildkit.clock.real_now", return_value=datetime.fromisoformat(BEFORE["now"]))
        clock.start()
        self.addCleanup(clock.stop)

    def run_old(self, command: str):
        result = run_cli(self.root, *shlex.split(command), expect=None)
        return (result.returncode, result.stdout.replace(str(self.root), "$PROJECT"),
                result.stderr.replace(str(self.root), "$PROJECT"))

    def test_every_command_prints_what_it_printed_before(self):
        for name, expected in BEFORE["expected"].items():
            with self.subTest(command=name):
                stdout = expected["stdout"]
                if name.startswith("task blockers") and "--json" not in name:
                    # The one addition (#433): a clearance says the state of its evidence, here that it has none.
                    stdout = re.sub(r"(?m)^(    evidence: .*)$", r"\1; " + NO_FINGERPRINT, stdout)
                self.assertEqual(self.run_old(name), (expected["code"], stdout, expected["stderr"]))

    def test_an_old_clearance_reads_without_error_and_says_it_has_no_fingerprint(self):
        _, output, _ = self.run_old("task blockers cleared-task")
        self.assertEqual(output.count(NO_FINGERPRINT), 2)
        _, output, _ = self.run_old("task list --json")
        self.assertNotIn("evidence_changed", output)

    def test_an_exported_record_of_the_old_code_is_written_again_byte_for_byte(self):
        target = self.root / "again.json"
        run_cli(self.root, "task", "export", "cleared-task", "--output", target)
        self.assertEqual(target.read_text(encoding="utf-8"),
                         BEFORE["files"][".openguildkit/decisions/cleared-task.json"])

    def test_the_old_records_hold_none_of_the_new_fields(self):
        for name, content in BEFORE["files"].items():
            if name.startswith(".openguildkit/tasks/") or name.startswith(".openguildkit/decisions/"):
                with self.subTest(name=name):
                    for field in ('"delivered_review"', '"after"', '"fingerprint"'):
                        self.assertNotIn(field, content)


if __name__ == "__main__":
    unittest.main()
