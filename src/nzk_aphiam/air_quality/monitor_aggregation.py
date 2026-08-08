"""EPA-style temporal aggregation of quality-controlled AirKorea observations."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from nzk_aphiam.air_quality.monitor_attributes import DEFAULT_ATTRIBUTES_PARQUET
from nzk_aphiam.air_quality.monitor_qc import (
    DEFAULT_CONFIG,
    DEFAULT_FINAL_QC_DIR,
    _portable_path,
    _resolve_path,
)
from nzk_aphiam.config.paths import AIRKOREA_PROCESSED_DIR
from nzk_aphiam.data.scrape.airkorea.scraper import file_sha256

DEFAULT_AGGREGATE_DIR = AIRKOREA_PROCESSED_DIR / "aggregates"
DEFAULT_MONTHLY_RAW = AIRKOREA_PROCESSED_DIR / "air_quality_monthly_raw.parquet"
DEFAULT_MONTHLY_QC = AIRKOREA_PROCESSED_DIR / "air_quality_monthly_qc.parquet"
DEFAULT_ANNUAL_PARQUET = AIRKOREA_PROCESSED_DIR / "airkorea_annual_pm_monitor.parquet"
DEFAULT_ANNUAL_CSV = AIRKOREA_PROCESSED_DIR / "airkorea_annual_pm_monitor.csv"


@dataclass(frozen=True)
class AggregationConfig:
    daily_min_fraction: float = 0.75
    quarterly_min_fraction: float = 0.75
    required_valid_quarters: int = 4
    annual_pollutants: tuple[str, ...] = ("PM10", "PM25")


def load_aggregation_config(path: Path = DEFAULT_CONFIG) -> AggregationConfig:
    settings = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    values = settings.get("aggregation", {})
    if "annual_pollutants" in values:
        values["annual_pollutants"] = tuple(values["annual_pollutants"])
    config = AggregationConfig(**values)
    if not 0 < config.daily_min_fraction <= 1:
        raise ValueError("daily_min_fraction must be in (0, 1]")
    if not 0 < config.quarterly_min_fraction <= 1:
        raise ValueError("quarterly_min_fraction must be in (0, 1]")
    if not 1 <= config.required_valid_quarters <= 4:
        raise ValueError("required_valid_quarters must be between 1 and 4")
    return config


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    frame.to_csv(partial, index=False, encoding="utf-8-sig")
    partial.replace(path)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    frame.to_parquet(partial, index=False)
    partial.replace(path)


def _source_observation_timestamp(data: pd.DataFrame) -> pd.Series:
    """Translate AirKorea's hour-ending 01..24 convention to hour starts."""
    raw = data["measurement_datetime_raw"].astype("string").str.replace(r"\.0$", "", regex=True)
    compact = raw.str.fullmatch(r"\d{10}")
    source_hour = pd.to_numeric(raw.str[-2:], errors="coerce")
    hour_ending = compact & source_hour.between(1, 24)
    timestamp = pd.to_datetime(data["datetime"], errors="coerce")
    return timestamp - pd.to_timedelta(hour_ending.astype(int), unit="h")


def collapse_monitor_hours(data: pd.DataFrame) -> pd.DataFrame:
    """Collapse exact duplicate source rows to one monitor-hour observation."""
    frame = data.copy()
    frame["observation_timestamp"] = _source_observation_timestamp(frame)
    keys = [
        "reporting_year",
        "monitor_id",
        "observation_timestamp",
        "pollutant",
        "unit",
    ]
    collapsed = (
        frame.groupby(keys, observed=True, sort=False, dropna=False)
        .agg(
            value_raw=("value_raw", "mean"),
            value_analysis=("value_analysis", "mean"),
            source_row_count=("source_record_id", "size"),
            archive_provisional=("archive_provisional", "max"),
        )
        .reset_index()
    )
    collapsed["source_row_count"] = collapsed["source_row_count"].astype("Int64")
    return collapsed


