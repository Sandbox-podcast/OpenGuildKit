"""Inventory the components, variants and style tokens of an existing React application, for storybook extract.

The sources are read with text patterns and the standard library, not a JavaScript parser: React function
components with their props, literal defaults and string-union prop types, the export aliases and re-exports of
index files, and CSS and SCSS stylesheets. Each item keeps the file and line it comes from.
"""

import json
import re
from datetime import date
from pathlib import Path

from . import clock
from .storage import file_sha256
from .storybook import JS_IDENTIFIER, MODULE_SUFFIXES, OUTSIDE, committed_path, source_files

MAX_FILE_BYTES = 1_000_000


_NAME = r"[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*"


_FUNCTION = re.compile(rf"^[ \t]*(export\s+(?:default\s+)?)?(?:async\s+)?function\s+({_NAME})\s*(?:<[^>()]*>)?\s*\(", re.M)


_CONST = re.compile(
    rf"^[ \t]*(export\s+)?const\s+({_NAME})\b[^=\n]*=\s*(?:React\.)?(?:(?:forwardRef|memo)\s*(?:<[^>()]*>)?\s*\(\s*)?"
    r"(?:async\s+)?(?:function\b[^(]*)?\(", re.M)


_EXPORT_LIST = re.compile(r"\bexport\s*\{([^}]*)\}(?:\s*from\s*(['\"])([^'\"\n]+)\2)?")


_EXPORT_ITEM = re.compile(r"\s*(?:type\s+)?([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?\s*")


_EXPORT_DEFAULT = re.compile(rf"\bexport\s+default\s+({_NAME})\s*;?\s*$", re.M)


_TAG = re.compile(r"<([A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*)?)(?=[\s/>])")


_ATTRIBUTE = re.compile(r"[A-Za-z_][\w:.-]*")


_VARIANT_VALUE = re.compile(r"[a-z][a-z0-9-]{0,30}")


_TYPED_VARIANT = re.compile(_VARIANT_VALUE.pattern, re.I | re.ASCII)


# Props that carry content or wiring rather than a visual variant.
_CONTENT_PROPS = {
    "children", "label", "title", "text", "placeholder", "alt", "href", "src", "id", "name", "key", "classname",
    "style", "value", "defaultvalue", "to", "description", "heading", "message", "caption", "tooltip", "role",
    "htmlfor", "type", "as", "ref", "onclick", "onchange", "testid",
}


_COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z])|(?:rgba?|hsla?)\([^()]*\)")


_LENGTH = re.compile(r"(?<![\w.-])(\d*\.?\d+)(px|rem)(?![\w-])")


_DECLARATION = re.compile(r"(--[\w-]+|\$[\w-]+|[a-zA-Z-]+)\s*:\s*([^;{}]+?)\s*(?=;|})")


_VAR = re.compile(r"var\(\s*(--[\w-]+)")


_SCSS_VAR = re.compile(r"\$([\w-]+)")


def _strip_js_comments(text: str) -> str:
    """Blank out comments and keep every line in place, so positions still give line numbers."""
    out, index, quote = [], 0, None
    while index < len(text):
        character = text[index]
        if quote:
            out.append(character)
            if character == "\\" and index + 1 < len(text):
                out.append(text[index + 1])
                index += 2
                continue
            if character == quote or (character == "\n" and quote != "`"):
                quote = None
        elif character in "'\"`":
            quote = character
            out.append(character)
        elif text.startswith("//", index) and (index == 0 or text[index - 1] != ":"):
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            out.append(" " * (end - index))
            index = end
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[index:end]))
            index = end
            continue
        else:
            out.append(character)
        index += 1
    return "".join(out)


