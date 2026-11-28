"""Write docs/compliance.md from the registry of controls, after setting each line of it from the code.

    python3 scripts/build_compliance.py

src/openguildkit/registry/controls.json says, for each control of OpenGuildKit, the file and the symbol that hold it and
the line where the symbol is defined. The script looks each symbol up again, so a line that moved is fixed by running it,
then regenerates the tables of docs/compliance.md between their two markers. tests/test_controls.py fails while the
registry points at a wrong line or the page differs from what the registry generates.
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openguildkit import controls  # noqa: E402 INTENTIONAL(#482): runs from a checkout, after sys.path is set above

REGISTRY = Path("src/openguildkit/registry/controls.json")
PAGE = Path("docs/compliance.md")


def build(root: Path, code: Path, data: dict) -> dict:
    """The registry with each line looked up in the files of `code`, its text, and the page of `root` regenerated."""
    data = copy.deepcopy(data)
    for item in data["controls"]:
        for place in item["code"]:
            line = controls.locate(code, place["file"], place["symbol"])
            if line is None:
                raise SystemExit(f"{place['symbol']} is not defined in {place['file']}: fix the control {item['id']}.")
            place["line"] = line
    controls.validate(data)
    page = controls.update_page((root / PAGE).read_text(encoding="utf-8"), data)
    return {"controls": data, "json": json.dumps(data, indent=2, ensure_ascii=False) + "\n", "page": page}


def main() -> int:
    built = build(ROOT, ROOT, controls.load())
    (ROOT / REGISTRY).write_text(built["json"], encoding="utf-8")
    (ROOT / PAGE).write_text(built["page"], encoding="utf-8")
    print(f"{REGISTRY.as_posix()} and {PAGE.as_posix()} written from {len(built['controls']['controls'])} controls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
