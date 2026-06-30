"""
Download annual and dated generator rosters from KPX EPSIS.

EPSIS does not expose these records through a documented public API. Its
website uses POST endpoints to populate the annual roster grid and a paginated
board whose dated snapshot attachments contain CSV and XLSX files.

Run from the project root:
    python -m nzk_aphiam.archive.annual_panel.scrape.epsis annual
    python -m nzk_aphiam.archive.annual_panel.scrape.epsis snapshots
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin

import requests

BASE_URL = "https://epsis.kpx.or.kr"
ANNUAL_PAGE_URL = f"{BASE_URL}/epsisnew/selectEkfaFclDtlChart.do?menuId=020600"
ANNUAL_DATA_URL = f"{BASE_URL}/epsisnew/selectEkfaFclDtlGrid.do"
ANNUAL_GENERATION_PAGE_URL = f"{BASE_URL}/epsisnew/selectEkgeGepGbpGrid.do?menuId=060105"
ANNUAL_GENERATION_DATA_URL = f"{BASE_URL}/epsisnew/selectEkgeGepGbpGridAjax.ajax"
SNAPSHOT_PAGE_URL = f"{BASE_URL}/epsisnew/selectEkifBoardList.do?boardId=080000&menuId=020902"
SNAPSHOT_LIST_URL = f"{BASE_URL}/epsisnew/selectEkifBoardList.ajax"
SNAPSHOT_DETAIL_URL = f"{BASE_URL}/epsisnew/detailEkifBoard.ajax"
FIRST_ANNUAL_YEAR = 2012
LAST_ANNUAL_YEAR = 2024
FIRST_GENERATION_YEAR = 2002

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "interim" / "supporting" / "plant_rosters" / "epsis" / "raw"
)

ANNUAL_COLUMNS = [
    "year",
    "generation_source",
    "plant_name",
    "unit_capacity_kw",
    "unit_count",
    "capacity_kw",
    "completion_date",
    "generation_type",
    "fuel",
    "boiler_nsss_manufacturer",
    "turbine_manufacturer",
    "generator_manufacturer",
    "generation_company",
    "rated_voltage",
    "use_category",
    "membership",
    "market_participation",
    "dispatch_type",
    "location_or_main_product",
]

ANNUAL_GENERATION_COLUMNS = [
    "year",
    "generation_source",
    "fuel_group",
    "fuel_detail",
    "company",
    "company_category",
    "source_record_name",
    "source_record_name_english",
    "capacity_kw",
    "gross_generation_mwh",
    "station_use_mwh",
    "net_generation_mwh",
    "maximum_output_kw",
    "average_output_kw",
    "load_factor_percent",
    "utilization_rate_percent",
    "station_use_rate_percent",
]

ASSIGNMENT_PATTERN = re.compile(r'^\s*c(?P<number>\d+)\s*=\s*(?P<value>"(?:\\.|[^"\\])*")\s*;\s*$')
YEAR_PATTERN = re.compile(r'"year"\s*:\s*"(?P<year>\d{4})"')
GENERATION_BRANCH_END_PATTERN = re.compile(r"^\s*}else\{\s*$", re.MULTILINE)
GRID_PUSH_PATTERN = re.compile(r"gridData\.push\(\{(?P<body>.*?)\}\);", re.DOTALL)
OBJECT_PAIR_PATTERN = re.compile(
    r'"(?P<key>[A-Za-z0-9_]+)"\s*:\s*(?P<value>"(?:\\.|[^"\\])*"|c\d+)'
)
TOTAL_PATTERN = re.compile(r"TOTAL\s*:\s*(\d+)")
END_PAGE_PATTERN = re.compile(r'linkPage\((\d+)\);\s*return false;">맨끝으로')
SNAPSHOT_DATE_PATTERN = re.compile(r"(\d{4})년\s*(\d{2})월\s*(\d{2})일")


class SnapshotListParser(HTMLParser):
    """Parse rows from the EPSIS generator-change board."""

    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_cells: list[str] = []
        self.current_no_index: int | None = None
        self.records: list[dict[str, str | int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.current_cells = []
            self.current_no_index = None
        elif tag == "td" and self.in_row:
            self.in_cell = True
            self.current_cell = []
            onclick = attributes.get("onclick") or ""
            match = re.search(r"viewPage\((\d+)\)", onclick)
            if match:
                self.current_no_index = int(match.group(1))

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_cell:
            self.current_cells.append(" ".join("".join(self.current_cell).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.current_no_index is not None and len(self.current_cells) >= 6:
                self.records.append(
                    {
                        "no_index": self.current_no_index,
                        "display_number": self.current_cells[0],
                        "title": self.current_cells[1],
                        "author": self.current_cells[2],
                        "created_date": self.current_cells[3],
                        "modified_date": self.current_cells[4],
                        "view_count": self.current_cells[5],
                    }
                )
            self.in_row = False


class AttachmentParser(HTMLParser):
    """Extract EPSIS board attachment links."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self.current_href: str | None = None
        self.current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if "/fileDownload.do?" in href:
            self.current_href = href
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_href is not None:
            self.links.append(
                {
                    "url": urljoin(BASE_URL, self.current_href),
                    "filename": "".join(self.current_text).strip(),
                }
            )
            self.current_href = None
            self.current_text = []


