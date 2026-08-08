"""Assemble power-point and non-power-grid emissions into InMAP input bundles."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.io import netcdf_file
import yaml

from nzk_aphiam.air_quality.inmap.emission_inputs import (
    emission_dependency_files,
    validate_coards_netcdf,
    validate_emissions_shapefile,
)
from nzk_aphiam.air_quality.inmap.inventory import write_inventory
from nzk_aphiam.air_quality.inmap.nonpower_spatial import (
    load_monitor_coordinate_surrogates,
    load_spatial_geometry,
)
from nzk_aphiam.config.paths import PROCESSED_DIR, PROJECT_ROOT
from nzk_aphiam.fleet.poc_scenarios import build_baseline_fleet
from nzk_aphiam.fleet.scenario_allocator import allocate_generation
from nzk_aphiam.mvp.peng_replication.scenarios import normalize_macro_scenarios

DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "configs" / "scenarios" / "inmap_combined_proxy_2025_2050.yaml"
)
DEFAULT_OUTPUT_DIR = PROCESSED_DIR / "inmap" / "combined_proxy_2025_2050"
INMAP_POLLUTANTS = {
    "VOCs": ("VOC", "voc_kg"),
    "NOx": ("NOx", "nox_kg"),
    "NH3": ("NH3", "nh3_kg"),
    "SOx": ("SOx", "sox_kg"),
    "PM2.5": ("PM2_5", "pm25_kg"),
}
POINT_PREFERRED_CAPSS_SECTORS = {
    "제조업_연소",
    "생산공정",
    "폐기물처리",
    "에너지수송_및_저장",
}
POWER_EF_POLLUTANTS = {
    "NOx": ("nox", "nox_kg"),
    "SOx": ("sox", "sox_kg"),
    "TSP": ("dust_tsp", "dust_tsp_kg"),
}


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _relative_path(path: Path, base: Path) -> str:
    return str(path.resolve().relative_to(base.resolve()))


def _truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def load_config(path: Path) -> dict[str, Any]:
    """Load the combined inventory configuration and resolve input paths."""
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")
    required = {
        "bundle_status",
        "years",
        "scenario_pairs",
        "inputs",
        "power",
        "nonpower",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"{path} is missing required keys: {missing}")
    config["config_path"] = path.resolve()
    config["inputs"] = {key: _resolve_path(value) for key, value in config["inputs"].items()}
    years = [int(year) for year in config["years"]]
    if years != sorted(set(years)):
        raise ValueError("Combined inventory years must be unique and sorted.")
    config["years"] = years
    if not config["scenario_pairs"]:
        raise ValueError("scenario_pairs may not be empty.")
    return config


def audit_nonpower_factor_catalog(
    factors: pd.DataFrame,
    links: pd.DataFrame,
    *,
    emissions_mode: str,
) -> dict[str, Any]:
    """Audit whether non-power factors are suitable for the requested mode."""
    required_factors = {
        "record_id",
        "production_ready",
        "review_status",
        "pollutant",
        "unit",
    }
    missing_factors = sorted(required_factors - set(factors.columns))
    if missing_factors:
        raise ValueError(f"Non-power factor catalog is missing fields: {missing_factors}")
    required_links = {"record_id", "inventory_id", "production_ready", "match_status"}
    missing_links = sorted(required_links - set(links.columns))
    if missing_links:
        raise ValueError(f"Non-power factor links are missing fields: {missing_links}")

    ready_factors = _truthy(factors["production_ready"])
    ready_links = _truthy(links["production_ready"])
    audit = {
        "emissions_mode": emissions_mode,
        "factor_rows": int(len(factors)),
        "factor_links": int(len(links)),
        "production_ready_factor_rows": int(ready_factors.sum()),
        "production_ready_factor_links": int(ready_links.sum()),
        "candidate_factor_rows": int((~ready_factors).sum()),
        "candidate_factor_links": int((~ready_links).sum()),
        "production_ready_record_ids": sorted(
            factors.loc[ready_factors, "record_id"].astype(str).unique()
        ),
        "factor_pollutants": sorted(factors["pollutant"].dropna().astype(str).unique()),
        "review_status_counts": {
            str(key): int(value)
            for key, value in factors["review_status"].value_counts(dropna=False).items()
        },
    }
    if emissions_mode == "approved_factor_inventory" and (
        not ready_factors.any() or not ready_links.any()
    ):
        raise ValueError(
            "approved_factor_inventory mode requires production-ready non-power factors "
            "and inventory links; the current catalog has none."
        )
    if emissions_mode not in {
        "approved_factor_inventory",
        "candidate_factor_screening",
        "capss_base_intensity_screening",
        "maximum_coverage_poc",
    }:
        raise ValueError(f"Unsupported non-power emissions mode: {emissions_mode}")
    return audit


def _expand_canonical_scenarios(
    data: pd.DataFrame,
    scenario_pairs: Mapping[str, Mapping[str, str]],
    source: str,
) -> pd.DataFrame:
    """Expand source scenarios so one GCAM path can pair with multiple power cases."""
    frames: list[pd.DataFrame] = []
    for canonical, pair in scenario_pairs.items():
        source_name = str(pair[source])
        selected = data.loc[data["scenario"].astype(str).eq(source_name)].copy()
        if selected.empty:
            continue
        selected["source_scenario"] = source_name
        selected["scenario"] = str(canonical)
        frames.append(selected)
    if not frames:
        return data.iloc[0:0].assign(source_scenario=pd.Series(dtype="string"))
    return pd.concat(frames, ignore_index=True)


def prepare_power_generation(
    path: Path,
    config: Mapping[str, Any],
) -> pd.DataFrame:
    """Normalize a MACRO-shaped power file and select the paired scenarios/years."""
    power = config["power"]
    normalized = normalize_macro_scenarios(
        path,
        scenario_label="unlabeled_power_scenario",
        province_crosswalk=power["province_crosswalk"],
        fuel_crosswalk=power["fuel_crosswalk"],
        technology_crosswalk=power["technology_crosswalk"],
    )
    normalized = normalized.loc[normalized["year"].astype(int).isin(config["years"])].copy()
    normalized = _expand_canonical_scenarios(normalized, config["scenario_pairs"], "power")
    if normalized.empty:
        raise ValueError("No configured power scenario/year rows were found.")
    expected = {
        (str(scenario), int(year))
        for scenario in config["scenario_pairs"]
        for year in config["years"]
    }
    observed = set(
        normalized[["scenario", "year"]].drop_duplicates().itertuples(index=False, name=None)
    )
    missing = sorted(expected - observed)
    if missing:
        raise ValueError(f"Power generation is missing configured scenario-years: {missing}")
    return normalized.reset_index(drop=True)


def build_power_emissions(
    generation: pd.DataFrame,
    fleet: pd.DataFrame,
    *,
    fuel_compatibility: Mapping[str, Sequence[str]],
    tolerance_mwh: float,
    ef_source: str,
    ef_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Allocate generation to KEPCO units and apply the unit-carried KEPCO EFs."""
    required_ef_fields = {
        f"{prefix}_ef_kg_per_mwh" for prefix, _mass_field in POWER_EF_POLLUTANTS.values()
    }
    missing = sorted(required_ef_fields - set(fleet.columns))
    if missing:
        raise ValueError(f"KEPCO fleet is missing emission-factor fields: {missing}")
    allocations, diagnostics = allocate_generation(
        generation,
        fleet,
        fuel_compatibility=fuel_compatibility,
        tolerance_mwh=tolerance_mwh,
    )
    for pollutant, (prefix, mass_field) in POWER_EF_POLLUTANTS.items():
        ef_field = f"{prefix}_ef_kg_per_mwh"
        allocations[mass_field] = allocations["generation_mwh"] * allocations[ef_field]
        allocations[f"{prefix}_ef_source"] = ef_source
        allocations[f"{prefix}_ef_year"] = int(ef_year)
        allocations[f"{prefix}_pollutant_label"] = pollutant
    allocations["pm25_kg"] = 0.0
    allocations["nh3_kg"] = 0.0
    allocations["voc_kg"] = 0.0
    allocations["pm25_treatment"] = "omitted_no_documented_tsp_to_primary_pm25_conversion"
    allocations["nh3_treatment"] = "omitted_no_documented_factor"
    allocations["voc_treatment"] = "omitted_no_documented_factor"
    allocations["source_family"] = "power"
    allocations["geometry_type"] = "Point"
    allocations["spatialization_status"] = "kepco_unit_coordinate_with_imputed_stack"
    if (
        allocations[["nox_kg", "sox_kg", "dust_tsp_kg", "pm25_kg", "nh3_kg", "voc_kg"]]
        .isna()
        .any()
        .any()
    ):
        raise ValueError("Power emissions contain missing pollutant mass.")
    return allocations, diagnostics


