"""
Download Korea South-East Power daily air-pollutant emissions.

The data.go.kr listing redirects to a spreadsheet-like page on the provider's
website. That page exposes a signed CSV export form rather than an API.

Source:
    https://www.data.go.kr/data/15131510/fileData.do
    https://www.koenergy.kr/kosep/gv/nf/dt/nfdt16/main.do?menuCd=FN0912020205

Run from the project root:
    python -m nzk_aphiam.data.scrape.thermal.southeast_power
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import time
from typing import Any
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning

DATASET_NAME = "한국남동발전㈜_일자별 대기오염물질 배출 실적 현황"
DATASET_URL = "https://www.data.go.kr/data/15131510/fileData.do"
SOURCE_URL = "https://www.koenergy.kr/kosep/gv/nf/dt/nfdt16/main.do?menuCd=FN0912020205"
EXPORT_URL = "https://www.koenergy.kr/kosep/gv/nf/dt/nfdt16/csvDown.do"
MENU_CODE = "FN0912020205"
DEFAULT_START_DATE = "20150101"
SOURCE_ENCODING = "cp949"
EXPECTED_COLUMNS = ["사업소", "호기", "일자", "SOX", "NOX", "먼지", "산소", "유량", "온도"]
PLANT_CODES = {
    "ALL": "전체",
    "SP": "삼천포",
    "YH": "영흥",
    "YD": "영동",
    "YS": "여수",
    "BD": "분당",
}

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "power_generation" / "thermal" / "raw" / "southeast_power"
)


class FormFieldsParser(HTMLParser):
    """Collect input fields from one HTML form."""

    def __init__(self, form_id: str) -> None:
        super().__init__()
        self.form_id = form_id
        self.in_target_form = False
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)

        if tag == "form" and attributes.get("id") == self.form_id:
            self.in_target_form = True
            return

        if self.in_target_form and tag == "input":
            name = attributes.get("name")
            if name:
                self.fields[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self.in_target_form:
            self.in_target_form = False


def validate_date(value: str) -> str:
    """Validate an export date in YYYYMMDD form."""
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must use YYYYMMDD format.") from error
    return value


def build_year_ranges(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split an inclusive date range into calendar-year export requests."""
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    ranges = []
    current = start

    while current <= end:
        year_end = date(current.year, 12, 31)
        chunk_end = min(year_end, end)
        ranges.append((current.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        current = chunk_end + timedelta(days=1)

    return ranges


def extract_export_fields(html: str) -> dict[str, str]:
    """Extract the provider's signed export fields from the data form."""
    parser = FormFieldsParser("frmDefault")
    parser.feed(html)

    if "ptSignature" not in parser.fields:
        raise RuntimeError("Southeast Power export form signature was not found.")

    return parser.fields


def build_export_fields(
    form_fields: dict[str, str],
    start_date: str,
    end_date: str,
    plant_code: str,
) -> dict[str, str]:
    """Apply export filters while preserving provider-required hidden fields."""
    fields = dict(form_fields)
    fields.update(
        {
            "pageIndex": "1",
            "menuCd": MENU_CODE,
            "strOrgNo": plant_code,
            "strDateS": start_date,
            "strDateE": end_date,
        }
    )
    return fields


def parse_source_csv(content: bytes) -> tuple[list[str], list[list[str]]]:
    """Decode and validate the provider's CP949 CSV response."""
    try:
        text = content.decode(SOURCE_ENCODING)
    except UnicodeDecodeError as error:
        raise RuntimeError("Southeast Power CSV was not valid CP949.") from error

    parsed_rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text))
        if any(cell.strip() for cell in row)
    ]

    if not parsed_rows:
        raise RuntimeError("Southeast Power CSV response was empty.")

    columns = parsed_rows[0]
    if columns != EXPECTED_COLUMNS:
        raise RuntimeError(f"Unexpected Southeast Power CSV columns: {columns}")

    rows = parsed_rows[1:]
    invalid_widths = {len(row) for row in rows if len(row) != len(columns)}
    if invalid_widths:
        raise RuntimeError(f"Unexpected Southeast Power CSV row widths: {invalid_widths}")

    return columns, rows


def request_export(
    start_date: str,
    end_date: str,
    plant_code: str,
    timeout: int,
    verify_tls: bool,
) -> tuple[bytes, str, str]:
    """Load the signed form and submit its CSV export within one session."""
    session = requests.Session()
    session.verify = verify_tls
    session.headers["User-Agent"] = "NZK-APHIAM data scraper"

    with warnings.catch_warnings():
        if not verify_tls:
            warnings.simplefilter("ignore", InsecureRequestWarning)

        try:
            page_response = session.get(SOURCE_URL, timeout=timeout)
            page_response.raise_for_status()
            form_fields = extract_export_fields(page_response.text)
            export_fields = build_export_fields(
                form_fields=form_fields,
                start_date=start_date,
                end_date=end_date,
                plant_code=plant_code,
            )
            export_response = session.post(EXPORT_URL, data=export_fields, timeout=timeout)
            export_response.raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(
                f"Southeast Power export request failed: {error.__class__.__name__}"
            ) from None

    content_type = export_response.headers.get("Content-Type", "")
    if "text/csv" not in content_type.lower():
        preview = export_response.text[:500]
        raise RuntimeError(
            f"Expected a CSV export but received {content_type or 'unknown content type'}: "
            f"{preview}"
        )

    return export_response.content, page_response.url, export_response.url


