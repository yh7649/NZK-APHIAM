"""Canonical, row-preserving ingestion of AirKorea annual workbooks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZipFile

import pandas as pd
import pyarrow.parquet as pq

from nzk_aphiam.air_quality.pipeline import _clean_label, _parse_airkorea_datetime
from nzk_aphiam.config.paths import (
    AIRKOREA_INTERIM_DIR,
    AIRKOREA_RAW_DIR,
    PROJECT_ROOT,
)
from nzk_aphiam.data.scrape.airkorea.scraper import file_sha256

SCHEMA_VERSION = "1.0.0"
DEFAULT_ARCHIVE_DIR = AIRKOREA_RAW_DIR / "hourly_finalized"
DEFAULT_OUTPUT_DIR = AIRKOREA_INTERIM_DIR / "raw_merged"
MANIFEST_NAME = "manifest.json"

POLLUTANTS = ("SO2", "CO", "O3", "NO2", "PM10", "PM25")
POLLUTANT_ALIASES = {
    "SO2": ("SO2", "아황산가스"),
    "CO": ("CO", "일산화탄소"),
    "O3": ("O3", "오존"),
    "NO2": ("NO2", "이산화질소"),
    "PM10": ("PM10", "미세먼지"),
    "PM25": ("PM25", "PM2.5", "초미세먼지"),
}
POLLUTANT_UNITS = {
    "SO2": "ppm",
    "CO": "ppm",
    "O3": "ppm",
    "NO2": "ppm",
    "PM10": "ug/m3",
    "PM25": "ug/m3",
}

CANONICAL_WIDE_COLUMNS = [
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
    *POLLUTANTS,
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
        return str(path)


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def load_canonical_manifest(canonical_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    path = canonical_dir / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(
            f"Canonical AirKorea manifest is absent: {path}; run the canonicalize stage first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _column_lookup(frame: pd.DataFrame) -> dict[str, object]:
    return {_clean_label(column): column for column in frame.columns}


def _find_column(
    lookup: dict[str, object],
    aliases: tuple[str, ...],
    *,
    required: bool,
) -> object | None:
    for alias in aliases:
        cleaned = _clean_label(alias).replace("PM2.5", "PM25")
        for label, original in lookup.items():
            candidate = label.replace("PM2.5", "PM25")
            if candidate == cleaned or candidate.startswith(cleaned + "("):
                return original
    if required:
        raise ValueError(f"AirKorea workbook is missing a column matching {aliases}")
    return None


def _string_column(frame: pd.DataFrame, source: object | None) -> pd.Series:
    if source is None:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    return frame[source].astype("string").str.strip()


def _clean_monitor_ids(values: pd.Series) -> pd.Series:
    return values.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)


def standardize_wide_frame(
    frame: pd.DataFrame,
    *,
    reporting_year: int,
    source_archive: str,
    source_member: str,
    member_index: int,
    archive_sha256: str,
    archive_provisional: bool,
) -> tuple[pd.DataFrame, list[str]]:
    """Return a fixed-schema wide table without removing source rows."""
    lookup = _column_lookup(frame)
    station_code = _find_column(
        lookup,
        ("측정소코드", "측정소 코드", "station_code"),
        required=False,
    )
    station_name = _find_column(
        lookup,
        ("측정소명", "측정소", "station_name"),
        required=station_code is None,
    )
    datetime_column = _find_column(
        lookup,
        (
            "측정일시",
            "측정 일시",
            "측정시간",
            "datetime",
            "data_tine",
        ),
        required=True,
    )
    region = _find_column(lookup, ("지역", "region"), required=False)
    network = _find_column(lookup, ("망", "측정망", "network", "network_type"), required=False)
    address = _find_column(
        lookup,
        ("주소", "측정소주소", "address"),
        required=False,
    )

    pollutant_columns = {
        pollutant: _find_column(lookup, aliases, required=False)
        for pollutant, aliases in POLLUTANT_ALIASES.items()
    }
    pollutants_present = [
        pollutant for pollutant, column in pollutant_columns.items() if column is not None
    ]
    if not pollutants_present:
        raise ValueError("AirKorea workbook contains no recognized pollutant columns")

    measurement_raw = (
        frame[datetime_column].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    )
    monitor_source = station_code if station_code is not None else station_name
    row_numbers = pd.Series(range(2, len(frame) + 2), index=frame.index, dtype="Int64")
    record_prefix = f"{reporting_year}:{member_index:02d}:"

    result = pd.DataFrame(index=frame.index)
    result["schema_version"] = SCHEMA_VERSION
    result["source_record_id"] = record_prefix + row_numbers.astype("string")
    result["reporting_year"] = pd.Series(reporting_year, index=frame.index, dtype="Int64")
    result["monitor_id"] = _clean_monitor_ids(_string_column(frame, monitor_source))
    result["datetime"] = _parse_airkorea_datetime(measurement_raw)
    result["measurement_datetime_raw"] = measurement_raw
    result["region"] = _string_column(frame, region)
    result["network_type"] = _string_column(frame, network)
    result["station_name"] = _string_column(frame, station_name)
    result["address"] = _string_column(frame, address)
    for pollutant, source in pollutant_columns.items():
        if source is None:
            result[pollutant] = pd.Series(pd.NA, index=frame.index, dtype="Float64")
        else:
            result[pollutant] = pd.to_numeric(frame[source], errors="coerce").astype("Float64")
    result["source_archive"] = source_archive
    result["source_member"] = source_member
    result["source_row_number"] = row_numbers
    result["archive_sha256"] = archive_sha256
    result["archive_provisional"] = bool(archive_provisional)

    if len(result) != len(frame):
        raise RuntimeError("Canonical AirKorea conversion changed the source row count")
    return result[CANONICAL_WIDE_COLUMNS], pollutants_present


def _archive_metadata(archive_dir: Path) -> dict[int, dict[str, Any]]:
    path = archive_dir / "metadata.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(record["year"]): record for record in payload.get("files", [])}


def _archive_year(path: Path) -> int:
    match = re.search(r"(20\d{2})", path.stem)
    if not match:
        raise ValueError(f"Cannot determine reporting year from {path.name}")
    return int(match.group(1))


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(
    output_dir: Path,
    archive_dir: Path,
    records: list[dict[str, Any]],
) -> Path:
    records = sorted(records, key=lambda item: (int(item["year"]), int(item["member_index"])))
    payload = {
        "dataset": "AirKorea canonical row-preserving raw merged dataset",
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_directory": _portable_path(archive_dir),
        "output_directory": _portable_path(output_dir),
        "storage": "partitioned_parquet",
        "partition_columns": ["year"],
        "canonical_columns": CANONICAL_WIDE_COLUMNS,
        "pollutant_units": POLLUTANT_UNITS,
        "parts": records,
        "total_rows": sum(int(record["rows"]) for record in records),
        "years": sorted({int(record["year"]) for record in records}),
    }
    manifest_path = output_dir / MANIFEST_NAME
    _atomic_json(manifest_path, payload)
    return manifest_path


def canonicalize_archives(
    *,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    years: set[int] | None = None,
    overwrite: bool = False,
) -> Path:
    """Convert annual ZIP members to one resumable, logical Parquet dataset."""
    archives = sorted(archive_dir.glob("*.zip"))
    if years is not None:
        archives = [path for path in archives if _archive_year(path) in years]
    if not archives:
        raise FileNotFoundError("No AirKorea annual ZIP archives matched the requested years")

    source_metadata = _archive_metadata(archive_dir)
    manifest_path = output_dir / MANIFEST_NAME
    existing_manifest = _load_manifest(manifest_path)
    records_by_output = {
        str(record["output"]): record for record in existing_manifest.get("parts", [])
    }

    for archive_path in archives:
        year = _archive_year(archive_path)
        source_record = source_metadata.get(year, {})
        source_hash = str(source_record.get("sha256") or file_sha256(archive_path))
        provisional = bool(source_record.get("provisional", False))
        with ZipFile(archive_path) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".xlsx")
            ]
            if not members:
                raise ValueError(f"No XLSX workbooks found in {archive_path}")

            year_dir = output_dir / f"year={year}"
            expected_outputs = {
                year_dir / f"part-{member_index:04d}.parquet"
                for member_index in range(len(members))
            }
            stale = set(year_dir.glob("part-*.parquet")).difference(expected_outputs)
            if stale and not overwrite:
                raise RuntimeError(
                    f"Superseded canonical parts exist for {year}: "
                    f"{[path.name for path in sorted(stale)]}; rerun with --overwrite"
                )
            for path in stale:
                path.unlink()
                records_by_output.pop(_portable_path(path), None)

            with TemporaryDirectory(prefix=f"airkorea_canonical_{year}_") as temporary:
                for member_index, member in enumerate(members):
                    destination = year_dir / f"part-{member_index:04d}.parquet"
                    portable_destination = _portable_path(destination)
                    prior = records_by_output.get(portable_destination)
                    if destination.exists() and not overwrite:
                        if prior and prior.get("archive_sha256") != source_hash:
                            raise RuntimeError(
                                f"{destination} was built from a different source archive; "
                                "rerun with --overwrite"
                            )
                        if prior is None:
                            existing = pd.read_parquet(
                                destination,
                                columns=list(POLLUTANTS),
                            )
                            prior = {
                                "year": year,
                                "member_index": member_index,
                                "source_archive": archive_path.name,
                                "source_member": member.filename,
                                "archive_sha256": source_hash,
                                "archive_provisional": provisional,
                                "output": portable_destination,
                                "rows": pq.ParquetFile(destination).metadata.num_rows,
                                "pollutants_present": [
                                    pollutant
                                    for pollutant in POLLUTANTS
                                    if existing[pollutant].notna().any()
                                ],
                                "status": "reused_without_prior_manifest",
                            }
                        else:
                            prior["status"] = "reused"
                        records_by_output[portable_destination] = prior
                        continue

                    extracted = Path(archive.extract(member, temporary))
                    raw = pd.read_excel(extracted)
                    canonical, pollutants_present = standardize_wide_frame(
                        raw,
                        reporting_year=year,
                        source_archive=archive_path.name,
                        source_member=member.filename,
                        member_index=member_index,
                        archive_sha256=source_hash,
                        archive_provisional=provisional,
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    partial = destination.with_suffix(".parquet.part")
                    canonical.to_parquet(partial, index=False)
                    partial.replace(destination)
                    records_by_output[portable_destination] = {
                        "year": year,
                        "member_index": member_index,
                        "source_archive": archive_path.name,
                        "source_member": member.filename,
                        "archive_sha256": source_hash,
                        "archive_provisional": provisional,
                        "output": portable_destination,
                        "rows": len(canonical),
                        "datetime_min": (
                            canonical["datetime"].min().isoformat()
                            if canonical["datetime"].notna().any()
                            else None
                        ),
                        "datetime_max": (
                            canonical["datetime"].max().isoformat()
                            if canonical["datetime"].notna().any()
                            else None
                        ),
                        "pollutants_present": pollutants_present,
                        "status": "written",
                    }
                    _write_manifest(
                        output_dir,
                        archive_dir,
                        list(records_by_output.values()),
                    )

    return _write_manifest(output_dir, archive_dir, list(records_by_output.values()))