def prepare_nonpower_emissions(
    projected: pd.DataFrame,
    config: Mapping[str, Any],
    *,
    factor_audit: Mapping[str, Any],
) -> pd.DataFrame:
    """Select paired non-power projected emissions and label their screening status."""
    mode = str(config["nonpower"]["emissions_mode"])
    if mode == "approved_factor_inventory":
        proof_fields = {
            "activity_unit",
            "emission_factor_unit",
            "factor_record_id",
            "factor_production_ready",
        }
        missing_proof = sorted(proof_fields - set(projected.columns))
        if missing_proof:
            raise ValueError(
                "Approved factor-inventory mode requires physical-activity and factor "
                f"provenance fields: {missing_proof}"
            )
        if not _truthy(projected["factor_production_ready"]).all():
            raise ValueError(
                "Approved factor-inventory mode received a non-production-ready factor row."
            )
        approved_ids = set(factor_audit["production_ready_record_ids"])
        unknown_ids = sorted(set(projected["factor_record_id"].astype(str)) - approved_ids)
        if unknown_ids:
            raise ValueError(
                f"Projected emissions reference unapproved factor records: {unknown_ids}"
            )
        if projected["activity_unit"].astype(str).str.contains("index", case=False).any():
            raise ValueError(
                "Approved factor-inventory mode requires physical activity, not an index."
            )
    required = {
        "scenario",
        "year",
        "sector",
        "fuel",
        "pollutant",
        "activity",
        "emission_factor_kg_per_activity",
        "projected_emissions_kg",
    }
    missing = sorted(required - set(projected.columns))
    if missing:
        raise ValueError(f"Projected non-power emissions are missing fields: {missing}")
    unknown_pollutants = sorted(set(projected["pollutant"].dropna()) - set(INMAP_POLLUTANTS))
    if unknown_pollutants:
        raise ValueError(f"Unsupported non-power pollutants: {unknown_pollutants}")

    selected = projected.loc[projected["year"].astype(int).isin(config["years"])].copy()
    selected = _expand_canonical_scenarios(selected, config["scenario_pairs"], "nonpower")
    selected["year"] = selected["year"].astype(int)
    selected["projected_emissions_kg"] = pd.to_numeric(
        selected["projected_emissions_kg"], errors="coerce"
    )
    if selected["projected_emissions_kg"].isna().any():
        raise ValueError("Non-power projected emissions contain missing mass.")
    if (selected["projected_emissions_kg"] < 0).any():
        raise ValueError("Non-power projected emissions must be non-negative.")
    selected["inmap_field"] = selected["pollutant"].map(
        {key: value[0] for key, value in INMAP_POLLUTANTS.items()}
    )
    selected["source_family"] = "nonpower"
    factor_methods = {
        "approved_factor_inventory": "approved_nonpower_factor_inventory",
        "candidate_factor_screening": ("median_unvalidated_candidate_factor_poc"),
        "capss_base_intensity_screening": ("capss_2023_aggregate_emissions_per_activity_index"),
        "maximum_coverage_poc": "ranked_maximum_coverage_nonpower_factor_poc",
    }
    if mode != "maximum_coverage_poc" or "factor_method" not in selected:
        selected["factor_method"] = factor_methods[mode]
    selected["nonpower_emissions_mode"] = mode
    selected["factor_catalog_production_ready_rows"] = int(
        factor_audit["production_ready_factor_rows"]
    )
    spatialization_mode = str(config["nonpower"].get("spatialization_mode", "national_proxy_grid"))
    if spatialization_mode == "reviewed_coordinate_geometry":
        selected["geometry_type"] = "Pending"
        selected["preferred_geometry"] = "Pending"
        selected["spatialization_status"] = "pending_reviewed_coordinate_join"
    elif spatialization_mode == "capss_monitor_coordinate_proxy":
        selected["geometry_type"] = "Pending"
        selected["preferred_geometry"] = "Grid"
        selected["spatialization_status"] = "pending_capss_monitor_coordinate_proxy_join"
    elif spatialization_mode == "national_proxy_grid":
        selected["geometry_type"] = "Grid"
        selected["preferred_geometry"] = np.where(
            selected["sector"].isin(POINT_PREFERRED_CAPSS_SECTORS),
            "Point",
            "Grid",
        )
        selected["spatialization_status"] = np.where(
            selected["preferred_geometry"].eq("Point"),
            "downgraded_to_proxy_grid_missing_facility_locations_and_stacks",
            "proxy_grid_missing_sector_specific_spatial_surrogate",
        )
    else:
        raise ValueError(f"Unsupported non-power spatialization mode: {spatialization_mode}")

    expected = {
        (str(scenario), int(year))
        for scenario in config["scenario_pairs"]
        for year in config["years"]
    }
    observed = set(
        selected[["scenario", "year"]].drop_duplicates().itertuples(index=False, name=None)
    )
    missing_pairs = sorted(expected - observed)
    if missing_pairs:
        raise ValueError(
            f"Non-power emissions are missing configured scenario-years: {missing_pairs}"
        )
    return selected.reset_index(drop=True)


