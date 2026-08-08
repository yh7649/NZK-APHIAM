"""Confirm whether an ML-flagged event is shared by nearby monitors."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _haversine_matrix(latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    lat = np.radians(latitude)
    lon = np.radians(longitude)
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    value = (
        np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    )
    return 6371.0088 * 2 * np.arcsin(np.sqrt(value))


def add_spatial_support(
    data: pd.DataFrame,
    radius_km: float = 25.0,
    support_robust_z: float = 3.0,
    minimum_neighbors: int = 1,
) -> pd.DataFrame:
    """Flag ML events whose residual direction is shared by a nearby monitor."""
    result = data.copy()
    result["nearby_monitor_count"] = 0
    result["flag_spatially_supported"] = False
    result["spatial_validation_available"] = False
    required = {"latitude", "longitude", "residual_robust_z"}
    if not required.issubset(result.columns):
        return result

    stations = (
        result[["monitor_id", "latitude", "longitude"]].dropna().drop_duplicates("monitor_id")
    )
    if stations.empty:
        return result
    distances = _haversine_matrix(
        stations["latitude"].to_numpy(), stations["longitude"].to_numpy()
    )
    ids = stations["monitor_id"].astype(str).to_numpy()
    neighbors = {
        station: set(ids[(distances[i] > 0) & (distances[i] <= radius_km)])
        for i, station in enumerate(ids)
    }

    for (_, _), frame in result.groupby(["pollutant", "datetime"], observed=True, sort=False):
        z_by_monitor = (
            frame.set_index(frame["monitor_id"].astype(str))["residual_robust_z"]
            .groupby(level=0)
            .mean()
        )
        for index in frame.index[frame["flag_ml"]]:
            station = str(result.at[index, "monitor_id"])
            available = z_by_monitor.reindex(list(neighbors.get(station, set()))).dropna()
            result.at[index, "nearby_monitor_count"] = len(available)
            result.at[index, "spatial_validation_available"] = len(available) >= minimum_neighbors
            if len(available) < minimum_neighbors:
                continue
            own_z = result.at[index, "residual_robust_z"]
            same_direction = available[np.sign(available) == np.sign(own_z)]
            result.at[index, "flag_spatially_supported"] = bool(
                same_direction.abs().ge(support_robust_z).any()
            )
    return result
