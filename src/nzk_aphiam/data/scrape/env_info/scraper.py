"""Scrape facility-level air emissions from Korea's ENV-INFO system.

The public search UI lists both representative companies and their individual
sites. Its older public detail view accepts either type of record and exposes
verified annual NOx, SOx, and TSP emissions in metric tons.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
from typing import Any

import requests

BASE_URL = "https://www.env-info.kr"
SEARCH_PAGE_URL = f"{BASE_URL}/member/open/companyTotalInfoSearch.do"
SEARCH_DATA_URL = f"{BASE_URL}/member/open/retrieveDoc.do"
DETAIL_URL = f"{BASE_URL}/user/register/viewUserSearch2.do"
POWER_INDUSTRY = "전기, 가스, 증기 및 수도사업"

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "emissions" / "env_info" / "raw"

OUTPUT_COLUMNS = [
    "year",
    "record_id",
    "parent_record_id",
    "facility_name",
    "record_type",
    "organization_type",
    "industry",
    "nox_tonnes",
    "sox_tonnes",
    "tsp_tonnes",
    "source_url",
]

NAME_PATTERN = re.compile(
    r'<td\s+id="printCompNm"[^>]*>\s*(?P<value>.*?)\s*</td>',
    re.DOTALL | re.IGNORECASE,
)
AIR_SECTION_PATTERN = re.compile(
    r'<div\s+id="inquiry14"[^>]*>(?P<section>.*?)<!--\s*//의무 14\.',
    re.DOTALL | re.IGNORECASE,
)
POLLUTANT_PATTERNS = {
    "nox_tonnes": re.compile(
        r"질소산화물\s*\(Nox\).*?<td[^>]*>\s*(?:<[^>]+>\s*)*"
        r"(?P<value>[\d,.]+)\s*ton",
        re.DOTALL | re.IGNORECASE,
    ),
    "sox_tonnes": re.compile(
        r"황산화물\s*\(SOX\).*?<td[^>]*>\s*(?:<[^>]+>\s*)*"
        r"(?P<value>[\d,.]+)\s*ton",
        re.DOTALL | re.IGNORECASE,
    ),
    "tsp_tonnes": re.compile(
        r"먼지\s*\(TSP\).*?<td[^>]*>\s*(?:<[^>]+>\s*)*"
        r"(?P<value>[\d,.]+)\s*ton",
        re.DOTALL | re.IGNORECASE,
    ),
}


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "NZK-APHIAM ENV-INFO emissions collector"
    return session


def columnar_json_to_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert ENV-INFO's dictionary-of-arrays response to row dictionaries."""
    lengths = [len(value) for value in payload.values() if isinstance(value, list)]
    if not lengths:
        return []
    row_count = max(lengths)
    rows: list[dict[str, Any]] = []
    for index in range(row_count):
        rows.append(
            {
                key: value[index] if isinstance(value, list) and index < len(value) else value
                for key, value in payload.items()
            }
        )
    return rows


def parse_emissions_detail(html: str) -> dict[str, str | float | None]:
    """Extract the displayed facility name and annual pollutant masses."""
    name_match = NAME_PATTERN.search(html)
    section_match = AIR_SECTION_PATTERN.search(html)
    air_section = section_match.group("section") if section_match else ""
    result: dict[str, str | float | None] = {
        "facility_name": (
            unescape(re.sub(r"<[^>]+>", "", name_match.group("value"))).strip()
            if name_match
            else None
        )
    }
    for column, pattern in POLLUTANT_PATTERNS.items():
        match = pattern.search(air_section)
        result[column] = float(match.group("value").replace(",", "")) if match else None
    return result


