"""Fill the Homebrew formula and the winget manifests of packaging/ from the SHA256SUMS.txt of a release.

    python scripts/release_manifests.py --sums SHA256SUMS.txt --output DIR [--repository OWNER/NAME]

Standard library only. It writes DIR/homebrew/openguildkit.rb and, when the release carries a Windows archive,
DIR/winget/manifests/s/SandboxPodcast/OpenGuildKit/X.Y.Z/, the folder layout of winget-pkgs. It publishes nothing:
the maintainer copies the files to a tap or to a pull request (docs/install.md, "Package managers").
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
LINE = re.compile(r"^([0-9a-f]{64}) [ *](\S+)$")
WHEEL = re.compile(r"^openguildkit-(\d+\.\d+\.\d+[\w.]*)-py3-none-any\.whl$")
WINGET_ID = "SandboxPodcast.OpenGuildKit"


def read_sums(path: Path) -> dict[str, str]:
    """File name to SHA-256, from lines written by `sha256sum`; any other line is refused."""
    sums = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = LINE.match(line.strip())
        if not match:
            raise SystemExit(f"release_manifests: {path}:{number} is not a sha256sum line: {line.strip()}")
        sums[match.group(2)] = match.group(1)
    return sums


def fill(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for name, value in values.items():
        text = text.replace(f"@{name}@", value)
    if left := sorted(set(re.findall(r"@[A-Z_]+@", text))):
        raise SystemExit(f"release_manifests: {template.name} still holds {', '.join(left)}")
    return text


def manifests(sums: dict[str, str], repository: str) -> tuple[dict[str, str], str | None]:
    """The files to write, by path relative to the output folder, and a warning for what is left out."""
    wheels = [(name, match.group(1)) for name in sums if (match := WHEEL.match(name))]
    if len(wheels) != 1:
        raise SystemExit("release_manifests: the manifest lists no openguildkit-X.Y.Z-py3-none-any.whl, or several")
    wheel, version = wheels[0]
    download = f"https://github.com/{repository}/releases/download/v{version}"
    values = {"VERSION": version, "REPOSITORY": repository,
              "WHEEL_URL": f"{download}/{wheel}", "WHEEL_SHA256": sums[wheel]}
    files = {"homebrew/openguildkit.rb": fill(PACKAGING / "homebrew" / "openguildkit.rb", values)}
    archive = f"openguildkit-{version}-windows-x64.zip"
    if archive not in sums:
        return files, (f"Warning: winget: the manifest lists no {archive}; winget installs an executable, "
                       "not a wheel, so the winget manifests are not written.")
    # winget-pkgs writes hashes in upper case.
    values |= {"WINDOWS_ZIP_URL": f"{download}/{archive}", "WINDOWS_ZIP_SHA256": sums[archive].upper()}
    folder = f"winget/manifests/s/{WINGET_ID.replace('.', '/')}/{version}"
    for template in sorted((PACKAGING / "winget").glob("*.yaml")):
        files[f"{folder}/{template.name}"] = fill(template, values)
    return files, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--sums", type=Path, required=True, help="SHA256SUMS.txt of the release")
    parser.add_argument("--output", type=Path, required=True, help="folder to write the filled files into")
    parser.add_argument("--repository", default="Sandbox-podcast/OpenGuildKit", help="OWNER/NAME of the release")
    args = parser.parse_args(argv)
    files, warning = manifests(read_sums(args.sums), args.repository)
    for relative, text in files.items():
        path = args.output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(path)
    if warning:
        print(warning, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
