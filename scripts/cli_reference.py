"""Write docs/cli.md: every command of the CLI with its options and their help, read from its parser.

Run `python scripts/cli_reference.py` after adding or changing a command or an option, or `--check` to fail when the
page is out of date. The script reads only the parser and opens no network.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openguildkit.cli import command_parser  # noqa: E402
from openguildkit.completion_cli import reference  # noqa: E402

OUTPUT = ROOT / "docs" / "cli.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail when the page is out of date instead of writing it.")
    parser.add_argument("--page", type=Path, default=OUTPUT, help="The page to write or compare (default docs/cli.md).")
    args = parser.parse_args(argv)
    text = reference(command_parser())
    if args.check:
        if not args.page.is_file() or args.page.read_text(encoding="utf-8") != text:
            print(f"{args.page} is out of date: run python scripts/cli_reference.py", file=sys.stderr)
            return 1
        return 0
    args.page.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
