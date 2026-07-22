"""Scientifically reviewed comparisons between project and literature EFs."""

from __future__ import annotations

import pandas as pd

from nzk_aphiam.validation.emission_factors.references import parse_unit_scope
from nzk_aphiam.validation.emission_factors.schema import (
    COMBINED_POLLUTANT,
    DIRECT_VALIDATION_CLASSES,
    SMALL_EXTERNAL_EF_THRESHOLD,
)
from nzk_aphiam.validation.emission_factors.utils import (
    percent_difference,
    symmetric_percent_difference,
)

INCLUDED_DIRECT = "included_external_validation"
INCLUDED_AGGREGATE = "included_aggregate_consistency_check"


def prepare_literature_output(references: pd.DataFrame) -> pd.DataFrame:
    """Return the source inventory with recalculated and Lee combined diagnostics."""
    base = references.copy()
    lee = base.loc[
        base["reference_id"].eq("lee_2025_kosae") & base["pollutant"].isin(["NOx", "SOx", "TSP"])
    ]
    group_columns = [
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
        "aggregation_scope",
        "fuel_type",
        "source_fuel_label",
        "technology",
        "source_technology_label",
        "normalization_basis",
        "benchmark_class",
        "source_data_origin",
        "validation_role",
        "independence_class",
        "direct_comparator",
        "comparability_notes",
        "review_status",
        "access_date",
    ]
    combined = lee.groupby(group_columns, as_index=False).agg(
        generation_mwh=("generation_mwh", "first"),
        emissions_kg=("emissions_kg", "sum"),
    )
    combined["pollutant"] = COMBINED_POLLUTANT
    combined["pollutant_scope"] = "NOx+SOx+TSP"
    combined["reported_ef_kg_per_mwh"] = pd.NA
    combined["recalculated_ef_kg_per_mwh"] = combined["emissions_kg"] / combined[
        "generation_mwh"
    ].where(combined["generation_mwh"].gt(0))
    combined["reference_ef_kg_per_mwh"] = combined["recalculated_ef_kg_per_mwh"]
    combined["reference_generation_mwh"] = combined["generation_mwh"]
    combined["reference_emissions_kg"] = combined["emissions_kg"]
    combined["source_method_diagnostic"] = True
    base["source_method_diagnostic"] = False
    return pd.concat([base, combined], ignore_index=True, sort=False)


def compare_to_literature(
    project_boundaries: pd.DataFrame,
    literature: pd.DataFrame,
) -> pd.DataFrame:
    """Evaluate only explicitly authorized plant/unit comparisons."""
    required_rule_columns = {
        "comparison_class",
        "direct_comparator",
        "required_fuel",
        "required_technology",
        "required_normalization_basis",
        "required_generation_basis",
        "minimum_coverage_fraction",
    }
    if (
        project_boundaries.empty
        or literature.empty
        or not required_rule_columns.issubset(literature.columns)
    ):
        return pd.DataFrame()
    references = literature.loc[
        literature["comparison_class"].isin(DIRECT_VALIDATION_CLASSES)
        & literature["direct_comparator"].eq(True)
        & literature["reference_ef_kg_per_mwh"].notna()
    ].copy()
    merged = project_boundaries.merge(
        references,
        left_on=["reference_id", "plant_group_id", "year", "pollutant_scope"],
        right_on=["reference_id", "plant_group_id", "data_year", "pollutant_scope"],
        how="inner",
        suffixes=("_project", "_external"),
    )
    if merged.empty:
        return merged
    merged = merged.loc[merged["pollutant_project"].eq(merged["pollutant_external"])].copy()
    if merged.empty:
        return merged

    merged["declared_comparison_class"] = merged["comparison_class"]
    reasons = merged.apply(_plant_exclusion_reason, axis=1)
    merged["exclusion_reason"] = reasons
    included = reasons.eq("")
    merged["comparison_status"] = included.map(
        {True: INCLUDED_DIRECT, False: "excluded_scientific_mismatch"}
    )
    coverage_mismatch = reasons.eq("incomplete_pollutant_year_coverage")
    merged.loc[coverage_mismatch, "comparison_status"] = "excluded_coverage_mismatch"
    historical_mismatch = reasons.eq("historical_fuel_mapping_unresolved")
    merged.loc[historical_mismatch, "comparison_status"] = "excluded_historical_fuel_ambiguity"
    merged.loc[~included, "comparison_class"] = "D_contextual_benchmark"
    merged["comparison_label"] = merged.apply(_comparison_label, axis=1)
    merged["coverage_status"] = included.map(
        {True: "complete_required_unit_month_coverage", False: "incomplete_or_mismatched"}
    )
    merged = _standardize_plant_attempts(merged)
    return _add_ef_metrics(merged, included)


