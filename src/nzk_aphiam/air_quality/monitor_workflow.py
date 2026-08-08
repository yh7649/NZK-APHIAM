"""Command-line orchestration for the staged AirKorea monitor workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from nzk_aphiam.air_quality.monitor_aggregation import (
    DEFAULT_AGGREGATE_DIR,
    DEFAULT_ANNUAL_CSV,
    DEFAULT_ANNUAL_PARQUET,
    DEFAULT_MONTHLY_QC,
    DEFAULT_MONTHLY_RAW,
    aggregate_qc_partitions,
)
from nzk_aphiam.air_quality.monitor_attributes import (
    DEFAULT_ATTRIBUTES_CSV,
    DEFAULT_ATTRIBUTES_PARQUET,
    DEFAULT_INTERIM_CROSSWALK,
    build_monitor_attributes,
)
from nzk_aphiam.air_quality.monitor_bias_grid import (
    DEFAULT_GRID_OUTPUT_DIR,
    build_inmap_bias_grid,
)
from nzk_aphiam.air_quality.monitor_canonical import (
    DEFAULT_ARCHIVE_DIR,
    POLLUTANTS,
    canonicalize_archives,
)
from nzk_aphiam.air_quality.monitor_canonical import (
    DEFAULT_OUTPUT_DIR as DEFAULT_CANONICAL_DIR,
)
from nzk_aphiam.air_quality.monitor_qc import (
    DEFAULT_CONFIG,
    DEFAULT_FINAL_QC_DIR,
    clean_qc_partitions,
)
from nzk_aphiam.data.scrape.airkorea.stations import DEFAULT_OUTPUT as DEFAULT_REGISTRY


def _add_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--years", type=int, nargs="+")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--pollutants", nargs="+", choices=POLLUTANTS)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace selected partitions when their source or settings changed.",
    )


def _add_shared_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--canonical-dir", type=Path, default=DEFAULT_CANONICAL_DIR)
    parser.add_argument("--final-qc-dir", type=Path, default=DEFAULT_FINAL_QC_DIR)
    parser.add_argument("--aggregate-dir", type=Path, default=DEFAULT_AGGREGATE_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--historical-stations", type=Path)
    parser.add_argument(
        "--interim-crosswalk",
        type=Path,
        default=DEFAULT_INTERIM_CROSSWALK,
    )
    parser.add_argument(
        "--attributes-parquet",
        type=Path,
        default=DEFAULT_ATTRIBUTES_PARQUET,
    )
    parser.add_argument("--attributes-csv", type=Path, default=DEFAULT_ATTRIBUTES_CSV)
    parser.add_argument("--monthly-raw", type=Path, default=DEFAULT_MONTHLY_RAW)
    parser.add_argument("--monthly-qc", type=Path, default=DEFAULT_MONTHLY_QC)
    parser.add_argument("--annual-parquet", type=Path, default=DEFAULT_ANNUAL_PARQUET)
    parser.add_argument("--annual-csv", type=Path, default=DEFAULT_ANNUAL_CSV)


def _add_grid_arguments(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument("--inmap-grid", type=Path, required=required)
    parser.add_argument("--grid-year", type=int, required=required)
    parser.add_argument("--grid-output-dir", type=Path, default=DEFAULT_GRID_OUTPUT_DIR)
    parser.add_argument("--model-pm25-column", default="TotalPM25")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run row-preserving canonicalization with coordinate crosswalk, "
            "resumable rule/forest/spatial QC, EPA-style PM aggregation, and "
            "optional InMAP-grid bias correction."
        )
    )
    subparsers = parser.add_subparsers(dest="stage", required=True)

    for name, help_text in [
        (
            "canonicalize",
            "Standardize ZIP/XLSX members into canonical raw Parquet parts and "
            "build the monitor-year coordinate crosswalk.",
        ),
        (
            "clean",
            "Apply rule flags, time-blocked random-forest anomaly detection, and "
            "spatial confirmation in one resumable pass.",
        ),
        ("aggregate", "Build monthly outputs and EPA-style annual monitor PM means."),
        ("all", "Run canonicalize, clean, and aggregation in order."),
    ]:
        command = subparsers.add_parser(name, help=help_text)
        _add_scope_arguments(command)
        _add_shared_paths(command)
        if name == "all":
            _add_grid_arguments(command, required=False)

    grid = subparsers.add_parser(
        "grid",
        help="Interpolate observed-minus-modeled monitor residuals to an InMAP grid.",
    )
    _add_shared_paths(grid)
    _add_grid_arguments(grid, required=True)
    return parser


def _selected_years(args: argparse.Namespace) -> set[int] | None:
    if args.years and (args.start_year is not None or args.end_year is not None):
        raise ValueError("Use either --years or --start-year/--end-year, not both")
    if args.years:
        return set(args.years)
    if args.start_year is None and args.end_year is None:
        return None
    if args.start_year is None or args.end_year is None:
        raise ValueError("--start-year and --end-year must be supplied together")
    if args.start_year > args.end_year:
        raise ValueError("--start-year cannot be after --end-year")
    return set(range(args.start_year, args.end_year + 1))


def _run_canonical(args: argparse.Namespace, years: set[int] | None) -> None:
    print("Stage 1/3: canonical row-preserving raw merge")
    manifest = canonicalize_archives(
        archive_dir=args.archive_dir,
        output_dir=args.canonical_dir,
        years=years,
        overwrite=args.overwrite,
    )
    print(f"Canonical manifest: {manifest}")
    print("Stage 1/3: monitor-year coordinate crosswalk")
    attributes = build_monitor_attributes(
        canonical_dir=args.canonical_dir,
        registry_path=args.registry,
        historical_stations_path=args.historical_stations,
        interim_crosswalk_path=args.interim_crosswalk,
        attributes_parquet_path=args.attributes_parquet,
        attributes_csv_path=args.attributes_csv,
    )
    print(
        f"Monitor-year attributes: {len(attributes):,} rows; "
        f"{attributes['latitude'].notna().sum():,} coordinate-resolved"
    )


def _run_clean(args: argparse.Namespace, years: set[int] | None) -> None:
    print("Stage 2/3: rules, out-of-fold random forest, and spatial confirmation")
    manifest = clean_qc_partitions(
        canonical_dir=args.canonical_dir,
        attributes_path=args.attributes_parquet,
        output_dir=args.final_qc_dir,
        config_path=args.config,
        years=years,
        pollutants=set(args.pollutants) if args.pollutants else None,
        overwrite=args.overwrite,
    )
    print(f"Clean hourly-QC manifest: {manifest}")


def _run_aggregation(args: argparse.Namespace, years: set[int] | None) -> None:
    print("Stage 3/3: monthly and EPA-style annual monitor aggregation")
    manifest = aggregate_qc_partitions(
        final_qc_dir=args.final_qc_dir,
        aggregate_dir=args.aggregate_dir,
        attributes_path=args.attributes_parquet,
        config_path=args.config,
        monthly_raw_path=args.monthly_raw,
        monthly_qc_path=args.monthly_qc,
        annual_parquet_path=args.annual_parquet,
        annual_csv_path=args.annual_csv,
        years=years,
        pollutants=set(args.pollutants) if args.pollutants else None,
        overwrite=args.overwrite,
    )
    print(f"Aggregation manifest: {manifest}")
    print(f"PI-facing annual PM file: {args.annual_csv}")


def _run_grid(args: argparse.Namespace) -> None:
    if args.inmap_grid is None or args.grid_year is None:
        raise ValueError("--inmap-grid and --grid-year are required to build a bias grid")
    print("Optional grid stage: interpolate monitor residuals to the InMAP grid")
    manifest = build_inmap_bias_grid(
        annual_path=args.annual_parquet,
        inmap_grid_path=args.inmap_grid,
        year=args.grid_year,
        output_dir=args.grid_output_dir,
        config_path=args.config,
        model_column=args.model_pm25_column,
    )
    print(f"Bias-correction manifest: {manifest}")


def main() -> None:
    args = build_parser().parse_args()
    years = _selected_years(args) if hasattr(args, "years") else None
    if args.stage == "all" and ((args.inmap_grid is None) != (args.grid_year is None)):
        raise ValueError("--inmap-grid and --grid-year must be supplied together")
    if args.stage in {"canonicalize", "all"}:
        _run_canonical(args, years)
    if args.stage in {"clean", "all"}:
        _run_clean(args, years)
    if args.stage in {"aggregate", "all"}:
        _run_aggregation(args, years)
    if args.stage == "grid" or (args.stage == "all" and args.inmap_grid is not None):
        _run_grid(args)


if __name__ == "__main__":
    main()
