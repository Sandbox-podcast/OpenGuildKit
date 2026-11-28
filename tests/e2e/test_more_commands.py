"""Commands that only had unit tests of their functions, run here through the CLI.

task deliberate, respond, blockers, clear and waive, storybook compose and
deliverable list: each test checks the output and the exit code.
"""

import copy
import json
import os
import runpy
import shutil
import subprocess
import unittest
from datetime import timedelta

from openguildkit import clock
from tests.e2e.test_cli_flow import EXAMPLE, TASK_ID, CliTestCase


class ReviewedTaskTestCase(CliTestCase):
    def review_with_blockers(self, phase=None):
        """The example review with a blocking security board, recorded through the CLI."""
        review = self.example_review()
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"]["verdict"] = "block"
        security["challenge"]["blockers"] = [
            {"finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
             "clears_when": "An automated test with two synthetic accounts passes."},
            {"finding": "Retention of request history is not decided.", "owner": "Data protection officer",
             "clears_when": "The retention period is recorded."},
        ]
        if phase:
            for blocker in security["challenge"]["blockers"]:
                blocker["phase"] = phase
        self.run_cli("task", "review", TASK_ID, "--file", self.write_json("review.json", review))


class DeliberationCommandTests(ReviewedTaskTestCase):
    def test_deliberate_prints_the_objections_and_respond_records_the_answers(self):
        self.consult_example()
        self.run_cli("task", "deliberate", TASK_ID, expect=1)
        self.record_example_review()
        request = json.loads(self.run_cli("task", "deliberate", TASK_ID).stdout)
        self.assertIn("security-to-legal", [item["id"] for item in request["objections"]])
        payload = copy.deepcopy(request["template"])
        for response in payload["responses"]:
            response.update(position="maintain", response="Our evidence still holds.", evidence_refs=[1])
        incomplete = self.run_cli("task", "respond", TASK_ID, "--file", self.write_json("d.json", payload), expect=1)
        self.assertIn("decision the responsible person", incomplete.stderr)
        self.assertTrue(incomplete.stderr.startswith("OpenGuildKit: "))
        payload["decision_needed"] = "Choose between shipping read-only now or after the access tests."
        result = self.run_cli("task", "respond", TASK_ID, "--file", self.write_json("d.json", payload))
        self.assertEqual(result.stdout.strip(), f"0 resolved, {len(request['objections'])} open")
        self.assertIn("An objection is resolved when one of the two boards concedes, or when both amend", result.stderr)
        self.assertEqual(self.task_record()["deliberation"]["decision_needed"], payload["decision_needed"])
        self.assertIn(payload["decision_needed"], self.run_cli("task", "challenge", TASK_ID).stdout)