def parse_annual_payload(payload: str, expected_year: int | None = None) -> list[dict[str, str]]:
    """Parse the JavaScript assignments returned by the EPSIS annual grid."""
    rows: list[dict[str, str]] = []
    values: dict[int, str] = {}

    for line in payload.splitlines():
        assignment = ASSIGNMENT_PATTERN.match(line)
        if assignment:
            number = int(assignment.group("number"))
            values[number] = json.loads(assignment.group("value"))
            continue

        if "gridData.push" not in line:
            continue

        year_match = YEAR_PATTERN.search(line)
        if not year_match:
            raise RuntimeError("EPSIS annual row did not include a four-digit year.")

        year = int(year_match.group("year"))
        if expected_year is not None and year != expected_year:
            raise RuntimeError(f"Expected EPSIS year {expected_year}, received {year}.")

        missing = [number for number in range(1, 19) if number not in values]
        if missing:
            raise RuntimeError(f"EPSIS annual row was missing fields: {missing}")

        row_values = [str(year), *(values[number] for number in range(1, 19))]
        rows.append(dict(zip(ANNUAL_COLUMNS, row_values, strict=True)))
        values = {}

    if not rows:
        raise RuntimeError("EPSIS annual roster response contained no rows.")

    return rows


def parse_annual_generation_payload(
    payload: str,
    expected_year: int | None = None,
) -> list[dict[str, str]]:
    """Parse detailed rows from the first branch of the EPSIS generation response."""
    branch_end = GENERATION_BRANCH_END_PATTERN.search(payload)
    if not branch_end:
        raise RuntimeError("Could not isolate detailed EPSIS annual generation rows.")

    detailed_branch = payload[: branch_end.start()]
    assignments: dict[str, str] = {}
    rows: list[dict[str, str]] = []
    source_keys = [
        "Period",
        "Power",
        "Fuel",
        "Fuel2",
        "Comp",
        "Comp2",
        "Equip",
        "Equip2",
        *(f"c{number}" for number in range(1, 10)),
    ]

    push_lines: list[str] = []
    in_push = False

    for line in detailed_branch.splitlines():
        assignment = ASSIGNMENT_PATTERN.match(line)
        if assignment:
            assignments[f"c{assignment.group('number')}"] = json.loads(assignment.group("value"))
            continue

        if "gridData.push({" in line:
            in_push = True
            push_lines = [line]
        elif in_push:
            push_lines.append(line)

        if not in_push or "});" not in line:
            continue

        body_match = GRID_PUSH_PATTERN.search("\n".join(push_lines))
        if not body_match:
            raise RuntimeError("Could not parse an EPSIS annual generation row.")
        parsed_values: dict[str, str] = {}
        for pair in OBJECT_PAIR_PATTERN.finditer(body_match.group("body")):
            key = pair.group("key")
            raw_value = pair.group("value")
            parsed_values[key] = (
                json.loads(raw_value)
                if raw_value.startswith('"')
                else assignments.get(raw_value, "")
            )

        missing = [key for key in source_keys if key not in parsed_values]
        if missing:
            raise RuntimeError(f"EPSIS annual generation row was missing fields: {missing}")

        if expected_year is not None and parsed_values["Period"] != str(expected_year):
            raise RuntimeError(
                f"Expected EPSIS generation year {expected_year}, "
                f"received {parsed_values['Period']}."
            )

        source_values = [parsed_values[key] for key in source_keys]
        rows.append(dict(zip(ANNUAL_GENERATION_COLUMNS, source_values, strict=True)))
        assignments = {}
        push_lines = []
        in_push = False

    if not rows:
        raise RuntimeError("EPSIS annual generation response contained no detailed rows.")
    return rows


