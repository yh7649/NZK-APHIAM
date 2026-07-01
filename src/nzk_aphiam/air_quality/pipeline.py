"""End-to-end hourly AirKorea QC and monthly sensitivity datasets."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pandas as pd
import yaml

from nzk_aphiam.air_quality.anomaly_model import ModelConfig, add_oof_predictions
from nzk_aphiam.air_quality.features import add_temporal_and_lag_features
from nzk_aphiam.air_quality.qc_rules import RuleConfig, apply_rule_flags
from nzk_aphiam.air_quality.spatial_validation import add_spatial_support
from nzk_aphiam.air_quality.station_crosswalk import (
    add_station_coordinates,
    build_station_crosswalk,
)
from nzk_aphiam.data.scrape.airkorea.stations import (
    DEFAULT_OUTPUT as DEFAULT_STATION_REGISTRY,
)
from nzk_aphiam.data.scrape.airkorea.stations import (
    fetch_registry,
    get_api_key,
    save_registry,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "air_quality_qc.yaml"
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "airkorea" / "hourly_finalized"
DEFAULT_INTERIM = PROJECT_ROOT / "data" / "interim" / "air_quality"
DEFAULT_PROCESSED = PROJECT_ROOT / "data" / "processed" / "air_quality"
DEFAULT_CROSSWALK = DEFAULT_INTERIM / "airkorea_station_crosswalk.csv"

POLLUTANT_ALIASES = {
    "SO2": "SO2",
    "아황산가스": "SO2",
    "CO": "CO",
    "일산화탄소": "CO",
    "O3": "O3",
    "오존": "O3",
    "NO2": "NO2",
    "이산화질소": "NO2",
    "PM10": "PM10",
    "미세먼지": "PM10",
    "PM25": "PM25",
    "PM2.5": "PM25",
    "초미세먼지": "PM25",
}


def _clean_label(value: object) -> str:
    return str(value).strip().upper().replace("㎍/㎥", "").replace("PPM", "").replace(" ", "")


def _parse_airkorea_datetime(values: pd.Series) -> pd.Series:
    """Parse AirKorea's YYYYMMDDHH convention, including hour 24."""
    text = values.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    compact = text.str.fullmatch(r"\d{10}")
    hour = pd.to_numeric(text.str[-2:], errors="coerce")
    base = pd.to_datetime(text.str[:8].where(compact), format="%Y%m%d", errors="coerce")
    parsed_compact = base + pd.to_timedelta(hour.where(hour.le(24)), unit="h")
    parsed_other = pd.to_datetime(text.where(~compact), errors="coerce")
    return parsed_compact.where(compact, parsed_other)


