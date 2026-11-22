"""Propose the project's components and technologies from the files in the repository.

Detection only reads local manifests. It never runs a package manager or opens the
network, and the team confirms or corrects the proposal before it reaches the profile.
"""

import json
import re
import tomllib
from pathlib import Path

from .stack_versions import declared_version, version_key

SKIPPED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".openguildkit", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", ".next", ".nuxt", "vendor", "coverage", ".tox", ".mypy_cache",
}
MAX_DEPTH = 4
MAX_MANIFEST_BYTES = 2_000_000

NPM_PACKAGES = {
    "next": "Next.js",
    "react": "React",
    "vue": "Vue",
    "@angular/core": "Angular",
    "svelte": "Svelte",
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
}
GO_MODULES = {
    "github.com/jackc/pgx": "PostgreSQL",
    "github.com/lib/pq": "PostgreSQL",
}
RUBY_GEMS = {"rails": "Rails", "pg": "PostgreSQL", "mysql2": "MySQL"}
COMPOSER_PACKAGES = {"laravel/framework": "Laravel"}
IMAGES = {"postgres": "PostgreSQL", "postgis/postgis": "PostgreSQL"}
IMAGE_PREFIXES = ("docker.io/library/", "docker.io/", "library/")
INFERRED = {"PostgreSQL", "MySQL"}
UNVERSIONED = {"AWS", "Stripe"}  # SDK versions are not the versions of the services they use.
ANDROID_NOTE = "the platform has no version of its own; see Android SDK and Android Gradle Plugin"


def _sdk_note(spec: object) -> str:
    """Why a service reached through an SDK has no version: the SDK's declared version is not the service's."""
    declared = declared_version(spec)
    if not declared:
        return "the service itself has no version"
    exact = declared[0].isdigit()
    return f"SDK {'==' if exact else ''}{declared}, the service itself has no version"

_VERSION = re.compile(r"\d+(?:\.\d+){0,2}")
_GEM = re.compile(r"""(?m)^\s*gem\s+["']([\w.-]+)["'](?:\s*,\s*["']([^"']+)["'])?""")
_ANDROID_PLUGIN = re.compile(r"com\.android\.(?:application|library|tools\.build:gradle)|"
                             r"libs\.plugins\.android\.(?:application|library)")
