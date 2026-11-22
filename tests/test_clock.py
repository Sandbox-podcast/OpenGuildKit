import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.cli import main
from openguildkit.storage import write_json

SOURCE = Path(__file__).resolve().parents[1] / "src" / "openguildkit"
# Reading the wall clock to stamp a record; time.monotonic, which measures a duration, is allowed.
_WALL_CLOCK = re.compile(r"\b(?:datetime\.(?:now|utcnow|today)|date\.today|time\.time)\s*\(|from time import time\b")
EPOCH = "1763640000"  # 2025-11-20T12:00:00Z


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

    def test_the_cli_stamps_tasks_and_shares_with_source_date_epoch(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"SOURCE_DATE_EPOCH": EPOCH}):
            root = Path(folder)
            write_json(root / "p.json", {"name": "Portal", "stack": ["Python"]})

            def cli(*arguments, code=0):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main(["--project", str(root), *map(str, arguments)]), code, stderr.getvalue())
                return stdout.getvalue()

            cli("init", "--answers", root / "p.json")
            cli("task", "new", "Show request status.", "--id", "status")
            self.assertEqual(json.loads(cli("task", "show", "status"))["created_at"], "2025-11-20T12:00:00+00:00")
            (root / "d").write_text("# Shared page\n", encoding="utf-8")
            common = ["docs", "share", "add", "--deliverable", "d", "--recipient", "reader@example.test",
                      "--portal", "https://docs.example.test/p/portal", "--by", "Camille"]
            cli(*common, "--until", "2025-11-20", code=1)
            cli(*common, "--until", "2025-12-01")
            share = json.loads(cli("docs", "share", "list", "--json"))[0]
            self.assertEqual(share["created_at"], "2025-11-20T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
