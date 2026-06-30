"""
Download annual facility-level air pollutant emissions from CleanSYS.

The public CleanSYS annual statistics endpoint covers 2015 onward and reports
emissions in kilograms per year for facilities fitted with stack TMS monitors.

Run from the project root:
    python -m nzk_aphiam.archive.annual_panel.scrape.cleansys
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
import warnings

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry

BASE_URL = "https://cleansys.or.kr"
SOURCE_PAGE_URL = f"{BASE_URL}/statAnnual.do"
DATA_URL = f"{BASE_URL}/apiService/selectAnnualResult.do"
FIRST_YEAR = 2015
LAST_CONFIRMED_YEAR = 2024

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "interim" / "supporting" / "emissions" / "cleansys" / "raw"
)

SOURCE_COLUMNS = [
    "examin_year",
    "fact_code",
    "biz_no",
    "fact_manage_nm",
    "fact_adres",
    "dscamt_sm",
    "tsp_dscamt",
    "sox_dscamt",
    "nox_dscamt",
    "hcl_dscamt",
    "hf_dscamt",
    "nh3_dscamt",
    "co_dscamt",
]

OUTPUT_COLUMNS = [
    "year",
    "facility_code",
    "business_registration_number",
    "facility_name",
    "address",
    "total_kg",
    "tsp_kg",
    "sox_kg",
    "nox_kg",
    "hcl_kg",
    "hf_kg",
    "nh3_kg",
    "co_kg",
]

COLUMN_MAP = dict(zip(SOURCE_COLUMNS, OUTPUT_COLUMNS, strict=True))


def build_session() -> requests.Session:
    """Create a CleanSYS session with a transparent project user agent."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "NZK-APHIAM annual emissions collector",
            "Referer": SOURCE_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1,
        allowed_methods={"GET", "POST"},
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def parse_payload(payload: dict[str, Any], expected_year: int) -> list[dict[str, Any]]:
    """Validate and normalize one CleanSYS annual JSON response."""
    records = payload.get("ResultList")
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"CleanSYS returned no annual records for {expected_year}.")

    rows: list[dict[str, Any]] = []
    for record in records:
        missing = [column for column in SOURCE_COLUMNS if column not in record]
        if missing:
            raise RuntimeError(f"CleanSYS record was missing fields: {missing}")

        if str(record["examin_year"]) != str(expected_year):
            raise RuntimeError(
                f"Expected CleanSYS year {expected_year}, received {record['examin_year']}."
            )

        # The first record is a national subtotal rather than a facility.
        if str(record["fact_code"]) == "0" and record["fact_manage_nm"] == "소계":
            continue

        rows.append({target: record[source] for source, target in COLUMN_MAP.items()})

    if not rows:
        raise RuntimeError(f"CleanSYS returned no facility records for {expected_year}.")
    return rows


def request_payload(
    session: requests.Session,
    year: int,
    timeout: int,
) -> tuple[dict[str, Any], bytes]:
    """Fetch one annual response from the public CleanSYS JSON endpoint."""
    params = {
        "s_year": year,
        "e_year": year,
        "selectArea": "",
        "selectComp": "",
        "selectCompDrop": "",
        "selectOrder": "1",
        "type": "json",
    }
    try:
        # CleanSYS currently serves an incomplete certificate chain to some
        # Python trust stores. The host is fixed above and no credentials are sent.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = session.post(DATA_URL, data=params, timeout=timeout, verify=False)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError(
            f"CleanSYS request failed for {year}: {error.__class__.__name__}"
        ) from None

    return payload, response.content


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write normalized annual records with a fixed column order."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def scrape(
    output_dir: Path,
    start_year: int,
    end_year: int,
    timeout: int,
    overwrite: bool,
    offline: bool = False,
) -> list[dict[str, Any]]:
    """Download and normalize a range of CleanSYS annual emissions records."""
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")
    if start_year < FIRST_YEAR:
        raise ValueError(f"CleanSYS annual public coverage starts in {FIRST_YEAR}.")

    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    manifest: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    if not offline:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                session.get(SOURCE_PAGE_URL, timeout=timeout, verify=False).raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(
                f"Could not initialize CleanSYS session: {error.__class__.__name__}"
            ) from None

    for year in range(start_year, end_year + 1):
        raw_path = output_dir / f"cleansys_annual_emissions_{year}.json"
        csv_path = output_dir / f"cleansys_annual_emissions_{year}.csv"

        if raw_path.exists() and not overwrite:
            raw_bytes = raw_path.read_bytes()
            payload = json.loads(raw_bytes)
            status = "reused"
        elif offline:
            raise RuntimeError(f"Offline CleanSYS rebuild is missing raw file: {raw_path}")
        else:
            payload, raw_bytes = request_payload(session, year, timeout)
            raw_path.write_bytes(raw_bytes)
            status = "downloaded"

        rows = parse_payload(payload, expected_year=year)
        all_rows.extend(rows)
        if overwrite or not csv_path.exists():
            write_csv(csv_path, rows)

        manifest.append(
            {
                "year": year,
                "facility_count": len(rows),
                "status": status,
                "raw_file": raw_path.name,
                "csv_file": csv_path.name,
                "raw_sha256": sha256(raw_bytes).hexdigest(),
                "csv_sha256": sha256(csv_path.read_bytes()).hexdigest(),
            }
        )
        print(f"{year}: {len(rows)} facilities ({status})")

    combined_path = output_dir / "cleansys_annual_emissions_panel.csv"
    write_csv(combined_path, all_rows)

    metadata = {
        "dataset": "CleanSYS annual facility air pollutant emissions",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "years": [start_year, end_year],
        "offline": offline,
        "unit": "kg/year",
        "reporting_level": "facility/workplace",
        "columns": OUTPUT_COLUMNS,
        "source_page_url": SOURCE_PAGE_URL,
        "data_endpoint_url": DATA_URL,
        "combined_csv_file": combined_path.name,
        "combined_csv_sha256": sha256(combined_path.read_bytes()).hexdigest(),
        "facility_year_count": len(all_rows),
        "coverage_notes": [
            "Public annual records begin in 2015.",
            "Only emissions measured by stack TMS instruments are included.",
            "Rows are facilities, not individual generating units or stacks.",
            "Business registration numbers can group facilities under the same legal entity.",
        ],
        "files": manifest,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download annual facility emissions from Korea CleanSYS."
    )
    parser.add_argument("--start-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--end-year", type=int, default=LAST_CONFIRMED_YEAR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild normalized files only from preserved raw responses.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scrape(
        output_dir=args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        timeout=args.timeout,
        overwrite=args.overwrite,
        offline=args.offline,
    )
