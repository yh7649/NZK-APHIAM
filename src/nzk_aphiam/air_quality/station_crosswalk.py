"""Build a year-specific AirKorea station coordinate crosswalk."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd


def normalize_korean_text(value: object) -> str:
    """Normalize provider text for deterministic matching, without fuzzy guesses."""
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower().strip()
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def historical_station_identities(hourly: pd.DataFrame) -> pd.DataFrame:
    """Extract station identity as reported in each annual finalized archive."""
    required = {"monitor_id", "datetime", "station_name", "address"}
    missing = required.difference(hourly.columns)
    if missing:
        raise ValueError(f"Hourly AirKorea data lacks station identity columns: {sorted(missing)}")
    history = hourly[["monitor_id", "datetime", "station_name", "address"]].copy()
    history["year"] = history["datetime"].dt.year.astype("Int64")
    history = history.drop(columns="datetime").drop_duplicates().dropna(subset=["year"])
    history["station_name_key"] = history["station_name"].map(normalize_korean_text)
    history["address_key"] = history["address"].map(normalize_korean_text)
    return history.reset_index(drop=True)


def _prepare_registry(registry: pd.DataFrame) -> pd.DataFrame:
    required = {"station_name", "address", "latitude", "longitude"}
    missing = required.difference(registry.columns)
    if missing:
        raise ValueError(f"Current station registry lacks columns: {sorted(missing)}")
    current = registry.copy()
    current["station_name_key"] = current["station_name"].map(normalize_korean_text)
    current["address_key"] = current["address"].map(normalize_korean_text)
    current["latitude"] = pd.to_numeric(current["latitude"], errors="coerce")
    current["longitude"] = pd.to_numeric(current["longitude"], errors="coerce")
    return current.dropna(subset=["latitude", "longitude"])


def _one_coordinate(candidates: pd.DataFrame) -> tuple[float, float] | None:
    coordinates = candidates[["latitude", "longitude"]].drop_duplicates()
    if len(coordinates) != 1:
        return None
    return float(coordinates.iloc[0, 0]), float(coordinates.iloc[0, 1])


def _match_identity(row: pd.Series, registry: pd.DataFrame) -> dict[str, object]:
    address = registry[registry["address_key"] == row["address_key"]]
    coordinate = _one_coordinate(address) if row["address_key"] else None
    method = "address_exact"
    confidence = "high"
    candidates = address

    if coordinate is None and row["station_name_key"] and row["address_key"]:
        same_name = registry[registry["station_name_key"] == row["station_name_key"]]
        address_contains = same_name["address_key"].map(
                lambda value: (
                    bool(value) and (value in row["address_key"] or row["address_key"] in value)
                )
            ).astype(bool)
        # `.loc` keeps this as a row selection even when `same_name` is empty;
        # `frame[empty_object_series]` can otherwise be treated as a column selector.
        candidates = same_name.loc[address_contains]
        coordinate = _one_coordinate(candidates)
        method = "name_address_containment"
        confidence = "high"

    if coordinate is None:
        same_name = registry[registry["station_name_key"] == row["station_name_key"]]
        candidate_coordinate = _one_coordinate(same_name)
        if candidate_coordinate is not None:
            # A changed address may mean relocation. Record the candidate but do
            # not use its coordinates for spatial QC without historical evidence.
            return {
                "latitude": pd.NA,
                "longitude": pd.NA,
                "coordinate_match_method": "name_only_with_address_change",
                "coordinate_match_confidence": "unresolved",
                "coordinate_candidate_count": len(same_name),
                "current_registry_address": same_name.iloc[0]["address"],
            }
        return {
            "latitude": pd.NA,
            "longitude": pd.NA,
            "coordinate_match_method": "unmatched",
            "coordinate_match_confidence": "unresolved",
            "coordinate_candidate_count": len(same_name),
            "current_registry_address": pd.NA,
        }

    return {
        "latitude": coordinate[0],
        "longitude": coordinate[1],
        "coordinate_match_method": method,
        "coordinate_match_confidence": confidence,
        "coordinate_candidate_count": len(candidates),
        "current_registry_address": candidates.iloc[0]["address"],
    }


def _apply_historical_reference(
    crosswalk: pd.DataFrame, historical_reference: pd.DataFrame
) -> pd.DataFrame:
    """Prefer code/year coordinates transcribed from annual-report appendices."""
    required = {"monitor_id", "year", "latitude", "longitude"}
    missing = required.difference(historical_reference.columns)
    if missing:
        raise ValueError(f"Historical station reference lacks columns: {sorted(missing)}")
    reference = historical_reference.copy()
    reference["monitor_id"] = reference["monitor_id"].astype("string").str.strip()
    reference["year"] = pd.to_numeric(reference["year"], errors="coerce").astype("Int64")
    if reference.duplicated(["monitor_id", "year"]).any():
        raise ValueError("Historical station reference has duplicate monitor_id/year rows")
    reference = reference.rename(
        columns={"latitude": "historical_latitude", "longitude": "historical_longitude"}
    )
    result = crosswalk.merge(reference, on=["monitor_id", "year"], how="left", validate="m:1")
    has_historical = result["historical_latitude"].notna() & result["historical_longitude"].notna()
    result.loc[has_historical, "latitude"] = result.loc[has_historical, "historical_latitude"]
    result.loc[has_historical, "longitude"] = result.loc[has_historical, "historical_longitude"]
    result.loc[has_historical, "coordinate_match_method"] = "annual_report_station_code"
    result.loc[has_historical, "coordinate_match_confidence"] = "authoritative"
    return result.drop(columns=["historical_latitude", "historical_longitude"])


def build_station_crosswalk(
    hourly: pd.DataFrame,
    current_registry: pd.DataFrame,
    historical_reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Resolve coordinates by station-year while exposing every uncertain match."""
    history = historical_station_identities(hourly)
    registry = _prepare_registry(current_registry)
    matches = pd.DataFrame(
        [_match_identity(row, registry) for _, row in history.iterrows()], index=history.index
    )
    identities = pd.concat([history, matches], axis=1)

    rows: list[dict[str, object]] = []
    for (monitor_id, year), group in identities.groupby(["monitor_id", "year"], sort=True):
        resolved = group.dropna(subset=["latitude", "longitude"])
        coordinates = resolved[["latitude", "longitude"]].drop_duplicates()
        base: dict[str, object] = {
            "monitor_id": monitor_id,
            "year": year,
            "historical_station_name": " | ".join(sorted(set(group["station_name"].dropna()))),
            "historical_address": " | ".join(sorted(set(group["address"].dropna()))),
        }
        if len(coordinates) == 1:
            selected = resolved.iloc[0]
            base.update(
                {
                    "latitude": selected["latitude"],
                    "longitude": selected["longitude"],
                    "coordinate_match_method": selected["coordinate_match_method"],
                    "coordinate_match_confidence": selected["coordinate_match_confidence"],
                    "current_registry_address": selected["current_registry_address"],
                }
            )
        elif len(coordinates) > 1:
            base.update(
                {
                    "latitude": pd.NA,
                    "longitude": pd.NA,
                    "coordinate_match_method": "multiple_locations_within_year",
                    "coordinate_match_confidence": "unresolved",
                    "current_registry_address": pd.NA,
                }
            )
        else:
            selected = group.iloc[0]
            base.update(
                {
                    "latitude": pd.NA,
                    "longitude": pd.NA,
                    "coordinate_match_method": selected["coordinate_match_method"],
                    "coordinate_match_confidence": "unresolved",
                    "current_registry_address": selected["current_registry_address"],
                }
            )
        rows.append(base)
    crosswalk = pd.DataFrame(rows)
    if historical_reference is not None:
        crosswalk = _apply_historical_reference(crosswalk, historical_reference)
    return crosswalk.sort_values(["year", "monitor_id"], kind="stable").reset_index(drop=True)


def add_station_coordinates(hourly: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Join station-year coordinates before any ML feature construction."""
    required = {"monitor_id", "year", "latitude", "longitude"}
    missing = required.difference(crosswalk.columns)
    if missing:
        raise ValueError(f"Station crosswalk lacks columns: {sorted(missing)}")
    data = hourly.copy()
    data = data.drop(columns=["latitude", "longitude"], errors="ignore")
    data["station_year"] = data["datetime"].dt.year.astype("Int64")
    reference = crosswalk.rename(columns={"year": "station_year"})
    result = data.merge(
        reference,
        on=["monitor_id", "station_year"],
        how="left",
        validate="m:1",
        suffixes=("", "_crosswalk"),
    )
    if len(result) != len(hourly):
        raise RuntimeError("Station coordinate merge changed the hourly row count")
    return result
