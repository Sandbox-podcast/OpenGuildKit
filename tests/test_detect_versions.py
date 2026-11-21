"""Detection keeps only versions it can read, and the person can correct them during init."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import _prompt_components, main
from openguildkit.catalog import load_catalog
from openguildkit.detect import components_for_profile, detect_stack
from openguildkit.patterns import recommend_patterns
from openguildkit.storage import write_json


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class DetectedVersionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def stacks(self):
        return {component["path"]: component["stack"] for component in detect_stack(self.root)["components"]}

    def test_a_client_library_version_is_not_the_database_version(self):
        write(self.root, "web/package.json", {"dependencies": {"pg": "^8.11.3"}})
        write(self.root, "api/pyproject.toml", '[project]\nname = "api"\ndependencies = ["psycopg[binary]>=3.1"]\n')
        write(self.root, "worker/requirements.txt", "asyncpg==0.29.0\n")
        stacks = self.stacks()
        self.assertEqual(stacks["web"], ["PostgreSQL"])
        self.assertIn("PostgreSQL", stacks["api"])
        self.assertIn("PostgreSQL", stacks["worker"])
        self.assertFalse([item for stack in stacks.values() for item in stack if item.startswith("PostgreSQL ")])

    def test_the_profile_and_instructions_carry_no_inferred_version(self):
        write(self.root, "api/pyproject.toml",
              '[project]\nname = "api"\nrequires-python = ">=3.12"\ndependencies = ["fastapi>=0.115", "psycopg[binary]>=3.2"]\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions"))}
        write_json(self.root / "answers.json", {"name": "Acme", "components": questions["components"]["default"]})
        self.run_cli("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertIn("PostgreSQL", profile["stack"])
        self.assertNotIn("PostgreSQL 3.2", profile["stack"])
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("PostgreSQL 3.2", agents)
        self.assertIn("PostgreSQL", agents)

    def test_a_declared_database_version_wins_over_a_client_library(self):
        write(self.root, "pyproject.toml", '[project]\nname = "api"\ndependencies = ["psycopg>=3.1"]\n')
        write(self.root, "compose.yaml", "services:\n  db:\n    image: postgres:16-alpine\n")
        self.assertIn("PostgreSQL 16", self.stacks()["."])

    def test_official_image_names_are_recognised(self):
        write(self.root, "full/compose.yaml", "services:\n  db:\n    image: docker.io/library/postgres:16\n")
        write(self.root, "bare/compose.yaml", "services:\n  db:\n    image: postgres\n")
        write(self.root, "quoted/Dockerfile", "FROM postgres AS base\n")
        stacks = self.stacks()
        self.assertEqual(stacks["full"], ["PostgreSQL 16"])
        self.assertEqual(stacks["bare"], ["PostgreSQL"])
        self.assertEqual(stacks["quoted"], ["Docker", "PostgreSQL"])  # a Dockerfile also names Docker

    def test_framework_and_infrastructure_markers(self):
        write(self.root, "k8s/deploy.yaml", "---\napiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: demo\n")
        write(self.root, "unrelated/config.yaml", "apiVersion: v1\n---\nkind: Other\n")
        write(self.root, "dbt/dbt_project.yml", "name: analytics\nversion: '1.0.0'\n")
        write(self.root, "web/vite.config.ts", "export default {};")
        write(self.root, "node/package.json", {
            "dependencies": {"express": ">=4.0.0 <5"}, "devDependencies": {"vite": "^8.0.0"},
        })
        write(self.root, "wp-config/wp-config.php", "<?php")
        (self.root / "wp-theme" / "wp-content").mkdir(parents=True)
        stacks = self.stacks()
        self.assertEqual(stacks["k8s"], ["Kubernetes"])
        self.assertNotIn("unrelated", stacks)
        self.assertEqual(stacks["dbt"], ["dbt"])
        self.assertEqual(stacks["web"], ["Vite"])
        self.assertEqual(stacks["node"], ["Express >=4.0.0 <5", "Vite ^8.0.0"])
        self.assertEqual(stacks["wp-config"], ["WordPress"])
        self.assertEqual(stacks["wp-theme"], ["WordPress"])

    def test_gradle_modules_share_the_root_with_the_declared_tool_versions(self):
        write(self.root, "mobile/settings.gradle.kts", 'include(\n    ":app",\n    ":modules:shared",\n)\n')
        write(self.root, "mobile/build.gradle.kts",
              'plugins {\n  alias(libs.plugins.android.application) apply false\n'
              '  alias(libs.plugins.kotlin.android) apply false\n}\n')
        write(self.root, "mobile/gradle/libs.versions.toml",
              '[versions]\nagp = "8.5.0"\nkotlin = "1.9.24"\n[plugins]\n'
              'android-application = { id = "com.android.application", version.ref = "agp" }\n'
              'kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }\n')
        write(self.root, "mobile/app/build.gradle.kts",
              'plugins { alias(libs.plugins.android.application) }\nandroid { compileSdk = 34 }\n')
        write(self.root, "mobile/modules/shared/build.gradle.kts", 'kotlin { jvmToolchain(17) }\n')
        write(self.root, "java/build.gradle",
              """plugins { id 'org.springframework.boot' version '3.2.1' }\nsourceCompatibility "21"\n""")
        stacks = self.stacks()
        self.assertEqual(set(stacks), {"mobile", "java"})
        self.assertEqual(set(stacks["mobile"]),
                         {"Android", "Android Gradle Plugin 8.5.0", "Android SDK 34", "Java 17", "Kotlin 1.9.24"})
        self.assertEqual(stacks["java"], ["Java 21", "Spring Boot 3.2.1"])

    def test_detects_ios_deployment_targets(self):
        write(self.root, "app/App.xcodeproj/project.pbxproj", 'SWIFT_VERSION = 6.0;\nIPHONEOS_DEPLOYMENT_TARGET = 16.4;\n')
        write(self.root, "module/Package.swift", '// swift-tools-version: 6.0\nlet p = Package(platforms: [.iOS(.v17)])\n')
        stacks = self.stacks()
        self.assertEqual(set(stacks["app"]), {"iOS 16.4", "Swift 6.0"})
        self.assertEqual(set(stacks["module"]), {"iOS 17", "Swift 6.0"})

    def test_declared_stripe_and_kubernetes_feed_the_pattern_recommendations(self):
        write(self.root, "pyproject.toml", '[project]\ndependencies = ["stripe>=10,<12"]\n')
        write(self.root, "cluster.tf", "terraform {}")
        write(self.root, "deploy.yaml", "apiVersion: v1\nkind: Service\n")
        write(self.root, "gitops.yaml", "apiVersion: argoproj.io/v1alpha1\nkind: Application\n")
        components = components_for_profile(detect_stack(self.root))
        matched = recommend_patterns(load_catalog(), [], "general", [], components)["matched"]
        self.assertLessEqual({"pci-dss-cardholder-data", "kubernetes-gitops", "terraform-kubernetes"},
                             {pattern["id"] for pattern in matched})

    def test_setup_uses_the_package_name_and_detected_root_with_an_empty_manual_stack(self):
        write(self.root, "package.json", {"name": "sample-shop", "devDependencies": {"vite": "^8.0.0"}})
        write(self.root, "answers.json", {"stack": []})
        self.run_cli("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["name"], "sample-shop")
        self.assertEqual(profile["components"], [{"id": "root", "path": ".", "stack": ["Vite ^8.0.0"]}])

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, 0, stderr.getvalue())
        return stdout.getvalue()


class ComponentPromptTests(unittest.TestCase):
    QUESTION = {
        "id": "components",
        "prompt": "Which components does the repository contain?",
        "default": [
            {"id": "apps-web", "path": "apps/web", "stack": ["Next.js 14.2.3", "React 18.3.1"]},
            {"id": "services-api", "path": "services/api", "stack": ["FastAPI 0.111", "PostgreSQL 3.1"]},
        ],
    }

    def prompt(self, *answers):
        with patch("builtins.input", side_effect=list(answers)), contextlib.redirect_stderr(io.StringIO()):
            return _prompt_components(self.QUESTION)

    def test_a_version_can_be_corrected_without_dropping_the_components(self):
        components = self.prompt("e", "", "FastAPI 0.111, PostgreSQL 16")
        self.assertEqual(components[0], self.QUESTION["default"][0])
        self.assertEqual(components[1], {"id": "services-api", "path": "services/api",
                                         "stack": ["FastAPI 0.111", "PostgreSQL 16"]})
        self.assertEqual(self.QUESTION["default"][1]["stack"], ["FastAPI 0.111", "PostgreSQL 3.1"])

    def test_keep_and_refuse_still_work(self):
        self.assertEqual(self.prompt(""), self.QUESTION["default"])
        self.assertEqual(self.prompt("n"), [])


if __name__ == "__main__":
    unittest.main()