def fetch_year_index(
    session: requests.Session,
    year: int,
    timeout: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch all public ENV-INFO records for one disclosure year."""
    response = session.post(
        SEARCH_DATA_URL,
        data={
            "mapData": json.dumps(
                {
                    "year": str(year),
                    "year2": str(year),
                    "firstOrder": "yearOrdersArea",
                    "pageSize": 10_000,
                    "currentIndex": 1,
                    "orderBy": "",
                },
                ensure_ascii=False,
            )
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload, columnar_json_to_rows(payload)


def fetch_detail(
    session: requests.Session,
    year: int,
    record_id: str,
    timeout: int,
) -> tuple[str, str]:
    response = session.get(
        DETAIL_URL,
        params={"YEAR": year, "COMP_ID": record_id, "OPEN_YN": "Y"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.url, response.text


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def gzip_content_sha256(path: Path) -> str:
    with gzip.open(path, "rb") as file:
        return sha256(file.read()).hexdigest()


def scrape_year(
    output_dir: Path,
    year: int,
    timeout: int = 30,
    overwrite: bool = False,
    offline: bool = False,
) -> list[dict[str, Any]]:
    """Download one year of power-sector facility emissions."""
    year_dir = output_dir / str(year)
    detail_dir = year_dir / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    index_path = year_dir / f"env_info_index_{year}.json"
    csv_path = year_dir / f"env_info_power_emissions_{year}.csv"

    session = build_session()
    if not offline:
        session.get(SEARCH_PAGE_URL, timeout=timeout).raise_for_status()
    if index_path.exists() and not overwrite:
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        index_rows = columnar_json_to_rows(index_payload)
    elif offline:
        raise RuntimeError(f"Offline ENV-INFO rebuild is missing index: {index_path}")
    else:
        index_payload, index_rows = fetch_year_index(session, year, timeout)
        index_path.write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    candidates = [
        row
        for row in index_rows
        if row.get("businesstypeNm") == POWER_INDUSTRY and row.get("compId")
    ]
    output_rows: list[dict[str, Any]] = []
    for position, candidate in enumerate(candidates, start=1):
        record_id = str(candidate["compId"])
        raw_path = detail_dir / f"{record_id}.html.gz"
        if raw_path.exists() and not overwrite:
            with gzip.open(raw_path, "rt", encoding="utf-8") as file:
                html = file.read()
            source_url = f"{DETAIL_URL}?YEAR={year}&COMP_ID={record_id}&OPEN_YN=Y"
        elif offline:
            raise RuntimeError(f"Offline ENV-INFO rebuild is missing detail page: {raw_path}")
        else:
            source_url, html = fetch_detail(session, year, record_id, timeout)
            with gzip.open(raw_path, "wt", encoding="utf-8") as file:
                file.write(html)

        parsed = parse_emissions_detail(html)
        output_rows.append(
            {
                "year": year,
                "record_id": record_id,
                "parent_record_id": candidate.get("custId", ""),
                "facility_name": parsed["facility_name"] or candidate.get("compNm", ""),
                "record_type": candidate.get("headOfficeTpNm", ""),
                "organization_type": candidate.get("compDivNm", ""),
                "industry": candidate.get("businesstypeNm", ""),
                "nox_tonnes": parsed["nox_tonnes"],
                "sox_tonnes": parsed["sox_tonnes"],
                "tsp_tonnes": parsed["tsp_tonnes"],
                "source_url": source_url,
            }
        )
        if position == 1 or position % 25 == 0 or position == len(candidates):
            print(f"{year}: fetched {position}/{len(candidates)} power-sector records")

    write_csv(csv_path, output_rows)
    detail_manifest = [
        {
            "record_id": row["record_id"],
            "source_url": row["source_url"],
            "raw_file": f"detail/{row['record_id']}.html.gz",
            "html_sha256": gzip_content_sha256(detail_dir / f"{row['record_id']}.html.gz"),
        }
        for row in output_rows
    ]
    manifest_path = year_dir / "detail_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["record_id", "source_url", "raw_file", "html_sha256"],
        )
        writer.writeheader()
        writer.writerows(detail_manifest)
    metadata = {
        "dataset": "ENV-INFO facility-level annual air pollutant emissions",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "offline": offline,
        "candidate_count": len(candidates),
        "rows_with_any_emissions": sum(
            any(row[column] is not None for column in ("nox_tonnes", "sox_tonnes", "tsp_tonnes"))
            for row in output_rows
        ),
        "units": {
            "nox_tonnes": "metric tonnes/year",
            "sox_tonnes": "metric tonnes/year",
            "tsp_tonnes": "metric tonnes/year",
        },
        "scope_note": (
            "The power-sector industry also includes gas, steam, and water utilities. "
            "Match these facility records to EPSIS before treating them as generators."
        ),
        "source_search_page": SEARCH_PAGE_URL,
        "source_detail_endpoint": DETAIL_URL,
        "index_sha256": sha256(index_path.read_bytes()).hexdigest(),
        "csv_sha256": sha256(csv_path.read_bytes()).hexdigest(),
        "detail_manifest": manifest_path.name,
        "detail_manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
    }
    (year_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild normalized files only from preserved raw responses.",
    )
    args = parser.parse_args()

    if args.start_year > args.end_year:
        parser.error("--start-year must not be after --end-year")
    panel_rows: list[dict[str, Any]] = []
    for year in range(args.start_year, args.end_year + 1):
        panel_rows.extend(
            scrape_year(
                args.output_dir,
                year,
                args.timeout,
                args.overwrite,
                args.offline,
            )
        )
    panel_path = (
        args.output_dir / f"env_info_power_emissions_{args.start_year}_{args.end_year}.csv"
    )
    write_csv(panel_path, panel_rows)
    panel_metadata = {
        "dataset": "ENV-INFO power-sector annual emissions panel",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "years": [args.start_year, args.end_year],
        "offline": args.offline,
        "row_count": len(panel_rows),
        "csv_file": panel_path.name,
        "csv_sha256": sha256(panel_path.read_bytes()).hexdigest(),
        "year_metadata": [
            {
                "year": year,
                "path": f"{year}/metadata.json",
                "sha256": sha256(
                    (args.output_dir / str(year) / "metadata.json").read_bytes()
                ).hexdigest(),
            }
            for year in range(args.start_year, args.end_year + 1)
        ],
    }
    panel_path.with_suffix(".metadata.json").write_text(
        json.dumps(panel_metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(panel_rows)} annual facility records to {panel_path}")


if __name__ == "__main__":
    main()
