"""Monitor-year attributes (station-coordinate crosswalk) for AirKorea observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from nzk_aphiam.air_quality.monitor_canonical import (
    DEFAULT_OUTPUT_DIR as DEFAULT_CANONICAL_DIR,
)
from nzk_aphiam.air_quality.monitor_canonical import (
    _resolve_path,
    load_canonical_manifest,
)
from nzk_aphiam.air_quality.station_crosswalk import (
    build_station_crosswalk,
    normalize_korean_text,
)
from nzk_aphiam.config.paths import AIRKOREA_INTERIM_DIR, AIRKOREA_PROCESSED_DIR
from nzk_aphiam.data.scrape.airkorea.stations import DEFAULT_OUTPUT as DEFAULT_REGISTRY

DEFAULT_INTERIM_CROSSWALK = AIRKOREA_INTERIM_DIR / "airkorea_station_crosswalk.csv"
DEFAULT_ATTRIBUTES_PARQUET = AIRKOREA_PROCESSED_DIR / "airkorea_monitor_year_attributes.parquet"
DEFAULT_ATTRIBUTES_CSV = AIRKOREA_PROCESSED_DIR / "airkorea_monitor_year_attributes.csv"

IDENTITY_COLUMNS = [
    "monitor_id",
    "datetime",
    "reporting_year",
    "station_name",
    "address",
    "region",
    "network_type",
]


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    frame.to_csv(partial, index=False, encoding="utf-8-sig")
    partial.replace(path)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    frame.to_parquet(partial, index=False)
    partial.replace(path)


def _canonical_identities(canonical_dir: Path) -> pd.DataFrame:
    manifest = load_canonical_manifest(canonical_dir)
    parts: list[pd.DataFrame] = []
    for record in manifest.get("parts", []):
        frame = pd.read_parquet(_resolve_path(str(record["output"])), columns=IDENTITY_COLUMNS)
        parts.append(frame.drop_duplicates())
    if not parts:
        raise ValueError("Canonical AirKorea dataset has no identity records")
    return pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)


def _registry_attributes(
    crosswalk: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    """Add current-registry fields only where an address identifies one row."""
    current = registry.copy()
    current["registry_address_key"] = current["address"].map(normalize_korean_text)
    counts = current["registry_address_key"].value_counts()
    unique_keys = counts[counts.eq(1)].index
    current = current[current["registry_address_key"].isin(unique_keys)].copy()
    current = current.rename(
        columns={
            "station_name": "registry_station_name",
            "network_name": "registry_network_name",
            "installation_year": "registry_installation_year",
            "pollutants_reported": "registry_pollutants_reported",
            "registry_retrieved_at_utc": "registry_retrieved_at_utc",
            "address": "registry_address",
            "latitude": "registry_latitude",
            "longitude": "registry_longitude",
        }
    )
    result = crosswalk.copy()
    result["registry_address_key"] = result["current_registry_address"].map(normalize_korean_text)
    keep = [
        "registry_address_key",
        "registry_station_name",
        "registry_network_name",
        "registry_installation_year",
        "registry_pollutants_reported",
        "registry_retrieved_at_utc",
        "registry_address",
        "registry_latitude",
        "registry_longitude",
    ]
    available = [column for column in keep if column in current]
    return result.merge(
        current[available],
        on="registry_address_key",
        how="left",
        validate="m:1",
    ).drop(columns="registry_address_key")


def build_monitor_attributes(
    *,
    canonical_dir: Path = DEFAULT_CANONICAL_DIR,
    registry_path: Path = DEFAULT_REGISTRY,
    historical_stations_path: Path | None = None,
    interim_crosswalk_path: Path = DEFAULT_INTERIM_CROSSWALK,
    attributes_parquet_path: Path = DEFAULT_ATTRIBUTES_PARQUET,
    attributes_csv_path: Path = DEFAULT_ATTRIBUTES_CSV,
) -> pd.DataFrame:
    """Build the comprehensive station-year dimension used by every partition."""
    if not registry_path.exists():
        raise FileNotFoundError(
            f"AirKorea station registry is absent: {registry_path}; "
            "run `python -m nzk_aphiam.data.scrape.airkorea.stations`"
        )
    identities = _canonical_identities(canonical_dir)
    registry = pd.read_csv(registry_path, dtype={"station_name": "string"})
    historical = None
    if historical_stations_path is not None:
        if not historical_stations_path.exists():
            raise FileNotFoundError(
                f"Historical AirKorea station reference is absent: {historical_stations_path}"
            )
        historical = pd.read_csv(
            historical_stations_path,
            dtype={"monitor_id": "string"},
        )
    crosswalk = build_station_crosswalk(identities, registry, historical)
    attributes = _registry_attributes(crosswalk, registry)
    _atomic_csv(crosswalk, interim_crosswalk_path)
    _atomic_parquet(attributes, attributes_parquet_path)
    _atomic_csv(attributes, attributes_csv_path)
    return attributes
