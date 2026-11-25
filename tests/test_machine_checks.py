"""Machine checks in the bundled catalog: which rules carry one, why the others need a person, and task verify."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import CatalogError, validate_entry, load_catalog
from openguildkit.patterns import is_stack_pattern
from openguildkit.rule_checks import evaluate_check
from openguildkit.storage import write_json

from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
# The regulation packs whose every rule carries a machine check or the reason only a person can verify it.
REGULATIONS = ("gdpr", "dora", "nis2", "iso-27001", "pci-dss", "eu-ai-act", "cyber-resilience-act",
               "european-accessibility-act")
# Regulation packs without a machine check: every rule names a record, a contract, a legal assessment or a
# behaviour that shows only in a running system, so its `manual` field says why a person verifies it.
PERSON_ONLY = {"gdpr", "dora", "eu-ai-act", "european-accessibility-act"}
# Stack packs without a machine check, with the reason: their rules are about behaviour under test, a running
# system or a judgement, and no literal text or field of a file says whether the rule is met.
STACK_EXCEPTIONS = {
    "api-design": "the contract and the status codes are judged against the behaviour of each endpoint",
    "chaosfolk-e2e": "the scenarios and replays are reviewed by a person and run by ChaosFolk itself",
    "go-database": "context, transactions and cleanup show in integration tests, not in a literal text",
    "kubernetes-gitops": "drift, pruning and recovery show in the controller's preview of a test environment",
    "mobile-accessibility": "labels, text sizes and targets are checked with VoiceOver, TalkBack and the scanners",
    "mobile-store-release": "store answers, rollouts and signing live in App Store Connect and Play Console",
    "playwright": "locators, isolation and flakiness are judged on the test code and the CI report",
    "postgresql": "constraints, migrations and query plans are judged on representative data",
    "pytest": "fixture scope and parameterization are judged on the tests themselves",
    "python": "style, typing and packaging run through the project's own formatter, type checker and build",
    "spring-boot": "settings, transaction boundaries and HTTP tests are judged in the application context",
    "terraform-kubernetes": "plans, state access and probes are reviewed in the infrastructure tools",
}


def pack(rules, pack_id="team-rules"):
    return {"id": pack_id, "title": "Team rules", "version": "1.0.0", "description": "Rules of the team.",
            "sources": [], "rules": rules}


def stack_packs(catalog):
    return sorted({pack_id for pattern in catalog["patterns"].values() if is_stack_pattern(pattern)
                   for pack_id in pattern["packs"]})


class ManualReasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_a_rule_names_why_only_a_person_can_verify_it_or_carries_a_check(self):
        validate_entry("packs", pack([{"id": "a", "instruction": "Ask the owner.", "verification": "Link it.",
                                        "manual": "The register lives outside the repository."}]))
        check = {"kind": "file-exists", "paths": ["SECURITY.md"]}
        with self.assertRaisesRegex(CatalogError, "manual"):
            validate_entry("packs", pack([{"id": "a", "check": check, "manual": "A person reads it."}]))
        for reason in ("", "Two\nlines", 3):
            with self.subTest(reason=reason), self.assertRaises(CatalogError):
                validate_entry("packs", pack([{"id": "a", "instruction": "Do it.", "verification": "Look.",
                                                "manual": reason}]))

    def test_every_regulation_rule_has_a_check_or_the_reason_a_person_verifies_it(self):
        for pack_id in REGULATIONS:
            for rule in self.catalog["packs"][pack_id]["rules"]:
                with self.subTest(pack=pack_id, rule=rule["id"]):
                    self.assertNotEqual("check" in rule, "manual" in rule)
            machine = [rule["id"] for rule in self.catalog["packs"][pack_id]["rules"] if "check" in rule]
            with self.subTest(pack=pack_id):
                self.assertEqual(not machine, pack_id in PERSON_ONLY, machine)

    def test_each_stack_pack_has_a_text_or_field_check_or_a_stated_exception(self):
        for pack_id in stack_packs(self.catalog):
            kinds = {rule["check"]["kind"] for rule in self.catalog["packs"][pack_id]["rules"] if "check" in rule}
            with self.subTest(pack=pack_id):
                if pack_id in STACK_EXCEPTIONS:
                    self.assertEqual(kinds, set(), "remove the exception: the pack has a check now")
                else:
                    self.assertTrue(kinds & {"text", "field"}, kinds)
        self.assertLessEqual(set(STACK_EXCEPTIONS), set(stack_packs(self.catalog)))
        for name in ("django", "express", "typescript", "fastapi", "nextjs"):
            self.assertNotIn(name, STACK_EXCEPTIONS)

    def test_the_catalog_keeps_at_least_twenty_machine_checks(self):
        checks = [f"{pack_id}/{rule['id']}" for pack_id, record in self.catalog["packs"].items()
                  for rule in record["rules"] if "check" in rule]
        self.assertGreaterEqual(len(checks), 20, checks)

    def test_owasp_asvs_names_identified_requirements_of_edition_5_0(self):
        record = self.catalog["packs"]["owasp-asvs"]
        text = " ".join(rule["instruction"] for rule in record["rules"])
        for chapter, requirements in (("V6 Authentication", ("6.2.1", "6.3.1")),
                                      ("V8 Authorization", ("8.2.1", "8.2.2", "8.3.1")),
                                      ("V2 Validation and Business Logic", ("2.2.1", "2.2.2"))):
            with self.subTest(chapter=chapter):
                self.assertIn(f"ASVS 5.0 chapter {chapter}", text)
                for requirement in requirements:
                    self.assertIn(requirement, text)
        urls = [source["url"] for source in record["sources"]]
        self.assertIn("https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x15-V6-Authentication.md", urls)


class StackCheckTests(unittest.TestCase):
    """Each stack check passes on a file that meets its rule and fails on one that does not."""

    CASES = {
        "typescript": ("tsconfig.json", '{"compilerOptions": {"strict": true}}', '{"compilerOptions": {"strict": false}}'),
        "django": ("shop/forms.py", 'fields = ["name", "email"]', 'fields = "__all__"'),
        "express": ("package.json", '{"engines": {"node": ">=22"}}', '{"name": "api"}'),
        "fastapi": ("app/main.py", "app = FastAPI(lifespan=lifespan)", '@app.on_event("startup")'),
        "nextjs": ("next.config.js", "module.exports = {}", "module.exports = {typescript: {ignoreBuildErrors: true}}"),
        "react": ("eslint.config.js", "rules: {'react-hooks/rules-of-hooks': 'error'}",
                  "rules: {'react-hooks/rules-of-hooks': 'off'}"),
        "vue": ("web/package.json", '{"scripts": {"type-check": "vue-tsc --noEmit"}}', '{"name": "web"}'),
        "angular": ("tsconfig.json", '{"angularCompilerOptions": {"strictTemplates": true}}',
                    '{"angularCompilerOptions": {"strictTemplates": false}}'),
        "rails": (".gitignore", "/config/master.key\n", "/tmp\n"),
        "laravel": ("app/Models/User.php", "protected $fillable = ['name'];", "protected $guarded = [];"),
        "symfony": (".env.prod", "APP_DEBUG=0\n", "APP_DEBUG=1\n"),
        "symfony-security": (".gitignore", "/.env.local\n", "/var/\n"),
        "container-images": ("Dockerfile", "FROM python:3.13-slim@sha256:abc", "FROM python:latest"),
        "gitlab-ci-security": (".gitlab-ci.yml", "image: node:22.11", "image: node:latest"),
        "github-actions-security": (".github/workflows/ci.yml", "permissions:\n  contents: read", "on: push"),
        "aws-iam": ("infra/main.tf", 'resource "aws_iam_role" "app" {}', 'resource "aws_iam_access_key" "ci" {}'),
        "android-app": ("app/src/main/AndroidManifest.xml", "<application />",
                        '<application android:usesCleartextTraffic="true" />'),
        "ios-app": ("App/Info.plist", "<dict></dict>", "<key>NSAllowsArbitraryLoads</key><true/>"),
        "aspnet-core": ("appsettings.json", '{"ConnectionStrings": {"Db": "Host=db"}}',
                        '{"ConnectionStrings": {"Db": "Host=db;Password=example"}}'),
        "pci-dss": (".pre-commit-config.yaml", "- repo: https://github.com/gitleaks/gitleaks", "repos: []"),
    }

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_each_stack_check_passes_and_fails_on_a_test_project(self):
        covered = set()
        for pack_id, (path, good, bad) in self.CASES.items():
            checks = [rule for rule in self.catalog["packs"][pack_id]["rules"] if "check" in rule]
            self.assertTrue(checks, pack_id)
            for content, expected in ((good, "passed"), (bad, "failed")):
                with self.subTest(pack=pack_id, expected=expected), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / path).parent.mkdir(parents=True, exist_ok=True)
                    (root / path).write_text(content, encoding="utf-8")
                    outcomes = {evaluate_check(root, rule["check"])["status"] for rule in checks}
                    self.assertIn(expected, outcomes)
            covered.add(pack_id)
        expected = set(stack_packs(self.catalog)) - set(STACK_EXCEPTIONS)
        self.assertEqual(expected - covered, set())


class DemoProjectTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    """On a demonstration project, task verify runs the machine checks of each active regulation pack."""

    PATTERNS = ["gdpr-personal-data", "dora-financial-entity", "nis2-essential-entity", "iso-27001-isms",
                "pci-dss-cardholder-data", "eu-ai-act-system", "cyber-resilience-act-product",
                "european-accessibility-act", "django", "node-express"]
    FILES = {
        "SECURITY.md": "Report vulnerabilities to security@example.test.",
        ".github/dependabot.yml": "version: 2\nupdates: []\n",
        ".github/workflows/ci.yml": "permissions:\n  contents: read\njobs:\n  scan:\n    steps:\n"
                                    "      - uses: gitleaks/gitleaks-action@v2\n      - run: syft . -o cyclonedx-json\n",
        "shop/forms.py": 'fields = ["name"]\n',
        "package.json": '{"name": "shop", "engines": {"node": ">=22"}}',
    }

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.catalog = load_catalog()

    def test_task_verify_runs_a_machine_check_of_each_active_regulation_pack(self):
        for name, content in self.FILES.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(content, encoding="utf-8")
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Shop", "stack": ["Python", "Django", "Express"], "packs": [],
                                                 "patterns": self.PATTERNS, "ask_every_rule": True, "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")), "data": "personal"}
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK))
        review = {"consultation_id": template["consultation_id"],
                  **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille Martin", "--reason", "Agreed")
        self.run_cli("task", "verify", TASK)
        recorded = {item["check"]: item for item in json.loads(self.run_cli("task", "show", TASK))["result"]["checks"]}
        for pack_id in REGULATIONS:
            machine = [f"rule:{pack_id}/{rule['id']}" for rule in self.catalog["packs"][pack_id]["rules"]
                       if "check" in rule]
            with self.subTest(pack=pack_id):
                if pack_id in PERSON_ONLY:
                    self.assertEqual(machine, [])
                    continue
                self.assertTrue(machine)
                for check_id in machine:
                    self.assertEqual(recorded[check_id]["status"], "passed", recorded[check_id])
                    self.assertTrue(recorded[check_id]["evidence"])
        for check_id in ("rule:django/list-form-fields-explicitly", "rule:express/declare-node-engines"):
            self.assertEqual(recorded[check_id]["status"], "passed", recorded[check_id])


if __name__ == "__main__":
    unittest.main()
