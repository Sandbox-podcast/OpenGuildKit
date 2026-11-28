"""openguildkit evidence export and verify: a dossier of facts for an auditor, whose files a check recomputes (issue #482)."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from openguildkit import controls
from openguildkit.lock import package_version
from openguildkit.storage import write_json
from tests.support import run_cli
from tests.test_trace import GIT_ENV, snapshot

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FILES = ["alerts.jsonl", "controls.json", "decisions.jsonl", "profile-changes.jsonl", "signers-history.jsonl"]


def epoch(year: int, month: int, day: int) -> str:
    return str(int(datetime(year, month, day, 12, tzinfo=UTC).timestamp()))


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@unittest.skipIf(shutil.which("git") is None, "needs git")
class EvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.root = self.work / "portal"
        self.root.mkdir()

    def cli(self, *arguments, code=0, env=None, typed=None):
        return run_cli(self.root, *arguments, expect=code, env=env, typed=typed)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True,
                              env=GIT_ENV).stdout.strip()

    def project(self, extra=None):
        self.git("init", "-q", "-b", "main")
        (self.root / "README.md").write_text("Support portal\n", encoding="utf-8")
        profile = {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), "checks": [], "guard": "enforce",
                   **(extra or {})}
        write_json(self.work / "profile.json", profile)
        self.cli("init", "--answers", self.work / "profile.json")

    def approved(self, task_id: str, day: tuple, export=True):
        """A task approved and exported on a day, the clock set to it."""
        env = {"SOURCE_DATE_EPOCH": epoch(*day)}
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id, env=env)
        self.cli("task", "consult", task_id, "--answers", EXAMPLE / "answers.json", env=env)
        template = json.loads(self.cli("task", "template", task_id, env=env).stdout)
        write_json(self.work / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))})
        self.cli("task", "review", task_id, "--file", self.work / "review.json", env=env)
        # The approval is stamped with the real clock, which SOURCE_DATE_EPOCH does not move.
        with patch("openguildkit.clock.real_timestamp", return_value=f"{day[0]}-{day[1]:02d}-{day[2]:02d}T12:00:00+00:00"):
            self.cli("task", "decide", task_id, "--approve", "--by", "Camille Martin", "--reason", "Agreed", env=env,
                     typed=task_id)
        if export:
            self.cli("task", "export", task_id, env=env)

    def two_decisions(self):
        self.project()
        self.approved("first-task", (2026, 10, 15))
        self.approved("second-task", (2026, 12, 1))

    def export(self, *arguments, code=0, output="dossier"):
        return self.cli("evidence", "export", "--output", output, *arguments, code=code)

    def failure(self, dossier: Path) -> str:
        """What `evidence verify` prints, both streams, when it ends in 1."""
        result = self.cli("evidence", "verify", dossier, code=1)
        return result.stdout + result.stderr

    def test_two_exported_decisions_give_two_lines_each_with_the_state_of_its_seal_and_signature(self):
        """Issue #482: an auditor had no command that handed over the decisions with the state of their seals."""
        self.two_decisions()
        self.export()
        dossier = self.root / "dossier"
        self.assertEqual(sorted(path.name for path in dossier.iterdir()), ["MANIFEST.json", *FILES])
        rows = lines(dossier / "decisions.jsonl")
        self.assertEqual([row["task"] for row in rows], ["first-task", "second-task"])
        for row in rows:
            record = self.root / row["record"]
            self.assertEqual(row["record"], f".openguildkit/decisions/{row['task']}.json")
            self.assertEqual(row["record_file_sha256"], hashlib.sha256(record.read_bytes()).hexdigest())
            self.assertEqual((row["seal"]["state"], len(row["seal"]["value"])), ("holds", 64))
            self.assertEqual(row["record_digest"], "holds")
            self.assertEqual(row["signature"], {"required": False, "state": "unsigned", "signer": None, "detail": None})
            self.assertEqual((row["decided_by"], row["reason"], row["status"]), ("Camille Martin", "Agreed", "approved"))
            self.assertTrue(row["holds"])
        self.assertEqual([row["decided_at"][:10] for row in rows], ["2026-10-15", "2026-12-01"])
        self.assertIn("2 decision", self.export(output="again").stdout)

    def test_a_record_changed_after_it_was_exported_has_a_broken_seal_and_does_not_hold(self):
        self.two_decisions()
        path = self.root / ".openguildkit" / "decisions" / "first-task.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["decision"]["payload"]["reason"] = "Changed afterwards"
        path.write_text(json.dumps(record), encoding="utf-8")
        (self.root / ".openguildkit" / "decisions" / "notes.json").write_text("{broken", encoding="utf-8")
        self.export()
        rows = {row["record"]: row for row in lines(self.root / "dossier" / "decisions.jsonl")}
        first = rows[".openguildkit/decisions/first-task.json"]
        self.assertEqual((first["seal"]["state"], first["record_digest"], first["holds"]), ("broken", "broken", False))
        self.assertEqual(first["problem"]["code"], "decision-record-invalid")
        self.assertTrue(rows[".openguildkit/decisions/second-task.json"]["holds"])
        notes = rows[".openguildkit/decisions/notes.json"]
        self.assertEqual((notes["state"], notes["holds"], notes["decided_at"]), ("unreadable", False, None))

    def test_the_period_keeps_the_decisions_dated_inside_it(self):
        self.two_decisions()
        self.export("--since", "2026-10-01", "--until", "2026-10-31", output="october")
        self.assertEqual([row["task"] for row in lines(self.root / "october" / "decisions.jsonl")], ["first-task"])
        self.export("--since", "2026-11-01", output="later")
        self.assertEqual([row["task"] for row in lines(self.root / "later" / "decisions.jsonl")], ["second-task"])
        self.export("--until", "2026-12-01", output="last-day")
        self.assertEqual(len(lines(self.root / "last-day" / "decisions.jsonl")), 2)
        manifest = json.loads((self.root / "october" / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["period"], {"since": "2026-10-01", "until": "2026-10-31"})
        for bad in ("2026-13-01", "yesterday", "20261001"):
            self.assertIn("--since", self.export("--since", bad, code=1, output="never").stderr)
        self.assertFalse((self.root / "never").exists())

    def test_the_manifest_gives_the_sha256_of_each_file_the_version_the_commit_and_states_no_conformity(self):
        self.two_decisions()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "decisions")
        self.export()
        dossier = self.root / "dossier"
        manifest = json.loads((dossier / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["openguildkit"], package_version())
        self.assertEqual(manifest["project"]["commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(sorted(manifest["files"]), FILES)
        for name, entry in manifest["files"].items():
            data = (dossier / name).read_bytes()
            self.assertEqual((entry["sha256"], entry["bytes"]), (hashlib.sha256(data).hexdigest(), len(data)))
        self.assertEqual(manifest["profile"]["guard"], "enforce")
        self.assertEqual(manifest["profile"]["approvals"], "local")
        self.assertEqual(len(manifest["profile"]["rules_fingerprint"]), 64)
        self.assertEqual(manifest["state_files"][".openguildkit/project.json"],
                         hashlib.sha256((self.root / ".openguildkit" / "project.json").read_bytes()).hexdigest())
        self.assertIn("do not state that the project", manifest["statement"])
        self.assertFalse({"compliant", "conforms", "conformity", "passed"} & set(manifest))
        self.assertEqual((dossier / "controls.json").read_bytes(),
                         (Path(controls.__file__).parent / "registry" / "controls.json").read_bytes())

    def test_verify_exits_1_when_a_file_of_the_dossier_is_modified_missing_or_added(self):
        """Issue #482: nothing told an auditor whether the dossier handed over was the one exported."""
        self.two_decisions()
        self.export()
        dossier = self.root / "dossier"
        self.assertIn("5 files match", self.cli("evidence", "verify", "dossier").stdout)  # the name given to export
        ok = self.cli("evidence", "verify", dossier).stdout
        self.assertIn("5 files match", ok)
        self.assertIn(hashlib.sha256((dossier / "MANIFEST.json").read_bytes()).hexdigest(), ok)
        original = (dossier / "decisions.jsonl").read_bytes()
        (dossier / "decisions.jsonl").write_bytes(original.replace(b"Agreed", b"Waived"))
        self.assertIn("decisions.jsonl: changed", self.failure(dossier))
        (dossier / "decisions.jsonl").write_bytes(original)
        self.cli("evidence", "verify", dossier)
        (dossier / "alerts.jsonl").unlink()
        self.assertIn("alerts.jsonl: missing", self.failure(dossier))
        (dossier / "alerts.jsonl").write_text("", encoding="utf-8")
        (dossier / "extra.txt").write_text("added", encoding="utf-8")
        self.assertIn("extra.txt: not in the manifest", self.failure(dossier))

    def test_verify_refuses_a_manifest_that_names_a_file_outside_the_dossier(self):
        self.two_decisions()
        self.export()
        dossier = self.root / "dossier"
        manifest = json.loads((dossier / "MANIFEST.json").read_text(encoding="utf-8"))
        outside = self.work / "secret.txt"
        outside.write_text("not part of the dossier", encoding="utf-8")
        manifest["files"]["../secret.txt"] = {"sha256": hashlib.sha256(outside.read_bytes()).hexdigest(), "bytes": 1}
        write_json(dossier / "MANIFEST.json", manifest)
        self.assertIn("../secret.txt: not a file of the dossier", self.failure(dossier))
        (dossier / "MANIFEST.json").write_text("{broken", encoding="utf-8")
        self.assertIn("MANIFEST.json", self.cli("evidence", "verify", dossier, code=1).stderr)
        self.assertIn("MANIFEST.json", self.cli("evidence", "verify", self.work / "nothing", code=1).stderr)

    def test_export_reads_the_project_and_writes_only_a_new_folder_inside_it(self):
        self.two_decisions()
        before = snapshot(self.root)
        self.export()
        after = snapshot(self.root)
        self.assertEqual({name: value for name, value in after.items() if not name.startswith("dossier/")}, before)
        self.assertIn(".openguildkit/", self.export(code=1, output=".openguildkit/dossier").stderr)
        outside = self.work / "elsewhere"
        self.assertIn("outside the project", self.export(code=1, output=outside).stderr)
        self.assertFalse(outside.exists())
        self.assertIn("already holds files", self.export(code=1).stderr)
        self.assertEqual({name: value for name, value in snapshot(self.root).items() if not name.startswith("dossier/")},
                         before)

    def test_a_project_without_exported_decision_gets_a_dossier_with_empty_lists_and_says_why(self):
        self.project()
        result = self.export()
        self.assertIn("0 decision", result.stdout)
        dossier = self.root / "dossier"
        self.assertEqual((dossier / "decisions.jsonl").read_text(encoding="utf-8"), "")
        manifest = json.loads((dossier / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertTrue(any("signers-history.jsonl" in note for note in manifest["notes"]))
        self.cli("evidence", "verify", dossier)

    def test_profile_changes_and_alerts_of_the_period_are_listed_with_who_why_and_when(self):
        self.project()
        self.cli("profile", "set", "host", "claude-code", "--by", "CM", "--reason", "Docs needed",
                 env={"SOURCE_DATE_EPOCH": epoch(2026, 10, 20)})
        self.cli("alerts", "import", FIXTURES / "alerts" / "pip-audit.json", env={"SOURCE_DATE_EPOCH": epoch(2026, 10, 21)})
        self.cli("alerts", "set", "pypi:jinja2:ghsa-h5c8-rqwp-cp95", "--status", "confirmed", "--by", "CM",
                 env={"SOURCE_DATE_EPOCH": epoch(2026, 12, 2)})
        self.export("--since", "2026-10-01", "--until", "2026-10-31", output="october")
        changes = lines(self.root / "october" / "profile-changes.jsonl")
        self.assertEqual([(item["by"], item["on"], item["reason"]) for item in changes], [("CM", "2026-10-20", "Docs needed")])
        self.assertTrue(changes[0]["change"].startswith("set host"))
        alerts = lines(self.root / "october" / "alerts.jsonl")
        self.assertEqual({item["kind"] for item in alerts}, {"alert", "import"})
        # The register keeps the latest decision on an alert, not each step: October lists it as it stands now.
        self.assertEqual([(item["status"], item["by"]) for item in alerts if item["kind"] == "alert"], [("confirmed", "CM")])
        self.export("--since", "2026-12-01", output="december")
        self.assertEqual(lines(self.root / "december" / "profile-changes.jsonl"), [])
        self.assertEqual([item["kind"] for item in lines(self.root / "december" / "alerts.jsonl")], ["alert"])
        self.export("--since", "2027-01-01", output="next-year")
        self.assertEqual(lines(self.root / "next-year" / "alerts.jsonl"), [])

    @unittest.skipIf(shutil.which("ssh-keygen") is None, "needs ssh-keygen")
    def test_a_signed_project_shows_the_verified_signer_and_the_history_of_its_signers_file_without_the_keys(self):
        keys = self.work / "keys"
        keys.mkdir()
        for name in ("camille", "alex"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / name)], check=True)
        public = {name: (keys / f"{name}.pub").read_text(encoding="utf-8").strip() for name in ("camille", "alex")}
        (self.root / "allowed_signers").write_text(f"camille@example.org {public['camille']}\n", encoding="utf-8")
        self.project({"approval": {"mode": "signed", "allowed_signers": "allowed_signers",
                                   "approvers": ["camille@example.org", "alex@example.org"]}})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "signers")
        env = {"SOURCE_DATE_EPOCH": epoch(2026, 10, 15)}
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "signed-task", env=env)
        self.cli("task", "consult", "signed-task", "--answers", EXAMPLE / "answers.json", env=env)
        template = json.loads(self.cli("task", "template", "signed-task").stdout)
        write_json(self.work / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))})
        self.cli("task", "review", "signed-task", "--file", self.work / "review.json")
        self.cli("task", "decision-payload", "signed-task", "--by", "CM", "--reason", "Agreed", "--output", keys / "decision.json")
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / "camille"), "-n", "openguildkit-decision",
                        str(keys / "decision.json")], check=True, capture_output=True, stdin=subprocess.DEVNULL)
        with patch("sys.stdin.isatty", return_value=False):
            self.cli("task", "decide", "signed-task", "--approve", "--by", "CM", "--reason", "Agreed",
                     "--signer", "camille@example.org", "--signature", keys / "decision.json.sig", env=env)
        self.cli("task", "export", "signed-task", env=env)
        (self.root / "allowed_signers").write_text(f"camille@example.org {public['camille']}\n"
                                                   f"alex@example.org {public['alex']}\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "alex may sign")
        self.export()
        decision, = lines(self.root / "dossier" / "decisions.jsonl")
        self.assertEqual((decision["signature"]["required"], decision["signature"]["state"], decision["signature"]["signer"]),
                         (True, "verified", "camille@example.org"))
        history = lines(self.root / "dossier" / "signers-history.jsonl")
        self.assertEqual([item["principals"] for item in history],
                         [["camille@example.org"], ["alex@example.org", "camille@example.org"]])
        self.assertEqual([item["commit"] for item in history][-1], self.git("rev-parse", "HEAD"))
        text = (self.root / "dossier" / "signers-history.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(public["camille"].split()[1], text)
        record = self.root / ".openguildkit" / "decisions" / "signed-task.json"
        broken = json.loads(record.read_text(encoding="utf-8"))
        broken["decision"]["signature"] = broken["decision"]["signature"].replace("A", "B", 3)
        record.write_text(json.dumps(broken), encoding="utf-8")
        self.export(output="tampered")
        row, = lines(self.root / "tampered" / "decisions.jsonl")
        self.assertEqual(row["signature"]["state"], "not-verified")


if __name__ == "__main__":
    unittest.main()
