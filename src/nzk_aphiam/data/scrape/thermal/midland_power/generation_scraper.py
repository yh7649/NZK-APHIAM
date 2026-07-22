"""
Scrape Korea Midland Power monthly generation records.

Source:
    https://www.data.go.kr/data/15084753/openapi.do

Required .env value:
    DATA_GO_KR_API_KEY=...

Run from the project root:
    python -m nzk_aphiam.data.scrape.thermal.midland_power
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from datetime import date, datetime
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
import pandas as pd
import requests

from nzk_aphiam.data.scrape.common.period_snapshot import save_period_snapshots

DATASET_NAME = "한국중부발전(주)_발전실적조회 서비스"
DATASET_URL = "https://www.data.go.kr/data/15084753/openapi.do"
API_KEY_ENV = "DATA_GO_KR_API_KEY"
API_URL_ENV = "MIDLAND_POWER_GENERATION_API_URL"
DEFAULT_API_URL = "https://apis.data.go.kr/B552521/resultPlant/getData"
DATE_COLUMN = "ym"
DATE_FORMAT = "%Y%m"
DEFAULT_START_MONTH = "201201"
DEFAULT_PER_PAGE = 1000

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "kepco_subsidiaries" / "midland_power"

SECRET_QUERY_KEYS = {"servicekey", "service_key", "apikey", "api_key", "key"}


def get_required_env(name: str) -> str:
    """Load a required environment variable from .env or the current shell."""
    load_dotenv()
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is missing. Add it to your .env file, but do not commit .env.")
    return value


def get_api_url() -> str:
    """Use an optional environment override or the documented endpoint."""
    load_dotenv()
    return os.getenv(API_URL_ENV, DEFAULT_API_URL)


def redact_url(url: str) -> str:
    """Hide API keys in a URL before printing or writing metadata."""
    parts = urlsplit(url)
    redacted_pairs = [
        (key, "REDACTED" if key.lower() in SECRET_QUERY_KEYS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(redacted_pairs, doseq=True),
            parts.fragment,
        )
    )


def split_url_params(url: str) -> tuple[str, dict[str, str]]:
    """Split a URL into its base URL and query parameters."""
    parts = urlsplit(url)
    base_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    return base_url, dict(parse_qsl(parts.query, keep_blank_values=True))


def validate_month(value: str) -> str:
    """Validate an API month in YYYYMM form."""
    try:
        datetime.strptime(value, "%Y%m")
    except ValueError as error:
        raise argparse.ArgumentTypeError("Month must use YYYYMM format.") from error
    return value


def build_params(
    api_url: str,
    service_key: str,
    page: int,
    per_page: int,
    start_month: str,
    end_month: str,
    plant_code: str | None = None,
    unit_start: str | None = None,
    unit_end: str | None = None,
) -> tuple[str, dict[str, str | int]]:
    """Build one monthly generation request."""
    base_url, params = split_url_params(api_url)
    for key in list(params):
        if key.lower() in SECRET_QUERY_KEYS:
            del params[key]

    params.update(
        {
            "ServiceKey": service_key,
            "pageNo": page,
            "numOfRows": per_page,
            "strDateS": start_month,
            "strDateE": end_month,
        }
    )
    optional = {
        "strOrgNo": plant_code,
        "strHokiS": unit_start,
        "strHokiE": unit_end,
    }
    params.update({key: value for key, value in optional.items() if value is not None})
    return base_url, params


def parse_response(xml_content: str | bytes) -> ET.Element:
    """Parse one XML response and validate the API result code."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as error:
        raise RuntimeError("Midland Power generation response was not valid XML.") from error

    result_code = root.findtext("./header/resultCode")
    result_message = root.findtext("./header/resultMsg")
    if result_code != "00":
        raise RuntimeError(
            f"Midland Power API error {result_code or 'UNKNOWN'}: {result_message or 'No message'}"
        )
    return root


def extract_rows(root: ET.Element) -> list[dict[str, str]]:
    """Extract source records without changing their values."""
    return [
        {child.tag: child.text or "" for child in item}
        for item in root.findall("./body/items/item")
    ]


def get_total_count(root: ET.Element) -> int | None:
    """Read the source pagination total."""
    value = root.findtext("./header/totalCount")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def request_page(
    api_url: str,
    service_key: str,
    page: int,
    per_page: int,
    start_month: str,
    end_month: str,
    timeout: int,
    plant_code: str | None = None,
    unit_start: str | None = None,
    unit_end: str | None = None,
) -> tuple[ET.Element, str]:
    """Request and parse one generation page."""
    base_url, params = build_params(
        api_url=api_url,
        service_key=service_key,
        page=page,
        per_page=per_page,
        start_month=start_month,
        end_month=end_month,
        plant_code=plant_code,
        unit_start=unit_start,
        unit_end=unit_end,
    )
    prepared_url = requests.Request("GET", base_url, params=params).prepare().url
    redacted_request_url = redact_url(prepared_url)

    try:
        response = requests.get(base_url, params=params, timeout=timeout)
    except requests.RequestException as error:
        raise RuntimeError(
            f"Request failed for {redacted_request_url}: {error.__class__.__name__}"
        ) from None

    print(f"Request URL: {redacted_request_url}")
    print(f"Status code: {response.status_code}")
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        print(response.text[:1000])
        raise RuntimeError(
            f"HTTP error for {redacted_request_url}: {response.status_code}"
        ) from error

    return parse_response(response.content), redacted_request_url


