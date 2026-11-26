"""Mainstream web, mobile and cloud stacks get their own stack pattern, from the answers or from the repository."""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.detect import components_for_profile, detect_stack
from openguildkit.project import profile_recommendations, resolved_profile, validate_profile
from openguildkit.rule_checks import evaluate_check

STACKS = {
    "django": ["Django", "Python", "MySQL"],
    "rails": ["Rails", "PostgreSQL"],
    "node-express": ["Vue", "Node.js", "Express", "MongoDB"],
    "vue": ["Vue", "Node.js", "Express", "MongoDB"],
    "ios-swift": ["Swift", "iOS"],
    "android-kotlin": ["Kotlin", "Android"],
    "kotlin-ktor": ["Kotlin 2.1", "Ktor 3.1"],
    "laravel": ["Laravel", "PHP"],
    "symfony": ["Symfony", "PHP"],
    "angular": ["Angular", "NestJS"],
    "rust-cargo": ["Rust 1.82", "Axum 0.8", "Tokio 1"],
    "svelte": ["Svelte 5"],
    "sveltekit": ["Svelte 5", "SvelteKit 2"],
    "react-native": ["React 19", "React Native 0.81"],
    "expo": ["Expo 54", "React Native 0.81"],
    "flutter": ["Dart 3.5", "Flutter 3.22"],
    "gitlab-ci-security": ["AWS", "GitLab CI", "Docker"],
    "docker-images": ["AWS", "GitLab CI", "Docker"],
    "aws-iam": ["AWS", "GitLab CI", "Docker"],
}
PACKS = {
    "django": "django", "rails": "rails", "node-express": "express", "vue": "vue", "angular": "angular",
    "laravel": "laravel", "symfony": "symfony", "ios-swift": "ios-app", "android-kotlin": "android-app",
    "kotlin-ktor": "ktor-server", "rust-cargo": "rust-cargo", "svelte": "svelte", "sveltekit": "sveltekit",
    "react-native": "react-native", "expo": "expo", "flutter": "flutter",
    "gitlab-ci-security": "gitlab-ci-security", "docker-images": "container-images", "aws-iam": "aws-iam",
}
GENERIC_PACKS = {"secure-sdlc", "api-design", "typescript", "python"}
# A pattern that activates more than one pack of its own: the security configuration of an application has its own.
EXTRA_PACKS = {"symfony": ["symfony-security"]}
# The machine checks of the Symfony packs, by PACK/RULE: a file that meets the rule and one that does not.
SYMFONY_CHECKS = {
    "symfony-security/keep-local-secrets-out-of-git": (
        ".gitignore", "/.env.local\n/.env.*.local\n", "/var/\n/vendor/\n"),
    "symfony-security/deny-when-no-voter-decides": (
        "config/packages/security.yaml", "security:\n    access_decision_manager:\n        strategy: unanimous\n",
        "security:\n    access_decision_manager:\n        allow_if_all_abstain: true\n"),
    "symfony/keep-debug-off-in-production": (".env.prod", "APP_ENV=prod\nAPP_DEBUG=0\n", "APP_ENV=prod\nAPP_DEBUG=1\n"),
}


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


