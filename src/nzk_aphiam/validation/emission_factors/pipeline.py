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
    build_readable_comparison_tables,
    compare_to_literature,
    prepare_literature_output,
    summarize_by_pollutant,
)
from nzk_aphiam.validation.emission_factors.crosswalk import (
    nonmatched_crosswalk_rows,
    project_boundaries_from_crosswalk,
)
from nzk_aphiam.validation.emission_factors.figures import (
    write_percent_difference_svg,
    write_scatter_svg,
    write_timeseries_svg,
)
from nzk_aphiam.validation.emission_factors.references import (
    load_catalog,
    load_crosswalk,
    load_literature_benchmarks,
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

METHOD_VERSION = "2026-07-16"


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
    crosswalk = load_crosswalk(reference_dir)
    catalog = load_catalog(reference_dir)

    annual_frames: list[pd.DataFrame] = []
    boundary_frames: list[pd.DataFrame] = []
    exclusion_frames: list[pd.DataFrame] = []
    for variant in ANALYSIS_VARIANTS:
        variant_data, exclusions = apply_variant(prepared, variant)
        annual_frames.append(
            aggregate_boundary(
                variant_data,
                group_columns=["plant_name"],
                analysis_variant=variant,
            )
        )
        boundary_data, boundary_status = project_boundaries_from_crosswalk(
            variant_data, crosswalk, analysis_variant=variant
        )
        boundary_frames.append(boundary_data)
        exclusion_frames.append(exclusions)
        exclusion_frames.append(boundary_status)

    project_annual = pd.concat(annual_frames, ignore_index=True)
    project_boundaries = pd.concat(boundary_frames, ignore_index=True)
    comparisons = compare_to_literature(project_boundaries, literature_output)
    summary = summarize_by_pollutant(comparisons)
    readable_comparison, readable_comparison_wide = build_readable_comparison_tables(comparisons)

    unmatched = nonmatched_crosswalk_rows(crosswalk)
    boundary_status = pd.concat(
        [frame for frame in exclusion_frames if "project_rows_after_crosswalk" in frame.columns],
        ignore_index=True,
    )
    unmatched_output = pd.concat([unmatched, boundary_status], ignore_index=True, sort=False)
    excluded_summary = pd.concat(
        [frame for frame in exclusion_frames if "exclusion_reason" in frame.columns],
        ignore_index=True,
    )

    table_output_dir.mkdir(parents=True, exist_ok=True)
    figure_output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "project_annual_emission_factors": project_annual,
        "literature_reference_emission_factors": literature_output,
        "matched_literature_comparisons": comparisons,
        "ef_comparison_readable": readable_comparison,
        "ef_comparison_readable_wide": readable_comparison_wide,
        "validation_summary_by_pollutant": summary,
        "unmatched_or_noncomparable_boundaries": unmatched_output,
        "excluded_observation_summary": excluded_summary,
    }
    for name, frame in outputs.items():
        frame.to_csv(table_output_dir / f"{name}.csv", index=False)
    write_markdown_table(
        readable_comparison_wide,
        table_output_dir / "ef_comparison_readable_wide.md",
    )

    write_scatter_svg(comparisons, figure_output_dir / "project_vs_literature_ef.svg")
    write_percent_difference_svg(
        comparisons, figure_output_dir / "percent_difference_by_plant_pollutant.svg"
    )
    write_timeseries_svg(
        project_annual,
        literature_output,
        figure_output_dir / "project_ef_timeseries_with_literature.svg",
    )

    metadata = build_metadata(input_path, reference_dir, catalog)
    (table_output_dir / "validation_run_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return outputs


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
        "run_timestamp": pd.Timestamp.utcnow().isoformat(),
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
            "Lee et al. (2025) is an external data-pipeline validation, not fully independent measurement evidence, because it uses CleanSYS TMS and EPSIS.",
            "KEEI Table 3-17 is historical company-origin benchmarking and is not a same-year independent measurement comparison.",
            "TSP is never compared directly with PM2.5, and no PM2.5/TSP fraction is applied.",
            "Missing emissions are not treated as zero; matched-period factors require generation and the relevant pollutant mass in the same month.",
        ],
    }
