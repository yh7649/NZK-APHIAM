from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
import yaml

from nzk_aphiam.air_quality.monitor_aggregation import (
    aggregate_qc_partitions,
    annual_pm_summaries,
    daily_pm_summaries,
    load_aggregation_config,
    monthly_summaries,
    quarterly_pm_summaries,
)
from nzk_aphiam.air_quality.monitor_attributes import build_monitor_attributes
from nzk_aphiam.air_quality.monitor_bias_grid import (
    GridConfig,
    interpolate_monitor_bias,
    monitor_grid_comparison,
)
from nzk_aphiam.air_quality.monitor_canonical import (
    CANONICAL_WIDE_COLUMNS,
    canonicalize_archives,
    standardize_wide_frame,
)
from nzk_aphiam.air_quality.monitor_qc import clean_qc_partitions
from nzk_aphiam.air_quality.pipeline import _parse_airkorea_datetime
from nzk_aphiam.air_quality.spatial_validation import add_spatial_support


def _config(path: Path) -> Path:
    settings = {
        "rules": {
            "bounds": {"PM25": [0.0, 1000.0]},
            "missing_sentinels": [-999.0, -9999.0],
            "flatline_hours": 12,
            "jump_multiplier": 10.0,
            "jump_minimum": {"PM25": 200.0},
        },
        "model": {
            "n_estimators": 5,
            "min_samples_leaf": 2,
            "max_features": 0.7,
            "random_state": 2026,
            "n_jobs": 1,
            "n_folds": 2,
            "mad_threshold": 6.0,
            "minimum_training_rows": 10,
            "max_training_rows": 100,
        },
        "spatial": {
            "radius_km": 25.0,
            "support_robust_z": 3.0,
            "minimum_neighbors": 1,
        },
        "aggregation": {
            "daily_min_fraction": 0.75,
            "quarterly_min_fraction": 0.75,
            "required_valid_quarters": 4,
            "annual_pollutants": ["PM25"],
        },
        "grid": {
            "interpolation": "idw_monitor_residual",
            "neighbor_count": 8,
            "power": 2.0,
            "max_distance_km": 250.0,
        },
    }
    path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    return path


def test_canonical_wide_standardization_preserves_source_rows() -> None:
    raw = pd.DataFrame(
        {
            "지역": ["서울", "서울"],
            "망": ["도시대기", "도시대기"],
            "측정소코드": [111, 112],
            "측정소명": ["A", "B"],
            "측정일시": [2024010101, 2024010101],
            "PM2.5": [12.0, -999.0],
            "주소": ["주소 A", "주소 B"],
        }
    )
    result, pollutants = standardize_wide_frame(
        raw,
        reporting_year=2024,
        source_archive="2024.zip",
        source_member="january.xlsx",
        member_index=0,
        archive_sha256="a" * 64,
        archive_provisional=False,
    )

    assert len(result) == len(raw)
    assert result.columns.tolist() == CANONICAL_WIDE_COLUMNS
    assert pollutants == ["PM25"]
    assert result["PM25"].tolist() == [12.0, -999.0]
    assert result["source_record_id"].is_unique


def test_canonical_wide_accepts_historical_data_tine_typo() -> None:
    raw = pd.DataFrame(
        {
            "측정소코드": [111],
            "DATA_TINE": [2004100101],
            "PM10": [42.0],
        }
    )
    result, pollutants = standardize_wide_frame(
        raw,
        reporting_year=2004,
        source_archive="2004.zip",
        source_member="2004-Q4.xlsx",
        member_index=3,
        archive_sha256="a" * 64,
        archive_provisional=False,
    )

    assert pollutants == ["PM10"]
    assert result.loc[0, "datetime"] == pd.Timestamp("2004-10-01 01:00:00")


def test_hour_24_stays_in_reporting_day_and_meets_daily_completeness(
    tmp_path: Path,
) -> None:
    config = load_aggregation_config(_config(tmp_path / "config.yml"))
    raw_times = pd.Series([f"20240101{hour:02d}" for hour in range(1, 25)])
    hourly = pd.DataFrame(
        {
            "reporting_year": 2024,
            "monitor_id": "A",
            "datetime": _parse_airkorea_datetime(raw_times),
            "measurement_datetime_raw": raw_times,
            "pollutant": "PM25",
            "unit": "ug/m3",
            "value_raw": np.arange(1, 25, dtype=float),
            "value_analysis": np.arange(1, 25, dtype=float),
            "source_record_id": [f"r{index}" for index in range(24)],
            "archive_provisional": False,
        }
    )

    daily = daily_pm_summaries(hourly, config)
    monthly_raw, monthly_qc = monthly_summaries(hourly)

    assert daily.loc[0, "date"] == pd.Timestamp("2024-01-01")
    assert daily.loc[0, "valid_hours"] == 24
    assert daily.loc[0, "daily_valid"]
    assert monthly_raw.loc[0, "month"] == pd.Timestamp("2024-01-01")
    assert monthly_qc.loc[0, "hours"] == 24


