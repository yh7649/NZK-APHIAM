"""Map native GCAM activity to stable non-power IDs and approved Korean factors."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterable

import numpy as np
import pandas as pd

from nzk_aphiam.config.paths import (
    GCAM_NZK_APHIAM_DIR,
    NONPOWER_PROCESSED_DIR,
    NONPOWER_REFERENCE_DIR,
)

CROSSWALK_FILE = "gcam_kaist_native_activity_crosswalk.csv"
INVENTORY_FILE = "gcam_kaist_nonpower_sector_inventory.csv"
POC_CONVERSION_FILE = "gcam_nzk_poc_activity_conversion_assumptions.csv"
CROSSWALK_COLUMNS = (
    "mapping_id",
    "inventory_id",
    "record_type",
    "sector_type",
    "sector_pattern",
    "subsector_type",
    "subsector_pattern",
    "technology_type",
    "technology_pattern",
    "node_type",
    "node_pattern",
    "native_unit",
    "native_to_canonical_multiplier",
    "canonical_activity_unit",
    "canonical_fuel",
    "match_status",
    "include_in_emissions_model",
    "note",
)
ACTIVITY_MATCH_COLUMNS = (
    ("record_type", "record_type"),
    ("sector_type", "sector_type"),
    ("sector_pattern", "sector"),
    ("subsector_type", "subsector_type"),
    ("subsector_pattern", "subsector"),
    ("technology_type", "technology_type"),
    ("technology_pattern", "technology"),
    ("node_type", "node_type"),
    ("node_pattern", "node"),
    ("native_unit", "activity_unit"),
)
INMAP_POLLUTANTS = {"VOCs", "NOx", "NH3", "SOx", "PM2.5"}
NONPRODUCTION_MAPPING_STATUSES = {
    "documented_conversion_assumption",
    "maximum_coverage_poc_assumption",
}
POC_CONVERSION_COLUMNS = (
    "mapping_id",
    "native_to_poc_multiplier",
    "poc_activity_unit",
    "poc_fuel",
    "assumption_type",
    "assumption_detail",
    "analytical_use_permitted",
)


class NativeActivityError(ValueError):
    """Raised when the native GCAM interface violates its mapping contract."""


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _require_columns(data: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns) - set(data.columns))
    if missing:
        raise NativeActivityError(f"{label} is missing required columns: {missing}")


def load_native_crosswalk(path: Path) -> pd.DataFrame:
    crosswalk = pd.read_csv(path, dtype=str, keep_default_na=False)
    _require_columns(crosswalk, CROSSWALK_COLUMNS, "native GCAM activity crosswalk")
    if crosswalk["mapping_id"].duplicated().any():
        duplicate = sorted(crosswalk.loc[crosswalk["mapping_id"].duplicated(), "mapping_id"])
        raise NativeActivityError(f"Duplicate native mapping IDs: {duplicate}")
    for row in crosswalk.itertuples(index=False):
        for field in (
            "sector_pattern",
            "subsector_pattern",
            "technology_pattern",
            "node_pattern",
        ):
            pattern = getattr(row, field)
            if pattern:
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise NativeActivityError(
                        f"Mapping {row.mapping_id} has invalid {field}: {error}"
                    ) from error
    return crosswalk


def apply_poc_activity_assumptions(
    crosswalk: pd.DataFrame,
    assumptions: pd.DataFrame,
) -> pd.DataFrame:
    """Enable otherwise blocked GCAM selectors using explicit POC conversions."""
    _require_columns(crosswalk, CROSSWALK_COLUMNS, "native GCAM activity crosswalk")
    _require_columns(assumptions, POC_CONVERSION_COLUMNS, "POC activity assumptions")
    if assumptions["mapping_id"].duplicated().any():
        duplicate = sorted(
            assumptions.loc[assumptions["mapping_id"].duplicated(), "mapping_id"].astype(str)
        )
        raise NativeActivityError(f"Duplicate POC conversion mapping IDs: {duplicate}")
    unknown = sorted(set(assumptions["mapping_id"]) - set(crosswalk["mapping_id"]))
    if unknown:
        raise NativeActivityError(
            f"POC conversion assumptions reference unknown mapping IDs: {unknown}"
        )
    converted = crosswalk.copy()
    assumption_lookup = assumptions.set_index("mapping_id")
    for index, row in converted.iterrows():
        mapping_id = str(row["mapping_id"])
        if mapping_id not in assumption_lookup.index:
            continue
        assumption = assumption_lookup.loc[mapping_id]
        multiplier = pd.to_numeric(
            pd.Series([assumption["native_to_poc_multiplier"]]), errors="coerce"
        ).iloc[0]
        if pd.isna(multiplier) or float(multiplier) <= 0:
            raise NativeActivityError(
                f"POC conversion {mapping_id} requires a positive numeric multiplier."
            )
        if _truthy(assumption["analytical_use_permitted"]):
            raise NativeActivityError(f"POC conversion {mapping_id} may not claim analytical use.")
        converted.at[index, "native_to_canonical_multiplier"] = str(float(multiplier))
        converted.at[index, "canonical_activity_unit"] = str(assumption["poc_activity_unit"])
        converted.at[index, "canonical_fuel"] = str(assumption["poc_fuel"])
        converted.at[index, "match_status"] = "maximum_coverage_poc_assumption"
        converted.at[index, "include_in_emissions_model"] = "true"
        converted.at[index, "note"] = (
            f"POC {assumption['assumption_type']}: {assumption['assumption_detail']}"
        )
    return converted


def _row_mask(activity: pd.DataFrame, mapping: object) -> pd.Series:
    mask = pd.Series(True, index=activity.index)
    for crosswalk_field, activity_field in ACTIVITY_MATCH_COLUMNS:
        value = str(getattr(mapping, crosswalk_field))
        if not value:
            continue
        if crosswalk_field.endswith("_pattern"):
            mask &= activity[activity_field].astype(str).str.fullmatch(value, na=False)
        else:
            mask &= activity[activity_field].astype(str).eq(value)
    return mask


def map_native_activity(
    activity: pd.DataFrame,
    crosswalk: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Apply reviewed native selectors and return canonical activity plus audits."""
    required_activity = {
        "scenario",
        "source_scenario",
        "region",
        "year",
        "record_type",
        "sector_type",
        "sector",
        "subsector_type",
        "subsector",
        "technology_type",
        "technology",
        "node_type",
        "node",
        "activity",
        "activity_unit",
    }
    _require_columns(activity, required_activity, "extracted GCAM activity")
    activity = activity.reset_index(drop=True).copy()
    activity["_native_row_id"] = np.arange(len(activity), dtype=int)
    candidates: list[pd.DataFrame] = []
    audit_rows: list[dict[str, object]] = []
    matched_native_ids: set[int] = set()
    for mapping in crosswalk.itertuples(index=False):
        mask = _row_mask(activity, mapping)
        selected = activity.loc[mask].copy()
        matched_native_ids.update(selected["_native_row_id"].astype(int))
        multiplier = pd.to_numeric(
            pd.Series([mapping.native_to_canonical_multiplier]), errors="coerce"
        ).iloc[0]
        include = _truthy(mapping.include_in_emissions_model)
        audit_rows.append(
            {
                "mapping_id": mapping.mapping_id,
                "inventory_id": mapping.inventory_id,
                "match_status": mapping.match_status,
                "matched_native_rows": int(len(selected)),
                "matched_years": "|".join(
                    str(year) for year in sorted(selected["year"].astype(int).unique())
                ),
                "native_activity_sum": float(
                    pd.to_numeric(selected["activity"], errors="coerce").sum()
                ),
                "native_unit": mapping.native_unit,
                "conversion_multiplier": (float(multiplier) if pd.notna(multiplier) else pd.NA),
                "canonical_activity_unit": mapping.canonical_activity_unit,
                "include_in_emissions_model": include,
                "conversion_ready": bool(pd.notna(multiplier) and include),
                "activity_mapping_production_ready": bool(
                    include
                    and pd.notna(multiplier)
                    and mapping.match_status not in NONPRODUCTION_MAPPING_STATUSES
                ),
                "note": mapping.note,
            }
        )
        if selected.empty:
            continue
        selected["mapping_id"] = mapping.mapping_id
        selected["inventory_id"] = mapping.inventory_id
        selected["canonical_fuel"] = mapping.canonical_fuel
        selected["mapping_status"] = mapping.match_status
        selected["activity_mapping_production_ready"] = (
            mapping.match_status not in NONPRODUCTION_MAPPING_STATUSES
        )
        selected["canonical_activity_unit"] = mapping.canonical_activity_unit
        selected["conversion_multiplier"] = multiplier
        selected["include_in_emissions_model"] = include
        selected["canonical_activity"] = (
            pd.to_numeric(selected["activity"], errors="coerce") * multiplier
            if pd.notna(multiplier)
            else np.nan
        )
        candidates.append(selected)

    candidate_frame = pd.concat(candidates, ignore_index=True) if candidates else pd.DataFrame()
    converted = candidate_frame.loc[
        candidate_frame.get("include_in_emissions_model", False)
        & candidate_frame.get("canonical_activity", pd.Series(dtype=float)).notna()
    ].copy()
    if converted.empty:
        canonical = pd.DataFrame(
            columns=[
                "scenario",
                "source_scenario",
                "region",
                "year",
                "inventory_id",
                "canonical_fuel",
                "activity",
                "activity_unit",
                "mapping_status",
                "activity_mapping_production_ready",
                "mapping_ids",
                "source_record_count",
            ]
        )
    else:
        canonical = (
            converted.groupby(
                [
                    "scenario",
                    "source_scenario",
                    "region",
                    "year",
                    "inventory_id",
                    "canonical_fuel",
                    "canonical_activity_unit",
                    "mapping_status",
                    "activity_mapping_production_ready",
                ],
                dropna=False,
                as_index=False,
            )
            .agg(
                activity=("canonical_activity", "sum"),
                mapping_ids=("mapping_id", lambda values: "|".join(sorted(set(values)))),
                source_record_count=("_native_row_id", "nunique"),
            )
            .rename(columns={"canonical_activity_unit": "activity_unit"})
        )
        canonical = canonical.sort_values(
            ["scenario", "year", "inventory_id", "canonical_fuel", "mapping_status"],
            kind="stable",
        ).reset_index(drop=True)
    mapping_audit = pd.DataFrame(audit_rows).sort_values("mapping_id").reset_index(drop=True)
    unmapped = activity.loc[~activity["_native_row_id"].isin(matched_native_ids)].copy()
    if unmapped.empty:
        unmapped_summary = pd.DataFrame()
    else:
        unmapped_summary = (
            unmapped.groupby(
                [
                    "record_type",
                    "sector_type",
                    "sector",
                    "subsector_type",
                    "subsector",
                    "technology_type",
                    "technology",
                    "node_type",
                    "node",
                    "activity_unit",
                ],
                dropna=False,
                as_index=False,
            )
            .agg(
                native_row_count=("_native_row_id", "size"),
                first_year=("year", "min"),
                last_year=("year", "max"),
            )
            .sort_values(["sector_type", "sector", "subsector", "technology", "record_type"])
            .reset_index(drop=True)
        )
    return canonical, mapping_audit, unmapped_summary


