"""Build analysis-ready KMA meteorology and upper-air dispersion features.

Outputs remain partitioned by year so a single new year does not rewrite the
entire historical dataset. No weather observations are interpolated or imputed.
Radiosonde-derived mixing height uses the documented HYSPLIT potential-
temperature method: the first level at least 2 K warmer in potential temperature
than the profile minimum. It is an estimate at sounding time, not a directly
observed KMA variable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from nzk_aphiam.config.paths import WEATHER_PROCESSED_DIR, WEATHER_RAW_DIR

SURFACE_RENAME = {
    "TM": "timestamp_kst",
    "STN": "station_id",
    "WD": "wind_direction_deg",
    "WS": "wind_speed_m_s",
    "GST_WD": "gust_direction_deg",
    "GST_WS": "gust_speed_m_s",
    "PA": "station_pressure_hpa",
    "PS": "sea_level_pressure_hpa",
    "TA": "temperature_c",
    "TD": "dew_point_c",
    "HM": "relative_humidity_pct",
    "PV": "vapor_pressure_hpa",
    "RN": "precipitation_mm",
    "RN_DAY": "daily_precipitation_mm",
    "RN_INT": "precipitation_intensity_mm_h",
    "CA_TOT": "total_cloud_tenths",
    "CA_MID": "mid_low_cloud_tenths",
    "CH_MIN": "lowest_cloud_height_100m",
    "VS": "visibility_10m",
    "SS": "sunshine_hours",
    "SI": "solar_radiation_mj_m2",
}

SURFACE_RANGES = {
    "wind_direction_deg": (0, 360),
    "wind_speed_m_s": (0, 150),
    "gust_direction_deg": (0, 360),
    "gust_speed_m_s": (0, 150),
    "station_pressure_hpa": (500, 1100),
    "sea_level_pressure_hpa": (800, 1100),
    "temperature_c": (-90, 60),
    "dew_point_c": (-100, 60),
    "relative_humidity_pct": (0, 100),
    "vapor_pressure_hpa": (0, 100),
    "precipitation_mm": (0, 1000),
    "daily_precipitation_mm": (0, 3000),
    "precipitation_intensity_mm_h": (0, 1000),
    "total_cloud_tenths": (0, 10),
    "mid_low_cloud_tenths": (0, 10),
    "lowest_cloud_height_100m": (0, 300),
    "visibility_10m": (0, 1_000_000),
    "sunshine_hours": (0, 1),
    "solar_radiation_mj_m2": (0, 10),
}


def bounded_numeric(series: pd.Series, minimum: float, maximum: float) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.where(values.between(minimum, maximum))


def wind_components(speed: pd.Series, direction_degrees: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Convert meteorological 'from' direction into eastward/northward components."""
    radians = np.deg2rad(direction_degrees)
    return -speed * np.sin(radians), -speed * np.cos(radians)


def _timestamp_strings(series: pd.Series, source_timezone: str) -> tuple[pd.Series, pd.Series]:
    timestamps = pd.to_datetime(series, format="%Y%m%d%H%M", errors="coerce")
    if timestamps.isna().any():
        raise ValueError("KMA data contain invalid timestamps; raw snapshot was not normalized.")
    localized = timestamps.dt.tz_localize(source_timezone)
    return localized.astype("string"), localized.dt.tz_convert("UTC").astype("string")


