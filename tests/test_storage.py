"""Writing a project file while another process reads it."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import storage


class BusyTargetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name) / "record.json"
        self.target.write_text("old", encoding="utf-8")
        self.calls = 0

    def refuse(self, times):
        """An os.replace that answers "access denied" a number of times, as Windows does while a reader holds the file."""
        real = os.replace

        def replace(source, target):
            self.calls += 1
            if self.calls <= times:
                raise PermissionError(5, "Access is denied")
            real(source, target)
        return replace

    def test_a_write_waits_for_a_reader_to_let_go_of_the_file(self):
        with patch.object(storage, "RETRIES_BUSY_TARGET", True), patch.object(storage.os, "replace", self.refuse(2)), \
                patch.object(storage.time, "sleep", lambda seconds: None):
            storage.write_text(self.target, "new")
        self.assertEqual((self.target.read_text(encoding="utf-8"), self.calls), ("new", 3))
        self.assertEqual([path.name for path in self.target.parent.iterdir()], ["record.json"])

    def test_a_file_that_stays_busy_is_reported_and_left_as_it_was(self):
        with patch.object(storage, "RETRIES_BUSY_TARGET", True), patch.object(storage.os, "replace", self.refuse(10_000)), \
                patch.object(storage.time, "sleep", lambda seconds: None), self.assertRaises(PermissionError):
            storage.write_text(self.target, "new")
        self.assertEqual(self.calls, storage.REPLACE_ATTEMPTS)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "old")
        self.assertEqual([path.name for path in self.target.parent.iterdir()], ["record.json"])

    def test_a_read_waits_while_the_file_is_being_replaced(self):
        real, calls = Path.read_bytes, []

        def read(path):
            calls.append(path)
            if len(calls) <= 2:
                raise PermissionError(13, "Permission denied")
            return real(path)

        with patch.object(storage, "RETRIES_BUSY_TARGET", True), patch.object(Path, "read_bytes", read), \
                patch.object(storage.time, "sleep", lambda seconds: None):
            self.assertEqual(storage.read_bytes(self.target), b"old")
        self.assertEqual(len(calls), 3)
        self.target.write_text('{"status": "draft"}', encoding="utf-8")
        calls.clear()
        with patch.object(storage, "RETRIES_BUSY_TARGET", True), patch.object(Path, "read_bytes", read), \
                patch.object(storage.time, "sleep", lambda seconds: None):
            self.assertEqual(storage.read_json(self.target), {"status": "draft"})

    def test_a_read_refused_for_good_is_reported(self):
        def read(path):
            raise PermissionError(13, "Permission denied")

        with patch.object(storage, "RETRIES_BUSY_TARGET", True), patch.object(Path, "read_bytes", read), \
                patch.object(storage.time, "sleep", lambda seconds: None), self.assertRaises(PermissionError):
            storage.read_bytes(self.target)
        with patch.object(storage, "RETRIES_BUSY_TARGET", False), patch.object(Path, "read_bytes", read), \
                self.assertRaises(PermissionError):
            storage.read_bytes(self.target)

    def test_where_readers_never_block_a_refusal_is_not_retried(self):
        with patch.object(storage, "RETRIES_BUSY_TARGET", False), patch.object(storage.os, "replace", self.refuse(1)), \
                self.assertRaises(PermissionError):
            storage.write_text(self.target, "new")
        self.assertEqual(self.calls, 1)


if __name__ == "__main__":
    unittest.main()
