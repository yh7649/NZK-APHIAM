"""Reproducible external-validation pipeline for KEPCO emission factors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from nzk_aphiam.validation.emission_factors.annualize import (
    aggregate_boundary,
    apply_variant,
    prepare_project_data,
)
from nzk_aphiam.validation.emission_factors.compare import (
    INCLUDED_AGGREGATE,
    INCLUDED_DIRECT,
    build_contextual_literature_benchmarks,
    build_plant_input_reconciliation,
    build_readable_comparison_tables,
    build_rejected_or_noncomparable_comparisons,
    build_source_coverage_matrix,
    compare_aggregate_fuel_year,
    compare_to_literature,
    prepare_literature_output,
)
from nzk_aphiam.validation.emission_factors.crosswalk import (
    project_boundaries_from_crosswalk,
)
from nzk_aphiam.validation.emission_factors.figures import (
    write_comparison_table_images,
    write_literature_ranges_svg,
    write_percent_difference_svg,
    write_scatter_svg,
    write_source_coverage_matrix_svg,
)
from nzk_aphiam.validation.emission_factors.references import (
    apply_comparison_rules,
    load_catalog,
    load_comparison_rules,
    load_crosswalk,
    load_literature_benchmarks,
    load_pdf_inventory,
)
from nzk_aphiam.validation.emission_factors.schema import (
    ANALYSIS_VARIANTS,
    FIGURE_OUTPUT_DIR,
    INPUT_PATH,
    REFERENCE_DIR,
    REFERENCE_FILES,
    TABLE_OUTPUT_DIR,
)
from nzk_aphiam.validation.emission_factors.utils import file_sha256

METHOD_VERSION = "2026-07-22"

SUPERSEDED_TABLE_OUTPUTS = {
    "ef_comparison_readable.csv",
    "ef_comparison_readable_wide.csv",
    "ef_comparison_readable_wide.md",
    "excluded_observation_summary.csv",
    "fuel_technology_validation_summary_table.csv",
    "fuel_technology_year_comparisons.csv",
    "literature_ef_benchmarks_complete.csv",
    "literature_pdf_inventory.csv",
    "literature_reference_emission_factors.csv",
    "literature_source_coverage_matrix.csv",
    "matched_literature_comparisons.csv",
    "project_annual_emission_factors.csv",
    "project_fuel_technology_year_efs.csv",
    "unmatched_literature_benchmarks.csv",
    "unmatched_or_noncomparable_boundaries.csv",
    "validation_summary_by_pollutant.csv",
}
SUPERSEDED_FIGURE_OUTPUTS = {
    "ef_comparison_table.png",
    "ef_comparison_table.svg",
    "ef_comparison_wide_table.png",
    "ef_comparison_wide_table.svg",
    "fuel_technology_ef_trends_with_literature.svg",
    "literature_ef_ranges_by_source_cell.svg",
    "literature_source_coverage_matrix.svg",
    "percent_difference_by_plant_pollutant.svg",
    "project_ef_timeseries_with_literature.svg",
    "project_vs_literature_ef.svg",
}


def run_validation(
    *,
    input_path: Path = INPUT_PATH,
    reference_dir: Path = REFERENCE_DIR,
    table_output_dir: Path = TABLE_OUTPUT_DIR,
    figure_output_dir: Path = FIGURE_OUTPUT_DIR,
) -> dict[str, pd.DataFrame]:
    """Run the full offline validation workflow and write all outputs."""
    raw_project = pd.read_csv(input_path, low_memory=False)
    prepared = prepare_project_data(raw_project)
    references = load_literature_benchmarks(reference_dir)
    literature_output = prepare_literature_output(references)
    rules = load_comparison_rules(reference_dir)
    literature_output = apply_comparison_rules(literature_output, rules)
    crosswalk = load_crosswalk(reference_dir)
    catalog = load_catalog(reference_dir)
    load_pdf_inventory(reference_dir)

    annual_frames: list[pd.DataFrame] = []
    boundary_frames: list[pd.DataFrame] = []
    for variant in ANALYSIS_VARIANTS:
        variant_data, _ = apply_variant(prepared, variant)
        annual_frames.append(
            aggregate_boundary(
                variant_data,
                group_columns=["fuel_type"],
                analysis_variant=f"{variant}_fuel",
            )
        )
        boundary_data, boundary_status = project_boundaries_from_crosswalk(
            variant_data, crosswalk, analysis_variant=variant
        )
        boundary_frames.append(boundary_data)
        del boundary_status

    all_annual = pd.concat(annual_frames, ignore_index=True)
    project_fuel_year = all_annual.copy()
    project_fuel_year["analysis_variant"] = project_fuel_year["analysis_variant"].str.replace(
        "_fuel", "", regex=False
    )
    project_boundaries = pd.concat(boundary_frames, ignore_index=True)
    plant_attempts = compare_to_literature(project_boundaries, literature_output)
    aggregate_attempts = compare_aggregate_fuel_year(project_fuel_year, literature_output)
    direct_comparisons = plant_attempts.loc[
        plant_attempts["comparison_status"].eq(INCLUDED_DIRECT)
    ].copy()
    aggregate_comparisons = aggregate_attempts.loc[
        aggregate_attempts["comparison_status"].eq(INCLUDED_AGGREGATE)
    ].copy()
    contextual = build_contextual_literature_benchmarks(
        literature_output, plant_attempts, crosswalk
    )
    rejected = build_rejected_or_noncomparable_comparisons(
        literature_output,
        plant_attempts,
        aggregate_attempts,
        crosswalk,
    )
    reconciliation = build_plant_input_reconciliation(plant_attempts, literature_output, crosswalk)
    coverage_matrix = build_source_coverage_matrix(literature_output)
    readable_comparison, readable_comparison_wide = build_readable_comparison_tables(
        direct_comparisons
    )

    table_output_dir.mkdir(parents=True, exist_ok=True)
    figure_output_dir.mkdir(parents=True, exist_ok=True)
    _clear_superseded_outputs(table_output_dir, figure_output_dir)
    outputs = {
        "direct_validation_comparisons": direct_comparisons,
        "aggregate_consistency_checks": aggregate_comparisons,
        "contextual_literature_benchmarks": contextual,
        "rejected_or_noncomparable_comparisons": rejected,
        "plant_input_reconciliation": reconciliation,
        "literature_coverage_matrix": coverage_matrix,
    }
    for name, frame in outputs.items():
        frame.to_csv(table_output_dir / f"{name}.csv", index=False)
    write_scatter_svg(
        direct_comparisons,
        figure_output_dir / "direct_validation_project_vs_external_ef.svg",
    )
    write_percent_difference_svg(
        direct_comparisons,
        figure_output_dir / "direct_validation_percent_difference.svg",
    )
    write_comparison_table_images(
        readable_comparison,
        readable_comparison_wide,
        figure_output_dir,
    )
    write_literature_ranges_svg(
        contextual,
        figure_output_dir / "contextual_literature_benchmarks.svg",
    )
    write_source_coverage_matrix_svg(
        coverage_matrix, figure_output_dir / "literature_coverage_matrix.svg"
    )

    metadata = build_metadata(input_path, reference_dir, catalog)
    (table_output_dir / "validation_run_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return outputs


def _clear_superseded_outputs(table_output_dir: Path, figure_output_dir: Path) -> None:
    """Remove generated files superseded by the reviewed output contract."""
    for filename in SUPERSEDED_TABLE_OUTPUTS:
        (table_output_dir / filename).unlink(missing_ok=True)
    for filename in SUPERSEDED_FIGURE_OUTPUTS:
        (figure_output_dir / filename).unlink(missing_ok=True)


def write_markdown_table(data: pd.DataFrame, output_path: Path) -> None:
    """Write a simple GitHub-flavored Markdown table without extra dependencies."""
    if data.empty:
        output_path.write_text("_No comparable emission-factor rows._\n", encoding="utf-8")
        return
    display = data.copy()
    for column in display.columns:
        if column == "year":
            display[column] = (
                pd.to_numeric(display[column], errors="coerce").astype("Int64").astype(str)
            )
        elif column.endswith("percent_error"):
            values = pd.to_numeric(display[column], errors="coerce")
            display[column] = values.map(lambda value: f"{value:.2f}%" if pd.notna(value) else "")
        elif column.endswith("kg_per_mwh"):
            values = pd.to_numeric(display[column], errors="coerce")
            display[column] = values.map(lambda value: f"{value:.6f}" if pd.notna(value) else "")

    headers = list(display.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in display.fillna("").to_dict("records"):
        lines.append("| " + " | ".join(str(row[column]) for column in headers) + " |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_metadata(input_path: Path, reference_dir: Path, catalog: pd.DataFrame) -> dict[str, Any]:
    """Build reproducibility metadata for a validation run."""
    return {
        "input_file": {
            "path": str(input_path),
            "sha256": file_sha256(input_path),
        },
        "reference_files": {
            filename: {
                "path": str(reference_dir / filename),
                "sha256": file_sha256(reference_dir / filename),
            }
            for filename in REFERENCE_FILES.values()
        },
        "run_timestamp": pd.Timestamp.now("UTC").isoformat(),
        "code_method_version": METHOD_VERSION,
        "analysis_variant_definitions": ANALYSIS_VARIANTS,
        "unit_conventions": {
            "generation": "MWh",
            "emissions": "kg",
            "emission_factor": "kg/MWh",
            "project_pollutants": "NOx, SOx, TSP/dust_tsp",
        },
        "crosswalk_version": file_sha256(reference_dir / REFERENCE_FILES["crosswalk"]),
        "source_catalog": catalog.to_dict("records"),
        "important_limitations": [
            "Lee et al. (2025) is class B external data-pipeline validation, not identical-data replication, because it uses annual CleanSYS emissions and EPSIS generation.",
            "KEEI Table 3-17 is eligible only for its exact 2016 plant/unit group and combined NOx+SOx+TSP definition.",
            "MOTIE is a class C KEPCO-subsidiary fuel-fleet consistency check, not national validation.",
            "Seo et al. is a methodological precedent and has no direct project percent-error rows.",
            "CAPSS Manual VII and Yu et al. use fuel-input normalization and cannot enter kg/MWh validation.",
            "TSP is never compared directly with PM2.5, and no PM2.5/TSP fraction is applied.",
            "Project annual EFs are ratios of matched mass sums to matched generation sums; monthly EF means are never used.",
        ],
    }