def normalize_surface(raw: pd.DataFrame) -> pd.DataFrame:
    required = set(SURFACE_RENAME)
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"KMA surface snapshot is missing columns: {missing}")
    data = raw.rename(columns=SURFACE_RENAME).copy()
    data["timestamp_kst"], data["timestamp_utc"] = _timestamp_strings(
        data["timestamp_kst"], "Asia/Seoul"
    )
    data["station_id"] = data["station_id"].astype("string")
    for column, (minimum, maximum) in SURFACE_RANGES.items():
        data[column] = bounded_numeric(data[column], minimum, maximum)
    data["lowest_cloud_base_m"] = data["lowest_cloud_height_100m"] * 100
    data["visibility_m"] = data["visibility_10m"] * 10
    data["is_precipitating"] = data["precipitation_mm"].gt(0).astype("boolean")
    data.loc[data["precipitation_mm"].isna(), "is_precipitating"] = pd.NA
    data["wind_u_m_s"], data["wind_v_m_s"] = wind_components(
        data["wind_speed_m_s"], data["wind_direction_deg"]
    )
    columns = [
        "timestamp_utc",
        "timestamp_kst",
        "station_id",
        "temperature_c",
        "dew_point_c",
        "relative_humidity_pct",
        "station_pressure_hpa",
        "sea_level_pressure_hpa",
        "vapor_pressure_hpa",
        "precipitation_mm",
        "daily_precipitation_mm",
        "precipitation_intensity_mm_h",
        "is_precipitating",
        "solar_radiation_mj_m2",
        "sunshine_hours",
        "total_cloud_tenths",
        "mid_low_cloud_tenths",
        "lowest_cloud_base_m",
        "visibility_m",
        "wind_direction_deg",
        "wind_speed_m_s",
        "wind_u_m_s",
        "wind_v_m_s",
        "gust_direction_deg",
        "gust_speed_m_s",
    ]
    return data[columns].sort_values(["timestamp_utc", "station_id"], kind="stable")


def potential_temperature_k(temperature_c: pd.Series, pressure_hpa: pd.Series) -> pd.Series:
    return (temperature_c + 273.15) * (1000.0 / pressure_hpa) ** 0.286


def normalize_radiosonde(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"TM", "STN", "LAT", "LON", "PA", "GH", "TA", "TD", "WD", "WS", "FLAG"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"KMA radiosonde snapshot is missing columns: {missing}")
    data = raw.rename(
        columns={
            "TM": "timestamp_utc",
            "STN": "station_id",
            "LAT": "latitude",
            "LON": "longitude",
            "PA": "pressure_hpa",
            "GH": "height_m",
            "TA": "temperature_c",
            "TD": "dew_point_c",
            "WD": "wind_direction_deg",
            "WS": "wind_speed_m_s",
            "FLAG": "level_flags",
        }
    ).copy()
    data["timestamp_utc"], _ = _timestamp_strings(data["timestamp_utc"], "UTC")
    data["station_id"] = data["station_id"].astype("string")
    ranges = {
        "latitude": (-90, 90),
        "longitude": (-180, 180),
        "pressure_hpa": (0.1, 1100),
        "height_m": (-500, 50_000),
        "temperature_c": (-110, 60),
        "dew_point_c": (-120, 60),
        "wind_direction_deg": (0, 360),
        "wind_speed_m_s": (0, 200),
    }
    for column, bounds in ranges.items():
        data[column] = bounded_numeric(data[column], *bounds)
    data["potential_temperature_k"] = potential_temperature_k(
        data["temperature_c"], data["pressure_hpa"]
    )
    data["wind_u_m_s"], data["wind_v_m_s"] = wind_components(
        data["wind_speed_m_s"], data["wind_direction_deg"]
    )
    return data.sort_values(["timestamp_utc", "station_id", "height_m"], kind="stable")


def summarize_sounding(profile: pd.DataFrame) -> dict[str, object]:
    valid = profile.dropna(subset=["height_m", "potential_temperature_k"]).copy()
    valid = valid.sort_values("height_m").drop_duplicates("height_m")
    result: dict[str, object] = {
        "mixing_height_agl_m": math.nan,
        "surface_inversion": pd.NA,
        "inversion_base_agl_m": math.nan,
        "inversion_top_agl_m": math.nan,
        "inversion_strength_k": math.nan,
        "potential_temperature_gradient_0_500m_k_m": math.nan,
        "profile_level_count": len(valid),
    }
    if len(valid) < 2:
        return result
    surface_height = float(valid["height_m"].iloc[0])
    valid["height_agl_m"] = valid["height_m"] - surface_height
    minimum_index = valid["potential_temperature_k"].idxmin()
    theta_min = float(valid.loc[minimum_index, "potential_temperature_k"])
    minimum_height = float(valid.loc[minimum_index, "height_agl_m"])
    candidates = valid.loc[
        (valid["height_agl_m"] > minimum_height)
        & (valid["potential_temperature_k"] >= theta_min + 2.0)
    ]
    if not candidates.empty:
        result["mixing_height_agl_m"] = float(candidates["height_agl_m"].iloc[0])

    theta0 = float(valid["potential_temperature_k"].iloc[0])
    above = valid.loc[valid["height_agl_m"] > 0].copy()
    above["mean_gradient"] = (above["potential_temperature_k"] - theta0) / above["height_agl_m"]
    inversion = above.loc[
        (above["potential_temperature_k"] - theta0 >= 2.0) & (above["mean_gradient"] >= 0.005)
    ]
    result["surface_inversion"] = not inversion.empty
    if not inversion.empty:
        top = inversion.iloc[0]
        result["inversion_base_agl_m"] = 0.0
        result["inversion_top_agl_m"] = float(top["height_agl_m"])
        result["inversion_strength_k"] = float(top["potential_temperature_k"] - theta0)

    low = valid.loc[valid["height_agl_m"].between(0, 500)]
    if len(low) >= 2 and low["height_agl_m"].nunique() >= 2:
        gradient = np.polyfit(low["height_agl_m"], low["potential_temperature_k"], 1)[0]
        result["potential_temperature_gradient_0_500m_k_m"] = float(gradient)
    return result