def _factor_activity_multiplier(factor_unit: str, activity_unit: str) -> float | None:
    """Return canonical activity units per factor denominator unit."""
    direct = {
        ("kg/ton-crude-steel", "tonne crude steel"),
        ("kg/ton-crude-steel", "tonne EAF steel"),
        ("kg/ton-clinker", "tonne clinker"),
        ("kg/ton-sinter", "tonne sinter"),
        ("kg/ton-product", "tonne product"),
        ("kg/ton-product", "tonne cement"),
        ("kg/ton-waste", "tonne waste treated"),
        ("kg/animal-year", "animal-year"),
        ("g/vehicle-km", "vehicle-km"),
        ("kg/kg-fuel", "kg fuel"),
    }
    if (factor_unit, activity_unit) in direct:
        return 1.0
    if factor_unit == "kg/ton-N" and activity_unit == "kg nitrogen applied":
        return 1.0 / 1000.0
    if factor_unit == "kg/1000m3-fuel" and activity_unit == "cubic metre fuel":
        return 1.0 / 1000.0
    if factor_unit == "kg/kL-fuel" and activity_unit == "litre fuel":
        return 1.0 / 1000.0
    return None


def _factor_mass_multiplier(factor_unit: str) -> float:
    return 0.001 if factor_unit.startswith("g/") else 1.0


