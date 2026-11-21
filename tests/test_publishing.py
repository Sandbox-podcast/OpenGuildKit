import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import publishing
from openguildkit.cli import main
from openguildkit.storage import write_json

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
DOCUMENTALIST = REPO / "examples" / "documentalist"
TASK = "request-status"
BUSY = "is writing this project"


class PublishingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"name": "Support portal", "stack": ["Python"], "packs": [], "checks": [command]})
        self.run_cli("init", "--answers", self.root / "profile.json")

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def done_task(self, task_id=TASK, brief_file=EXAMPLE / "brief.md"):
        self.run_cli("task", "new", "--file", brief_file, "--id", task_id)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each request's status and next step."}
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", task_id, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=task_id):
            self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Agreed")
        self.run_cli("task", "verify", task_id)
        checks = json.loads(self.run_cli("task", "checks", task_id, "--json")[0])
        rules = [{"check": c["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"} for c in checks if c["kind"] == "rule"]
        write_json(self.root / "result.json", {"pull_request": "https://github.com/example/portal/pull/7", "checks": rules,
                                               "criteria": [{"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/test_access.py"}]})
        self.run_cli("task", "result", task_id, "--file", self.root / "result.json")
        self.run_cli("task", "complete", task_id)

    def test_completed_tasks_become_reference_learn_and_dated_blog_pages(self):
        self.done_task()
        self.run_cli("task", "new", "Not finished yet.", "--id", "draft")
        self.run_cli("docs", "export", "--tasks", "draft", "--output", "docs-site", "--version", "1.4.0", code=1)
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0")
        site = self.root / "docs-site"
        reference = (site / "reference" / f"{TASK}.md").read_text(encoding="utf-8")
        self.assertIn('project_version: "1.4.0"', reference)
        self.assertIn("Users only see their own requests.", reference)
        self.assertNotIn("tests/test_access.py", reference)
        self.assertNotIn("recommendation", reference)
        blog = next((site / "blog").glob(f"*-{TASK}.md"))
        self.assertRegex(blog.read_text(encoding="utf-8"), r'date: "\d{4}-\d{2}-\d{2}"')
        self.assertIn(f"(reference/{TASK}.md)", (site / "SUMMARY.md").read_text(encoding="utf-8"))

        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.5.0", "--sections", "reference,blog")
        self.assertIn('project_version: "1.5.0"', (site / "reference" / f"{TASK}.md").read_text(encoding="utf-8"))
        self.assertFalse((site / "learn" / f"{TASK}.md").exists())
        self.assertEqual(len(list((site / "reference").glob("*.md"))), 1)

    def test_export_refuses_a_folder_it_did_not_create(self):
        self.done_task()
        (self.root / "notes").mkdir()
        (self.root / "notes" / "team.md").write_text("# Team\n", encoding="utf-8")
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "notes", "--version", "1.0.0", code=1)

    def test_shares_record_recipients_end_date_and_revocation(self):
        until = (date.today() + timedelta(days=14)).isoformat()
        common = ["docs", "share", "add", "--deliverable", "docs-site/reference/request-status.md", "--portal", "https://docs.example.org/p/portal"]
        self.run_cli(*common, "--recipient", "not-an-email", "--until", until, "--by", "Camille", code=1)
        output, _ = self.run_cli(*common, "--recipient", "client@example.org", "--until", until, "--by", "Camille")
        self.assertIn("remove their access on", output)
        shares = json.loads(self.run_cli("docs", "share", "list", "--json")[0])
        self.assertEqual(shares[0]["state"], "active")
        self.run_cli("docs", "share", "check")
        state = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(state.read_text())
        data["shares"][0]["until"] = (date.today() - timedelta(days=1)).isoformat()
        state.write_text(json.dumps(data), encoding="utf-8")
        self.run_cli("docs", "share", "check", code=1)
        self.run_cli("docs", "share", "revoke", "--id", data["shares"][0]["id"], "--by", "Camille")
        self.run_cli("docs", "share", "check")
        self.assertIn("shares/", (self.root / ".openguildkit" / ".gitignore").read_text())

    def exported_site(self):
        self.done_task()
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0")
        return self.root / "docs-site"

    def add_to_manifest(self, site, entry):
        manifest = json.loads((site / ".openguildkit-export.json").read_text(encoding="utf-8"))
        manifest["files"].append(entry)
        write_json(site / ".openguildkit-export.json", manifest)

    def test_export_keeps_a_file_the_manifest_places_above_the_output_folder(self):
        site = self.exported_site()
        victim = self.root / "victim.txt"
        victim.write_text("VICTIM\n", encoding="utf-8")
        self.add_to_manifest(site, "../victim.txt")
        output, _ = self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.1")
        self.assertTrue(victim.is_file())
        self.assertIn("kept ../victim.txt", output)
        self.assertNotIn("removed ../victim.txt", output)
        self.assertNotIn("../victim.txt", (site / ".openguildkit-export.json").read_text(encoding="utf-8"))

    def test_export_keeps_a_file_the_manifest_names_by_absolute_path(self):
        site = self.exported_site()
        victim = self.root / "victim.txt"
        victim.write_text("VICTIM\n", encoding="utf-8")
        self.add_to_manifest(site, victim.as_posix())
        output, _ = self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.1")
        self.assertTrue(victim.is_file())
        self.assertIn(f"kept {victim.as_posix()}", output)

    def test_export_keeps_a_file_reached_through_a_symbolic_link_out_of_the_folder(self):
        site = self.exported_site()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "old.md").write_text("# Keep\n", encoding="utf-8")
        try:
            (site / "blog" / "linked").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"This account cannot create symbolic links: {error}")
        self.add_to_manifest(site, "blog/linked/old.md")
        output, _ = self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.1")
        self.assertTrue((outside / "old.md").is_file())
        self.assertIn("kept blog/linked/old.md", output)

    def test_export_refuses_to_write_pages_through_a_link_out_of_the_folder(self):
        site = self.exported_site()
        outside = self.root / "outside"
        outside.mkdir()
        for page in (site / "learn").iterdir():
            page.unlink()
        (site / "learn").rmdir()
        try:
            (site / "learn").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"This account cannot create symbolic links: {error}")
        _, error = self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.1", code=1)
        self.assertIn("outside", error)
        self.assertEqual(list(outside.iterdir()), [])

    def test_twenty_shares_recorded_at_once_are_all_kept(self):
        until = (date.today() + timedelta(days=30)).isoformat()
        environment = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
                       "PYTHONIOENCODING": "utf-8"}

        def add(index):
            command = [sys.executable, "-m", "openguildkit", "--project", str(self.root), "docs", "share", "add",
                       "--deliverable", f"d{index}", "--recipient", f"reader{index}@example.test", "--until", until,
                       "--portal", "https://docs.example.test/p/portal", "--by", "Camille"]
            for _ in range(400):
                done = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8")
                # The project lock may refuse a busy project instead of waiting: try again then.
                if done.returncode == 0 or BUSY not in done.stderr:
                    return done
                time.sleep(0.05)
            return done

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(add, range(20)))
        self.assertEqual([item.returncode for item in results], [0] * 20, [item.stderr for item in results])
        shares = json.loads((self.root / ".openguildkit" / "shares" / "shares.json").read_text(encoding="utf-8"))["shares"]
        self.assertEqual(sorted(share["deliverable"] for share in shares), sorted(f"d{index}" for index in range(20)))

    def test_revoking_a_share_holds_the_project_lock(self):
        until = (date.today() + timedelta(days=30)).isoformat()
        self.run_cli("docs", "share", "add", "--deliverable", "d", "--recipient", "reader@example.test", "--until", until,
                     "--portal", "https://docs.example.test/p/portal", "--by", "Camille")
        share_id = json.loads(self.run_cli("docs", "share", "list", "--json")[0])[0]["id"]
        held = []
        real_lock = publishing.project_lock

        @contextlib.contextmanager
        def recording_lock(state):
            with real_lock(state):
                held.append(True)
                yield
                held.append(False)

        with patch.object(publishing, "project_lock", recording_lock), \
                patch.object(publishing, "write_json", side_effect=lambda *args: self.assertEqual(held[-1:], [True]) or write_json(*args)):
            self.run_cli("docs", "share", "revoke", "--id", share_id, "--by", "Camille")
        self.assertEqual(held, [True, False])

    def test_share_dates_portal_and_revocation_are_checked(self):
        common = ["docs", "share", "add", "--deliverable", "d", "--recipient", "reader@example.test", "--by", "Camille"]
        portal = ["--portal", "https://docs.example.test/p/portal"]
        later = date.today() + timedelta(days=30)
        for until in (later.strftime("%Y%m%d"), later.strftime("%G-W%V-%u"), "9999-12-31", "2026-02-30"):
            _, error = self.run_cli(*common, *portal, "--until", until, code=1)
            self.assertTrue(error.startswith("OpenGuildKit: "), error)
        self.run_cli(*common, "--portal", "https://", "--until", later.isoformat(), code=1)
        self.run_cli(*common, *portal, "--until", later.isoformat())
        share_id = json.loads(self.run_cli("docs", "share", "list", "--json")[0])[0]["id"]
        self.run_cli("docs", "share", "revoke", "--id", share_id, "--by", "   ", code=1)
        self.run_cli("docs", "share", "revoke", "--id", share_id, "--by", "Camille")
        _, error = self.run_cli("docs", "share", "revoke", "--id", share_id, "--by", "Mallory", code=1)
        self.assertIn("already revoked", error)
        share = json.loads(self.run_cli("docs", "share", "list", "--json")[0])[0]
        self.assertEqual(share["revoked_by"], "Camille")

    @unittest.skipIf(shutil.which("git") is None, "The example's only check command is git --version.")
    def test_replaying_the_documentalist_example_gives_its_docs_site(self):
        project = self.root / "replay"
        command = [sys.executable, str(DOCUMENTALIST / "replay.py"), "--project", str(project)]
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        first = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("Approval needs a person", first.stdout)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--project", str(project), "task", "decide", TASK, "--approve", "--by", "Camille Martin",
                                   "--reason", "Scope agreed"]), 0)
        second = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(second.returncode, 0, second.stderr)
        produced, expected = project / "docs-site", DOCUMENTALIST / "docs-site"
        # The blog page is named and dated after the day of completion; every other byte must match.
        expected_day = next((expected / "blog").glob("*.md")).name[:10]
        produced_day = next((produced / "blog").glob("*.md")).name[:10]

        def tree(folder, day):
            return {path.relative_to(folder).as_posix().replace(day, "DAY"): path.read_text(encoding="utf-8").replace(day, "DAY")
                    for path in sorted(folder.rglob("*")) if path.is_file()}

        self.assertEqual(tree(produced, produced_day), tree(expected, expected_day))


if __name__ == "__main__":
    unittest.main()
