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
# The same reference as the bundled catalog records it: each source carries the day a person read it.
CHECKED = {"quality": {**FAMILIES["quality"], "references": [
    {**FAMILIES["quality"]["references"][0], "sources": [{"title": "Spec", "url": PAGE, "checked": "2026-11-20"},
                                                         {"title": "Mirror", "url": MIRROR, "checked": "2026-11-18"}]},
    FAMILIES["quality"]["references"][1],
]}}


# References whose every source is a page whose address holds the edition: the publisher keeps that page online after
# a new edition, so the watch keeps finding the old one there. Each one lacks a page of the publisher that follows the
# editions and that the watch can read (#348); the list may only shrink.
VERSIONED_ONLY = {
    "keep-a-changelog": "keepachangelog.com sends readers to the versioned page through an HTML redirect the watch "
                        "does not follow.",
    "owasp-agentic-top-10": "No OWASP page other than the 2026 resource names the edition.",
    "prince2": "PeopleCert refused both a browser and the watch (HTTP 403) on 2026-11-25.",
    "saml-2": "The OASIS page of the standard writes v2.0, which the watch does not read as the edition 2.0.",
}
PINNED = "https://standards.example.test/2026b/spec"
CURRENT = "https://standards.example.test/current/spec"
FOLLOWED = {"data": {"id": "data", "title": "Data", "references": [
    {"id": "spec-y", "edition": "2026b", "sources": [{"title": "Pinned", "url": PINNED, "checked": "2026-11-20"},
                                                      {"title": "Current", "url": CURRENT, "checked": "2026-11-20"}]},
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
                                  "seen_on": "2026-11-21", "seen_in": "page", "checked": "2026-11-21", "status": "found"})
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

    def test_an_edition_the_watch_never_saw_starts_from_the_day_the_catalog_checked_it(self):
        state = watch_editions.watch(CHECKED, {}, pages(page="SP 800-53 Rev. 6 is out", mirror="Rev. 6"), "2026-12-01")
        record = state["references"]["spec-x"]
        self.assertEqual({key: record[key] for key in ("status", "seen", "seen_on", "seen_in", "checked")},
                         {"status": "may-have-changed", "seen": "Rev. 5", "seen_on": "2026-11-20", "seen_in": "catalog",
                          "checked": "2026-12-01"})
        found = watch_editions.changes(state)["may_have_changed"]
        self.assertEqual([item["title"] for item in found], ["Edition may have changed: spec-x"])
        self.assertIn("The catalog records it as read on 2026-11-20; the watch has not found it on the page since",
                      " ".join(found[0]["body"].split()))
        shown = watch_editions.watch(CHECKED, {}, pages(page="Rev. 5"), "2026-12-01")["references"]["spec-x"]
        self.assertEqual((shown["status"], shown["seen_on"], shown["seen_in"]), ("found", "2026-12-01", "page"))

    def test_seeding_records_the_catalog_observation_without_opening_a_page(self):
        seeded = watch_editions.seed(CHECKED, {})
        self.assertEqual(seeded["references"]["spec-x"], {
            "family": "quality", "edition": "Rev. 5", "page": PAGE, "seen": "Rev. 5", "seen_on": "2026-11-20",
            "seen_in": "catalog", "checked": None, "status": "from-catalog"})
        observed = watch_editions.watch(CHECKED, seeded, pages(page="Rev. 5"), "2026-12-01")
        self.assertEqual(watch_editions.seed(CHECKED, observed), observed)
        newer = {"quality": {**CHECKED["quality"], "references": [
            {**CHECKED["quality"]["references"][0], "edition": "Rev. 6",
             "sources": [{"title": "Spec", "url": PAGE, "checked": "2026-12-05"}]}]}}
        record = watch_editions.seed(newer, observed)["references"]["spec-x"]
        self.assertEqual((record["edition"], record["seen"], record["seen_on"], record["status"]),
                         ("Rev. 6", "Rev. 6", "2026-12-05", "from-catalog"))

    def test_the_watch_file_covers_every_reference_with_an_edition(self):
        state = watch_editions.read_state(watch_editions.STATE)
        expected = {entry["reference"]: entry for entry in watch_editions.watched(load_references())}
        self.assertEqual(set(state["references"]), set(expected), "run python3 -I scripts/watch_editions.py --seed")
        for reference, record in state["references"].items():
            self.assertEqual(record["edition"], expected[reference]["edition"], reference)
            self.assertIn(record["page"], expected[reference]["pages"], reference)

    def test_a_page_that_names_the_edition_comes_with_one_that_does_not(self):
        """A versioned page stays online and keeps showing its edition: the watch needs a source that follows the
        editions, such as DICOM's current folder (#348)."""
        names_edition = watch_editions.names_edition
        self.assertTrue(names_edition("https://dicom.nema.org/medical/dicom/2026b/output/html/part01.html", "2026b"))
        self.assertFalse(names_edition("https://dicom.nema.org/medical/dicom/current/output/html/part01.html", "2026b"))
        self.assertTrue(names_edition("https://publications.europa.eu/resource/celex/02016R0679-20160504",
                                      "02016R0679-20160504"))
        versioned_only = sorted(entry["reference"] for entry in watch_editions.watched(load_references())
                                if all(names_edition(url, entry["edition"]) for url in entry["pages"]))
        self.assertEqual(versioned_only, sorted(VERSIONED_ONLY))

    def test_once_seen_on_a_page_that_follows_the_editions_the_pinned_page_is_no_longer_read(self):
        """The pinned page keeps showing 2026b after 2026e is out: the current page, where the watch saw 2026b, alone
        decides (#348)."""
        seen = watch_editions.watch(FOLLOWED, {}, lambda url: {"status": 200, "text": "DICOM 2026b"}, "2026-11-30")
        self.assertEqual(seen["references"]["spec-y"]["page"], CURRENT)
        for status, text, expected in ((200, "DICOM 2026e", "may-have-changed"), (403, None, "unreachable")):
            opened = []

            def fetcher(url, status=status, text=text):
                opened.append(url)
                return {"status": status, "text": text} if url == CURRENT else {"status": 200, "text": "DICOM 2026b"}

            with self.subTest(status=status):
                record = watch_editions.watch(FOLLOWED, seen, fetcher, "2026-12-07")["references"]["spec-y"]
                self.assertEqual((record["status"], record["page"], record["seen"]), (expected, CURRENT, "2026b"))
                self.assertEqual(opened, [CURRENT])

    def test_a_page_that_never_showed_the_edition_leaves_the_pinned_page_in_the_watch(self):
        """A regulation cites a policy page and EUR-Lex, which show no consolidation to the watch: its Publications
        Office page, whose address holds the consolidation, keeps it watched (#348)."""
        opened = []

        def fetcher(url):
            opened.append(url)
            return {"status": 200, "text": "Policy summary" if url == CURRENT else "02016R0679-20160504 2026b"}

        record = watch_editions.watch(FOLLOWED, {}, fetcher, "2026-12-01")["references"]["spec-y"]
        self.assertEqual((record["status"], record["page"]), ("found", PINNED))
        self.assertEqual(opened, [CURRENT, PINNED])

    def test_dicom_follows_the_current_edition(self):
        state = watch_editions.read_state(watch_editions.STATE)
        record = state["references"]["dicom"]
        self.assertEqual((record["edition"], record["seen"]), ("2026e", "2026e"))
        self.assertEqual(record["page"], "https://dicom.nema.org/medical/dicom/current/output/html/part01.html")
        self.assertGreaterEqual(record["seen_on"], "2026-11-25")

    def test_no_reference_of_the_watch_file_waits_for_a_first_observation(self):
        state = watch_editions.read_state(watch_editions.STATE)
        waiting = sorted(reference for reference, record in state["references"].items()
                         if record["status"] == "not-checked" or record["seen"] != record["edition"]
                         or not record["seen_on"])
        self.assertEqual(waiting, [], "run python3 -I scripts/watch_editions.py --seed and commit the file")

    def test_the_committed_watch_file_reports_a_new_edition_on_the_next_run(self):
        state = watch_editions.read_state(watch_editions.STATE)
        other_edition = {"status": 200, "text": "Edition 9999.99 is out"}
        later = watch_editions.watch(load_references(), state, lambda url: other_edition, "2026-12-07")
        found = watch_editions.changes(later)["may_have_changed"]
        self.assertTrue(found)
        self.assertEqual(len(found), len(state["references"]))

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
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(watch_editions.main(["--state", str(state_path), "--seed"]), 0)
            self.assertIn("seeded", out.getvalue())
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")),
                             watch_editions.seed(load_references(), state))
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