def spatialize_nonpower_with_geometry(
    emissions: pd.DataFrame,
    geometry: pd.DataFrame,
) -> pd.DataFrame:
    """Allocate national inventory totals to reviewed point or grid coordinates."""
    if geometry.empty:
        raise ValueError(
            "reviewed_coordinate_geometry mode requires production-ready non-power "
            "coordinates; nonpower_spatial_geometry.csv is currently empty."
        )
    required = {
        "inventory_id",
        "spatial_id",
        "geometry_type",
        "latitude",
        "longitude",
        "weight",
        "stack_height_m",
        "stack_diameter_m",
        "stack_temperature_k",
        "stack_velocity_m_s",
        "status",
        "source_id",
    }
    missing = sorted(required - set(geometry))
    if missing:
        raise ValueError(f"Non-power geometry is missing fields: {missing}")
    if "inventory_id" not in emissions:
        raise ValueError(
            "Reviewed non-power spatialization requires inventory_id in projected emissions."
        )
    approved = geometry.loc[geometry["status"].eq("production_ready")].copy()
    if approved.empty:
        raise ValueError("Non-power coordinate rows exist, but none have status=production_ready.")
    required_ids = set(emissions["inventory_id"].astype(str))
    available_ids = set(approved["inventory_id"].astype(str))
    missing_ids = sorted(required_ids - available_ids)
    if missing_ids:
        raise ValueError(
            "Production-ready coordinate geometry is missing projected inventory IDs: "
            f"{missing_ids}"
        )
    allocated = emissions.drop(columns="geometry_type", errors="ignore").merge(
        approved,
        on="inventory_id",
        how="left",
        validate="many_to_many",
        suffixes=("", "_geometry"),
    )
    allocated["spatial_weight"] = pd.to_numeric(allocated["weight"], errors="raise")
    allocated["projected_emissions_kg"] *= allocated["spatial_weight"]
    allocated["activity"] *= allocated["spatial_weight"]
    allocated["preferred_geometry"] = allocated["geometry_type"]
    allocated["spatialization_status"] = "reviewed_production_ready_coordinate_geometry"
    allocated["source_id"] = allocated["spatial_id"]

    original = (
        emissions.groupby(["scenario", "year", "pollutant"])["projected_emissions_kg"]
        .sum()
        .sort_index()
    )
    distributed = (
        allocated.groupby(["scenario", "year", "pollutant"])["projected_emissions_kg"]
        .sum()
        .reindex(original.index, fill_value=0.0)
    )
    if not np.allclose(original.to_numpy(), distributed.to_numpy(), rtol=1e-12, atol=1e-6):
        raise AssertionError("Reviewed non-power spatial allocation changed national mass.")
    return allocated.reset_index(drop=True)


