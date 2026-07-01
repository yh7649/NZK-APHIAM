"""Plant-to-monitor geometry and conservative wind-transport screening."""

from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: object, lon1: object, lat2: object, lon2: object) -> np.ndarray:
    """Return great-circle distance; inputs may be scalars or array-like."""
    phi1, phi2 = np.deg2rad(lat1), np.deg2rad(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = np.deg2rad(lon2) - np.deg2rad(lon1)
    a = np.sin(delta_phi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def bearing_degrees(lat1: object, lon1: object, lat2: object, lon2: object) -> np.ndarray:
    """Return initial bearing from plant to monitor in degrees clockwise from north."""
    phi1, phi2 = np.deg2rad(lat1), np.deg2rad(lat2)
    delta_lambda = np.deg2rad(lon2) - np.deg2rad(lon1)
    y = np.sin(delta_lambda) * np.cos(phi2)
    x = np.cos(phi1) * np.sin(phi2) - np.sin(phi1) * np.cos(phi2) * np.cos(delta_lambda)
    return (np.rad2deg(np.arctan2(y, x)) + 360) % 360


def wind_alignment(wind_from_degrees: object, plant_to_monitor_bearing: object) -> np.ndarray:
    """Cosine alignment for meteorological wind direction (the direction wind comes from)."""
    wind_to = (np.asarray(wind_from_degrees, dtype=float) + 180) % 360
    difference = np.deg2rad(wind_to - np.asarray(plant_to_monitor_bearing, dtype=float))
    return np.maximum(0, np.cos(difference))


def add_exposure_features(
    hourly: pd.DataFrame,
    plant_latitude: float,
    plant_longitude: float,
    distance_offset_km: float = 5.0,
    distance_power: float = 1.0,
) -> pd.DataFrame:
    """Add geometry and a unitless screening index; this is not a dispersion model."""
    required = {"latitude", "longitude", "wind_direction_deg", "wind_speed_m_s"}
    missing = sorted(required - set(hourly))
    if missing:
        raise ValueError(f"Exposure input is missing columns: {missing}")
    result = hourly.copy()
    result["plant_monitor_distance_km"] = haversine_km(
        plant_latitude, plant_longitude, result["latitude"], result["longitude"]
    )
    result["plant_to_monitor_bearing_deg"] = bearing_degrees(
        plant_latitude, plant_longitude, result["latitude"], result["longitude"]
    )
    result["wind_alignment"] = wind_alignment(
        result["wind_direction_deg"], result["plant_to_monitor_bearing_deg"]
    )
    result["downwind_indicator"] = result["wind_alignment"].gt(0).astype("boolean")
    speed = pd.to_numeric(result["wind_speed_m_s"], errors="coerce").clip(lower=0)
    result["target_exposure"] = (
        result["wind_alignment"]
        * speed
        / (result["plant_monitor_distance_km"] + distance_offset_km) ** distance_power
    )
    return result
