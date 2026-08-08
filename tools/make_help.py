"""Print documented Makefile targets without losing digits or wrapped descriptions."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


TARGET_PATTERN = re.compile(r"^\.PHONY:\s+([A-Za-z0-9_.-]+)\s*$")


def documented_targets(makefile: Path) -> list[tuple[str, str]]:
    """Return targets paired with the contiguous ``##`` block above ``.PHONY``."""
    descriptions: list[str] = []
    entries: list[tuple[str, str]] = []

    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            descriptions.append(line[3:].strip())
            continue

        match = TARGET_PATTERN.match(line)
        if match and descriptions:
            entries.append((match.group(1), " ".join(descriptions)))

        if line.strip() and not line.startswith("##"):
            descriptions = []

    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("makefile", type=Path, nargs="?", default=Path("Makefile"))
    args = parser.parse_args()

    print("Available rules:\n")
    for target, description in documented_targets(args.makefile):
        print(f"{target:<40}{description}")


if __name__ == "__main__":
    main()