REPOSITORIES = {
    "django": {
        "manage.py": 'import os\nos.environ.setdefault("DJANGO_SETTINGS_MODULE", "shop.settings")\n'
                     "from django.core.management import execute_from_command_line\n",
    },
    "rails": {
        "Gemfile": 'source "https://rubygems.org"\nruby "3.3.4"\ngem "rails", "~> 8.1.0"\ngem "pg", "~> 1.5"\n',
    },
    "node-express": {"package.json": {"dependencies": {"express": "^5.1.0"}, "engines": {"node": ">=22"}}},
    "vue": {"package.json": {"dependencies": {"vue": "^3.5.0"}}},
    "angular": {"package.json": {"dependencies": {"@angular/core": "^22.0.0"}}},
    "laravel": {"composer.json": {"require": {"php": "^8.3", "laravel/framework": "^13.0"}}},
    "symfony": {"composer.json": {"require": {"php": ">=8.3", "symfony/framework-bundle": "7.2.*"}}},
    "rust-cargo": {
        "Cargo.toml": '[package]\nname = "orders"\nedition = "2021"\nrust-version = "1.82"\n\n'
                      '[dependencies]\naxum = "0.8"\ntokio = { version = "1", features = ["full"] }\n',
    },
    "svelte": {"package.json": {"devDependencies": {"svelte": "^5.0.0"}}},
    "sveltekit": {"package.json": {"devDependencies": {"svelte": "^5.0.0", "@sveltejs/kit": "^2.20.0"}}},
    "react-native": {"package.json": {"dependencies": {"react": "19.1.0", "react-native": "0.81.4"}}},
    "expo": {"package.json": {"dependencies": {"expo": "~54.0.0", "react": "19.1.0", "react-native": "0.81.4"}}},
    "flutter": {"pubspec.yaml": "name: shop\nenvironment:\n  sdk: ^3.5.0\ndependencies:\n  flutter:\n    sdk: flutter\n"},
    "ios-swift": {
        "Shop.xcodeproj/project.pbxproj": "{ buildSettings = { SDKROOT = iphoneos; SWIFT_VERSION = 6.0; }; }\n",
    },
    "android-kotlin": {
        "app/build.gradle.kts": 'plugins {\n  id("com.android.application")\n  id("org.jetbrains.kotlin.android")\n}\n',
    },
    "kotlin-ktor": {
        "build.gradle.kts": 'plugins {\n  kotlin("jvm") version "2.1.0"\n  id("io.ktor.plugin") version "3.1.0"\n}\n',
    },
    "gitlab-ci-security": {".gitlab-ci.yml": "test:\n  script: make test\n"},
    "docker-images": {"Dockerfile": "FROM python:3.13-slim\nUSER app\n"},
    "aws-iam": {"infra/main.tf": 'provider "aws" {\n  region = "eu-west-3"\n}\n'},
}


class StackPatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def matched(self, answers: dict) -> set[str]:
        plan = profile_recommendations({"name": "Project", "roles": ["engineering"], **answers}, self.catalog)
        return {pattern["id"] for pattern in plan["matched"]}

    def test_each_mainstream_stack_gets_its_pattern_from_the_answers(self):
        for pattern_id, stack in STACKS.items():
            with self.subTest(pattern=pattern_id, stack=stack):
                self.assertIn(pattern_id, self.matched({"stack": stack}))

    def test_each_pattern_activates_its_own_stack_pack(self):
        for pattern_id, pack_id in PACKS.items():
            with self.subTest(pattern=pattern_id):
                pattern = self.catalog["patterns"][pattern_id]
                self.assertIn(pack_id, pattern["packs"])
                self.assertTrue(pattern["sources"])

    def test_symfony_activates_its_two_packs_and_only_for_a_symfony_application(self):
        pattern = self.catalog["patterns"]["symfony"]
        self.assertEqual(pattern["packs"], ["symfony", *EXTRA_PACKS["symfony"]])
        self.assertEqual(pattern["match"]["stack"], [["symfony"]])
        self.assertIn("symfony", self.matched({"stack": ["Symfony 7.2", "PHP 8.3"]}))
        self.assertIn("symfony", self.matched({"stack": ["Symfony 3.4.*"]}))
        self.assertNotIn("symfony", self.matched({"stack": ["Laravel", "PHP"]}))
        self.assertNotIn("laravel", self.matched({"stack": ["Symfony", "PHP"]}))
        profile = validate_profile({"name": "Shop", "stack": ["Symfony 7.2", "PHP 8.3"]}, self.catalog)
        packs = resolved_profile(profile, self.catalog)["packs"]
        self.assertLessEqual({"symfony", "symfony-security"}, set(packs))

    def test_each_symfony_check_passes_on_a_file_that_meets_its_rule_and_fails_on_one_that_does_not(self):
        for rule_path, (path, good, bad) in SYMFONY_CHECKS.items():
            pack_id, rule_id = rule_path.split("/")
            rule = next(rule for rule in self.catalog["packs"][pack_id]["rules"] if rule["id"] == rule_id)
            for content, expected in ((good, "passed"), (bad, "failed")):
                with self.subTest(rule=rule_path, expected=expected), tempfile.TemporaryDirectory() as directory:
                    write(Path(directory), path, content)
                    self.assertEqual(evaluate_check(Path(directory), rule["check"])["status"], expected)

    def test_mobile_apps_get_accessibility_and_store_release_packs(self):
        for stack in (["Swift", "iOS"], ["Kotlin", "Android"]):
            with self.subTest(stack=stack):
                profile = validate_profile({"name": "App", "stack": stack}, self.catalog)
                packs = resolved_profile(profile, self.catalog)["packs"]
                self.assertIn("mobile-accessibility", packs)
                self.assertIn("mobile-store-release", packs)

    def test_a_server_side_swift_or_plain_kotlin_project_gets_no_mobile_rules(self):
        self.assertNotIn("ios-swift", self.matched({"stack": ["Swift", "Vapor"]}))
        self.assertNotIn("android-kotlin", self.matched({"stack": ["Kotlin", "Spring Boot"]}))
        self.assertNotIn("android-kotlin", self.matched({"stack": ["Kotlin", "Ktor"]}))

    def test_a_ktor_server_gets_its_own_pattern_without_the_spring_boot_or_android_ones(self):
        self.assertLessEqual({"kotlin-ktor"}, self.matched({"stack": ["Ktor 3.1"]}))
        self.assertLessEqual({"kotlin-ktor"}, self.matched({"stack": ["Kotlin", "Ktor"]}))
        self.assertLessEqual({"kotlin-ktor"}, self.matched({"stack": ["Kotlin", "Ktor Server 3"]}))
        self.assertNotIn("java-spring-boot", self.matched({"stack": ["Kotlin", "Ktor"]}))
        for stack in (["Kotlin", "Spring Boot"], ["Kotlin", "Android"], ["Kotlin"], ["Java", "Spring Boot"]):
            with self.subTest(stack=stack):
                self.assertNotIn("kotlin-ktor", self.matched({"stack": stack}))

    def test_a_ktor_server_gets_the_kotlin_and_ktor_packs_on_top_of_the_http_contract_rules(self):
        profile = validate_profile({"name": "Service", "stack": ["Kotlin", "Ktor"]}, self.catalog)
        packs = resolved_profile(profile, self.catalog)["packs"]
        self.assertLessEqual({"kotlin-service", "ktor-server", "api-design"}, set(packs))
        self.assertNotIn("spring-boot", packs)
        self.assertNotIn("android-app", packs)
        self.assertIn("api-design", self.catalog["packs"]["ktor-server"]["depends_on"])
        pattern = self.catalog["patterns"]["kotlin-ktor"]
        for neighbour in ("java-spring-boot", "android-kotlin"):
            self.assertIn(neighbour, pattern["description"])
        self.assertTrue(set(pattern["packs"]).isdisjoint(self.catalog["patterns"]["java-spring-boot"]["packs"]))
        self.assertTrue(set(pattern["packs"]).isdisjoint(self.catalog["patterns"]["android-kotlin"]["packs"]))

    def test_new_rules_are_actionable_sourced_and_not_generic(self):
        generic = {
            rule["instruction"] for pack_id in GENERIC_PACKS for rule in self.catalog["packs"][pack_id]["rules"]
        }
        new_packs = {*PACKS.values(), *(pack for packs in EXTRA_PACKS.values() for pack in packs),
                     "mobile-accessibility", "mobile-store-release", "kotlin-service", "rust-dependencies"}
        new_packs |= {"svelte", "sveltekit", "react-native", "expo", "flutter"}
        for pack_id in sorted(new_packs):
            with self.subTest(pack=pack_id):
                pack = self.catalog["packs"][pack_id]
                self.assertTrue(pack["description"].startswith("For "))
                self.assertGreaterEqual(len(pack["sources"]), 1)
                self.assertTrue(4 <= len(pack["rules"]) <= 7)
                for rule in pack["rules"]:
                    self.assertTrue(rule["instruction"].strip() and rule["verification"].strip())
                    self.assertNotIn(rule["instruction"], generic)

    def test_the_rust_pattern_reaches_both_cargo_packs_from_the_language_alone(self):
        for stack in (["Rust"], ["Rust 1.75"], ["rust", "Actix Web 4"]):
            with self.subTest(stack=stack):
                self.assertIn("rust-cargo", self.matched({"stack": stack}))
        # The edition is a line of its own in the detected stack, not the language.
        self.assertNotIn("rust-cargo", self.matched({"stack": ["Rust edition 2021"]}))
        self.assertNotIn("rust-cargo", self.matched({"stack": ["Python", "FastAPI"]}))
        self.assertEqual(self.catalog["patterns"]["rust-cargo"]["packs"], ["rust-cargo", "rust-dependencies"])

    def test_the_svelte_and_mobile_cross_platform_patterns_match_only_their_own_stack(self):
        # React web, Vue, a Dart package and a plain Node.js project get none of them.
        for stack in (["React 19", "Next.js 15"], ["Vue 3"], ["Dart 3.5"], ["Node.js 22", "TypeScript"]):
            with self.subTest(stack=stack):
                self.assertFalse({"svelte", "sveltekit", "react-native", "expo", "flutter"} & self.matched({"stack": stack}))
        self.assertNotIn("sveltekit", self.matched({"stack": ["Svelte 5"]}))
        self.assertNotIn("expo", self.matched({"stack": ["React Native 0.81"]}))
        # A framework stands for its platform: SvelteKit brings the Svelte rules, Expo the React Native ones.
        self.assertIn("svelte", self.matched({"stack": ["SvelteKit 2"]}))
        self.assertIn("react-native", self.matched({"stack": ["Expo 54"]}))
        # A React Native app keeps the Rules of React, which hold for every React renderer.
        self.assertIn("react-web", self.matched({"stack": ["React 19", "React Native 0.81"]}))

    def test_the_cross_platform_mobile_apps_get_the_mobile_packs_and_their_framework_packs(self):
        for stack, own in ((["React Native 0.81"], {"react-native", "react"}),
                           (["Expo 54"], {"expo", "react-native", "react"}),
                           (["Flutter 3.22"], {"flutter"}),
                           (["SvelteKit 2"], {"sveltekit", "svelte"})):
            with self.subTest(stack=stack):
                profile = validate_profile({"name": "App", "stack": stack}, self.catalog)
                packs = set(resolved_profile(profile, self.catalog)["packs"])
                self.assertLessEqual(own, packs)
                mobile = {"mobile-accessibility", "mobile-store-release"}
                self.assertEqual(mobile <= packs, stack[0] != "SvelteKit 2")

    def test_framework_packs_reuse_the_generic_packs_instead_of_repeating_them(self):
        self.assertIn("python", self.catalog["packs"]["django"]["depends_on"])
        self.assertIn("typescript", self.catalog["packs"]["angular"]["depends_on"])
        self.assertIn("api-design", self.catalog["packs"]["express"]["depends_on"])


class StackDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def detect(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, content in files.items():
                write(root, relative, content)
            return detect_stack(root)

    def test_a_repository_of_each_stack_is_recommended_its_pattern(self):
        for pattern_id, files in REPOSITORIES.items():
            with self.subTest(pattern=pattern_id):
                components = components_for_profile(self.detect(files))
                self.assertTrue(components, "nothing detected")
                answers = {"name": "Repository", "roles": ["engineering"], "components": components}
                plan = profile_recommendations(answers, self.catalog)
                self.assertIn(pattern_id, {pattern["id"] for pattern in plan["matched"]})

    def test_versions_and_evidence_come_from_the_manifests(self):
        stacks = {
            "rails": {"Ruby 3.3.4", "Rails ~> 8.1.0"},
            "laravel": {"PHP ^8.3", "Laravel ^13.0"},
            "symfony": {"PHP >=8.3", "Symfony 7.2.*"},
            "rust-cargo": {"Rust 1.82", "Rust edition 2021", "Axum 0.8", "Tokio 1"},
            "ios-swift": {"Swift 6.0", "iOS"},
            "android-kotlin": {"Android", "Kotlin"},
            "kotlin-ktor": {"Kotlin 2.1.0", "Ktor 3.1.0"},
            "django": {"Python", "Django"},
            "sveltekit": {"Svelte ^5.0.0", "SvelteKit ^2.20.0"},
            "expo": {"Expo ~54.0.0", "React 19.1.0", "React Native 0.81.4"},
            "flutter": {"Dart ^3.5.0", "Flutter"},
        }
        for pattern_id, expected in stacks.items():
            with self.subTest(pattern=pattern_id):
                detected = self.detect(REPOSITORIES[pattern_id])
                stack = {item for component in detected["components"] for item in component["stack"]}
                self.assertLessEqual(expected, stack)
        rails = self.detect(REPOSITORIES["rails"])["components"][0]
        postgres = next(item for item in rails["evidence"] if item["name"] == "PostgreSQL")
        self.assertTrue(postgres["inferred"])
        self.assertEqual(postgres["evidence"], "Gemfile")

    def test_the_xcode_project_belongs_to_the_folder_that_holds_it(self):
        detected = self.detect({"apps/ios/Shop.xcodeproj/project.pbxproj": "SDKROOT = iphoneos;\n"})
        self.assertEqual([component["path"] for component in detected["components"]], ["apps/ios"])

    def test_mac_projects_and_plain_gradle_builds_are_not_mobile(self):
        mac = self.detect({"Tool.xcodeproj/project.pbxproj": "SDKROOT = macosx;\n"})
        self.assertNotIn("iOS", mac["components"][0]["stack"])
        library = self.detect({"build.gradle": "plugins { id 'java-library' }\n"})
        self.assertEqual(library["components"][0]["stack"], ["Java"])

    def test_swift_packages_for_ios_and_aws_cdk_apps_are_recognised(self):
        manifest = "// swift-tools-version: 6.0\nlet p = Package(platforms: [.iOS(.v17)])\n"
        package = self.detect({"Package.swift": manifest})
        self.assertLessEqual({"Swift 6.0", "iOS 17"}, set(package["components"][0]["stack"]))
        cdk = self.detect({"package.json": {"dependencies": {"aws-cdk-lib": "^2.200.0"}}})
        self.assertIn("AWS", cdk["components"][0]["stack"])


# What each agent framework or MCP SDK declares in its manifest, and the technology detect reports for it. The
# package names were read in the registries (PyPI, npm) and the publishers' repositories on 25 November 2026.
AGENT_MANIFESTS = {
    "MCP": [
        ("pyproject.toml", '[project]\nname = "srv"\ndependencies = ["mcp[cli]>=1.2"]\n'),
        ("requirements.txt", "mcp==1.2.0\n"),
        ("package.json", {"dependencies": {"@modelcontextprotocol/sdk": "^1.12.0"}}),
        ("package.json", {"dependencies": {"@modelcontextprotocol/server": "^2.0.0"}}),
        ("package.json", {"devDependencies": {"@modelcontextprotocol/client": "^2.0.0"}}),
    ],
    "LangGraph": [("pyproject.toml", '[project]\nname = "a"\ndependencies = ["langgraph>=0.2"]\n'),
                  ("pyproject.toml", '[tool.poetry.dependencies]\npython = "^3.12"\nlanggraph = "^0.2"\n')],
    "CrewAI": [("requirements.txt", "crewai==0.80.0\n")],
    "OpenAI Agents SDK": [("pyproject.toml", '[project]\nname = "a"\ndependencies = ["openai-agents>=0.1"]\n')],
    "Pydantic AI": [("pyproject.toml", '[project]\nname = "a"\ndependencies = ["pydantic-ai>=0.1"]\n'),
                    ("requirements.txt", "pydantic-ai-slim[openai]==0.1.0\n")],
    "Claude Agent SDK": [
        ("pyproject.toml", '[project]\nname = "a"\ndependencies = ["claude-agent-sdk>=0.1"]\n'),
        ("package.json", {"dependencies": {"@anthropic-ai/claude-agent-sdk": "^0.1.0"}}),
    ],
    "AutoGen": [("requirements.txt", "autogen-agentchat>=0.4\n"), ("requirements.txt", "autogen>=0.9\n"),
                ("requirements.txt", "pyautogen==0.2.35\n")],
}


class AgenticStackTests(unittest.TestCase):
    """A repository that depends on an MCP SDK or an agent framework gets the agentic application security pattern."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def detect(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, content in files.items():
                write(root, relative, content)
            return detect_stack(root)

    def test_each_mcp_sdk_and_agent_framework_is_detected_from_its_manifest(self):
        for technology, manifests in AGENT_MANIFESTS.items():
            for relative, content in manifests:
                with self.subTest(technology=technology, manifest=relative, content=content):
                    stack = {item["name"] for component in self.detect({relative: content})["components"]
                             for item in component["evidence"]}
                    self.assertIn(technology, stack)

    def test_each_of_them_is_recommended_the_pattern_and_its_pack(self):
        for technology, manifests in AGENT_MANIFESTS.items():
            for relative, content in manifests:
                with self.subTest(technology=technology, manifest=relative, content=content):
                    components = components_for_profile(self.detect({relative: content}))
                    answers = {"name": "Repository", "roles": ["engineering"], "components": components}
                    plan = profile_recommendations(answers, self.catalog)
                    self.assertIn("agentic-application-security", {pattern["id"] for pattern in plan["matched"]})
        profile = validate_profile({"name": "Agent", "stack": ["Python 3.12", "LangGraph"]}, self.catalog)
        self.assertIn("agentic-application-security", resolved_profile(profile, self.catalog)["packs"])

    def test_a_repository_without_an_agent_dependency_gets_no_agentic_rules(self):
        files = {"pyproject.toml": '[project]\nname = "api"\ndependencies = ["fastapi>=0.115", "pydantic>=2"]\n',
                 "web/package.json": {"dependencies": {"react": "^18.3.0", "@modelcontextprotocol-docs/site": "^1.0.0"}}}
        components = components_for_profile(self.detect(files))
        plan = profile_recommendations({"name": "Repository", "roles": ["engineering"], "components": components},
                                       self.catalog)
        self.assertNotIn("agentic-application-security", {pattern["id"] for pattern in plan["matched"]})


if __name__ == "__main__":
    unittest.main()