def _plant_exclusion_reason(row: pd.Series) -> str:
    if str(row.get("required_normalization_basis", "")) != str(row.get("normalization_basis", "")):
        return "normalization_basis_mismatch"
    if str(row.get("required_generation_basis", "")) != "electricity_generation_mwh":
        return "generation_denominator_mismatch"
    if str(row.get("boundary_match_status", "")) not in {"exact", "renamed_exact"}:
        return "plant_or_unit_boundary_mismatch"
    required_units = parse_unit_scope(str(row.get("required_unit_scope", "")))
    if required_units is not None and int(row.get("n_boundary_units", 0)) != len(required_units):
        return "plant_or_unit_boundary_mismatch"
    project_fuels = _split_values(row.get("fuel_type_project", ""))
    required_fuel = str(row.get("required_fuel", ""))
    if len(project_fuels) != 1:
        return "historical_fuel_mapping_unresolved"
    if required_fuel and project_fuels != {required_fuel}:
        return "fuel_mismatch"
    project_technologies = _split_values(row.get("technology_project", ""))
    required_technology = str(row.get("required_technology", ""))
    if len(project_technologies) != 1:
        return "historical_technology_mapping_unresolved"
    if required_technology and project_technologies != {required_technology}:
        return "technology_mismatch"
    coverage = pd.to_numeric(pd.Series([row.get("coverage_fraction")]), errors="coerce").iloc[0]
    minimum = float(row.get("minimum_coverage_fraction", 1.0))
    if pd.isna(coverage) or coverage < minimum or not bool(row.get("complete_calendar_year")):
        return "incomplete_pollutant_year_coverage"
    return ""


