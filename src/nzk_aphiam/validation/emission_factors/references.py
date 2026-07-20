"""Load and validate tracked literature emission-factor references."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nzk_aphiam.validation.emission_factors.schema import (
    COMBINED_POLLUTANT,
    COMBINED_SCOPE,
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
