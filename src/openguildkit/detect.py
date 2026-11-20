"""Propose the project's components and technologies from the files in the repository.

Detection only reads local manifests. It never runs a package manager or opens the
network, and the team confirms or corrects the proposal before it reaches the profile.
"""

import json
import re
import tomllib
from pathlib import Path

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
    "jest": "Jest",
    "storybook": "Storybook",
    "pg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "prisma": "Prisma",
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
}
GO_MODULES = {
    "github.com/jackc/pgx": "PostgreSQL",
    "github.com/lib/pq": "PostgreSQL",
}
IMAGES = {"postgres": "PostgreSQL", "postgis/postgis": "PostgreSQL"}
INFERRED = {"PostgreSQL"}

_VERSION = re.compile(r"\d+(?:\.\d+){0,2}")
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(?:(==|~=|>=|===)\s*([0-9][^,;\s]*))?")


def _version(spec: object) -> str | None:
    """Return the lowest version a dependency range allows, or None when it is not stated."""
    if not isinstance(spec, str):
        return None
    if spec.strip().startswith(("workspace:", "file:", "link:", "git", "http", "npm:")):
        return None
    match = _VERSION.search(spec)
    return match.group(0) if match else None


def _technology(name: str, version: str | None) -> str:
    return f"{name} {version}" if version else name


class _Component:
    def __init__(self, path: str):
        self.path = path
        self.technologies: dict[str, dict] = {}

    def add(self, name: str, version: str | None, evidence: str, inferred: bool = False) -> None:
        current = self.technologies.get(name)
        if current is None or (version and not current["version"]):
            self.technologies[name] = {
                "name": name,
                "version": version,
                "evidence": evidence,
                "inferred": inferred,
            }


def _read_text(path: Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None


def _package_json(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path)
    try:
        data = json.loads(text) if text else None
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        dependencies = data.get(field)
        if not isinstance(dependencies, dict):
            continue
        for package, spec in dependencies.items():
            name = NPM_PACKAGES.get(package)
            if name:
                component.add(name, _version(spec), label, inferred=name in INFERRED)
    engines = data.get("engines")
    if isinstance(engines, dict) and "node" in engines:
        component.add("Node.js", _version(engines["node"]), label)


def _python_requirement(component: _Component, line: str, label: str) -> None:
    match = _REQUIREMENT.match(line)
    if not match:
        return
    package = match.group(1).lower().replace("_", "-")
    name = PYTHON_PACKAGES.get(package)
    if name:
        version = match.group(3) if match.group(2) in ("==", "~=", ">=", "===") else None
        component.add(name, _version(version), label, inferred=name in INFERRED)


def _pyproject(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path)
    try:
        data = tomllib.loads(text) if text else {}
    except tomllib.TOMLDecodeError:
        return
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    component.add("Python", _version(project.get("requires-python")), label)
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
                    component.add("Python", _version(spec if isinstance(spec, str) else None), label)
                    continue
                name = PYTHON_PACKAGES.get(package.lower())
                if name:
                    version = spec if isinstance(spec, str) else (spec or {}).get("version")
                    component.add(name, _version(version), label, inferred=name in INFERRED)


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
    component.add("Java", _version(_xml_value(text, "java.version") or _xml_value(text, "maven.compiler.release")), label)
    if "spring-boot" in text:
        parent = re.search(r"<artifactId>spring-boot-starter-parent</artifactId>\s*<version>([^<]+)</version>", text)
        component.add("Spring Boot", _version(parent.group(1)) if parent else None, label)


def _gradle(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    component.add("Java", None, label)
    plugin = re.search(r"org\.springframework\.boot['\"]?\)?\s*version\s*['\"]([^'\"]+)", text)
    if plugin or "spring-boot" in text:
        component.add("Spring Boot", _version(plugin.group(1)) if plugin else None, label)


def _xml_value(text: str, tag: str) -> str | None:
    match = re.search(rf"<{re.escape(tag)}>([^<]+)</{re.escape(tag)}>", text)
    return match.group(1) if match else None


def _csproj(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    framework = re.search(r"<TargetFrameworks?>\s*net(\d+(?:\.\d+)?)", text)
    component.add(".NET", framework.group(1) if framework else None, label)
    if "Microsoft.NET.Sdk.Web" in text or "Microsoft.AspNetCore" in text:
        component.add("ASP.NET Core", framework.group(1) if framework else None, label)


def _container_images(component: _Component, path: Path, label: str) -> None:
    text = _read_text(path) or ""
    for image, tag in re.findall(r"(?mi)(?:^\s*FROM\s+|image:\s*['\"]?)([a-z0-9./_-]+):([A-Za-z0-9._-]+)", text):
        name = IMAGES.get(image.split("/", 1)[-1] if image.startswith("docker.io/") else image)
        if name:
            component.add(name, _version(tag), label)


def _parse(component: _Component, path: Path, label: str) -> None:
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
        _gradle(component, path, label)
    elif name.endswith(".csproj"):
        _csproj(component, path, label)
    elif name == "Dockerfile" or re.fullmatch(r"(docker-)?compose[\w.-]*\.ya?ml", name):
        _container_images(component, path, label)
    elif name == "tsconfig.json":
        component.add("TypeScript", None, label)
    elif name.endswith(".tf"):
        component.add("Terraform", None, label)
    elif name in ("Chart.yaml", "kustomization.yaml", "kustomization.yml"):
        component.add("Kubernetes", None, label)


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

    def visit(directory: Path, depth: int) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError:
            return
        relative = directory.relative_to(root).as_posix() or "."
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_file():
                component = components.setdefault(relative, _Component(relative))
                label = entry.relative_to(root).as_posix()
                _parse(component, entry, label)
            elif entry.is_dir() and depth < MAX_DEPTH and entry.name not in SKIPPED_DIRECTORIES:
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
