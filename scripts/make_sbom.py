"""Write the CycloneDX SBOM of a release: the wheel, and the runtime npm packages its web interface is built from.

    python scripts/make_sbom.py --lock web/package-lock.json --wheel dist/openguildkit-X.Y.Z-py3-none-any.whl [--output FILE]

Standard library only. The wheel has no Python dependency; its web interface bundles the npm packages that
package-lock.json (lockfile version 2 or 3) does not mark as development-only. The output is CycloneDX 1.5 JSON,
sorted and dated by SOURCE_DATE_EPOCH when it is set, so the same inputs give the same bytes.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

ALGORITHMS = {"sha1": "SHA-1", "sha256": "SHA-256", "sha384": "SHA-384", "sha512": "SHA-512"}


def licenses(value) -> list[dict]:
    """A single SPDX identifier is an id, an SPDX expression stays an expression, any other text is a name."""
    if not isinstance(value, str) or not value:
        return []
    if re.fullmatch(r"[\w.+-]+", value):
        return [{"license": {"id": value}}]
    if re.search(r"\s(?:OR|AND|WITH)\s", value):
        return [{"expression": value}]
    return [{"license": {"name": value}}]


def hashes(integrity) -> list[dict]:
    """The subresource integrity of the lock (`sha512-BASE64`) as a CycloneDX hash in hexadecimal."""
    for item in str(integrity or "").split():
        name, _, digest = item.partition("-")
        if name in ALGORITHMS:
            return [{"alg": ALGORITHMS[name], "content": base64.b64decode(digest).hex()}]
    return []


def component(path: str, entry: dict) -> dict:
    name = entry.get("name") or path.rsplit("node_modules/", 1)[1]
    group, _, short = name.rpartition("/")
    purl = f"pkg:npm/{quote(name, safe='/')}@{entry['version']}"
    found = {"type": "library", "bom-ref": purl, "name": short, "version": entry["version"], "purl": purl}
    if group:
        found["group"] = group
    for key, value in (("hashes", hashes(entry.get("integrity"))), ("licenses", licenses(entry.get("license")))):
        if value:
            found[key] = value
    return found


def runtime_components(lock: dict) -> list[dict]:
    """The packages npm installs for a user of the package: no development-only, no link, no root."""
    if not isinstance(lock.get("packages"), dict):
        raise SystemExit("make_sbom: the lock has no 'packages' table: lockfile version 2 or 3 is needed.")
    kept = [component(path, entry) for path, entry in lock["packages"].items()
            if path and entry.get("version") and not entry.get("dev") and not entry.get("devOptional")]
    return sorted(kept, key=lambda item: item["bom-ref"])


def bom(lock: dict, wheel: Path) -> dict:
    name, version = wheel.name.split("-")[:2]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), UTC) if epoch else datetime.now(UTC)
    components = runtime_components(lock)
    serial = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([digest, [item["bom-ref"] for item in components]]))
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{serial}", "version": 1,
        "metadata": {
            "timestamp": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {"type": "application", "bom-ref": f"{name}@{version}", "name": name, "version": version,
                          "hashes": [{"alg": "SHA-256", "content": digest}]},
        },
        "components": components,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--lock", required=True, type=Path, help="package-lock.json of the web interface")
    parser.add_argument("--wheel", required=True, type=Path, help="the wheel the SBOM describes")
    parser.add_argument("--output", type=Path, help="the file to write (default: standard output)")
    options = parser.parse_args(argv)
    text = json.dumps(bom(json.loads(options.lock.read_text(encoding="utf-8")), options.wheel), indent=2) + "\n"
    if options.output:
        options.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
