"""Exercise the hook inputs that contributors can copy from the integration guide."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.catalog import load_catalog
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.storage import write_json
from openguildkit.workflow import consult

ROOT = Path(__file__).resolve().parents[1]


class HookExampleTests(unittest.TestCase):
    def test_consultation_names_the_research_decision_for_each_scope(self):
        example = ROOT / "examples" / "request-status"
        catalog = load_catalog()
        profile = json.loads((example / "profile.json").read_text(encoding="utf-8"))
        answers = json.loads((example / "answers.json").read_text(encoding="utf-8"))
        task = {"id": "example", "brief": "Show request status."}
        for policy, choice, expected in (("local-only", "local", "a task authorize public-research decision"),
                                         ("public-sources", "public", "needs no separate task authorize decision")):
            with self.subTest(policy=policy):
                configured = validate_profile({**profile, "research": policy}, catalog)
                result = consult(resolved_profile(configured, catalog), catalog,
                                 {**task, "answers": {**answers, "research": choice}})
                self.assertIn(expected, result["markdown"])

    def test_documented_inputs_run_through_the_guard(self):
        readme = (ROOT / "integrations" / "README.md").read_text(encoding="utf-8")
        examples = re.findall(r"printf '%s\\n' '([^']+)' \| openguildkit guard --hook (prompt|pre-edit)", readme)
        self.assertEqual(len(examples), 4)
        self.assertEqual([kind for _, kind in examples], ["prompt", "pre-edit", "prompt", "pre-edit"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "profile.json", {"name": "Example", "stack": ["Python"], "guard": "enforce"})

            def run(arguments, stdin=""):
                output, error = io.StringIO(), io.StringIO()
                with patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    code = main(["--project", str(root), *arguments])
                return code, output.getvalue(), error.getvalue()

            self.assertEqual(run(["init", "--answers", str(root / "profile.json")])[0], 0)
            for raw, kind in examples:
                with self.subTest(kind=kind, input=raw):
                    json.loads(raw)
                    code, output, error = run(["guard", "--hook", kind], raw)
                    if kind == "prompt":
                        self.assertEqual(code, 0)
                        self.assertIn("no approved task", json.loads(output)["hookSpecificOutput"]["additionalContext"])
                    else:
                        self.assertEqual(code, 2)
                        self.assertIn("Edit refused", error)
