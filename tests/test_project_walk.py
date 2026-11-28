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
from openguildkit.consultation import code_not_found
from openguildkit.detect import SKIPPED_DIRECTORIES, detect_stack, walk
from openguildkit.project_checks import propose_checks
from openguildkit.storybook_extract import extract

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


class LargeRepositoryLookupTests(unittest.TestCase):
    """A bug brief's code is looked for in the file the brief names first, then in every source file of a Git
    repository; a walk stopped at its limit says so instead of calling the rest absent."""

    BRIEF = ("The status page crashes: `render17()` returns the wrong label in services/svc-9/file_9.ts and "
             "`missingHelper()` is never called.")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for index in range(10):  # More source files than the limit the tests set, the named one walked last.
            folder = self.root / "services" / f"svc-{index}"
            folder.mkdir(parents=True)
            (folder / f"file_{index}.ts").write_text(f"export function render{index}() {{ return {index}; }}\n",
                                                    encoding="utf-8")
        (self.root / "services" / "svc-9" / "file_9.ts").write_text("export function render17() { return 1; }\n",
                                                                   encoding="utf-8")

    def lookup(self, brief=BRIEF):
        from openguildkit import code_lookup

        with patch.object(code_lookup, "MAX_SCANNED_FILES", 4):
            return code_lookup.code_lookup(brief, self.root)

    def git(self, *arguments):
        import shutil
        import subprocess

        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True)

    def test_a_function_of_the_file_the_brief_names_is_found_past_the_limit(self):
        """Issue #536: past 5,000 source files, a function defined in the very file the brief names was called absent."""
        missing, not_searched = self.lookup()
        self.assertNotIn("render17()", missing + not_searched)
        self.assertEqual((missing, not_searched), ([], ["missingHelper()"]))

    def test_a_walk_stopped_at_its_limit_is_said_incomplete_not_absent(self):
        """Issue #536: a name the walk did not reach was listed as not found in the project."""
        from openguildkit.catalog import load_catalog
        from openguildkit.consultation import consult
        from openguildkit.project import validate_profile
        from openguildkit.project_rules import resolved_profile

        missing, not_searched = self.lookup("`render8()` and src/absent.ts are named.")
        self.assertEqual(missing, [])
        self.assertEqual(not_searched, ["src/absent.ts", "render8()"])
        catalog = load_catalog()
        profile = resolved_profile(validate_profile(json.loads((EXAMPLE / "profile.json").read_text()), catalog),
                                   catalog)
        task = {"id": "t", "brief": "`render8()` crashes.", "answers": {
            **json.loads((EXAMPLE / "answers.json").read_text()), "kind": "bug"}}
        consultation = consult(profile, catalog, task, code_not_searched=not_searched)
        self.assertIn("stopped at 5,000 source files before finding: src/absent.ts, render8()",
                      consultation["markdown"])
        self.assertNotIn("not found", consultation["markdown"])

    def test_in_a_git_repository_every_source_file_is_searched(self):
        """Issue #536: a Git repository is searched whole, and a name really absent is still listed."""
        self.git("init", "-q")
        self.git("add", "services/svc-0")  # One file tracked, the others untracked: both are searched.
        (self.root / "node_modules" / "dep").mkdir(parents=True)
        (self.root / "node_modules" / "dep" / "index.js").write_text("function missingHelper() {}\n", encoding="utf-8")
        self.assertEqual(self.lookup("`render8()`, `render0()` and `missingHelper()` in src/absent.ts and file_7.ts."),
                         (["src/absent.ts", "missingHelper()"], []))