def request_export_with_retries(
    start_date: str,
    end_date: str,
    plant_code: str,
    timeout: int,
    verify_tls: bool,
    attempts: int,
    retry_delay: float,
) -> tuple[bytes, str, str]:
    """Retry a complete signed-form export after transient provider failures."""
    for attempt in range(1, attempts + 1):
        try:
            return request_export(
                start_date=start_date,
                end_date=end_date,
                plant_code=plant_code,
                timeout=timeout,
                verify_tls=verify_tls,
            )
        except RuntimeError:
            if attempt == attempts:
                raise
            delay = retry_delay * attempt
            print(f"Export attempt {attempt} failed; retrying in {delay:g} seconds...")
            time.sleep(delay)

    raise AssertionError("Unreachable retry state.")


def save_raw(content: bytes, path: Path) -> None:
    """Preserve the exact provider response bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def save_utf8_csv(columns: list[str], rows: list[list[str]], path: Path) -> None:
    """Write a normalized UTF-8 CSV for analysis."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)


def save_json(data: dict[str, Any], path: Path) -> None:
    """Save metadata as UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Korea South-East Power daily air-pollutant emissions."
    )
    parser.add_argument(
        "--start-date",
        type=validate_date,
        default=DEFAULT_START_DATE,
        help="Inclusive YYYYMMDD start. Defaults to 20150101.",
    )
    parser.add_argument(
        "--end-date",
        type=validate_date,
        default=date.today().strftime("%Y%m%d"),
        help="Inclusive YYYYMMDD end. Defaults to today.",
    )
    parser.add_argument(
        "--plant",
        choices=tuple(PLANT_CODES),
        default="ALL",
        help="Plant code: ALL, SP, YH, YD, YS, or BD. Defaults to ALL.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where source CSV, UTF-8 CSV, and metadata are saved.",
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        help="Maximum export attempts per calendar-year chunk.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2,
        help="Base delay in seconds between export attempts.",
    )
    parser.add_argument(
        "--reuse-existing-source",
        action="store_true",
        help="Reuse existing yearly source CSV files to resume an interrupted run.",
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Require TLS certificate verification. The official site currently fails it.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.start_date > args.end_date:
        raise ValueError("--start-date must be on or before --end-date.")
    if args.attempts < 1:
        raise ValueError("--attempts must be at least 1.")
    if args.retry_delay < 0:
        raise ValueError("--retry-delay must be nonnegative.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_stem = args.out_dir / "southeast_power_daily_air_pollutant_emissions"
    csv_path = output_stem.with_suffix(".csv")
    metadata_path = output_stem.with_suffix(".metadata.json")
    columns = EXPECTED_COLUMNS
    rows: list[list[str]] = []
    chunks = []
    tls_warning_printed = False

    for chunk_start, chunk_end in reversed(build_year_ranges(args.start_date, args.end_date)):
        print(f"Processing {chunk_start} through {chunk_end}...")
        raw_path = output_stem.with_name(
            f"{output_stem.name}.source.{chunk_start}_{chunk_end}.csv"
        )

        if args.reuse_existing_source and raw_path.exists():
            print(f"Reusing source CSV: {raw_path}")
            content = raw_path.read_bytes()
            resolved_source_url = SOURCE_URL
            resolved_export_url = EXPORT_URL
        else:
            if not args.verify_tls and not tls_warning_printed:
                print(
                    "Warning: TLS verification is disabled for www.koenergy.kr because "
                    "the official site serves an incomplete certificate chain."
                )
                tls_warning_printed = True
            content, resolved_source_url, resolved_export_url = request_export_with_retries(
                start_date=chunk_start,
                end_date=chunk_end,
                plant_code="" if args.plant == "ALL" else args.plant,
                timeout=args.timeout,
                verify_tls=args.verify_tls,
                attempts=args.attempts,
                retry_delay=args.retry_delay,
            )
            save_raw(content, raw_path)

        chunk_columns, chunk_rows = parse_source_csv(content)
        rows.extend(chunk_rows)
        columns = chunk_columns
        chunks.append(
            {
                "start_date": chunk_start,
                "end_date": chunk_end,
                "row_count": len(chunk_rows),
                "source_url": resolved_source_url,
                "export_url": resolved_export_url,
                "output_source_csv": str(raw_path),
            }
        )
        print(f"Fetched {len(chunk_rows)} rows")

    actual_start_date = min((row[2] for row in rows), default=None)
    actual_end_date = max((row[2] for row in rows), default=None)
    coverage_warning = None
    if actual_start_date and actual_start_date > args.start_date:
        coverage_warning = (
            f"The provider returned no daily records before {actual_start_date}, "
            f"although data.go.kr advertises coverage from {args.start_date}."
        )
        print(f"Warning: {coverage_warning}")

    save_utf8_csv(columns, rows, csv_path)
    save_json(
        {
            "source": "Korea South-East Power website",
            "dataset": DATASET_NAME,
            "dataset_url": DATASET_URL,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "actual_start_date": actual_start_date,
            "actual_end_date": actual_end_date,
            "coverage_warning": coverage_warning,
            "plant_code": args.plant,
            "plant_name": PLANT_CODES[args.plant],
            "source_encoding": SOURCE_ENCODING,
            "tls_verification": args.verify_tls,
            "row_count": len(rows),
            "columns": columns,
            "chunks": chunks,
            "output_csv": str(csv_path),
        },
        metadata_path,
    )

    print(f"Saved {len(chunks)} source CSV files to: {args.out_dir}")
    print(f"Saved UTF-8 CSV to: {csv_path}")
    print(f"Saved metadata to: {metadata_path}")
    print(f"Rows saved: {len(rows)}")


if __name__ == "__main__":
    main()
