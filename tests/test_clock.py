import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.cli import main
from openguildkit.guard import _age_days
from openguildkit.storage import write_json

TESTS = Path(__file__).resolve().parent
SOURCE = TESTS.parent / "src" / "openguildkit"
# Reading the wall clock to stamp a record; time.monotonic, which measures a duration, is allowed.
_WALL_CLOCK = re.compile(r"\b(?:datetime\.(?:now|utcnow|today)|date\.today|time\.time)\s*\(|from time import time\b")
EPOCH = "1763640000"  # 2025-11-20T12:00:00Z
# One fixed day after the real one and one before, so a decision read from the fixed clock fails either way.
LATER, EARLIER = "2000000000", "1000000000"  # 2033-05-18 and 2001-09-09


class ClockTests(unittest.TestCase):
    def test_records_are_stamped_only_through_the_clock_helper(self):
        offenders = []
        for path in sorted(SOURCE.rglob("*.py")):
            if path.name == "clock.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if _WALL_CLOCK.search(line):
                    offenders.append(f"{path.relative_to(SOURCE).as_posix()}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "Use openguildkit.clock.now() or today() so SOURCE_DATE_EPOCH applies.")

    def test_tests_read_the_date_through_the_clock_helper(self):
        """A test that reads the wall clock disagrees with the product as soon as SOURCE_DATE_EPOCH is set."""
        offenders = []
        for path in sorted(TESTS.rglob("*.py")):
            if path.name == "test_clock.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if _WALL_CLOCK.search(line):
                    offenders.append(f"{path.relative_to(TESTS).as_posix()}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "Use openguildkit.clock (real_today() for a decision), or set SOURCE_DATE_EPOCH "
                                        "with patch.dict.")

    def test_source_date_epoch_replaces_now_and_today(self):
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": EPOCH}):
            self.assertEqual(clock.now(), datetime(2025, 11, 20, 12, tzinfo=timezone.utc))
            self.assertEqual(clock.today(), date(2025, 11, 20))
            self.assertEqual(clock.timestamp(), "2025-11-20T12:00:00+00:00")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOURCE_DATE_EPOCH", None)
            self.assertEqual(clock.today(), date.today())

    def test_a_malformed_source_date_epoch_is_a_clear_error(self):
        for value in ("yesterday", "-5", "1.5", "²", "99999999999999999999"):
            with self.subTest(value=value), patch.dict(os.environ, {"SOURCE_DATE_EPOCH": value}):
                with self.assertRaisesRegex(ValueError, "SOURCE_DATE_EPOCH"):
                    clock.now()

    def cli(self, root, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["--project", str(root), *map(str, arguments)]), code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def project(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        write_json(root / "p.json", {"name": "Portal", "stack": ["Python"]})
        self.cli(root, "init", "--answers", root / "p.json")
        (root / "d").write_text("# Shared page\n", encoding="utf-8")
        return root

    def share(self, root, until, code=0):
        return self.cli(root, "docs", "share", "add", "--deliverable", "d", "--recipient", "reader@example.test",
                        "--portal", "https://docs.example.test/p/portal", "--by", "Camille", "--until", until, code=code)

    def test_the_cli_stamps_tasks_with_source_date_epoch_and_says_so(self):
        root = self.project()
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": EPOCH}), patch.object(clock, "_announced", set()):
            _, notice = self.cli(root, "task", "new", "Show request status.", "--id", "status")
            self.assertEqual(json.loads(self.cli(root, "task", "show", "status")[0])["created_at"], "2025-11-20T12:00:00+00:00")
        self.assertIn("SOURCE_DATE_EPOCH is set: this command dates what it writes 2025-11-20T12:00:00+00:00, not now", notice)
        with patch.dict(os.environ, {}), patch.object(clock, "_announced", set()):
            os.environ.pop("SOURCE_DATE_EPOCH", None)
            self.assertNotIn("SOURCE_DATE_EPOCH", self.cli(root, "task", "new", "Show request history.", "--id", "history")[1])

    def test_shares_follow_the_real_clock_under_source_date_epoch(self):
        root = self.project()
        until = (clock.real_today() + timedelta(days=10)).isoformat()
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": LATER}):
            self.share(root, until)
            self.share(root, clock.real_today().isoformat(), code=1)
            share = json.loads(self.cli(root, "docs", "share", "list", "--json")[0])[0]
        self.assertEqual(share["created_at"][:10], clock.real_now().date().isoformat())
        register = root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(register.read_text(encoding="utf-8"))
        data["shares"][0]["until"] = (clock.real_today() - timedelta(days=1)).isoformat()
        register.write_text(json.dumps(data), encoding="utf-8")
        for fixed in (LATER, EARLIER):
            with self.subTest(fixed=fixed), patch.dict(os.environ, {"SOURCE_DATE_EPOCH": fixed}):
                output, _ = self.cli(root, "docs", "share", "check", code=1)
                self.assertIn("expired", output)

    def test_an_approval_age_follows_the_real_clock_under_source_date_epoch(self):
        moment = clock.real_timestamp()
        for fixed in (LATER, EARLIER):
            with self.subTest(fixed=fixed), patch.dict(os.environ, {"SOURCE_DATE_EPOCH": fixed}):
                self.assertEqual(_age_days(moment), 0)
        self.assertEqual(_age_days((clock.real_now() - timedelta(days=40)).isoformat()), 40)


if __name__ == "__main__":
    unittest.main()
