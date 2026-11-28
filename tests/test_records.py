"""The types of the records (records.py): a task, a profile and the catalog, as the functions that read them return."""

import ast
import importlib.util
import os
import subprocess
import tempfile
import typing
import unittest
from pathlib import Path

from openguildkit import lock, project, records, task_files, tasks
from openguildkit.tasks_command import TaskCommand

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "openguildkit"
spec = importlib.util.spec_from_file_location("lint_ratchet", REPO / "scripts" / "lint_ratchet.py")
lint_ratchet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint_ratchet)


class RecordTypeTests(unittest.TestCase):
    def test_issue_507_the_readers_return_the_record_types(self):
        """Issue #507: read_task, load_profile and project_catalog returned a bare dict, whose keys no tool checks."""
        self.assertIs(typing.get_type_hints(task_files.read_task)["return"], records.Task)
        self.assertIs(typing.get_type_hints(project.load_profile)["return"], records.Profile)
        self.assertEqual(typing.get_type_hints(lock.project_catalog)["return"], records.Catalog)
        self.assertIs(typing.get_type_hints(tasks.write_task)["task"], records.Task)
        hints = typing.get_type_hints(TaskCommand)
        self.assertEqual((hints["task"], hints["profile"]), (records.Task, records.Profile))

    def test_issue_507_no_task_profile_or_catalog_parameter_is_a_bare_dict(self):
        """Issue #507: 573 parameters named task, profile or catalog were annotated `dict`."""
        found = []
        for path in sorted(PACKAGE.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.arg) and node.arg in ("task", "profile", "catalog") and node.annotation \
                        and ast.unparse(node.annotation) in ("dict", "dict | None"):
                    found.append(f"{path.name}:{node.lineno} {node.arg}")
        self.assertEqual(found, [])

    def test_issue_507_the_type_checker_names_an_unknown_key_of_a_task(self):
        """Issue #507: a typo in task["consultation"] was seen by no tool."""
        try:
            mypy = lint_ratchet.launcher("mypy", lint_ratchet.read_config()["mypy"])
        except lint_ratchet.ToolError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            probe = Path(folder, "probe.py")
            probe.write_text("from openguildkit.records import Task\n\n\ndef scope(task: Task) -> object:\n"
                             "    return task[\"consultaton\"]\n", encoding="utf-8")
            run = subprocess.run([*mypy, "--cache-dir", os.devnull, str(probe)], capture_output=True, text=True,
                                 check=False, env={**os.environ, "MYPYPATH": str(PACKAGE.parent)})
        self.assertIn('TypedDict "Task" has no key "consultaton"', run.stdout)


if __name__ == "__main__":
    unittest.main()