def _closing(text: str, start: int, opening: str = "{", closing: str = "}") -> int:
    """Index of the bracket that closes the one at start, skipping quoted text; -1 if none."""
    depth, quote, index = 0, None, start
    while index < len(text):
        character = text[index]
        if quote:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
        elif character in "'\"`":
            quote = character
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _split_top_level(text: str, separators: str = ",") -> list[str]:
    parts, depth, quote, current = [], 0, None, []
    for index, character in enumerate(text):
        if quote:
            if character == quote and text[index - 1] != "\\":
                quote = None
        elif character in "'\"`":
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character in separators and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _literal(expression: str):
    """(True, value) for a string, number or boolean literal; (False, None) otherwise."""
    expression = expression.strip()
    if len(expression) >= 2 and expression[0] == expression[-1] and expression[0] in "'\"`" \
            and not (expression[0] == "`" and "${" in expression):
        return True, expression[1:-1]
    if expression in ("true", "false"):
        return True, expression == "true"
    if re.fullmatch(r"-?\d+(\.\d+)?", expression):
        return True, float(expression) if "." in expression else int(expression)
    return False, None


def _destructured_props(text: str, start: int) -> list[dict] | None:
    """Props of a component whose first parameter is destructured: names and literal defaults."""
    position = start
    while position < len(text) and text[position] in " \t\r\n":
        position += 1
    if position >= len(text) or text[position] != "{":
        return None
    end = _closing(text, position)
    if end < 0:
        return None
    props = []
    for part in _split_top_level(text[position + 1:end]):
        if part.startswith("..."):
            continue
        match = re.match(r"([A-Za-z_$][\w$]*)\s*(?::\s*[A-Za-z_$][\w$]*)?\s*(?:=\s*(.+))?$", part, re.S)
        if not match:
            continue
        prop = {"name": match.group(1)}
        if match.group(2) is not None:
            known, value = _literal(match.group(2))
            if known:
                prop["default"] = value
        props.append(prop)
    return props


def _line_of(starts: list[int], position: int) -> int:
    low, high = 0, len(starts)
    while low < high:
        middle = (low + high) // 2
        if starts[middle] <= position:
            low = middle + 1
        else:
            high = middle
    return low


def _line_starts(text: str) -> list[int]:
    return [0] + [match.end() for match in re.finditer("\n", text)]


def _tag_attributes(text: str, start: int):
    """Attributes of a JSX opening tag from start, its end and whether it closes itself."""
    attributes, index = [], start
    while index < len(text):
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if index >= len(text):
            break
        if text.startswith("/>", index):
            return attributes, index + 2, True
        if text[index] == ">":
            return attributes, index + 1, False
        if text[index] == "{":
            end = _closing(text, index)
            if end < 0:
                break
            attributes.append(("...", False, None))
            index = end + 1
            continue
        match = _ATTRIBUTE.match(text, index)
        if not match:
            break
        name, index = match.group(0), match.end()
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if text[index:index + 1] != "=":
            attributes.append((name, True, True))
            continue
        index += 1
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if text[index:index + 1] in ("'", '"'):
            end = text.find(text[index], index + 1)
            if end < 0:
                break
            attributes.append((name, True, text[index + 1:end]))
            index = end + 1
        elif text[index:index + 1] == "{":
            end = _closing(text, index)
            if end < 0:
                break
            known, value = _literal(text[index + 1:end])
            attributes.append((name, known, value))
            index = end + 1
        else:
            break
    return None, index, False


def _file_label(root: Path, base: Path, path: Path) -> str:
    """A source file as the inventory names it: relative to the project, or outside:FOLDER/... by the given folder."""
    label = committed_path(root, path)
    if label.startswith(OUTSIDE):
        return f"{OUTSIDE}{base.name}/{path.relative_to(base).as_posix()}"
    return label


def _origin(label: str, line: int) -> str:
    return f"{label}:{line}"


def _type_body(code: str, name: str) -> str | None:
    """The members of an interface or object type alias declared in the same file."""
    match = re.search(rf"\binterface\s+{re.escape(name)}\b[^{{;]*\{{", code) or re.search(
        rf"\btype\s+{re.escape(name)}\s*(?:<[^>]*>)?\s*=\s*\{{", code)
    if not match:
        return None
    end = _closing(code, match.end() - 1)
    return code[match.end():end] if end > 0 else None


def _type_alias(code: str, name: str) -> str | None:
    """The right-hand side of type NAME = ..., up to its semicolon or the last line that continues the union."""
    match = re.search(rf"\btype\s+{re.escape(name)}\s*=", code)
    if not match:
        return None
    lines, rest = [], code[match.end():].split("\n")
    for index, line in enumerate(rest):
        if index and not line.strip().startswith("|"):
            break
        lines.append(line.split(";")[0])
        if ";" in line:
            break
    return " ".join(lines)


