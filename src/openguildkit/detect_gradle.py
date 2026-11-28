"""Proposes the components a Gradle build declares: Android and Kotlin plugins, Ktor from the build files or the version
catalog, and the modules of the settings.

Entry: gradle_components, gradle_modules
Tests: tests/test_detect_versions.py, tests/test_components.py
"""

import re
import tomllib
from pathlib import Path

from . import lazy_re
from .detect_manifest import DetectedComponent, read_manifest_text
from .stack_versions import declared_version

ANDROID_NOTE = "the platform has no version of its own; see Android SDK and Android Gradle Plugin"


_ANDROID_PLUGIN = lazy_re.compile(r"com\.android\.(?:application|library|tools\.build:gradle)|"
                             r"libs\.plugins\.android\.(?:application|library)")
_KOTLIN_PLUGIN = lazy_re.compile(r"org\.jetbrains\.kotlin|kotlin\(\s*[\"']|kotlin-android|libs\.plugins\.kotlin|"
                            r"plugin:\s*[\"']kotlin[\"'-]")
# Ktor server: the Gradle plugin, a server artifact, or the server libraries of the Ktor version catalog. The
# client artifacts (ktor-client-*) are not a server, so an Android app that calls an API does not match.
_KTOR_PLUGIN = "io.ktor.plugin"
_KTOR_SERVER_ARTIFACT = lazy_re.compile(r"""io\.ktor:ktor-server-[\w-]+(?::([^'"\s)]+))?""")
_KTOR_BOM = lazy_re.compile(r"""io\.ktor:ktor-bom:([^'"\s)]+)""")
_KTOR_SETTINGS_CATALOG = lazy_re.compile(
    r"""create\(\s*["'](\w+)["']\s*\)\s*\{\s*from\(\s*["']io\.ktor:ktor-version-catalog:([^"']+)["']""")


def _gradle_plugin_version(text: str, plugin: str) -> str | None:
    # The group keeps an alternation in plugin from splitting the whole expression.
    match = re.search(rf"""(?:{plugin})['"]?\)?\s+version\s*\(?\s*['"]([^'"]+)""", text)
    return declared_version(match.group(1)) if match else None


def _gradle_catalog_plugins(path: Path, text: str) -> dict:
    aliases = set(re.findall(r"\blibs\.plugins\.([a-zA-Z0-9.]+)", text))
    if not aliases:
        return {}
    try:
        catalog = tomllib.loads(read_manifest_text(path) or "")
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


def _gradle_variable(name: str, text: str, directory: Path) -> str | None:
    """The value of a variable a version names: an assignment in the build script, or gradle.properties."""
    assigned = re.search(rf"""\b{re.escape(name)}\s*=\s*['"]([^'"]+)['"]""", text)
    if assigned:
        return assigned.group(1)
    properties = read_manifest_text(directory / "gradle.properties") or ""
    declared = re.search(rf"(?m)^[ \t]*{re.escape(name)}[ \t]*[=:][ \t]*(\S+)", properties)
    return declared.group(1) if declared else None


def _gradle_declared(token: str, text: str, directory: Path) -> str | None:
    """A version written in a dependency: a number, or $name and ${name} for a variable."""
    variable = re.fullmatch(r"\$\{?(\w+)\}?", token)
    return declared_version(_gradle_variable(variable.group(1), text, directory) if variable else token)


def _catalog_version(item: dict, versions: dict) -> str | None:
    version = item.get("version")
    if isinstance(version, dict):
        ref = version.get("ref")
        version = versions.get(ref) if isinstance(ref, str) else next(
            (version[key] for key in ("strictly", "require", "prefer") if isinstance(version.get(key), str)), None)
    return declared_version(version)


def _gradle_catalog_ktor(path: Path, text: str) -> tuple[bool, str | None]:
    """Whether the build uses a Ktor server library or bundle of its catalog, and the version the catalog gives."""
    def accessor(name: str) -> str:
        return re.sub(r"[-_]", ".", name)

    used = {re.sub(r"\.(?:get|asProvider)$", "", name) for name in re.findall(r"\blibs\.([a-zA-Z0-9.]+)", text)}
    if not used:
        return False, None
    try:
        catalog = tomllib.loads(read_manifest_text(path) or "")
    except tomllib.TOMLDecodeError:
        return False, None
    sections = [catalog.get(name, {}) for name in ("versions", "libraries", "bundles")]
    if not all(isinstance(section, dict) for section in sections):
        return False, None
    versions, libraries, bundles = sections
    wanted = {alias for alias in libraries if accessor(alias) in used}
    for name, members in bundles.items():
        if f"bundles.{accessor(name)}" in used and isinstance(members, list):
            wanted.update(member for member in members if member in libraries)
    server, bom = [], []
    for alias in sorted(wanted):
        item = libraries[alias]
        if isinstance(item, str):
            # The short notation: "group:artifact:version".
            group, _, rest = item.partition(":")
            artifact, _, number = rest.partition(":")
            coordinate, version = f"{group}:{artifact}", declared_version(number)
        elif isinstance(item, dict):
            module = item.get("module")
            coordinate = module if isinstance(module, str) else f"{item.get('group')}:{item.get('name')}"
            version = _catalog_version(item, versions)
        else:
            continue
        if coordinate.startswith("io.ktor:ktor-server-"):
            server.append(version)
        elif coordinate == "io.ktor:ktor-bom":
            bom.append(version)
    return bool(server), next((version for version in server + bom if version), None)


