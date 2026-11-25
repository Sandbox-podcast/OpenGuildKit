"""Detection keeps only versions it can read, and the person can correct them during init."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import _prompt_components
from openguildkit.catalog import load_catalog
from openguildkit.detect import components_for_profile, detect_stack, detected_project_name
from openguildkit.patterns import recommend_patterns, technology_version
from openguildkit.stack_versions import version_key
from openguildkit.storage import write_json
from openguildkit.storybook import dependency_conflicts

from tests.support import CapturedCli, run_cli


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class DetectedVersionTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

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
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Acme", "components": questions["components"]["default"]})
        self.run_cli("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertIn("PostgreSQL", profile["stack"])
        self.assertNotIn("PostgreSQL 3.2", profile["stack"])
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("PostgreSQL 3.2", agents)
        self.assertIn("PostgreSQL", agents)

    def test_the_unsure_text_names_the_detected_components_in_words(self):
        write(self.root, "apps/web/package.json", {"dependencies": {"react": "^18.2.0"}})
        write(self.root, "services/api/pyproject.toml", '[project]\nname = "api"\nrequires-python = ">=3.12"\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions"))}
        unsure = questions["components"]["unsure"]
        self.assertEqual(len(questions["components"]["default"]), 2)
        for component in questions["components"]["default"]:
            self.assertIn(f"{component['id']} ({component['path']})", unsure)
        for text in (question["unsure"] for question in questions.values()):
            with self.subTest(text=text):
                self.assertNotRegex(text, r"[{}\[\]]|'id'")

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

    def test_plugin_versions_declared_in_a_plugins_block_are_read(self):
        write(self.root, "android/settings.gradle", 'include ":app"\n')
        write(self.root, "android/build.gradle",
              'plugins {\n  id "com.android.application" version "8.5.0" apply false\n'
              '  id "org.jetbrains.kotlin.android" version "1.9.24" apply false\n}\n')
        write(self.root, "android/app/build.gradle",
              'plugins { id "com.android.application"; id "org.jetbrains.kotlin.android" }\n'
              'android { compileSdk 34 }\n')
        write(self.root, "kts/build.gradle.kts", 'plugins { kotlin("jvm") version "2.0.0" }\n')
        stacks = self.stacks()
        self.assertEqual(set(stacks), {"android", "kts"})
        self.assertEqual(set(stacks["android"]),
                         {"Android", "Android Gradle Plugin 8.5.0", "Android SDK 34", "Kotlin 1.9.24"})
        self.assertEqual(stacks["kts"], ["Kotlin 2.0.0"])

    def test_a_declared_range_matches_the_patterns_of_its_lower_bound(self):
        write(self.root, "web/package.json", {"dependencies": {"next": "^14.2.0", "react": "^18.2.0"},
                                              "devDependencies": {"vite": "^5.2.0"}})
        write(self.root, "old/package.json", {"dependencies": {"next": "~13.0.1"}})
        write(self.root, "api/pyproject.toml", '[project]\nrequires-python = ">=3.11,<3.13"\n')
        stacks = self.stacks()
        self.assertEqual(stacks["web"], ["Next.js ^14.2.0", "React ^18.2.0", "Vite ^5.2.0"])
        self.assertEqual(stacks["api"], ["Python >=3.11,<3.13"])
        components = components_for_profile(detect_stack(self.root))
        plan = recommend_patterns(load_catalog(), [], "general", [], components)
        matched = {pattern["id"] for pattern in plan["matched"]}
        self.assertLessEqual({"nextjs-react", "react-web", "python-development"}, matched)
        conflicts = json.dumps(plan)
        self.assertIn("Next.js ~13.0.1 is below next.js 13.4", conflicts)

    def test_a_symfony_application_is_recognised_by_its_framework_bundle_and_its_version(self):
        write(self.root, "shop/composer.json", {"require": {
            "php": ">=8.3", "symfony/framework-bundle": "7.2.*", "symfony/console": "7.2.*"}})
        write(self.root, "legacy/composer.json", {"require": {"symfony/symfony": "^3.4"}})
        # A Symfony component alone is not a Symfony application: Laravel and a console tool both use them.
        write(self.root, "tool/composer.json", {"require": {"symfony/console": "^7.0"}})
        write(self.root, "store/composer.json", {"require": {
            "laravel/framework": "^13.0", "symfony/http-foundation": "^7.0"}})
        stacks = self.stacks()
        self.assertEqual(stacks["shop"], ["PHP >=8.3", "Symfony 7.2.*"])
        self.assertEqual(stacks["legacy"], ["PHP", "Symfony ^3.4"])
        self.assertEqual(stacks["tool"], ["PHP"])
        self.assertEqual(stacks["store"], ["Laravel ^13.0", "PHP"])
        components = components_for_profile(detect_stack(self.root))
        matched = recommend_patterns(load_catalog(), [], "general", [], components)["matched"]
        self.assertEqual({component for pattern in matched if pattern["id"] == "symfony"
                          for component in pattern["components"]}, {"shop", "legacy"})

    def test_an_old_style_kotlin_version_variable_is_read(self):
        write(self.root, "app/build.gradle",
              "buildscript {\n  ext.kotlin_version = '1.9.24'\n  dependencies {\n"
              '    classpath "org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version"\n  }\n}\n'
              "apply plugin: 'kotlin-android'\n")
        write(self.root, "lib/build.gradle",
              "buildscript {\n  ext {\n    kotlin_version = '2.0.0'\n  }\n}\napply plugin: 'kotlin'\n")
        stacks = self.stacks()
        self.assertIn("Kotlin 1.9.24", stacks["app"])
        self.assertIn("Kotlin 2.0.0", stacks["lib"])

    def test_the_ktor_plugin_and_the_server_artifacts_give_the_ktor_version(self):
        write(self.root, "plugin/build.gradle.kts",
              'plugins {\n  kotlin("jvm") version "2.0.0"\n  id("io.ktor.plugin") version "3.0.0"\n}\n')
        write(self.root, "groovy/build.gradle",
              "plugins {\n  id 'org.jetbrains.kotlin.jvm' version '2.0.0'\n  id 'io.ktor.plugin' version '3.0.1'\n}\n")
        write(self.root, "deps/build.gradle.kts",
              'plugins { kotlin("jvm") version "2.0.0" }\ndependencies {\n'
              '  implementation("io.ktor:ktor-server-core-jvm:3.0.2")\n'
              '  implementation("io.ktor:ktor-server-netty:3.0.2")\n}\n')
        stacks = self.stacks()
        self.assertEqual(stacks["plugin"], ["Kotlin 2.0.0", "Ktor 3.0.0"])
        self.assertEqual(stacks["groovy"], ["Kotlin 2.0.0", "Ktor 3.0.1"])
        self.assertEqual(stacks["deps"], ["Kotlin 2.0.0", "Ktor 3.0.2"])

    def test_ktor_is_read_from_a_version_catalog_through_a_plugin_a_library_or_a_bundle(self):
        catalog = ('[versions]\nktor = "3.0.3"\n[libraries]\n'
                   'ktor-server-core = { module = "io.ktor:ktor-server-core", version.ref = "ktor" }\n'
                   'ktor-server-netty = { group = "io.ktor", name = "ktor-server-netty", version = "3.0.3" }\n'
                   'ktor-server-cio = "io.ktor:ktor-server-cio:3.0.3"\n'
                   '[bundles]\nktor-server = ["ktor-server-core", "ktor-server-netty"]\n'
                   '[plugins]\nktor = { id = "io.ktor.plugin", version.ref = "ktor" }\n')
        for folder, build in {
            "by-plugin": "plugins { alias(libs.plugins.ktor) }\n",
            "by-library": "dependencies { implementation(libs.ktor.server.core) }\n",
            "by-group-and-name": "dependencies { implementation(libs.ktor.server.netty) }\n",
            "by-bundle": "dependencies { implementation(libs.bundles.ktor.server) }\n",
            "by-notation": "dependencies { implementation(libs.ktor.server.cio) }\n",
        }.items():
            write(self.root, f"{folder}/build.gradle.kts", build)
            write(self.root, f"{folder}/gradle/libs.versions.toml", catalog)
        # The catalog declares Ktor, the build never uses it.
        write(self.root, "unused/build.gradle.kts", 'plugins { kotlin("jvm") version "2.0.0" }\n')
        write(self.root, "unused/gradle/libs.versions.toml", catalog)
        stacks = self.stacks()
        for folder in ("by-plugin", "by-library", "by-group-and-name", "by-bundle", "by-notation"):
            with self.subTest(folder=folder):
                self.assertIn("Ktor 3.0.3", stacks[folder])
                self.assertIn("Kotlin", stacks[folder])
        self.assertEqual(stacks["unused"], ["Kotlin 2.0.0"])
        evidence = {item["name"]: item["evidence"] for component in detect_stack(self.root)["components"]
                    if component["path"] == "by-library" for item in component["evidence"]}
        self.assertEqual(evidence["Ktor"], "by-library/gradle/libs.versions.toml")

    def test_a_ktor_module_shares_the_component_and_the_version_of_its_gradle_build(self):
        write(self.root, "settings.gradle.kts", 'include(":server", ":shared")\n')
        write(self.root, "build.gradle.kts", "plugins { alias(libs.plugins.ktor) apply false }\n")
        write(self.root, "gradle/libs.versions.toml",
              '[versions]\nktor = "3.0.4"\n[plugins]\nktor = { id = "io.ktor.plugin", version.ref = "ktor" }\n'
              '[libraries]\nktor-server-core = { module = "io.ktor:ktor-server-core", version.ref = "ktor" }\n')
        write(self.root, "server/build.gradle.kts", "dependencies { implementation(libs.ktor.server.core) }\n")
        write(self.root, "shared/build.gradle.kts", "kotlin { jvmToolchain(21) }\n")
        stacks = self.stacks()
        self.assertEqual(set(stacks), {"."})
        self.assertIn("Ktor 3.0.4", stacks["."])

    def test_a_ktor_version_catalog_in_the_settings_and_a_version_variable_are_read(self):
        write(self.root, "catalog/settings.gradle.kts",
              'dependencyResolutionManagement {\n  versionCatalogs {\n'
              '    create("ktorLibs") {\n      from("io.ktor:ktor-version-catalog:3.0.5")\n    }\n  }\n}\n'
              'include(":server")\n')
        write(self.root, "catalog/server/build.gradle.kts",
              'plugins { kotlin("jvm") version "2.0.0" }\ndependencies { implementation(ktorLibs.server.core) }\n')
        write(self.root, "properties/gradle.properties", "ktor_version=3.0.6\nkotlin.code.style=official\n")
        write(self.root, "properties/build.gradle.kts",
              'val ktor_version: String by project\ndependencies {\n'
              '  implementation("io.ktor:ktor-server-core-jvm:$ktor_version")\n}\n')
        write(self.root, "groovy-ext/build.gradle",
              "ext.ktor_version = '3.0.7'\ndependencies {\n"
              '  implementation "io.ktor:ktor-server-netty:$ktor_version"\n  implementation "io.ktor:ktor-server-auth:${ktor_version}"\n}\n')
        stacks = self.stacks()
        self.assertIn("Ktor 3.0.5", stacks["catalog"])
        self.assertIn("Ktor 3.0.6", stacks["properties"])
        self.assertIn("Ktor 3.0.7", stacks["groovy-ext"])

    def test_ktor_without_a_readable_version_is_still_detected_as_a_kotlin_server(self):
        write(self.root, "managed/build.gradle.kts",
              'plugins { id("io.ktor.plugin") }\ndependencies { implementation("io.ktor:ktor-server-core") }\n')
        write(self.root, "bom/build.gradle.kts",
              'dependencies {\n  implementation(platform("io.ktor:ktor-bom:3.0.8"))\n'
              '  implementation("io.ktor:ktor-server-core")\n}\n')
        stacks = self.stacks()
        self.assertEqual(stacks["managed"], ["Kotlin", "Ktor"])
        self.assertEqual(stacks["bom"], ["Kotlin", "Ktor 3.0.8"])

    def test_the_ktor_client_alone_does_not_make_a_ktor_server(self):
        write(self.root, "android/build.gradle.kts",
              'plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }\n'
              'dependencies { implementation("io.ktor:ktor-client-okhttp:3.0.0") }\n')
        write(self.root, "client/build.gradle.kts",
              'plugins { kotlin("jvm") version "2.0.0" }\n'
              'dependencies { implementation("io.ktor:ktor-client-cio:3.0.0") }\n')
        stacks = self.stacks()
        self.assertFalse([item for stack in stacks.values() for item in stack if item.startswith("Ktor")])
        self.assertIn("Android", stacks["android"])

    def test_detect_says_why_a_technology_has_no_version(self):
        write(self.root, "requirements.txt", "stripe==8.1.0\n")
        write(self.root, "android/build.gradle", 'plugins { id "com.android.application" }\nandroid { compileSdk 34 }\n')
        evidence = {item["name"]: item for component in detect_stack(self.root)["components"]
                    for item in component["evidence"]}
        self.assertIsNone(evidence["Stripe"]["version"])
        self.assertIn("==8.1.0", evidence["Stripe"]["note"])
        self.assertIn("Android SDK", evidence["Android"]["note"])
        output = self.run_cli("detect")
        self.assertIn("Stripe: SDK ==8.1.0, the service itself has no version", output)
        self.assertNotIn("version unknown", output.split("Android:")[1].splitlines()[0])

    def test_a_kustomize_overlay_belongs_to_its_base(self):
        write(self.root, "k2/kustomization.yaml", "resources:\n  - deploy.yaml\n")
        write(self.root, "k2/deploy.yaml", "apiVersion: apps/v1\nkind: Deployment\n")
        write(self.root, "k2/overlays/kustomization.yaml", "resources:\n  - ../\n")
        write(self.root, "k3/base/kustomization.yaml", "resources: []\n")
        write(self.root, "k3/overlays/prod/kustomization.yaml", "resources:\n  - ../../base\n")
        self.assertEqual(self.stacks(), {"k2": ["Kubernetes"], "k3": ["Kubernetes"]})

    def test_every_card_payment_provider_of_the_pci_pattern_is_read(self):
        write(self.root, "py/pyproject.toml", '[project]\ndependencies = ["adyen~=9.0", "braintree>=4"]\n')
        write(self.root, "js/package.json", {"dependencies": {"@mollie/api-client": "^3.7.0"}})
        stacks = self.stacks()
        self.assertEqual(stacks["py"], ["Adyen", "Braintree", "Python"])
        self.assertEqual(stacks["js"], ["Mollie"])
        components = components_for_profile(detect_stack(self.root))
        matched = recommend_patterns(load_catalog(), [], "general", [], components)["matched"]
        self.assertIn("pci-dss-cardholder-data", {pattern["id"] for pattern in matched})

    def test_a_cargo_manifest_gives_the_rust_version_the_edition_and_the_frameworks(self):
        write(self.root, "svc/Cargo.toml",
              '[package]\nname = "svc"\nversion = "0.1.0"\nedition = "2021"\nrust-version = "1.75"\n\n'
              '[dependencies]\naxum = { version = "0.7.5", features = ["macros"] }\n'
              'tokio = { version = "1", features = ["full"] }\nserde = "1"\n\n'
              '[dev-dependencies]\nactix-web = "4.5"\n\n[build-dependencies]\nrocket = ">=0.5, <0.6"\n')
        write(self.root, "plain/Cargo.toml", '[package]\nname = "plain"\nversion = "0.1.0"\n')
        stacks = self.stacks()
        self.assertEqual(stacks["svc"], ["Actix Web 4.5", "Axum 0.7.5", "Rocket >=0.5, <0.6", "Rust 1.75",
                                         "Rust edition 2021", "Tokio 1"])
        self.assertEqual(stacks["plain"], ["Rust"])
        evidence = {item["name"]: item["evidence"] for component in detect_stack(self.root)["components"]
                    if component["path"] == "svc" for item in component["evidence"]}
        self.assertEqual(set(evidence.values()), {"svc/Cargo.toml"})

    def test_cargo_dependencies_are_read_in_every_form_a_manifest_writes_them(self):
        write(self.root, "tables/Cargo.toml",
              '[package]\nname = "tables"\n\n[dependencies.axum]\nversion = "0.8"\nfeatures = ["json"]\n\n'
              '[target.\'cfg(unix)\'.dependencies]\ntokio = "1.38"\n')
        write(self.root, "renamed/Cargo.toml",
              '[package]\nname = "renamed"\n\n[dependencies]\nweb = { package = "actix-web", version = "4" }\n'
              'other = { package = "serde", version = "1" }\n')
        write(self.root, "git/Cargo.toml",
              '[package]\nname = "git"\n\n[dependencies]\nrocket = { git = "https://github.com/rwf2/Rocket" }\n'
              'axum = { path = "../axum" }\n')
        write(self.root, "exact/Cargo.toml",
              '[package]\nname = "exact"\n\n[dependencies]\ntokio = "=1.40.0"\naxum = "^0.7"\nactix-web = "4.*"\n')
        write(self.root, "broken/Cargo.toml", '[package\nname = "broken"\n')
        write(self.root, "inherit/Cargo.toml",
              '[package]\nname = "inherit"\nedition.workspace = true\nrust-version = { workspace = true }\n\n'
              '[dependencies]\naxum.workspace = true\n')
        stacks = self.stacks()
        self.assertEqual(stacks["tables"], ["Axum 0.8", "Rust", "Tokio 1.38"])
        self.assertEqual(stacks["renamed"], ["Actix Web 4", "Rust"])
        self.assertEqual(stacks["git"], ["Axum", "Rocket", "Rust"])
        self.assertEqual(stacks["exact"], ["Actix Web 4.*", "Axum ^0.7", "Rust", "Tokio 1.40.0"])
        self.assertEqual(stacks["broken"], ["Rust"])
        self.assertEqual(stacks["inherit"], ["Axum", "Rust"])

    def test_cargo_workspace_members_share_the_component_of_their_root(self):
        write(self.root, "Cargo.toml",
              '[workspace]\nmembers = ["crates/*", "tools/xtask"]\nexclude = ["crates/legacy"]\nresolver = "2"\n\n'
              '[workspace.package]\nedition = "2021"\nrust-version = "1.80"\n\n'
              '[workspace.dependencies]\ntokio = { version = "1.38", features = ["rt"] }\naxum = "0.7"\n')
        write(self.root, "crates/api/Cargo.toml",
              '[package]\nname = "api"\nedition.workspace = true\nrust-version.workspace = true\n\n'
              '[dependencies]\naxum.workspace = true\ntokio = { workspace = true }\n')
        write(self.root, "crates/worker/Cargo.toml", '[package]\nname = "worker"\n\n[dependencies]\nactix-web = "4"\n')
        write(self.root, "crates/legacy/Cargo.toml", '[package]\nname = "legacy"\n\n[dependencies]\nrocket = "0.5"\n')
        write(self.root, "tools/xtask/Cargo.toml", '[package]\nname = "xtask"\n')
        write(self.root, "tools/other/Cargo.toml", '[package]\nname = "other"\n')
        stacks = self.stacks()
        self.assertEqual(set(stacks), {".", "crates/legacy", "tools/other"})
        self.assertEqual(stacks["."], ["Actix Web 4", "Axum 0.7", "Rust 1.80", "Rust edition 2021", "Tokio 1.38"])
        self.assertEqual(stacks["crates/legacy"], ["Rocket 0.5", "Rust"])
        self.assertEqual(stacks["tools/other"], ["Rust"])

    def test_a_cargo_workspace_never_reaches_outside_the_project_or_into_a_link(self):
        project = self.root / "project"
        write(self.root, "outside/stolen/Cargo.toml", '[package]\nname = "stolen"\n\n[dependencies]\nrocket = "0.5"\n')
        write(project, "ws/Cargo.toml", '[workspace]\nmembers = ["../../outside/*", "/abs", "link", "*"]\n')
        write(project, "ws/real/Cargo.toml", '[package]\nname = "real"\n\n[dependencies]\naxum = "0.7"\n')
        (project / "ws" / "link").symlink_to(self.root / "outside" / "stolen", target_is_directory=True)
        stacks = {component["path"]: component["stack"] for component in detect_stack(project)["components"]}
        self.assertEqual(stacks, {"ws": ["Axum 0.7", "Rust"]})

    def test_the_project_name_comes_from_the_cargo_package_when_there_is_no_package_json(self):
        write(self.root, "Cargo.toml", '[package]\nname = "billing-svc"\nversion = "0.1.0"\n')
        self.assertEqual(detected_project_name(self.root), "billing-svc")
        write(self.root, "package.json", {"name": "sample-shop"})
        self.assertEqual(detected_project_name(self.root), "sample-shop")
        (self.root / "package.json").unlink()
        write(self.root, "Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
        self.assertEqual(detected_project_name(self.root), self.root.name)
        write(self.root, "Cargo.toml", '[package]\nname = "two\\nlines"\n')
        self.assertEqual(detected_project_name(self.root), self.root.name)

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
        write(self.root, "answers.json", {"stack": [], "personal_data": "no"})
        self.run_cli("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["name"], "sample-shop")
        self.assertEqual(profile["components"], [{"id": "root", "path": ".", "stack": ["Vite ^8.0.0"]}])

    def test_a_single_detected_root_keeps_the_stack_the_person_wrote(self):
        write(self.root, "requirements.txt", "fastapi==0.110\n")
        write(self.root, "answers.json", {"stack": ["Python 3.12", "PostgreSQL 16"], "personal_data": "no"})
        self.run_cli("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["components"],
                         [{"id": "root", "path": ".", "stack": ["FastAPI 0.110", "Python 3.12", "PostgreSQL 16"]}])

    def test_several_detected_components_still_yield_to_a_written_stack(self):
        write(self.root, "web/package.json", {"dependencies": {"react": "^18.2.0"}})
        write(self.root, "api/requirements.txt", "fastapi==0.110\n")
        write(self.root, "answers.json", {"stack": ["Python"], "personal_data": "no"})
        out, err = self.run_cli_with_errors("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertNotIn("components", profile)
        self.assertIn("left aside", out + err)

    def run_cli_with_errors(self, *arguments):
        result = run_cli(self.root, *arguments)
        return result.stdout, result.stderr


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


class VersionRangeTests(unittest.TestCase):
    """Pattern matching and the Storybook dependency report read a declared range with one engine."""

    # The lowest version each range accepts, as npm reads it; None when an alternative sets no lower bound.
    RANGES = {
        "^18.2.0": "18.2.0", "~1.2.3": "1.2.3", ">=1.2.0": "1.2.0", ">1.2": "1.3", ">1.2.3": "1.2.4", "1.2.x": "1.2",
        "1.2.3 - 2.0.0": "1.2.3", "<2 || >=3": None, "*": None, "=1.2.3": "1.2.3", ">=1.0.0 <2.0.0": "1.0.0",
        "^0.2.3": "0.2.3", "~1.2 || ^2": "1.2",
    }

    @staticmethod
    def key(version: str | None):
        return None if version is None else version_key(version.partition("-")[0])

    def test_patterns_and_the_storybook_report_read_the_same_lower_bound(self):
        library = {"peerDependencies": {"react": ">=0.0.0"}}
        with tempfile.TemporaryDirectory() as folder:
            for spec, expected in self.RANGES.items():
                with self.subTest(range=spec):
                    for_patterns = technology_version(f"React {spec}")
                    row = dependency_conflicts(library, {"dependencies": {"react": spec}}, Path(folder))[0]
                    checked = row.get("checked")
                    for_storybook = min(checked, key=self.key) if checked else None
                    self.assertEqual(self.key(for_patterns), self.key(expected))
                    self.assertEqual(self.key(for_storybook), self.key(expected))


if __name__ == "__main__":
    unittest.main()