_KOTLIN_PLUGIN = re.compile(r"org\.jetbrains\.kotlin|kotlin\(\s*[\"']|kotlin-android|libs\.plugins\.kotlin|"
                            r"plugin:\s*[\"']kotlin[\"'-]")
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*([^;#]*)")
_KUBE_API = re.compile(r"""(?m)^apiVersion:[ \t]+["']?(?:([a-z0-9.-]+)/)?v\d+(?:[a-z]+\d+)?["']?[ \t]*(?:#.*)?$""")
_KUBE_KIND = re.compile(r"""(?m)^kind:[ \t]+["']?([A-Z][A-Za-z0-9]*)["']?[ \t]*(?:#.*)?$""")


def _technology(name: str, version: str | None) -> str:
    return f"{name} {version}" if version else name


class _Component:
    def __init__(self, path: str):
        self.path = path
        self.technologies: dict[str, dict] = {}

    def add(self, name: str, version: str | None, evidence: str, inferred: bool = False, note: str = "") -> None:
        if inferred:
            # A client library's version says nothing about the server it talks to.
            version = None
        current = self.technologies.get(name)
        if current is None or (version and not current["version"]):
            self.technologies[name] = {
                "name": name,
                "version": version,
                "evidence": evidence,
                "inferred": inferred,
            }
            # Why a technology carries no version although its manifest is read.
            if note and not version:
                self.technologies[name]["note"] = note


def _read_text(path: Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None


def _json_manifest(path: Path) -> dict:
    text = _read_text(path)
    try:
        data = json.loads(text) if text else None
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def detected_project_name(root: Path) -> str:
    name = _json_manifest(root / "package.json").get("name")
    if isinstance(name, str) and len(name.strip().splitlines()) == 1:
        return name.strip()
    return root.name or "Project"


def _package_json(component: _Component, path: Path, label: str) -> None:
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


def _python_requirement(component: _Component, line: str, label: str) -> None:
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


def _pyproject(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path)
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


def _requirements(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    component.add("Python", None, label)
    for line in text.splitlines():
        if not line.strip().startswith(("#", "-")):
            _python_requirement(component, line, label)


def _go_mod(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    version = re.search(r"(?m)^go\s+(\d+(?:\.\d+){0,2})", text)
    component.add("Go", version.group(1) if version else None, label)
    for module, name in GO_MODULES.items():
        if module in text:
            component.add(name, None, label, inferred=True)


def _maven(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    component.add("Java", declared_version(_xml_value(text, "java.version") or _xml_value(text, "maven.compiler.release")), label)
    if "spring-boot" in text:
        parent = re.search(r"<artifactId>spring-boot-starter-parent</artifactId>\s*<version>([^<]+)</version>", text)
        component.add("Spring Boot", declared_version(parent.group(1)) if parent else None, label)


def _gradle_plugin_version(text: str, plugin: str) -> str | None:
    # The group keeps an alternation in plugin from splitting the whole expression.
    match = re.search(rf"""(?:{plugin})['"]?\)?\s+version\s*\(?\s*['"]([^'"]+)""", text)
    return declared_version(match.group(1)) if match else None


def _gradle_catalog_plugins(path: Path, text: str) -> dict:
    aliases = set(re.findall(r"\blibs\.plugins\.([a-zA-Z0-9.]+)", text))
    if not aliases:
        return {}
    try:
        catalog = tomllib.loads(_read_text(path) or "")
    except tomllib.TOMLDecodeError:
        return {}
    versions = catalog.get("versions", {})
    plugins = catalog.get("plugins", {})
    if not isinstance(versions, dict) or not isinstance(plugins, dict):
        return {}
    found = {}
    for alias, item in plugins.items():
        if re.sub(r"[-_]", ".", alias) in aliases and isinstance(item, dict) and isinstance(item.get("id"), str):
            version = item.get("version")
            if isinstance(version, dict):
                version = versions.get(version.get("ref", ""))
            found[item["id"]] = declared_version(version)
    return found


def _gradle(component: _Component, path: Path, label: str, root: Path) -> None:
    text = _read_text(path) or ""
    java = re.search(r"""(?:jvmToolchain|JavaLanguageVersion\.of)\s*\(\s*(\d+)|"""
                     r"""sourceCompatibility\s*(?:=\s*)?(?:JavaVersion\.VERSION_|["']?)(\d+(?:[._]\d+)?)""", text)
    catalog_path = root / component.path / "gradle" / "libs.versions.toml"
    catalog_label = catalog_path.relative_to(root).as_posix()
    catalog = _gradle_catalog_plugins(catalog_path, text)
    kotlin = next((version for plugin, version in catalog.items() if plugin.startswith("org.jetbrains.kotlin.")), None)
    has_kotlin = _KOTLIN_PLUGIN.search(text) or any(plugin.startswith("org.jetbrains.kotlin.") for plugin in catalog)
    if java or not has_kotlin:
        component.add("Java", (java.group(1) or java.group(2)).replace("_", ".") if java else None, label)
    if has_kotlin:
        explicit = _gradle_plugin_version(text, r"""org\.jetbrains\.kotlin\.[\w-]+|kotlin\(\s*['"][\w-]+""")
        classpath = re.search(r"""org\.jetbrains\.kotlin:kotlin-gradle-plugin:([^'"\s]+)""", text)
        # An old-style build names the version in a variable: ext.kotlin_version = '1.9.24'.
        variable = re.search(r"""\bkotlin_version\s*=\s*['"]([^'"]+)['"]""", text)
        version = explicit or (declared_version(classpath.group(1)) if classpath else None) \
            or (declared_version(variable.group(1)) if variable else None)
        component.add("Kotlin", version or kotlin, label if version or not kotlin else catalog_label)
    android = next((version for plugin, version in catalog.items() if plugin.startswith("com.android.")), None)
    if _ANDROID_PLUGIN.search(text) or any(plugin.startswith("com.android.") for plugin in catalog):
        component.add("Android", None, label, note=ANDROID_NOTE)
        sdk = re.search(r"\bcompileSdk(?:Version)?\s*(?:=\s*|\(\s*)?(\d+)", text)
        if sdk:
            component.add("Android SDK", sdk.group(1), label)
        explicit = _gradle_plugin_version(text, r"com\.android\.(?:application|library)")
        classpath = re.search(r"""com\.android\.tools\.build:gradle:([^'"\s]+)""", text)
        version = explicit or (declared_version(classpath.group(1)) if classpath else None)
        if version or android:
            component.add("Android Gradle Plugin", version or android, label if version else catalog_label)
    plugin = _gradle_plugin_version(text, r"org\.springframework\.boot")
    if plugin or "spring-boot" in text:
        component.add("Spring Boot", plugin, label)


def _gradle_modules(directory: Path) -> list[Path]:
    settings = _read_text(directory / "settings.gradle.kts") or _read_text(directory / "settings.gradle") or ""
    modules = []
    for arguments, line in re.findall(r"(?m)^[ \t]*include(?:[ \t]*\(([^)]*)\)|[ \t]+([^\n/]*))", settings):
        for name in re.findall(r"""["'](:?[\w.-]+(?::[\w.-]+)*)["']""", arguments or line):
            parts = name.lstrip(":").split(":")
            if not {".", ".."}.intersection(parts):
                modules.append(directory.joinpath(*parts))
    return modules


def _xml_value(text: str, tag: str) -> str | None:
    match = re.search(rf"<{re.escape(tag)}>([^<]+)</{re.escape(tag)}>", text)
    return match.group(1) if match else None


def _csproj(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    framework = re.search(r"<TargetFrameworks?>\s*net(\d+(?:\.\d+)?)", text)
    component.add(".NET", framework.group(1) if framework else None, label)
    if "Microsoft.NET.Sdk.Web" in text or "Microsoft.AspNetCore" in text:
        component.add("ASP.NET Core", framework.group(1) if framework else None, label)


def _gemfile(component: _Component, path: Path, label: str) -> None:
    """A Gemfile names the Ruby version and the gems; Rails comes from its gem."""
    text = _read_text(path) or ""
    ruby = re.search(r"""(?m)^\s*ruby\s+["']([^"']+)["']""", text)
    component.add("Ruby", declared_version(ruby.group(1)) if ruby else None, label)
    for gem, spec in _GEM.findall(text):
        name = RUBY_GEMS.get(gem)
        if name:
            component.add(name, declared_version(spec), label, inferred=name in INFERRED)


def _composer(component: _Component, path: Path, label: str) -> None:
    data = _json_manifest(path)
    if not data:
        return
    requirements = data.get("require") if isinstance(data.get("require"), dict) else {}
    component.add("PHP", declared_version(requirements.get("php")), label)
    for package, spec in requirements.items():
        name = COMPOSER_PACKAGES.get(package)
        if name:
            component.add(name, declared_version(spec), label)


def _xcode_project(component: _Component, path: Path, label: str) -> None:
    """An Xcode project builds Swift code; its SDK setting tells an iOS app from a Mac one."""
    text = _read_text(path / "project.pbxproj") or ""
    swift = re.search(r"SWIFT_VERSION\s*=\s*\"?(\d+(?:\.\d+)?)", text)
    component.add("Swift", swift.group(1) if swift else None, label)
    ios = re.findall(r'IPHONEOS_DEPLOYMENT_TARGET\s*=\s*"?(\d+(?:\.\d+){0,2})', text)
    if ios or re.search(r"SDKROOT\s*=\s*\"?iphoneos", text):
        component.add("iOS", min(ios, key=version_key) if ios else None, label)


def _swift_package(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    tools = re.search(r"swift-tools-version:\s*(\d+(?:\.\d+){0,2})", text)
    component.add("Swift", tools.group(1) if tools else None, label)
    if re.search(r"\.iOS\s*\(", text):
        ios = re.search(r"""\.iOS\s*\(\s*(?:"(\d+(?:\.\d+){0,2})"|\.v(\d+(?:_\d+){0,2}))""", text)
        version = (ios.group(1) or ios.group(2)).replace("_", ".") if ios else None
        component.add("iOS", version, label)


def _terraform(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    component.add("Terraform", None, label)
    if re.search(r"""provider\s+"aws"|hashicorp/aws""", text):
        component.add("AWS", None, label)


def _container_images(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
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


def _kubernetes(component: _Component, path: Path, label: str) -> None:
    documents = re.split(r"(?m)^(?:---|\.\.\.)(?:[ \t]+#.*)?[ \t]*$", _read_text(path) or "")
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


def _parse(component: _Component, path: Path, label: str, root: Path) -> None:
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
        _gradle(component, path, label, root)
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
    elif name == "Package.swift":
        _swift_package(component, path, label)
    elif name == "manage.py" and "django" in (_read_text(path) or ""):
        component.add("Python", None, label)
        component.add("Django", None, label)
    elif name == ".gitlab-ci.yml":
        component.add("GitLab CI", None, label)
    elif name == "tsconfig.json":
        component.add("TypeScript", None, label)
    elif re.fullmatch(r"vite\.config\.[cm]?[jt]s", name):
        component.add("Vite", None, label)
    elif name in ("dbt_project.yml", "dbt_project.yaml"):
        component.add("dbt", None, label)
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


def detect_stack(root: Path) -> dict:
    """Return the components found under root, each with its technologies and evidence."""
    root = root.resolve()
    components: dict[str, _Component] = {}
    gradle_roots: dict[Path, str] = {}

    def visit(directory: Path, depth: int) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError:
            return
        relative = directory.relative_to(root).as_posix() or "."
        if any(entry.name in ("settings.gradle", "settings.gradle.kts") for entry in entries):
            for module in _gradle_modules(directory):
                gradle_roots[module] = relative
        relative = gradle_roots.get(directory, relative)
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_file():
                component = components.setdefault(relative, _Component(relative))
                label = entry.relative_to(root).as_posix()
                _parse(component, entry, label, root)
            elif entry.is_dir() and entry.name.endswith(".xcodeproj"):
                component = components.setdefault(relative, _Component(relative))
                _xcode_project(component, entry, entry.relative_to(root).as_posix())
            elif entry.is_dir() and depth < MAX_DEPTH and entry.name not in SKIPPED_DIRECTORIES:
                if entry.name == "wp-content":
                    component = components.setdefault(relative, _Component(relative))
                    component.add("WordPress", None, entry.relative_to(root).as_posix())
                visit(entry, depth + 1)

    visit(root, 0)
    workflows = root / ".github" / "workflows"
    if workflows.is_dir() and any(path.suffix in (".yml", ".yaml") for path in workflows.iterdir()):
        components.setdefault(".", _Component(".")).add("GitHub Actions", None, ".github/workflows")

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