def _gradle_ktor(text: str, base: Path, plugins: dict, catalog_path: Path) -> tuple[bool, str | None, Path | None]:
    """Whether a build is a Ktor server, the version it declares and the file that declares it (None: the build).

    The Ktor Gradle plugin, a server artifact, a server library of the project's version catalog and the version
    catalog that Ktor publishes (ktorLibs.server.core) each say it is a server. The version comes from the plugin
    first, then the server artifacts, the project's catalog, a Ktor BOM and last the Ktor version catalog.
    """
    artifacts = _KTOR_SERVER_ARTIFACT.findall(text)
    in_catalog, catalog_version = _gradle_catalog_ktor(catalog_path, text)
    published = None
    for name in ("settings.gradle.kts", "settings.gradle"):
        declared = _KTOR_SETTINGS_CATALOG.search(read_manifest_text(base / name) or "")
        if declared and re.search(rf"\b{re.escape(declared.group(1))}\.server\.", text):
            published = (declared_version(declared.group(2)), base / name)
            break
    if not (_KTOR_PLUGIN in text or _KTOR_PLUGIN in plugins or artifacts or in_catalog or published):
        return False, None, None
    plugin = _gradle_plugin_version(text, re.escape(_KTOR_PLUGIN))
    named = next(filter(None, (_gradle_declared(token, text, base) for token in artifacts if token)), None)
    if plugin or named:
        return True, plugin or named, None
    if plugins.get(_KTOR_PLUGIN) or catalog_version:
        return True, plugins.get(_KTOR_PLUGIN) or catalog_version, catalog_path
    bom = _KTOR_BOM.search(text)
    bom_version = _gradle_declared(bom.group(1), text, base) if bom else None
    if bom_version:
        return True, bom_version, None
    return (True, *published) if published and published[0] else (True, None, None)


def gradle_components(component: DetectedComponent, path: Path, label: str, root: Path) -> None:
    text = read_manifest_text(path) or ""
    java = re.search(r"""(?:jvmToolchain|JavaLanguageVersion\.of)\s*\(\s*(\d+)|"""
                     r"""sourceCompatibility\s*(?:=\s*)?(?:JavaVersion\.VERSION_|["']?)(\d+(?:[._]\d+)?)""", text)
    catalog_path = root / component.path / "gradle" / "libs.versions.toml"
    catalog_label = catalog_path.relative_to(root).as_posix()
    catalog = _gradle_catalog_plugins(catalog_path, text)
    kotlin = next((version for plugin, version in catalog.items() if plugin.startswith("org.jetbrains.kotlin.")), None)
    ktor, ktor_version, ktor_source = _gradle_ktor(text, root / component.path, catalog, catalog_path)
    # A Ktor server is written in Kotlin, even when a convention plugin applies the Kotlin plugin.
    has_kotlin = (_KOTLIN_PLUGIN.search(text) or any(plugin.startswith("org.jetbrains.kotlin.") for plugin in catalog)
                  or ktor)
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
    if ktor:
        component.add("Ktor", ktor_version, ktor_source.relative_to(root).as_posix() if ktor_source else label)


def gradle_modules(directory: Path) -> list[Path]:
    settings = read_manifest_text(directory / "settings.gradle.kts") or read_manifest_text(directory / "settings.gradle") or ""
    modules = []
    for arguments, line in re.findall(r"(?m)^[ \t]*include(?:[ \t]*\(([^)]*)\)|[ \t]+([^\n/]*))", settings):
        for name in re.findall(r"""["'](:?[\w.-]+(?::[\w.-]+)*)["']""", arguments or line):
            parts = name.lstrip(":").split(":")
            if not {".", ".."}.intersection(parts):
                modules.append(directory.joinpath(*parts))
    return modules
