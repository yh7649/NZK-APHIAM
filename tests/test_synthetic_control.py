from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from nzk_aphiam.modeling.synthetic_control.config import EventConfig
from nzk_aphiam.modeling.synthetic_control.exposure import (
    add_exposure_features,
    bearing_degrees,
    haversine_km,
    wind_alignment,
)
from nzk_aphiam.modeling.synthetic_control.panel import build_weekly_panel, select_donors


def event(**updates: object) -> EventConfig:
    values = dict(
        event_id="pilot",
        plant_id="plant",
        event_date=date(2020, 1, 6),
        pre_start=date(2019, 12, 30),
        pre_end=date(2020, 1, 5),
        post_start=date(2020, 1, 6),
        post_end=date(2020, 1, 12),
        pollutants=("SO2",),
        treated_monitor_ids=("T",),
        plant_latitude=36.0,
        plant_longitude=126.0,
        minimum_donor_distance_km=75,
        maximum_donor_exposure=0.01,
        minimum_weekly_hours=2,
        minimum_pre_weeks=1,
        maximum_missing_pre_fraction=0.99,
    )
    values.update(updates)
    return EventConfig(**values)


def test_geometry_and_meteorological_wind_direction() -> None:
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.2, rel=0.01)
    east = bearing_degrees(0, 0, 0, 1)
    assert east == pytest.approx(90)
    assert wind_alignment(270, east) == pytest.approx(1)
    assert wind_alignment(90, east) == pytest.approx(0)


def test_exposure_features_are_stronger_downwind() -> None:
    frame = pd.DataFrame(
        {
            "latitude": [0, 0],
            "longitude": [1, 1],
            "wind_direction_deg": [270, 90],
            "wind_speed_m_s": [5, 5],
        }
    )
    result = add_exposure_features(frame, 0, 0)
    assert result.loc[0, "target_exposure"] > result.loc[1, "target_exposure"]


def test_donor_decisions_and_weekly_coverage() -> None:
    times = pd.to_datetime(
        ["2019-12-30 00:00", "2019-12-30 01:00", "2020-01-06 00:00", "2020-01-06 01:00"]
    )
    rows = []
    for monitor, distance, exposure in [("T", 20, 0.2), ("D", 100, 0.0), ("C", 40, 0.0)]:
        for timestamp in times:
            rows.append(
                {
                    "datetime": timestamp,
                    "monitor_id": monitor,
                    "pollutant": "SO2",
                    "plant_monitor_distance_km": distance,
                    "target_exposure": exposure,
                    "concentration": 2.0,
                    "normalized_concentration": 1.5,
                }
            )
    hourly = pd.DataFrame(rows)
    decisions = select_donors(hourly, event())
    assert decisions.set_index("monitor_id").loc["D", "eligible"]
    assert not decisions.set_index("monitor_id").loc["C", "eligible"]
    weekly = build_weekly_panel(hourly, decisions, event())
    assert set(weekly["monitor_id"]) == {"T", "D"}
    assert weekly.groupby("monitor_id").size().eq(2).all()
    assert set(weekly["post"]) == {0, 1}