def spatialize_nonpower_with_monitor_surrogates(
    emissions: pd.DataFrame,
    surrogates: pd.DataFrame,
) -> pd.DataFrame:
    """Allocate every inventory/pollutant total to CAPSS-weighted monitor centroids."""
    required = {
        "inventory_id",
        "pollutant",
        "latitude",
        "longitude",
        "weight",
        "coordinate_method",
        "spatialization_status",
    }
    missing = sorted(required - set(surrogates))
    if missing:
        raise ValueError(f"CAPSS/monitor spatial surrogates are missing fields: {missing}")
    if "inventory_id" not in emissions:
        raise ValueError(
            "CAPSS/monitor spatialization requires inventory_id in projected emissions."
        )
    required_keys = set(
        emissions[["inventory_id", "pollutant"]].itertuples(index=False, name=None)
    )
    available_keys = set(
        surrogates[["inventory_id", "pollutant"]].itertuples(index=False, name=None)
    )
    missing_keys = sorted(required_keys - available_keys)
    if missing_keys:
        raise ValueError(
            "CAPSS/monitor coordinate surrogates are missing projected "
            f"inventory/pollutant keys: {missing_keys}"
        )
    allocated = emissions.merge(
        surrogates,
        on=["inventory_id", "pollutant"],
        how="left",
        validate="many_to_many",
        suffixes=("", "_surrogate"),
    )
    allocated["spatial_weight"] = pd.to_numeric(allocated["weight"], errors="raise")
    allocated["projected_emissions_kg"] *= allocated["spatial_weight"]
    allocated["activity"] *= allocated["spatial_weight"]
    allocated["geometry_type"] = "Grid"
    allocated["preferred_geometry"] = "Grid"
    if "spatialization_status_surrogate" in allocated:
        allocated["spatialization_status"] = allocated["spatialization_status_surrogate"]
    else:
        allocated["spatialization_status"] = (
            "maximum_coverage_poc_capss_share_at_real_monitor_centroid"
        )
    allocated["source_id"] = (
        "capss-monitor::"
        + allocated["inventory_id"].astype(str)
        + "::"
        + allocated["pollutant"].astype(str)
        + "::"
        + allocated["latitude"].astype(str)
        + "::"
        + allocated["longitude"].astype(str)
    )
    original = (
        emissions.groupby(["scenario", "year", "pollutant"])["projected_emissions_kg"]
        .sum()
        .sort_index()
    )
    distributed = (
        allocated.groupby(["scenario", "year", "pollutant"])["projected_emissions_kg"]
        .sum()
        .reindex(original.index, fill_value=0.0)
    )
    if not np.allclose(original.to_numpy(), distributed.to_numpy(), rtol=1e-12, atol=1e-6):
        raise AssertionError("CAPSS/monitor non-power spatial allocation changed national mass.")
    return allocated.reset_index(drop=True)


