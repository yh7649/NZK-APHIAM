from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nzk_aphiam.archive.kma_weather.process.processor import (
    add_station_location,
    build_local_readme,
    derive_sounding_features,
    normalize_stations,
    normalize_surface,
    summarize_sounding,
    wind_components,
)
from nzk_aphiam.archive.kma_weather.scrape.schemas import ASOS_COLUMNS


def surface_row(**updates: str) -> pd.DataFrame:
    values = {column: "0" for column in ASOS_COLUMNS}
    values.update(
        {
            "TM": "202401010900",
            "STN": "108",
            "WD": "90",
            "WS": "2",
            "GST_WD": "100",
            "GST_WS": "3",
            "PA": "1000",
            "PS": "1010",
            "TA": "5",
            "TD": "-1",
            "HM": "60",
            "PV": "7",
            "RN": "0.5",
            "RN_DAY": "1.0",
            "RN_INT": "0.5",
            "CA_TOT": "7",
            "CA_MID": "4",
            "CH_MIN": "12",
            "VS": "1500",
            "SS": "0.2",
            "SI": "0.4",
            **updates,
        }
    )
    return pd.DataFrame([values])


def test_surface_normalization_converts_kst_and_builds_dispersion_features() -> None:
    result = normalize_surface(surface_row())

    assert result.loc[0, "timestamp_utc"].startswith("2024-01-01 00:00:00+00:00")
    assert result.loc[0, "lowest_cloud_base_m"] == 1200
    assert result.loc[0, "visibility_m"] == 15_000
    assert result.loc[0, "is_precipitating"]
    assert result.loc[0, "wind_u_m_s"] == pytest.approx(-2)
    assert result.loc[0, "wind_v_m_s"] == pytest.approx(0, abs=1e-12)


def test_physical_bounds_remove_missing_sentinels_without_erasing_real_negative_temperature() -> (
    None
):
    result = normalize_surface(surface_row(TA="-9", HM="-9", RN="-9"))

    assert result.loc[0, "temperature_c"] == -9
    assert np.isnan(result.loc[0, "relative_humidity_pct"])
    assert np.isnan(result.loc[0, "precipitation_mm"])
    assert pd.isna(result.loc[0, "is_precipitating"])


def test_wind_components_use_meteorological_from_direction() -> None:
    speed = pd.Series([5.0, 5.0])
    direction = pd.Series([0.0, 180.0])

    eastward, northward = wind_components(speed, direction)

    assert eastward.iloc[0] == pytest.approx(0)
    assert northward.iloc[0] == pytest.approx(-5)
    assert northward.iloc[1] == pytest.approx(5)


def test_sounding_summary_derives_mixing_height_and_surface_inversion() -> None:
    profile = pd.DataFrame(
        {
            "height_m": [50.0, 150.0, 350.0],
            "potential_temperature_k": [290.0, 290.4, 292.2],
        }
    )

    result = summarize_sounding(profile)

    assert result["mixing_height_agl_m"] == 300
    assert result["surface_inversion"] is True
    assert result["inversion_top_agl_m"] == 300
    assert result["inversion_strength_k"] == pytest.approx(2.2)


def test_derived_sounding_features_remain_sparse_at_observation_times() -> None:
    profile = pd.DataFrame(
        {
            "timestamp_utc": ["2024-01-01 00:00:00+00:00"] * 2,
            "station_id": ["47122"] * 2,
            "height_m": [50.0, 300.0],
            "potential_temperature_k": [290.0, 292.1],
        }
    )

    result = derive_sounding_features(profile)

    assert len(result) == 1
    assert result.loc[0, "station_id"] == "47122"


def test_station_history_retains_coordinates_by_network_and_year() -> None:
    raw = pd.DataFrame(
        {
            "SNAPSHOT_YEAR": ["2024"],
            "STATION_TYPE": ["SFC"],
            "STN_ID": ["108"],
            "LON": ["126.97"],
            "LAT": ["37.57"],
            "HT": ["85.7"],
            "HT_WD": ["10"],
            "STN_KO": ["서울"],
            "STN_EN": ["Seoul"],
            "LAW_ID": ["11110"],
            "OBS_START": [pd.NA],
            "OBS_END": [pd.NA],
        }
    )

    result = normalize_stations(raw)

    assert result.loc[0, "snapshot_year"] == 2024
    assert result.loc[0, "station_type"] == "SFC"
    assert result.loc[0, "longitude"] == pytest.approx(126.97)

    observations = pd.DataFrame({"station_id": ["108", "999"], "value": [1, 2]})
    joined = add_station_location(observations, result, "SFC")
    assert joined.loc[0, "station_latitude"] == pytest.approx(37.57)
    assert np.isnan(joined.loc[1, "station_latitude"])


def test_local_readme_uses_archived_paths_and_command() -> None:
    readme = build_local_readme(
        [{"dataset": "surface_hourly", "year": 2024, "rows": 1, "path": "unused"}],
        2024,
        2024,
    )

    assert "data/archive/processed/weather/kma/" in readme
    assert "nzk_aphiam.archive.kma_weather.process" in readme
    assert "make process-kma-weather" not in readme
