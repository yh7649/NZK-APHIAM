"""Scrape KHNP's rolling daily generation/transmission records.

The source returns roughly six recent days of hourly generator observations.
Repeated runs merge that rolling window into month snapshots, from which the
generation panel calculates monthly MWh.

Run from the project root:
    PYTHONPATH=src python -m nzk_aphiam.data.scrape.thermal.khnp
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
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

DATASET_NAME = "한국수력원자력(주)_한수원 전원 별 송전량 정보"
DATASET_URL = "https://www.data.go.kr/data/15157705/openapi.do"
API_KEY_ENV = "DATA_GO_KR_API_KEY"
API_URL_ENV = "KHNP_GENERATION_API_URL"
DEFAULT_API_URL = "https://apis.data.go.kr/B552041/scrap/getscrap"
DATE_COLUMN = "tradeDt"
DATE_FORMAT = "%Y%m%d"

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "khnp"
OUTPUT_STEM = "khnp_daily_generation"
SECRET_QUERY_KEYS = {"servicekey", "service_key", "apikey", "api_key", "key"}


def get_required_env(name: str) -> str:
    """Load a required environment variable from .env or the shell."""
    load_dotenv()
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is missing. Add it to .env, but do not commit .env.")
    return value


def get_api_url() -> str:
    load_dotenv()
    return os.getenv(API_URL_ENV, DEFAULT_API_URL)


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, "REDACTED" if key.lower() in SECRET_QUERY_KEYS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def parse_response(xml_content: str | bytes) -> ET.Element:
    """Parse a KHNP XML response and validate its result code."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as error:
        raise RuntimeError("KHNP generation response was not valid XML.") from error
    code = root.findtext("./header/resultCode")
    message = root.findtext("./header/resultMsg")
    if code != "00":
        raise RuntimeError(f"KHNP API error {code or 'UNKNOWN'}: {message or 'No message'}")
    return root


def extract_rows(root: ET.Element) -> list[dict[str, str]]:
    return [
        {child.tag: child.text or "" for child in item}
        for item in root.findall("./body/items/item")
    ]


def request_generation(api_url: str, service_key: str, timeout: int) -> tuple[ET.Element, str]:
    """Fetch the source's complete rolling window once."""
    parts = urlsplit(api_url)
    base_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key in list(params):
        if key.lower() in SECRET_QUERY_KEYS:
            del params[key]
    params["serviceKey"] = service_key
    prepared = requests.Request("GET", base_url, params=params).prepare().url
    redacted = redact_url(prepared)
    try:
        response = requests.get(base_url, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Request failed for {redacted}: {error.__class__.__name__}") from error
    print(f"Request URL: {redacted}")
    print(f"Status code: {response.status_code}")
    return parse_response(response.content), redacted


def save_xml(root: ET.Element, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def merge_with_collected_history(rows: pd.DataFrame, combined_path: Path) -> pd.DataFrame:
    """Retain days that have fallen out of KHNP's rolling response window."""
    if not combined_path.exists():
        return rows
    existing = pd.read_csv(combined_path, encoding="utf-8-sig", dtype="string")
    columns = list(dict.fromkeys([*existing.columns, *rows.columns]))
    merged = pd.concat(
        [existing.reindex(columns=columns), rows.reindex(columns=columns)], ignore_index=True
    )
    identity = [column for column in ("tradeDt", "genCd") if column in merged]
    return merged.drop_duplicates(subset=identity, keep="last").reset_index(drop=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download KHNP rolling generation records.")
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace the latest raw XML and metadata files."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    stem = args.out_dir / OUTPUT_STEM
    raw_path = stem.with_suffix(".xml")
    metadata_path = stem.with_suffix(".metadata.json")
    existing = [path for path in (raw_path, metadata_path) if path.exists()]
    if existing and not args.overwrite:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Output already exists: {joined}. Use --overwrite to replace it.")

    api_url = args.api_url or get_api_url()
    root, request_url = request_generation(api_url, get_required_env(API_KEY_ENV), args.timeout)
    new_rows = pd.DataFrame(extract_rows(root), dtype="string")
    if new_rows.empty:
        raise RuntimeError("KHNP generation request returned no records; no files written.")
    if DATE_COLUMN not in new_rows:
        raise RuntimeError(f"KHNP response did not contain required {DATE_COLUMN!r} values.")

    rows = merge_with_collected_history(new_rows, stem.with_suffix(".csv"))
    save_xml(root, raw_path)
    summary = save_period_snapshots(
        rows,
        date_column=DATE_COLUMN,
        date_format=DATE_FORMAT,
        output_dir=args.out_dir,
        stem=OUTPUT_STEM,
        granularity="month",
    )
    dates = pd.to_datetime(new_rows[DATE_COLUMN], format=DATE_FORMAT)
    save_json(
        {
            "source": "data.go.kr",
            "dataset": DATASET_NAME,
            "dataset_url": DATASET_URL,
            "api_url_redacted": redact_url(api_url),
            "request_url_redacted": request_url,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "response_start_date": dates.min().date().isoformat(),
            "response_end_date": dates.max().date().isoformat(),
            "response_row_count": len(new_rows),
            "collected_row_count": len(rows),
            "output_xml": str(raw_path),
            "output_csv": str(summary.combined_path),
            "period_snapshots": summary.to_metadata_dict(),
            "notes": "The API returns a rolling daily window and ignores date/pagination parameters.",
        },
        metadata_path,
    )
    print(f"Saved raw response to: {raw_path}")
    print(f"Saved CSV to: {summary.combined_path}")
    print(f"Saved metadata to: {metadata_path}")
    print(f"Rows in rolling response: {len(new_rows)}; rows collected: {len(rows)}")


if __name__ == "__main__":
    main()