def test_complete_year_uses_equal_weighted_valid_quarter_means(
    tmp_path: Path,
) -> None:
    config = load_aggregation_config(_config(tmp_path / "config.yml"))
    dates = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    daily = pd.DataFrame(
        {
            "reporting_year": 2024,
            "monitor_id": "A",
            "date": dates,
            "pollutant": "PM25",
            "unit": "ug/m3",
            "daily_mean": dates.quarter.astype(float) * 10,
            "daily_valid": True,
            "valid_hours": 24,
            "archive_provisional": False,
        }
    )

    quarterly = quarterly_pm_summaries(daily, config)
    annual = annual_pm_summaries(daily, quarterly, config)

    assert quarterly["quarter_valid"].all()
    assert annual.loc[0, "valid_quarters"] == 4
    assert annual.loc[0, "analysis_ready"]
    assert annual.loc[0, "annual_mean"] == 25.0


def test_grid_stage_interpolates_monitor_residual_not_observed_surface() -> None:
    annual = pd.DataFrame(
        {
            "reporting_year": [2024, 2024],
            "monitor_id": ["A", "B"],
            "pollutant": ["PM25", "PM25"],
            "analysis_ready": [True, True],
            "annual_mean": [12.0, 25.0],
            "longitude": [126.5, 127.5],
            "latitude": [36.5, 36.5],
        }
    )
    grid = gpd.GeoDataFrame(
        {"TotalPM25": [10.0, 20.0]},
        geometry=[
            box(126.0, 36.0, 127.0, 37.0),
            box(127.0, 36.0, 128.0, 37.0),
        ],
        crs="EPSG:4326",
    )

    comparison, prepared_grid = monitor_grid_comparison(
        annual,
        grid,
        year=2024,
    )
    corrected = interpolate_monitor_bias(
        comparison,
        prepared_grid,
        GridConfig(neighbor_count=1),
    )

    assert sorted(comparison["monitor_bias_ugm3"]) == [2.0, 5.0]
    assert corrected["bias_correction_ugm3"].notna().all()
    assert corrected["corrected_pm25_ugm3"].tolist() == [12.0, 25.0]


def test_spatial_support_handles_duplicate_monitor_hour_rows() -> None:
    data = pd.DataFrame(
        {
            "monitor_id": ["A", "A", "B"],
            "pollutant": ["PM25", "PM25", "PM25"],
            "datetime": [pd.Timestamp("2024-01-01 00:00:00")] * 3,
            "latitude": [37.50, 37.50, 37.51],
            "longitude": [127.00, 127.00, 127.01],
            "residual_robust_z": [8.0, 8.5, 9.0],
            "flag_ml": [True, True, True],
        }
    )

    result = add_spatial_support(data, radius_km=25.0, support_robust_z=3.0, minimum_neighbors=1)

    assert result["nearby_monitor_count"].tolist() == [1, 1, 1]
    assert result["flag_spatially_supported"].all()


def test_miniature_three_stage_workflow(tmp_path: Path) -> None:
    archive_dir = tmp_path / "raw"
    archive_dir.mkdir()
    source = tmp_path / "source.xlsx"
    raw_times = [f"202401{day:02d}{hour:02d}" for day in (1, 2) for hour in range(1, 25)]
    rows = []
    for station, address, offset in [("A", "주소 A", 0.0), ("B", "주소 B", 1.0)]:
        for index, timestamp in enumerate(raw_times):
            rows.append(
                {
                    "지역": "서울",
                    "망": "도시대기",
                    "측정소코드": station,
                    "측정소명": station,
                    "측정일시": timestamp,
                    "PM2.5": 20 + offset + np.sin(index / 4),
                    "주소": address,
                }
            )
    pd.DataFrame(rows).to_excel(source, index=False)
    archive_path = archive_dir / "airkorea_hourly_finalized_2024.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.write(source, arcname="2024-01.xlsx")

    canonical_dir = tmp_path / "canonical"
    canonical_manifest = canonicalize_archives(
        archive_dir=archive_dir,
        output_dir=canonical_dir,
    )
    canonical_metadata = json.loads(canonical_manifest.read_text())
    assert canonical_metadata["total_rows"] == 96

    registry = tmp_path / "registry.csv"
    pd.DataFrame(
        {
            "station_name": ["A", "B"],
            "address": ["주소 A", "주소 B"],
            "latitude": [37.50, 37.51],
            "longitude": [127.00, 127.01],
            "network_name": ["도시대기", "도시대기"],
            "installation_year": [2000, 2000],
            "pollutants_reported": ["PM2.5", "PM2.5"],
            "registry_retrieved_at_utc": ["2026-01-01", "2026-01-01"],
        }
    ).to_csv(registry, index=False)
    crosswalk = tmp_path / "crosswalk.csv"
    attributes_parquet = tmp_path / "attributes.parquet"
    attributes_csv = tmp_path / "attributes.csv"
    attributes = build_monitor_attributes(
        canonical_dir=canonical_dir,
        registry_path=registry,
        interim_crosswalk_path=crosswalk,
        attributes_parquet_path=attributes_parquet,
        attributes_csv_path=attributes_csv,
    )
    assert len(attributes) == 2
    assert attributes["latitude"].notna().all()

    config_path = _config(tmp_path / "config.yml")
    final_dir = tmp_path / "final_qc"
    final_manifest = clean_qc_partitions(
        canonical_dir=canonical_dir,
        attributes_path=attributes_parquet,
        output_dir=final_dir,
        config_path=config_path,
        pollutants={"PM25"},
    )
    final_metadata = json.loads(final_manifest.read_text())
    assert final_metadata["total_rows"] == 96
    clean_output = pd.read_parquet(
        next((final_dir / "year=2024" / "pollutant=PM25").glob("*.parquet"))
    )
    assert "source_record_id" in clean_output.columns
    assert not {"region", "address", "station_name"}.intersection(clean_output.columns)

    aggregate_dir = tmp_path / "aggregates"
    annual_path = tmp_path / "annual.parquet"
    aggregate_qc_partitions(
        final_qc_dir=final_dir,
        aggregate_dir=aggregate_dir,
        attributes_path=attributes_parquet,
        config_path=config_path,
        monthly_raw_path=tmp_path / "monthly_raw.parquet",
        monthly_qc_path=tmp_path / "monthly_qc.parquet",
        annual_parquet_path=annual_path,
        annual_csv_path=tmp_path / "annual.csv",
    )
    annual = pd.read_parquet(annual_path)
    assert len(annual) == 2
    assert not annual["analysis_ready"].any()
    assert annual["expected_days"].eq(366).all()