def parse_snapshot_list(html: str) -> list[dict[str, str | int]]:
    """Parse one page of dated snapshot board records."""
    parser = SnapshotListParser()
    parser.feed(html)
    return parser.records


def parse_snapshot_coverage(html: str) -> tuple[int, int]:
    """Return total board records and final page number."""
    total_match = TOTAL_PATTERN.search(html)
    end_page_match = END_PAGE_PATTERN.search(html)
    if not total_match or not end_page_match:
        raise RuntimeError("Could not determine EPSIS snapshot board coverage.")
    return int(total_match.group(1)), int(end_page_match.group(1))


def parse_attachments(html: str) -> list[dict[str, str]]:
    """Parse attachment URLs and provider filenames from a board detail page."""
    parser = AttachmentParser()
    parser.feed(html)
    return parser.links


def snapshot_date_from_title(title: str) -> str:
    """Convert the Korean effective date in a snapshot title to ISO format."""
    match = SNAPSHOT_DATE_PATTERN.search(title)
    if not match:
        raise RuntimeError(f"Could not parse snapshot date from title: {title}")
    return "-".join(match.groups())


def build_session() -> requests.Session:
    """Create a session with a transparent project user agent."""
    session = requests.Session()
    session.headers["User-Agent"] = "NZK-APHIAM EPSIS roster collector"
    return session


