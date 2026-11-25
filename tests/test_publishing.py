import contextlib
import importlib.util
import io
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock, publishing
from openguildkit.catalog import load_catalog
from openguildkit.storage import write_json

from tests.support import CapturedCli, run_cli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
DOCUMENTALIST = REPO / "examples" / "documentalist"


def load_script(path: Path):
    """Import an example script, which lives outside the package."""
    spec = importlib.util.spec_from_file_location(f"example_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
TASK = "request-status"
BUSY = "is writing this project"


class PublishingTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Support portal", "stack": ["Python"], "packs": [], "checks": [command]})
        self.run_cli("init", "--answers", self.root / "profile.json")
        # A folder that docs export wrote carries its manifest: it can be shared as a whole.
        (self.root / "docs-site").mkdir()
        (self.root / "docs-site" / publishing.MANIFEST).write_text('{"version": "0", "tasks": [], "files": []}', encoding="utf-8")

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
        self.assertEqual(reference.count("- Users only see their own requests."), 1)
        self.assertRegex(reference, r"Checks before release: 1 passed, [1-9][0-9]* not applicable")
        self.assertRegex(reference, r"[1-9][0-9]* objection\(s\) between the boards were not deliberated")
        self.assertNotIn("tests/test_access.py", reference)
        self.assertNotIn("recommendation", reference)
        blog = next((site / "blog").glob(f"*-{TASK}.md"))
        self.assertRegex(blog.read_text(encoding="utf-8"), r'date: "\d{4}-\d{2}-\d{2}"')
        self.assertIn(f"(reference/{TASK}.md)", (site / "SUMMARY.md").read_text(encoding="utf-8"))

        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.5.0", "--sections", "reference,blog")
        self.assertIn('project_version: "1.5.0"', (site / "reference" / f"{TASK}.md").read_text(encoding="utf-8"))
        self.assertFalse((site / "learn" / f"{TASK}.md").exists())
        self.assertEqual(len(list((site / "reference").glob("*.md"))), 1)

    def test_export_replaces_a_credential_the_record_holds_and_says_what_personal_data_it_publishes(self):
        self.done_task()
        path = self.root / ".openguildkit" / "tasks" / f"{TASK}.json"
        task = json.loads(path.read_text(encoding="utf-8"))
        password, key = "hunter" + "2pass", "AK" + "IA" + "IOSFODNN7EXAMPLE"
        task["brief"] += f"\nDeploy with {key}. Ask ops@example.test, +33 6 12 34 56 78 or FR76 3000 6000 0112 3456 7890 189.\n"
        task["answers"]["outcome"] = f"Customers see their status, read with password={password}."
        task["result"]["pull_request"] = f"https://user:{password}@github.com/example/portal/pull/7"
        write_json(path, task)
        _, warning = self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0")
        for page in (self.root / "docs-site").rglob("*.md"):
            text = page.read_text(encoding="utf-8")
            for secret in (key, password):
                self.assertNotIn(secret, text, page.name)
        reference = (self.root / "docs-site" / "reference" / f"{TASK}.md").read_text(encoding="utf-8")
        self.assertIn("Delivered in https://user:[password]@github.com/example/portal/pull/7", reference)
        self.assertIn("Deploy with [credential].", reference)
        self.assertIn(f"{TASK}: replaced a possible credential with a placeholder before publishing it", warning)
        self.assertIn(f"{TASK}: the pages contain an email address and a phone number and a bank account number", warning)
        for value in (key, password, "ops@example.test", "56 78", "3000 6000"):
            self.assertNotIn(value, warning)

    def test_export_of_a_clean_record_has_nothing_to_say(self):
        self.done_task()
        self.assertEqual(self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0")[1], "")

    def test_a_long_first_line_stays_in_reference_and_blog_when_the_title_is_shortened(self):
        brief = (
            "Show each signed-in customer the status and next step of their own support requests, "
            "including the requests created before the portal migration."
        )
        brief_path = self.root / "long-brief.md"
        brief_path.write_text(brief + "\n", encoding="utf-8")
        self.done_task(brief_file=brief_path)
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0")

        for section in ("reference", "blog"):
            page, = (self.root / "docs-site" / section).glob(f"*{TASK}.md")
            markdown = page.read_text(encoding="utf-8")
            self.assertIn(f"# {brief[:120]}\n", markdown)
            self.assertIn(f"\n{brief}\n", markdown)

    def test_export_refuses_a_folder_it_did_not_create(self):
        self.done_task()
        (self.root / "notes").mkdir()
        (self.root / "notes" / "team.md").write_text("# Team\n", encoding="utf-8")
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "notes", "--version", "1.0.0", code=1)

    def deliverable(self, relative="d"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Shared page\n", encoding="utf-8")

    def test_shares_record_recipients_end_date_and_revocation(self):
        self.deliverable("docs-site/reference/request-status.md")
        until = (clock.real_today() + timedelta(days=14)).isoformat()
        common = ["docs", "share", "add", "--deliverable", "docs-site/reference/request-status.md", "--portal", "https://docs.example.org/p/portal"]
        self.run_cli(*common, "--recipient", "not-an-email", "--until", until, "--by", "Camille", code=1)
        output, _ = self.run_cli(*common, "--recipient", "client@example.org", "--until", until, "--by", "Camille")
        self.assertIn(f"Set the last day {until} in Documentalist if supported", output)
        self.assertIn("On older versions remove access", output)
        shares = json.loads(self.run_cli("docs", "share", "list", "--json")[0])
        self.assertEqual(shares[0]["state"], "active")
        self.run_cli("docs", "share", "check")
        state = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(state.read_text())
        data["shares"][0]["until"] = (clock.real_today() - timedelta(days=1)).isoformat()
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
        until = (clock.real_today() + timedelta(days=30)).isoformat()
        environment = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
                       "PYTHONIOENCODING": "utf-8"}

        for index in range(20):
            self.deliverable(f"d{index}")

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
        self.deliverable()
        until = (clock.real_today() + timedelta(days=30)).isoformat()
        self.run_cli("docs", "share", "add", "--deliverable", "d", "--recipient", "reader@example.test",
                     "--until", until, "--portal", "https://docs.example.test/p/portal", "--by", "Camille")
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

    def test_a_share_names_a_file_of_the_project_or_a_docs_export_and_nothing_else(self):
        until = (clock.real_today() + timedelta(days=30)).isoformat()
        (self.root / "notes").mkdir()
        (self.root / ".openguildkit" / "tasks").mkdir(exist_ok=True)
        (self.root / ".openguildkit" / "tasks" / "report.json").write_text("{}", encoding="utf-8")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "secret.md").write_text("outside", encoding="utf-8")
        refused = {
            "notes": "a folder that holds no documentation export",
            "docs-site/missing.md": "does not exist",
            ".openguildkit/tasks/report.json": "in .openguildkit/",
            "docs-site/../.openguildkit/tasks/report.json": "in .openguildkit/",
            "../outside/f.md": "outside the project",
            str(outside / "secret.md"): "outside the project",
        }
        for path, reason in refused.items():
            with self.subTest(path=path):
                _, error = self.run_cli("docs", "share", "add", "--deliverable", path, "--recipient", "reader@example.test",
                                        "--until", until, "--portal", "https://docs.example.test/p/portal", "--by", "Camille", code=1)
                self.assertIn(reason, error)
        self.assertEqual(json.loads(self.run_cli("docs", "share", "list", "--json")[0]), [])
        self.run_cli("docs", "share", "add", "--deliverable", "docs-site", "--recipient", "reader@example.test",
                     "--until", until, "--portal", "https://docs.example.test/p/portal", "--by", "Camille")

    def test_a_share_refuses_a_path_through_a_link_out_of_the_project(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "page.md").write_text("outside the project", encoding="utf-8")
        link = self.root / "docs-site" / "linked-folder"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            # A directory junction does not require Windows symlink privileges.
            subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", r"docs-site\linked-folder", str(outside)],
                           cwd=self.root, capture_output=True, check=True)
        try:
            until = (clock.real_today() + timedelta(days=30)).isoformat()
            _, error = self.run_cli("docs", "share", "add", "--deliverable", "docs-site/linked-folder/page.md",
                                    "--recipient", "reader@example.test", "--until", until,
                                    "--portal", "https://docs.example.test/p/portal", "--by", "Camille", code=1)
            self.assertIn("outside the project, once links are followed", error)
            self.assertEqual(json.loads(self.run_cli("docs", "share", "list", "--json")[0]), [])
        finally:
            if link.is_symlink():
                link.unlink()
            else:
                link.rmdir()

    def test_share_dates_portal_and_revocation_are_checked(self):
        self.deliverable()
        common = ["docs", "share", "add", "--deliverable", "d", "--recipient", "reader@example.test", "--by", "Camille"]
        portal = ["--portal", "https://docs.example.test/p/portal"]
        later = clock.real_today() + timedelta(days=30)
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
        replay = load_script(DOCUMENTALIST / "replay.py")

        def run_here(folder, *args, capture=False):
            """The script's run(), with the CLI in this process and the script's dates."""
            result = run_cli(folder, *args, stdin="", expect=None, env={"SOURCE_DATE_EPOCH": replay.COMPLETED})
            if not capture:
                print(result.stdout, end="")
            return result

        def play():
            shown = io.StringIO()
            with patch.object(replay, "run", run_here), patch.object(sys, "argv", ["replay.py", "--project", str(project)]), \
                    patch("sys.stdin", io.StringIO("")), contextlib.redirect_stdout(shown):
                replay.main()
            return shown.getvalue()

        self.assertIn("Approval needs a person", play())
        run_cli(project, "task", "decide", TASK, "--approve", "--by", "CM", "--reason", "Scope agreed", typed=TASK)
        self.assertIn("is identical to examples/documentalist/docs-site", play())
        script = subprocess.run([sys.executable, str(DOCUMENTALIST / "replay.py"), "--help"], capture_output=True,
                                text=True, encoding="utf-8", timeout=60)
        self.assertEqual(script.returncode, 0, script.stderr)
        produced, expected = project / "docs-site", DOCUMENTALIST / "docs-site"

        def tree(folder):
            # A Windows checkout may hold the committed example with CRLF line endings.
            return {path.relative_to(folder).as_posix(): path.read_bytes().replace(b"\r\n", b"\n")
                    for path in sorted(folder.rglob("*")) if path.is_file()}

        self.assertEqual(tree(produced), tree(expected))

    def test_export_writes_one_project_page_from_the_profile_packs_and_boards(self):
        profile_path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile.update(sector="general", conventions=["Write user-facing text in French and English."],
                       components=[{"id": "portal-api", "path": "services/api", "stack": ["Python"]}])
        write_json(profile_path, profile)
        self.run_cli("sync")
        self.done_task()
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0")
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.1")
        site = self.root / "docs-site"
        self.assertEqual([path.name for path in (site / "project").iterdir()], ["overview.md"])
        page = (site / "project" / "overview.md").read_text(encoding="utf-8")
        manifest = json.loads((site / ".openguildkit-export.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"].count("project/overview.md"), 1)
        self.assertIn("(project/overview.md)", (site / "SUMMARY.md").read_text(encoding="utf-8"))
        self.assertIn('project_version: "1.4.1"', page)
        self.assertIn("# Support portal", page)
        self.assertIn("Sector: general", page)
        self.assertIn("Python", page)
        self.assertIn("portal-api", page)
        self.assertIn("Write user-facing text in French and English.", page)
        workflow = load_catalog()["packs"]["agent-workflow"]
        self.assertIn(f"{workflow['title']} (agent-workflow, version {workflow['version']})", page)
        self.assertIn(workflow["rules"][0]["instruction"], page)
        self.assertIn("Marketing and market research", page)
        task = json.loads(self.run_cli("task", "show", TASK)[0])
        consulted = {entry["id"] for entry in task["review"]["boards"]}
        listed = set(re.findall(r"\(([a-z-]+)\)$", page.split("## Boards consulted", 1)[1], re.M))
        self.assertEqual(listed, consulted)
        for private in ("services/api", str(self.root), self.root.as_posix(), "print(1)", "Camille"):
            self.assertNotIn(private, page)

    def test_the_project_page_is_selected_like_the_other_sections(self):
        self.done_task()
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0", "--sections", "reference")
        self.assertFalse((self.root / "docs-site" / "project").exists())
        output, _ = self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0", "--sections", "project")
        self.assertIn("wrote project/overview.md", output)
        self.assertIn("removed reference/request-status.md", output)

    def link(self, name, target):
        try:
            (self.root / name).symlink_to(target, target_is_directory=target.is_dir())
        except OSError as error:
            self.skipTest(f"This account cannot create symbolic links: {error}")

    def share(self, deliverable, code=0):
        until = (clock.real_today() + timedelta(days=14)).isoformat()
        return self.run_cli("docs", "share", "add", "--deliverable", deliverable, "--recipient", "reader@example.test",
                            "--until", until, "--portal", "https://docs.example.test/p/x", "--by", "Sam", code=code)[1]

    def test_a_share_of_a_task_record_is_refused(self):
        error = self.share(".openguildkit/tasks/report-csv.json", code=1)
        self.assertIn("--deliverable .openguildkit/tasks/report-csv.json is in .openguildkit/", error)
        self.assertIn("--deliverable .openguildkit is in .openguildkit/", self.share(".openguildkit", code=1))
        self.assertFalse((self.root / ".openguildkit" / "shares" / "shares.json").exists())

    def test_a_share_outside_the_project_is_refused(self):
        error = self.share("../outside/f.md", code=1)
        self.assertIn("--deliverable ../outside/f.md is outside the project", error)
        absolute = Path(tempfile.gettempdir()).resolve() / "elsewhere.md"
        self.assertIn(f"--deliverable {absolute.as_posix()} is outside the project", self.share(str(absolute), code=1))
        self.assertFalse((self.root / ".openguildkit" / "shares" / "shares.json").exists())

    def test_a_share_through_a_link_out_of_the_project_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.link("published", Path(outside.name))
        self.assertIn("--deliverable published/f.md is outside the project", self.share("published/f.md", code=1))

    def test_a_share_through_a_link_into_the_state_folder_is_refused(self):
        self.link("records", self.root / ".openguildkit" / "tasks")
        self.assertIn("--deliverable records/x.json is in .openguildkit/", self.share("records/x.json", code=1))

    def test_a_share_of_the_state_folder_written_in_another_case_is_refused(self):
        if not (self.root / ".OPENGUILDKIT").exists():
            self.skipTest("This file system tells .OPENGUILDKIT from .openguildkit: the path is another folder.")
        error = self.share(".OpenGuildKit/tasks/report-csv.json", code=1)
        self.assertIn("--deliverable .OpenGuildKit/tasks/report-csv.json is in .openguildkit/", error)

    def test_a_missing_file_or_a_folder_without_an_export_is_not_shared(self):
        self.assertIn("--deliverable docs-site/reference/nonexistent.md does not exist",
                      self.share("docs-site/reference/nonexistent.md", code=1))
        (self.root / "notes").mkdir()
        self.assertIn("--deliverable notes is a folder that holds no documentation export", self.share("notes", code=1))
        self.assertFalse((self.root / ".openguildkit" / "shares" / "shares.json").exists())

    def test_the_folder_of_a_documentation_export_can_be_shared(self):
        self.exported_site()
        self.share("docs-site")
        self.assertEqual(json.loads(self.run_cli("docs", "share", "list", "--json")[0])[0]["deliverable"], "docs-site")

    def test_a_share_inside_the_project_is_recorded_as_written(self):
        self.deliverable("docs-site/reference/request-status.md")
        self.share("docs-site/reference/request-status.md")
        shares = json.loads(self.run_cli("docs", "share", "list", "--json")[0])
        self.assertEqual(shares[0]["deliverable"], "docs-site/reference/request-status.md")

    def test_docs_export_writes_only_inside_the_project_and_outside_the_state_folder(self):
        self.done_task()
        common = ("docs", "export", "--tasks", TASK, "--version", "1.4.0")
        _, error = self.run_cli(*common, "--output", "../site", code=1)
        self.assertIn("--output ../site is outside the project", error)
        _, error = self.run_cli(*common, "--output", ".openguildkit/site", code=1)
        self.assertIn("--output .openguildkit/site is in .openguildkit/", error)
        _, error = self.run_cli(*common, "--output", "docs-site", "--openapi", ".openguildkit/tasks/x.json", code=1)
        self.assertIn("--openapi .openguildkit/tasks/x.json is in .openguildkit/", error)
        self.assertFalse((self.root / ".openguildkit" / "site").exists())

    def test_the_export_summary_is_honest_and_says_each_thing_once(self):
        site = self.exported_site()
        reference = (site / "reference" / f"{TASK}.md").read_text(encoding="utf-8")
        task = json.loads(self.run_cli("task", "show", TASK)[0])
        checks = task["result"]["checks"]
        passed = sum(item["status"] == "passed" for item in checks)
        skipped = sum(item["status"] == "not-applicable" for item in checks)
        self.assertGreater(skipped, 0)
        self.assertIn(f"Checks before release: {passed} passed, {skipped} not applicable, "
                      f"{len(checks) - passed - skipped} open.", reference)
        bullets = [line for line in reference.splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), len({line.casefold().rstrip(".") for line in bullets}))
        title = task["brief"].strip().splitlines()[0].rstrip(".")
        self.assertEqual(reference.count(title), 2, "the title, in the front matter and the heading only")

    def test_the_project_page_lists_only_the_boards_consulted(self):
        self.done_task()
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0", "--sections", "project")
        page = (self.root / "docs-site" / "project" / "overview.md").read_text(encoding="utf-8")
        consulted = json.loads(self.run_cli("task", "show", TASK)[0])["consultation"]["boards"]
        listed = page.split("## Boards consulted", 1)[1]
        boards = load_catalog()["boards"]
        for board_id in boards:
            self.assertEqual(f"({board_id})" in listed, board_id in consulted, board_id)


    def add(self, deliverable="d", recipient="reader@example.test", portal="https://docs.example.test/p/support-portal",
            until=None, code=0, dedicated=False):
        until = until or (clock.real_today() + timedelta(days=14)).isoformat()
        return self.run_cli("docs", "share", "add", "--deliverable", deliverable, "--recipient", recipient, "--until", until,
                            "--portal", portal, "--by", "Camille", *(["--dedicated-space"] if dedicated else []), code=code)

    def shares(self):
        return json.loads(self.run_cli("docs", "share", "list", "--json")[0])

    def test_a_share_records_and_shows_the_portal_space_as_its_perimeter(self):
        self.deliverable()
        self.deliverable("docs-site/reference/request-status.md")
        output, _ = self.add("docs-site/reference/request-status.md",
                             portal="https://Docs.Example.test/p/support-portal/reference/request-status")
        self.assertIn("whole space docs.example.test/p/support-portal", output)
        self.assertIn("every published page of that space", output)
        self.assertEqual(self.shares()[0]["space"], "docs.example.test/p/support-portal")
        listed, _ = self.run_cli("docs", "share", "list")
        self.assertIn("docs-site/reference/request-status.md (whole space docs.example.test/p/support-portal)", listed)
        for portal in ("https://docs.example.test", "https://docs.example.test/", "https://docs.example.test/p/",
                       "https://docs.example.test/support-portal"):
            with self.subTest(portal=portal):
                _, error = self.add(portal=portal, code=1)
                self.assertIn("https://HOST/p/SPACE", error)
        self.assertEqual(len(self.shares()), 1)

    def test_a_share_recorded_before_the_space_field_shows_the_space_of_its_portal(self):
        self.deliverable()
        self.add()
        register = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(register.read_text(encoding="utf-8"))
        del data["shares"][0]["space"]
        register.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.shares()[0]["space"], "docs.example.test/p/support-portal")

    def test_until_is_a_reminder_and_check_names_the_access_to_remove(self):
        self.deliverable()
        until = (clock.real_today() + timedelta(days=14)).isoformat()
        output, _ = self.add(until=until)
        self.assertIn(f"Set the last day {until} in Documentalist if supported", output)
        self.assertIn("On older versions remove access", output)
        self.assertIn("local check is a reminder", output)
        share_id = self.shares()[0]["id"]
        register = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(register.read_text(encoding="utf-8"))
        data["shares"][0]["until"] = (clock.real_today() - timedelta(days=1)).isoformat()
        register.write_text(json.dumps(data), encoding="utf-8")
        output, _ = self.run_cli("docs", "share", "check", code=1)
        self.assertIn("remove reader@example.test from space docs.example.test/p/support-portal", output)
        self.assertIn(f"openguildkit docs share revoke --id {share_id} --by NAME", output)
        self.assertEqual(self.shares()[0]["remove"], ["reader@example.test"])

    def test_check_keeps_an_address_that_another_running_share_still_covers(self):
        self.deliverable()
        self.deliverable("e")
        self.run_cli("docs", "share", "add", "--deliverable", "d", "--recipient", "reader@example.test", "--recipient",
                     "other@example.test", "--until", (clock.real_today() + timedelta(days=14)).isoformat(),
                     "--portal", "https://docs.example.test/p/support-portal", "--by", "Camille")
        later = (clock.real_today() + timedelta(days=60)).isoformat()
        self.add("e", portal="https://docs.example.test/p/support-portal/learn/x", until=later)
        first, second = (row["id"] for row in self.shares())
        register = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(register.read_text(encoding="utf-8"))
        data["shares"][0]["until"] = (clock.real_today() - timedelta(days=1)).isoformat()
        register.write_text(json.dumps(data), encoding="utf-8")
        output, _ = self.run_cli("docs", "share", "check", code=1)
        self.assertIn(f"keep reader@example.test: share {second} gives the same space until {later}", output)
        self.assertIn("remove other@example.test from space docs.example.test/p/support-portal", output)
        self.assertNotIn("remove reader@example.test", output)
        self.assertIn(f"openguildkit docs share revoke --id {first} --by NAME", output)
        self.assertEqual(self.shares()[0]["remove"], ["other@example.test"])
        data["shares"][0]["recipients"] = ["reader@example.test"]
        register.write_text(json.dumps(data), encoding="utf-8")
        output, _ = self.run_cli("docs", "share", "check")
        self.assertIn("covered: other shares keep the same access, nothing to remove yet", output)
        self.assertNotIn("revoke", output)
        self.assertEqual(self.shares()[0]["kept"], {"reader@example.test": {"share": second, "until": later}})

    def test_a_second_share_for_the_same_recipient_and_space_is_announced(self):
        self.deliverable()
        self.deliverable("e")
        self.add()
        first = self.shares()[0]["id"]
        _, warning = self.add("e", recipient="reader@example.test",
                              portal="https://docs.example.test/p/support-portal/reference/other")
        self.assertIn(f"reader@example.test already has access to space docs.example.test/p/support-portal through share {first}",
                      warning)
        self.assertIn("one access per address and space", warning)
        for other in ({"recipient": "other@example.test"}, {"portal": "https://docs.example.test/p/another-space"},
                      {"portal": "https://elsewhere.example.test/p/support-portal"}):
            with self.subTest(other=other):
                self.assertNotIn("already has access", self.add("e", **other)[1])
        self.run_cli("docs", "share", "revoke", "--id", first, "--by", "Camille")
        self.assertNotIn(first, self.add("e")[1])

    def test_two_deliverables_in_one_space_are_announced_as_readable_by_both_audiences(self):
        self.deliverable()
        self.deliverable("e")
        self.add()
        first = self.shares()[0]["id"]
        _, warning = self.add("./e", recipient="other@example.test")
        self.assertIn(f"space docs.example.test/p/support-portal also carries d (share {first})", warning)
        self.assertIn("can read both deliverables", warning)
        self.assertIn("--dedicated-space", warning)
        rows = self.shares()
        self.assertEqual([row["also_in_space"] for row in rows], [["./e"], ["d"]])
        listed, _ = self.run_cli("docs", "share", "list")
        self.assertIn("its recipients can also read ./e, shared through the same space", listed)
        self.run_cli("docs", "share", "check")
        self.assertEqual(self.add("./d", recipient="third@example.test")[1].count("also carries d "), 0)
        self.assertEqual(self.add("e", portal="https://docs.example.test/p/another-space")[1], "")
        self.run_cli("docs", "share", "revoke", "--id", first, "--by", "Camille")
        self.assertEqual(self.shares()[0]["also_in_space"], [])

    def test_a_dedicated_space_refuses_a_second_deliverable_and_keeps_existing_spaces_working(self):
        self.deliverable()
        self.deliverable("e")
        dedicated = "https://docs.example.test/p/deliverable-d"
        output, _ = self.add(portal=dedicated, dedicated=True)
        self.assertIn("is recorded as dedicated to d", output)
        self.assertIn("check from a reader session", output)
        self.assertTrue(self.shares()[0]["dedicated"])
        _, error = self.add("e", portal=dedicated + "/reference/x", code=1)
        self.assertIn("Space docs.example.test/p/deliverable-d is dedicated to d", error)
        _, error = self.add("e", portal=dedicated, dedicated=True, code=1)
        self.assertIn("is dedicated to d", error)
        self.assertEqual(len(self.shares()), 1)
        output, _ = self.add("./d", recipient="other@example.test", portal=dedicated)
        self.assertIn("is recorded as dedicated to ./d", output)
        self.add("e")
        self.add("d")
        _, error = self.add("e", recipient="third@example.test", dedicated=True, code=1)
        self.assertIn("already carries d (share", error)
        self.assertIn("cannot be dedicated", error)
        self.assertEqual([row["dedicated"] for row in self.shares()], [True, True, False, False])
        self.run_cli("docs", "share", "check")
        for row in self.shares()[2:]:
            self.run_cli("docs", "share", "revoke", "--id", row["id"], "--by", "Camille")
        self.add("e", recipient="third@example.test", dedicated=True)
        first = self.shares()[0]["id"]
        self.run_cli("docs", "share", "revoke", "--id", first, "--by", "Camille")
        _, error = self.add("e", portal=dedicated, code=1)
        self.assertIn("is dedicated to ./d", error)

    def test_check_fails_when_a_dedicated_space_carries_another_deliverable_after_an_edit(self):
        self.deliverable()
        self.deliverable("e")
        self.add(dedicated=True)
        self.add("e", portal="https://docs.example.test/p/other-space")
        register = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(register.read_text(encoding="utf-8"))
        data["shares"][1]["portal"] = data["shares"][0]["portal"]
        data["shares"][1]["space"] = data["shares"][0]["space"]
        register.write_text(json.dumps(data), encoding="utf-8")
        output, _ = self.run_cli("docs", "share", "check", code=1)
        self.assertIn("its recipients can also read e, shared through the same space although the space is recorded "
                      "as dedicated to this deliverable", output)
        self.run_cli("docs", "share", "list")

    def test_revoking_says_the_portal_removal_covers_the_whole_space(self):
        self.deliverable()
        self.deliverable("e")
        self.add()
        self.add("e")
        self.add("e", recipient="other@example.test")
        first, second, third = (row["id"] for row in self.shares())
        output, _ = self.run_cli("docs", "share", "revoke", "--id", first, "--by", "Camille")
        self.assertIn("revoked", output)
        self.assertIn("removes an address from the whole space docs.example.test/p/support-portal", output)
        self.assertIn("Other shares give reader@example.test the same space", output)
        self.assertIn(f"openguildkit docs share revoke --id {second} --by NAME", output)
        self.assertNotIn(third, output)
        output, _ = self.run_cli("docs", "share", "revoke", "--id", second, "--by", "Camille")
        self.assertNotIn("--id", output)

    def test_a_local_portal_address_may_use_http_on_this_machine_only(self):
        self.deliverable()
        for portal in ("http://127.0.0.1:3000/p/support-portal", "http://localhost:3000/p/support-portal",
                       "http://[::1]:3000/p/support-portal"):
            with self.subTest(portal=portal):
                self.add(portal=portal)
        self.assertEqual([row["space"] for row in self.shares()],
                         ["127.0.0.1:3000/p/support-portal", "localhost:3000/p/support-portal", "[::1]:3000/p/support-portal"])
        for portal in ("http://docs.example.test/p/support-portal", "http://127.0.0.1.example.test/p/support-portal",
                       "http://10.0.0.8/p/support-portal", "ftp://127.0.0.1/p/support-portal",
                       "http://127.0.0.1:99999/p/support-portal"):
            with self.subTest(portal=portal):
                _, error = self.add(portal=portal, code=1)
                self.assertTrue(error.startswith("OpenGuildKit: "), error)
        self.assertEqual(len(self.shares()), 3)

    def section(self, title):
        guide = (REPO / "docs" / "documentation.md").read_text(encoding="utf-8")
        return guide.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]

    def test_the_guide_names_the_documentalist_version_checked_and_its_reuse_conditions(self):
        verified = self.section("Versions verified and reuse")
        for fact in ("2026-11-22", "947429b", "Node.js 26.13.0", "Node.js 22.20.0", "imported three pages", "same three pages and IDs",
                     "stand-in",
                     "no licence file", "`null`", "no `license` field", "Ask its author"):
            self.assertIn(fact, verified)
        report = DOCUMENTALIST / "reports" / "2026-11-22.md"
        self.assertIn("(../examples/documentalist/reports/2026-11-22.md)", verified)
        addresses = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", report.read_text(encoding="utf-8")))
        self.assertEqual({address.rsplit("@", 1)[1] for address in addresses}, {"example.test"})

    def test_the_guide_corrects_the_import_paths_the_run_checked(self):
        imports = self.section("Import into Documentalist")
        for fact in ('Outils → Importer → "Depuis GitHub"', "github.com only", "Mettre à jour l'espace actuel",
                     "every page goes to Reference", "creates a new page", "source path and locale", "new ID",
                     '"Relancer sync"', "never syncs on its own", '"Publier"', "takes a URL", "delete the pages of the previous one"):
            self.assertIn(fact, imports)
        export = self.section("Export")
        self.assertIn("neither imports them nor reads them for the order", export)
        self.assertNotIn("SUMMARY.md` fixes the order", export)

    def test_the_guide_says_what_a_share_gives_and_what_the_instance_keeps(self):
        sharing = self.section("Share a deliverable")
        for fact in ("whole space", "**The perimeter is the space.**", "**`--until` records the intended last day.**",
                     "**One access per address and space.**", "**What the instance records.**",
                     "`DOCUMENTALIST_SMTP_URL`", "`127.0.0.1`"):
            self.assertIn(fact, sharing)

    def test_the_guide_says_what_source_date_epoch_changes_and_what_it_does_not_decide(self):
        dates = self.section("Reproducible dates")
        self.assertIn("once on stderr", dates)
        decisions = dates.split("What it does not decide:", 1)[1].split("\n\n", 1)[0]
        for decision in ("docs share add", "docs share check", "waiver", "approval", "real clock"):
            self.assertIn(decision, decisions)

if __name__ == "__main__":
    unittest.main()
