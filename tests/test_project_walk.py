"""One walk of the project tree: code lookup, proposed checks, detection and Storybook extraction skip the same folders.

A bug consult looks up the code its brief names. It used to list every file of node_modules before dropping them,
and it read vendor/ and .next/, which detection skips.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.detect import SKIPPED_DIRECTORIES, detect_stack, walk
from openguildkit.project_checks import propose_checks
from openguildkit.storybook import extract
from openguildkit.workflow import code_not_found

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
COMPONENT = "export function {name}() {{ return <button className=\"x\">Go</button>; }}\n"


class WalkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def folder_with_code(self, relative: str, name: str) -> None:
        """A front-end package: a function, a React component and a test script."""
        folder = self.root / relative
        folder.mkdir(parents=True)
        (folder / "lib.js").write_text(f"export function {name}Helper() {{ return 1; }}\n", encoding="utf-8")
        (folder / f"{name}Card.tsx").write_text(COMPONENT.format(name=f"{name}Card"), encoding="utf-8")
        (folder / "package.json").write_text(json.dumps({"name": name.lower(), "scripts": {"test": "vitest run"},
                                                         "dependencies": {"react": "18.3.1"}}), encoding="utf-8")

    def test_code_lookup_checks_and_extraction_skip_the_same_folders(self):
        self.folder_with_code("src", "Kept")
        skipped = sorted(SKIPPED_DIRECTORIES)
        for index, name in enumerate(skipped):
            self.folder_with_code(name, f"Skipped{index}")
        brief = " ".join(f"`Skipped{index}Helper()`" for index in range(len(skipped)))
        self.assertEqual(code_not_found(f"Fix `KeptHelper()`. {brief}", self.root),
                         [f"Skipped{index}Helper()" for index in range(len(skipped))])
        proposed = [item["command"] for item in propose_checks(self.root, detect_stack(self.root))]
        self.assertEqual(proposed, ["cd src && npm test"])
        self.assertEqual([component["name"] for component in extract(self.root, [self.root])["components"]],
                         ["KeptCard"])
        self.assertEqual([component["path"] for component in detect_stack(self.root)["components"]], ["src"])

    def test_a_name_found_only_under_vendor_or_next_is_reported_missing(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.ts").write_text("export function renderStatus() { return 1; }\n", encoding="utf-8")
        for folder in ("vendor/acme", ".next/server"):
            (self.root / folder).mkdir(parents=True)
            (self.root / folder / "bundle.js").write_text("function missingHelper() {}\n", encoding="utf-8")
        brief = "The page crashes: `renderStatus()` is wrong in src/app.ts, `missingHelper()` and bundle.js are absent."
        self.assertEqual(code_not_found(brief, self.root), ["bundle.js", "missingHelper()"])

    def test_the_code_lookup_never_lists_a_dependency_folder(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.ts").write_text("export function renderStatus() { return 1; }\n", encoding="utf-8")
        for package in range(20):
            folder = self.root / "node_modules" / f"pkg-{package}" / "lib"
            folder.mkdir(parents=True)
            (folder / "index.js").write_text("function missingHelper() {}\n", encoding="utf-8")
        listed = []
        scandir = os.scandir

        def recording(path="."):
            listed.append(Path(path))
            return scandir(path)

        with patch("os.scandir", recording):
            self.assertEqual(code_not_found("`renderStatus()` calls `missingHelper()`.", self.root), ["missingHelper()"])
        self.assertTrue(listed)
        self.assertEqual([path for path in listed if "node_modules" in path.parts], [])

    def test_init_lists_each_folder_of_the_project_once(self):
        for index in range(6):
            folder = self.root / ("apps" if index % 2 else "packages") / f"pkg-{index}"
            (folder / "src").mkdir(parents=True)
            (folder / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "lint": "eslint ."},
                                                             "dependencies": {"react": "18.3.1"}}), encoding="utf-8")
            (folder / "node_modules" / "dep").mkdir(parents=True)
        profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
        (self.root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        walks, listed = [], []
        scandir = os.scandir

        def counting(root, max_depth=None):
            walks.append(Path(root).resolve())
            return walk(root, max_depth)

        def recording(path="."):
            listed.append(Path(path).resolve())
            return scandir(path)

        with patch("openguildkit.detect.walk", counting), patch("openguildkit.project_checks.walk", counting), \
                patch("os.scandir", recording), contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            code = main(["--project", str(self.root), "init", "--answers", str(self.root / "profile.json")])
        self.assertEqual(code, 0)
        self.assertIn("cd apps/pkg-1 && npm run lint", out.getvalue())
        self.assertEqual(walks, [self.root])
        # Below the first level of the packages only the walk lists folders; tool and host detection read the root,
        # its first level and .github on their own.
        below = [path.relative_to(self.root).parts for path in listed if self.root in path.parents]
        deep = [self.root.joinpath(*parts) for parts in below if parts[0] in ("apps", "packages") and len(parts) > 1]
        self.assertIn(self.root / "packages" / "pkg-0" / "src", deep)
        self.assertEqual(sorted({path for path in deep if deep.count(path) > 1}), [])

    def test_the_walk_goes_depth_first_in_name_order_and_a_caller_can_prune_it(self):
        for relative in ("b/deep/er", "a/x", "a.txt", "node_modules/pkg", "c"):
            path = self.root / relative
            if path.suffix:
                path.write_text("", encoding="utf-8")
            else:
                path.mkdir(parents=True)
        seen = []
        for folder, parts, files, folders in walk(self.root, max_depth=2):
            self.assertEqual(folder, self.root.joinpath(*parts))
            seen.append(("/".join(parts) or ".", len(parts), files, list(folders)))
            if folder.name == "a":
                folders.clear()
        self.assertEqual(seen, [(".", 0, ["a.txt"], ["a", "b", "c"]), ("a", 1, [], ["x"]), ("b", 1, [], ["deep"]),
                                ("b/deep", 2, [], ["er"]), ("c", 1, [], [])])


if __name__ == "__main__":
    unittest.main()
