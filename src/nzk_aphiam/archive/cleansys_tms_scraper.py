"""
Scrape CleanSYS TMS real-time measurement data from data.go.kr.

Run from the project root:

    python -m nzk_aphiam.archive.cleansys_tms_scraper

Optional filters:

    python -m nzk_aphiam.archive.cleansys_tms_scraper \
        --area-nm 충남 \
        --fact-manage-nm 태안

Output:

    data/archive/raw/cleansys_tms/
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
import requests

from nzk_aphiam.config.paths import CLEANSYS_DIR

BASE_URL = "http://apis.data.go.kr/B552584/cleansys/rltmMesureResult"


def redact_service_key(url: str) -> str:
    """
    Return URL with serviceKey hidden so we do not leak the API key in logs.
    """
    parts = urlsplit(url)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)

    redacted_pairs = []
    for key, value in query_pairs:
        if key.lower() == "servicekey":
            redacted_pairs.append((key, "REDACTED"))
        else:
            redacted_pairs.append((key, value))

    redacted_query = urlencode(redacted_pairs, doseq=True)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            redacted_query,
            parts.fragment,
        )
    )


def get_service_key() -> str:
    """
    Load the data.go.kr API key from environment variables.
    """
    load_dotenv()

    service_key = os.getenv("DATA_GO_KR_API_KEY")

    if not service_key:
        raise ValueError(
            "DATA_GO_KR_API_KEY is missing. Add it to your .env file, but do not commit .env."
        )

    return service_key


def build_params(
    service_key: str,
    area_nm: str | None = None,
    fact_manage_nm: str | None = None,
    stack_code: str | None = None,
) -> dict[str, str]:
    """
    Build request parameters for the CleanSYS real-time TMS endpoint.
    """
    params = {
        "serviceKey": service_key,
        "type": "json",
    }

    if area_nm:
        params["areaNm"] = area_nm

    if fact_manage_nm:
        params["factManageNm"] = fact_manage_nm

    if stack_code:
        params["stackCode"] = stack_code

    return params


def fetch_cleansys_tms(
    params: dict[str, str],
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Fetch one CleanSYS TMS response.

    Raises a detailed error if the server returns an HTTP error or non-JSON body.
    """
    response = requests.get(BASE_URL, params=params, timeout=timeout)

    print(f"Request URL: {redact_service_key(response.url)}")
    print(f"Status code: {response.status_code}")

    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        print("Response preview:")
        print(response.text[:1000])
        raise error

    try:
        return response.json()
    except json.JSONDecodeError as error:
        print("Response was not valid JSON.")
        print("Response preview:")
        print(response.text[:1000])
        raise error


def make_output_path(
    out_dir: Path,
    area_nm: str | None = None,
    fact_manage_nm: str | None = None,
    stack_code: str | None = None,
) -> Path:
    """
    Create a timestamped raw JSON output path.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    pieces = ["cleansys_tms", timestamp]

    if area_nm:
        pieces.append(f"area-{area_nm}")

    if fact_manage_nm:
        pieces.append(f"facility-{fact_manage_nm}")

    if stack_code:
        pieces.append(f"stack-{stack_code}")

    filename = "__".join(pieces) + ".json"

    return out_dir / filename


def save_json(data: dict[str, Any], path: Path) -> None:
    """
    Save JSON with UTF-8 encoding so Korean text is preserved.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_metadata(
    metadata_path: Path,
    request_url_redacted: str,
    output_path: Path,
    params_without_key: dict[str, str],
) -> None:
    """
    Save a metadata sidecar file for reproducibility.
    """
    metadata = {
        "source": "data.go.kr",
        "dataset": "CleanSYS TMS real-time measurement result",
        "endpoint": BASE_URL,
        "request_url_redacted": request_url_redacted,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_path": str(output_path),
        "params_without_service_key": params_without_key,
    }

    save_json(metadata, metadata_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download CleanSYS TMS real-time measurement data from data.go.kr."
    )

    parser.add_argument(
        "--area-nm",
        type=str,
        default=None,
        help="Optional Korean area name filter, e.g. 충남, 서울, 전남.",
    )

    parser.add_argument(
        "--fact-manage-nm",
        type=str,
        default=None,
        help="Optional facility/company/plant name filter, e.g. 태안.",
    )

    parser.add_argument(
        "--stack-code",
        type=str,
        default=None,
        help="Optional stack code filter.",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=CLEANSYS_DIR,
        help="Directory where raw API responses should be saved.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    service_key = get_service_key()

    params = build_params(
        service_key=service_key,
        area_nm=args.area_nm,
        fact_manage_nm=args.fact_manage_nm,
        stack_code=args.stack_code,
    )

    data = fetch_cleansys_tms(params=params)

    output_path = make_output_path(
        out_dir=args.out_dir,
        area_nm=args.area_nm,
        fact_manage_nm=args.fact_manage_nm,
        stack_code=args.stack_code,
    )

    save_json(data, output_path)

    params_without_key = {
        key: value for key, value in params.items() if key.lower() != "servicekey"
    }

    redacted_url = redact_service_key(
        requests.Request("GET", BASE_URL, params=params).prepare().url
    )

    metadata_path = output_path.with_suffix(".metadata.json")

    save_metadata(
        metadata_path=metadata_path,
        request_url_redacted=redacted_url,
        output_path=output_path,
        params_without_key=params_without_key,
    )

    print(f"Saved raw response to: {output_path}")
    print(f"Saved metadata to: {metadata_path}")


if __name__ == "__main__":
    main()
