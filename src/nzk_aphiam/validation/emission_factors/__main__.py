"""CLI entry point for KEPCO emission-factor validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from nzk_aphiam.validation.emission_factors.pipeline import run_validation
from nzk_aphiam.validation.emission_factors.schema import (
    FIGURE_OUTPUT_DIR,
    INPUT_PATH,
    REFERENCE_DIR,
    TABLE_OUTPUT_DIR,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Externally validate KEPCO plant emission factors against tracked literature tables."
    )
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--reference-dir", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--table-output-dir", type=Path, default=TABLE_OUTPUT_DIR)
    parser.add_argument("--figure-output-dir", type=Path, default=FIGURE_OUTPUT_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    outputs = run_validation(
        input_path=args.input,
        reference_dir=args.reference_dir,
        table_output_dir=args.table_output_dir,
        figure_output_dir=args.figure_output_dir,
    )
    print(
        "Saved KEPCO emission-factor validation outputs: "
        + ", ".join(f"{name}={len(frame):,} rows" for name, frame in outputs.items())
    )


if __name__ == "__main__":
    main()
