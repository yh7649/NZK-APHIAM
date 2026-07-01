"""Validated event registry for synthetic-control analyses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


@dataclass(frozen=True)
class EventConfig:
    event_id: str
    plant_id: str
    event_date: date
    pre_start: date
    pre_end: date
    post_start: date
    post_end: date
    pollutants: tuple[str, ...]
    treated_monitor_ids: tuple[str, ...]
    plant_latitude: float
    plant_longitude: float
    maximum_treated_distance_km: float = 50.0
    minimum_donor_distance_km: float = 75.0
    maximum_donor_exposure: float = 0.01
    minimum_weekly_hours: int = 120
    minimum_pre_weeks: int = 104
    maximum_missing_pre_fraction: float = 0.2
    same_monitor_type: bool = True

    @property
    def intervention_week(self) -> date:
        return self.event_date - __import__("datetime").timedelta(days=self.event_date.weekday())


def _as_date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)") from error


def load_event_config(path: str | Path) -> EventConfig:
    """Load an event YAML and reject ambiguous or internally inconsistent designs."""
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    required = {
        "event_id",
        "plant_id",
        "event_date",
        "pollutants",
        "treated_monitor_ids",
        "plant",
        "pre_period",
        "post_period",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"Event config is missing fields: {missing}")
    plant = raw["plant"]
    pre = raw["pre_period"]
    post = raw["post_period"]
    treated = raw.get("treated_monitor_rules", {})
    donor = raw.get("donor_rules", {})
    dates = {
        "event_date": _as_date(raw["event_date"], "event_date"),
        "pre_start": _as_date(pre["start"], "pre_period.start"),
        "pre_end": _as_date(pre["end"], "pre_period.end"),
        "post_start": _as_date(post["start"], "post_period.start"),
        "post_end": _as_date(post["end"], "post_period.end"),
    }
    if not dates["pre_start"] <= dates["pre_end"] < dates["event_date"]:
        raise ValueError("Pre-period must end before event_date")
    if not dates["event_date"] <= dates["post_start"] <= dates["post_end"]:
        raise ValueError("Post-period must begin on or after event_date")
    pollutants = tuple(str(value).upper() for value in raw["pollutants"])
    monitor_ids = tuple(str(value) for value in raw["treated_monitor_ids"])
    if not pollutants or not monitor_ids:
        raise ValueError("pollutants and treated_monitor_ids cannot be empty")
    return EventConfig(
        event_id=str(raw["event_id"]),
        plant_id=str(raw["plant_id"]),
        pollutants=pollutants,
        treated_monitor_ids=monitor_ids,
        plant_latitude=float(plant["latitude"]),
        plant_longitude=float(plant["longitude"]),
        maximum_treated_distance_km=float(treated.get("maximum_distance_km", 50)),
        minimum_donor_distance_km=float(donor.get("minimum_distance_from_target_km", 75)),
        maximum_donor_exposure=float(donor.get("maximum_target_exposure", 0.01)),
        minimum_weekly_hours=int(raw.get("minimum_weekly_hours", 120)),
        minimum_pre_weeks=int(donor.get("minimum_pre_weeks", 104)),
        maximum_missing_pre_fraction=float(donor.get("maximum_missing_pre_fraction", 0.2)),
        same_monitor_type=bool(donor.get("same_monitor_type", True)),
        **dates,
    )