def _string_union(code: str, type_text: str, depth: int = 0) -> list[str] | None:
    """The values of a union of string literals, following type aliases of the same file; None for other types."""
    values = []
    for part in type_text.strip().lstrip("|").split("|"):
        part = part.strip()
        known, value = _literal(part)
        if known and isinstance(value, str) and part[0] != "`":
            values.append(value)
        elif part in ("undefined", "null"):
            continue
        elif JS_IDENTIFIER.fullmatch(part) and depth < 3 and _type_alias(code, part) is not None:
            nested = _string_union(code, _type_alias(code, part), depth + 1)
            if nested is None:
                return None
            values.extend(nested)
        else:
            return None
    values = list(dict.fromkeys(values))
    return values if len(values) >= 2 else None


def _member_types(body: str) -> dict:
    """Prop name to (type text, required) for the top-level members of an object type."""
    starts = re.compile(r"^(?:readonly\s+)?([A-Za-z_$][\w$]*)\s*(\?)?\s*:\s*(.*)$", re.S)
    members = {}
    current = None
    for part in _split_top_level(body, ",;\n"):
        match = starts.fullmatch(part)
        if match:
            current, optional, annotation = match.groups()
            members[current] = (annotation, optional is None)
        elif current:
            annotation, required = members[current]
            members[current] = (f"{annotation} {part}".strip(), required)
    return members


def _props_type(code: str, after_props: int, declaration: str) -> dict:
    """Member types of the props: the annotation after the destructured parameter, or FC<Props> on a constant."""
    position = after_props
    while position < len(code) and code[position] in " \t\r\n":
        position += 1
    name = None
    if code[position:position + 1] == ":":
        annotation = code[position + 1:].lstrip()
        if annotation.startswith("{"):
            end = _closing(annotation, 0)
            return _member_types(annotation[1:end]) if end > 0 else {}
        match = JS_IDENTIFIER.match(annotation)
        name = match.group(0) if match else None
    if name is None:
        generics = re.findall(r"<([^<>()]*)>", declaration)
        if generics:
            name = generics[-1].split(",")[-1].strip()
    body = _type_body(code, name) if name and JS_IDENTIFIER.fullmatch(name) else None
    return _member_types(body) if body is not None else {}


def _callback_type(annotation: str) -> bool:
    """A function type, such as (input: Input) => void: a story passes a function that does nothing."""
    annotation = annotation.strip()
    return annotation == "Function" or (annotation.startswith(("(", "<")) and "=>" in annotation)


def _sample_arg(code: str, name: str, annotation: str, depth: int = 0):
    """Find a JSON sample for a locally declared type, without reading prop values from app usages."""
    if depth >= 4:
        return False, None
    if annotation in ("string", "ReactNode", "React.ReactNode"):
        return True, f"Sample {name}"
    if annotation == "number":
        return True, 1
    if annotation == "boolean":
        return True, False
    if (annotation.endswith("[]") and "=>" not in annotation) or re.fullmatch(r"(?:Readonly)?Array<.+>", annotation):
        return True, []
    if annotation == "null":
        return True, None
    options = _string_union(code, annotation)
    if options and all(_TYPED_VARIANT.fullmatch(option) for option in options):
        return True, options[0]
    known, value = _literal(annotation)
    if known and (not isinstance(value, str) or _TYPED_VARIANT.fullmatch(value)):
        return True, value
    body = annotation[1:-1] if annotation.startswith("{") and annotation.endswith("}") else None
    if body is None and JS_IDENTIFIER.fullmatch(annotation):
        body = _type_body(code, annotation)
        if body is None:
            alias = _type_alias(code, annotation)
            if alias:
                return _sample_arg(code, name, alias.strip(), depth + 1)
    if body is not None:
        fields = {}
        for field, (field_type, required) in _member_types(body).items():
            if required:
                known, value = _sample_arg(code, field, field_type, depth + 1)
                if not known:
                    return False, None
                fields[field] = value
        return True, fields
    return False, None


