"""Download Korean district mortality and population statistics from KOSIS.

The initial public-health panel contains:

* monthly all-cause deaths by residence district;
* annual cause-specific deaths by residence district; and
* monthly resident population denominators.

KOSIS requires a free OpenAPI key. Put it in ``KOSIS_API_KEY`` in ``.env``.
Raw annual JSON responses are preserved before normalized CSV files are built.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
OPENAPI_PAGE_URL = "https://kosis.kr/openapi/"
PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "health" / "kosis"
DEFAULT_START_YEAR = 2001
DEFAULT_END_YEAR = 2024


@dataclass(frozen=True)
class Dataset:
    """Configuration for one KOSIS statistical table."""

    key: str
    table_id: str
    title: str
    period: str
    first_year: int
    item_id: str
    dimensions: tuple[str, ...]
    output_columns: tuple[str, ...]
    normalizer: Callable[[dict[str, Any]], dict[str, Any]]


def parse_integer(value: Any) -> int | None:
    """Parse KOSIS count strings while retaining suppressed/missing cells."""
    text = "" if value is None else str(value).strip().replace(",", "")
    if text in {"", "-", "--", "...", "…", "NA", "N/A"}:
        return None
    try:
        return int(float(text))
    except ValueError as error:
        raise RuntimeError(f"Unexpected non-numeric KOSIS count: {value!r}") from error


def geography_level(code: str, name: str = "") -> str:
    """Classify KOSIS administrative codes without discarding aggregates."""
    if code == "00":
        return "national"
    if name.startswith("세종"):
        return "district_equivalent"
    if len(code) == 2:
        return "province"
    return "district"


def normalize_monthly_death(record: dict[str, Any]) -> dict[str, Any]:
    period = str(record["PRD_DE"])
    code = str(record["C1"])
    return {
        "district_code": code,
        "district_name": record["C1_NM"],
        "geography_level": geography_level(code, str(record["C1_NM"])),
        "year": int(period[:4]),
        "month": int(period[4:6]),
        "sex_code": str(record.get("C2", "0")),
        "sex": record.get("C2_NM", "계"),
        "deaths_all": parse_integer(record.get("DT")),
        "unit": record.get("UNIT_NM", "명"),
    }


def normalize_cause_death(record: dict[str, Any]) -> dict[str, Any]:
    code = str(record["C2"])
    return {
        "district_code": code,
        "district_name": record["C2_NM"],
        "geography_level": geography_level(code, str(record["C2_NM"])),
        "year": int(str(record["PRD_DE"])[:4]),
        "cause_code": str(record["C1"]),
        "cause_name": record["C1_NM"],
        "sex_code": str(record.get("C3", "0")),
        "sex": record.get("C3_NM", "계"),
        "deaths": parse_integer(record.get("DT")),
        "unit": record.get("UNIT_NM", "명"),
    }


def normalize_population(record: dict[str, Any]) -> dict[str, Any]:
    period = str(record["PRD_DE"])
    code = str(record["C1"])
    return {
        "district_code": code,
        "district_name": record["C1_NM"],
        "geography_level": geography_level(code, str(record["C1_NM"])),
        "year": int(period[:4]),
        "month": int(period[4:6]),
        "sex_code": str(record.get("C2", "0")),
        "sex": record.get("C2_NM", "계"),
        "population": parse_integer(record.get("DT")),
        "unit": record.get("UNIT_NM", "명"),
    }


DATASETS = {
    "monthly-deaths": Dataset(
        key="monthly-deaths",
        table_id="DT_1B82A01",
        title="KOSIS monthly deaths by city, county, and district",
        period="M",
        first_year=1997,
        item_id="T1",
        dimensions=("ALL", "0"),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "month",
            "sex_code",
            "sex",
            "deaths_all",
            "unit",
        ),
        normalizer=normalize_monthly_death,
    ),
    "cause-deaths": Dataset(
        key="cause-deaths",
        table_id="DT_1B34E13",
        title="KOSIS annual deaths by district, 50-cause group, and sex",
        period="Y",
        first_year=1998,
        item_id="T1",
        dimensions=("ALL", "ALL", "0"),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "cause_code",
            "cause_name",
            "sex_code",
            "sex",
            "deaths",
            "unit",
        ),
        normalizer=normalize_cause_death,
    ),
    "population": Dataset(
        key="population",
        table_id="DT_1B040A3",
        title="KOSIS monthly resident population by district and sex",
        period="M",
        # This table advertises annual history from 1992, but its monthly
        # series returns KOSIS error 30 before 2011.
        first_year=2011,
        item_id="T20",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "month",
            "sex_code",
            "sex",
            "population",
            "unit",
        ),
        normalizer=normalize_population,
    ),
}


def build_session() -> requests.Session:
    """Create a retrying KOSIS API session."""
    session = requests.Session()
    # KOSIS's web-application firewall closes connections for some bot-like
    # user-agent phrases. Keep a browser-compatible prefix while identifying
    # this academic project explicitly.
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (compatible; NZK-APHIAM/0.1; academic research)"}
    )
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1,
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET"},
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def build_params(
    dataset: Dataset,
    year: int,
    api_key: str,
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    dimensions: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Build a documented KOSIS parameter-query request."""
    default_start = str(year) if dataset.period == "Y" else f"{year}01"
    default_end = str(year) if dataset.period == "Y" else f"{year}12"
    params = {
        "method": "getList",
        "apiKey": api_key,
        "orgId": "101",
        "tblId": dataset.table_id,
        "itmId": dataset.item_id,
        "prdSe": dataset.period,
        "startPrdDe": start_period or default_start,
        "endPrdDe": end_period or default_end,
        "format": "json",
        "jsonVD": "Y",
    }
    selected_dimensions = dataset.dimensions if dimensions is None else dimensions
    params.update({f"objL{index}": value for index, value in enumerate(selected_dimensions, 1)})
    return params


