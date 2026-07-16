"""Comparison metrics between project annual EFs and literature references."""

from __future__ import annotations

import pandas as pd

from nzk_aphiam.validation.emission_factors.schema import COMBINED_POLLUTANT
from nzk_aphiam.validation.emission_factors.utils import (
    percent_difference,
    symmetric_percent_difference,
)


def prepare_literature_output(references: pd.DataFrame) -> pd.DataFrame:
    """Return literature table with recalculated factors and combined Lee rows."""
    base = references.copy()
    lee = base.loc[
        base["reference_id"].eq("lee_2025_kosae") & base["pollutant"].isin(["NOx", "SOx", "TSP"])
    ]
    combined = lee.groupby(
        [
            "reference_id",
            "source_title",
            "source_identifier",
            "publication_year",
            "data_year",
            "source_table",
            "plant_group_id",
            "plant_name_en",
            "plant_name_ko",
            "unit_scope",
            "fuel_type",
            "technology",
            "source_data_origin",
            "validation_role",
            "independence_class",
            "comparability_notes",
            "access_date",
        ],
        as_index=False,
    ).agg(generation_mwh=("generation_mwh", "first"), emissions_kg=("emissions_kg", "sum"))
    combined["pollutant"] = COMBINED_POLLUTANT
    combined["pollutant_scope"] = "NOx+SOx+TSP"
    combined["reported_ef_kg_per_mwh"] = pd.NA
    combined["recalculated_ef_kg_per_mwh"] = combined["emissions_kg"] / combined[
        "generation_mwh"
    ].where(combined["generation_mwh"].gt(0))
    combined["reference_ef_kg_per_mwh"] = combined["recalculated_ef_kg_per_mwh"]
    combined["reference_generation_mwh"] = combined["generation_mwh"]
    combined["reference_emissions_kg"] = combined["emissions_kg"]
    return pd.concat([base, combined], ignore_index=True, sort=False)


def compare_to_literature(
    project_boundaries: pd.DataFrame,
    literature: pd.DataFrame,
) -> pd.DataFrame:
    """Build strict matched project/reference comparisons."""
    if project_boundaries.empty:
        return pd.DataFrame()
    comparable_refs = literature.loc[literature["reference_ef_kg_per_mwh"].notna()].copy()
    merged = project_boundaries.merge(
        comparable_refs,
        left_on=["reference_id", "plant_group_id", "year", "pollutant_scope"],
        right_on=["reference_id", "plant_group_id", "data_year", "pollutant_scope"],
        how="inner",
        suffixes=("_project", "_reference"),
    )
    if merged.empty:
        return merged

    same_pollutant = merged["pollutant_project"].eq(merged["pollutant_reference"])
    combined = merged["pollutant_project"].eq(COMBINED_POLLUTANT) & merged[
        "pollutant_reference"
    ].eq(COMBINED_POLLUTANT)
    merged = merged.loc[same_pollutant | combined].copy()
    strict = (
        merged["complete_calendar_year"].eq(True)
        & merged["boundary_match_status"].isin(["exact", "renamed_exact", "plant"])
        & merged["validation_role"].eq("primary_same_year_external_pipeline_validation")
    )
    merged["comparability_status"] = strict.map(
        {True: "strict_same_year_comparable", False: "non_strict_or_historical_benchmark"}
    )
    merged["coverage_status"] = merged["complete_calendar_year"].map(
        {True: "complete_matched_calendar_year", False: "incomplete_matched_calendar_year"}
    )
    merged["project_generation_mwh"] = merged["generation_mwh_sum"]
    merged["project_emissions_kg"] = merged["pollutant_mass_kg_sum"]
    merged["project_ef_kg_per_mwh"] = merged["ef_kg_per_mwh"]
    merged["reference_ef_kg_per_mwh"] = merged["reference_ef_kg_per_mwh"]
    merged["generation_absolute_difference_mwh"] = (
        merged["project_generation_mwh"] - merged["reference_generation_mwh"]
    )
    merged["generation_percent_difference"] = percent_difference(
        merged["project_generation_mwh"], merged["reference_generation_mwh"]
    )
    merged["emissions_absolute_difference_kg"] = (
        merged["project_emissions_kg"] - merged["reference_emissions_kg"]
    )
    merged["emissions_percent_difference"] = percent_difference(
        merged["project_emissions_kg"], merged["reference_emissions_kg"]
    )
    merged["ef_absolute_difference_kg_per_mwh"] = (
        merged["project_ef_kg_per_mwh"] - merged["reference_ef_kg_per_mwh"]
    )
    merged["ef_percent_difference"] = percent_difference(
        merged["project_ef_kg_per_mwh"], merged["reference_ef_kg_per_mwh"]
    )
    merged["project_to_reference_ratio"] = merged["project_ef_kg_per_mwh"] / merged[
        "reference_ef_kg_per_mwh"
    ].where(merged["reference_ef_kg_per_mwh"].ne(0))
    merged["symmetric_percent_difference"] = symmetric_percent_difference(
        merged["project_ef_kg_per_mwh"], merged["reference_ef_kg_per_mwh"]
    )
    merged["explanatory_notes"] = merged["comparability_notes"].fillna("")
    columns = [
        "reference_id",
        "plant_group_id",
        "plant_name_en",
        "project_plant_name",
        "year",
        "pollutant_project",
        "pollutant_scope",
        "analysis_variant",
        "project_generation_mwh",
        "reference_generation_mwh",
        "generation_absolute_difference_mwh",
        "generation_percent_difference",
        "project_emissions_kg",
        "reference_emissions_kg",
        "emissions_absolute_difference_kg",
        "emissions_percent_difference",
        "project_ef_kg_per_mwh",
        "reference_ef_kg_per_mwh",
        "ef_absolute_difference_kg_per_mwh",
        "ef_percent_difference",
        "project_to_reference_ratio",
        "symmetric_percent_difference",
        "n_matched_months",
        "coverage_status",
        "boundary_match_status",
        "comparability_status",
        "explanatory_notes",
    ]
    return merged[columns].rename(columns={"pollutant_project": "pollutant"})


