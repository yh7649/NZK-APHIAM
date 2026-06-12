"""
Scrape Korea Southern Power monthly air-pollutant emissions.

Source:
    https://www.data.go.kr/data/15099713/fileData.do

Required .env values:
    DATA_GO_KR_API_KEY=...
    SOUTHERN_POWER_EMISSIONS_API_URL=https://api.odcloud.kr/api/...

Run from the project root:
    python -m nzk_aphiam.data.scrape.thermal.southern_power.emissions_scraper
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
import pandas as pd
import requests

from nzk_aphiam.data.scrape.thermal.southern_power.provenance import (
    ENRICHMENT_SOURCES,
    FUEL_MAPPING_REFERENCE,
)

DATASET_NAME = "한국남부발전(주)_대기오염물질 배출량 현황"
DATASET_URL = "https://www.data.go.kr/data/15099713/fileData.do"
API_KEY_ENV = "DATA_GO_KR_API_KEY"
API_URL_ENV = "SOUTHERN_POWER_EMISSIONS_API_URL"
DEFAULT_PER_PAGE = 1000

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "power_generation" / "thermal" / "raw" / "southern_power"
)

SECRET_QUERY_KEYS = {"servicekey", "service_key", "apikey", "api_key", "key"}


def get_required_env(name: str) -> str:
    """Load a required environment variable from .env or the current shell."""
    load_dotenv()
    value = os.getenv(name)

    if not value:
        raise ValueError(f"{name} is missing. Add it to your .env file, but do not commit .env.")

    return value


def redact_url(url: str) -> str:
    """Hide API keys in a URL before printing or writing metadata."""
    parts = urlsplit(url)
    redacted_pairs = []

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        redacted_pairs.append((key, "REDACTED" if key.lower() in SECRET_QUERY_KEYS else value))

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


def build_params(
    api_url: str,
    service_key: str,
    page: int,
    per_page: int,
) -> tuple[str, dict[str, str | int]]:
    """Build parameters for the data.go.kr converted file-data API."""
    base_url, params = split_url_params(api_url)

    for key in list(params):
        if key.lower() in SECRET_QUERY_KEYS:
            del params[key]

    params.update(
        {
            "page": page,
            "perPage": per_page,
            "returnType": params.get("returnType", "JSON"),
            "serviceKey": service_key,
        }
    )
    return base_url, params


def request_page(
    api_url: str,
    service_key: str,
    page: int,
    per_page: int,
    timeout: int,
) -> tuple[dict[str, Any], str]:
    """Request one paginated JSON page."""
    base_url, params = build_params(api_url, service_key, page, per_page)
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
        print("Response preview:")
        print(response.text[:1000])
        raise RuntimeError(
            f"HTTP error for {redacted_request_url}: {response.status_code}"
        ) from error

    try:
        return response.json(), redacted_request_url
    except json.JSONDecodeError:
        print("Response was not valid JSON.")
        print("Response preview:")
        print(response.text[:1000])
        raise


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract records from an ODCloud response."""
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def get_total_count(payload: dict[str, Any]) -> int | None:
    """Read totalCount from an ODCloud response."""
    try:
        return int(payload["totalCount"])
    except (KeyError, TypeError, ValueError):
        return None


def fetch_all_pages(
    api_url: str,
    service_key: str,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int | None = None,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Fetch all pages without filtering or transforming source records."""
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    request_urls: list[str] = []
    page = 1
    total_count: int | None = None

    while True:
        payload, redacted_request_url = request_page(api_url, service_key, page, per_page, timeout)
        page_rows = extract_rows(payload)

        pages.append(payload)
        request_urls.append(redacted_request_url)
        rows.extend(page_rows)

        if total_count is None:
            total_count = get_total_count(payload)

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


def save_json(data: dict[str, Any], path: Path) -> None:
    """Save JSON with UTF-8 encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def save_csv(rows: Iterable[dict[str, Any]], path: Path) -> None:
    """Save source records to CSV without aggregation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download raw Korea Southern Power monthly emissions."
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help=f"API endpoint. Defaults to {API_URL_ENV} from .env.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where raw JSON, CSV, and metadata files are saved.",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=DEFAULT_PER_PAGE,
        help="Rows per page for the ODCloud API.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional page cap for smoke tests. The default downloads all pages.",
    )
    parser.add_argument("--timeout", type=int, default=30)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    service_key = get_required_env(API_KEY_ENV)
    api_url = args.api_url or get_required_env(API_URL_ENV)

    rows, pages, request_urls = fetch_all_pages(
        api_url=api_url,
        service_key=service_key,
        per_page=args.per_page,
        max_pages=args.max_pages,
        timeout=args.timeout,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_stem = args.out_dir / "southern_power_air_pollutant_emissions"
    raw_path = output_stem.with_suffix(".json")
    csv_path = output_stem.with_suffix(".csv")
    metadata_path = output_stem.with_suffix(".metadata.json")

    save_json(
        {
            "source": "data.go.kr",
            "dataset": DATASET_NAME,
            "dataset_url": DATASET_URL,
            "fuel_mapping_reference": FUEL_MAPPING_REFERENCE,
            "enrichment_sources": ENRICHMENT_SOURCES,
            "pages": pages,
        },
        raw_path,
    )
    save_csv(rows, csv_path)
    save_json(
        {
            "source": "data.go.kr",
            "dataset": DATASET_NAME,
            "dataset_url": DATASET_URL,
            "fuel_mapping_reference": FUEL_MAPPING_REFERENCE,
            "enrichment_sources": ENRICHMENT_SOURCES,
            "api_url_redacted": redact_url(api_url),
            "request_urls_redacted": request_urls,
            "row_count": len(rows),
            "output_json": str(raw_path),
            "output_csv": str(csv_path),
            "per_page": args.per_page,
            "max_pages": args.max_pages,
        },
        metadata_path,
    )

    print(f"Saved raw response to: {raw_path}")
    print(f"Saved CSV to: {csv_path}")
    print(f"Saved metadata to: {metadata_path}")
    print(f"Rows saved: {len(rows)}")


if __name__ == "__main__":
    main()