def fetch_all_pages(
    api_url: str,
    service_key: str,
    start_month: str,
    end_month: str,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int | None = None,
    timeout: int = 60,
    plant_code: str | None = None,
    unit_start: str | None = None,
    unit_end: str | None = None,
) -> tuple[list[dict[str, str]], list[ET.Element], list[str]]:
    """Fetch all generation pages in the requested month range."""
    rows: list[dict[str, str]] = []
    pages: list[ET.Element] = []
    request_urls: list[str] = []
    page = 1
    total_count: int | None = None

    while True:
        root, request_url = request_page(
            api_url=api_url,
            service_key=service_key,
            page=page,
            per_page=per_page,
            start_month=start_month,
            end_month=end_month,
            timeout=timeout,
            plant_code=plant_code,
            unit_start=unit_start,
            unit_end=unit_end,
        )
        page_rows = extract_rows(root)
        pages.append(root)
        request_urls.append(request_url)
        rows.extend(page_rows)

        if total_count is None:
            total_count = get_total_count(root)
        print(f"Fetched page {page}: {len(page_rows)} rows")

        if not page_rows:
            break
        if total_count is not None and len(rows) >= total_count:
            break
        if len(page_rows) < per_page:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1

    return rows, pages, request_urls


def save_xml_responses(responses: Iterable[ET.Element], path: Path) -> None:
    """Save all source responses beneath one XML document root."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document_root = ET.Element("responses")
    for response_number, response in enumerate(responses, start=1):
        response.set("responseNumber", str(response_number))
        document_root.append(response)
    ET.indent(document_root, space="  ")
    ET.ElementTree(document_root).write(path, encoding="utf-8", xml_declaration=True)


def save_json(data: dict[str, Any], path: Path) -> None:
    """Save metadata as UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def ensure_outputs_available(paths: Iterable[Path], overwrite: bool) -> None:
    """Protect previously downloaded raw files from accidental replacement."""
    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Output already exists: {joined}. Use --overwrite to replace it.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download raw Korea Midland Power monthly generation records."
    )
    parser.add_argument("--api-url", default=None)
    parser.add_argument(
        "--start-month",
        type=validate_month,
        default=DEFAULT_START_MONTH,
        help="Inclusive YYYYMM start.",
    )
    parser.add_argument(
        "--end-month",
        type=validate_month,
        default=date.today().strftime("%Y%m"),
        help="Inclusive YYYYMM end. Defaults to the current month.",
    )
    parser.add_argument("--plant-code", default=None)
    parser.add_argument("--unit-start", default=None)
    parser.add_argument("--unit-end", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly allow replacement of existing Midland output files.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.start_month > args.end_month:
        raise ValueError("--start-month must be on or before --end-month.")
    if (args.unit_start is None) != (args.unit_end is None):
        raise ValueError("--unit-start and --unit-end must be supplied together.")

    output_stem = args.out_dir / "midland_power_monthly_generation"
    raw_path = output_stem.with_suffix(".xml")
    metadata_path = output_stem.with_suffix(".metadata.json")
    # The CSV is no longer guarded here: save_period_snapshots() only ever
    # touches a period file when its content actually changed, so repeated
    # runs are already safe by construction. The raw XML and metadata are
    # still single cumulative files, so they keep the explicit guard.
    ensure_outputs_available((raw_path, metadata_path), args.overwrite)

    rows, pages, request_urls = fetch_all_pages(
        api_url=args.api_url or get_api_url(),
        service_key=get_required_env(API_KEY_ENV),
        start_month=args.start_month,
        end_month=args.end_month,
        per_page=args.per_page,
        timeout=args.timeout,
        plant_code=args.plant_code,
        unit_start=args.unit_start,
        unit_end=args.unit_end,
    )
    if not rows:
        raise RuntimeError(
            "Midland Power generation request returned no records; no files written."
        )

    save_xml_responses(pages, raw_path)

    snapshot_summary = save_period_snapshots(
        pd.DataFrame(rows),
        date_column=DATE_COLUMN,
        date_format=DATE_FORMAT,
        output_dir=args.out_dir,
        stem=output_stem.name,
    )

    save_json(
        {
            "source": "data.go.kr",
            "dataset": DATASET_NAME,
            "dataset_url": DATASET_URL,
            "api_url_redacted": redact_url(args.api_url or get_api_url()),
            "request_urls_redacted": request_urls,
            "start_month": args.start_month,
            "end_month": args.end_month,
            "plant_code": args.plant_code,
            "unit_start": args.unit_start,
            "unit_end": args.unit_end,
            "row_count": len(rows),
            "output_xml": str(raw_path),
            "output_csv": str(snapshot_summary.combined_path),
            "per_page": args.per_page,
            "period_snapshots": snapshot_summary.to_metadata_dict(),
        },
        metadata_path,
    )
    print(f"Saved raw responses to: {raw_path}")
    print(f"Saved CSV to: {snapshot_summary.combined_path}")
    print(f"Saved metadata to: {metadata_path}")
    print(f"Rows saved: {len(rows)}")
    if snapshot_summary.revisions:
        print(
            f"NOTE: {len(snapshot_summary.revisions)} historic period(s) were revised "
            "by the source -- see warnings above and the metadata file."
        )


if __name__ == "__main__":
    main()