class BlockerCommandTests(ReviewedTaskTestCase):
    @unittest.skipUnless(shutil.which("ssh-keygen") and shutil.which("git"), "needs ssh-keygen and git")
    def test_signed_verification_blockers_are_reported_and_clear_with_the_named_signature(self):
        principal = "camille@example.org"
        key = self.project / "synthetic-test-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        allowed = self.project / "allowed_signers"
        allowed.write_text(f"{principal} {key.with_suffix('.pub').read_text(encoding='utf-8')}", encoding="utf-8")
        # Signatures are verified against the allowed signers file as Git holds it at HEAD.
        identity = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
                    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}
        for args in (("init", "-q"), ("add", allowed.name), ("commit", "-q", "-m", "signers")):
            subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True,
                           env={**os.environ, **identity})

        profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
        profile.update(checks=[], approval={"mode": "signed", "allowed_signers": allowed.name, "approvers": [principal]})
        self.run_cli("init", "--answers", self.write_json("profile.json", profile))
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")
        self.review_with_blockers(phase="verification")

        def sign(payload):
            subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", "openguildkit-decision",
                            str(payload)], check=True)
            return ("--signature", payload.with_suffix(".json.sig"), "--signer", principal)

        approval = self.project / "approval.json"
        reason = "Scope agreed"
        self.run_cli("task", "decision-payload", TASK_ID, "--by", principal, "--reason", reason, "--output", approval)
        _, approval_signature, _, signer = sign(approval)
        rehearsal = runpy.run_path(str(EXAMPLE.parent / "host-validation" / "rehearse.py"))
        self.assertTrue(rehearsal["approve"](self.project, TASK_ID, by=principal, reason=reason,
                                             signature=approval_signature, signer=signer))
        self.assertIn("Verification blocker security:1 is open", self.run_cli("task", "verify", TASK_ID).stdout)
        self.assertIn("Verification blocker security:1 is open", self.run_cli("task", "complete", TASK_ID, expect=1).stderr)

        payload = self.project / "clearance.json"
        clear = ("task", "clear", TASK_ID, "security:1", "--by", principal, "--evidence", "AGENTS.md")
        supports = ("--supports", "The test with two accounts passed.")
        refused = self.run_cli(*clear, *supports, expect=1)
        self.assertIn("requires a signed clearance", refused.stderr)
        self.run_cli(*clear, *supports, "--payload", payload)
        signature = sign(payload)
        tampered = self.run_cli(*clear, "--supports", "Different evidence.", *signature, expect=1)
        self.assertIn("does not verify", tampered.stderr)
        self.run_cli(*clear, *supports, *signature)
        self.assertEqual(self.task_record()["verification_blocker_resolutions"]["security:1"]["signer"], principal)
        verified = self.run_cli("task", "verify", TASK_ID)
        self.assertNotIn("Verification blocker security:1", verified.stdout)
        self.assertIn("Verification blocker security:2 is open", verified.stdout)

    def test_blockers_lists_each_blocker_and_clear_records_its_evidence(self):
        self.consult_example()
        self.review_with_blockers()
        listing = self.run_cli("task", "blockers", TASK_ID).stdout
        self.assertIn("security:1 [open] No test proves a user cannot read another user's request.", listing)
        self.assertIn("owner: Security lead; clears when: An automated test with two synthetic accounts passes.", listing)
        items = json.loads(self.run_cli("task", "blockers", TASK_ID, "--json").stdout)
        self.assertEqual([item["id"] for item in items], ["security:1", "security:2"])

        unknown = self.run_cli("task", "clear", TASK_ID, "security:9", "--by", "Alex", "--evidence", "x", "--supports", "y",
                               expect=1)
        self.assertTrue(unknown.stderr.startswith("OpenGuildKit: "))
        missing_file = self.run_cli("task", "clear", TASK_ID, "security:1", "--by", "Alex", "--evidence",
                                    "tests/test_access.py", "--supports", "Cross-account access is refused.", expect=1)
        self.assertIn("existing file or folder of the project, or an https link", missing_file.stderr)
        (self.project / "tests").mkdir()
        (self.project / "tests" / "test_access.py").write_text("def test_access(): pass\n", encoding="utf-8")
        clear = ("task", "clear", TASK_ID, "security:1", "--by", "Alex", "--evidence", "tests/test_access.py",
                 "--supports", "Cross-account access is refused.")
        refused = self.run_cli(*clear, expect=1)
        self.assertIn("Clearing a blocker is the person's act", refused.stderr)
        self.assertIn("security:1 [open]", self.run_cli("task", "blockers", TASK_ID).stdout)
        if os.name != "posix":
            return
        code, _, stderr = self.in_terminal(clear, "wrong-id")
        self.assertTrue(stderr.strip().endswith("OpenGuildKit [OGK-CORE-013]: Clearing cancelled."), stderr)
        code, stdout, stderr = self.in_terminal(clear, TASK_ID)
        self.assertEqual((code, stdout.strip()), (0, "cleared"), stderr)
        listing = self.run_cli("task", "blockers", TASK_ID).stdout
        self.assertIn("security:1 [cleared by Alex]", listing)
        self.assertNotIn("without a terminal", listing)
        self.assertIn("security:2 [open]", listing)
        code, _, stderr = self.in_terminal(("task", "clear", TASK_ID, "security:1", "--by", "Bob", "--evidence",
                                            "AGENTS.md", "--supports", "Something else."), TASK_ID)
        self.assertEqual(code, 1)
        self.assertIn("already has a resolution: cleared by Alex on ", stderr)
        self.assertIn("security:1 [cleared by Alex]", self.run_cli("task", "blockers", TASK_ID).stdout)
        missing = self.run_cli("task", "clear", TASK_ID, "security:2", "--by", "Alex", expect=2)
        self.assertIn("--evidence", missing.stderr)

    def test_a_task_without_blockers_says_so(self):
        self.consult_example()
        self.record_example_review()
        self.assertEqual(self.run_cli("task", "blockers", TASK_ID).stdout.strip(), "No blockers.")
        self.assertEqual(json.loads(self.run_cli("task", "blockers", TASK_ID, "--json").stdout), [])


