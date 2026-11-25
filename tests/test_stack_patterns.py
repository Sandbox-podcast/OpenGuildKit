"""Mainstream web, mobile and cloud stacks get their own stack pattern, from the answers or from the repository."""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.detect import components_for_profile, detect_stack
from openguildkit.project import profile_recommendations, resolved_profile, validate_profile

STACKS = {
    "django": ["Django", "Python", "MySQL"],
    "rails": ["Rails", "PostgreSQL"],
    "node-express": ["Vue", "Node.js", "Express", "MongoDB"],
    "vue": ["Vue", "Node.js", "Express", "MongoDB"],
    "ios-swift": ["Swift", "iOS"],
    "android-kotlin": ["Kotlin", "Android"],
    "laravel": ["Laravel", "PHP"],
    "angular": ["Angular", "NestJS"],
    "rust-cargo": ["Rust 1.82", "Axum 0.8", "Tokio 1"],
    "gitlab-ci-security": ["AWS", "GitLab CI", "Docker"],
    "docker-images": ["AWS", "GitLab CI", "Docker"],
    "aws-iam": ["AWS", "GitLab CI", "Docker"],
}
PACKS = {
    "django": "django", "rails": "rails", "node-express": "express", "vue": "vue", "angular": "angular",
    "laravel": "laravel", "rust-cargo": "rust-cargo", "ios-swift": "ios-app", "android-kotlin": "android-app",
    "gitlab-ci-security": "gitlab-ci-security", "docker-images": "container-images", "aws-iam": "aws-iam",
}
GENERIC_PACKS = {"secure-sdlc", "api-design", "typescript", "python"}


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
    "rust-cargo": {
        "Cargo.toml": '[package]\nname = "orders"\nedition = "2021"\nrust-version = "1.82"\n\n'
                      '[dependencies]\naxum = "0.8"\ntokio = { version = "1", features = ["full"] }\n',
    },
    "ios-swift": {
        "Shop.xcodeproj/project.pbxproj": "{ buildSettings = { SDKROOT = iphoneos; SWIFT_VERSION = 6.0; }; }\n",
    },
    "android-kotlin": {
        "app/build.gradle.kts": 'plugins {\n  id("com.android.application")\n  id("org.jetbrains.kotlin.android")\n}\n',
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

    def test_new_rules_are_actionable_sourced_and_not_generic(self):
        generic = {
            rule["instruction"] for pack_id in GENERIC_PACKS for rule in self.catalog["packs"][pack_id]["rules"]
        }
        new_packs = {*PACKS.values(), "mobile-accessibility", "mobile-store-release", "rust-dependencies"}
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
            "rust-cargo": {"Rust 1.82", "Rust edition 2021", "Axum 0.8", "Tokio 1"},
            "ios-swift": {"Swift 6.0", "iOS"},
            "android-kotlin": {"Android", "Kotlin"},
            "django": {"Python", "Django"},
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


if __name__ == "__main__":
    unittest.main()
