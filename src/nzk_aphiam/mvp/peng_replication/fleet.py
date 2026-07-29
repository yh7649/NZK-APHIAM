"""Resolve the existing processed KEPCO thermal roster without fuzzy matching."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
import re
from typing import Any

import pandas as pd


def _slug(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return text or sha1(str(value).encode()).hexdigest()[:12]


def _year(value: object) -> float:
    if pd.isna(value) or str(value).strip() == "":
        return float("nan")
    parsed = pd.to_datetime(value, errors="coerce")
    return float(parsed.year) if not pd.isna(parsed) else float("nan")


def _first_nonmissing(series: pd.Series) -> Any:
    values = series.dropna()
    return values.iloc[0] if not values.empty else pd.NA


def add_canonical_unit_ids(monthly: pd.DataFrame) -> pd.DataFrame:
    """Attach the canonical reporting-boundary identifier used by the fleet."""
    required = {
        "subsidiary_company",
        "plant_name",
        "reporting_unit_id",
        "fuel_type",
        "technology",
    }
    missing = sorted(required - set(monthly.columns))
    if missing:
        raise ValueError(f"Monthly KEPCO data are missing unit identity columns: {missing}")
    prepared = monthly.copy()
    fallback_id = (
        prepared["subsidiary_company"].astype(str)
        + ":"
        + prepared["plant_name"].astype(str)
        + ":site_boundary:"
        + prepared["fuel_type"].astype(str)
        + ":"
        + prepared["technology"].astype(str)
    )
    prepared["unit_id"] = prepared["reporting_unit_id"].fillna(fallback_id)
    return prepared


def build_thermal_fleet(
    monthly_path: Path,
    *,
    representative_sites: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one row per documented unit/reporting boundary plus configured sites."""
    monthly = pd.read_csv(monthly_path, low_memory=False)
    required = {
        "subsidiary_company",
        "plant_name",
        "reporting_unit_id",
        "plant_province",
        "fuel_type",
        "technology",
        "energy_capacity_mw",
        "plant_latitude",
        "plant_longitude",
        "plant_opening_date",
        "plant_closing_date",
        "energy_generated_mwh",
        "date",
    }
    missing = sorted(required - set(monthly.columns))
    if missing:
        raise ValueError(f"{monthly_path} is missing roster columns: {missing}")
    monthly = monthly.loc[monthly["fuel_type"].notna() & monthly["technology"].notna()].copy()
    monthly = add_canonical_unit_ids(monthly)
    monthly["plant_id"] = (
        monthly["subsidiary_company"].map(_slug) + ":" + monthly["plant_name"].map(_slug)
    )
    monthly["year"] = pd.to_datetime(monthly["date"], errors="coerce").dt.year
    recent = (
        monthly.loc[monthly["year"].between(2019, 2021)]
        .groupby("unit_id")["energy_generated_mwh"]
        .sum(min_count=1)
    )
    roster = monthly.groupby("unit_id", as_index=False, sort=True).agg(
        plant_id=("plant_id", _first_nonmissing),
        plant_name=("plant_name", _first_nonmissing),
        subsidiary_company=("subsidiary_company", _first_nonmissing),
        province=("plant_province", _first_nonmissing),
        district=("plant_district", _first_nonmissing),
        fuel=("fuel_type", _first_nonmissing),
        technology=("technology", _first_nonmissing),
        capacity_mw=("energy_capacity_mw", "max"),
        latitude=("plant_latitude", _first_nonmissing),
        longitude=("plant_longitude", _first_nonmissing),
        opening_date=("plant_opening_date", _first_nonmissing),
        closing_date=("plant_closing_date", _first_nonmissing),
        closing_date_status=("plant_closing_date_status", _first_nonmissing),
        original_korean_plant_name=("original_korean_plant_name", _first_nonmissing),
    )
    roster["commissioning_year"] = roster["opening_date"].map(_year)
    roster["retirement_year"] = roster["closing_date"].map(_year)
    roster["recent_historical_generation_mwh"] = roster["unit_id"].map(recent)
    roster["roster_source"] = str(monthly_path)
    roster["coordinate_provenance"] = "processed_canonical_plant_crosswalk"
    roster["synthetic_site_flag"] = False
    roster["site_role"] = "canonical_kepco_unit_or_reporting_boundary"

    additional = pd.DataFrame(representative_sites)
    if not additional.empty:
        additional["subsidiary_company"] = "non_kepco_representative_site"
        additional["district"] = pd.NA
        additional["opening_date"] = pd.NA
        additional["closing_date"] = pd.NA
        additional["closing_date_status"] = pd.NA
        additional["retirement_year"] = pd.NA
        additional["recent_historical_generation_mwh"] = pd.NA
        additional["original_korean_plant_name"] = pd.NA
        additional["roster_source"] = additional.pop("source")
        additional["synthetic_site_flag"] = False
        additional["site_role"] = "real_representative_thermal_site_for_province_coverage"
        additional["opening_date"] = additional["commissioning_year"].map(
            lambda value: f"{int(value)}-01-01" if pd.notna(value) else pd.NA
        )
        roster = pd.concat([roster, additional], ignore_index=True, sort=False)

    numeric = ["capacity_mw", "latitude", "longitude", "commissioning_year", "retirement_year"]
    for column in numeric:
        roster[column] = pd.to_numeric(roster[column], errors="coerce")
    roster["coordinate_valid"] = roster["latitude"].between(33.0, 39.0) & roster[
        "longitude"
    ].between(124.0, 132.0)
    roster["retirement_inconsistency"] = (
        roster["commissioning_year"].notna()
        & roster["retirement_year"].notna()
        & (roster["retirement_year"] < roster["commissioning_year"])
    )
    diagnostics = roster[
        [
            "plant_id",
            "unit_id",
            "plant_name",
            "province",
            "fuel",
            "technology",
            "capacity_mw",
            "latitude",
            "longitude",
            "coordinate_valid",
            "commissioning_year",
            "retirement_year",
            "retirement_inconsistency",
            "coordinate_provenance",
            "roster_source",
        ]
    ].copy()
    diagnostics["missing_coordinates"] = roster[["latitude", "longitude"]].isna().any(axis=1)
    diagnostics["missing_province"] = roster["province"].isna()
    diagnostics["missing_fuel"] = roster["fuel"].isna()
    diagnostics["missing_technology"] = roster["technology"].isna()
    diagnostics["missing_capacity"] = roster["capacity_mw"].isna()
    if roster["unit_id"].duplicated().any():
        raise ValueError("Canonical roster contains duplicate unit_id values.")
    invalid = roster.loc[~roster["coordinate_valid"], ["unit_id", "latitude", "longitude"]]
    if not invalid.empty:
        raise ValueError(f"Fleet has invalid or missing coordinates:\n{invalid}")
    return roster.sort_values(["province", "plant_name", "unit_id"]).reset_index(
        drop=True
    ), diagnostics
