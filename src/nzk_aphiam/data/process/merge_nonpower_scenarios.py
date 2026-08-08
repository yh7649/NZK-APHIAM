"""Concatenate independently mapped GCAM-KAIST non-power scenario projections.

Each `nonpower_native` run maps exactly one GCAM scenario label (e.g. `nzk` or
`reference`) into its own output directory. `combined_inventory` reads a single
non-power projected-emissions file and selects rows by scenario label, so a
combined bundle spanning two GCAM scenarios needs those independent outputs
merged into one file first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def merge_projected_emissions(paths: list[Path], output: Path) -> pd.DataFrame:
    """Concatenate single-scenario projected-emissions CSVs into one file."""
    if len(paths) < 2:
        raise ValueError("At least two input files are required to merge scenarios.")
    frames = [pd.read_csv(path) for path in paths]
    columns = list(frames[0].columns)
    for path, frame in zip(paths, frames):
        if list(frame.columns) != columns:
            raise ValueError(f"{path} columns do not match {paths[0]}: {list(frame.columns)}")
        if "scenario" not in frame.columns:
            raise ValueError(f"{path} has no 'scenario' column.")

    seen: set[str] = set()
    for path, frame in zip(paths, frames):
        labels = sorted(frame["scenario"].astype(str).unique())
        if len(labels) != 1:
            raise ValueError(f"{path} must contain exactly one scenario label; found {labels}.")
        label = labels[0]
        if label in seen:
            raise ValueError(f"Scenario {label!r} appears in more than one input file.")
        seen.add(label)

    merged = pd.concat(frames, ignore_index=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output, index=False)
    return merged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        required=True,
        dest="inputs",
        help="Single-scenario maximum_coverage_poc_projected_emissions.csv; repeatable.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    merged = merge_projected_emissions(args.inputs, args.output)
    scenarios = sorted(merged["scenario"].astype(str).unique())
    print(f"Wrote {len(merged)} rows across scenarios {scenarios} to {args.output}")


if __name__ == "__main__":
    main()
