"""One walk of the project tree: code lookup, proposed checks, detection and Storybook extraction skip the same folders.

A bug consult looks up the code its brief names. It used to list every file of node_modules before dropping them,
and it read vendor/ and .next/, which detection skips.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.detect import SKIPPED_DIRECTORIES, detect_stack, walk
from openguildkit.project_checks import propose_checks
from openguildkit.storybook import extract
from openguildkit.workflow import code_not_found

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

    def test_the_walk_goes_depth_first_in_name_order_and_a_caller_can_prune_it(self):
        for relative in ("b/deep/er", "a/x", "a.txt", "node_modules/pkg", "c"):
            path = self.root / relative
            if path.suffix:
                path.write_text("", encoding="utf-8")
            else:
                path.mkdir(parents=True)
        seen = []
        for folder, depth, files, folders in walk(self.root, max_depth=2):
            seen.append((folder.relative_to(self.root).as_posix(), depth, files, list(folders)))
            if folder.name == "a":
                folders.clear()
        self.assertEqual(seen, [(".", 0, ["a.txt"], ["a", "b", "c"]), ("a", 1, [], ["x"]), ("b", 1, [], ["deep"]),
                                ("b/deep", 2, [], ["er"]), ("c", 1, [], [])])


if __name__ == "__main__":
    unittest.main()