def summarize_by_pollutant(comparisons: pd.DataFrame) -> pd.DataFrame:
    """Summarize matched strict comparisons by pollutant and variant."""
    if comparisons.empty:
        return pd.DataFrame()
    strict = comparisons.loc[comparisons["comparability_status"].eq("strict_same_year_comparable")]
    if strict.empty:
        return pd.DataFrame()
    return strict.groupby(["analysis_variant", "pollutant"], as_index=False).agg(
        matched_boundaries=("plant_group_id", "nunique"),
        mean_ef_difference_kg_per_mwh=("ef_absolute_difference_kg_per_mwh", "mean"),
        median_ef_percent_difference=("ef_percent_difference", "median"),
        max_abs_ef_percent_difference=("ef_percent_difference", lambda x: x.abs().max()),
        project_generation_mwh=("project_generation_mwh", "sum"),
        reference_generation_mwh=("reference_generation_mwh", "sum"),
    )


def build_readable_comparison_tables(
    comparisons: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return tidy and wide report tables for hand-checking project EFs."""
    if comparisons.empty:
        return pd.DataFrame(), pd.DataFrame()

    report = comparisons.loc[
        comparisons["comparability_status"].eq("strict_same_year_comparable")
        & comparisons["analysis_variant"].eq("reported")
    ].copy()
    if report.empty:
        return pd.DataFrame(), pd.DataFrame()

    report["source_ef_kg_per_mwh"] = report["reference_ef_kg_per_mwh"].round(6)
    report["hand_calculated_ef_kg_per_mwh"] = report["project_ef_kg_per_mwh"].round(6)
    report["percent_error"] = report["ef_percent_difference"].round(2)
    report["generation_percent_error"] = report["generation_percent_difference"].round(2)
    report["emissions_percent_error"] = report["emissions_percent_difference"].round(2)
    report["source"] = (
        report["reference_id"]
        .map({"lee_2025_kosae": "Lee et al. (2025) Table 1"})
        .fillna(report["reference_id"])
    )

    tidy_columns = [
        "source",
        "year",
        "plant_name_en",
        "pollutant",
        "source_ef_kg_per_mwh",
        "hand_calculated_ef_kg_per_mwh",
        "percent_error",
        "generation_percent_error",
        "emissions_percent_error",
        "n_matched_months",
        "coverage_status",
        "boundary_match_status",
    ]
    tidy = report[tidy_columns].rename(
        columns={
            "plant_name_en": "plant",
            "source_ef_kg_per_mwh": "other_source_ef_kg_per_mwh",
            "percent_error": "ef_percent_error",
        }
    )

    wide_metric_names = {
        "source_ef_kg_per_mwh": "other_source_ef",
        "hand_calculated_ef_kg_per_mwh": "hand_calculated_ef",
        "percent_error": "percent_error",
    }
    wide_source = report[
        [
            "source",
            "year",
            "plant_name_en",
            "pollutant",
            *wide_metric_names,
        ]
    ].rename(columns={"plant_name_en": "plant"})
    wide = wide_source.pivot_table(
        index=["source", "year", "plant"],
        columns="pollutant",
        values=list(wide_metric_names),
        aggfunc="first",
    )
    wide.columns = [
        f"{pollutant.lower()}_{wide_metric_names[metric]}_kg_per_mwh"
        if metric != "percent_error"
        else f"{pollutant.lower()}_percent_error"
        for metric, pollutant in wide.columns
    ]
    wide = wide.reset_index()

    ordered_columns = ["source", "year", "plant"]
    for pollutant in ["NOx", "SOx", "TSP", "combined"]:
        key = pollutant.lower()
        ordered_columns.extend(
            [
                f"{key}_other_source_ef_kg_per_mwh",
                f"{key}_hand_calculated_ef_kg_per_mwh",
                f"{key}_percent_error",
            ]
        )
    ordered_columns = [column for column in ordered_columns if column in wide.columns]
    wide = wide[ordered_columns]
    return tidy.sort_values(["plant", "pollutant"]).reset_index(drop=True), wide.sort_values(
        "plant"
    ).reset_index(drop=True)