def monthly_summaries(hourly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return source-shaped and final-QC monitor-month summaries."""
    data = collapse_monitor_hours(hourly)
    data["month"] = data["observation_timestamp"].dt.to_period("M").dt.to_timestamp()
    keys = ["reporting_year", "monitor_id", "month", "pollutant", "unit"]
    raw = (
        data.groupby(keys, observed=True, sort=False)
        .agg(
            value=("value_raw", "mean"),
            hours=("value_raw", "count"),
            hours_observed=("observation_timestamp", "count"),
            source_rows=("source_row_count", "sum"),
            archive_provisional=("archive_provisional", "max"),
        )
        .reset_index()
    )
    qc = (
        data.groupby(keys, observed=True, sort=False)
        .agg(
            value=("value_analysis", "mean"),
            hours=("value_analysis", "count"),
            hours_observed=("observation_timestamp", "count"),
            source_rows=("source_row_count", "sum"),
            archive_provisional=("archive_provisional", "max"),
        )
        .reset_index()
    )
    for result in (raw, qc):
        expected = result["month"].dt.days_in_month * 24
        result["hours_expected"] = expected.astype("Int64")
        result["hour_completeness"] = result["hours"] / result["hours_expected"]
    return raw, qc


def daily_pm_summaries(
    hourly: pd.DataFrame,
    config: AggregationConfig,
) -> pd.DataFrame:
    """Apply the 75%-of-hours rule to monitor-day PM means."""
    data = collapse_monitor_hours(hourly)
    data["date"] = data["observation_timestamp"].dt.normalize()
    data = data[data["date"].dt.year.eq(data["reporting_year"])].copy()
    keys = ["reporting_year", "monitor_id", "date", "pollutant", "unit"]
    daily = (
        data.groupby(keys, observed=True, sort=False)
        .agg(
            daily_mean_available=("value_analysis", "mean"),
            valid_hours=("value_analysis", "count"),
            observed_hours=("observation_timestamp", "count"),
            source_rows=("source_row_count", "sum"),
            archive_provisional=("archive_provisional", "max"),
        )
        .reset_index()
    )
    daily["expected_hours"] = 24
    daily["hour_completeness"] = daily["valid_hours"] / daily["expected_hours"]
    daily["daily_valid"] = daily["hour_completeness"].ge(config.daily_min_fraction)
    daily["daily_mean"] = daily["daily_mean_available"].where(daily["daily_valid"])
    return daily


def _days_in_quarter(year: int, quarter: int) -> int:
    months = range((quarter - 1) * 3 + 1, quarter * 3 + 1)
    return sum(calendar.monthrange(year, month)[1] for month in months)


def quarterly_pm_summaries(
    daily: pd.DataFrame,
    config: AggregationConfig,
) -> pd.DataFrame:
    """Apply quarterly valid-day completeness and calculate quarter means."""
    frame = daily.copy()
    frame["quarter"] = frame["date"].dt.quarter.astype("Int64")
    keys = ["reporting_year", "monitor_id", "quarter", "pollutant", "unit"]
    quarterly = (
        frame.groupby(keys, observed=True, sort=False)
        .agg(
            quarter_mean_available=("daily_mean", "mean"),
            valid_days=("daily_valid", "sum"),
            observed_days=("date", "count"),
            valid_hours=("valid_hours", "sum"),
            archive_provisional=("archive_provisional", "max"),
        )
        .reset_index()
    )
    identity_keys = ["reporting_year", "monitor_id", "pollutant", "unit"]
    identities = (
        frame.groupby(identity_keys, observed=True, sort=False)
        .agg(archive_provisional=("archive_provisional", "max"))
        .reset_index()
    )
    complete_grid = identities.merge(
        pd.DataFrame({"quarter": pd.Series([1, 2, 3, 4], dtype="Int64")}),
        how="cross",
    )
    quarterly = complete_grid.merge(
        quarterly.drop(columns="archive_provisional"),
        on=keys,
        how="left",
        validate="1:1",
    )
    for column in ("valid_days", "observed_days", "valid_hours"):
        quarterly[column] = quarterly[column].fillna(0).astype("Int64")
    quarterly["expected_days"] = [
        _days_in_quarter(int(year), int(quarter))
        for year, quarter in zip(
            quarterly["reporting_year"],
            quarterly["quarter"],
            strict=True,
        )
    ]
    quarterly["day_completeness"] = quarterly["valid_days"] / quarterly["expected_days"]
    quarterly["quarter_valid"] = quarterly["day_completeness"].ge(config.quarterly_min_fraction)
    quarterly["quarter_mean"] = quarterly["quarter_mean_available"].where(
        quarterly["quarter_valid"]
    )
    return quarterly


def annual_pm_summaries(
    daily: pd.DataFrame,
    quarterly: pd.DataFrame,
    config: AggregationConfig,
) -> pd.DataFrame:
    """Calculate equal-quarter annual PM means and strict analysis readiness."""
    keys = ["reporting_year", "monitor_id", "pollutant", "unit"]
    annual_quarter = (
        quarterly.groupby(keys, observed=True, sort=False)
        .agg(
            annual_mean_quarter_weighted_available=("quarter_mean", "mean"),
            valid_quarters=("quarter_valid", "sum"),
            valid_days=("valid_days", "sum"),
            expected_days=("expected_days", "sum"),
            archive_provisional=("archive_provisional", "max"),
        )
        .reset_index()
    )
    annual_daily = (
        daily.groupby(keys, observed=True, sort=False)
        .agg(
            annual_mean_valid_days_available=("daily_mean", "mean"),
            valid_hours=("valid_hours", "sum"),
        )
        .reset_index()
    )
    annual = annual_quarter.merge(annual_daily, on=keys, how="left", validate="1:1")
    annual["day_completeness"] = annual["valid_days"] / annual["expected_days"]
    annual["analysis_ready"] = annual["valid_quarters"].ge(
        config.required_valid_quarters
    ) & ~annual["archive_provisional"].astype(bool)
    annual["annual_mean"] = annual["annual_mean_quarter_weighted_available"].where(
        annual["analysis_ready"]
    )
    annual["aggregation_method"] = (
        "mean_of_valid_quarterly_means; "
        f"daily_requires_{config.daily_min_fraction:.0%}_hours; "
        f"quarter_requires_{config.quarterly_min_fraction:.0%}_days"
    )
    return annual


def _final_qc_fingerprint(manifest: dict[str, Any]) -> str:
    stable = [
        {
            "year": record["year"],
            "pollutant": record["pollutant"],
            "rows": record["rows"],
            "output": record["output"],
            "qc_status_counts": record.get("qc_status_counts", {}),
        }
        for record in manifest.get("partitions", [])
    ]
    return sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def _checkpoint_paths(
    aggregate_dir: Path,
    year: int,
    pollutant: str,
) -> dict[str, Path]:
    root = aggregate_dir / "partitions" / f"year={year}" / f"pollutant={pollutant}"
    return {
        "monthly_raw": root / "monthly_raw.parquet",
        "monthly_qc": root / "monthly_qc.parquet",
        "daily": root / "daily.parquet",
        "quarterly": root / "quarterly.parquet",
        "annual": root / "annual.parquet",
    }


def _merge_attributes(
    annual: pd.DataFrame,
    attributes_path: Path,
) -> pd.DataFrame:
    if not attributes_path.exists():
        raise FileNotFoundError(f"Monitor attribute table is absent: {attributes_path}")
    attributes = pd.read_parquet(attributes_path)
    attributes["monitor_id"] = attributes["monitor_id"].astype("string")
    annual = annual.copy()
    annual["monitor_id"] = annual["monitor_id"].astype("string")
    attributes = attributes.rename(columns={"year": "reporting_year"})
    return annual.merge(
        attributes,
        on=["monitor_id", "reporting_year"],
        how="left",
        validate="m:1",
    )


def aggregate_qc_partitions(
    *,
    final_qc_dir: Path = DEFAULT_FINAL_QC_DIR,
    aggregate_dir: Path = DEFAULT_AGGREGATE_DIR,
    attributes_path: Path = DEFAULT_ATTRIBUTES_PARQUET,
    config_path: Path = DEFAULT_CONFIG,
    monthly_raw_path: Path = DEFAULT_MONTHLY_RAW,
    monthly_qc_path: Path = DEFAULT_MONTHLY_QC,
    annual_parquet_path: Path = DEFAULT_ANNUAL_PARQUET,
    annual_csv_path: Path = DEFAULT_ANNUAL_CSV,
    years: set[int] | None = None,
    pollutants: set[str] | None = None,
    overwrite: bool = False,
) -> Path:
    """Build reusable monthly data and EPA-style annual monitor PM summaries."""
    final_manifest_path = final_qc_dir / "manifest.json"
    if not final_manifest_path.exists():
        raise FileNotFoundError(
            f"Final AirKorea QC manifest is absent: {final_manifest_path}; "
            "run the attributes stage first"
        )
    final_manifest = json.loads(final_manifest_path.read_text(encoding="utf-8"))
    fingerprint = _final_qc_fingerprint(final_manifest)
    config = load_aggregation_config(config_path)
    annual_pollutants = set(config.annual_pollutants)

    manifest_path = aggregate_dir / "manifest.json"
    prior_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    if (
        prior_manifest
        and not overwrite
        and (
            prior_manifest.get("final_qc_fingerprint") != fingerprint
            or prior_manifest.get("config_sha256") != file_sha256(config_path)
        )
    ):
        raise RuntimeError(
            "Existing AirKorea aggregates use different QC inputs or settings; "
            "rerun with --overwrite"
        )

    selected_partitions = [
        record
        for record in final_manifest.get("partitions", [])
        if (years is None or int(record["year"]) in years)
        and (pollutants is None or str(record["pollutant"]) in pollutants)
    ]
    if not selected_partitions:
        raise ValueError("No AirKorea QC partitions matched the aggregation request")

    partition_records = {
        (int(record["year"]), str(record["pollutant"])): record
        for record in prior_manifest.get("partitions", [])
    }
    for record in selected_partitions:
        year = int(record["year"])
        pollutant = str(record["pollutant"])
        paths = _checkpoint_paths(aggregate_dir, year, pollutant)
        required = [paths["monthly_raw"], paths["monthly_qc"]]
        if pollutant in annual_pollutants:
            required.extend([paths["daily"], paths["quarterly"], paths["annual"]])
        if not overwrite and all(path.exists() for path in required):
            status = "reused"
        else:
            hourly = pd.read_parquet(_resolve_path(str(record["output"])))
            monthly_raw, monthly_qc = monthly_summaries(hourly)
            _atomic_parquet(monthly_raw, paths["monthly_raw"])
            _atomic_parquet(monthly_qc, paths["monthly_qc"])
            if pollutant in annual_pollutants:
                daily = daily_pm_summaries(hourly, config)
                quarterly = quarterly_pm_summaries(daily, config)
                annual = annual_pm_summaries(daily, quarterly, config)
                _atomic_parquet(daily, paths["daily"])
                _atomic_parquet(quarterly, paths["quarterly"])
                _atomic_parquet(annual, paths["annual"])
            status = "written"
        partition_records[(year, pollutant)] = {
            "year": year,
            "pollutant": pollutant,
            "monthly_raw": _portable_path(paths["monthly_raw"]),
            "monthly_qc": _portable_path(paths["monthly_qc"]),
            "daily": (_portable_path(paths["daily"]) if pollutant in annual_pollutants else None),
            "quarterly": (
                _portable_path(paths["quarterly"]) if pollutant in annual_pollutants else None
            ),
            "annual": (
                _portable_path(paths["annual"]) if pollutant in annual_pollutants else None
            ),
            "status": status,
        }

    all_records = sorted(
        partition_records.values(), key=lambda item: (item["year"], item["pollutant"])
    )
    monthly_raw_parts = [
        pd.read_parquet(_resolve_path(record["monthly_raw"])) for record in all_records
    ]
    monthly_qc_parts = [
        pd.read_parquet(_resolve_path(record["monthly_qc"])) for record in all_records
    ]
    monthly_raw = pd.concat(monthly_raw_parts, ignore_index=True)
    monthly_qc = pd.concat(monthly_qc_parts, ignore_index=True)
    _atomic_parquet(monthly_raw, monthly_raw_path)
    _atomic_parquet(monthly_qc, monthly_qc_path)

    annual_parts = [
        pd.read_parquet(_resolve_path(record["annual"]))
        for record in all_records
        if record["annual"] is not None
    ]
    annual_rows = 0
    annual_ready = 0
    if annual_parts:
        annual = pd.concat(annual_parts, ignore_index=True)
        annual = _merge_attributes(annual, attributes_path)
        _atomic_parquet(annual, annual_parquet_path)
        _atomic_csv(annual, annual_csv_path)
        annual_rows = len(annual)
        annual_ready = int(annual["analysis_ready"].sum())

    payload = {
        "dataset": "AirKorea monthly and EPA-style annual monitor summaries",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_qc_fingerprint": fingerprint,
        "config": _portable_path(config_path),
        "config_sha256": file_sha256(config_path),
        "daily_min_fraction": config.daily_min_fraction,
        "quarterly_min_fraction": config.quarterly_min_fraction,
        "required_valid_quarters": config.required_valid_quarters,
        "annual_pollutants": list(config.annual_pollutants),
        "monthly_raw": _portable_path(monthly_raw_path),
        "monthly_qc": _portable_path(monthly_qc_path),
        "annual_monitor_pm": (_portable_path(annual_parquet_path) if annual_parts else None),
        "monthly_raw_rows": len(monthly_raw),
        "monthly_qc_rows": len(monthly_qc),
        "annual_rows": annual_rows,
        "annual_analysis_ready_rows": annual_ready,
        "partitions": all_records,
    }
    _atomic_json(manifest_path, payload)
    return manifest_path