def derive_sounding_features(profile: pd.DataFrame) -> pd.DataFrame:
    keys = ["timestamp_utc", "station_id"]
    records = []
    for values, group in profile.groupby(keys, dropna=False, sort=True):
        record = dict(zip(keys, values, strict=True))
        record.update(summarize_sounding(group))
        records.append(record)
    return pd.DataFrame(records)


def normalize_stability(raw: pd.DataFrame) -> pd.DataFrame:
    if "TM" not in raw or "STN" not in raw:
        raise ValueError("KMA stability snapshot must contain TM and STN.")
    data = raw.rename(columns={"TM": "timestamp_utc", "STN": "station_id"}).copy()
    data = data.rename(
        columns={
            column: column.lower()
            for column in data.columns
            if column not in {"timestamp_utc", "station_id"}
        }
    )
    data = data.rename(columns={"wd": "wind_direction_deg", "ws": "wind_speed_kt"})
    data["timestamp_utc"], _ = _timestamp_strings(data["timestamp_utc"], "UTC")
    data["station_id"] = data["station_id"].astype("string")
    for column in data.columns:
        if column not in {"timestamp_utc", "station_id", "cloud"}:
            data[column] = pd.to_numeric(data[column], errors="coerce")
            data.loc[data[column].abs().ge(9000), column] = np.nan
    physical_ranges = {
        "hm": (0, 100),
        "wind_direction_deg": (0, 360),
        "wind_speed_kt": (0, 400),
        "fl": (0, 30_000),
        "tp": (0, 30_000),
        "lcl": (0, 30_000),
        "ccl": (0, 30_000),
        "lfc": (0, 30_000),
        "hel": (0, 30_000),
        "mw": (0, 30_000),
        "cape": (0, 20_000),
        "tpw": (0, 500),
        "upress": (0, 1100),
        "mpress": (0, 1100),
        "lpress": (0, 1100),
    }
    for column, bounds in physical_ranges.items():
        data[column] = data[column].where(data[column].between(*bounds))
    data["wind_speed_m_s"] = data["wind_speed_kt"] * 0.514444
    return data.sort_values(["timestamp_utc", "station_id"], kind="stable")


def normalize_profiler(raw: pd.DataFrame) -> pd.DataFrame:
    data = raw.rename(
        columns={
            "TM": "timestamp_utc",
            "STN": "station_id",
            "HT": "height_m",
            "WD": "wind_direction_deg",
            "WS": "wind_speed_m_s",
            "U": "wind_u_m_s",
            "V": "wind_v_m_s",
            "W": "vertical_wind_m_s",
            "QC": "quality_code",
        }
    ).copy()
    data["timestamp_utc"], _ = _timestamp_strings(data["timestamp_utc"], "UTC")
    data["station_id"] = data["station_id"].astype("string")
    ranges = {
        "height_m": (0, 20_000),
        "wind_direction_deg": (0, 360),
        "wind_speed_m_s": (0, 200),
        "wind_u_m_s": (-200, 200),
        "wind_v_m_s": (-200, 200),
        "vertical_wind_m_s": (-100, 100),
    }
    for column, bounds in ranges.items():
        data[column] = bounded_numeric(data[column], *bounds)
    return data.sort_values(["timestamp_utc", "station_id", "height_m"], kind="stable")


