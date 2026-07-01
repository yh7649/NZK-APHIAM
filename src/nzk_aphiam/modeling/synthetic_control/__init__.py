"""Exposure-aware weather-normalized augmented synthetic control."""

from .config import EventConfig, load_event_config
from .exposure import add_exposure_features, bearing_degrees, haversine_km, wind_alignment
from .panel import build_weekly_panel, select_donors

__all__ = [
    "EventConfig",
    "add_exposure_features",
    "bearing_degrees",
    "build_weekly_panel",
    "haversine_km",
    "load_event_config",
    "select_donors",
    "wind_alignment",
]
