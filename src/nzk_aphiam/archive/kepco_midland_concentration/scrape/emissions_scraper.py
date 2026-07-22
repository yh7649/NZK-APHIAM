"""
Scrape Korea Midland Power monthly air-pollutant emissions records.

Source:
    https://www.data.go.kr/data/15084758/openapi.do

Required .env value:
    DATA_GO_KR_API_KEY=...

Run from the project root:
    python -m nzk_aphiam.archive.kepco_midland_concentration.scrape emissions
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
import pandas as pd
import requests

from nzk_aphiam.config.paths import ARCHIVE_RAW_DIR
from nzk_aphiam.data.scrape.common.period_snapshot import save_period_snapshots
from nzk_aphiam.data.scrape.thermal.midland_power.generation_scraper import (
    ensure_outputs_available,
    redact_url,
    save_json,
    save_xml_responses,
)

DATASET_NAME = "한국중부발전(주)_대기오염물질배출 조회서비스"
DATASET_URL = "https://www.data.go.kr/data/15084758/openapi.do"
API_KEY_ENV = "DATA_GO_KR_API_KEY"
API_URL_ENV = "MIDLAND_POWER_EMISSIONS_API_URL"
DEFAULT_API_URL = "https://apis.data.go.kr/B552521/airDischarge/getData"
DATE_COLUMN = "ym"
DATE_FORMAT = "%Y%m"
DEFAULT_START_MONTH = "201201"

DEFAULT_OUTPUT_DIR = ARCHIVE_RAW_DIR / "kepco_midland_concentration"


def get_required_env(name: str) -> str:
    load_dotenv()
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is missing. Add it to your .env file, but do not commit .env.")
    return value


def get_api_url() -> str:
    load_dotenv()
    return os.getenv(API_URL_ENV, DEFAULT_API_URL)


def validate_month(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m")
    except ValueError as error:
        raise argparse.ArgumentTypeError("Month must use YYYYMM format.") from error
    return value


def build_params(
    api_url: str,
    service_key: str,
    start_month: str,
    end_month: str,
    plant_code: str | None = None,
    unit_code: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Build one emissions request, retaining non-secret URL parameters."""
    parts = urlsplit(api_url)
    base_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    params = {
        key: value
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"servicekey", "service_key", "apikey", "api_key", "key"}
    }
    params.update(
        {
            "ServiceKey": service_key,
            "strDateS": start_month,
            "strDateE": end_month,
        }
    )
    if plant_code is not None:
        params["strOrgNo"] = plant_code
    if unit_code is not None:
        params["strHoki"] = unit_code
    return base_url, params


def parse_response(xml_content: str | bytes) -> ET.Element:
    """Parse one XML response and validate the API result code."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as error:
        raise RuntimeError("Midland Power emissions response was not valid XML.") from error

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
    value = root.findtext("./header/totalCount")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def request_records(
    api_url: str,
    service_key: str,
    start_month: str,
    end_month: str,
    timeout: int,
    plant_code: str | None = None,
    unit_code: str | None = None,
) -> tuple[ET.Element, str]:
    """Request and parse one emissions response."""
    base_url, params = build_params(
        api_url=api_url,
        service_key=service_key,
        start_month=start_month,
        end_month=end_month,
        plant_code=plant_code,
        unit_code=unit_code,
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


def fetch_records(
    api_url: str,
    service_key: str,
    start_month: str,
    end_month: str,
    timeout: int = 60,
    plant_codes: Sequence[str] | None = None,
    unit_code: str | None = None,
) -> tuple[list[dict[str, str]], list[ET.Element], list[str]]:
    """Fetch emissions for an unfiltered request or each requested plant."""
    filters: list[str | None] = list(plant_codes) if plant_codes else [None]
    rows: list[dict[str, str]] = []
    responses: list[ET.Element] = []
    request_urls: list[str] = []

    for plant_code in filters:
        root, request_url = request_records(
            api_url=api_url,
            service_key=service_key,
            start_month=start_month,
            end_month=end_month,
            timeout=timeout,
            plant_code=plant_code,
            unit_code=unit_code,
        )
        response_rows = extract_rows(root)
        total_count = get_total_count(root)
        if total_count is not None and total_count != len(response_rows):
            raise RuntimeError(
                f"Midland Power emissions response reported {total_count} records "
                f"but contained {len(response_rows)}."
            )
        print(f"Fetched plant {plant_code or 'all'}: {len(response_rows)} rows")
        rows.extend(response_rows)
        responses.append(root)
        request_urls.append(request_url)

    return rows, responses, request_urls


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download raw Korea Midland Power monthly emissions records."
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
    parser.add_argument(
        "--plant-code",
        action="append",
        default=None,
        help="Optional provider plant code. Repeat to query multiple plants.",
    )
    parser.add_argument("--unit-code", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
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

    output_stem = args.out_dir / "midland_power_air_pollutant_emissions"
    raw_path = output_stem.with_suffix(".xml")
    metadata_path = output_stem.with_suffix(".metadata.json")
    # The CSV is no longer guarded here: save_period_snapshots() only ever
    # touches a period file when its content actually changed, so repeated
    # runs are already safe by construction. The raw XML and metadata are
    # still single cumulative files, so they keep the explicit guard.
    ensure_outputs_available((raw_path, metadata_path), args.overwrite)

    rows, responses, request_urls = fetch_records(
        api_url=args.api_url or get_api_url(),
        service_key=get_required_env(API_KEY_ENV),
        start_month=args.start_month,
        end_month=args.end_month,
        timeout=args.timeout,
        plant_codes=args.plant_code,
        unit_code=args.unit_code,
    )
    if not rows:
        raise RuntimeError(
            "Midland Power emissions request returned no records; no files written."
        )

    save_xml_responses(responses, raw_path)

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
            "plant_codes": args.plant_code,
            "unit_code": args.unit_code,
            "row_count": len(rows),
            "output_xml": str(raw_path),
            "output_csv": str(snapshot_summary.combined_path),
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
