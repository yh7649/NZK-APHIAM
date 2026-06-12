"""
Scrape Korea East-West Power monthly air-pollutant emissions and generation data.

Source:
    https://www.data.go.kr/data/15099768/fileData.do#tab-layer-openapi

Required .env values:
    DATA_GO_KR_API_KEY=...
    EASTWEST_POWER_API_URL=https://api.odcloud.kr/api/...

Run from the project root:
    python -m nzk_aphiam.data.scrape.thermal.eastwest_power
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
import pandas as pd
import requests

DATASET_NAME = "한국동서발전(주)_월별 대기오염물질 배출실적 및 발전량"
DATASET_URL = "https://www.data.go.kr/data/15099768/fileData.do#tab-layer-openapi"
API_KEY_ENV = "DATA_GO_KR_API_KEY"
API_URL_ENV = "EASTWEST_POWER_API_URL"
DEFAULT_PER_PAGE = 1000
FUEL_MAPPING_REFERENCE = "references/thermal/eastwest_power_energy_type_mapping.csv"
ENRICHMENT_SOURCES = [
    {
        "description": "East-West Power 2011 sustainability report: unit fuels",
        "url": "https://www.ewp.co.kr/kor/download/ewp_open/environ_2011.pdf",
    },
    {
        "description": "East-West Power 2016 sustainability report: fuels and emissions units",
        "url": "https://www.ewp.co.kr/kor/download/ewp_open/environ_2016.pdf",
    },
]

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "power_generation" / "thermal" / "raw" / "eastwest_power"
)

SECRET_QUERY_KEYS = {"servicekey", "service_key", "apikey", "api_key", "key"}


def get_required_env(name: str) -> str:
    """
    Load a required environment variable from .env or the current shell.
    """
    load_dotenv()
    value = os.getenv(name)

    if not value:
        raise ValueError(f"{name} is missing. Add it to your .env file, but do not commit .env.")

    return value


def redact_url(url: str) -> str:
    """
    Hide API keys in a URL before printing or writing metadata.
    """
    parts = urlsplit(url)
    redacted_pairs = []

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SECRET_QUERY_KEYS:
            redacted_pairs.append((key, "REDACTED"))
        else:
            redacted_pairs.append((key, value))

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
    """
    Split a URL into its base URL and query parameters.
    """
    parts = urlsplit(url)
    base_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    params = dict(parse_qsl(parts.query, keep_blank_values=True))

    return base_url, params


def build_params(
    api_url: str,
    service_key: str,
    page: int,
    per_page: int,
) -> tuple[str, dict[str, str | int]]:
    """
    Build params for data.go.kr converted file-data APIs.

    The generated API link from data.go.kr often includes returnType/page/perPage
    query params. We keep those URL params, then set page and perPage explicitly
    for pagination and put the API key in serviceKey from .env.
    """
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
    """
    Request one paginated JSON page.
    """
    base_url, params = build_params(
        api_url=api_url,
        service_key=service_key,
        page=page,
        per_page=per_page,
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
        print("Response preview:")
        print(response.text[:1000])
        raise RuntimeError(
            f"HTTP error for {redacted_request_url}: {response.status_code}"
        ) from error

    try:
        return response.json(), redacted_request_url
    except json.JSONDecodeError as error:
        print("Response was not valid JSON.")
        print("Response preview:")
        print(response.text[:1000])
        raise error


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract records from common data.go.kr JSON response shapes.
    """
    data = payload.get("data")

    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    body = payload.get("response", {}).get("body", {})
    items = body.get("items", {})

    if isinstance(items, dict):
        item = items.get("item", [])
    else:
        item = items

    if isinstance(item, dict):
        return [item]

    if isinstance(item, list):
        return [row for row in item if isinstance(row, dict)]

    return []


def get_total_count(payload: dict[str, Any]) -> int | None:
    """
    Read totalCount from converted file-data or older data.go.kr response shapes.
    """
    total_count = payload.get("totalCount")

    if total_count is None:
        total_count = payload.get("response", {}).get("body", {}).get("totalCount")

    if total_count is None:
        return None

    try:
        return int(total_count)
    except (TypeError, ValueError):
        return None


def fetch_all_pages(
    api_url: str,
    service_key: str,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int | None = None,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """
    Fetch every page and return rows, raw page payloads, and redacted request URLs.
    """
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    request_urls: list[str] = []
    page = 1
    total_count: int | None = None

    while True:
        payload, redacted_request_url = request_page(
            api_url=api_url,
            service_key=service_key,
            page=page,
            per_page=per_page,
            timeout=timeout,
        )
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


def make_output_stem(out_dir: Path) -> Path:
    """
    Create the output path stem used for json/csv/metadata files.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "eastwest_power_air_pollutants_generation"


def save_json(data: dict[str, Any], path: Path) -> None:
    """
    Save JSON with UTF-8 encoding so Korean text is preserved.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_csv(rows: Iterable[dict[str, Any]], path: Path) -> None:
    """
    Save extracted records to CSV.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Korea East-West Power emissions and generation data."
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
        help="Rows per page for the data.go.kr API.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional cap for smoke tests.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    service_key = get_required_env(API_KEY_ENV)
    api_url = args.api_url or get_required_env(API_URL_ENV)

    rows, pages, request_urls = fetch_all_pages(
        api_url=api_url,
        service_key=service_key,
        per_page=args.per_page,
        max_pages=args.max_pages,
        timeout=args.timeout,
    )

    output_stem = make_output_stem(args.out_dir)
    raw_path = output_stem.with_suffix(".json")
    csv_path = output_stem.with_suffix(".csv")
    metadata_path = output_stem.with_suffix(".metadata.json")

    raw_payload = {
        "source": "data.go.kr",
        "dataset": DATASET_NAME,
        "dataset_url": DATASET_URL,
        "fuel_mapping_reference": FUEL_MAPPING_REFERENCE,
        "enrichment_sources": ENRICHMENT_SOURCES,
        "pages": pages,
    }
    metadata = {
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
    }

    save_json(raw_payload, raw_path)
    save_csv(rows, csv_path)
    save_json(metadata, metadata_path)

    print(f"Saved raw response to: {raw_path}")
    print(f"Saved CSV to: {csv_path}")
    print(f"Saved metadata to: {metadata_path}")
    print(f"Rows saved: {len(rows)}")


if __name__ == "__main__":
    main()