def request_text(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    data: dict[str, str | int] | None = None,
) -> str:
    """Request an EPSIS text response with a concise error message."""
    try:
        response = session.request(method, url, data=data, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"EPSIS request failed: {error.__class__.__name__}: {url}") from None
    return response.text


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    """Write dictionaries to a UTF-8 CSV with fixed column order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def scrape_annual(
    output_dir: Path,
    start_year: int,
    end_year: int,
    timeout: int,
    overwrite: bool,
    offline: bool = False,
) -> list[dict[str, Any]]:
    """Download annual generator rosters and preserve raw EPSIS payloads."""
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")

    annual_dir = output_dir / "annual"
    annual_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    if not offline:
        request_text(session, "GET", ANNUAL_PAGE_URL, timeout=timeout)
    manifest: list[dict[str, Any]] = []

    for year in range(start_year, end_year + 1):
        payload_path = annual_dir / f"epsis_generator_roster_{year}_raw.js"
        csv_path = annual_dir / f"epsis_generator_roster_{year}.csv"

        if payload_path.exists() and not overwrite:
            payload = payload_path.read_text(encoding="utf-8")
            status = "reused"
        elif offline:
            raise RuntimeError(f"Offline EPSIS rebuild is missing raw file: {payload_path}")
        else:
            payload = request_text(
                session,
                "POST",
                ANNUAL_DATA_URL,
                timeout=timeout,
                data={
                    "srchDate": year,
                    "selGenGubun": "",
                    "srchNm": "",
                    "srchYn": "Y",
                },
            )
            payload_path.write_text(payload, encoding="utf-8")
            status = "downloaded"

        rows = parse_annual_payload(payload, expected_year=year)
        if overwrite or not csv_path.exists():
            write_csv(csv_path, ANNUAL_COLUMNS, rows)

        manifest.append(
            {
                "year": year,
                "row_count": len(rows),
                "status": status,
                "raw_payload": payload_path.name,
                "csv_file": csv_path.name,
                "raw_sha256": sha256(payload.encode("utf-8")).hexdigest(),
                "csv_sha256": sha256(csv_path.read_bytes()).hexdigest(),
                "source_page_url": ANNUAL_PAGE_URL,
                "data_endpoint_url": ANNUAL_DATA_URL,
            }
        )
        print(f"{year}: {len(rows)} rows ({status})")

    metadata = {
        "dataset": "KPX EPSIS annual generator detail rosters",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "years": [start_year, end_year],
        "offline": offline,
        "columns": ANNUAL_COLUMNS,
        "files": manifest,
    }
    (annual_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def scrape_annual_generation(
    output_dir: Path,
    start_year: int,
    end_year: int,
    timeout: int,
    overwrite: bool,
    offline: bool = False,
) -> list[dict[str, Any]]:
    """Download annual mixed-granularity capacity and generation records."""
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")

    generation_dir = output_dir / "annual_generation"
    generation_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    if not offline:
        request_text(session, "GET", ANNUAL_GENERATION_PAGE_URL, timeout=timeout)
    manifest: list[dict[str, Any]] = []

    for year in range(start_year, end_year + 1):
        payload_path = generation_dir / f"epsis_generator_generation_{year}_raw.js"
        csv_path = generation_dir / f"epsis_generator_generation_{year}.csv"

        if payload_path.exists() and not overwrite:
            payload = payload_path.read_text(encoding="utf-8")
            status = "reused"
        elif offline:
            raise RuntimeError(
                f"Offline EPSIS generation rebuild is missing raw file: {payload_path}"
            )
        else:
            payload = request_text(
                session,
                "POST",
                ANNUAL_GENERATION_DATA_URL,
                timeout=timeout,
                data={"beginDate": year, "endDate": year},
            )
            payload_path.write_text(payload, encoding="utf-8")
            status = "downloaded"

        rows = parse_annual_generation_payload(payload, expected_year=year)
        if overwrite or not csv_path.exists():
            write_csv(csv_path, ANNUAL_GENERATION_COLUMNS, rows)

        manifest.append(
            {
                "year": year,
                "row_count": len(rows),
                "status": status,
                "raw_payload": payload_path.name,
                "csv_file": csv_path.name,
                "raw_sha256": sha256(payload.encode("utf-8")).hexdigest(),
                "csv_sha256": sha256(csv_path.read_bytes()).hexdigest(),
                "source_page_url": ANNUAL_GENERATION_PAGE_URL,
                "data_endpoint_url": ANNUAL_GENERATION_DATA_URL,
            }
        )
        print(f"{year}: {len(rows)} generation rows ({status})")

    metadata = {
        "dataset": "KPX EPSIS annual plant and aggregate capacity and generation",
        "record_granularity": "mixed",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "years": [start_year, end_year],
        "offline": offline,
        "columns": ANNUAL_GENERATION_COLUMNS,
        "source_notes": [
            "Annual values are sourced by EPSIS from Korea Electric Power Statistics.",
            (
                "Rows are not uniformly generating units. They mix unit, plant, "
                "multi-unit plant, company/technology, and portfolio aggregates."
            ),
            (
                "The EPSIS Korean menu says 'by generator', while its English data "
                "column labels the record 'Plant'."
            ),
            "Small non-KEPCO and renewable facilities are partly omitted by the provider.",
            "Capacity is reported capacity and may not reflect facility improvements.",
        ],
        "files": manifest,
    }
    (generation_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def fetch_snapshot_index(session: requests.Session, timeout: int) -> list[dict[str, Any]]:
    """Crawl every EPSIS generator-change board page."""
    request_text(session, "GET", SNAPSHOT_PAGE_URL, timeout=timeout)
    first_html = request_text(
        session,
        "POST",
        SNAPSHOT_LIST_URL,
        timeout=timeout,
        data={
            "pageIndex": 1,
            "menuId": "020902",
            "boardId": "080000",
            "lowerId": "080000",
        },
    )
    total, final_page = parse_snapshot_coverage(first_html)
    records: list[dict[str, Any]] = []

    for page in range(1, final_page + 1):
        html = (
            first_html
            if page == 1
            else request_text(
                session,
                "POST",
                SNAPSHOT_LIST_URL,
                timeout=timeout,
                data={
                    "pageIndex": page,
                    "menuId": "020902",
                    "boardId": "080000",
                    "lowerId": "080000",
                },
            )
        )
        page_records = parse_snapshot_list(html)
        for record in page_records:
            record["page_index"] = page
            record["snapshot_date"] = snapshot_date_from_title(str(record["title"]))
        records.extend(page_records)

    if len(records) != total:
        raise RuntimeError(f"Expected {total} EPSIS snapshots, parsed {len(records)}.")
    return records


def add_snapshot_attachments(
    session: requests.Session,
    records: list[dict[str, Any]],
    timeout: int,
) -> None:
    """Add attachment metadata from each snapshot detail page."""
    for position, record in enumerate(records, start=1):
        html = request_text(
            session,
            "POST",
            SNAPSHOT_DETAIL_URL,
            timeout=timeout,
            data={
                "pageIndex": record["page_index"],
                "noIndex": record["no_index"],
                "menuId": "020902",
                "boardId": "080000",
                "lowerId": "080000",
            },
        )
        attachments = parse_attachments(html)
        if len(attachments) != 1:
            raise RuntimeError(
                f"Expected one attachment for snapshot {record['no_index']}, "
                f"found {len(attachments)}."
            )
        record.update(
            {
                "attachment_filename": attachments[0]["filename"],
                "attachment_url": attachments[0]["url"],
            }
        )
        if position == 1 or position % 25 == 0 or position == len(records):
            print(f"Indexed snapshot {position}/{len(records)}: {record['snapshot_date']}")


def download_snapshot(
    session: requests.Session,
    record: dict[str, Any],
    output_dir: Path,
    timeout: int,
    overwrite: bool,
) -> dict[str, Any]:
    """Download one original EPSIS snapshot ZIP and record its checksum."""
    snapshot_date = str(record["snapshot_date"]).replace("-", "")
    path = output_dir / f"epsis_generator_snapshot_{snapshot_date}.zip"

    if path.exists() and not overwrite:
        content = path.read_bytes()
        status = "reused"
    else:
        try:
            response = session.get(str(record["attachment_url"]), timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(
                f"EPSIS snapshot download failed: {error.__class__.__name__}: "
                f"{record['attachment_url']}"
            ) from None
        content = response.content
        if not content.startswith(b"PK"):
            raise RuntimeError(f"EPSIS snapshot {record['no_index']} was not a ZIP archive.")
        path.write_bytes(content)
        status = "downloaded"

    record["local_filename"] = path.name
    record["byte_count"] = len(content)
    record["sha256"] = sha256(content).hexdigest()
    record["status"] = status
    return record


def scrape_snapshots(
    output_dir: Path,
    timeout: int,
    overwrite: bool,
    index_only: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Index and optionally download every dated EPSIS generator snapshot."""
    snapshot_dir = output_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    records = fetch_snapshot_index(session, timeout)
    add_snapshot_attachments(session, records, timeout)

    selected_records = records if limit is None else records[:limit]
    if not index_only:
        for position, record in enumerate(selected_records, start=1):
            download_snapshot(session, record, snapshot_dir, timeout, overwrite)
            print(
                f"Downloaded snapshot {position}/{len(selected_records)}: "
                f"{record['snapshot_date']} ({record['status']})"
            )

    columns = [
        "snapshot_date",
        "no_index",
        "display_number",
        "title",
        "author",
        "created_date",
        "modified_date",
        "view_count",
        "page_index",
        "attachment_filename",
        "attachment_url",
        "local_filename",
        "byte_count",
        "sha256",
        "status",
    ]
    for record in records:
        for column in columns:
            record.setdefault(column, "")
    write_csv(snapshot_dir / "snapshot_manifest.csv", columns, records)

    metadata = {
        "dataset": "KPX EPSIS dated generator roster snapshots",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "downloaded_or_reused_count": sum(bool(record["local_filename"]) for record in records),
        "index_only": index_only,
        "source_page_url": SNAPSHOT_PAGE_URL,
        "list_endpoint_url": SNAPSHOT_LIST_URL,
        "detail_endpoint_url": SNAPSHOT_DETAIL_URL,
    }
    (snapshot_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return records


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild normalized files only from preserved raw responses.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    annual = subparsers.add_parser("annual", help="Download annual rosters.")
    annual.add_argument("--start-year", type=int, default=FIRST_ANNUAL_YEAR)
    annual.add_argument("--end-year", type=int, default=LAST_ANNUAL_YEAR)

    generation = subparsers.add_parser(
        "annual-generation",
        help="Download annual mixed-granularity capacity and generation.",
    )
    generation.add_argument("--start-year", type=int, default=FIRST_GENERATION_YEAR)
    generation.add_argument("--end-year", type=int, default=LAST_ANNUAL_YEAR)

    snapshots = subparsers.add_parser("snapshots", help="Index/download dated snapshots.")
    snapshots.add_argument(
        "--index-only",
        action="store_true",
        help="Write the complete manifest without downloading ZIP attachments.",
    )
    snapshots.add_argument(
        "--limit",
        type=int,
        help="Download only the newest N attachments; the manifest still covers all snapshots.",
    )
    return parser


def main() -> None:
    """Run the requested EPSIS collection workflow."""
    args = build_parser().parse_args()
    if args.command == "annual":
        scrape_annual(
            output_dir=args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            timeout=args.timeout,
            overwrite=args.overwrite,
            offline=args.offline,
        )
    elif args.command == "annual-generation":
        scrape_annual_generation(
            output_dir=args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            timeout=args.timeout,
            overwrite=args.overwrite,
            offline=args.offline,
        )
    else:
        scrape_snapshots(
            output_dir=args.output_dir,
            timeout=args.timeout,
            overwrite=args.overwrite,
            index_only=args.index_only,
            limit=args.limit,
        )