def _export_lists(path: Path, code: str, reexports: list) -> dict:
    """Local name to the public names an export list gives it; re-exports from another module are set aside."""
    exported: dict[str, list[str]] = {}
    for match in _EXPORT_LIST.finditer(code):
        for item in match.group(1).split(","):
            names = _EXPORT_ITEM.fullmatch(item)
            if not names:
                continue
            local, public = names.group(1), names.group(2) or names.group(1)
            if match.group(3):
                reexports.append((path, match.group(3), local, public))
            else:
                exported.setdefault(local, []).append(public)
    for match in _EXPORT_DEFAULT.finditer(code):
        exported.setdefault(match.group(1), []).append("default")
    return exported


def _export_of(name: str, prefix: str, publics: list[str]) -> tuple[str | None, str]:
    """How the component is exported and the name to import: its own name first, then default, then an alias."""
    if "default" in prefix:
        return "default", "default"
    if prefix or name in publics:
        return "named", name
    if "default" in publics:
        return "default", "default"
    return ("named", publics[0]) if publics else (None, "")


def _scan_reexports(path: Path, text: str, reexports: list) -> None:
    """An index module that re-exports components, possibly under another name."""
    _export_lists(path, _strip_js_comments(text), reexports)


def _scan_components(label: str, path: Path, text: str, definitions: dict, usages: dict, modules: dict,
                     reexports: list) -> None:
    code = _strip_js_comments(text)
    starts = _line_starts(code)
    exported = _export_lists(path, code, reexports)
    public_names = modules.setdefault(path, {})
    has_jsx = bool(_TAG.search(code)) or bool(re.search(r"<[a-z][a-z0-9]*[\s/>]", code))
    for pattern in (_FUNCTION, _CONST):
        for match in pattern.finditer(code):
            prefix, name = match.group(1) or "", match.group(2)
            export, public = _export_of(name, prefix, exported.get(name, []))
            if not export or not has_jsx or name in definitions:
                continue
            props = _destructured_props(code, match.end())
            if props is not None:
                members = _props_type(code, _closing(code, code.index("{", match.end())) + 1, match.group(0))
                destructured = {prop["name"] for prop in props}
                props.extend({"name": member} for member, (_, required) in members.items()
                             if required and member not in destructured)
                for prop in props:
                    annotation, required = members.get(prop["name"], ("", False))
                    options = _string_union(code, annotation)
                    if options:
                        prop["options"] = options
                    if required:
                        prop["required"] = True
                        known, value = _sample_arg(code, prop["name"], annotation)
                        if known:
                            prop["sample"] = value
                        elif _callback_type(annotation):
                            prop["callback"] = True
            definitions[name] = {
                "name": name, "file": label, "line": _line_of(starts, match.start(2)),
                "export": export, "props": props if props is not None else [],
                "children": any(prop["name"] == "children" for prop in props or []),
            }
            if export == "named" and public != name:
                definitions[name]["public"] = public
            for alias in {public, *exported.get(name, [])}:
                public_names[alias] = name
    for match in _TAG.finditer(code):
        if match.start() > 0 and (code[match.start() - 1].isalnum() or code[match.start() - 1] in "_$).]"):
            continue
        attributes, _, closes = _tag_attributes(code, match.end())
        if attributes is None:
            continue
        name = match.group(1)
        usage = usages.setdefault(name, {"count": 0, "origins": [], "with_children": 0, "props": {}, "calls": []})
        usage["count"] += 1
        origin = _origin(label, _line_of(starts, match.start()))
        usage["origins"].append(origin)
        usage["with_children"] += not closes
        literals = {}
        for prop, known, value in attributes:
            entry = usage["props"].setdefault(prop, {"literal": 0, "dynamic": 0})
            entry["literal" if known else "dynamic"] += 1
            if known:
                literals[prop] = value
        usage["calls"].append((origin, literals, [prop for prop, _, _ in attributes]))


def _variant_prop(prop: str, options: list[str] | None = None) -> bool:
    """A prop that can carry a visual state, not content or wiring."""
    if prop == "type" and options:
        return True
    return prop.casefold() not in _CONTENT_PROPS and not prop.startswith(("aria-", "data-", "on"))


