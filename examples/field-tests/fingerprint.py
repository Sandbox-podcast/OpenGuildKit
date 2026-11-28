"""Print what must be identical for two teams that did the same thing.

    python examples/field-tests/fingerprint.py --project DIR [--task ID --answers FILE]

The output is a JSON object: a short digest of each file OpenGuildKit wrote and of each
answer it gives about the project, with the project's own path, random identifiers and
timestamps replaced first. Two teams that ran the same commands on the same files must
print the same object; a key that differs names what depends on something else.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from field_cli import command, environment

WRITTEN = ("AGENTS.md", ".openguildkit/project.json", ".openguildkit/catalog.lock.json", ".openguildkit/tools.json",
           ".mcp.json", ".codex/config.toml", ".claude/settings.json")
_IDENTIFIER = re.compile(r"\b[0-9a-f]{32}\b")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+\d{2}:\d{2}|Z)?")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def normalise(text: str, root: Path) -> str:
    """Replace what legitimately differs between two folders: the path, random identifiers, times."""
    for spelling in (str(root), root.as_posix()):
        text = text.replace(spelling, "<project>")
    return _TIMESTAMP.sub("<time>", _IDENTIFIER.sub("<id>", text.replace("\r\n", "\n")))


def run(root: Path, *arguments: str) -> tuple[int, str, str]:
    """Exit code, output and errors of openguildkit on the project. The kit's tests run it in their own process."""
    result = subprocess.run(command("--project", str(root), *arguments),
                            capture_output=True, text=True, encoding="utf-8", env=environment())
    return result.returncode, result.stdout, result.stderr


def cli(root: Path, *arguments: str) -> str:
    code, stdout, stderr = run(root, *arguments)
    return normalise(stdout if code == 0 else f"exit {code}: {stderr}", root)


def fingerprint(root: Path, task: str | None = None, answers: Path | None = None) -> dict:
    root = root.resolve()
    out = {}
    for name in WRITTEN:
        path = root / name
        if path.is_file():
            out[name] = digest(normalise(path.read_text(encoding="utf-8"), root))
    out["rule plan"] = digest(cli(root, "preview", "--json"))
    out["tools recommend"] = digest(cli(root, "tools", "recommend", "--json"))
    if task is None:
        return out
    if answers is not None:
        route = cli(root, "task", "route", task, "--answers", str(answers))
        # The route repeats the answers file in the command it proposes; each team keeps its own copy.
        for spelling in (str(answers), Path(answers).as_posix()):
            route = route.replace(spelling, "<answers>")
        out["route"] = sorted(line.split(":", 1)[0] for line in route.splitlines() if ":" in line and not line.startswith(" "))
        out["route text"] = digest(route)
    record = cli(root, "task", "show", task, "--json")
    try:
        consultation = json.loads(record).get("consultation", {})
    except ValueError:
        out["task"] = record[:200]
        return out
    out["boards consulted"] = consultation.get("boards")
    out["consultation"] = digest(normalise(consultation.get("markdown", ""), root))
    out["packs in scope"] = sorted(pack["id"] for pack in consultation.get("scope", {}).get("packs", []))
    out["expected checks"] = digest(cli(root, "task", "checks", task, "--json"))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--task")
    parser.add_argument("--answers", type=Path)
    args = parser.parse_args()
    print(json.dumps(fingerprint(args.project, args.task, args.answers), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
