import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.cli import main
from openguildkit.guard import _age_days
from openguildkit.storage import write_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src' / 'openguildkit'
_WALL_CLOCK = re.compile(r'\b(?:datetime\.(?:now|utcnow|today)|date\.today|time\.time)\s*\(|from time import time\b')
EPOCH = '1763640000'  # 2025-11-20T12:00:00Z


class ClockTests(unittest.TestCase):
    def test_records_are_stamped_only_through_the_clock_helper(self):
        offenders = []
        for path in sorted(SOURCE.rglob('*.py')):
            if path.name == 'clock.py':
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
                if _WALL_CLOCK.search(line):
                    offenders.append(f'{path.relative_to(SOURCE).as_posix()}:{number}: {line.strip()}')
        self.assertEqual(offenders, [], 'Use openguildkit.clock for wall-clock reads.')

    def test_tests_use_the_product_clock(self):
        offenders = []
        for path in (ROOT / 'tests').rglob('*.py'):
            if path.name == 'test_clock.py':
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
                if _WALL_CLOCK.search(line):
                    offenders.append(f'{path.relative_to(ROOT)}:{number}')
        self.assertEqual(offenders, [], 'Use openguildkit.clock in tests.')

    def test_source_date_epoch_is_only_the_export_date(self):
        before = datetime.now(timezone.utc)
        with patch('os.environ', {**os.environ, 'SOURCE_DATE_EPOCH': EPOCH}):
            self.assertEqual(clock.source_date_epoch(), datetime(2025, 11, 20, 12, tzinfo=timezone.utc))
            self.assertGreaterEqual(clock.now(), before)
            self.assertLessEqual(clock.now(), datetime.now(timezone.utc))
            self.assertGreaterEqual(_age_days((before - timedelta(days=30)).isoformat()), 30)

    def test_a_malformed_source_date_epoch_is_a_clear_error(self):
        for value in ('yesterday', '-5', '1.5', '²', '99999999999999999999'):
            with self.subTest(value=value), patch('os.environ', {**os.environ, 'SOURCE_DATE_EPOCH': value}):
                with self.assertRaisesRegex(ValueError, 'SOURCE_DATE_EPOCH'):
                    clock.source_date_epoch()

    def test_share_dates_follow_the_real_clock_when_epoch_is_set(self):
        with tempfile.TemporaryDirectory() as folder, patch('os.environ', {**os.environ, 'SOURCE_DATE_EPOCH': EPOCH}):
            root = Path(folder)
            write_json(root / 'p.json', {'name': 'Portal', 'stack': ['Python']})

            def cli(*arguments, code=0):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main(['--project', str(root), *map(str, arguments)]), code, stderr.getvalue())
                return stdout.getvalue()

            cli('init', '--answers', root / 'p.json')
            (root / 'docs-site').mkdir()
            (root / 'docs-site' / '.openguildkit-export.json').write_text('{"version":"0","tasks":[],"files":[]}', encoding='utf-8')
            common = ['docs', 'share', 'add', '--deliverable', 'docs-site/d.md', '--recipient',
                      'reader@example.test', '--portal', 'https://docs.example.test/p/portal', '--by', 'CM']
            yesterday = (clock.today() - timedelta(days=1)).isoformat()
            tomorrow = (clock.today() + timedelta(days=1)).isoformat()
            cli(*common, '--until', yesterday, code=1)
            before = clock.now().replace(microsecond=0)
            cli(*common, '--until', tomorrow)
            after = clock.now()
            share = json.loads(cli('docs', 'share', 'list', '--json'))[0]
            self.assertEqual(share['state'], 'active')
            self.assertGreaterEqual(datetime.fromisoformat(share['created_at']), before)
            self.assertLessEqual(datetime.fromisoformat(share['created_at']), after)
            shares_path = root / '.openguildkit' / 'shares' / 'shares.json'
            shares = json.loads(shares_path.read_text(encoding='utf-8'))
            shares['shares'][0]['until'] = yesterday
            write_json(shares_path, shares)
            cli('docs', 'share', 'check', code=1)


if __name__ == '__main__':
    unittest.main()
