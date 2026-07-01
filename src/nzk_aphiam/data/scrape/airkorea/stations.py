"""Archive the official AirKorea current station registry from data.go.kr."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nzk_aphiam.config.paths import AIRKOREA_STATION_RAW_DIR, PROJECT_ROOT

API_KEY_ENV = "DATA_GO_KR_API_KEY"
ENDPOINT = "https://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getMsrstnList"
SOURCE_PAGE = "https://www.data.go.kr/data/15073877/openapi.do"
DEFAULT_OUTPUT = AIRKOREA_STATION_RAW_DIR / "airkorea_station_registry_current.csv"


class StationApiError(RuntimeError):
    """Credential, transport, or response-schema failure from the station API."""


def get_api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = unquote(os.getenv(API_KEY_ENV, "").strip())
    if not key:
        raise ValueError(f"{API_KEY_ENV} is missing. Add it to .env without committing the key.")
    return key


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "NZK-APHIAM AirKorea station registry collector"})
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1,
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET"},
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def request_page(
    session: requests.Session, api_key: str, page: int, rows: int, timeout: int
) -> tuple[list[dict[str, object]], int]:
    """Fetch one JSON page without including the credential in failures."""
    try:
        response = session.get(
            ENDPOINT,
            params={
                "serviceKey": api_key,
                "returnType": "json",
                "numOfRows": rows,
                "pageNo": page,
            },
            timeout=timeout,
        )
    except requests.RequestException as error:
        raise StationApiError(
            f"AirKorea station API request failed: {error.__class__.__name__}"
        ) from None
    if response.status_code != 200:
        raise StationApiError(
            f"AirKorea station API returned HTTP {response.status_code}. "
            "Confirm that dataset 15073877 is active for DATA_GO_KR_API_KEY."
        )
    try:
        payload = response.json()["response"]
        header = payload["header"]
        body = payload["body"]
    except (KeyError, TypeError, ValueError, requests.JSONDecodeError):
        raise StationApiError(
            "AirKorea station API returned an unexpected non-JSON schema."
        ) from None
    if str(header.get("resultCode")) != "00":
        raise StationApiError(f"AirKorea station API error: {header.get('resultMsg', 'unknown')}")
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item", [])
    if not isinstance(items, list):
        raise StationApiError("AirKorea station API returned an unexpected items schema.")
    return items, int(body.get("totalCount", len(items)))


def fetch_registry(
    api_key: str, timeout: int = 60, page_size: int = 1000, session: requests.Session | None = None
) -> pd.DataFrame:
    """Download all current stations and standardize documented coordinate fields."""
    client = session or build_session()
    records: list[dict[str, object]] = []
    page = 1
    total = 1
    while len(records) < total:
        items, total = request_page(client, api_key, page, page_size, timeout)
        records.extend(items)
        if not items:
            break
        page += 1
    frame = pd.DataFrame(records)
    required = {"stationName", "addr", "dmX", "dmY"}
    missing = required.difference(frame.columns)
    if missing:
        raise StationApiError(f"AirKorea station API omitted required fields: {sorted(missing)}")
    frame = frame.rename(
        columns={
            "stationName": "station_name",
            "addr": "address",
            "year": "installation_year",
            "mangName": "network_name",
            "item": "pollutants_reported",
            # The official API documents dmX as latitude and dmY as longitude.
            "dmX": "latitude",
            "dmY": "longitude",
        }
    )
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    valid = frame["latitude"].between(32, 39.5) & frame["longitude"].between(124, 132)
    frame.loc[~valid, ["latitude", "longitude"]] = pd.NA
    frame["registry_retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
    return frame.drop_duplicates().reset_index(drop=True)


def save_registry(frame: pd.DataFrame, path: Path, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Station registry already exists: {path}; use --overwrite to replace it"
        )
    temporary = path.with_suffix(path.suffix + ".part")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)
    digest = sha256(path.read_bytes()).hexdigest()
    metadata = {
        "dataset": "Korea Environment Corporation AirKorea station information",
        "source_page_url": SOURCE_PAGE,
        "api_endpoint": ENDPOINT,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "credential_env": API_KEY_ENV,
        "rows": len(frame),
        "sha256": digest,
        "coordinate_note": "API dmX is WGS84 latitude; dmY is WGS84 longitude.",
    }
    path.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive the current AirKorea station registry.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    registry = fetch_registry(get_api_key(), timeout=args.timeout)
    save_registry(registry, args.output, args.overwrite)
    print(f"Saved {len(registry)} AirKorea stations to {args.output}")


if __name__ == "__main__":
    main()