class WaiverCommandTests(ReviewedTaskTestCase):
    def setUp(self):
        super().setUp()
        profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
        profile["waivers"] = {"allowed_by": ["Camille Martin"], "max_days": 30}
        self.run_cli("init", "--answers", self.write_json("profile.json", profile))
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")
        self.review_with_blockers()
        self.until = (clock.real_today() + timedelta(days=10)).isoformat()

    def waive(self, by="Camille Martin"):
        return ("task", "waive", TASK_ID, "security:2", "--by", by, "--reason", "Internal pilot only",
                "--scope", "Internal pilot", "--until", self.until)

    def test_a_waiver_without_a_terminal_is_refused(self):
        refused = self.run_cli(*self.waive(), expect=1)
        self.assertEqual(refused.stderr.strip(), "OpenGuildKit: A waiver needs a person at an interactive terminal.")
        self.assertIn("security:2 [open]", self.run_cli("task", "blockers", TASK_ID).stdout)

    @unittest.skipUnless(os.name == "posix", "the typed confirmation needs a pseudo-terminal, available on Linux and macOS")
    def test_a_person_at_a_terminal_waives_within_the_policy(self):
        code, _, stderr = self.in_terminal(self.waive(by="Sam"), TASK_ID)
        self.assertEqual(code, 1)
        self.assertIn("cannot grant waivers", stderr)
        code, _, stderr = self.in_terminal(self.waive(), "wrong-id")
        self.assertEqual(code, 1)
        self.assertTrue(stderr.strip().endswith("OpenGuildKit [OGK-CORE-013]: Waiver cancelled."), stderr)
        code, stdout, stderr = self.in_terminal(self.waive(), TASK_ID)
        self.assertEqual((code, stdout.strip()), (0, "waived"), stderr)
        self.assertIn("security:2 [waived by Camille Martin]", self.run_cli("task", "blockers", TASK_ID).stdout)

class StorybookComposeCommandTests(CliTestCase):
    def test_compose_adds_updates_and_removes_a_ref(self):
        self.init_example()
        missing = self.run_cli("storybook", "compose", "company", "--url", "https://design.example.test", expect=1)
        self.assertIn("No Storybook configuration in .storybook", missing.stderr)
        (self.project / ".storybook").mkdir()
        (self.project / ".storybook" / "main.ts").write_text("export default {};\n", encoding="utf-8")
        added = self.run_cli("storybook", "compose", "company", "--url", "https://design.example.test/", "--title",
                             "Example design system").stdout
        self.assertIn(".storybook/openguildkit-refs.json: company (https://design.example.test)", added)
        self.assertIn("Add these lines to .storybook/main.ts", added)
        refs = json.loads((self.project / ".storybook" / "openguildkit-refs.json").read_text(encoding="utf-8"))
        self.assertEqual(refs, {"company": {"title": "Example design system", "url": "https://design.example.test"}})
        as_json = json.loads(self.run_cli("storybook", "compose", "brand", "--url", "https://brand.example.test",
                                          "--json").stdout)
        self.assertEqual(sorted(as_json["refs"]), ["brand", "company"])
        self.assertIn("https", self.run_cli("storybook", "compose", "brand", "--url", "ftp://brand.example.test",
                                            expect=1).stderr)
        removed = self.run_cli("storybook", "compose", "brand", "--remove").stdout
        self.assertNotIn("brand", removed)
        self.run_cli("storybook", "compose", "brand", "--remove", expect=1)

    def test_compose_refuses_a_url_with_a_password_or_a_token(self):
        self.init_example()
        (self.project / ".storybook").mkdir()
        (self.project / ".storybook" / "main.ts").write_text("export default {};\n", encoding="utf-8")
        password, token = "S3cr3t" + "Pw", "abcd1234" + "efgh5678"
        for url, message in ((f"https://design.example.com/?access_token={token}", "the link must carry no user name, password or token"),
                             (f"https://design.example.com/?api_key={token}", "the link must carry no user name, password or token"),
                             (f"https://admin:{password}@design.example.com/?x=1", "Remove the user name and password")):
            with self.subTest(url=url[:30]):
                refused = self.run_cli("storybook", "compose", "company", "--url", url, "--title", "Acme", expect=1)
                self.assertIn(message, refused.stderr)
                for secret in (password, token):
                    self.assertNotIn(secret, refused.stderr)
        self.assertFalse((self.project / ".storybook" / "openguildkit-refs.json").exists())


class DeliverableListCommandTests(CliTestCase):
    def test_list_shows_every_template_with_its_reviewers(self):
        self.init_example()
        listing = self.run_cli("deliverable", "list").stdout.splitlines()
        ids = [line.split()[0] for line in listing]
        self.assertIn("campaign-brief", ids)
        self.assertEqual(ids, sorted(ids))
        for line in listing:
            self.assertRegex(line, r"\[[a-z-]+(, [a-z-]+)*\]$")
        shown = self.run_cli("deliverable", "show", ids[0]).stdout
        self.assertIn("Checks:", shown)


if __name__ == "__main__":
    unittest.main()
