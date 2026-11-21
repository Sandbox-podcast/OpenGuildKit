"""The edition watch finds each reference's edition on its page, without network access, and its workflow files issues."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openguildkit.references import load_references

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "watch-editions.yml"
spec = importlib.util.spec_from_file_location("watch_editions", ROOT / "scripts" / "watch_editions.py")
watch_editions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch_editions)

PAGE = "https://standards.example.test/spec"
MIRROR = "https://mirror.example.test/spec"
FAMILIES = {"quality": {"id": "quality", "title": "Quality", "references": [
    {"id": "spec-x", "edition": "Rev. 5", "sources": [{"title": "Spec", "url": PAGE}, {"title": "Mirror", "url": MIRROR}]},
    {"id": "no-edition", "sources": [{"title": "Other", "url": "https://other.example.test/"}]},
]}}


def pages(**texts):
    """A fetcher that serves the given page texts; None stands for a page that did not answer."""
    by_url = {"page": PAGE, "mirror": MIRROR}

    def fetcher(url):
        for name, address in by_url.items():
            if address == url:
                text = texts.get(name)
                return {"status": 200, "text": text} if text is not None else {"status": 403, "text": None}
        raise AssertionError(url)
    return fetcher


class EditionWatchTests(unittest.TestCase):
    def test_an_edition_seen_then_missing_may_have_changed(self):
        state = watch_editions.watch(FAMILIES, {}, pages(page="<p>NIST SP 800-53 <b>Rev.&nbsp;5</b></p>"), "2026-11-21")
        record = state["references"]["spec-x"]
        self.assertEqual(list(state["references"]), ["spec-x"])
        self.assertEqual(record, {"family": "quality", "edition": "Rev. 5", "page": PAGE, "seen": "Rev. 5",
                                  "seen_on": "2026-11-21", "checked": "2026-11-21", "status": "found"})
        later = watch_editions.watch(FAMILIES, state, pages(page="SP 800-53 Rev. 6 is out", mirror="Rev. 6"), "2026-12-01")
        record = later["references"]["spec-x"]
        self.assertEqual((record["status"], record["seen"], record["seen_on"], record["checked"]),
                         ("may-have-changed", "Rev. 5", "2026-11-21", "2026-12-01"))
        found = watch_editions.changes(later)["may_have_changed"]
        self.assertEqual([item["title"] for item in found], ["Edition may have changed: spec-x"])
        self.assertIn(f"The page {PAGE} no longer shows the edition \"Rev. 5\"", found[0]["body"])
        self.assertIn("can raise a false alarm", found[0]["body"])

    def test_pages_that_never_showed_or_did_not_answer_raise_no_alarm(self):
        never = watch_editions.watch(FAMILIES, {}, pages(page="Rev. 50", mirror="Revision 5"), "2026-11-21")
        self.assertEqual(never["references"]["spec-x"]["status"], "not-found")
        self.assertEqual(watch_editions.changes(never), {"may_have_changed": []})
        seen = watch_editions.watch(FAMILIES, {}, pages(mirror="rev. 5"), "2026-11-21")
        self.assertEqual((seen["references"]["spec-x"]["status"], seen["references"]["spec-x"]["page"]), ("found", MIRROR))
        down = watch_editions.watch(FAMILIES, seen, pages(), "2026-11-28")
        record = down["references"]["spec-x"]
        self.assertEqual((record["status"], record["seen"], record["page"], record["checked"]),
                         ("unreachable", "Rev. 5", MIRROR, "2026-11-28"))
        self.assertEqual(watch_editions.changes(down), {"may_have_changed": []})

    def test_the_edition_matches_whole_words_only(self):
        self.assertTrue(watch_editions.shows_edition("ISO 19005-1:2005 (PDF/A-1)", "ISO 19005-1:2005 (PDF/A-1)"))
        self.assertTrue(watch_editions.shows_edition("Version\n 4.4.1 released", "4.4.1"))
        self.assertFalse(watch_editions.shows_edition("version 14.4.10", "4.4.1"))
        self.assertEqual(watch_editions.page_text("<style>p{}</style><p>a&amp;b</p>\n<script>x=1</script> c"), "a&b c")

    def test_the_watch_file_covers_every_reference_with_an_edition(self):
        state = watch_editions.read_state(watch_editions.STATE)
        expected = {entry["reference"]: entry for entry in watch_editions.watched(load_references())}
        self.assertEqual(set(state["references"]), set(expected))
        for reference, record in state["references"].items():
            self.assertEqual(record["edition"], expected[reference]["edition"], reference)
            self.assertIn(record["page"], expected[reference]["pages"], reference)

    def test_main_updates_the_state_and_writes_the_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path, changes_path = Path(folder) / "state.json", Path(folder) / "changes.json"
            original = watch_editions.fetch
            watch_editions.fetch = lambda url, timeout: {"status": 404, "text": None}
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(watch_editions.main(["--state", str(state_path), "--changes", str(changes_path)]), 0)
            finally:
                watch_editions.fetch = original
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(all(record["status"] == "unreachable" for record in state["references"].values()))
            self.assertEqual(json.loads(changes_path.read_text(encoding="utf-8")), {"may_have_changed": []})
            self.assertIn("unreachable", out.getvalue())
            state_path.write_text('{"schema_version": 2}', encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(watch_editions.main(["--state", str(state_path)]), 1)
            self.assertIn("schema version 1", err.getvalue())


class EditionWorkflowTests(unittest.TestCase):
    def test_the_workflow_is_pinned_like_the_link_check_with_the_narrowest_permissions(self):
        from tests.test_market import pinned_actions
        from tests.test_workflows import parse

        text = WORKFLOW.read_text(encoding="utf-8")
        link_pins = set(pinned_actions((ROOT / ".github" / "workflows" / "check-links.yml").read_text(encoding="utf-8")))
        self.assertTrue(pinned_actions(text))
        self.assertLessEqual(set(pinned_actions(text)), link_pins)
        workflow = parse(WORKFLOW)
        self.assertEqual(workflow["permissions"], {})
        self.assertEqual(workflow["jobs"]["editions"]["permissions"], {"contents": "read", "issues": "write"})
        self.assertIn("schedule", workflow["on"])

    def test_the_issue_step_opens_one_issue_per_change_and_never_a_duplicate(self):
        from tests.test_market import run_block

        bash, jq = shutil.which("bash"), shutil.which("jq")
        if os.name == "nt" or not bash or not jq:
            self.skipTest("Running the workflow steps needs bash and jq, as on the GitHub runner.")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = watch_editions.watch(FAMILIES, {}, pages(page="Rev. 5"), "2026-11-21")
            state = watch_editions.watch(FAMILIES, state, pages(page="Rev. 6"), "2026-11-28")
            (root / "editions.json").write_text(json.dumps(watch_editions.changes(state)), encoding="utf-8")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "gh").write_text("#!/bin/sh\nif [ \"$2\" = list ]; then cat \"$KNOWN\"; exit 0; fi\n"
                                        "printf '%s\\n' \"$@\" >> \"$GH_LOG\"\n", encoding="utf-8")
            (bin_dir / "gh").chmod(0o755)
            (root / "known.txt").write_text("", encoding="utf-8")
            environment = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                           "GH_LOG": str(root / "gh.log"), "KNOWN": str(root / "known.txt")}
            script = run_block(WORKFLOW.read_text(encoding="utf-8"), "Open an issue per edition that may have changed")

            def step():
                return subprocess.run([bash, "-e", "-c", script], cwd=root, env=environment, check=True,
                                      capture_output=True, text=True)

            step()
            calls = (root / "gh.log").read_text(encoding="utf-8")
            self.assertEqual(calls.count("issue\ncreate\n"), 1)
            self.assertIn("--title\nEdition may have changed: spec-x\n--body\nThe page", calls)
            (root / "gh.log").unlink()
            (root / "known.txt").write_text("Edition may have changed: spec-x\n", encoding="utf-8")
            self.assertIn("Already reported: Edition may have changed: spec-x", step().stdout)
            self.assertFalse((root / "gh.log").exists())


if __name__ == "__main__":
    unittest.main()