def normalize_stations(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"SNAPSHOT_YEAR", "STATION_TYPE", "STN_ID", "LON", "LAT"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"KMA station snapshot is missing columns: {missing}")
    data = raw.rename(
        columns={
            "SNAPSHOT_YEAR": "snapshot_year",
            "STATION_TYPE": "station_type",
            "STN_ID": "station_id",
            "LON": "longitude",
            "LAT": "latitude",
            "HT": "station_elevation_m",
            "HT_WD": "wind_sensor_height_m",
            "STN_KO": "station_name_ko",
            "STN_EN": "station_name_en",
            "LAW_ID": "legal_district_code",
            "OBS_START": "observation_start_utc",
            "OBS_END": "observation_end_utc",
        }
    ).copy()
    data["snapshot_year"] = pd.to_numeric(data["snapshot_year"], errors="raise").astype(int)
    data["station_id"] = data["station_id"].astype("string")
    data["longitude"] = bounded_numeric(data["longitude"], -180, 180)
    data["latitude"] = bounded_numeric(data["latitude"], -90, 90)
    data["station_elevation_m"] = bounded_numeric(data["station_elevation_m"], -500, 5000)
    data["wind_sensor_height_m"] = bounded_numeric(data["wind_sensor_height_m"], 0, 500)
    columns = [
        "snapshot_year",
        "station_type",
        "station_id",
        "station_name_ko",
        "station_name_en",
        "latitude",
        "longitude",
        "station_elevation_m",
        "wind_sensor_height_m",
        "legal_district_code",
        "observation_start_utc",
        "observation_end_utc",
    ]
    return data[columns].sort_values(["station_type", "station_id"], kind="stable")


def _read_raw(raw_dir: Path, dataset: str, year: int) -> pd.DataFrame | None:
    path = raw_dir / dataset / f"{dataset}.source.{year}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, encoding="utf-8-sig", dtype="string", low_memory=False)


def _save(frame: pd.DataFrame, output_dir: Path, dataset: str, year: int) -> Path:
    directory = output_dir / dataset
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{dataset}.{year}.csv"
    partial = path.with_suffix(".csv.part")
    frame.to_csv(partial, index=False, encoding="utf-8-sig")
    partial.replace(path)
    return path


def add_station_location(
    observations: pd.DataFrame, stations: pd.DataFrame | None, station_type: str
) -> pd.DataFrame:
    if stations is None or stations.empty:
        return observations
    lookup = stations.loc[
        stations["station_type"].eq(station_type),
        [
            "station_id",
            "station_name_ko",
            "station_name_en",
            "latitude",
            "longitude",
            "station_elevation_m",
        ],
    ].drop_duplicates("station_id")
    lookup = lookup.rename(
        columns={
            "latitude": "station_latitude",
            "longitude": "station_longitude",
        }
    )
    return observations.merge(lookup, on="station_id", how="left", validate="many_to_one")


def process_year(raw_dir: Path, output_dir: Path, year: int) -> list[dict[str, object]]:
    outputs = []
    stations = _read_raw(raw_dir, "stations", year)
    station_history = None
    if stations is not None:
        station_history = normalize_stations(stations)
        path = _save(station_history, output_dir, "station_history", year)
        outputs.append(
            {
                "dataset": "station_history",
                "year": year,
                "rows": len(station_history),
                "path": str(path),
            }
        )

    surface = _read_raw(raw_dir, "surface", year)
    if surface is not None:
        normalized = normalize_surface(surface)
        normalized = add_station_location(normalized, station_history, "SFC")
        path = _save(normalized, output_dir, "surface_hourly", year)
        outputs.append(
            {"dataset": "surface_hourly", "year": year, "rows": len(normalized), "path": str(path)}
        )

    radiosonde = _read_raw(raw_dir, "radiosonde", year)
    if radiosonde is not None:
        profile = normalize_radiosonde(radiosonde)
        profile = add_station_location(profile, station_history, "UPP")
        path = _save(profile, output_dir, "radiosonde_profile", year)
        outputs.append(
            {
                "dataset": "radiosonde_profile",
                "year": year,
                "rows": len(profile),
                "path": str(path),
            }
        )
        derived = derive_sounding_features(profile)
        path = _save(derived, output_dir, "upper_air_dispersion", year)
        outputs.append(
            {
                "dataset": "upper_air_dispersion",
                "year": year,
                "rows": len(derived),
                "path": str(path),
            }
        )

    stability = _read_raw(raw_dir, "stability", year)
    if stability is not None:
        normalized = normalize_stability(stability)
        path = _save(normalized, output_dir, "stability_indices", year)
        outputs.append(
            {
                "dataset": "stability_indices",
                "year": year,
                "rows": len(normalized),
                "path": str(path),
            }
        )

    profiler = _read_raw(raw_dir, "profiler", year)
    if profiler is not None:
        normalized = normalize_profiler(profiler)
        normalized = add_station_location(normalized, station_history, "WPF")
        path = _save(normalized, output_dir, "profiler_wind", year)
        outputs.append(
            {"dataset": "profiler_wind", "year": year, "rows": len(normalized), "path": str(path)}
        )
    return outputs


