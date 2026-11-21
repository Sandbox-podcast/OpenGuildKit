"""The sources must stay parseable by Python 3.11, the oldest supported version.

Python 3.12 accepts f-strings that 3.11 refuses: a backslash, a comment or the enclosing
quote inside a replacement field. A contributor on a recent Python would not see the error.
"""

import sys
import tokenize
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


if __name__ == "__main__":
    unittest.main()
