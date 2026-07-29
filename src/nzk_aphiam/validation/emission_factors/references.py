"""Load and validate tracked literature emission-factor references."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nzk_aphiam.validation.emission_factors.schema import (
    COMBINED_POLLUTANT,
    COMBINED_SCOPE,
    COMPARISON_CLASSES,
    POLLUTANT_COLUMNS,
    reference_path,
)

REFERENCE_KEY = [
    "reference_id",
    "plant_group_id",
    "data_year",
    "pollutant_scope",
    "normalization_basis",
]
OPTIONAL_BENCHMARK_COLUMNS = {
    "pdf_filename": "",
    "source_page": pd.NA,
    "aggregation_scope": "",
    "source_fuel_label": "",
    "source_technology_label": "",
    "normalization_basis": "output_generation_kg_per_mwh",
    "original_value": pd.NA,
    "original_unit": "",
    "benchmark_class": "",
    "direct_comparator": "",
    "review_status": "",
}


def load_literature_benchmarks(reference_dir: Path) -> pd.DataFrame:
    """Load benchmark rows and recalculate factors from stored mass/generation."""
    data = pd.read_csv(reference_path("benchmarks", reference_dir))
    required = {
        "reference_id",
        "plant_group_id",
        "data_year",
        "pollutant",
        "pollutant_scope",
        "generation_mwh",
        "emissions_kg",
        "reported_ef_kg_per_mwh",
        "recalculated_ef_kg_per_mwh",
    }
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Literature benchmarks missing columns: {sorted(missing)}")
    for column, default in OPTIONAL_BENCHMARK_COLUMNS.items():
        if column not in data.columns:
            data[column] = default

    data["pollutant"] = data["pollutant"].replace({"Dust": "TSP"})
    valid_pollutants = set(POLLUTANT_COLUMNS) | {COMBINED_POLLUTANT, "PM2.5", "PM10"}
    unknown = set(data["pollutant"].dropna()) - valid_pollutants
    if unknown:
        raise ValueError(f"Unknown literature pollutants: {sorted(unknown)}")

    scalar_columns = [
        "generation_mwh",
        "emissions_kg",
        "reported_ef_kg_per_mwh",
        "recalculated_ef_kg_per_mwh",
    ]
    for column in scalar_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    calculated = data["emissions_kg"] / data["generation_mwh"].where(data["generation_mwh"].gt(0))
    data["recalculated_ef_kg_per_mwh"] = data["recalculated_ef_kg_per_mwh"].combine_first(
        calculated
    )
    data["reference_ef_kg_per_mwh"] = data["recalculated_ef_kg_per_mwh"].combine_first(
        data["reported_ef_kg_per_mwh"]
    )
    data["reference_generation_mwh"] = data["generation_mwh"]
    data["reference_emissions_kg"] = data["emissions_kg"]

    duplicate_mask = data.duplicated(REFERENCE_KEY, keep=False)
    if duplicate_mask.any():
        duplicates = data.loc[duplicate_mask, REFERENCE_KEY].to_dict("records")
        raise ValueError(f"Duplicate literature benchmark keys: {duplicates}")

    bad_combined = data["pollutant"].eq(COMBINED_POLLUTANT) & data["pollutant_scope"].ne(
        COMBINED_SCOPE
    )
    if bad_combined.any():
        raise ValueError("Combined literature rows must use pollutant_scope NOx+SOx+TSP")
    return data


def load_crosswalk(reference_dir: Path) -> pd.DataFrame:
    """Load the reviewed plant-boundary crosswalk."""
    data = pd.read_csv(reference_path("crosswalk", reference_dir), keep_default_na=False)
    required = {
        "reference_id",
        "literature_plant_group_id",
        "project_plant_name",
        "project_reporting_unit_id",
        "included_unit_numbers",
        "match_status",
        "boundary_match_status",
        "evidence",
        "notes",
    }
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Literature crosswalk missing columns: {sorted(missing)}")
    accepted = data["match_status"].eq("accepted")
    missing_project = accepted & data["project_plant_name"].eq("")
    if missing_project.any():
        raise ValueError("Accepted crosswalk rows must include project_plant_name")
    return data


def load_comparison_rules(reference_dir: Path) -> pd.DataFrame:
    """Load the reviewed rules that authorize or reject quantitative matches."""
    data = pd.read_csv(reference_path("comparison_rules", reference_dir), keep_default_na=False)
    required = {
        "rule_id",
        "reference_id",
        "comparison_class",
        "direct_comparator",
        "required_project_scope",
        "required_plant_group_id",
        "required_unit_scope",
        "required_fuel",
        "required_technology",
        "required_year",
        "required_pollutant",
        "required_pollutant_scope",
        "required_normalization_basis",
        "required_generation_basis",
        "minimum_coverage_fraction",
        "operator_coverage",
        "validation_role",
        "exclusion_reason",
        "review_status",
        "evidence",
    }
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Literature comparison rules missing columns: {sorted(missing)}")
    unknown = set(data["comparison_class"]) - COMPARISON_CLASSES
    if unknown:
        raise ValueError(f"Unknown comparison classes: {sorted(unknown)}")
    if not data["review_status"].eq("reviewed").all():
        raise ValueError("Production comparison rules must all have review_status=reviewed")
    data["direct_comparator"] = (
        data["direct_comparator"].astype(str).str.lower().map({"true": True, "false": False})
    )
    if data["direct_comparator"].isna().any():
        raise ValueError("direct_comparator must be true or false")
    data["minimum_coverage_fraction"] = pd.to_numeric(
        data["minimum_coverage_fraction"], errors="raise"
    )
    if not data["minimum_coverage_fraction"].between(0, 1).all():
        raise ValueError("minimum_coverage_fraction must be between zero and one")
    if data["rule_id"].duplicated().any():
        raise ValueError("Comparison rule IDs must be unique")
    return data


def apply_comparison_rules(literature: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """Attach exactly one explicit reviewed rule to every literature benchmark."""
    rows: list[dict[str, object]] = []
    rule_columns = [column for column in rules.columns if column != "reference_id"]
    for benchmark in literature.to_dict("records"):
        candidates = rules.loc[rules["reference_id"].eq(benchmark["reference_id"])]
        candidates = candidates.loc[
            candidates["required_plant_group_id"].eq("")
            | candidates["required_plant_group_id"].eq(str(benchmark["plant_group_id"]))
        ]
        candidates = candidates.loc[
            candidates["required_pollutant"].map(
                lambda value: _rule_allows(value, str(benchmark["pollutant"]))
            )
        ]
        if len(candidates) != 1:
            raise ValueError(
                "Literature benchmark must have exactly one reviewed comparison rule: "
                f"{benchmark['reference_id']} / {benchmark['plant_group_id']} / "
                f"{benchmark['pollutant']} matched {len(candidates)} rules"
            )
        rule = candidates.iloc[0]
        _validate_rule_against_benchmark(rule, benchmark)
        enriched = dict(benchmark)
        if "direct_comparator" in enriched:
            enriched["catalog_direct_comparator"] = enriched["direct_comparator"]
        for column in rule_columns:
            enriched[column] = rule[column]
        rows.append(enriched)
    return pd.DataFrame(rows)


def _rule_allows(rule_values: str, actual: str) -> bool:
    allowed = {value.strip() for value in str(rule_values).split(";") if value.strip()}
    return not allowed or actual in allowed


def _validate_rule_against_benchmark(rule: pd.Series, benchmark: dict[str, object]) -> None:
    """Reject reviewed rules whose declared source requirements do not match."""
    required_year = str(rule["required_year"]).strip()
    actual_year = benchmark.get("data_year")
    if required_year and (pd.isna(actual_year) or float(required_year) != float(actual_year)):
        raise ValueError(f"Comparison rule year does not match benchmark: {rule['rule_id']}")
    if not _rule_allows(str(rule["required_pollutant_scope"]), str(benchmark["pollutant_scope"])):
        raise ValueError(
            f"Comparison rule pollutant scope does not match benchmark: {rule['rule_id']}"
        )
    required_basis = str(rule["required_normalization_basis"])
    actual_basis = str(benchmark["normalization_basis"])
    basis_matches = (
        actual_basis.startswith("fuel_input")
        if required_basis == "fuel_input"
        else required_basis == actual_basis
    )
    if not basis_matches:
        raise ValueError(
            f"Comparison rule normalization does not match benchmark: {rule['rule_id']}"
        )
    if bool(rule["direct_comparator"]):
        required_fuel = str(rule["required_fuel"])
        if required_fuel and required_fuel != str(benchmark["fuel_type"]):
            raise ValueError(f"Comparison rule fuel does not match benchmark: {rule['rule_id']}")
        if not str(rule["required_generation_basis"]):
            raise ValueError(f"Direct comparison rule lacks generation basis: {rule['rule_id']}")


def load_catalog(reference_dir: Path) -> pd.DataFrame:
    """Load literature source catalog."""
    return pd.read_csv(reference_path("catalog", reference_dir))


def load_pdf_inventory(reference_dir: Path) -> pd.DataFrame:
    """Load reviewed local PDF inventory."""
    return pd.read_csv(reference_path("pdf_inventory", reference_dir))


def parse_unit_scope(scope: str) -> set[float] | None:
    """Parse reviewed unit scopes like ``1-10`` or ``3,4``."""
    scope = str(scope).strip()
    if scope == "" or scope.lower() in {"all", "plant"}:
        return None
    units: set[float] = set()
    for part in scope.split(","):
        part = part.strip().replace("#", "")
        if "-" in part:
            start, end = part.split("-", maxsplit=1)
            units.update(float(i) for i in range(int(start), int(end) + 1))
        else:
            units.add(float(part))
    return units