def _standardize_plant_attempts(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    result["external_generation_mwh"] = result["reference_generation_mwh"]
    result["kepco_generation_mwh"] = result["generation_mwh_sum"]
    result["generation_difference_mwh"] = (
        result["kepco_generation_mwh"] - result["external_generation_mwh"]
    )
    result["generation_percent_difference"] = percent_difference(
        result["kepco_generation_mwh"], result["external_generation_mwh"]
    )
    result["external_pollutant_mass_kg"] = result["reference_emissions_kg"]
    result["kepco_pollutant_mass_kg"] = result["pollutant_mass_kg_sum"]
    result["mass_difference_kg"] = (
        result["kepco_pollutant_mass_kg"] - result["external_pollutant_mass_kg"]
    )
    result["mass_percent_difference"] = percent_difference(
        result["kepco_pollutant_mass_kg"], result["external_pollutant_mass_kg"]
    )
    result["external_ef_kg_per_mwh"] = result["reference_ef_kg_per_mwh"]
    result["kepco_ef_kg_per_mwh"] = result["ef_kg_per_mwh"]
    result["ef_difference_kg_per_mwh"] = (
        result["kepco_ef_kg_per_mwh"] - result["external_ef_kg_per_mwh"]
    )
    result["pollutant"] = result["pollutant_project"]
    return result


def compare_aggregate_fuel_year(
    project_fuel_year: pd.DataFrame,
    literature: pd.DataFrame,
) -> pd.DataFrame:
    """Compare one ratio-of-sums KEPCO fuel fleet with each MOTIE fuel value."""
    if project_fuel_year.empty or literature.empty:
        return pd.DataFrame()
    references = literature.loc[
        literature.get("comparison_class", pd.Series(index=literature.index)).eq(
            "C_aggregate_consistency_check"
        )
        & literature.get("direct_comparator", pd.Series(index=literature.index)).eq(True)
        & literature["reference_ef_kg_per_mwh"].notna()
    ].copy()
    if references.empty:
        return pd.DataFrame()
    project = project_fuel_year.drop(columns=["reference_id", "plant_group_id"], errors="ignore")
    merged = project.merge(
        references,
        left_on=["year", "fuel_type", "pollutant_scope"],
        right_on=["data_year", "required_fuel", "pollutant_scope"],
        how="inner",
        suffixes=("_project", "_external"),
    )
    if merged.empty:
        return merged
    merged = merged.loc[merged["pollutant_project"].eq(merged["pollutant_external"])].copy()
    if merged.empty:
        return merged
    coverage = pd.to_numeric(merged["coverage_fraction"], errors="coerce")
    minimum = pd.to_numeric(merged["minimum_coverage_fraction"], errors="coerce")
    calendar_coverage = pd.to_numeric(merged["calendar_month_coverage_fraction"], errors="coerce")
    included = coverage.ge(minimum) & calendar_coverage.eq(1.0)
    merged["comparison_status"] = included.map(
        {True: INCLUDED_AGGREGATE, False: "excluded_coverage_mismatch"}
    )
    merged["exclusion_reason"] = included.map(
        {True: "", False: "incomplete_pollutant_year_coverage"}
    )
    merged["comparison_label"] = "Aggregate consistency check"
    merged["external_generation_mwh"] = merged["reference_generation_mwh"]
    merged["kepco_generation_mwh"] = merged["generation_mwh_sum"]
    merged["external_pollutant_mass_kg"] = merged["reference_emissions_kg"]
    merged["kepco_pollutant_mass_kg"] = merged["pollutant_mass_kg_sum"]
    merged["external_ef_kg_per_mwh"] = merged["reference_ef_kg_per_mwh"]
    merged["kepco_ef_kg_per_mwh"] = merged["ef_kg_per_mwh"]
    merged["ef_difference_kg_per_mwh"] = (
        merged["kepco_ef_kg_per_mwh"] - merged["external_ef_kg_per_mwh"]
    )
    merged["pollutant"] = merged["pollutant_project"]
    return _add_ef_metrics(merged, included)


def compare_fuel_technology_year(
    project_fuel_technology: pd.DataFrame,
    literature: pd.DataFrame,
) -> pd.DataFrame:
    """Backward-compatible guard: aggregate technology rows before any comparison."""
    needed = {"generation_mwh_sum", "pollutant_mass_kg_sum"}
    if project_fuel_technology.empty or not needed.issubset(project_fuel_technology.columns):
        return pd.DataFrame()
    group_columns = [
        "year",
        "fuel_type",
        "pollutant",
        "pollutant_scope",
        "analysis_variant",
    ]
    aggregate = project_fuel_technology.groupby(group_columns, as_index=False).agg(
        generation_mwh_sum=("generation_mwh_sum", "sum"),
        pollutant_mass_kg_sum=("pollutant_mass_kg_sum", "sum"),
        coverage_fraction=("coverage_fraction", "min"),
        calendar_month_coverage_fraction=("calendar_month_coverage_fraction", "min"),
        complete_calendar_year=("complete_calendar_year", "all"),
        missing_months=(
            "missing_months",
            lambda values: ";".join(filter(None, values.astype(str))),
        ),
    )
    aggregate["ef_kg_per_mwh"] = aggregate["pollutant_mass_kg_sum"] / aggregate[
        "generation_mwh_sum"
    ].where(aggregate["generation_mwh_sum"].gt(0))
    return compare_aggregate_fuel_year(aggregate, literature)


def _add_ef_metrics(data: pd.DataFrame, valid: pd.Series) -> pd.DataFrame:
    result = data.copy()
    result["absolute_difference_kg_per_mwh"] = (
        result["kepco_ef_kg_per_mwh"] - result["external_ef_kg_per_mwh"]
    )
    result["small_external_denominator_flag"] = (
        result["external_ef_kg_per_mwh"].abs() <= SMALL_EXTERNAL_EF_THRESHOLD
    )
    result["percent_difference"] = percent_difference(
        result["kepco_ef_kg_per_mwh"], result["external_ef_kg_per_mwh"]
    )
    result["ratio"] = result["kepco_ef_kg_per_mwh"] / result["external_ef_kg_per_mwh"].where(
        result["external_ef_kg_per_mwh"].ne(0)
    )
    result["symmetric_percent_difference"] = symmetric_percent_difference(
        result["kepco_ef_kg_per_mwh"], result["external_ef_kg_per_mwh"]
    )
    suppress_percent = ~valid | result["small_external_denominator_flag"]
    result.loc[suppress_percent, "percent_difference"] = pd.NA
    result.loc[~valid, ["ratio", "symmetric_percent_difference"]] = pd.NA
    return result


def build_plant_input_reconciliation(
    attempts: pd.DataFrame,
    literature: pd.DataFrame | None = None,
    crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Report Lee generation and mass reconciliation before EF diagnostics."""
    columns = [
        "reference_id",
        "plant_group_id",
        "plant_name_en",
        "project_plant_name",
        "year",
        "pollutant",
        "analysis_variant",
        "external_generation_mwh",
        "kepco_generation_mwh",
        "generation_difference_mwh",
        "external_pollutant_mass_kg",
        "kepco_pollutant_mass_kg",
        "mass_difference_kg",
        "external_ef_kg_per_mwh",
        "kepco_ef_kg_per_mwh",
        "ef_difference_kg_per_mwh",
        "coverage_fraction",
        "missing_months",
        "comparison_class",
        "comparison_status",
        "exclusion_reason",
    ]
    if attempts.empty:
        lee = pd.DataFrame(columns=columns)
    else:
        lee = attempts.loc[
            attempts["reference_id"].eq("lee_2025_kosae")
            & attempts["pollutant"].isin(["NOx", "SOx", "TSP"])
        ].reindex(columns=columns)
    if literature is not None and not literature.empty:
        existing = {
            (row.reference_id, row.plant_group_id, row.pollutant)
            for row in lee.itertuples(index=False)
        }
        boundary_lookup = (
            {
                (row["reference_id"], row["literature_plant_group_id"]): row
                for row in crosswalk.to_dict("records")
            }
            if crosswalk is not None
            else {}
        )
        missing_rows = []
        source_rows = literature.loc[
            literature["reference_id"].eq("lee_2025_kosae")
            & literature["pollutant"].isin(["NOx", "SOx", "TSP"])
        ]
        for row in source_rows.to_dict("records"):
            key = (row["reference_id"], row["plant_group_id"], row["pollutant"])
            if key in existing:
                continue
            boundary = boundary_lookup.get((row["reference_id"], row["plant_group_id"]), {})
            missing_rows.append(
                {
                    "reference_id": row["reference_id"],
                    "plant_group_id": row["plant_group_id"],
                    "plant_name_en": row.get("plant_name_en"),
                    "project_plant_name": boundary.get("project_plant_name", ""),
                    "year": row.get("data_year"),
                    "pollutant": row["pollutant"],
                    "analysis_variant": pd.NA,
                    "external_generation_mwh": row.get("reference_generation_mwh"),
                    "external_pollutant_mass_kg": row.get("reference_emissions_kg"),
                    "external_ef_kg_per_mwh": row.get("reference_ef_kg_per_mwh"),
                    "comparison_class": "D_contextual_benchmark",
                    "comparison_status": "excluded_no_project_match",
                    "exclusion_reason": boundary.get(
                        "boundary_match_status", "no_project_observations_for_required_year"
                    ),
                }
            )
        if missing_rows:
            lee = pd.concat(
                [lee, pd.DataFrame(missing_rows).reindex(columns=columns)],
                ignore_index=True,
            )
    return lee.sort_values(["analysis_variant", "plant_name_en", "pollutant"])


def build_contextual_literature_benchmarks(
    literature: pd.DataFrame,
    plant_attempts: pd.DataFrame,
    crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return class D source values without ordinary percent-error fields."""
    rows: list[dict[str, object]] = []
    contextual = literature.loc[literature["comparison_class"].eq("D_contextual_benchmark")]
    for row in contextual.to_dict("records"):
        rows.append(
            {
                **row,
                "external_ef_kg_per_mwh": row.get("reference_ef_kg_per_mwh"),
                "kepco_ef_kg_per_mwh": pd.NA,
                "ef_difference_kg_per_mwh": pd.NA,
                "comparison_status": "contextual_only",
                "comparison_label": _comparison_label(pd.Series(row)),
            }
        )
    if not plant_attempts.empty:
        excluded = plant_attempts.loc[
            plant_attempts["comparison_class"].eq("D_contextual_benchmark")
        ]
        rows.extend(excluded.to_dict("records"))
    attempted_keys = (
        {
            (row.reference_id, row.plant_group_id, row.pollutant, row.year)
            for row in plant_attempts.itertuples(index=False)
        }
        if not plant_attempts.empty
        else set()
    )
    boundary_lookup = (
        {
            (row["reference_id"], row["literature_plant_group_id"]): row
            for row in crosswalk.to_dict("records")
        }
        if crosswalk is not None
        else {}
    )
    unmatched_plant = literature.loc[
        literature["comparison_class"].isin(DIRECT_VALIDATION_CLASSES)
    ]
    for row in unmatched_plant.to_dict("records"):
        key = (row["reference_id"], row["plant_group_id"], row["pollutant"], row["data_year"])
        if key in attempted_keys:
            continue
        boundary = boundary_lookup.get((row["reference_id"], row["plant_group_id"]), {})
        contextual_row = {
            **row,
            "declared_comparison_class": row["comparison_class"],
            "comparison_class": "D_contextual_benchmark",
            "external_ef_kg_per_mwh": row.get("reference_ef_kg_per_mwh"),
            "kepco_ef_kg_per_mwh": pd.NA,
            "ef_difference_kg_per_mwh": pd.NA,
            "comparison_status": "excluded_no_project_match",
            "exclusion_reason": boundary.get(
                "boundary_match_status", "no_project_observations_for_required_year"
            ),
        }
        contextual_row["comparison_label"] = _comparison_label(pd.Series(contextual_row))
        rows.append(contextual_row)
    result = pd.DataFrame(rows)
    forbidden = [column for column in result.columns if "percent_difference" in column]
    return result.drop(columns=forbidden, errors="ignore")


def build_rejected_or_noncomparable_comparisons(
    literature: pd.DataFrame,
    plant_attempts: pd.DataFrame,
    aggregate_attempts: pd.DataFrame,
    crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Return every reviewed non-match and attempted comparison that was rejected."""
    rows: list[dict[str, object]] = []
    for row in literature.loc[literature["direct_comparator"].eq(False)].to_dict("records"):
        rows.append(
            {
                **row,
                "comparison_status": "excluded_by_reviewed_rule",
                "attempted_match_scope": row.get("required_project_scope", ""),
                "external_ef_kg_per_mwh": row.get("reference_ef_kg_per_mwh"),
                "exclusion_reason": row.get("exclusion_reason")
                or "no_quantitative_match_authorized",
            }
        )

    attempted_frames = []
    for attempts in [plant_attempts, aggregate_attempts]:
        if not attempts.empty:
            attempted_frames.append(attempts)
            excluded = attempts.loc[
                ~attempts["comparison_status"].isin([INCLUDED_DIRECT, INCLUDED_AGGREGATE])
            ].copy()
            excluded["attempted_match_scope"] = excluded.get("required_project_scope", "")
            rows.extend(excluded.to_dict("records"))

    attempted_keys: set[tuple[object, ...]] = set()
    for attempts in attempted_frames:
        attempted_keys.update(
            zip(
                attempts["reference_id"],
                attempts["plant_group_id"],
                attempts["pollutant"],
                attempts["year"],
                strict=False,
            )
        )
    crosswalk_lookup = {
        (row["reference_id"], row["literature_plant_group_id"]): row
        for row in crosswalk.to_dict("records")
    }
    authorized = literature.loc[literature["direct_comparator"].eq(True)]
    for row in authorized.to_dict("records"):
        key = (row["reference_id"], row["plant_group_id"], row["pollutant"], row["data_year"])
        if key in attempted_keys:
            continue
        boundary = crosswalk_lookup.get((row["reference_id"], row["plant_group_id"]))
        if boundary and boundary["match_status"] != "accepted":
            reason = boundary["boundary_match_status"]
        else:
            reason = "no_project_observations_for_required_year"
        rows.append(
            {
                **row,
                "declared_comparison_class": row["comparison_class"],
                "comparison_class": (
                    "D_contextual_benchmark"
                    if row["comparison_class"] in DIRECT_VALIDATION_CLASSES
                    else row["comparison_class"]
                ),
                "comparison_status": "excluded_no_project_match",
                "attempted_match_scope": row.get("required_project_scope", ""),
                "external_ef_kg_per_mwh": row.get("reference_ef_kg_per_mwh"),
                "exclusion_reason": reason,
            }
        )
    rejected = pd.DataFrame(rows)
    if rejected.empty:
        return rejected
    rejected["exclusion_reason"] = rejected["exclusion_reason"].fillna("").astype(str)
    if rejected["exclusion_reason"].eq("").any():
        raise ValueError("Every rejected comparison must have an exclusion_reason")
    rejected["comparison_label"] = rejected.apply(_comparison_label, axis=1)
    dedupe = [
        column
        for column in [
            "reference_id",
            "plant_group_id",
            "data_year",
            "pollutant",
            "analysis_variant",
            "comparison_status",
            "exclusion_reason",
        ]
        if column in rejected.columns
    ]
    rejected = rejected.drop_duplicates(dedupe).reset_index(drop=True)
    forbidden = [column for column in rejected.columns if "percent_difference" in column]
    return rejected.drop(columns=forbidden, errors="ignore")


def build_source_coverage_matrix(literature: pd.DataFrame) -> pd.DataFrame:
    """Expose literature availability without manufacturing project comparisons."""
    work = literature.copy()
    work["evidence_count"] = 1
    return (
        work.groupby(
            [
                "fuel_type",
                "technology",
                "data_year",
                "pollutant",
                "comparison_class",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            evidence_count=("evidence_count", "sum"),
            sources=("reference_id", lambda values: ";".join(sorted(set(values)))),
            direct_comparator=("direct_comparator", "any"),
        )
        .sort_values(
            ["fuel_type", "technology", "data_year", "pollutant", "comparison_class"],
            na_position="last",
        )
    )


def summarize_by_pollutant(comparisons: pd.DataFrame) -> pd.DataFrame:
    """Summarize only included A/B observations."""
    if comparisons.empty:
        return pd.DataFrame()
    direct = comparisons.loc[comparisons["comparison_status"].eq(INCLUDED_DIRECT)]
    if direct.empty:
        return pd.DataFrame()
    return direct.groupby(["analysis_variant", "pollutant"], as_index=False).agg(
        matched_boundaries=("plant_group_id", "nunique"),
        mean_ef_difference_kg_per_mwh=("absolute_difference_kg_per_mwh", "mean"),
        median_percent_difference=("percent_difference", "median"),
        max_abs_percent_difference=("percent_difference", lambda values: values.abs().max()),
        kepco_generation_mwh=("kepco_generation_mwh", "sum"),
        external_generation_mwh=("external_generation_mwh", "sum"),
    )


def build_readable_comparison_tables(
    comparisons: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return plant-level validation tables with input reconciliation fields."""
    if comparisons.empty:
        return pd.DataFrame(), pd.DataFrame()
    report = comparisons.loc[
        comparisons["comparison_status"].eq(INCLUDED_DIRECT)
        & comparisons["analysis_variant"].eq("reported")
    ].copy()
    if report.empty:
        return pd.DataFrame(), pd.DataFrame()
    tidy = report[
        [
            "reference_id",
            "year",
            "plant_name_en",
            "pollutant",
            "external_generation_mwh",
            "kepco_generation_mwh",
            "generation_difference_mwh",
            "external_pollutant_mass_kg",
            "kepco_pollutant_mass_kg",
            "mass_difference_kg",
            "external_ef_kg_per_mwh",
            "kepco_ef_kg_per_mwh",
            "absolute_difference_kg_per_mwh",
            "percent_difference",
            "ratio",
            "symmetric_percent_difference",
            "small_external_denominator_flag",
            "coverage_fraction",
        ]
    ].rename(columns={"plant_name_en": "plant"})
    wide_source = tidy[
        [
            "reference_id",
            "year",
            "plant",
            "pollutant",
            "external_ef_kg_per_mwh",
            "kepco_ef_kg_per_mwh",
            "percent_difference",
        ]
    ]
    wide = wide_source.pivot_table(
        index=["reference_id", "year", "plant"],
        columns="pollutant",
        values=["external_ef_kg_per_mwh", "kepco_ef_kg_per_mwh", "percent_difference"],
        aggfunc="first",
    )
    wide.columns = [f"{pollutant.lower()}_{metric}" for metric, pollutant in wide.columns]
    return (
        tidy.sort_values(["plant", "pollutant"]).reset_index(drop=True),
        wide.reset_index().sort_values("plant").reset_index(drop=True),
    )


def build_presentation_summary(comparisons: pd.DataFrame) -> pd.DataFrame:
    """Return a concise aggregate-check presentation table."""
    if comparisons.empty:
        return pd.DataFrame()
    return comparisons.loc[
        comparisons["comparison_status"].eq(INCLUDED_AGGREGATE)
        & comparisons["analysis_variant"].eq("reported")
    ].copy()


def build_unmatched_literature_benchmarks(
    literature: pd.DataFrame, comparisons: pd.DataFrame
) -> pd.DataFrame:
    """Compatibility helper returning reviewed non-direct literature rows."""
    del comparisons
    return literature.loc[literature["direct_comparator"].eq(False)].copy()


def _split_values(value: object) -> set[str]:
    return {part.strip() for part in str(value).split(";") if part.strip() and part != "nan"}


def _comparison_label(row: pd.Series) -> str:
    comparison_class = str(row.get("comparison_class", ""))
    role = str(row.get("validation_role", ""))
    if comparison_class in DIRECT_VALIDATION_CLASSES:
        return "Plant-level external validation"
    if comparison_class == "C_aggregate_consistency_check":
        return "Aggregate consistency check"
    if role == "methodological_precedent":
        return "Methodological precedent"
    if comparison_class == "D_contextual_benchmark":
        return "Engineering/contextual benchmark"
    return "Not directly comparable"
