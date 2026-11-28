"""Proposes components, technologies and versions from the repository's manifests, without running a package manager.

Detection only reads local manifests. It never runs a package manager or opens the
network, and the team confirms or corrects the proposal before it reaches the profile.

Entry: walk, detected_project_name, detect_stack, components_for_profile
Tests: tests/test_detect_versions.py
"""

import itertools
import json
import os
import re
import tomllib
from pathlib import Path

from . import lazy_re
from .detect_gradle import gradle_components, gradle_modules
from .detect_manifest import DetectedComponent, read_manifest_text
from .stack_versions import declared_version, version_key

# The folders no walk of the project enters: version control, OpenGuildKit's state, dependencies, virtual
# environments, caches and build output. Detection, proposed checks, the code a bug brief names and Storybook
# extraction all walk the tree with walk() below, so they all skip the same folders.
SKIPPED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".openguildkit", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", ".next", ".nuxt", "vendor", "coverage", ".tox", ".mypy_cache",
    "storybook-static",
})
MAX_DEPTH = 4
MAX_WORKSPACE_MEMBERS = 500

NPM_PACKAGES = {
    "next": "Next.js",
    "react": "React",
    "vue": "Vue",
    "@angular/core": "Angular",
    "svelte": "Svelte",
    "@sveltejs/kit": "SvelteKit",
    # A React Native app declares react-native next to react; a web app declares react-dom instead. Expo projects
    # declare expo as well.
    "react-native": "React Native",
    "expo": "Expo",
    "typescript": "TypeScript",
    "express": "Express",
    "@nestjs/core": "NestJS",
    "@playwright/test": "Playwright",
    "playwright": "Playwright",
    "vitest": "Vitest",
    "vite": "Vite",
    "jest": "Jest",
    "storybook": "Storybook",
    "pg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "prisma": "Prisma",
    "aws-cdk-lib": "AWS",
    "stripe": "Stripe",
    "@adyen/api-library": "Adyen",
    "braintree": "Braintree",
    "checkout-sdk-node": "Checkout.com",
    "@mollie/api-client": "Mollie",
    # What puts an MCP server or an AI agent in a project, which the agentic-application-security pattern follows. The
    # MCP SDK for TypeScript is `sdk` up to its first line and `server` and `client` from its second.
    "@modelcontextprotocol/sdk": "MCP",
    "@modelcontextprotocol/server": "MCP",
    "@modelcontextprotocol/client": "MCP",
    "@anthropic-ai/claude-agent-sdk": "Claude Agent SDK",
}
PYTHON_PACKAGES = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "pytest": "pytest",
    "sqlalchemy": "SQLAlchemy",
    "psycopg": "PostgreSQL",
    "psycopg2": "PostgreSQL",
    "psycopg2-binary": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "chaosfolk": "ChaosFolk",
    "playwright": "Playwright",
    "stripe": "Stripe",
    "adyen": "Adyen",
    "braintree": "Braintree",
    "checkout-sdk": "Checkout.com",
    "mollie-api-python": "Mollie",
    # The names the registry gives: `autogen` is the community AG2 line, `autogen-agentchat` the Microsoft one and
    # `pyautogen` the proxy of the second.
    "mcp": "MCP",
    "langgraph": "LangGraph",
    "crewai": "CrewAI",
    "openai-agents": "OpenAI Agents SDK",
    "pydantic-ai": "Pydantic AI",
    "pydantic-ai-slim": "Pydantic AI",
    "claude-agent-sdk": "Claude Agent SDK",
    # The Airflow distribution itself; its REST API client (apache-airflow-client) and a provider alone are not.
    "apache-airflow": "Apache Airflow",
    "autogen": "AutoGen",
    "autogen-agentchat": "AutoGen",
    "pyautogen": "AutoGen",
}
GO_MODULES = {
    "github.com/jackc/pgx": "PostgreSQL",
    "github.com/lib/pq": "PostgreSQL",
}
RUBY_GEMS = {
    "rails": "Rails", "pg": "PostgreSQL", "mysql2": "MySQL", "stripe": "Stripe",
    "adyen-ruby-api-library": "Adyen", "braintree": "Braintree", "mollie-api-ruby": "Mollie",
}
CARGO_CRATES = {"axum": "Axum", "actix-web": "Actix Web", "rocket": "Rocket", "tokio": "Tokio"}
COMPOSER_PACKAGES = {
    # The framework bundle (or the full-stack package of old applications) marks a Symfony application; the
    # Symfony components that Laravel, Drupal or a console tool use alone do not.
    "laravel/framework": "Laravel", "symfony/framework-bundle": "Symfony", "symfony/symfony": "Symfony",
    "stripe/stripe-php": "Stripe", "adyen/php-api-library": "Adyen",
    "braintree/braintree_php": "Braintree", "checkout/checkout-sdk-php": "Checkout.com",
    "mollie/mollie-api-php": "Mollie",
}
IMAGES = {"postgres": "PostgreSQL", "postgis/postgis": "PostgreSQL", "apache/airflow": "Apache Airflow"}
IMAGE_PREFIXES = ("docker.io/library/", "docker.io/", "library/")
INFERRED = {"PostgreSQL", "MySQL"}
# SDK versions are not the versions of the services they use. The card payment providers are those the
# pci-dss-cardholder-data pattern names (Worldpay publishes no common SDK package to read).
PAYMENT_PROVIDERS = {"Stripe", "Adyen", "Braintree", "Checkout.com", "Mollie"}
UNVERSIONED = {"AWS", *PAYMENT_PROVIDERS}


