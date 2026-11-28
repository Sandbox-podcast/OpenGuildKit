"""How often a command loads and copies the catalog and reads the lock, and when a changed file is read again."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openguildkit import catalog, lock
from openguildkit.cli import main
from openguildkit.storage import write_json
from tests.support import load_script, run_cli

bench = load_script(Path(__file__).resolve().parents[1] / "scripts" / "bench.py")


class CatalogLoadTests(unittest.TestCase):
    """Each command reads and validates the bundled catalog once, however many times it loads the catalog."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        profile = {**json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": "enforce"}
        write_json(self.root / "profile.json", profile)

    def bundled_reads(self, *arguments, stdin="", code=0):
        """How many times one command read the bundled catalog, starting as a fresh process does."""
        catalog._BUNDLED.clear()
        with patch("openguildkit.catalog._read_bundled", wraps=catalog._read_bundled) as reader:
            run_cli(self.root, *arguments, expect=code, stdin=stdin)
        return reader.call_count

    def test_each_command_validates_the_bundled_catalog_once(self):
        hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "app.py")}})
        commands = [
            ("init", "--answers", self.root / "profile.json"), ("catalog", "--json"), ("sync",), ("check",),
            ("update",), ("task", "new", "A brief.", "--id", "one"), ("task", "list"), ("guard", "--json"),
        ]
        for command in commands:
            with self.subTest(command=command[0]):
                self.assertEqual(self.bundled_reads(*command), 1)
        self.assertEqual(self.bundled_reads("guard", "--hook", "pre-edit", stdin=hook, code=2), 1)

    def test_the_edit_hook_reads_no_catalog_when_the_guard_is_off(self):
        profile = {**json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": "off"}
        write_json(self.root / "profile.json", profile)
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "app.py")}})
        for event in ("pre-edit", "prompt"):
            with self.subTest(event=event):
                self.assertEqual(self.bundled_reads("guard", "--hook", event, stdin=hook), 0)

    def test_task_consult_validates_the_project_catalog_and_the_lock_once(self):
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        pack = {"id": "house-rules", "title": "House rules", "version": "1.0.0", "description": "Team rules.",
                "sources": [], "rules": [{"id": "small-changes", "instruction": "Keep changes small.",
                                          "verification": "Check the size of the diff."}]}
        write_json(self.root / ".openguildkit" / "catalog" / "packs" / "house-rules.json", pack)
        self.bundled_reads("task", "new", (bench.EXAMPLE / "brief.md").read_text(encoding="utf-8"), "--id", "status")
        catalog._MERGED.clear()
        lock._READ.clear()  # As a new process starts.
        with patch("openguildkit.catalog._merged_records", wraps=catalog._merged_records) as merged, \
                patch("openguildkit.lock._validated_lock", wraps=lock._validated_lock) as locks:
            self.bundled_reads("task", "consult", "status", "--answers", bench.EXAMPLE / "answers.json")
        project = [call for call in merged.call_args_list if call.args[1] is not None]
        self.assertEqual((len(project), locks.call_count), (1, 1))

    def test_task_list_loads_the_catalog_once_and_reads_the_lock_once(self):
        """Issue #533: task list loaded the catalog twice and read the lock twice, a deep copy each time."""
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        self.bundled_reads("task", "new", "A brief.", "--id", "one")
        counters = {}
        with contextlib.ExitStack() as stack:
            for module, name in ((catalog, "load_catalog"), (lock, "read_lock")):
                function = getattr(module, name)
                counters[name] = MagicMock(wraps=function)
                holders = [item for key, item in list(sys.modules.items())
                           if key.startswith("openguildkit") and getattr(item, name, None) is function]
                for holder in holders:
                    stack.enter_context(patch.object(holder, name, counters[name]))
            self.bundled_reads("task", "list")
        self.assertEqual({name: counter.call_count for name, counter in counters.items()},
                         {"load_catalog": 1, "read_lock": 1})

    def test_task_list_copies_the_catalog_at_most_25_times(self):
        """Issue #533: task list deep-copied each locked record once more, 46 copies for a lock of 41 records."""
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        original, depth, copies = catalog.json_copy, [0], [0]

        def counted(value):
            copies[0] += depth[0] == 0  # json_copy calls itself for each nested value: count the outer call only
            depth[0] += 1
            try:
                return original(value)
            finally:
                depth[0] -= 1

        with patch.object(catalog, "json_copy", counted), patch.object(lock, "json_copy", counted):
            self.bundled_reads("task", "list")
        self.assertLessEqual(copies[0], 25)

    def rewrite_in_place(self, path: Path, old: bytes, new: bytes) -> None:
        """Rewrite a file in place with the same size and give it back its modification time, as an editor that
        saves in place within one tick of a coarse file system (HFS+, FAT, SMB) leaves it (issue 285)."""
        info = path.stat()
        content = path.read_bytes()
        self.assertEqual(len(old), len(new))
        self.assertIn(old, content)
        with open(path, "r+b") as handle:
            handle.write(content.replace(old, new))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual((path.stat().st_size, path.stat().st_mtime_ns), (info.st_size, info.st_mtime_ns))

    def test_a_same_size_rewrite_that_keeps_the_modification_time_is_read_again(self):
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        state = self.root / ".openguildkit"
        pack = {"id": "house-rules", "title": "House rules", "version": "1.0.0", "description": "Team rules.",
                "sources": [], "rules": [{"id": "small-changes", "instruction": "Rule EEEE 0049.",
                                          "verification": "Check the size of the diff."}]}
        path = state / "catalog" / "packs" / "house-rules.json"
        write_json(path, pack)
        rule = lambda: catalog.load_catalog(state / "catalog")["packs"]["house-rules"]["rules"][0]["instruction"]
        self.assertEqual(rule(), "Rule EEEE 0049.")
        self.rewrite_in_place(path, b"EEEE", b"FFFF")
        self.assertEqual(rule(), "Rule FFFF 0049.")
        # The CLI, which keeps its caches between commands in one process (openguildkit ui), reads it too.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(["--project", str(self.root), "catalog", "--json"])
        self.assertIn("Rule FFFF 0049", output.getvalue())

        described = lambda: lock.read_lock(state)["records"]["packs"]["python"]["description"]
        self.assertTrue(described().startswith("Repository conventions for Python code"))
        self.rewrite_in_place(state / lock.LOCK_FILE, b"conventions for Python code", b"conventions for PYTHON code")
        self.assertTrue(described().startswith("Repository conventions for PYTHON code"))

    def test_the_task_index_the_catalog_and_the_lock_compare_one_file_signature(self):
        from openguildkit import storage, task_index
        for module in (catalog, lock, task_index):
            with self.subTest(module=module.__name__):
                self.assertIs(module.file_signature, storage.file_signature)

    def test_a_load_hands_out_its_own_copy(self):
        first = catalog.load_catalog()
        first["packs"].clear()
        next(iter(first["boards"].values()))["title"] = "Changed"
        second = catalog.load_catalog()
        self.assertTrue(second["packs"])
        self.assertNotIn("Changed", [board["title"] for board in second["boards"].values()])


if __name__ == "__main__":
    unittest.main()
