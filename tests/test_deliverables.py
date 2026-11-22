import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.deliverables import load_deliverables
from openguildkit.storage import write_json

from tests.support import CapturedCli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
MARKETING = ("landing-page-brief", "product-one-pager", "case-study", "newsletter-issue", "social-media-plan",
             "press-release", "webinar-plan", "pricing-page-brief", "competitive-battle-card")
BYPASS = """---
deliverable: "campaign-brief"
---

- Objective: grow.

<!--
- [x] claim-substantiated: x Evidence: none
- [x] consent-confirmed: x Evidence: none
- [x] measurement-ready: x Evidence: none
-->
"""


class DeliverableTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "p.json", {"name": "Portal", "stack": ["Python"], "tools": ["Brevo"]})
        self.run_cli("init", "--answers", self.root / "p.json")

    def approved_task(self, *consult_options):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "launch")
        self.run_cli("task", "consult", "launch", "--answers", EXAMPLE / "answers.json", *consult_options)
        template = json.loads(self.run_cli("task", "template", "launch")[0])
        write_json(self.root / "r.json", {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", "launch", "--file", self.root / "r.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="launch"):
            self.run_cli("task", "decide", "launch", "--approve", "--by", "Camille Martin", "--reason", "Launch agreed")

    def test_a_draft_is_written_only_inside_the_project_and_outside_the_state_folder(self):
        self.approved_task()
        common = ("deliverable", "new", "campaign-brief", "--task", "launch", "--tool", "Brevo", "--output")
        escape = f"../escape-{self.root.name}.md"  # one name per run: the parent folder is shared
        _, error = self.run_cli(*common, escape, code=1)
        self.assertIn(f"--output {escape} is outside the project", error)
        self.assertFalse((self.root / escape).exists())
        _, error = self.run_cli(*common, ".openguildkit/tasks/brief.md", code=1)
        self.assertIn("--output .openguildkit/tasks/brief.md is in .openguildkit/", error)
        self.assertFalse((self.root / ".openguildkit" / "tasks" / "brief.md").exists())
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        try:
            (self.root / "marketing").symlink_to(Path(outside.name), target_is_directory=True)
        except OSError as error:
            self.skipTest(f"This account cannot create symbolic links: {error}")
        _, error = self.run_cli(*common, "marketing/brief.md", code=1)
        self.assertIn("--output marketing/brief.md is outside the project", error)
        self.assertEqual(list(Path(outside.name).iterdir()), [])
        _, error = self.run_cli("deliverable", "check", "../escape-test.md", code=1)
        self.assertIn("deliverable check ../escape-test.md is outside the project", error)

    def test_a_draft_needs_no_tool(self):
        """A social media plan in a profile whose only tool is a newsletter tool: no tool to name."""
        self.approved_task()
        output, _ = self.run_cli("deliverable", "new", "social-media-plan", "--task", "launch", "--output", "plan.md")
        self.assertIn("Draft written to plan.md", output)
        self.assertNotIn("tool:", (self.root / "plan.md").read_text(encoding="utf-8"))
        self.assertNotIn("tool", json.loads(self.run_cli("task", "show", "launch")[0])["deliverables"][0])

    def test_bundled_templates_link_a_method_inputs_approvals_and_checks(self):
        templates = load_deliverables(load_catalog())
        brief = templates["campaign-brief"]
        self.assertEqual(brief["method"], "marketing-campaign-planning")
        self.assertTrue(any(item["data"] == "internal" for item in brief["inputs"]))
        self.assertTrue(brief["tool_actions"])

    def test_a_draft_starts_from_an_approved_task_with_an_approved_tool(self):
        output, _ = self.run_cli("deliverable", "show", "campaign-brief")
        self.assertIn("Needs your approval (task authorize --action send-message)", output)
        self.run_cli("task", "new", "Plan the spring campaign.", "--id", "draft-task")
        self.run_cli("deliverable", "new", "campaign-brief", "--task", "draft-task", "--tool", "Brevo", "--output", "brief.md", code=1)
        self.approved_task()
        _, error = self.run_cli("deliverable", "new", "campaign-brief", "--task", "launch", "--tool", "Mailchimp", "--output", "brief.md", code=1)
        self.assertIn("not an approved tool", error)
        output, _ = self.run_cli("deliverable", "new", "campaign-brief", "--task", "launch", "--tool", "Brevo", "--output", "brief.md")
        self.assertIn("Audience segment, described without personal data (internal data)", output)
        draft = (self.root / "brief.md").read_text(encoding="utf-8")
        # The draft may go to a client: the approval stays in the task record.
        for internal in ("approved_by", "decision_reason", "Camille Martin", "Launch agreed"):
            self.assertNotIn(internal, draft)
        self.assertEqual(json.loads(self.run_cli("task", "show", "launch")[0])["deliverables"][0]["tool"], "Brevo")

        problems, _ = self.run_cli("deliverable", "check", "brief.md", code=1)
        self.assertIn("placeholder", problems)
        self.assertIn("claim-substantiated", problems)
        filled = draft.replace("TODO: each source with its date or link", "Customer interviews, 2026-11-02").replace("TODO", "Filled.")
        for check in ("claim-substantiated", "consent-confirmed", "measurement-ready"):
            filled = filled.replace(f"- [ ] {check}:", f"- [x] {check}:").replace(f"{check}: ", f"{check}: ", 1)
        filled = "\n".join(line + "docs/evidence.md" if line.startswith("- [x] ") else line for line in filled.splitlines()) + "\n"
        (self.root / "brief.md").write_text(filled, encoding="utf-8")
        output, _ = self.run_cli("deliverable", "check", "brief.md")
        self.assertIn("Ready for review by marketing, communication, legal", output)
        old_draft = filled.replace("task: ", "approved_by: \"Camille Martin\"\ntask: ", 1)
        (self.root / "brief.md").write_text(old_draft, encoding="utf-8")
        problems, _ = self.run_cli("deliverable", "check", "brief.md", code=1)
        self.assertIn("approved_by", problems)

        self.run_cli("deliverable", "new", "social-media-plan", "--task", "launch", "--output", "social.md")
        self.assertNotIn("tool:", (self.root / "social.md").read_text(encoding="utf-8"))

    def test_an_approved_task_cannot_write_a_draft_outside_the_project_or_to_task_records(self):
        self.approved_task()
        escape = f"../{self.root.name}-outside.md"
        self.addCleanup((self.root / escape).unlink, missing_ok=True)
        for output, reason in (
            (escape, f"--output {escape} is outside the project"),
            (".openguildkit/draft.md", "--output .openguildkit/draft.md is in .openguildkit/"),
        ):
            with self.subTest(output=output):
                _, error = self.run_cli("deliverable", "new", "social-media-plan", "--task", "launch", "--output", output, code=1)
                self.assertIn(reason, error)
                self.assertFalse((self.root / output).exists())
        record = json.loads(self.run_cli("task", "show", "launch")[0])
        self.assertFalse(record.get("deliverables"))

    def filled(self, draft):
        """A draft with every placeholder, source and check completed."""
        text = draft.replace("TODO: each source with its date or link", "Customer interviews, 2026-11-02").replace("TODO", "Filled.")
        return "\n".join(line.replace("- [ ] ", "- [x] ") + "docs/evidence.md" if line.startswith("- [ ] ") else line
                         for line in text.splitlines()) + "\n"

    def test_the_audit_bypass_draft_is_refused_with_what_is_missing(self):
        (self.root / "bypass.md").write_text(BYPASS, encoding="utf-8")
        problems, _ = self.run_cli("deliverable", "check", "bypass.md", code=1)
        for section in ("Inputs", "Message", "Channels and calendar", "Measurement", "Consent and data", "Sources", "Checks"):
            self.assertIn(f'Section "{section}" is missing.', problems)
        self.assertIn("task", problems)
        self.assertNotIn("approved_by", problems)
        for check in ("claim-substantiated", "consent-confirmed", "measurement-ready"):
            self.assertIn(f"Check {check} is not ticked", problems)
        self.assertNotIn("Ready for review", problems)

    def test_an_empty_draft_is_refused(self):
        (self.root / "empty.md").write_text('---\ndeliverable: "support-article"\n---\n', encoding="utf-8")
        problems, _ = self.run_cli("deliverable", "check", "empty.md", code=1)
        self.assertIn('Section "Problem" is missing.', problems)

    def test_checks_ticked_in_a_comment_or_a_code_block_do_not_count(self):
        self.approved_task()
        self.run_cli("deliverable", "new", "support-article", "--task", "launch", "--tool", "Brevo", "--output", "article.md")
        draft = self.filled((self.root / "article.md").read_text(encoding="utf-8"))
        self.assertIn("Ready for review", self.write_and_check(draft, 0))
        ticked = [line for line in draft.splitlines() if line.startswith("- [x] ")]
        unticked = "\n".join(line.replace("- [x] ", "- [ ] ") if line in ticked else line for line in draft.splitlines()) + "\n"
        in_comment = unticked + "\n<!--\n" + "\n".join(ticked) + "\n-->\n"
        self.assertIn("Check steps-tested is not ticked", self.write_and_check(in_comment, 1))
        in_code = unticked + "\n```\n" + "\n".join(ticked) + "\n```\n"
        self.assertIn("Check no-personal-data is not ticked", self.write_and_check(in_code, 1))
        hidden_section = draft.replace("## Resolution", "<!-- ## Resolution -->")
        self.assertIn('Section "Resolution" is missing.', self.write_and_check(hidden_section, 1))
        empty_section = draft.replace("## When to contact support\n", "## When to contact support\n<!-- nothing -->\n## Ignored\n", 1)
        self.assertIn('Section "When to contact support" is empty.', self.write_and_check(empty_section, 1))

    def write_and_check(self, text, code):
        (self.root / "article.md").write_text(text, encoding="utf-8")
        return self.run_cli("deliverable", "check", "article.md", code=code)[0]

    def test_documentation_and_command_agree_on_the_task_states_accepted(self):
        self.run_cli("task", "new", "Plan the spring campaign.", "--id", "draft-task")
        _, error = self.run_cli("deliverable", "new", "campaign-brief", "--task", "draft-task", "--tool", "Brevo", "--output", "b.md", code=1)
        self.assertIn("approved or completed task", error)
        self.assertIn("approved or completed task", (REPO / "docs" / "deliverables.md").read_text(encoding="utf-8"))

    def test_marketing_templates_cover_the_work_of_a_software_publisher(self):
        catalog = load_catalog()
        templates = load_deliverables(catalog)
        listing, _ = self.run_cli("deliverable", "list")
        documented = (REPO / "docs" / "deliverables.md").read_text(encoding="utf-8")
        for template_id in MARKETING:
            with self.subTest(template=template_id):
                template = templates[template_id]
                self.assertIn(template_id, listing)
                self.assertIn(f"`{template_id}`", documented)
                self.assertGreaterEqual(len(template["sections"]), 3)
                self.assertGreaterEqual(len(template["checks"]), 2)
                self.assertTrue(set(template["brains"]) & {"marketing", "communication", "sales"})
                self.assertIn(template.get("method", "marketing-campaign-planning"), catalog["patterns"])
                cited = {source["url"] for pattern in catalog["patterns"].values() for source in pattern.get("sources", [])}
                self.assertLessEqual({source["url"] for source in template["sources"]}, cited)

    def test_market_templates_carry_the_dossier_the_task_was_consulted_with(self):
        (self.root / ".openguildkit" / "market").mkdir()
        shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", self.root / ".openguildkit" / "market")
        self.approved_task("--market", "support-portals")
        templates = load_deliverables(load_catalog())
        for template_id in ("landing-page-brief", "competitive-battle-card", "case-study", "social-media-plan"):
            self.assertTrue(templates[template_id].get("market"), template_id)
        self.run_cli("deliverable", "new", "competitive-battle-card", "--task", "launch", "--tool", "Brevo", "--output", "card.md")
        draft = (self.root / "card.md").read_text(encoding="utf-8")
        self.assertIn('market: "support-portals"', draft)
        self.assertIn(".openguildkit/market/support-portals.json", draft)

    def test_without_a_dossier_a_market_template_says_how_to_attach_one(self):
        self.approved_task()
        self.run_cli("deliverable", "new", "landing-page-brief", "--task", "launch", "--tool", "Brevo", "--output", "landing.md")
        draft = (self.root / "landing.md").read_text(encoding="utf-8")
        self.assertIn("--market", draft)
        self.assertNotIn("market:", draft.split("---", 2)[1])

    def test_utm_builds_a_campaign_link_that_follows_the_measurement_pack(self):
        output, _ = self.run_cli("deliverable", "utm", "--url", "https://www.example.test/pricing?plan=team#compare",
                                 "--campaign", " spring-launch ", "--source", "newsletter", "--medium", "email",
                                 "--content", "header-button")
        self.assertEqual(output.strip(), "https://www.example.test/pricing?plan=team&utm_source=newsletter&utm_medium=email"
                                         "&utm_campaign=spring-launch&utm_content=header-button#compare")
        common = ["deliverable", "utm", "--campaign", "spring-launch", "--source", "newsletter", "--medium", "email"]
        refused = {
            "http://www.example.test/": "https",
            "https:///pricing": "https",
            "https://www.example.test/?utm_source=x": "already carries",
            "https://www.example.test/?UTM_Medium=x": "already carries",
        }
        for url, message in refused.items():
            with self.subTest(url=url):
                _, error = self.run_cli(*common, "--url", url, code=1)
                self.assertIn(message, error)
        for flag, value, message in (("--campaign", "Spring-Launch", "lowercase"), ("--campaign", "spring launch", "lowercase"),
                                     ("--source", "camille@example.test", "personal data"), ("--medium", "", "lowercase")):
            with self.subTest(value=value):
                arguments = [item for item in common]
                arguments[arguments.index(flag) + 1] = value
                _, error = self.run_cli(*arguments, "--url", "https://www.example.test/", code=1)
                self.assertTrue(error.startswith("OpenGuildKit: "), error)
                self.assertIn(message, error)

    def test_templates_that_publish_a_link_point_to_the_utm_command(self):
        templates = load_deliverables(load_catalog())
        for template_id in ("campaign-brief", "landing-page-brief", "newsletter-issue", "social-media-plan", "webinar-plan"):
            with self.subTest(template=template_id):
                self.assertIn("openguildkit deliverable utm", json.dumps(templates[template_id]))
        self.assertIn("deliverable utm", (REPO / "docs" / "deliverables.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