def validate_payload(payload: Any, dataset: Dataset, year: int) -> list[dict[str, Any]]:
    """Validate KOSIS errors and the fields needed for normalization."""
    if isinstance(payload, dict) and "err" in payload:
        raise RuntimeError(
            f"KOSIS error {payload.get('err')} for {dataset.key} {year}: "
            f"{payload.get('errMsg', 'unknown error')}"
        )
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"KOSIS returned no rows for {dataset.key} {year}.")

    required = {"PRD_DE", "C1", "C1_NM", "DT"}
    if dataset.key == "cause-deaths":
        required.update({"C2", "C2_NM"})
    for record in payload:
        missing = required.difference(record)
        if missing:
            raise RuntimeError(
                f"KOSIS {dataset.key} response is missing fields: {sorted(missing)}"
            )
    return payload


def request_year(
    session: requests.Session,
    dataset: Dataset,
    year: int,
    api_key: str,
    timeout: int,
) -> tuple[list[dict[str, Any]], bytes]:
    """Download one table-year response in chunks below KOSIS's row cap."""

    def request_chunk(params: dict[str, str]) -> list[dict[str, Any]]:
        try:
            response = session.get(API_URL, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise RuntimeError(
                f"KOSIS request failed for {dataset.key} {year}: {error.__class__.__name__}"
            ) from None
        return validate_payload(payload, dataset, year)

    records: list[dict[str, Any]] = []
    try:
        if dataset.period == "M":
            # An ALL-geography query contains roughly 386 rows per month. KOSIS
            # closes responses above about 1,000 rows, so use two-month chunks.
            for first_month in range(1, 13, 2):
                records.extend(
                    request_chunk(
                        build_params(
                            dataset,
                            year,
                            api_key,
                            start_period=f"{year}{first_month:02d}",
                            end_period=f"{year}{first_month + 1:02d}",
                        )
                    )
                )
        elif dataset.key == "cause-deaths":
            # Discover the current cause codes using the national row, then
            # request two causes at a time across all geographies (about 770
            # rows). Cause codes include letters and are not safely enumerable.
            cause_index = request_chunk(
                build_params(
                    dataset,
                    year,
                    api_key,
                    dimensions=("ALL", "00", "0"),
                )
            )
            cause_codes = list(dict.fromkeys(str(row["C1"]) for row in cause_index))
            for index in range(0, len(cause_codes), 2):
                cause_batch = "+".join(cause_codes[index : index + 2])
                records.extend(
                    request_chunk(
                        build_params(
                            dataset,
                            year,
                            api_key,
                            dimensions=(cause_batch, "ALL", "0"),
                        )
                    )
                )
        else:
            records.extend(request_chunk(build_params(dataset, year, api_key)))
    except RuntimeError:
        raise

    raw_bytes = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return validate_payload(records, dataset, year), raw_bytes


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """Write one normalized table with deterministic columns."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scrape_dataset(
    session: requests.Session,
    dataset: Dataset,
    output_dir: Path,
    start_year: int,
    end_year: int,
    api_key: str,
    timeout: int,
    overwrite: bool,
) -> dict[str, Any]:
    """Download, preserve, and normalize one configured KOSIS dataset."""
    effective_start = max(start_year, dataset.first_year)
    dataset_dir = output_dir / dataset.key.replace("-", "_")
    raw_dir = dataset_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []

    for year in range(effective_start, end_year + 1):
        raw_path = raw_dir / f"{dataset.table_id}_{year}.json"
        if raw_path.exists() and not overwrite:
            raw_bytes = raw_path.read_bytes()
            payload = validate_payload(json.loads(raw_bytes), dataset, year)
            status = "reused"
        else:
            payload, raw_bytes = request_year(session, dataset, year, api_key, timeout)
            raw_path.write_bytes(raw_bytes)
            status = "downloaded"

        normalized = [dataset.normalizer(record) for record in payload]
        rows.extend(normalized)
        files.append(
            {
                "year": year,
                "raw_file": str(raw_path.relative_to(output_dir)),
                "raw_rows": len(payload),
                "raw_sha256": sha256(raw_bytes).hexdigest(),
                "status": status,
            }
        )
        print(f"{dataset.key} {year}: {len(payload)} rows ({status})")

    csv_path = dataset_dir / f"{dataset.key.replace('-', '_')}.csv"
    write_csv(csv_path, dataset.output_columns, rows)
    return {
        "key": dataset.key,
        "title": dataset.title,
        "table_id": dataset.table_id,
        "period": dataset.period,
        "coverage": [effective_start, end_year],
        "normalized_file": str(csv_path.relative_to(output_dir)),
        "normalized_rows": len(rows),
        "normalized_sha256": file_sha256(csv_path),
        "files": files,
    }


def resolve_api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("KOSIS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "KOSIS_API_KEY is missing. Request a free key at the KOSIS OpenAPI site "
            "and add it to .env."
        )
    return api_key


def scrape(
    output_dir: Path,
    start_year: int,
    end_year: int,
    dataset_keys: list[str],
    timeout: int,
    overwrite: bool,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Collect selected public-health tables and write a provenance manifest."""
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")
    selected = list(DATASETS) if not dataset_keys or "all" in dataset_keys else dataset_keys
    unknown = sorted(set(selected).difference(DATASETS))
    if unknown:
        raise ValueError(f"Unknown KOSIS health dataset(s): {', '.join(unknown)}")

    key = api_key or resolve_api_key()
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    results = [
        scrape_dataset(
            session,
            DATASETS[dataset_key],
            output_dir,
            start_year,
            end_year,
            key,
            timeout,
            overwrite,
        )
        for dataset_key in selected
    ]

    metadata = {
        "dataset": "KOSIS public mortality and population baseline for NZK-APHIAM",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_url": API_URL,
        "openapi_page_url": OPENAPI_PAGE_URL,
        "requested_coverage": [start_year, end_year],
        "geographic_basis": "Published administrative area; mortality is by residence.",
        "analysis_notes": [
            "Keep death counts and use log(population) as a count-model offset.",
            "Monthly public mortality is all-cause; cause-specific district data are annual.",
            "Administrative boundaries and codes must be harmonized before spatial modeling.",
            "National and province aggregates are retained and labeled in geography_level.",
        ],
        "datasets": results,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Korean district mortality and population statistics from KOSIS."
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        default=[],
        metavar="DATASET",
        help="Datasets to collect; defaults to all.",
    )
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scrape(
        output_dir=args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        dataset_keys=args.datasets,
        timeout=args.timeout,
        overwrite=args.overwrite,
    )
