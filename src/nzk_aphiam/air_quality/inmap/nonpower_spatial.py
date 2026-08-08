"""Build fail-closed non-power spatial surrogates for native GCAM activity."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from nzk_aphiam.config.paths import (
    AIRKOREA_STATION_RAW_DIR,
    CAPSS_INTERIM_DIR,
    GCAM_NZK_APHIAM_DIR,
    NONPOWER_REFERENCE_DIR,
)
from nzk_aphiam.data.process.capss.processor import normalize_label

POINT_PREFERRED_CAPSS_SECTORS = {
    "제조업_연소",
    "생산공정",
    "폐기물처리",
    "에너지수송_및_저장",
}
INMAP_POLLUTANTS = {"VOCs", "NOx", "NH3", "SOx", "PM2.5"}
GEOMETRY_COLUMNS = (
    "spatial_id",
    "inventory_id",
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
    "notes",
)
MONITOR_SURROGATE_COLUMNS = (
    "inventory_id",
    "pollutant",
    "latitude",
    "longitude",
    "weight",
    "coordinate_method",
    "spatialization_status",
    "analytical_use_permitted",
)
PROVINCE_ALIASES = {
    "강원특별자치도": "강원도",
    "강원": "강원도",
    "경기": "경기도",
    "경남": "경상남도",
    "경북": "경상북도",
    "광주": "광주광역시",
    "대구": "대구광역시",
    "대전": "대전광역시",
    "부산": "부산광역시",
    "서울": "서울특별시",
    "세종": "세종특별자치시",
    "울산": "울산광역시",
    "인천": "인천광역시",
    "전남": "전라남도",
    "전북": "전라북도",
    "전북특별자치도": "전라북도",
    "제주": "제주특별자치도",
    "충남": "충청남도",
    "충북": "충청북도",
}


class SpatialSurrogateError(ValueError):
    """Raised when non-power spatial weights violate their schema."""


def _require_columns(data: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns) - set(data.columns))
    if missing:
        raise SpatialSurrogateError(f"{label} is missing required columns: {missing}")


def _key(value: object) -> str:
    return normalize_label(value) or ""


def _prepare_capss(capss: pd.DataFrame, base_year: int) -> pd.DataFrame:
    required = {
        "year",
        "province_name_ko",
        "sub_district_name_ko",
        "source_category",
        "source_midcategory",
        "source_subcategory",
        "pollutant",
        "emissions_kg",
    }
    _require_columns(capss, required, "CAPSS emissions")
    prepared = capss.loc[
        capss["year"].astype(int).eq(base_year) & capss["pollutant"].isin(INMAP_POLLUTANTS)
    ].copy()
    for column in ("source_category", "source_midcategory", "source_subcategory"):
        prepared[f"_{column}_key"] = prepared[column].map(_key)
    prepared["emissions_kg"] = pd.to_numeric(prepared["emissions_kg"], errors="coerce")
    prepared = prepared.loc[
        prepared["emissions_kg"].notna() & prepared["emissions_kg"].gt(0)
    ].reset_index(drop=True)
    return prepared


def build_capss_admin_surrogates(
    capss: pd.DataFrame,
    inventory_crosswalk: pd.DataFrame,
    *,
    base_year: int = 2021,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Derive inventory/pollutant administrative shares from base-year CAPSS."""
    required_crosswalk = {
        "crosswalk_id",
        "inventory_id",
        "capss_major_category",
        "capss_intermediate_category",
        "capss_minor_category",
        "match_status",
    }
    _require_columns(inventory_crosswalk, required_crosswalk, "GCAM-CAPSS crosswalk")
    prepared = _prepare_capss(capss, base_year)
    selected_frames: list[pd.DataFrame] = []
    audit_rows: list[dict[str, object]] = []
    usable = inventory_crosswalk.loc[
        ~inventory_crosswalk["match_status"].isin({"unresolved", "not_applicable"})
    ]
    for inventory_id, mappings in usable.groupby("inventory_id", sort=True):
        matched_indexes: set[int] = set()
        mapping_ids: list[str] = []
        for mapping in mappings.itertuples(index=False):
            mask = prepared["_source_category_key"].eq(_key(mapping.capss_major_category))
            if mapping.capss_intermediate_category:
                mask &= prepared["_source_midcategory_key"].eq(
                    _key(mapping.capss_intermediate_category)
                )
            if mapping.capss_minor_category:
                mask &= prepared["_source_subcategory_key"].eq(_key(mapping.capss_minor_category))
            indexes = set(prepared.index[mask])
            if indexes:
                mapping_ids.append(str(mapping.crosswalk_id))
                matched_indexes.update(indexes)
        selected = prepared.loc[sorted(matched_indexes)].copy()
        audit_rows.append(
            {
                "inventory_id": inventory_id,
                "base_year": base_year,
                "matched_capss_rows": int(len(selected)),
                "matched_crosswalk_ids": "|".join(sorted(mapping_ids)),
                "pollutant_count": int(selected["pollutant"].nunique()),
                "province_count": int(selected["province_name_ko"].nunique()),
                "district_count": int(selected["sub_district_name_ko"].nunique()),
                "status": (
                    "admin_weights_ready_geometry_missing"
                    if not selected.empty
                    else "no_capss_spatial_match"
                ),
            }
        )
        if selected.empty:
            continue
        selected["inventory_id"] = inventory_id
        selected_frames.append(selected)

    if not selected_frames:
        return pd.DataFrame(), pd.DataFrame(audit_rows)
    selected = pd.concat(selected_frames, ignore_index=True)
    weights = (
        selected.groupby(
            [
                "inventory_id",
                "pollutant",
                "province_name_ko",
                "sub_district_name_ko",
            ],
            dropna=False,
            as_index=False,
        )["emissions_kg"]
        .sum()
        .rename(columns={"emissions_kg": "base_emissions_kg"})
    )
    totals = weights.groupby(["inventory_id", "pollutant"])["base_emissions_kg"].transform("sum")
    weights["weight"] = weights["base_emissions_kg"] / totals
    weights["base_year"] = base_year
    weights["surrogate_source"] = "capss_base_year_administrative_emissions_share"
    weights["geometry_status"] = "administrative_names_only_no_coordinates"
    weights["analytical_use_permitted"] = False
    check = weights.groupby(["inventory_id", "pollutant"])["weight"].sum()
    if not np.allclose(check.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise SpatialSurrogateError("CAPSS administrative weights do not sum to one.")
    return (
        weights.sort_values(
            ["inventory_id", "pollutant", "province_name_ko", "sub_district_name_ko"]
        ).reset_index(drop=True),
        pd.DataFrame(audit_rows).sort_values("inventory_id").reset_index(drop=True),
    )


def _canonical_province(value: object) -> str:
    text = str(value).strip()
    return PROVINCE_ALIASES.get(text, text)


def expand_admin_surrogates_for_poc(
    weights: pd.DataFrame,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    """Fill missing P1 inventory/pollutant keys with national CAPSS patterns."""
    _require_columns(
        weights,
        {
            "inventory_id",
            "pollutant",
            "province_name_ko",
            "sub_district_name_ko",
            "base_emissions_kg",
            "weight",
        },
        "CAPSS administrative weights",
    )
    _require_columns(inventory, {"inventory_id", "priority"}, "non-power inventory")
    expanded = weights.copy()
    expanded["allocation_origin"] = "inventory_specific_capss_crosswalk"
    existing = set(expanded[["inventory_id", "pollutant"]].itertuples(index=False, name=None))
    p1_ids = sorted(
        inventory.loc[inventory["priority"].eq("P1"), "inventory_id"].astype(str).unique()
    )
    fallback_by_pollutant: dict[str, pd.DataFrame] = {}
    for pollutant, rows in weights.groupby("pollutant", sort=True):
        fallback = (
            rows.groupby(
                ["province_name_ko", "sub_district_name_ko"],
                dropna=False,
                as_index=False,
            )["base_emissions_kg"]
            .sum()
            .loc[lambda frame: frame["base_emissions_kg"].gt(0)]
        )
        total = float(fallback["base_emissions_kg"].sum())
        if total > 0:
            fallback["weight"] = fallback["base_emissions_kg"] / total
            fallback_by_pollutant[str(pollutant)] = fallback
    additions: list[pd.DataFrame] = []
    for inventory_id in p1_ids:
        for pollutant in sorted(INMAP_POLLUTANTS):
            if (inventory_id, pollutant) in existing:
                continue
            fallback = fallback_by_pollutant.get(pollutant)
            if fallback is None or fallback.empty:
                raise SpatialSurrogateError(
                    f"No CAPSS administrative fallback exists for {pollutant}."
                )
            addition = fallback.copy()
            addition["inventory_id"] = inventory_id
            addition["pollutant"] = pollutant
            addition["base_year"] = int(weights["base_year"].iloc[0])
            addition["surrogate_source"] = (
                "national_all_inventory_capss_pollutant_distribution_poc"
            )
            addition["geometry_status"] = "administrative_names_only_no_coordinates"
            addition["analytical_use_permitted"] = False
            addition["allocation_origin"] = (
                "national_capss_pollutant_fallback_missing_inventory_crosswalk"
            )
            additions.append(addition)
    if additions:
        expanded = pd.concat([expanded, *additions], ignore_index=True, sort=False)
    check = expanded.groupby(["inventory_id", "pollutant"])["weight"].sum()
    if not np.allclose(check.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise SpatialSurrogateError("Expanded POC administrative weights do not sum to one.")
    return expanded.reset_index(drop=True)


def build_monitor_coordinate_surrogates(
    admin_weights: pd.DataFrame,
    stations: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Place CAPSS administrative shares at matching real monitor centroids."""
    _require_columns(
        admin_weights,
        {
            "inventory_id",
            "pollutant",
            "province_name_ko",
            "sub_district_name_ko",
            "weight",
            "allocation_origin",
        },
        "expanded CAPSS administrative weights",
    )
    _require_columns(
        stations,
        {"address", "latitude", "longitude", "station_name"},
        "AirKorea station registry",
    )
    station_frame = stations.copy()
    station_frame["latitude"] = pd.to_numeric(station_frame["latitude"], errors="coerce")
    station_frame["longitude"] = pd.to_numeric(station_frame["longitude"], errors="coerce")
    address_parts = (
        station_frame["address"].fillna("").astype(str).str.extract(r"^\s*(\S+)\s+(\S+)")
    )
    station_frame["_province"] = address_parts[0].map(_canonical_province)
    station_frame["_district"] = address_parts[1].fillna("").astype(str)
    station_frame = station_frame.loc[
        station_frame["latitude"].between(33.0, 39.0)
        & station_frame["longitude"].between(124.0, 132.0)
        & station_frame["_province"].ne("")
    ].copy()
    if station_frame.empty:
        raise SpatialSurrogateError("AirKorea station registry has no usable coordinates.")
    district_centroids = (
        station_frame.groupby(["_province", "_district"], as_index=False)
        .agg(
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
            monitor_count=("station_name", "size"),
        )
        .set_index(["_province", "_district"])
    )
    province_centroids = (
        station_frame.groupby("_province", as_index=False)
        .agg(
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
            monitor_count=("station_name", "size"),
        )
        .set_index("_province")
    )
    national_latitude = float(station_frame["latitude"].mean())
    national_longitude = float(station_frame["longitude"].mean())
    national_count = int(len(station_frame))

    rows: list[dict[str, object]] = []
    for admin in admin_weights.itertuples(index=False):
        province = _canonical_province(admin.province_name_ko)
        district = str(admin.sub_district_name_ko).strip().split()[0]
        district_key = (province, district)
        if district_key in district_centroids.index:
            centroid = district_centroids.loc[district_key]
            method = "capss_district_share_at_airkorea_district_monitor_centroid"
        elif province in province_centroids.index:
            centroid = province_centroids.loc[province]
            method = "capss_district_share_at_airkorea_province_monitor_centroid"
        else:
            centroid = pd.Series(
                {
                    "latitude": national_latitude,
                    "longitude": national_longitude,
                    "monitor_count": national_count,
                }
            )
            method = "capss_district_share_at_national_airkorea_monitor_centroid"
        rows.append(
            {
                "inventory_id": str(admin.inventory_id),
                "pollutant": str(admin.pollutant),
                "province_name_ko": str(admin.province_name_ko),
                "sub_district_name_ko": str(admin.sub_district_name_ko),
                "latitude": round(float(centroid["latitude"]), 6),
                "longitude": round(float(centroid["longitude"]), 6),
                "weight": float(admin.weight),
                "base_emissions_kg": float(admin.base_emissions_kg),
                "allocation_origin": str(admin.allocation_origin),
                "coordinate_method": method,
                "monitor_count": int(centroid["monitor_count"]),
                "spatialization_status": (
                    "maximum_coverage_poc_capss_share_at_real_monitor_centroid"
                ),
                "analytical_use_permitted": False,
            }
        )
    unaggregated = pd.DataFrame(rows)
    surrogate = (
        unaggregated.groupby(
            [
                "inventory_id",
                "pollutant",
                "latitude",
                "longitude",
                "allocation_origin",
                "coordinate_method",
                "spatialization_status",
                "analytical_use_permitted",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            weight=("weight", "sum"),
            base_emissions_kg=("base_emissions_kg", "sum"),
            capss_admin_area_count=("sub_district_name_ko", "size"),
            monitor_count=("monitor_count", "max"),
        )
        .sort_values(["inventory_id", "pollutant", "latitude", "longitude"])
        .reset_index(drop=True)
    )
    totals = surrogate.groupby(["inventory_id", "pollutant"])["weight"].transform("sum")
    surrogate["weight"] = surrogate["weight"] / totals
    check = surrogate.groupby(["inventory_id", "pollutant"])["weight"].sum()
    if not np.allclose(check.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise SpatialSurrogateError("Monitor-coordinate surrogate weights do not sum to one.")
    audit = (
        unaggregated.groupby(
            ["inventory_id", "pollutant", "allocation_origin"],
            as_index=False,
        )
        .agg(
            capss_admin_area_count=("sub_district_name_ko", "size"),
            coordinate_count=("latitude", "nunique"),
            district_monitor_centroid_count=(
                "coordinate_method",
                lambda values: int(
                    values.eq("capss_district_share_at_airkorea_district_monitor_centroid").sum()
                ),
            ),
            province_monitor_centroid_count=(
                "coordinate_method",
                lambda values: int(
                    values.eq("capss_district_share_at_airkorea_province_monitor_centroid").sum()
                ),
            ),
            national_monitor_centroid_count=(
                "coordinate_method",
                lambda values: int(
                    values.eq("capss_district_share_at_national_airkorea_monitor_centroid").sum()
                ),
            ),
        )
        .sort_values(["inventory_id", "pollutant"])
        .reset_index(drop=True)
    )
    audit["analytical_use_permitted"] = False
    return surrogate, audit


def load_monitor_coordinate_surrogates(path: Path) -> pd.DataFrame:
    """Load and validate the non-analytical CAPSS/monitor coordinate surrogate."""
    surrogate = (
        pd.read_parquet(path) if path.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(path)
    )
    _require_columns(
        surrogate,
        MONITOR_SURROGATE_COLUMNS,
        "CAPSS/monitor coordinate surrogate",
    )
    for column in ("latitude", "longitude", "weight"):
        surrogate[column] = pd.to_numeric(surrogate[column], errors="coerce")
    if surrogate[["latitude", "longitude", "weight"]].isna().any().any():
        raise SpatialSurrogateError(
            "CAPSS/monitor coordinate surrogate requires numeric coordinates and weights."
        )
    if not surrogate["latitude"].between(33.0, 39.0).all():
        raise SpatialSurrogateError("Monitor surrogate latitude lies outside South Korea.")
    if not surrogate["longitude"].between(124.0, 132.0).all():
        raise SpatialSurrogateError("Monitor surrogate longitude lies outside South Korea.")
    if (surrogate["weight"] <= 0).any():
        raise SpatialSurrogateError("Monitor surrogate weights must be positive.")
    if (
        surrogate["analytical_use_permitted"]
        .astype(str)
        .str.lower()
        .isin({"1", "true", "yes"})
        .any()
    ):
        raise SpatialSurrogateError("Monitor-coordinate POC may not claim analytical use.")
    sums = surrogate.groupby(["inventory_id", "pollutant"])["weight"].sum()
    if not np.allclose(sums.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise SpatialSurrogateError(
            "Monitor surrogate weights must sum to one per inventory/pollutant."
        )
    return surrogate


def load_spatial_geometry(path: Path) -> pd.DataFrame:
    geometry = pd.read_csv(path, dtype=str, keep_default_na=False)
    _require_columns(geometry, GEOMETRY_COLUMNS, "non-power spatial geometry")
    if geometry.empty:
        return geometry
    if geometry["spatial_id"].duplicated().any():
        duplicate = sorted(geometry.loc[geometry["spatial_id"].duplicated(), "spatial_id"])
        raise SpatialSurrogateError(f"Duplicate non-power spatial IDs: {duplicate}")
    if not set(geometry["geometry_type"]).issubset({"Point", "Grid"}):
        raise SpatialSurrogateError("geometry_type must be Point or Grid.")
    for column in ("latitude", "longitude", "weight"):
        geometry[column] = pd.to_numeric(geometry[column], errors="coerce")
    if geometry[["latitude", "longitude", "weight"]].isna().any().any():
        raise SpatialSurrogateError("Spatial geometry requires numeric coordinates and weights.")
    if not geometry["latitude"].between(33.0, 39.0).all():
        raise SpatialSurrogateError("Spatial latitude lies outside South Korea.")
    if not geometry["longitude"].between(124.0, 132.0).all():
        raise SpatialSurrogateError("Spatial longitude lies outside South Korea.")
    if (geometry["weight"] <= 0).any():
        raise SpatialSurrogateError("Spatial weights must be positive.")
    sums = geometry.groupby("inventory_id")["weight"].sum()
    if not np.allclose(sums.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise SpatialSurrogateError("Spatial weights must sum to one for each inventory_id.")
    point = geometry["geometry_type"].eq("Point")
    stack_columns = (
        "stack_height_m",
        "stack_diameter_m",
        "stack_temperature_k",
        "stack_velocity_m_s",
    )
    for column in stack_columns:
        numeric = pd.to_numeric(geometry.loc[point, column], errors="coerce")
        if numeric.isna().any() or (numeric <= 0).any():
            raise SpatialSurrogateError(f"Point geometry requires positive numeric {column}.")
    return geometry


def build_spatial_readiness(
    inventory: pd.DataFrame,
    inventory_crosswalk: pd.DataFrame,
    admin_audit: pd.DataFrame,
    geometry: pd.DataFrame,
) -> pd.DataFrame:
    """Report the exact routing state for every priority inventory activity."""
    p1 = inventory.loc[inventory["priority"].eq("P1"), ["inventory_id"]].copy()
    admin_status = (
        admin_audit.set_index("inventory_id")["status"].to_dict() if not admin_audit.empty else {}
    )
    geometry_ids = (
        set(geometry.loc[geometry["status"].eq("production_ready"), "inventory_id"])
        if not geometry.empty
        else set()
    )
    rows: list[dict[str, object]] = []
    for inventory_id in p1["inventory_id"]:
        mappings = inventory_crosswalk.loc[inventory_crosswalk["inventory_id"].eq(inventory_id)]
        categories = {
            _key(value) for value in mappings["capss_major_category"] if str(value).strip()
        }
        point_flags = {category in POINT_PREFERRED_CAPSS_SECTORS for category in categories}
        if point_flags == {True}:
            preferred = "Point"
        elif point_flags == {False}:
            preferred = "Grid"
        elif not point_flags:
            preferred = "Unresolved"
        else:
            preferred = "Mixed"
        has_geometry = inventory_id in geometry_ids
        if has_geometry:
            status = "geometry_ready"
        elif preferred == "Point":
            status = "blocked_missing_nonpower_facility_coordinates_and_stacks"
        elif admin_status.get(inventory_id) == "admin_weights_ready_geometry_missing":
            status = "blocked_admin_weights_ready_but_grid_geometry_missing"
        else:
            status = "blocked_missing_spatial_surrogate"
        rows.append(
            {
                "inventory_id": inventory_id,
                "preferred_geometry": preferred,
                "capss_admin_status": admin_status.get(inventory_id, "no_capss_spatial_match"),
                "coordinate_geometry_available": has_geometry,
                "routing_status": status,
                "analytical_use_permitted": has_geometry,
            }
        )
    return pd.DataFrame(rows).sort_values("inventory_id").reset_index(drop=True)


def build_nonpower_spatial_interface(
    *,
    capss_path: Path,
    inventory_path: Path,
    inventory_crosswalk_path: Path,
    geometry_path: Path,
    station_registry_path: Path,
    output_dir: Path,
    base_year: int = 2021,
) -> dict[str, object]:
    capss = pd.read_parquet(capss_path)
    inventory = pd.read_csv(inventory_path, dtype=str, keep_default_na=False)
    inventory_crosswalk = pd.read_csv(inventory_crosswalk_path, dtype=str, keep_default_na=False)
    stations = pd.read_csv(station_registry_path, dtype=str)
    geometry = load_spatial_geometry(geometry_path)
    weights, admin_audit = build_capss_admin_surrogates(
        capss, inventory_crosswalk, base_year=base_year
    )
    expanded_weights = expand_admin_surrogates_for_poc(weights, inventory)
    monitor_surrogate, monitor_audit = build_monitor_coordinate_surrogates(
        expanded_weights, stations
    )
    readiness = build_spatial_readiness(inventory, inventory_crosswalk, admin_audit, geometry)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "admin_weights": output_dir / f"capss_{base_year}_admin_surrogate_weights.parquet",
        "admin_weights_csv": output_dir / f"capss_{base_year}_admin_surrogate_weights.csv",
        "admin_audit": output_dir / f"capss_{base_year}_admin_surrogate_audit.csv",
        "monitor_surrogate": output_dir
        / f"capss_{base_year}_monitor_coordinate_surrogate_weights.parquet",
        "monitor_surrogate_csv": output_dir
        / f"capss_{base_year}_monitor_coordinate_surrogate_weights.csv",
        "monitor_surrogate_audit": output_dir
        / f"capss_{base_year}_monitor_coordinate_surrogate_audit.csv",
        "readiness": output_dir / "nonpower_spatial_readiness.csv",
        "metadata": output_dir / "nonpower_spatial_interface.metadata.json",
    }
    weights.to_parquet(outputs["admin_weights"], index=False)
    weights.to_csv(outputs["admin_weights_csv"], index=False)
    admin_audit.to_csv(outputs["admin_audit"], index=False)
    monitor_surrogate.to_parquet(outputs["monitor_surrogate"], index=False)
    monitor_surrogate.to_csv(outputs["monitor_surrogate_csv"], index=False)
    monitor_audit.to_csv(outputs["monitor_surrogate_audit"], index=False)
    readiness.to_csv(outputs["readiness"], index=False)
    ready_count = int(readiness["coordinate_geometry_available"].sum())
    metadata: dict[str, object] = {
        "dataset": "NZK non-power spatial interface",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "capss_base_year": base_year,
        "admin_weight_rows": int(len(weights)),
        "admin_weight_inventory_count": int(weights["inventory_id"].nunique()),
        "poc_monitor_surrogate_rows": int(len(monitor_surrogate)),
        "poc_monitor_surrogate_inventory_count": int(monitor_surrogate["inventory_id"].nunique()),
        "poc_monitor_surrogate_inventory_pollutant_count": int(
            len(monitor_surrogate[["inventory_id", "pollutant"]].drop_duplicates())
        ),
        "poc_monitor_surrogate_coordinate_method_counts": {
            str(key): int(value)
            for key, value in monitor_surrogate["coordinate_method"].value_counts().items()
        },
        "poc_monitor_surrogate_analytical_use_permitted": False,
        "priority_inventory_count": int(len(readiness)),
        "coordinate_ready_priority_inventory_count": ready_count,
        "analytical_use_permitted": ready_count == len(readiness),
        "status": (
            "ready" if ready_count == len(readiness) else "blocked_pending_coordinate_geometry"
        ),
        "outputs": {key: path.name for key, path in outputs.items() if key != "metadata"},
    }
    outputs["metadata"].write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capss",
        type=Path,
        default=CAPSS_INTERIM_DIR / "emissions_statistics" / "capss_emissions_tidy.parquet",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=NONPOWER_REFERENCE_DIR / "gcam_kaist_nonpower_sector_inventory.csv",
    )
    parser.add_argument(
        "--inventory-crosswalk",
        type=Path,
        default=NONPOWER_REFERENCE_DIR / "gcam_capss_nonpower_crosswalk.csv",
    )
    parser.add_argument(
        "--geometry",
        type=Path,
        default=NONPOWER_REFERENCE_DIR / "nonpower_spatial_geometry.csv",
    )
    parser.add_argument(
        "--station-registry",
        type=Path,
        default=AIRKOREA_STATION_RAW_DIR / "airkorea_station_registry_current.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=GCAM_NZK_APHIAM_DIR)
    parser.add_argument("--base-year", type=int, default=2021)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = build_nonpower_spatial_interface(
        capss_path=args.capss,
        inventory_path=args.inventory,
        inventory_crosswalk_path=args.inventory_crosswalk,
        geometry_path=args.geometry,
        station_registry_path=args.station_registry,
        output_dir=args.output_dir,
        base_year=args.base_year,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