def _sdk_note(spec: object) -> str:
    """Why a service reached through an SDK has no version: the SDK's declared version is not the service's."""
    declared = declared_version(spec)
    if not declared:
        return "the service itself has no version"
    exact = declared[0].isdigit()
    return f"SDK {'==' if exact else ''}{declared}, the service itself has no version"

_VERSION = lazy_re.compile(r"\d+(?:\.\d+){0,2}")
_GEM = lazy_re.compile(r"""(?m)^\s*gem\s+["']([\w.-]+)["'](?:\s*,\s*["']([^"']+)["'])?""")
_REQUIREMENT = lazy_re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*([^;#]*)")
# A Mix project's Elixir requirement and its Phoenix dependency; text after a # is a comment.
_MIX_ELIXIR = lazy_re.compile(r'(?m)^[^#\n]*\belixir:[ \t]*"([^"\n]+)"')
_MIX_PHOENIX = lazy_re.compile(r'(?m)^[^#\n]*\{[ \t]*:phoenix[ \t]*,[ \t]*(?:"([^"\n]+)")?')
# What Mix writes next to mix.exs: the fetched dependencies and the build, each with mix.exs files of its own.
MIX_OUTPUT = ("deps", "_build")
_AIRFLOW_IMPORT = lazy_re.compile(r"(?m)^[ \t]*(?:from|import)[ \t]+airflow\b")
_DBT_VERSION = lazy_re.compile(r"""(?m)^require-dbt-version:[ \t]*(\[[^\]\n]*\]|"[^"\n]*"|'[^'\n]*')""")
_KUBE_API = lazy_re.compile(r"""(?m)^apiVersion:[ \t]+["']?(?:([a-z0-9.-]+)/)?v\d+(?:[a-z]+\d+)?["']?[ \t]*(?:#.*)?$""")
_KUBE_KIND = lazy_re.compile(r"""(?m)^kind:[ \t]+["']?([A-Z][A-Za-z0-9]*)["']?[ \t]*(?:#.*)?$""")


def _entry_names(entries: list) -> tuple[list[str], list[str]]:
    """The names of the files and of the folders a folder lists, without symbolic links or SKIPPED_DIRECTORIES."""
    files, folders = [], []
    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in SKIPPED_DIRECTORIES:
                    folders.append(entry.name)
            elif entry.is_file():
                files.append(entry.name)
        except OSError:
            continue
    return files, folders


def walk(root: Path, max_depth: int | None = None):
    """Each folder from root down, depth first in name order, as (folder, parts, files, folders).

    parts are the names of the folder's path below root, () for root itself, so its depth is len(parts). files
    and folders are the names the folder holds, sorted. Symbolic links are neither followed nor listed, and
    folders leaves out the names SKIPPED_DIRECTORIES gives, so a node_modules costs nothing however large it is.
    The walk then enters the folders still in the list, down to max_depth: a caller removes a name from folders
    to keep the walk out of that folder.
    """
    pending = [(root, ())]
    while pending:
        folder, parts = pending.pop()
        try:
            with os.scandir(folder) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)
        except OSError:
            continue
        files, folders = _entry_names(entries)
        yield folder, parts, files, folders
        if max_depth is None or len(parts) < max_depth:
            pending.extend((folder / name, (*parts, name)) for name in reversed(folders))


def _technology(name: str, version: str | None) -> str:
    return f"{name} {version}" if version else name


def _json_manifest(path: Path) -> dict:
    text = read_manifest_text(path)
    try:
        data = json.loads(text) if text else None
    except RecursionError as error:
        raise ValueError(f"{path.as_posix()}: JSON nested too deeply") from error
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _toml_manifest(path: Path) -> dict:
    text = read_manifest_text(path)
    try:
        data = tomllib.loads(text) if text else None
    except (tomllib.TOMLDecodeError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _table(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _single_line(name: object) -> str | None:
    return name.strip() if isinstance(name, str) and len(name.strip().splitlines()) == 1 else None


def detected_project_name(root: Path) -> str:
    """The name of the root package.json, else of the root Cargo.toml package, else the folder's name."""
    name = _single_line(_json_manifest(root / "package.json").get("name"))
    return name or _single_line(_table(_toml_manifest(root / "Cargo.toml"), "package").get("name")) \
        or root.name or "Project"


def _package_json(component: DetectedComponent, path: Path, label: str) -> None:
    data = _json_manifest(path)
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        dependencies = data.get(field)
        if not isinstance(dependencies, dict):
            continue
        for package, spec in dependencies.items():
            name = NPM_PACKAGES.get(package)
            if name:
                version = None if name in UNVERSIONED else declared_version(spec)
                note = _sdk_note(spec) if name in UNVERSIONED else ""
                component.add(name, version, label, inferred=name in INFERRED, note=note)
    engines = data.get("engines")
    if isinstance(engines, dict) and "node" in engines:
        component.add("Node.js", declared_version(engines["node"]), label)


def _python_requirement(component: DetectedComponent, line: str, label: str) -> None:
    match = _REQUIREMENT.match(line)
    if not match:
        return
    package = match.group(1).lower().replace("_", "-")
    name = PYTHON_PACKAGES.get(package)
    if name:
        spec = match.group(2).strip().removeprefix("(").removesuffix(")")
        version = None if name in UNVERSIONED else declared_version(spec)
        note = _sdk_note(spec) if name in UNVERSIONED else ""
        component.add(name, version, label, inferred=name in INFERRED, note=note)


def _pyproject(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path)
    try:
        data = tomllib.loads(text) if text else {}
    except tomllib.TOMLDecodeError:
        return
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    component.add("Python", declared_version(project.get("requires-python")), label)
    requirements = list(project.get("dependencies") or [])
    for group in (project.get("optional-dependencies") or {}).values():
        if isinstance(group, list):
            requirements.extend(group)
    for group in (data.get("dependency-groups") or {}).values():
        if isinstance(group, list):
            requirements.extend(item for item in group if isinstance(item, str))
    for requirement in requirements:
        if isinstance(requirement, str):
            _python_requirement(component, requirement, label)
    poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    if isinstance(poetry, dict):
        for section in ("dependencies", "dev-dependencies"):
            for package, spec in (poetry.get(section) or {}).items():
                if package.lower() == "python":
                    component.add("Python", declared_version(spec), label)
                    continue
                name = PYTHON_PACKAGES.get(package.lower())
                if name:
                    spec = spec.get("version") if isinstance(spec, dict) else spec
                    version = None if name in UNVERSIONED else declared_version(spec)
                    note = _sdk_note(spec) if name in UNVERSIONED else ""
                    component.add(name, version, label, inferred=name in INFERRED, note=note)


def _requirements(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path) or ""
    component.add("Python", None, label)
    for line in text.splitlines():
        if not line.strip().startswith(("#", "-")):
            _python_requirement(component, line, label)


def _go_mod(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path) or ""
    version = re.search(r"(?m)^go\s+(\d+(?:\.\d+){0,2})", text)
    component.add("Go", version.group(1) if version else None, label)
    for module, name in GO_MODULES.items():
        if module in text:
            component.add(name, None, label, inferred=True)


def _cargo_dependencies(data: dict) -> list[dict]:
    """Every dependency table of a manifest: the package's, its target-specific ones and the workspace's."""
    kinds = ("dependencies", "dev-dependencies", "build-dependencies")
    tables = [_table(data, kind) for kind in kinds] + [_table(_table(data, "workspace"), "dependencies")]
    for target in _table(data, "target").values():
        tables.extend(_table(target, kind) for kind in kinds if isinstance(target, dict))
    return tables


def _cargo(component: DetectedComponent, path: Path, label: str) -> None:
    """A Cargo.toml names the Rust version, the edition and the crates; a workspace root can state the first two
    for its members, which then write `workspace = true`, and the versions of their crates."""
    data = _toml_manifest(path)
    package, shared = _table(data, "package"), _table(_table(data, "workspace"), "package")

    def declared(key: str) -> str | None:
        return next((value for value in map(declared_version, (package.get(key), shared.get(key))) if value), None)

    component.add("Rust", declared("rust-version"), label)
    if declared("edition"):
        component.add("Rust edition", declared("edition"), label)
    for table in _cargo_dependencies(data):
        for crate, spec in table.items():
            spec = spec if isinstance(spec, dict) else {"version": spec}
            package_name = spec["package"] if isinstance(spec.get("package"), str) else crate
            name = CARGO_CRATES.get(package_name.lower().replace("_", "-"))
            if name:
                component.add(name, declared_version(spec.get("version")), label)


def _cargo_folders(directory: Path, patterns: object) -> list[Path]:
    """The folders below directory that a workspace's `members` or `exclude` list names, globs expanded.

    A pattern that leaves the folder, a link and a folder without a Cargo.toml are left out, so that a member
    never reaches files outside the project."""
    folders: list[Path] = []
    for pattern in patterns[:MAX_WORKSPACE_MEMBERS] if isinstance(patterns, list) else []:
        if not isinstance(pattern, str) or pattern.startswith(("/", "\\")) or ".." in pattern.split("/") \
                or re.match(r"[A-Za-z]:", pattern):
            continue
        try:
            matches = list(itertools.islice(directory.glob(pattern), MAX_WORKSPACE_MEMBERS))
        except (ValueError, NotImplementedError, OSError, RecursionError):
            continue
        for match in matches:
            current, plain = directory, True
            for part in match.relative_to(directory).parts:
                current = current / part
                plain = plain and part not in SKIPPED_DIRECTORIES and not current.is_symlink()
            if plain and (match / "Cargo.toml").is_file() and not (match / "Cargo.toml").is_symlink():
                folders.append(match)
    return folders


def _cargo_members(directory: Path) -> list[Path]:
    """The folders of the workspace that the Cargo.toml of directory declares, less its excluded ones."""
    workspace = _table(_toml_manifest(directory / "Cargo.toml"), "workspace")
    excluded = set(_cargo_folders(directory, workspace.get("exclude")))
    return [member for member in _cargo_folders(directory, workspace.get("members")) if member not in excluded]


def _maven(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path) or ""
    component.add("Java", declared_version(_xml_value(text, "java.version") or _xml_value(text, "maven.compiler.release")), label)
    if "spring-boot" in text:
        parent = re.search(r"<artifactId>spring-boot-starter-parent</artifactId>\s*<version>([^<]+)</version>", text)
        component.add("Spring Boot", declared_version(parent.group(1)) if parent else None, label)


def _xml_value(text: str, tag: str) -> str | None:
    match = re.search(rf"<{re.escape(tag)}>([^<]+)</{re.escape(tag)}>", text)
    return match.group(1) if match else None


def _csproj(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path) or ""
    framework = re.search(r"<TargetFrameworks?>\s*net(\d+(?:\.\d+)?)", text)
    component.add(".NET", framework.group(1) if framework else None, label)
    if "Microsoft.NET.Sdk.Web" in text or "Microsoft.AspNetCore" in text:
        component.add("ASP.NET Core", framework.group(1) if framework else None, label)


def _gemfile(component: DetectedComponent, path: Path, label: str) -> None:
    """A Gemfile names the Ruby version and the gems; Rails comes from its gem."""
    text = read_manifest_text(path) or ""
    ruby = re.search(r"""(?m)^\s*ruby\s+["']([^"']+)["']""", text)
    component.add("Ruby", declared_version(ruby.group(1)) if ruby else None, label)
    for gem, spec in _GEM.findall(text):
        name = RUBY_GEMS.get(gem)
        if name in UNVERSIONED:
            component.add(name, None, label, note=_sdk_note(spec))
        elif name:
            component.add(name, declared_version(spec), label, inferred=name in INFERRED)


def _composer(component: DetectedComponent, path: Path, label: str) -> None:
    data = _json_manifest(path)
    if not data:
        return
    requirements = data.get("require") if isinstance(data.get("require"), dict) else {}
    component.add("PHP", declared_version(requirements.get("php")), label)
    for package, spec in requirements.items():
        name = COMPOSER_PACKAGES.get(package)
        if name in UNVERSIONED:
            component.add(name, None, label, note=_sdk_note(spec))
        elif name:
            component.add(name, declared_version(spec), label)


def _xcode_project(component: DetectedComponent, path: Path, label: str) -> None:
    """An Xcode project builds Swift code; its SDK setting tells an iOS app from a Mac one."""
    text = read_manifest_text(path / "project.pbxproj") or ""
    swift = re.search(r"SWIFT_VERSION\s*=\s*\"?(\d+(?:\.\d+)?)", text)
    component.add("Swift", swift.group(1) if swift else None, label)
    ios = re.findall(r'IPHONEOS_DEPLOYMENT_TARGET\s*=\s*"?(\d+(?:\.\d+){0,2})', text)
    if ios or re.search(r"SDKROOT\s*=\s*\"?iphoneos", text):
        component.add("iOS", min(ios, key=version_key) if ios else None, label)


def _swift_package(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path) or ""
    tools = re.search(r"swift-tools-version:\s*(\d+(?:\.\d+){0,2})", text)
    component.add("Swift", tools.group(1) if tools else None, label)
    if re.search(r"\.iOS\s*\(", text):
        ios = re.search(r"""\.iOS\s*\(\s*(?:"(\d+(?:\.\d+){0,2})"|\.v(\d+(?:_\d+){0,2}))""", text)
        version = (ios.group(1) or ios.group(2)).replace("_", ".") if ios else None
        component.add("iOS", version, label)


def _terraform(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path) or ""
    component.add("Terraform", None, label)
    if re.search(r"""provider\s+"aws"|hashicorp/aws""", text):
        component.add("AWS", None, label)


def _container_images(component: DetectedComponent, path: Path, label: str) -> None:
    text = read_manifest_text(path) or ""
    pattern = r"(?mi)(?:^\s*FROM\s+|image:\s*['\"]?)([a-z0-9./_-]+)(?::([A-Za-z0-9._-]+))?"
    for image, tag in re.findall(pattern, text):
        for prefix in IMAGE_PREFIXES:
            if image.lower().startswith(prefix):
                image = image[len(prefix):]
                break
        name = IMAGES.get(image.lower())
        if name:
            version = _VERSION.search(tag)
            component.add(name, version.group(0) if version else None, label)


def _kubernetes(component: DetectedComponent, path: Path, label: str) -> None:
    documents = re.split(r"(?m)^(?:---|\.\.\.)(?:[ \t]+#.*)?[ \t]*$", read_manifest_text(path) or "")
    for document in documents:
        version, kind = _KUBE_API.search(document), _KUBE_KIND.search(document)
        if not version or not kind:
            continue
        component.add("Kubernetes", None, label)
        group = version.group(1) or ""
        if group == "argoproj.io" and kind.group(1) in ("Application", "ApplicationSet", "AppProject"):
            component.add("Argo CD", None, label)
        elif group.endswith(".toolkit.fluxcd.io"):
            component.add("Flux", None, label)


def _mix(component: DetectedComponent, path: Path, label: str) -> None:
    """A mix.exs makes an Elixir project, with the version its `elixir:` requirement gives; a `{:phoenix, ...}`
    dependency makes it a Phoenix application. Phoenix's own libraries (phoenix_html, phoenix_pubsub) alone do not."""
    text = read_manifest_text(path) or ""
    elixir = _MIX_ELIXIR.search(text)
    component.add("Elixir", declared_version(elixir.group(1)) if elixir else None, label)
    phoenix = _MIX_PHOENIX.search(text)
    if phoenix:
        component.add("Phoenix", declared_version(phoenix.group(1)), label)


def _dbt_project(component: DetectedComponent, path: Path, label: str) -> None:
    """A dbt project; its version is the range `require-dbt-version` declares, as a string or a list of strings."""
    found = _DBT_VERSION.search(read_manifest_text(path) or "")
    ranges = re.findall(r"""["']([^"']*)["']""", found.group(1)) if found else []
    component.add("dbt", declared_version(",".join(ranges)) if ranges else None, label)


def _airflow_dags(folder: Path) -> bool:
    """Whether a dags folder holds a DAG file: a Python file at its top that imports Airflow."""
    try:
        files = sorted(entry for entry in folder.iterdir() if entry.suffix == ".py" and entry.is_file())
    except OSError:
        return False
    return any(_AIRFLOW_IMPORT.search(read_manifest_text(entry) or "") for entry in files[:MAX_WORKSPACE_MEMBERS])


def _pubspec(component: DetectedComponent, path: Path, label: str) -> None:
    """A pubspec.yaml makes a Dart package; a dependency on the Flutter SDK (`sdk: flutter`) makes it a Flutter one.

    The environment section gives the Dart SDK constraint and, for Flutter, the Flutter constraint. Only these
    lines are read, without a YAML parser: a comment that names Flutter is not a dependency on its SDK.
    """
    text = read_manifest_text(path) or ""
    environment = re.search(r"(?m)^environment:[ \t]*(?:#.*)?\n((?:[ \t]+.*\n?|[ \t]*\n)*)", text)
    block = environment.group(1) if environment else ""

    def constraint(key: str) -> str | None:
        found = re.search(rf"""(?m)^[ \t]+{key}:[ \t]*["']?([^"'#\n]+?)["']?[ \t]*(?:#.*)?$""", block)
        return declared_version(found.group(1)) if found else None

    component.add("Dart", constraint("sdk"), label)
    if re.search(r"""(?m)^[ \t]+sdk:[ \t]*["']?flutter["']?[ \t]*(?:#.*)?$""", text):
        component.add("Flutter", constraint("flutter"), label)


def _parse(component: DetectedComponent, path: Path, label: str, root: Path) -> None:
    name = path.name
    if name == "package.json":
        _package_json(component, path, label)
    elif name == "pyproject.toml":
        _pyproject(component, path, label)
    elif re.fullmatch(r"requirements[\w.-]*\.txt", name):
        _requirements(component, path, label)
    elif name == "go.mod":
        _go_mod(component, path, label)
    elif name == "pom.xml":
        _maven(component, path, label)
    elif name in ("build.gradle", "build.gradle.kts"):
        gradle_components(component, path, label, root)
    elif name.endswith(".csproj"):
        _csproj(component, path, label)
    elif name in ("Dockerfile", "Containerfile") or re.fullmatch(r"Dockerfile\.[\w.-]+|[\w.-]+\.Dockerfile", name):
        component.add("Docker", None, label)
        _container_images(component, path, label)
    elif re.fullmatch(r"(docker-)?compose[\w.-]*\.ya?ml", name):
        _container_images(component, path, label)
    elif name == "Gemfile":
        _gemfile(component, path, label)
    elif name == "composer.json":
        _composer(component, path, label)
    elif name == "Cargo.toml":
        _cargo(component, path, label)
    elif name == "mix.exs":
        _mix(component, path, label)
    elif name == "pubspec.yaml":
        _pubspec(component, path, label)
    elif name == "Package.swift":
        _swift_package(component, path, label)
    elif name == "manage.py" and "django" in (read_manifest_text(path) or ""):
        component.add("Python", None, label)
        component.add("Django", None, label)
    elif name == ".gitlab-ci.yml":
        component.add("GitLab CI", None, label)
    elif name == "tsconfig.json":
        component.add("TypeScript", None, label)
    elif re.fullmatch(r"vite\.config\.[cm]?[jt]s", name):
        component.add("Vite", None, label)
    elif name in ("dbt_project.yml", "dbt_project.yaml"):
        _dbt_project(component, path, label)
    elif name == "wp-config.php":
        component.add("WordPress", None, label)
    elif name.endswith(".tf"):
        _terraform(component, path, label)
    elif name in ("Chart.yaml", "kustomization.yaml", "kustomization.yml"):
        component.add("Kubernetes", None, label)
    elif path.suffix in (".yaml", ".yml"):
        _kubernetes(component, path, label)


def _component_id(relative: str, taken: set[str]) -> str:
    base = "root" if relative == "." else re.sub(r"[^a-z0-9]+", "-", relative.lower()).strip("-") or "component"
    candidate, counter = base[:48], 2
    while candidate in taken:
        candidate = f"{base[:44]}-{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def _kustomize_base(relative: str, names: list[str]) -> str:
    """A Kustomize overlay or base folder (k2/overlays/prod, k2/base) belongs to the application above it."""
    if not any(name in ("kustomization.yaml", "kustomization.yml", "Kustomization") for name in names):
        return relative
    parts = relative.split("/")
    layout = next((index for index, part in enumerate(parts) if part in ("overlays", "base", "bases")), None)
    if layout is None or relative == ".":
        return relative
    return "/".join(parts[:layout]) or "."


def detect_stack(root: Path, listings: dict[str, set[str]] | None = None) -> dict:
    """Return the components found under root, each with its technologies and evidence.

    listings, when given, receives the files of each folder walked, by path below root ("." for root), so that
    propose_checks can use them instead of walking the tree again.
    """
    root = root.resolve()
    components: dict[str, DetectedComponent] = {}
    module_roots: dict[Path, str] = {}
    # Each file and marker folder, keyed by its path parts below root: read in that order, a folder's entries come
    # in name order with each subfolder's content in its place, so the first evidence of a technology stays the same.
    found: list[tuple[tuple[str, ...], str, Path, str]] = []
    for directory, parts, files, folders in walk(root, MAX_DEPTH):
        relative = "/".join(parts) or "."
        if listings is not None:
            listings[relative] = set(files)
        names = files + folders
        if any(name in ("settings.gradle", "settings.gradle.kts") for name in names):
            for module in gradle_modules(directory):
                module_roots[module] = relative
        if "Cargo.toml" in files:
            for member in _cargo_members(directory):
                module_roots[member] = relative
        if "mix.exs" in files:
            folders[:] = [name for name in folders if name not in MIX_OUTPUT]
        relative = _kustomize_base(module_roots.get(directory, relative), names)
        found += [((*parts, name), "file", directory / name, relative) for name in files]
        for name in [name for name in folders if name.endswith(".xcodeproj")]:
            found.append(((*parts, name), "xcode", directory / name, relative))
            folders.remove(name)
        if "wp-content" in folders and len(parts) < MAX_DEPTH:
            found.append(((*parts, "wp-content"), "wordpress", directory / "wp-content", relative))
        # Airflow reads its DAGs from a dags folder; one whose files import Airflow makes its parent an Airflow project.
        if "dags" in folders and len(parts) < MAX_DEPTH and _airflow_dags(directory / "dags"):
            found.append(((*parts, "dags"), "airflow", directory / "dags", relative))
    for key, kind, entry, relative in sorted(found, key=lambda item: item[0]):
        component = components.setdefault(relative, DetectedComponent(relative))
        label = "/".join(key)
        if kind == "file":
            _parse(component, entry, label, root)
        elif kind == "xcode":
            _xcode_project(component, entry, label)
        elif kind == "airflow":
            component.add("Apache Airflow", None, label)
        else:
            component.add("WordPress", None, label)
    workflows = root / ".github" / "workflows"
    if workflows.is_dir() and any(path.suffix in (".yml", ".yaml") for path in workflows.iterdir()):
        components.setdefault(".", DetectedComponent(".")).add("GitHub Actions", None, ".github/workflows")

    taken: set[str] = set()
    result = []
    for relative in sorted(components):
        component = components[relative]
        if not component.technologies:
            continue
        technologies = sorted(component.technologies.values(), key=lambda item: item["name"].casefold())
        result.append(
            {
                "id": _component_id(relative, taken),
                "path": relative,
                "stack": [_technology(item["name"], item["version"]) for item in technologies],
                "evidence": technologies,
            }
        )
    return {"components": result}


def components_for_profile(detected: dict) -> list[dict]:
    """Keep the fields the profile stores; evidence stays in the detection report."""
    return [{key: component[key] for key in ("id", "path", "stack")} for component in detected["components"]]
