"""The sources must stay parseable by Python 3.11, the oldest supported version.

Python 3.12 accepts f-strings that 3.11 refuses: a backslash, a comment or the enclosing
quote inside a replacement field. A contributor on a recent Python would not see the error.
"""

import os
import re
import subprocess
import sys
import tokenize
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("src", "tests", "scripts", "examples", ".github")


def newer_fstring_syntax(path: Path) -> list[str]:
    problems, stack = [], []
    with tokenize.open(path) as source:
        for token in tokenize.generate_tokens(source.readline):
            if token.type == tokenize.FSTRING_START:
                quote = token.string.lstrip("rRfFbBuU")
                if stack and quote[0] == stack[-1][0]:
                    problems.append(f"{path}:{token.start[0]} reuses the enclosing quote in a nested f-string")
                stack.append(quote)
            elif token.type == tokenize.FSTRING_END:
                stack.pop()
            elif stack and token.type != tokenize.FSTRING_MIDDLE:
                where = f"{path}:{token.start[0]}"
                if token.type == tokenize.COMMENT:
                    problems.append(f"{where} has a comment inside an f-string field")
                elif "\\" in token.string:
                    problems.append(f"{where} has a backslash inside an f-string field")
                elif token.type == tokenize.STRING and token.string.lstrip("rRbBuU")[0] == stack[-1][0]:
                    problems.append(f"{where} reuses the enclosing quote inside an f-string field")
                elif token.type == tokenize.NL and len(stack[-1]) == 1:
                    problems.append(f"{where} breaks a single-quoted f-string field across lines")
    return problems


@unittest.skipUnless(sys.version_info >= (3, 12), "Python 3.11 refuses this syntax by itself")
class PythonFloorTests(unittest.TestCase):
    def test_f_strings_parse_on_python_3_11(self):
        problems = []
        for folder in FOLDERS:
            for path in sorted((ROOT / folder).rglob("*.py")):
                problems.extend(newer_fstring_syntax(path))
        self.assertEqual(problems, [])

    def test_the_check_sees_the_syntax_python_3_11_refuses(self):
        import tempfile

        cases = {
            'x = f"{chr(92) + \'\\n\'}"\n': "backslash",
            'x = f"{d["key"]}"\n': "enclosing quote",
            'x = f"""{1 + 1}"""\n': None,
            "x = f\"{d['key']!r:>10}\"\n": None,
        }
        with tempfile.TemporaryDirectory() as folder:
            for index, (source, expected) in enumerate(cases.items()):
                path = Path(folder) / f"case{index}.py"
                path.write_text(source, encoding="utf-8")
                found = newer_fstring_syntax(path)
                if expected:
                    self.assertTrue(found and expected in found[0], (source, found))
                else:
                    self.assertEqual(found, [], source)


class FloorMessageTests(unittest.TestCase):
    """A Python older than the floor is told so in one line, not with a TypeError from an annotation."""

    FLOOR = tuple(int(part) for part in
                  tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
                  .removeprefix(">=").split("."))

    def run_cli(self, python: str, *code: str) -> subprocess.CompletedProcess:
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([python, *code], capture_output=True, text=True, env=environment, timeout=60, check=False)

    def assert_one_line_naming_the_floor(self, result: subprocess.CompletedProcess, found: str):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
        self.assertIn("Python " + ".".join(map(str, self.FLOOR)), result.stderr)
        self.assertIn(found, result.stderr)

    def test_a_python_below_the_floor_gets_one_line_that_names_the_floor(self):
        """Issue #520: with the python3 of macOS (3.9) the CLI ends on a TypeError at the first annotation."""
        code = ("import runpy, sys; sys.version_info = (3, 9, 6, 'final', 0); "
                "runpy.run_module('openguildkit', run_name='__main__')")
        self.assert_one_line_naming_the_floor(self.run_cli(sys.executable, "-c", code), "Python 3.9")

    def test_the_python_of_this_machine_when_it_is_below_the_floor(self):
        """Issue #520: `python3 -m openguildkit --version` with the system Python of macOS prints a trace."""
        for candidate in ("/usr/bin/python3", "/usr/bin/python"):
            probe = subprocess.run([candidate, "-c", "import sys; print(*sys.version_info[:2])"],
                                   capture_output=True, text=True, check=False) if Path(candidate).exists() else None
            if probe and probe.returncode == 0 and tuple(map(int, probe.stdout.split())) < self.FLOOR:
                version = ".".join(probe.stdout.split())
                with self.subTest(python=candidate):
                    self.assert_one_line_naming_the_floor(
                        self.run_cli(candidate, "-m", "openguildkit", "--version"), "Python " + version)
                return
        self.skipTest("no Python below the floor on this machine")

    def test_the_floor_in_the_check_is_the_one_of_requires_python(self):
        text = (ROOT / "src" / "openguildkit" / "__main__.py").read_text(encoding="utf-8")
        checked = re.search(r"if sys\.version_info < \((\d+), (\d+)\):", text)
        self.assertIsNotNone(checked, "__main__.py checks sys.version_info before its first annotation")
        self.assertEqual(tuple(map(int, checked.groups())), self.FLOOR)
        self.assertLess(checked.start(), text.index("def "), "the check comes before any annotation is evaluated")

    def test_the_python_with_the_check_still_starts_the_cli(self):
        result = self.run_cli(sys.executable, "-m", "openguildkit", "--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