def _module_file(path: Path, specifier: str) -> Path | None:
    """The scanned module a relative import specifier names, as a bundler resolves it."""
    if not specifier.startswith("."):
        return None
    target = path.parent / specifier
    candidates = [target, *(target.with_name(target.name + suffix) for suffix in MODULE_SUFFIXES),
                  *(target / f"index{suffix}" for suffix in MODULE_SUFFIXES)]
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _aliases(definitions: dict, modules: dict, reexports: list) -> dict:
    """Component name to the other names the application uses it under: export aliases and re-exports."""
    aliases: dict[str, list[str]] = {}

    def add(name: str | None, alias: str) -> None:
        if name in definitions and alias not in (name, "default") and alias not in definitions:
            aliases.setdefault(name, [])
            if alias not in aliases[name]:
                aliases[name].append(alias)

    for public_names in modules.values():
        for alias, name in public_names.items():
            add(name, alias)
    for path, specifier, local, public in reexports:
        target = _module_file(path, specifier)
        add(modules.get(target, {}).get(local), public)
    return aliases


def _merged_usage(found: list[dict]) -> dict:
    """The uses of one component under each of its names, counted together."""
    merged = {"count": 0, "origins": [], "with_children": 0, "calls": [], "props": {}}
    for usage in found:
        for field in ("count", "with_children"):
            merged[field] += usage[field]
        for field in ("origins", "calls"):
            merged[field].extend(usage[field])
    return merged


def _hex(red: float, green: float, blue: float, alpha: float = 1.0) -> str:
    channels = [max(0, min(255, round(value))) for value in (red, green, blue)]
    text = "#" + "".join(f"{value:02x}" for value in channels)
    return text if alpha >= 1 else text + f"{max(0, min(255, round(alpha * 255))):02x}"


def normalize_color(text: str) -> str | None:
    """A CSS hex, rgb() or hsl() color as #rrggbb, or #rrggbbaa below full opacity."""
    text = text.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(character * 2 for character in digits)
        if len(digits) == 8 and digits.endswith("ff"):
            digits = digits[:6]
        return "#" + digits if len(digits) in (6, 8) else None
    match = re.fullmatch(r"(rgba?|hsla?)\(([^()]*)\)", text)
    if not match:
        return None
    values = [item for item in re.split(r"[\s,/]+", match.group(2).strip()) if item]
    if len(values) not in (3, 4):
        return None
    try:
        alpha = 1.0
        if len(values) == 4:
            alpha = float(values[3][:-1]) / 100 if values[3].endswith("%") else float(values[3])
        if match.group(1).startswith("rgb"):
            channels = [float(item[:-1]) * 2.55 if item.endswith("%") else float(item) for item in values[:3]]
            return _hex(*channels, alpha)
        hue = float(values[0].removesuffix("deg")) % 360 / 360
        saturation, lightness = (float(item.rstrip("%")) / 100 for item in values[1:3])
    except ValueError:
        return None
    import colorsys

    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _hex(red * 255, green * 255, blue * 255, alpha)


def _length(number: str, unit: str) -> str | None:
    value = float(number)
    if value == 0:
        return None
    return f"{value:g}{unit}"


def _dimension_kind(name: str) -> str:
    lowered = name.casefold()
    if "radius" in lowered or "rounded" in lowered:
        return "radius"
    if "font" in lowered or "text" in lowered:
        return "font-size"
    if any(word in lowered for word in ("space", "spacing", "gap", "padding", "margin", "inset")):
        return "spacing"
    return "dimension"