def process(
    raw_dir: Path, output_dir: Path, start_year: int, end_year: int
) -> list[dict[str, object]]:
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")
    outputs = []
    for year in range(start_year, end_year + 1):
        year_outputs = process_year(raw_dir, output_dir, year)
        outputs.extend(year_outputs)
        for item in year_outputs:
            print(f"{item['dataset']} {year}: {item['rows']:,} rows -> {item['path']}")
    metadata = {
        "dataset": "KMA meteorology normalized for air-pollution dispersion modeling",
        "built_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "no_imputation": True,
        "surface_timestamp_source": "KST converted to UTC; both retained",
        "upper_air_timestamp_source": "UTC",
        "mixing_height_method": (
            "First sounding level where potential temperature is at least 2 K above the "
            "profile minimum; estimate at sounding time, not a directly observed KMA field."
        ),
        "surface_inversion_method": (
            "First layer at least 2 K warmer than the surface with mean potential-temperature "
            "gradient at least 0.005 K/m."
        ),
        "outputs": outputs,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "metadata.json"
    partial = path.with_suffix(".json.part")
    partial.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(path)

    save_local_readme(build_local_readme(outputs, start_year, end_year), output_dir / "README.md")
    return outputs


def build_local_readme(outputs: list[dict[str, object]], start_year: int, end_year: int) -> str:
    """Render current-value coverage matching the placeholders in
    docs/datasets/kma_weather.md, so the local snapshot tracks whatever this
    processing run just produced.
    """
    by_dataset: dict[str, dict[str, object]] = {}
    for item in outputs:
        entry = by_dataset.setdefault(str(item["dataset"]), {"rows": 0, "years": set()})
        entry["rows"] += item["rows"]
        entry["years"].add(item["year"])

    lines = []
    for dataset in sorted(by_dataset):
        entry = by_dataset[dataset]
        years = sorted(entry["years"])
        year_range = f"{years[0]}-{years[-1]}" if years else "none"
        lines.append(f"- `{dataset}`: `{entry['rows']:,}` rows across {year_range}")

    return f"""# KMA Weather Dataset: Current Local Values

This local file records the current generated values for the partitioned
outputs under `data/processed/weather/kma/`.

The tracked dataset description is:

- `docs/datasets/kma_weather.md`

This folder is ignored by git, so these values are local snapshots. Running
`make process-kma-weather` regenerates this file every time it regenerates
the dataset, so it should never go stale relative to the data actually on
disk. This snapshot reflects the last processed range, `{start_year}-{end_year}`;
existing years outside that range keep their own annual files but are not
recounted here unless reprocessed.

## Current Coverage

Rows by processed dataset (summed across annual partitions from this run):

{chr(10).join(lines)}

## Refresh

These values are written automatically by:

```bash
make process-kma-weather
```
"""


def save_local_readme(readme_text: str, readme_path: Path) -> None:
    """Write the local current-values README, replacing it atomically."""
    partial = readme_path.with_suffix(".md.part")
    partial.write_text(readme_text, encoding="utf-8")
    partial.replace(readme_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize KMA observations and derive upper-air dispersion features."
    )
    parser.add_argument("--raw-dir", type=Path, default=WEATHER_RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=WEATHER_PROCESSED_DIR)
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year", type=int, default=2024)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    process(args.raw_dir, args.output_dir, args.start_year, args.end_year)
