"""Write src/openguildkit/registry/catalog.bundle.json: the bundled packs, boards, sectors and patterns in one file.

    python scripts/build_catalog_bundle.py

The CI package job and the release run it before `python -m build`, so the wheel ships the file. A process then reads
that one file instead of one file per record, without validating the records again: this script validated them. The
bundle lists each record file with its size; when one was added, removed or resized since, the record files are read
as in a checkout without the bundle. Git ignores the bundle: the record files stay the source.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openguildkit.catalog import BUNDLE_FILE, bundle_sources, read_record_files  # noqa: E402 INTENTIONAL(#533): runs from a checkout, before any install

REGISTRY = ROOT / "src" / "openguildkit" / "registry"


def bundle_text(registry: Path) -> str:
    """The bundle of a registry folder: its validated records, collections and IDs sorted, each record's fields in the
    order of its file so that commands print the same bytes, and the size of each record file. Same files, same text."""
    records = read_record_files(registry)
    bundle = {
        "records": {collection: dict(sorted(records[collection].items())) for collection in sorted(records)},
        "schema_version": 1,
        "sources": bundle_sources(registry),
    }
    return json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n"


def write_bundle(registry: Path) -> Path:
    path = registry / BUNDLE_FILE
    path.write_bytes(bundle_text(registry).encode("utf-8"))
    return path


def main() -> int:
    path = write_bundle(REGISTRY)
    print(f"Wrote {path.relative_to(ROOT).as_posix()}: {len(bundle_sources(REGISTRY))} record files, "
          f"{path.stat().st_size} bytes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