def _scan_styles(label: str, path: Path, text: str, tokens: dict, variables: dict) -> None:
    code = re.sub(r"/\*.*?\*/", lambda match: re.sub(r"[^\n]", " ", match.group(0)), text, flags=re.S)
    if path.suffix == ".scss":
        code = re.sub(r"(^|[^:])//[^\n]*", lambda match: match.group(1), code)
    starts = _line_starts(code)

    def add(kind: str, value: str, origin: str, variable: str | None = None) -> None:
        key = f"{kind}:{value}"
        # Keep the original key for the first candidate so existing proposals still match.
        primary = tokens.get(key)
        if variable and primary and primary.get("variable") not in (None, variable):
            key = f"{key}:{variable}"
        token = tokens.setdefault(key, {
            "key": key, "kind": kind, "value": value, "occurrences": 0, "origins": []})
        token["occurrences"] += 1
        token["origins"].append(origin)
        if variable:
            token["name_hint"] = variable.removeprefix("--").removeprefix("$")
            token["variable"] = variable

    for match in _DECLARATION.finditer(code):
        prop, value = match.group(1), match.group(2).strip()
        origin = _origin(label, _line_of(starts, match.start()))
        for variable in _VAR.findall(value):
            variables.setdefault(variable, []).append(origin)
        if path.suffix == ".scss":
            for variable in _SCSS_VAR.findall(value):
                variables.setdefault(f"${variable}", []).append(origin)
        if prop.startswith(("--", "$")):
            hint = prop.lstrip("-$")
            colors = _COLOR.findall(value)
            lengths = _LENGTH.findall(value)
            if len(colors) == 1 and _COLOR.fullmatch(value) and normalize_color(colors[0]):
                add("color", normalize_color(colors[0]), origin, prop)
            elif len(lengths) == 1 and _LENGTH.fullmatch(value) and _length(*lengths[0]):
                add(_dimension_kind(hint), _length(*lengths[0]), origin, prop)
            elif "family" in hint.casefold() or ("," in value and not colors and "(" not in value):
                add("font-family", ", ".join(part.strip() for part in value.split(",")), origin, prop)
            else:
                add("other", f"{prop}: {value}", origin, prop)
            continue
        name = prop.casefold()
        if "var(" in value and not _COLOR.search(value) and not _LENGTH.search(value):
            continue
        for color in _COLOR.findall(value):
            normalized = normalize_color(color)
            if normalized:
                add("color", normalized, origin)
        if name == "font-size":
            for number, unit in _LENGTH.findall(value):
                if _length(number, unit):
                    add("font-size", _length(number, unit), origin)
        elif name == "font-family" and "var(" not in value:
            add("font-family", ", ".join(part.strip() for part in value.split(",")), origin)
        elif name.startswith(("margin", "padding")) or name in ("gap", "row-gap", "column-gap"):
            for number, unit in _LENGTH.findall(value):
                if _length(number, unit):
                    add("spacing", _length(number, unit), origin)
        elif name.endswith("radius"):
            for number, unit in _LENGTH.findall(value):
                if _length(number, unit):
                    add("radius", _length(number, unit), origin)


def _confidence(count: int, basis: str = "code") -> str:
    return "observed" if count >= 2 and basis != "preview" else "hypothesis"


def _capped(origins: list[str], limit: int = 20) -> list[str]:
    return list(dict.fromkeys(origins))[:limit]