def _merge_factor_links(factors: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    merged = links.merge(factors, on="record_id", suffixes=("_link", "_factor"))
    if {"pollutant_link", "pollutant_factor"}.issubset(merged.columns):
        mismatch = merged["pollutant_link"].ne(merged["pollutant_factor"])
        if mismatch.any():
            records = sorted(merged.loc[mismatch, "record_id"].astype(str).unique())
            raise NativeActivityError(f"Factor-link pollutant disagreement for records: {records}")
        merged["pollutant"] = merged["pollutant_factor"]
    return merged


def build_approved_factor_projection(
    activity: pd.DataFrame,
    inventory: pd.DataFrame,
    factors: pd.DataFrame,
    links: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join only approved numeric factors with denominator-compatible activity."""
    _require_columns(
        activity,
        {
            "inventory_id",
            "activity",
            "activity_unit",
            "activity_mapping_production_ready",
        },
        "canonical GCAM activity",
    )
    _require_columns(
        factors,
        {"record_id", "production_ready", "pollutant", "ef_value", "unit"},
        "factor catalog",
    )
    _require_columns(
        links,
        {"record_id", "inventory_id", "production_ready", "match_status"},
        "factor links",
    )
    ready_factors = factors.loc[factors["production_ready"].map(_truthy)].copy()
    ready_links = links.loc[links["production_ready"].map(_truthy)].copy()
    approved = _merge_factor_links(ready_factors, ready_links)
    joined = activity.merge(approved, on="inventory_id", how="left", indicator=True)
    if joined.empty:
        return pd.DataFrame(), pd.DataFrame()

    joined["ef_numeric"] = pd.to_numeric(joined.get("ef_value"), errors="coerce")
    joined["activity_to_factor_denominator"] = [
        _factor_activity_multiplier(str(unit), str(activity_unit)) if pd.notna(unit) else None
        for unit, activity_unit in zip(joined.get("unit"), joined["activity_unit"], strict=True)
    ]
    joined["factor_compatible"] = (
        joined["_merge"].eq("both")
        & joined["ef_numeric"].notna()
        & joined["activity_to_factor_denominator"].notna()
        & joined["activity_mapping_production_ready"].map(_truthy)
    )
    successful = joined.loc[joined["factor_compatible"]].copy()
    if successful.empty:
        projection = pd.DataFrame()
    else:
        successful["emission_factor_kg_per_activity"] = [
            float(ef) * _factor_mass_multiplier(str(unit)) * float(activity_multiplier)
            for ef, unit, activity_multiplier in zip(
                successful["ef_numeric"],
                successful["unit"],
                successful["activity_to_factor_denominator"],
                strict=True,
            )
        ]
        successful["projected_emissions_kg"] = (
            successful["activity"] * successful["emission_factor_kg_per_activity"]
        )
        inventory_fields = inventory[
            ["inventory_id", "gcam_cluster", "gcam_sector", "gcam_technology"]
        ].drop_duplicates("inventory_id")
        successful = successful.merge(inventory_fields, on="inventory_id", how="left")
        projection = successful.assign(
            sector=successful["inventory_id"],
            fuel=successful["canonical_fuel"],
            technology=successful["gcam_technology"],
            emission_factor_unit="kg per canonical activity unit",
            factor_record_id=successful["record_id"],
            factor_production_ready=True,
            factor_method="approved_korean_nonpower_factor",
        )[
            [
                "scenario",
                "source_scenario",
                "region",
                "year",
                "inventory_id",
                "sector",
                "fuel",
                "technology",
                "pollutant",
                "activity",
                "activity_unit",
                "emission_factor_kg_per_activity",
                "emission_factor_unit",
                "projected_emissions_kg",
                "factor_record_id",
                "factor_production_ready",
                "factor_method",
            ]
        ].sort_values(["scenario", "year", "inventory_id", "pollutant"])

    gap_columns = [
        "scenario",
        "year",
        "inventory_id",
        "canonical_fuel",
        "activity_unit",
        "_merge",
        "record_id",
        "unit",
        "ef_value",
        "factor_compatible",
        "activity_mapping_production_ready",
    ]
    gaps = joined.loc[~joined["factor_compatible"], gap_columns].copy()
    gaps["gap_reason"] = np.select(
        [
            ~gaps["activity_mapping_production_ready"].map(_truthy),
            gaps["_merge"].ne("both"),
            pd.to_numeric(gaps["ef_value"], errors="coerce").isna(),
            gaps["unit"].notna(),
        ],
        [
            "activity_mapping_requires_conversion_review",
            "no_production_ready_factor_link",
            "approved_factor_is_not_numeric",
            "activity_and_factor_denominators_are_incompatible",
        ],
        default="unknown_factor_gap",
    )
    return projection.reset_index(drop=True), gaps.drop(columns="_merge").reset_index(drop=True)


def build_candidate_factor_screening_projection(
    activity: pd.DataFrame,
    inventory: pd.DataFrame,
    factors: pd.DataFrame,
    links: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply median compatible candidate EFs for a non-analytical POC."""
    _require_columns(
        activity,
        {
            "scenario",
            "source_scenario",
            "region",
            "year",
            "inventory_id",
            "canonical_fuel",
            "activity",
            "activity_unit",
            "activity_mapping_production_ready",
        },
        "canonical GCAM activity",
    )
    _require_columns(
        factors,
        {"record_id", "pollutant", "ef_value", "unit"},
        "factor catalog",
    )
    _require_columns(
        links,
        {"record_id", "inventory_id", "match_status"},
        "factor links",
    )
    candidate_factors = factors.loc[
        pd.to_numeric(factors["ef_value"], errors="coerce").notna()
        & factors["pollutant"].isin(INMAP_POLLUTANTS)
    ].copy()
    linked = _merge_factor_links(candidate_factors, links)
    joined = activity.merge(linked, on="inventory_id", how="left", indicator=True)
    joined["ef_numeric"] = pd.to_numeric(joined.get("ef_value"), errors="coerce")
    joined["activity_to_factor_denominator"] = [
        _factor_activity_multiplier(str(unit), str(activity_unit)) if pd.notna(unit) else None
        for unit, activity_unit in zip(joined.get("unit"), joined["activity_unit"], strict=True)
    ]
    joined["candidate_compatible"] = (
        joined["_merge"].eq("both")
        & joined["ef_numeric"].notna()
        & joined["activity_to_factor_denominator"].notna()
        & joined["activity_mapping_production_ready"].map(_truthy)
    )
    compatible = joined.loc[joined["candidate_compatible"]].copy()
    if compatible.empty:
        projection = pd.DataFrame()
    else:
        compatible["candidate_ef_kg_per_activity"] = [
            float(ef) * _factor_mass_multiplier(str(unit)) * float(activity_multiplier)
            for ef, unit, activity_multiplier in zip(
                compatible["ef_numeric"],
                compatible["unit"],
                compatible["activity_to_factor_denominator"],
                strict=True,
            )
        ]
        group_fields = [
            "scenario",
            "source_scenario",
            "region",
            "year",
            "inventory_id",
            "canonical_fuel",
            "activity",
            "activity_unit",
            "pollutant",
        ]
        projection = (
            compatible.groupby(group_fields, dropna=False, as_index=False)
            .agg(
                emission_factor_kg_per_activity=(
                    "candidate_ef_kg_per_activity",
                    "median",
                ),
                candidate_factor_count=("record_id", "nunique"),
                candidate_factor_record_ids=(
                    "record_id",
                    lambda values: "|".join(sorted(set(map(str, values)))),
                ),
                candidate_factor_match_statuses=(
                    "match_status",
                    lambda values: "|".join(sorted(set(map(str, values)))),
                ),
            )
            .assign(
                sector=lambda frame: frame["inventory_id"],
                fuel=lambda frame: frame["canonical_fuel"],
                technology=lambda frame: frame["inventory_id"],
                emission_factor_unit="kg per canonical activity unit",
                factor_record_id=lambda frame: frame["candidate_factor_record_ids"],
                factor_production_ready=False,
                factor_method="median_unvalidated_candidate_factor_poc",
                analytical_use_permitted=False,
            )
        )
        projection["projected_emissions_kg"] = (
            projection["activity"] * projection["emission_factor_kg_per_activity"]
        )
        inventory_fields = inventory[["inventory_id", "gcam_technology"]].drop_duplicates(
            "inventory_id"
        )
        projection = projection.merge(inventory_fields, on="inventory_id", how="left")
        projection["technology"] = projection["gcam_technology"].where(
            projection["gcam_technology"].astype(str).str.strip().ne(""),
            projection["technology"],
        )
        projection = projection[
            [
                "scenario",
                "source_scenario",
                "region",
                "year",
                "inventory_id",
                "sector",
                "fuel",
                "technology",
                "pollutant",
                "activity",
                "activity_unit",
                "emission_factor_kg_per_activity",
                "emission_factor_unit",
                "projected_emissions_kg",
                "factor_record_id",
                "candidate_factor_count",
                "candidate_factor_match_statuses",
                "factor_production_ready",
                "factor_method",
                "analytical_use_permitted",
            ]
        ].sort_values(["scenario", "year", "inventory_id", "fuel", "pollutant"])

    gap_fields = [
        "scenario",
        "year",
        "inventory_id",
        "canonical_fuel",
        "activity_unit",
        "activity_mapping_production_ready",
    ]
    successful_keys = (
        compatible[gap_fields].drop_duplicates()
        if not compatible.empty
        else pd.DataFrame(columns=gap_fields)
    )
    gaps = activity.merge(
        successful_keys.assign(_has_candidate=True),
        on=gap_fields,
        how="left",
    )
    gaps = gaps.loc[gaps["_has_candidate"].isna()].copy()
    gaps["gap_reason"] = np.where(
        gaps["activity_mapping_production_ready"].map(_truthy),
        "no_denominator_compatible_numeric_candidate_factor",
        "activity_mapping_requires_conversion_review",
    )
    return projection.reset_index(drop=True), gaps.drop(columns="_has_candidate").reset_index(
        drop=True
    )


def build_maximum_coverage_projection(
    activity: pd.DataFrame,
    inventory: pd.DataFrame,
    factors: pd.DataFrame,
    links: pd.DataFrame,
    capss_admin_weights: pd.DataFrame,
    *,
    capss_base_year: int = 2021,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign every mapped activity an explicitly ranked, non-analytical POC EF."""
    _require_columns(
        activity,
        {
            "scenario",
            "source_scenario",
            "region",
            "year",
            "inventory_id",
            "activity",
            "activity_unit",
            "mapping_ids",
        },
        "maximum-coverage canonical GCAM activity",
    )
    _require_columns(
        factors,
        {"record_id", "pollutant", "ef_value", "unit"},
        "factor catalog",
    )
    _require_columns(
        links,
        {"record_id", "inventory_id", "match_status"},
        "factor links",
    )
    _require_columns(
        capss_admin_weights,
        {"inventory_id", "pollutant", "base_emissions_kg"},
        "CAPSS administrative weights",
    )
    group_fields = [
        "scenario",
        "source_scenario",
        "region",
        "year",
        "inventory_id",
        "activity_unit",
    ]
    aggregated = (
        activity.groupby(group_fields, dropna=False, as_index=False)
        .agg(
            activity=("activity", "sum"),
            mapping_ids=(
                "mapping_ids",
                lambda values: "|".join(
                    sorted(
                        {item for value in values.astype(str) for item in value.split("|") if item}
                    )
                ),
            ),
        )
        .sort_values(["scenario", "year", "inventory_id", "activity_unit"])
        .reset_index(drop=True)
    )
    unit_counts = aggregated.groupby("inventory_id")["activity_unit"].nunique()
    mixed_units = sorted(unit_counts.loc[unit_counts.gt(1)].index.astype(str))
    if mixed_units:
        raise NativeActivityError(
            "Maximum-coverage projection cannot aggregate inventory IDs with mixed "
            f"activity units: {mixed_units}"
        )

    numeric_factors = factors.loc[factors["pollutant"].isin(INMAP_POLLUTANTS)].copy()
    numeric_factors["ef_numeric"] = pd.to_numeric(numeric_factors["ef_value"], errors="coerce")
    numeric_factors = numeric_factors.loc[
        numeric_factors["ef_numeric"].notna() & numeric_factors["ef_numeric"].ge(0)
    ]
    linked = _merge_factor_links(numeric_factors, links)

    direct_ef: dict[tuple[str, str, str], dict[str, object]] = {}
    for inventory_id, activity_unit in (
        aggregated[["inventory_id", "activity_unit"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    ):
        selected = linked.loc[linked["inventory_id"].astype(str).eq(str(inventory_id))].copy()
        if selected.empty:
            continue
        selected["denominator_multiplier"] = selected["unit"].map(
            lambda unit: _factor_activity_multiplier(str(unit), str(activity_unit))
        )
        selected = selected.loc[selected["denominator_multiplier"].notna()].copy()
        if selected.empty:
            continue
        selected["ef_kg_per_activity"] = [
            float(ef) * _factor_mass_multiplier(str(unit)) * float(denominator_multiplier)
            for ef, unit, denominator_multiplier in zip(
                selected["ef_numeric"],
                selected["unit"],
                selected["denominator_multiplier"],
                strict=True,
            )
        ]
        for pollutant, rows in selected.groupby("pollutant", sort=True):
            direct_ef[(str(inventory_id), str(activity_unit), str(pollutant))] = {
                "ef": float(rows["ef_kg_per_activity"].median()),
                "record_ids": "|".join(sorted(rows["record_id"].astype(str).unique())),
                "count": int(rows["record_id"].nunique()),
                "match_statuses": "|".join(sorted(rows["match_status"].astype(str).unique())),
                "factor_units": "|".join(sorted(rows["unit"].astype(str).unique())),
            }

    linked_ef: dict[tuple[str, str], dict[str, object]] = {}
    for (inventory_id, pollutant), rows in linked.groupby(
        ["inventory_id", "pollutant"], sort=True
    ):
        values = [
            float(ef) * _factor_mass_multiplier(str(unit))
            for ef, unit in zip(rows["ef_numeric"], rows["unit"], strict=True)
        ]
        linked_ef[(str(inventory_id), str(pollutant))] = {
            "ef": float(np.median(values)),
            "record_ids": "|".join(sorted(rows["record_id"].astype(str).unique())),
            "count": int(rows["record_id"].nunique()),
            "match_statuses": "|".join(sorted(rows["match_status"].astype(str).unique())),
            "factor_units": "|".join(sorted(rows["unit"].astype(str).unique())),
        }

    global_ef: dict[str, dict[str, object]] = {}
    for pollutant, rows in numeric_factors.groupby("pollutant", sort=True):
        values = [
            float(ef) * _factor_mass_multiplier(str(unit))
            for ef, unit in zip(rows["ef_numeric"], rows["unit"], strict=True)
        ]
        global_ef[str(pollutant)] = {
            "ef": float(np.median(values)),
            "record_ids": f"GLOBAL_CATALOG_MEDIAN::{pollutant}",
            "count": int(rows["record_id"].nunique()),
            "match_statuses": "unlinked_global_pollutant_fallback",
            "factor_units": "|".join(sorted(rows["unit"].astype(str).unique())),
        }

    capss_totals = (
        capss_admin_weights.groupby(["inventory_id", "pollutant"], as_index=False)[
            "base_emissions_kg"
        ]
        .sum()
        .set_index(["inventory_id", "pollutant"])["base_emissions_kg"]
        .to_dict()
    )
    reference_activity: dict[tuple[str, str, str], tuple[int, float]] = {}
    for (scenario, inventory_id, activity_unit), rows in aggregated.groupby(
        ["scenario", "inventory_id", "activity_unit"], sort=True
    ):
        positive = rows.loc[pd.to_numeric(rows["activity"], errors="coerce").gt(0)].copy()
        if positive.empty:
            continue
        positive["_year_distance"] = (positive["year"].astype(int) - int(capss_base_year)).abs()
        reference = positive.sort_values(["_year_distance", "year"], kind="stable").iloc[0]
        reference_activity[(str(scenario), str(inventory_id), str(activity_unit))] = (
            int(reference["year"]),
            float(reference["activity"]),
        )

    inventory_fields = (
        inventory[["inventory_id", "gcam_technology"]]
        .drop_duplicates("inventory_id")
        .set_index("inventory_id")["gcam_technology"]
        .to_dict()
    )
    output_rows: list[dict[str, object]] = []
    for row in aggregated.itertuples(index=False):
        inventory_id = str(row.inventory_id)
        activity_unit = str(row.activity_unit)
        reference = reference_activity.get((str(row.scenario), inventory_id, activity_unit))
        for pollutant in sorted(INMAP_POLLUTANTS):
            direct = direct_ef.get((inventory_id, activity_unit, pollutant))
            capss_mass = float(capss_totals.get((inventory_id, pollutant), 0.0))
            linked_fallback = linked_ef.get((inventory_id, pollutant))
            global_fallback = global_ef.get(pollutant)
            if direct is not None:
                selected_factor = direct
                factor_method = "median_denominator_compatible_linked_factor_poc"
                rank = 1
                reference_year: int | object = pd.NA
                reference_mass: float | object = pd.NA
            elif capss_mass > 0 and reference is not None and reference[1] > 0:
                selected_factor = {
                    "ef": capss_mass / reference[1],
                    "record_ids": (
                        f"CAPSS_{capss_base_year}_IMPLICIT::{inventory_id}::{pollutant}"
                    ),
                    "count": 1,
                    "match_statuses": "capss_inventory_crosswalk_calibration",
                    "factor_units": f"kg/{activity_unit}",
                }
                factor_method = "capss_base_emissions_per_gcam_activity_poc"
                rank = 2
                reference_year = reference[0]
                reference_mass = capss_mass
            elif linked_fallback is not None:
                selected_factor = linked_fallback
                factor_method = "median_linked_factor_ignoring_denominator_poc"
                rank = 3
                reference_year = pd.NA
                reference_mass = pd.NA
            elif global_fallback is not None:
                selected_factor = global_fallback
                factor_method = "global_pollutant_median_ignoring_sector_and_denominator_poc"
                rank = 4
                reference_year = pd.NA
                reference_mass = pd.NA
            else:
                raise NativeActivityError(
                    f"No numeric {pollutant} factor exists for maximum-coverage fallback."
                )
            emission_factor = float(selected_factor["ef"])
            output_rows.append(
                {
                    "scenario": row.scenario,
                    "source_scenario": row.source_scenario,
                    "region": row.region,
                    "year": int(row.year),
                    "inventory_id": inventory_id,
                    "sector": inventory_id,
                    "fuel": "aggregate",
                    "technology": inventory_fields.get(inventory_id, inventory_id),
                    "pollutant": pollutant,
                    "activity": float(row.activity),
                    "activity_unit": activity_unit,
                    "emission_factor_kg_per_activity": emission_factor,
                    "emission_factor_unit": "kg per canonical activity unit",
                    "projected_emissions_kg": float(row.activity) * emission_factor,
                    "factor_record_id": selected_factor["record_ids"],
                    "candidate_factor_count": int(selected_factor["count"]),
                    "candidate_factor_match_statuses": selected_factor["match_statuses"],
                    "source_factor_units": selected_factor["factor_units"],
                    "factor_selection_rank": rank,
                    "factor_production_ready": False,
                    "factor_method": factor_method,
                    "capss_reference_year": reference_year,
                    "capss_reference_emissions_kg": reference_mass,
                    "mapping_ids": row.mapping_ids,
                    "analytical_use_permitted": False,
                }
            )
    projection = pd.DataFrame(output_rows).sort_values(
        ["scenario", "year", "inventory_id", "pollutant"]
    )
    expected = (
        aggregated[["scenario", "year", "inventory_id"]]
        .drop_duplicates()
        .assign(_key=1)
        .merge(pd.DataFrame({"pollutant": sorted(INMAP_POLLUTANTS), "_key": 1}), on="_key")
        .drop(columns="_key")
    )
    observed = projection[["scenario", "year", "inventory_id", "pollutant"]].drop_duplicates()
    missing = expected.merge(
        observed.assign(_covered=True),
        on=["scenario", "year", "inventory_id", "pollutant"],
        how="left",
    )
    missing = missing.loc[missing["_covered"].isna()].drop(columns="_covered")
    if not missing.empty:
        raise NativeActivityError(
            "Maximum-coverage projection left activity/pollutant combinations uncovered."
        )
    audit = (
        projection.groupby(
            [
                "inventory_id",
                "pollutant",
                "factor_selection_rank",
                "factor_method",
                "activity_unit",
                "factor_record_id",
                "candidate_factor_match_statuses",
                "source_factor_units",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            first_year=("year", "min"),
            last_year=("year", "max"),
            projected_row_count=("year", "size"),
            emission_factor_kg_per_activity=(
                "emission_factor_kg_per_activity",
                "first",
            ),
        )
        .sort_values(["inventory_id", "pollutant"])
        .reset_index(drop=True)
    )
    audit["analytical_use_permitted"] = False
    return projection.reset_index(drop=True), audit


def summarize_native_emissions(emissions: pd.DataFrame) -> pd.DataFrame:
    """Summarize model-native emissions strictly as a validation lane."""
    _require_columns(
        emissions,
        {"scenario", "year", "pollutant", "emissions_kg", "native_emissions_unit"},
        "native GCAM emissions",
    )
    selected = emissions.loc[
        emissions["pollutant"].isin(INMAP_POLLUTANTS)
        & pd.to_numeric(emissions["emissions_kg"], errors="coerce").notna()
    ].copy()
    summary = (
        selected.groupby(["scenario", "year", "pollutant"], as_index=False)["emissions_kg"]
        .sum()
        .sort_values(["scenario", "year", "pollutant"])
    )
    summary["use_status"] = "validation_only_native_gcam_emissions_not_korean_ef"
    summary["spatial_scope"] = "national_south_korea"
    summary["analytical_use_permitted"] = False
    return summary


def build_native_nonpower_interface(
    *,
    activity_path: Path,
    native_emissions_path: Path,
    output_dir: Path,
    crosswalk_path: Path = NONPOWER_REFERENCE_DIR / CROSSWALK_FILE,
    inventory_path: Path = NONPOWER_REFERENCE_DIR / INVENTORY_FILE,
    factor_catalog_path: Path = NONPOWER_PROCESSED_DIR / "nonpower_emission_factors.parquet",
    factor_links_path: Path = (
        NONPOWER_PROCESSED_DIR / "nonpower_emission_factor_inventory_links.parquet"
    ),
    poc_conversion_path: Path = NONPOWER_REFERENCE_DIR / POC_CONVERSION_FILE,
    capss_admin_weights_path: Path = (
        GCAM_NZK_APHIAM_DIR / "capss_2021_admin_surrogate_weights.parquet"
    ),
) -> dict[str, object]:
    """Build mapped activity, approved-factor projections, and explicit gap tables."""
    activity = pd.read_parquet(activity_path)
    native_emissions = pd.read_parquet(native_emissions_path)
    crosswalk = load_native_crosswalk(crosswalk_path)
    inventory = pd.read_csv(inventory_path, dtype=str, keep_default_na=False)
    factors = pd.read_parquet(factor_catalog_path)
    links = pd.read_parquet(factor_links_path)
    assumptions = pd.read_csv(poc_conversion_path, dtype=str, keep_default_na=False)
    capss_admin_weights = pd.read_parquet(capss_admin_weights_path)
    canonical, mapping_audit, unmapped = map_native_activity(activity, crosswalk)
    projection, factor_gaps = build_approved_factor_projection(
        canonical, inventory, factors, links
    )
    candidate_projection, candidate_factor_gaps = build_candidate_factor_screening_projection(
        canonical, inventory, factors, links
    )
    maximum_coverage_crosswalk = apply_poc_activity_assumptions(crosswalk, assumptions)
    maximum_coverage_activity, maximum_coverage_mapping_audit, _ = map_native_activity(
        activity, maximum_coverage_crosswalk
    )
    maximum_coverage_projection, maximum_coverage_factor_audit = build_maximum_coverage_projection(
        maximum_coverage_activity,
        inventory,
        factors,
        links,
        capss_admin_weights,
    )
    native_summary = summarize_native_emissions(native_emissions)

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "canonical_activity": output_dir / "gcam_kaist_nzk_canonical_nonpower_activity.parquet",
        "canonical_activity_csv": output_dir / "gcam_kaist_nzk_canonical_nonpower_activity.csv",
        "mapping_audit": output_dir / "gcam_kaist_nzk_activity_mapping_audit.csv",
        "unmapped_activity": output_dir / "gcam_kaist_nzk_unmapped_activity_summary.csv",
        "approved_projection": output_dir / "approved_projected_emissions.csv",
        "factor_gaps": output_dir / "approved_factor_gaps.csv",
        "candidate_projection": output_dir / "candidate_screening_projected_emissions.csv",
        "candidate_factor_gaps": output_dir / "candidate_factor_screening_gaps.csv",
        "maximum_coverage_activity": output_dir
        / "gcam_kaist_nzk_maximum_coverage_nonpower_activity.csv",
        "maximum_coverage_mapping_audit": output_dir
        / "gcam_kaist_nzk_maximum_coverage_activity_mapping_audit.csv",
        "maximum_coverage_projection": output_dir / "maximum_coverage_poc_projected_emissions.csv",
        "maximum_coverage_factor_audit": output_dir / "maximum_coverage_poc_factor_audit.csv",
        "native_emissions_summary": output_dir
        / "gcam_kaist_nzk_native_emissions_validation_summary.csv",
        "metadata": output_dir / "gcam_kaist_nzk_nonpower_interface.metadata.json",
    }
    canonical.to_parquet(outputs["canonical_activity"], index=False)
    canonical.to_csv(outputs["canonical_activity_csv"], index=False)
    mapping_audit.to_csv(outputs["mapping_audit"], index=False)
    unmapped.to_csv(outputs["unmapped_activity"], index=False)
    if projection.empty:
        projection = pd.DataFrame(
            columns=[
                "scenario",
                "source_scenario",
                "region",
                "year",
                "inventory_id",
                "sector",
                "fuel",
                "technology",
                "pollutant",
                "activity",
                "activity_unit",
                "emission_factor_kg_per_activity",
                "emission_factor_unit",
                "projected_emissions_kg",
                "factor_record_id",
                "factor_production_ready",
                "factor_method",
            ]
        )
    if candidate_projection.empty:
        candidate_projection = pd.DataFrame(
            columns=[
                "scenario",
                "source_scenario",
                "region",
                "year",
                "inventory_id",
                "sector",
                "fuel",
                "technology",
                "pollutant",
                "activity",
                "activity_unit",
                "emission_factor_kg_per_activity",
                "emission_factor_unit",
                "projected_emissions_kg",
                "factor_record_id",
                "candidate_factor_count",
                "candidate_factor_match_statuses",
                "factor_production_ready",
                "factor_method",
                "analytical_use_permitted",
            ]
        )
    projection.to_csv(outputs["approved_projection"], index=False)
    factor_gaps.to_csv(outputs["factor_gaps"], index=False)
    candidate_projection.to_csv(outputs["candidate_projection"], index=False)
    candidate_factor_gaps.to_csv(outputs["candidate_factor_gaps"], index=False)
    maximum_coverage_activity.to_csv(outputs["maximum_coverage_activity"], index=False)
    maximum_coverage_mapping_audit.to_csv(outputs["maximum_coverage_mapping_audit"], index=False)
    maximum_coverage_projection.to_csv(outputs["maximum_coverage_projection"], index=False)
    maximum_coverage_factor_audit.to_csv(outputs["maximum_coverage_factor_audit"], index=False)
    native_summary.to_csv(outputs["native_emissions_summary"], index=False)

    p1_ids = set(inventory.loc[inventory["priority"].eq("P1"), "inventory_id"])
    mapped_p1 = set(canonical["inventory_id"]) & p1_ids
    ready_mapped_p1 = (
        set(
            canonical.loc[
                canonical["activity_mapping_production_ready"].map(_truthy),
                "inventory_id",
            ]
        )
        & p1_ids
    )
    metadata: dict[str, object] = {
        "dataset": "GCAM-KAIST NZK native non-power interface",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_activity_rows": int(len(canonical)),
        "canonical_inventory_ids": sorted(canonical["inventory_id"].unique()),
        "mapped_priority_inventory_ids": sorted(mapped_p1),
        "mapped_priority_inventory_count": len(mapped_p1),
        "production_ready_activity_mapping_ids": sorted(ready_mapped_p1),
        "production_ready_activity_mapping_count": len(ready_mapped_p1),
        "priority_inventory_count": len(p1_ids),
        "mapping_rows_with_native_matches": int(mapping_audit["matched_native_rows"].gt(0).sum()),
        "mapping_rows_without_native_matches": int(
            mapping_audit["matched_native_rows"].eq(0).sum()
        ),
        "approved_projected_emissions_rows": int(len(projection)),
        "factor_gap_rows": int(len(factor_gaps)),
        "candidate_screening_projected_emissions_rows": int(len(candidate_projection)),
        "candidate_screening_inventory_ids": sorted(candidate_projection["inventory_id"].unique()),
        "candidate_screening_factor_gap_rows": int(len(candidate_factor_gaps)),
        "maximum_coverage_activity_rows": int(len(maximum_coverage_activity)),
        "maximum_coverage_inventory_ids": sorted(
            maximum_coverage_activity["inventory_id"].unique()
        ),
        "maximum_coverage_inventory_count": int(
            maximum_coverage_activity["inventory_id"].nunique()
        ),
        "maximum_coverage_projected_emissions_rows": int(len(maximum_coverage_projection)),
        "maximum_coverage_factor_method_counts": {
            str(key): int(value)
            for key, value in maximum_coverage_factor_audit["factor_method"].value_counts().items()
        },
        "native_emissions_use": "validation_only",
        "analytical_use_permitted": False,
        "production_blockers": [
            "No Korean non-power factor rows or links are currently production-ready.",
            "The candidate-factor POC uses median unvalidated factors and is non-analytical.",
            "The maximum-coverage POC uses assumed conversions and may ignore factor denominators or sectors.",
            "CAPSS-calibrated effective factors combine a 2021 inventory with the nearest available GCAM activity year.",
            "Native GCAM emissions have national support and do not supply source coordinates.",
            "Primary PM2.5 is not inferred from BC and OC.",
        ],
        "outputs": {key: path.name for key, path in outputs.items() if key != "metadata"},
    }
    outputs["metadata"].write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--activity",
        type=Path,
        default=GCAM_NZK_APHIAM_DIR / "gcam_kaist_nzk_activity.parquet",
    )
    parser.add_argument(
        "--native-emissions",
        type=Path,
        default=GCAM_NZK_APHIAM_DIR / "gcam_kaist_nzk_native_emissions.parquet",
    )
    parser.add_argument("--output-dir", type=Path, default=GCAM_NZK_APHIAM_DIR)
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=NONPOWER_REFERENCE_DIR / CROSSWALK_FILE,
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=NONPOWER_REFERENCE_DIR / INVENTORY_FILE,
    )
    parser.add_argument(
        "--factor-catalog",
        type=Path,
        default=NONPOWER_PROCESSED_DIR / "nonpower_emission_factors.parquet",
    )
    parser.add_argument(
        "--factor-links",
        type=Path,
        default=NONPOWER_PROCESSED_DIR / "nonpower_emission_factor_inventory_links.parquet",
    )
    parser.add_argument(
        "--poc-conversions",
        type=Path,
        default=NONPOWER_REFERENCE_DIR / POC_CONVERSION_FILE,
    )
    parser.add_argument(
        "--capss-admin-weights",
        type=Path,
        default=GCAM_NZK_APHIAM_DIR / "capss_2021_admin_surrogate_weights.parquet",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = build_native_nonpower_interface(
        activity_path=args.activity,
        native_emissions_path=args.native_emissions,
        output_dir=args.output_dir,
        crosswalk_path=args.crosswalk,
        inventory_path=args.inventory,
        factor_catalog_path=args.factor_catalog,
        factor_links_path=args.factor_links,
        poc_conversion_path=args.poc_conversions,
        capss_admin_weights_path=args.capss_admin_weights,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
