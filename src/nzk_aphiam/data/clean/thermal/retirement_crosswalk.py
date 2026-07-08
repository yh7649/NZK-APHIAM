"""Attach reviewed actual or planned retirement dates to thermal units.

Retirement evidence is heterogeneous and hand-reviewed, not scraped from the
subsidiary operating-data APIs. Unit mappings take precedence over explicitly
plant-scoped fallbacks, and no unit date is ever propagated to sibling units.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_RETIREMENT_PATH = (
    PROJECT_ROOT / "docs" / "references" / "crosswalk" / "plant_retirement_dates.csv"
)
DEFAULT_EVIDENCE_PATH = (
    PROJECT_ROOT
    / "docs"
    / "references"
    / "crosswalk"
    / "plant_retirement_dates_official_evidence.csv"
)
REFERENCE_COLUMNS = [
    "subsidiary_company",
    "plant_name",
    "scope",
    "reporting_unit_id",
    "plant_closing_date",
    "plant_closing_date_status",
    "evidence_id",
    "notes",
]
EVIDENCE_COLUMNS = [
    "evidence_id",
    "source_title",
    "source_url",
    "publication_date",
    "accessed_date",
    "evidence",
]
ALLOWED_SCOPES = {"unit", "plant"}
ALLOWED_STATUSES = {"actual", "planned"}
PLANT_KEY = ["subsidiary_company", "plant_name"]


def _require_columns(data: pd.DataFrame, expected: list[str], label: str) -> None:
    if list(data.columns) != expected:
        raise ValueError(
            f"Unexpected {label} columns. Expected {expected!r}, received {list(data.columns)!r}."
        )


def load_retirement_crosswalk(
    path: Path = DEFAULT_RETIREMENT_PATH,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> pd.DataFrame:
    """Load and validate the reviewed retirement reference and its evidence."""
    reference = pd.read_csv(path, dtype="string", keep_default_na=False)
    evidence = pd.read_csv(evidence_path, dtype="string", keep_default_na=False)
    _require_columns(reference, REFERENCE_COLUMNS, "retirement reference")
    _require_columns(evidence, EVIDENCE_COLUMNS, "retirement evidence")

    if evidence["evidence_id"].eq("").any() or evidence["evidence_id"].duplicated().any():
        raise ValueError("Retirement evidence_id values must be nonblank and unique.")
    if not set(reference["scope"]).issubset(ALLOWED_SCOPES):
        bad = sorted(set(reference["scope"]) - ALLOWED_SCOPES)
        raise ValueError(f"Unknown retirement scopes: {bad}")
    if not set(reference["plant_closing_date_status"]).issubset(ALLOWED_STATUSES):
        bad = sorted(set(reference["plant_closing_date_status"]) - ALLOWED_STATUSES)
        raise ValueError(f"Unknown plant_closing_date_status values: {bad}")
    if reference[PLANT_KEY + ["plant_closing_date", "evidence_id"]].eq("").any().any():
        raise ValueError("Retirement mappings require plant, date, and evidence values.")

    unit_rows = reference["scope"].eq("unit")
    plant_rows = reference["scope"].eq("plant")
    if reference.loc[unit_rows, "reporting_unit_id"].eq("").any():
        raise ValueError("Unit-scoped retirement mappings require reporting_unit_id.")
    if reference.loc[plant_rows, "reporting_unit_id"].ne("").any():
        raise ValueError("Plant-scoped retirement mappings must leave reporting_unit_id blank.")
    if reference.loc[unit_rows, "reporting_unit_id"].duplicated().any():
        raise ValueError("Unit-scoped retirement reporting_unit_id values must be unique.")
    if reference.loc[plant_rows, PLANT_KEY].duplicated().any():
        raise ValueError("Plant-scoped retirement mappings must be unique by plant.")

    missing_evidence = sorted(set(reference["evidence_id"]) - set(evidence["evidence_id"]))
    if missing_evidence:
        raise ValueError(f"Retirement mappings reference unknown evidence: {missing_evidence}")

    reference["plant_closing_date"] = pd.to_datetime(
        reference["plant_closing_date"], format="%Y-%m-%d", errors="raise"
    )
    return reference


def apply_retirement_crosswalk(
    data: pd.DataFrame,
    crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apply plant fallbacks first and exact unit mappings second."""
    result = data.copy()
    reference = crosswalk if crosswalk is not None else load_retirement_crosswalk()
    result["plant_closing_date"] = pd.to_datetime(result["plant_closing_date"])
    result["plant_closing_date_status"] = pd.Series(pd.NA, index=result.index, dtype="string")

    companies = set(result["subsidiary_company"].dropna().astype(str))
    relevant = reference[reference["subsidiary_company"].isin(companies)].copy()
    if relevant.empty:
        if result["plant_closing_date"].notna().any():
            raise ValueError("Plant closing dates require a reviewed retirement mapping.")
        return result

    known_plants = set(map(tuple, result[PLANT_KEY].drop_duplicates().astype(str).to_numpy()))
    mapped_plants = set(map(tuple, relevant[PLANT_KEY].drop_duplicates().astype(str).to_numpy()))
    unknown_plants = sorted(mapped_plants - known_plants)
    if unknown_plants:
        raise ValueError(f"Retirement reference contains unknown plants: {unknown_plants}")

    units = relevant[relevant["scope"].eq("unit")]
    known_units = set(result["reporting_unit_id"].dropna().astype(str))
    unknown_units = sorted(set(units["reporting_unit_id"].astype(str)) - known_units)
    if unknown_units:
        raise ValueError(f"Retirement reference contains unknown reporting units: {unknown_units}")

    plants = relevant[relevant["scope"].eq("plant")]
    for row in plants.itertuples(index=False):
        match = result["subsidiary_company"].eq(row.subsidiary_company) & result["plant_name"].eq(
            row.plant_name
        )
        result.loc[match, "plant_closing_date"] = row.plant_closing_date
        result.loc[match, "plant_closing_date_status"] = row.plant_closing_date_status

    for row in units.itertuples(index=False):
        match = result["reporting_unit_id"].eq(row.reporting_unit_id)
        result.loc[match, "plant_closing_date"] = row.plant_closing_date
        result.loc[match, "plant_closing_date_status"] = row.plant_closing_date_status

    unsupported = result["plant_closing_date"].notna() & result["plant_closing_date_status"].isna()
    if unsupported.any():
        raise ValueError("Plant closing dates require a reviewed retirement mapping.")

    return result