def standardize_airkorea_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert common Korean/English AirKorea wide columns to the canonical long schema."""
    original = {_clean_label(column): column for column in frame.columns}

    def find(*aliases: str, required: bool = True) -> object | None:
        for alias in aliases:
            cleaned = _clean_label(alias)
            if cleaned in original:
                return original[cleaned]
        if required:
            raise ValueError(f"AirKorea workbook is missing a column matching {aliases}")
        return None

    station = find("측정소코드", "측정소 코드", "station_code", required=False)
    station_name = find("측정소명", "측정소", "station_name", required=station is None)
    datetime_column = find("측정일시", "측정 일시", "측정시간", "datetime")
    pollutant_columns: dict[object, str] = {}
    for column in frame.columns:
        label = _clean_label(column).replace("PM2.5", "PM25")
        for alias, canonical in POLLUTANT_ALIASES.items():
            if label == _clean_label(alias).replace("PM2.5", "PM25") or label.startswith(
                _clean_label(alias).replace("PM2.5", "PM25") + "("
            ):
                pollutant_columns[column] = canonical
                break
    if not pollutant_columns:
        raise ValueError("AirKorea workbook contains no recognized pollutant columns")

    identity = [datetime_column, station or station_name]
    optional_aliases = {
        "station_name": ("측정소명", "측정소", "station_name"),
        "address": ("주소", "측정소주소", "address"),
        "latitude": ("위도", "latitude", "lat"),
        "longitude": ("경도", "longitude", "lon"),
    }
    optional: dict[str, object] = {}
    for canonical, aliases in optional_aliases.items():
        column = find(*aliases, required=False)
        if column is not None and column not in identity:
            optional[canonical] = column
            identity.append(column)

    long = frame[identity + list(pollutant_columns)].melt(
        id_vars=identity, var_name="source_pollutant", value_name="value_raw"
    )
    rename = {datetime_column: "datetime", station or station_name: "monitor_id"}
    rename.update({column: canonical for canonical, column in optional.items()})
    long = long.rename(columns=rename)
    long["pollutant"] = long["source_pollutant"].map(pollutant_columns)
    long["monitor_id"] = long["monitor_id"].astype("string").str.strip()
    long["datetime"] = _parse_airkorea_datetime(long["datetime"])
    long["value_raw"] = pd.to_numeric(long["value_raw"], errors="coerce")
    return long.drop(columns="source_pollutant")


def read_airkorea_zip(path: Path) -> pd.DataFrame:
    """Read every XLSX member from an annual AirKorea ZIP without altering the archive."""
    frames: list[pd.DataFrame] = []
    with TemporaryDirectory(prefix="airkorea_") as temporary, ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.lower().endswith(".xlsx"):
                continue
            extracted = Path(archive.extract(member, temporary))
            raw = pd.read_excel(extracted)
            standardized = standardize_airkorea_frame(raw)
            standardized["source_archive"] = path.name
            standardized["source_member"] = member.filename
            frames.append(standardized)
    if not frames:
        raise ValueError(f"No XLSX workbooks found in {path}")
    return pd.concat(frames, ignore_index=True)


@dataclass
class AirQualityQCPipeline:
    rule_config: RuleConfig = field(default_factory=RuleConfig)
    model_config: ModelConfig = field(default_factory=ModelConfig)
    radius_km: float = 25.0
    spatial_support_z: float = 3.0
    minimum_neighbors: int = 1

    @classmethod
    def from_yaml(cls, path: Path = DEFAULT_CONFIG) -> "AirQualityQCPipeline":
        settings = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules = settings.get("rules", {})
        if "bounds" in rules:
            rules["bounds"] = {key: tuple(value) for key, value in rules["bounds"].items()}
        if "missing_sentinels" in rules:
            rules["missing_sentinels"] = tuple(rules["missing_sentinels"])
        model = settings.get("model", {})
        spatial = settings.get("spatial", {})
        return cls(
            rule_config=RuleConfig(**rules),
            model_config=ModelConfig(**model),
            radius_km=spatial.get("radius_km", 25.0),
            spatial_support_z=spatial.get("support_robust_z", 3.0),
            minimum_neighbors=spatial.get("minimum_neighbors", 1),
        )

    def run(self, hourly: pd.DataFrame) -> pd.DataFrame:
        """Run rule QC, RF residual detection, and spatial confirmation."""
        checked = apply_rule_flags(hourly, self.rule_config)
        featured, numeric, categorical = add_temporal_and_lag_features(checked)
        predicted = add_oof_predictions(featured, numeric, categorical, self.model_config)
        result = add_spatial_support(
            predicted, self.radius_km, self.spatial_support_z, self.minimum_neighbors
        )
        hard_invalid = result["flag_missing"] | result["flag_impossible"]
        unsupported_anomaly = (
            result["flag_ml"]
            & result["spatial_validation_available"]
            & ~result["flag_spatially_supported"]
        )
        unconfirmed_anomaly = result["flag_ml"] & ~result["spatial_validation_available"]
        result["qc_status"] = "pass"
        result.loc[result["flag_flatline"] | result["flag_jump"], "qc_status"] = "rule_review"
        result.loc[result["flag_ml"] & result["flag_spatially_supported"], "qc_status"] = (
            "supported_event"
        )
        result.loc[unconfirmed_anomaly, "qc_status"] = "ml_review"
        result.loc[unsupported_anomaly, "qc_status"] = "sensor_anomaly"
        result.loc[hard_invalid, "qc_status"] = "invalid"
        result["value_analysis"] = result["value_raw"].mask(hard_invalid | unsupported_anomaly)
        preferred = [
            "monitor_id",
            "datetime",
            "pollutant",
            "value_raw",
            "value_expected",
            "model_residual",
            "residual_robust_z",
            "flag_rule",
            "flag_ml",
            "flag_spatially_supported",
            "qc_status",
            "value_analysis",
        ]
        return result[preferred + [column for column in result if column not in preferred]]


def monthly_aggregates(hourly_qc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build parallel raw and QC monthly monitor-pollutant datasets."""
    data = hourly_qc.copy()
    data["month"] = data["datetime"].dt.to_period("M").dt.to_timestamp()
    keys = ["monitor_id", "month", "pollutant"]
    raw = (
        data.groupby(keys, observed=True)["value_raw"]
        .agg(value="mean", hours="count")
        .reset_index()
    )
    qc = (
        data.groupby(keys, observed=True)["value_analysis"]
        .agg(value="mean", hours="count")
        .reset_index()
    )
    return raw, qc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run auditable QC on AirKorea hourly archives.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--years", type=int, nargs="+")
    parser.add_argument("--interim-dir", type=Path, default=DEFAULT_INTERIM)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--station-registry", type=Path, default=DEFAULT_STATION_REGISTRY)
    parser.add_argument(
        "--historical-stations",
        type=Path,
        help="Optional CSV transcribed from annual-report station appendices, keyed by monitor_id/year.",
    )
    parser.add_argument(
        "--refresh-stations", action="store_true", help="Refresh the current data.go.kr registry."
    )
    args = parser.parse_args()
    archives = sorted(args.input_dir.glob("*.zip"))
    if args.years:
        archives = [
            path for path in archives if any(str(year) in path.stem for year in args.years)
        ]
    if not archives:
        parser.error("No complete ZIP archives matched the requested input")
    hourly = pd.concat([read_airkorea_zip(path) for path in archives], ignore_index=True)
    if args.refresh_stations or not args.station_registry.exists():
        registry = fetch_registry(get_api_key())
        save_registry(registry, args.station_registry, overwrite=args.station_registry.exists())
    else:
        registry = pd.read_csv(args.station_registry, dtype={"station_name": "string"})
    historical = pd.read_csv(args.historical_stations) if args.historical_stations else None
    crosswalk = build_station_crosswalk(hourly, registry, historical)
    hourly_with_coordinates = add_station_coordinates(hourly, crosswalk)
    args.interim_dir.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(args.interim_dir / DEFAULT_CROSSWALK.name, index=False, encoding="utf-8-sig")
    output = AirQualityQCPipeline.from_yaml(args.config).run(hourly_with_coordinates)
    raw_monthly, qc_monthly = monthly_aggregates(output)
    args.processed_dir.mkdir(parents=True, exist_ok=True)
    output.to_parquet(args.interim_dir / "air_quality_hourly_qc.parquet", index=False)
    raw_monthly.to_parquet(args.processed_dir / "air_quality_monthly_raw.parquet", index=False)
    qc_monthly.to_parquet(args.processed_dir / "air_quality_monthly_qc.parquet", index=False)


if __name__ == "__main__":
    main()