def extract(root: Path, sources: list[Path], previews: list[Path] | None = None, today: date | None = None) -> dict:
    """Inventory React components, their variants and style token candidates, each tied to its origin."""
    today = today or clock.today()
    definitions, usages, tokens, variables = {}, {}, {}, {}
    modules, reexports = {}, []
    scanned = {"components": 0, "styles": 0}
    for base, path in source_files(sources):
        name = path.name
        if any(marker in name for marker in (".stories.", ".test.", ".spec.")) or name.endswith(".d.ts"):
            continue
        if path.suffix not in (*MODULE_SUFFIXES, ".css", ".scss") or path.stat().st_size > MAX_FILE_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        label = _file_label(root, base, path)
        if path.suffix in (".tsx", ".jsx"):
            scanned["components"] += 1
            _scan_components(label, path, text, definitions, usages, modules, reexports)
        elif path.suffix in (".ts", ".js"):
            _scan_reexports(path, text, reexports)
        else:
            scanned["styles"] += 1
            _scan_styles(label, path, text, tokens, variables)
    aliases = _aliases(definitions, modules, reexports)
    # A custom property counts once where it is defined and once per var() that uses it.
    for token in tokens.values():
        uses = variables.get(token.pop("variable", None), [])
        token["occurrences"] += len(uses)
        token["origins"].extend(uses)
    components, variants = [], {}
    for name, definition in sorted(definitions.items()):
        usage = _merged_usage([usages[tag] for tag in [name, *aliases.get(name, [])] if tag in usages])
        components.append({
            **definition, "children": definition["children"] or usage["with_children"] > 0,
            "usages": usage["count"], "origins": _capped(usage["origins"]),
            "confidence": _confidence(usage["count"]),
        })
        defaults = {prop["name"]: prop["default"] for prop in definition["props"] if "default" in prop}
        options = {prop["name"]: prop["options"] for prop in definition["props"] if "options" in prop}
        for origin, literals, given in usage["calls"]:
            found = []
            for prop, value in literals.items():
                if not _variant_prop(prop, options.get(prop)):
                    continue
                if value is True or (isinstance(value, str) and (
                        _VARIANT_VALUE.fullmatch(value) or
                        (value in options.get(prop, []) and _TYPED_VARIANT.fullmatch(value)))):
                    found.append((prop, value, "usage"))
            for prop, value in defaults.items():
                if prop not in given and _variant_prop(prop, options.get(prop)) and isinstance(value, str) \
                        and _VARIANT_VALUE.fullmatch(value):
                    found.append((prop, value, "default"))
            for prop, value, basis in found:
                key = f"{name}:{prop}={json.dumps(value)}"
                item = variants.setdefault(key, {
                    "key": key, "component": name, "props": {prop: value}, "occurrences": 0, "origins": [],
                    "basis": basis})
                item["occurrences"] += 1
                item["origins"].append(origin)
                if basis == "usage":
                    item["basis"] = "usage"
        # Values a typed string union allows, and the other value of a boolean with a default, unseen in the
        # scanned uses: states to confirm on the screens.
        for prop in definition["props"]:
            if not _variant_prop(prop["name"], prop.get("options")):
                continue
            if isinstance(prop.get("default"), bool):
                key = f"{name}:{prop['name']}={json.dumps(not prop['default'])}"
                variants.setdefault(key, {
                    "key": key, "component": name, "props": {prop["name"]: not prop["default"]}, "occurrences": 0,
                    "origins": [_origin(definition["file"], definition["line"])], "basis": "type"})
            for value in prop.get("options", []):
                key = f"{name}:{prop['name']}={json.dumps(value)}"
                if _TYPED_VARIANT.fullmatch(value) and key not in variants:
                    variants[key] = {
                        "key": key, "component": name, "props": {prop["name"]: value}, "occurrences": 0,
                        "origins": [_origin(definition["file"], definition["line"])],
                        "basis": "default" if prop.get("default") == value else "type"}
    for item in variants.values():
        item["origins"] = _capped(item["origins"])
        item["confidence"] = _confidence(item["occurrences"])
    aliased = {alias for names in aliases.values() for alias in names}
    external = [{"name": name, "usages": usage["count"]} for name, usage in sorted(usages.items())
                if name not in definitions and name not in aliased and len(name) > 1]
    token_list = []
    for token in sorted(tokens.values(), key=lambda item: (item["kind"], -item["occurrences"], item["key"])):
        token["origins"] = _capped(token["origins"])
        token["confidence"] = _confidence(token["occurrences"])
        token_list.append(token)
    inventory = {
        "schema_version": 1,
        "extracted": today.isoformat(),
        "sources": [committed_path(root, path) for path in sources],
        "previews": [{"path": committed_path(root, path), "sha256": file_sha256(path)}
                     for path in previews or []],
        "scanned": scanned,
        "components": components,
        "variants": sorted(variants.values(), key=lambda item: item["key"]),
        "external_components": external,
        "tokens": token_list,
    }
    if any(item.startswith(OUTSIDE) for item in inventory["sources"]) or any(
            item["file"].startswith(OUTSIDE) for item in components):
        inventory["notes"] = [
            "A source outside the project is named outside:FOLDER/... by its folder name, because a path relative "
            "to the project would spell the home folder or the drive. generate writes no story for a component "
            "defined there: copy it into the project, or extract from a folder next to the project."]
    return inventory