def test_aggregate_qc_partitions_preserves_prior_years_on_filtered_rerun(
    tmp_path: Path,
) -> None:
    archive_dir = tmp_path / "raw"
    archive_dir.mkdir()
    for year in (2024, 2025):
        raw_times = [f"{year}01{day:02d}{hour:02d}" for day in (1, 2) for hour in range(1, 25)]
        rows = [
            {
                "지역": "서울",
                "망": "도시대기",
                "측정소코드": "A",
                "측정소명": "A",
                "측정일시": timestamp,
                "PM2.5": 20 + np.sin(index / 4),
                "주소": "주소 A",
            }
            for index, timestamp in enumerate(raw_times)
        ]
        source = tmp_path / f"source_{year}.xlsx"
        pd.DataFrame(rows).to_excel(source, index=False)
        archive_path = archive_dir / f"airkorea_hourly_finalized_{year}.zip"
        with ZipFile(archive_path, "w") as archive:
            archive.write(source, arcname=f"{year}-01.xlsx")

    canonical_dir = tmp_path / "canonical"
    canonicalize_archives(archive_dir=archive_dir, output_dir=canonical_dir)

    registry = tmp_path / "registry.csv"
    pd.DataFrame(
        {
            "station_name": ["A"],
            "address": ["주소 A"],
            "latitude": [37.50],
            "longitude": [127.00],
            "network_name": ["도시대기"],
            "installation_year": [2000],
            "pollutants_reported": ["PM2.5"],
            "registry_retrieved_at_utc": ["2026-01-01"],
        }
    ).to_csv(registry, index=False)
    attributes_parquet = tmp_path / "attributes.parquet"
    build_monitor_attributes(
        canonical_dir=canonical_dir,
        registry_path=registry,
        interim_crosswalk_path=tmp_path / "crosswalk.csv",
        attributes_parquet_path=attributes_parquet,
        attributes_csv_path=tmp_path / "attributes.csv",
    )

    config_path = _config(tmp_path / "config.yml")
    final_dir = tmp_path / "final_qc"
    clean_qc_partitions(
        canonical_dir=canonical_dir,
        attributes_path=attributes_parquet,
        output_dir=final_dir,
        config_path=config_path,
        pollutants={"PM25"},
    )

    aggregate_dir = tmp_path / "aggregates"
    annual_path = tmp_path / "annual.parquet"
    aggregate_kwargs = dict(
        final_qc_dir=final_dir,
        aggregate_dir=aggregate_dir,
        attributes_path=attributes_parquet,
        config_path=config_path,
        monthly_raw_path=tmp_path / "monthly_raw.parquet",
        monthly_qc_path=tmp_path / "monthly_qc.parquet",
        annual_parquet_path=annual_path,
        annual_csv_path=tmp_path / "annual.csv",
    )
    aggregate_qc_partitions(years={2024}, **aggregate_kwargs)
    aggregate_qc_partitions(years={2025}, **aggregate_kwargs)

    annual = pd.read_parquet(annual_path)
    assert sorted(annual["reporting_year"].unique().tolist()) == [2024, 2025]
