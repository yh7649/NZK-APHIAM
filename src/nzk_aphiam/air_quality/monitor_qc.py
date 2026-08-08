"""Partitioned rule, random-forest, and spatial QC for AirKorea monitors."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pandas as pd

from nzk_aphiam.air_quality.anomaly_model import add_oof_predictions
from nzk_aphiam.air_quality.features import add_temporal_and_lag_features
from nzk_aphiam.air_quality.monitor_attributes import DEFAULT_ATTRIBUTES_PARQUET
from nzk_aphiam.air_quality.monitor_canonical import (
    DEFAULT_OUTPUT_DIR as DEFAULT_CANONICAL_DIR,
)
from nzk_aphiam.air_quality.monitor_canonical import (
    POLLUTANT_UNITS,
    POLLUTANTS,
    _resolve_path,
    load_canonical_manifest,
)
from nzk_aphiam.air_quality.pipeline import AirQualityQCPipeline
from nzk_aphiam.air_quality.qc_rules import apply_rule_flags
from nzk_aphiam.air_quality.spatial_validation import add_spatial_support
from nzk_aphiam.air_quality.station_crosswalk import add_station_coordinates
from nzk_aphiam.config.paths import AIRKOREA_PROCESSED_DIR, PROJECT_ROOT
from nzk_aphiam.data.scrape.airkorea.scraper import file_sha256

DEFAULT_FINAL_QC_DIR = AIRKOREA_PROCESSED_DIR / "hourly_qc"
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "air_quality_qc.yaml"

OUTPUT_COLUMNS = [
    "source_record_id",
    "reporting_year",
    "monitor_id",
    "datetime",
    "measurement_datetime_raw",
    "pollutant",
    "unit",
    "value_raw",
    "value_analysis",
    "archive_provisional",
    "qc_status",
    "flag_rule",
    "flag_ml",
    "residual_robust_z",
    "nearby_monitor_count",
]

IDENTITY_COLUMNS = [
    "schema_version",
    "source_record_id",
    "reporting_year",
    "monitor_id",
    "datetime",
    "measurement_datetime_raw",
    "region",
    "network_type",
    "station_name",
    "address",
    "source_archive",
    "source_member",
    "source_row_number",
    "archive_sha256",
    "archive_provisional",
]


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _stable_fingerprint(records: list[dict[str, Any]]) -> str:
    fields = [
        {
            "year": record["year"],
            "member_index": record["member_index"],
            "archive_sha256": record["archive_sha256"],
            "rows": record["rows"],
            "pollutants_present": record.get("pollutants_present", []),
        }
        for record in records
    ]
    encoded = json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()
    return sha256(encoded).hexdigest()


def _selected_source_parts(
    manifest: dict[str, Any],
    year: int,
    pollutant: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in manifest.get("parts", [])
        if int(record["year"]) == year and pollutant in set(record.get("pollutants_present", []))
    ]


def load_canonical_pollutant(
    canonical_manifest: dict[str, Any],
    *,
    year: int,
    pollutant: str,
) -> pd.DataFrame:
    """Read only source members that actually reported the selected pollutant."""
    records = _selected_source_parts(canonical_manifest, year, pollutant)
    if not records:
        raise ValueError(f"AirKorea source has no {pollutant} records for {year}")
    frames: list[pd.DataFrame] = []
    for record in sorted(records, key=lambda item: int(item["member_index"])):
        path = _resolve_path(str(record["output"]))
        frame = pd.read_parquet(path, columns=[*IDENTITY_COLUMNS, pollutant])
        frame = frame.rename(columns={pollutant: "value_raw"})
        frame["pollutant"] = pollutant
        frame["unit"] = POLLUTANT_UNITS[pollutant]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def add_duplicate_flags(data: pd.DataFrame) -> pd.DataFrame:
    """Flag repeated monitor-hour-pollutant keys while preserving every row."""
    result = data.copy()
    keys = ["reporting_year", "monitor_id", "datetime", "pollutant"]
    result["_duplicate_value_key"] = result["value_raw"].astype("string").fillna("<NA>")
    groups = result.groupby(keys, sort=False, observed=True, dropna=False)
    result["duplicate_count"] = groups["value_raw"].transform("size").astype("Int64")
    result["flag_duplicate"] = result["duplicate_count"].gt(1)
    distinct = groups["_duplicate_value_key"].transform("nunique")
    result["flag_duplicate_conflict"] = result["flag_duplicate"] & distinct.gt(1)
    return result.drop(columns="_duplicate_value_key")


def add_model_qc(data: pd.DataFrame, pipeline: AirQualityQCPipeline) -> pd.DataFrame:
    """Apply deterministic rules and time-blocked out-of-fold forest predictions."""
    checked = apply_rule_flags(add_duplicate_flags(data), pipeline.rule_config)
    checked["flag_monitor_missing"] = checked["monitor_id"].isna() | checked["monitor_id"].eq("")
    additions = pd.Series("", index=checked.index, dtype="string")
    for column, label in {
        "flag_duplicate": "duplicate",
        "flag_duplicate_conflict": "duplicate_conflict",
        "flag_monitor_missing": "monitor_id_missing",
    }.items():
        next_label = pd.Series("", index=checked.index, dtype="string")
        next_label.loc[checked[column].fillna(False).astype(bool)] = label
        additions = additions.str.cat(next_label, sep="|").str.strip("|")
    checked["flag_rule"] = (
        checked["flag_rule"].fillna("").str.cat(additions, sep="|").str.strip("|")
    )
    featured, numeric, categorical = add_temporal_and_lag_features(checked)
    return add_oof_predictions(
        featured,
        numeric,
        categorical,
        pipeline.model_config,
    )


def finalize_spatial_qc(data: pd.DataFrame, pipeline: AirQualityQCPipeline) -> pd.DataFrame:
    """Apply spatial confirmation and produce the non-destructive analysis value."""
    result = add_spatial_support(
        data,
        pipeline.radius_km,
        pipeline.spatial_support_z,
        pipeline.minimum_neighbors,
    )
    hard_invalid = (
        result["flag_missing"]
        | result["flag_impossible"]
        | result["flag_monitor_missing"]
        | result["flag_duplicate_conflict"]
    )
    unsupported_anomaly = (
        result["flag_ml"]
        & result["spatial_validation_available"]
        & ~result["flag_spatially_supported"]
    )
    unconfirmed_anomaly = result["flag_ml"] & ~result["spatial_validation_available"]
    result["qc_status"] = "pass"
    rule_review = result["flag_flatline"] | result["flag_jump"] | result["flag_duplicate"]
    result.loc[rule_review, "qc_status"] = "rule_review"
    result.loc[result["flag_ml"] & result["flag_spatially_supported"], "qc_status"] = (
        "supported_event"
    )
    result.loc[unconfirmed_anomaly, "qc_status"] = "ml_review"
    result.loc[unsupported_anomaly, "qc_status"] = "sensor_anomaly"
    result.loc[hard_invalid, "qc_status"] = "invalid"
    result["value_analysis"] = result["value_raw"].mask(hard_invalid | unsupported_anomaly)
    result["analysis_eligible"] = result["value_analysis"].notna()
    return result


def _clean_manifest_payload(
    *,
    output_dir: Path,
    canonical_fingerprint: str,
    attributes_path: Path,
    attributes_sha256: str,
    config_path: Path,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    records = sorted(records, key=lambda item: (int(item["year"]), str(item["pollutant"])))
    return {
        "dataset": "AirKorea hourly rule, forest, and spatially confirmed QC",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "storage": "partitioned_parquet",
        "partition_columns": ["year", "pollutant"],
        "output_directory": _portable_path(output_dir),
        "canonical_fingerprint": canonical_fingerprint,
        "monitor_attributes": _portable_path(attributes_path),
        "monitor_attributes_sha256": attributes_sha256,
        "config": _portable_path(config_path),
        "config_sha256": file_sha256(config_path),
        "partitions": records,
        "total_rows": sum(int(record["rows"]) for record in records),
    }


def clean_qc_partitions(
    *,
    canonical_dir: Path = DEFAULT_CANONICAL_DIR,
    attributes_path: Path = DEFAULT_ATTRIBUTES_PARQUET,
    output_dir: Path = DEFAULT_FINAL_QC_DIR,
    config_path: Path = DEFAULT_CONFIG,
    years: set[int] | None = None,
    pollutants: set[str] | None = None,
    overwrite: bool = False,
) -> Path:
    """Build resumable year-pollutant rule, forest, and spatial QC partitions.

    Monitor coordinates are joined in-memory before the forest and spatial
    steps run, but are not persisted in the output — they are cheap to
    re-join at the annual grain downstream, so keeping them out of the
    hourly-grain table here avoids duplicating them across every partition.
    """
    if not attributes_path.exists():
        raise FileNotFoundError(
            f"AirKorea monitor attributes are absent: {attributes_path}; "
            "run `build_monitor_attributes` first"
        )
    manifest = load_canonical_manifest(canonical_dir)
    source_parts = manifest.get("parts", [])
    fingerprint = _stable_fingerprint(source_parts)
    attributes_sha256 = file_sha256(attributes_path)
    selected_years = sorted(
        years if years is not None else {int(record["year"]) for record in source_parts}
    )
    selected_pollutants = sorted(pollutants if pollutants is not None else set(POLLUTANTS))
    unknown = set(selected_pollutants).difference(POLLUTANTS)
    if unknown:
        raise ValueError(f"Unknown AirKorea pollutants: {sorted(unknown)}")

    manifest_path = output_dir / "manifest.json"
    prior_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    if (
        prior_manifest
        and not overwrite
        and (
            prior_manifest.get("canonical_fingerprint") != fingerprint
            or prior_manifest.get("monitor_attributes_sha256") != attributes_sha256
            or prior_manifest.get("config_sha256") != file_sha256(config_path)
        )
    ):
        raise RuntimeError(
            "Existing AirKorea clean QC partitions use different inputs or settings; "
            "rerun with --overwrite"
        )
    records = {
        (int(record["year"]), str(record["pollutant"])): record
        for record in prior_manifest.get("partitions", [])
    }
    pipeline = AirQualityQCPipeline.from_yaml(config_path)
    attributes = pd.read_parquet(attributes_path)

    for year in selected_years:
        for pollutant in selected_pollutants:
            if not _selected_source_parts(manifest, year, pollutant):
                continue
            destination = (
                output_dir
                / f"year={year}"
                / f"pollutant={pollutant}"
                / "air_quality_hourly_qc.parquet"
            )
            key = (year, pollutant)
            if destination.exists() and not overwrite:
                prior = records.get(
                    key,
                    {
                        "year": year,
                        "pollutant": pollutant,
                        "output": _portable_path(destination),
                        "rows": pd.read_parquet(destination, columns=["monitor_id"]).shape[0],
                    },
                )
                prior["status"] = "reused"
                records[key] = prior
                continue

            raw = load_canonical_pollutant(manifest, year=year, pollutant=pollutant)
            located = add_station_coordinates(raw, attributes)
            checked = add_model_qc(located, pipeline)
            finalized = finalize_spatial_qc(checked, pipeline)
            output = finalized[OUTPUT_COLUMNS]
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_suffix(".parquet.part")
            output.to_parquet(partial, index=False)
            partial.replace(destination)
            records[key] = {
                "year": year,
                "pollutant": pollutant,
                "unit": POLLUTANT_UNITS[pollutant],
                "output": _portable_path(destination),
                "rows": len(output),
                "monitors": int(output["monitor_id"].nunique()),
                "datetime_min": output["datetime"].min().isoformat(),
                "datetime_max": output["datetime"].max().isoformat(),
                "qc_status_counts": {
                    str(name): int(count)
                    for name, count in output["qc_status"].value_counts().items()
                },
                "status": "written",
            }
            _atomic_json(
                manifest_path,
                _clean_manifest_payload(
                    output_dir=output_dir,
                    canonical_fingerprint=fingerprint,
                    attributes_path=attributes_path,
                    attributes_sha256=attributes_sha256,
                    config_path=config_path,
                    records=list(records.values()),
                ),
            )

    _atomic_json(
        manifest_path,
        _clean_manifest_payload(
            output_dir=output_dir,
            canonical_fingerprint=fingerprint,
            attributes_path=attributes_path,
            attributes_sha256=attributes_sha256,
            config_path=config_path,
            records=list(records.values()),
        ),
    )
    return manifest_path