def _grid_arrays(grid_config: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    latitude = np.asarray(grid_config["latitudes"], dtype=float)
    longitude = np.asarray(grid_config["longitudes"], dtype=float)
    weights = np.asarray(grid_config["weights"], dtype=float)
    if latitude.ndim != 1 or longitude.ndim != 1 or not latitude.size or not longitude.size:
        raise ValueError("Proxy-grid latitude and longitude must be non-empty vectors.")
    if weights.shape != (latitude.size, longitude.size):
        raise ValueError("Proxy-grid weights must have shape [len(latitudes), len(longitudes)].")
    if not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Proxy-grid weights must be finite and non-negative.")
    if not np.isclose(weights.sum(), 1.0, rtol=0.0, atol=1e-12):
        raise ValueError("Proxy-grid weights must sum to one.")
    return latitude, longitude, weights


def write_coards_inventory(
    emissions: pd.DataFrame,
    path: Path,
    *,
    grid_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Write national non-power totals to a configured NetCDF-3 COARDS proxy grid."""
    required = {"pollutant", "projected_emissions_kg"}
    missing = sorted(required - set(emissions.columns))
    if missing:
        raise ValueError(f"Non-power grid emissions are missing fields: {missing}")
    latitude, longitude, weights = _grid_arrays(grid_config)
    totals = (
        emissions.groupby("pollutant")["projected_emissions_kg"]
        .sum()
        .reindex(INMAP_POLLUTANTS, fill_value=0.0)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with netcdf_file(path, mode="w", version=1) as dataset:
        dataset.history = "NZK-APHIAM screening proxy; not production spatial allocation"
        dataset.spatialization_status = str(grid_config["status"])
        dataset.createDimension("lat", len(latitude))
        dataset.createDimension("lon", len(longitude))
        latitude_variable = dataset.createVariable("lat", "d", ("lat",))
        longitude_variable = dataset.createVariable("lon", "d", ("lon",))
        latitude_variable.units = "degrees_north"
        longitude_variable.units = "degrees_east"
        latitude_variable[:] = latitude
        longitude_variable[:] = longitude
        for pollutant, (inmap_field, _mass_field) in INMAP_POLLUTANTS.items():
            variable = dataset.createVariable(inmap_field, "d", ("lat", "lon"))
            variable.units = "kg"
            variable.long_name = f"annual {pollutant} emissions per grid cell"
            variable[:] = weights * float(totals.loc[pollutant])

    details = validate_coards_netcdf(path)
    with netcdf_file(path, mode="r", mmap=False) as dataset:
        for pollutant, (inmap_field, _mass_field) in INMAP_POLLUTANTS.items():
            written = float(np.asarray(dataset.variables[inmap_field][:], dtype=float).sum())
            expected = float(totals.loc[pollutant])
            if not np.isclose(written, expected, rtol=1e-12, atol=1e-6):
                raise AssertionError(
                    f"COARDS {pollutant} mass balance failed: {written} != {expected}"
                )
    return {
        **details,
        "units": "kg",
        "totals_kg": {str(key): float(value) for key, value in totals.items()},
        "spatialization_status": str(grid_config["status"]),
    }


def write_coordinate_coards_inventory(
    emissions: pd.DataFrame,
    path: Path,
    *,
    spatialization_status: str = "reviewed_production_ready_coordinate_geometry",
) -> dict[str, Any]:
    """Write reviewed coordinate-weighted grid rows to a COARDS NetCDF-3 file."""
    required = {"pollutant", "projected_emissions_kg", "latitude", "longitude"}
    missing = sorted(required - set(emissions))
    if missing:
        raise ValueError(f"Coordinate grid emissions are missing fields: {missing}")
    latitude = np.sort(pd.to_numeric(emissions["latitude"], errors="raise").unique())
    longitude = np.sort(pd.to_numeric(emissions["longitude"], errors="raise").unique())
    if not len(latitude) or not len(longitude):
        raise ValueError("Coordinate grid emissions require at least one location.")
    latitude_index = {value: index for index, value in enumerate(latitude)}
    longitude_index = {value: index for index, value in enumerate(longitude)}
    arrays = {
        pollutant: np.zeros((len(latitude), len(longitude)), dtype=float)
        for pollutant in INMAP_POLLUTANTS
    }
    for row in emissions.itertuples(index=False):
        arrays[str(row.pollutant)][
            latitude_index[float(row.latitude)],
            longitude_index[float(row.longitude)],
        ] += float(row.projected_emissions_kg)

    path.parent.mkdir(parents=True, exist_ok=True)
    with netcdf_file(path, mode="w", version=1) as dataset:
        dataset.history = "NZK-APHIAM non-power coordinate allocation"
        dataset.spatialization_status = spatialization_status
        dataset.createDimension("lat", len(latitude))
        dataset.createDimension("lon", len(longitude))
        latitude_variable = dataset.createVariable("lat", "d", ("lat",))
        longitude_variable = dataset.createVariable("lon", "d", ("lon",))
        latitude_variable.units = "degrees_north"
        longitude_variable.units = "degrees_east"
        latitude_variable[:] = latitude
        longitude_variable[:] = longitude
        for pollutant, (inmap_field, _mass_field) in INMAP_POLLUTANTS.items():
            variable = dataset.createVariable(inmap_field, "d", ("lat", "lon"))
            variable.units = "kg"
            variable.long_name = f"annual {pollutant} emissions per grid cell"
            variable[:] = arrays[pollutant]
    details = validate_coards_netcdf(path)
    return {
        **details,
        "units": "kg",
        "totals_kg": {pollutant: float(values.sum()) for pollutant, values in arrays.items()},
        "spatialization_status": spatialization_status,
    }


def build_nonpower_point_inventory(emissions: pd.DataFrame) -> pd.DataFrame:
    """Pivot reviewed non-power point rows to the InMAP shapefile schema."""
    identity = [
        "spatial_id",
        "inventory_id",
        "latitude",
        "longitude",
        "stack_height_m",
        "stack_diameter_m",
        "stack_temperature_k",
        "stack_velocity_m_s",
    ]
    grouped = (
        emissions.groupby([*identity, "pollutant"], as_index=False)["projected_emissions_kg"]
        .sum()
        .pivot(index=identity, columns="pollutant", values="projected_emissions_kg")
        .fillna(0.0)
        .reset_index()
    )
    for pollutant, (_inmap_field, mass_field) in INMAP_POLLUTANTS.items():
        grouped[mass_field] = grouped.get(pollutant, 0.0)
    grouped["plant_id"] = "nonpower::" + grouped["inventory_id"].astype(str)
    grouped["unit_id"] = grouped["spatial_id"].astype(str)
    grouped["plant_name"] = grouped["inventory_id"].astype(str)
    grouped["pm25_treatment"] = "approved_nonpower_factor"
    grouped["nh3_treatment"] = "approved_nonpower_factor"
    grouped["voc_treatment"] = "approved_nonpower_factor"
    return grouped


def build_harmonized_ledger(
    power: pd.DataFrame,
    nonpower: pd.DataFrame,
) -> pd.DataFrame:
    """Return one long-form accounting ledger for both InMAP input geometries."""
    columns = [
        "scenario",
        "year",
        "source_family",
        "source_id",
        "sector",
        "fuel",
        "technology",
        "pollutant",
        "inmap_field",
        "emissions_kg",
        "geometry_type",
        "preferred_geometry",
        "longitude",
        "latitude",
        "stack_height_m",
        "stack_diameter_m",
        "stack_temperature_k",
        "stack_velocity_m_s",
        "activity",
        "activity_unit",
        "emission_factor",
        "emission_factor_unit",
        "factor_method",
        "spatialization_status",
        "analytical_use_permitted",
    ]
    rows: list[dict[str, Any]] = []
    power_pollutants = {
        "VOCs": ("VOC", "voc_kg", None),
        "NOx": ("NOx", "nox_kg", "nox"),
        "NH3": ("NH3", "nh3_kg", None),
        "SOx": ("SOx", "sox_kg", "sox"),
        "PM2.5": ("PM2_5", "pm25_kg", None),
    }
    for record in power.to_dict("records"):
        for pollutant, (inmap_field, mass_field, ef_prefix) in power_pollutants.items():
            rows.append(
                {
                    "scenario": record["scenario"],
                    "year": int(record["year"]),
                    "source_family": "power",
                    "source_id": record["unit_id"],
                    "sector": "power_generation",
                    "fuel": record["fuel"],
                    "technology": record["technology"],
                    "pollutant": pollutant,
                    "inmap_field": inmap_field,
                    "emissions_kg": float(record[mass_field]),
                    "geometry_type": "Point",
                    "preferred_geometry": "Point",
                    "longitude": float(record["longitude"]),
                    "latitude": float(record["latitude"]),
                    "stack_height_m": float(record["stack_height_m"]),
                    "stack_diameter_m": float(record["stack_diameter_m"]),
                    "stack_temperature_k": float(record["stack_temperature_k"]),
                    "stack_velocity_m_s": float(record["stack_velocity_m_s"]),
                    "activity": float(record["generation_mwh"]),
                    "activity_unit": "MWh/year",
                    "emission_factor": (
                        float(record[f"{ef_prefix}_ef_kg_per_mwh"])
                        if ef_prefix is not None
                        else 0.0
                    ),
                    "emission_factor_unit": "kg/MWh",
                    "factor_method": (
                        str(record.get(f"{ef_prefix}_ef_mapping_level", "kepco_ef"))
                        if ef_prefix is not None
                        else str(record[f"{mass_field[:-3]}_treatment"])
                    ),
                    "spatialization_status": record["spatialization_status"],
                    "analytical_use_permitted": False,
                }
            )
    for record in nonpower.to_dict("records"):
        geometry_type = record.get("geometry_type", "Grid")
        rows.append(
            {
                "scenario": record["scenario"],
                "year": int(record["year"]),
                "source_family": "nonpower",
                "source_id": record.get("source_id", f"{record['sector']}::{record['fuel']}"),
                "sector": record["sector"],
                "fuel": record["fuel"],
                "technology": record.get("gcam_sector", pd.NA),
                "pollutant": record["pollutant"],
                "inmap_field": record["inmap_field"],
                "emissions_kg": float(record["projected_emissions_kg"]),
                "geometry_type": geometry_type,
                "preferred_geometry": record["preferred_geometry"],
                "longitude": record.get("longitude", np.nan),
                "latitude": record.get("latitude", np.nan),
                "stack_height_m": record.get("stack_height_m", np.nan),
                "stack_diameter_m": record.get("stack_diameter_m", np.nan),
                "stack_temperature_k": record.get("stack_temperature_k", np.nan),
                "stack_velocity_m_s": record.get("stack_velocity_m_s", np.nan),
                "activity": float(record["activity"]),
                "activity_unit": record.get("activity_unit", "index_2025_100"),
                "emission_factor": float(record["emission_factor_kg_per_activity"]),
                "emission_factor_unit": record.get(
                    "emission_factor_unit", "kg/activity-index-point"
                ),
                "factor_method": record["factor_method"],
                "spatialization_status": record["spatialization_status"],
                "analytical_use_permitted": False,
            }
        )
    ledger = pd.DataFrame(rows, columns=columns)
    if ledger.empty or ledger["emissions_kg"].isna().any():
        raise ValueError("Harmonized emissions ledger is empty or contains missing mass.")
    return ledger.sort_values(
        ["scenario", "year", "source_family", "source_id", "pollutant"]
    ).reset_index(drop=True)


def _spatialization_diagnostics(nonpower: pd.DataFrame) -> pd.DataFrame:
    return (
        nonpower.groupby(
            [
                "scenario",
                "year",
                "sector",
                "preferred_geometry",
                "geometry_type",
                "spatialization_status",
            ],
            as_index=False,
            dropna=False,
        )["projected_emissions_kg"]
        .sum()
        .rename(columns={"projected_emissions_kg": "emissions_kg"})
        .sort_values(["scenario", "year", "sector"])
        .reset_index(drop=True)
    )


def _mass_reconciliation(ledger: pd.DataFrame) -> pd.DataFrame:
    return (
        ledger.groupby(
            ["scenario", "year", "source_family", "pollutant", "inmap_field"],
            as_index=False,
        )["emissions_kg"]
        .sum()
        .sort_values(["scenario", "year", "source_family", "pollutant"])
        .reset_index(drop=True)
    )


def assemble_combined_inventory(
    config: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Build the complete multi-scenario InMAP emissions-input bundle."""
    inputs = config["inputs"]
    for name, path in inputs.items():
        if not Path(path).is_file():
            raise FileNotFoundError(f"Configured input {name!r} does not exist: {path}")

    factor_catalog = pd.read_parquet(inputs["nonpower_factor_catalog"])
    factor_links = pd.read_parquet(inputs["nonpower_factor_links"])
    factor_audit = audit_nonpower_factor_catalog(
        factor_catalog,
        factor_links,
        emissions_mode=str(config["nonpower"]["emissions_mode"]),
    )
    generation = prepare_power_generation(inputs["power_generation"], config)
    fleet = build_baseline_fleet(
        inputs["kepco_monthly"],
        inputs["stack_properties"],
        baseline_year=int(config["power"]["ef_base_year"]),
        scenario_start_year=min(config["years"]),
    )
    power, allocation_diagnostics = build_power_emissions(
        generation,
        fleet,
        fuel_compatibility=config["power"]["fuel_compatibility"],
        tolerance_mwh=float(config["power"]["mass_balance_tolerance_mwh"]),
        ef_source=_relative_path(inputs["kepco_monthly"], PROJECT_ROOT),
        ef_year=int(config["power"]["ef_base_year"]),
    )
    projected = pd.read_csv(inputs["nonpower_projected_emissions"])
    nonpower = prepare_nonpower_emissions(
        projected,
        config,
        factor_audit=factor_audit,
    )
    spatialization_mode = str(config["nonpower"].get("spatialization_mode", "national_proxy_grid"))
    if spatialization_mode == "reviewed_coordinate_geometry":
        if "nonpower_spatial_geometry" not in inputs:
            raise ValueError(
                "reviewed_coordinate_geometry mode requires the "
                "inputs.nonpower_spatial_geometry path."
            )
        geometry = load_spatial_geometry(inputs["nonpower_spatial_geometry"])
        nonpower = spatialize_nonpower_with_geometry(nonpower, geometry)
    elif spatialization_mode == "capss_monitor_coordinate_proxy":
        if "nonpower_spatial_surrogates" not in inputs:
            raise ValueError(
                "capss_monitor_coordinate_proxy mode requires the "
                "inputs.nonpower_spatial_surrogates path."
            )
        surrogates = load_monitor_coordinate_surrogates(inputs["nonpower_spatial_surrogates"])
        nonpower = spatialize_nonpower_with_monitor_surrogates(nonpower, surrogates)
    ledger = build_harmonized_ledger(power, nonpower)

    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir = output_dir / "diagnostics"
    diagnostics_dir.mkdir(exist_ok=True)
    allocation_diagnostics.to_csv(
        diagnostics_dir / "power_allocation_diagnostics.csv", index=False
    )
    spatial_diagnostics = _spatialization_diagnostics(nonpower)
    spatial_diagnostics.to_csv(
        diagnostics_dir / "nonpower_spatialization_diagnostics.csv", index=False
    )
    reconciliation = _mass_reconciliation(ledger)
    reconciliation.to_csv(diagnostics_dir / "mass_reconciliation.csv", index=False)
    (diagnostics_dir / "nonpower_factor_catalog_audit.json").write_text(
        json.dumps(factor_audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ledger.to_parquet(output_dir / "harmonized_emissions_ledger.parquet", index=False)
    ledger.to_csv(output_dir / "harmonized_emissions_ledger.csv", index=False)

    jobs: list[dict[str, Any]] = []
    for scenario in config["scenario_pairs"]:
        for year in config["years"]:
            job_dir = output_dir / str(scenario) / str(year)
            power_group = power.loc[
                power["scenario"].eq(scenario) & power["year"].eq(year)
            ].reset_index(drop=True)
            nonpower_group = nonpower.loc[
                nonpower["scenario"].eq(scenario) & nonpower["year"].eq(year)
            ].reset_index(drop=True)
            if power_group.empty or nonpower_group.empty:
                raise ValueError(f"Empty combined inventory component for {scenario} {year}.")

            point_files = write_inventory(power_group, job_dir / "power_point")
            point_details = validate_emissions_shapefile(point_files["shapefile"])
            input_records = [
                {
                    "id": "kepco_power_point",
                    "sector": "power",
                    "format": "shapefile",
                    "path": _relative_path(point_files["shapefile"], job_dir),
                    "units": "kg/year",
                    **point_details,
                }
            ]
            emission_paths = [point_files["shapefile"]]
            grid_path: Path | None = None
            nonpower_point_path: Path | None = None
            if spatialization_mode == "reviewed_coordinate_geometry":
                nonpower_points = nonpower_group.loc[nonpower_group["geometry_type"].eq("Point")]
                if not nonpower_points.empty:
                    nonpower_point_files = write_inventory(
                        build_nonpower_point_inventory(nonpower_points),
                        job_dir / "nonpower_point",
                    )
                    nonpower_point_path = nonpower_point_files["shapefile"]
                    nonpower_point_details = validate_emissions_shapefile(nonpower_point_path)
                    emission_paths.append(nonpower_point_path)
                    input_records.append(
                        {
                            "id": "reviewed_nonpower_point",
                            "sector": "nonpower",
                            "format": "shapefile",
                            "path": _relative_path(nonpower_point_path, job_dir),
                            "units": "kg/year",
                            **nonpower_point_details,
                        }
                    )
                nonpower_grid = nonpower_group.loc[nonpower_group["geometry_type"].eq("Grid")]
                if not nonpower_grid.empty:
                    grid_path = job_dir / "nonpower_grid" / "emissions.nc"
                    grid_details = write_coordinate_coards_inventory(nonpower_grid, grid_path)
                    emission_paths.append(grid_path)
                    input_records.append(
                        {
                            "id": "reviewed_nonpower_grid",
                            "sector": "nonpower",
                            "format": "coards",
                            "path": _relative_path(grid_path, job_dir),
                            "units": "kg",
                            "coards_year": int(year),
                            **grid_details,
                        }
                    )
            elif spatialization_mode == "capss_monitor_coordinate_proxy":
                grid_path = job_dir / "nonpower_grid" / "emissions.nc"
                grid_details = write_coordinate_coards_inventory(
                    nonpower_group,
                    grid_path,
                    spatialization_status=(
                        "maximum_coverage_poc_capss_share_at_real_monitor_centroid"
                    ),
                )
                emission_paths.append(grid_path)
                input_records.append(
                    {
                        "id": "capss_weighted_monitor_centroid_nonpower_grid",
                        "sector": "nonpower",
                        "format": "coards",
                        "path": _relative_path(grid_path, job_dir),
                        "units": "kg",
                        "coards_year": int(year),
                        **grid_details,
                    }
                )
            else:
                grid_path = job_dir / "nonpower_grid" / "emissions.nc"
                grid_details = write_coards_inventory(
                    nonpower_group,
                    grid_path,
                    grid_config=config["nonpower"]["proxy_grid"],
                )
                emission_paths.append(grid_path)
                input_records.append(
                    {
                        "id": "gcam_kaist_shaped_nonpower_grid",
                        "sector": "nonpower",
                        "format": "coards",
                        "path": _relative_path(grid_path, job_dir),
                        "units": "kg",
                        "coards_year": int(year),
                        **grid_details,
                    }
                )
            if len(input_records) == 1:
                raise ValueError(
                    f"No reviewed non-power point or grid rows for {scenario} {year}."
                )
            job_ledger = ledger.loc[
                ledger["scenario"].eq(scenario) & ledger["year"].eq(year)
            ].reset_index(drop=True)
            job_ledger.to_parquet(job_dir / "harmonized_emissions_ledger.parquet", index=False)
            job_ledger.to_csv(job_dir / "harmonized_emissions_ledger.csv", index=False)

            dependencies = emission_dependency_files(emission_paths)
            manifest_path = job_dir / "emission_inputs.json"
            manifest = {
                "bundle_status": config["bundle_status"],
                "scenario": str(scenario),
                "year": int(year),
                "analytical_use_permitted": False,
                "inputs": input_records,
                "factor_status": {
                    "power": "kepco_baseline_generation_weighted_factors",
                    "nonpower": str(config["nonpower"]["emissions_mode"]),
                    "production_ready_nonpower_factor_rows": int(
                        factor_audit["production_ready_factor_rows"]
                    ),
                },
                "path_resolution": "relative_to_this_manifest",
                "dependency_sha256": {
                    _relative_path(path, job_dir): _sha256(path) for path in dependencies
                },
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            jobs.append(
                {
                    "scenario": str(scenario),
                    "year": int(year),
                    "manifest": _relative_path(manifest_path, output_dir),
                    "power_shapefile": _relative_path(point_files["shapefile"], output_dir),
                    "nonpower_point_shapefile": (
                        _relative_path(nonpower_point_path, output_dir)
                        if nonpower_point_path is not None
                        else None
                    ),
                    "nonpower_coards": (
                        _relative_path(grid_path, output_dir) if grid_path is not None else None
                    ),
                    "ledger": _relative_path(
                        job_dir / "harmonized_emissions_ledger.parquet",
                        output_dir,
                    ),
                }
            )

    source_checksums = {
        name: {
            "path": _relative_path(Path(path), PROJECT_ROOT),
            "sha256": _sha256(Path(path)),
        }
        for name, path in inputs.items()
    }
    root_manifest = {
        "name": config.get("name", "combined_inmap_inventory"),
        "bundle_status": config["bundle_status"],
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": _relative_path(Path(config["config_path"]), PROJECT_ROOT),
        "years": config["years"],
        "scenarios": list(config["scenario_pairs"]),
        "analytical_use_permitted": False,
        "power_method": (
            "MACRO-shaped generation allocated to KEPCO units and multiplied by "
            f"{config['power']['ef_base_year']} generation-weighted KEPCO factors"
        ),
        "nonpower_method": str(config["nonpower"]["emissions_mode"]),
        "nonpower_factor_catalog_audit": factor_audit,
        "spatialization_status": (
            "reviewed_production_ready_coordinate_geometry"
            if spatialization_mode == "reviewed_coordinate_geometry"
            else (
                "maximum_coverage_poc_capss_share_at_real_monitor_centroid"
                if spatialization_mode == "capss_monitor_coordinate_proxy"
                else str(config["nonpower"]["proxy_grid"]["status"])
            )
        ),
        "source_inputs": source_checksums,
        "outputs": {
            "harmonized_ledger": "harmonized_emissions_ledger.parquet",
            "mass_reconciliation": "diagnostics/mass_reconciliation.csv",
            "power_allocation_diagnostics": ("diagnostics/power_allocation_diagnostics.csv"),
            "nonpower_spatialization_diagnostics": (
                "diagnostics/nonpower_spatialization_diagnostics.csv"
            ),
        },
        "jobs": jobs,
    }
    manifest_path = output_dir / "combined_inmap_input_manifest.json"
    manifest_path.write_text(
        json.dumps(root_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": manifest_path,
        "job_count": len(jobs),
        "power_rows": len(power),
        "nonpower_rows": len(nonpower),
        "ledger_rows": len(ledger),
        "factor_audit": factor_audit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    config = load_config(args.config.resolve())
    result = assemble_combined_inventory(config, args.output_dir.resolve())
    print(
        f"Wrote {result['job_count']} combined InMAP input bundles to {result['manifest'].parent}"
    )


if __name__ == "__main__":
    main()
