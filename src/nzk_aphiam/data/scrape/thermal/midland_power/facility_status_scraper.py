"""
Scrape Korea Midland Power facility air-status datasets from data.go.kr.

These datasets are separate from KOMIPO's monthly emissions API. Each facility
is published as an odcloud file-backed API with its own namespace and endpoint.

Run from the project root:
    python -m nzk_aphiam.data.scrape.thermal.midland_power facility-status
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import pandas as pd
import requests

from nzk_aphiam.data.scrape.thermal.midland_power.generation_scraper import (
    ensure_outputs_available,
    redact_url,
)

API_KEY_ENV = "DATA_GO_KR_API_KEY"
DEFAULT_PER_PAGE = 1000
PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "midland_power"
BASE_API_URL = "https://api.odcloud.kr/api"


@dataclass(frozen=True)
class FacilityStatusSpec:
    slug: str
    korean_name: str
    english_name: str
    namespace: str
    uddi: str
    usable_for_mass_derivation: bool

    @property
    def endpoint_path(self) -> str:
        return f"/{self.namespace}/v1/{self.uddi}"

    @property
    def api_url(self) -> str:
        return f"{BASE_API_URL}{self.endpoint_path}"


FACILITY_STATUS_SPECS = (
    FacilityStatusSpec(
        slug="boryeong",
        korean_name="보령발전소",
        english_name="Boryeong",
        namespace="15119110",
        uddi="uddi:b7d10202-d7a9-4aa2-b0e6-807dfb30bf1e",
        usable_for_mass_derivation=False,
    ),
    FacilityStatusSpec(
        slug="seoul",
        korean_name="서울발전소",
        english_name="Seoul",
        namespace="15119114",
        uddi="uddi:bc56ad0a-6e10-41ce-8e8c-c6255698855e",
        usable_for_mass_derivation=False,
    ),
    FacilityStatusSpec(
        slug="seocheon",
        korean_name="서천발전소",
        english_name="Seocheon",
        namespace="15154810",
        uddi="uddi:5c97905f-7574-485f-a133-f6f37459ac12",
        usable_for_mass_derivation=True,
    ),
    FacilityStatusSpec(
        slug="sejong",
        korean_name="세종발전소",
        english_name="Sejong",
        namespace="15155553",
        uddi="uddi:708cb5a2-9c9e-4362-9201-f468fb37b2c8",
        usable_for_mass_derivation=True,
    ),
    FacilityStatusSpec(
        slug="shin_boryeong",
        korean_name="신보령발전소",
        english_name="Shin-Boryeong",
        namespace="15119112",
        uddi="uddi:624cdbe1-81ea-4345-b9ee-ff4d7af1b4c4",
        usable_for_mass_derivation=False,
    ),
    FacilityStatusSpec(
        slug="jeju",
        korean_name="제주발전소",
        english_name="Jeju",
        namespace="15154638",
        uddi="uddi:f45cbb94-0a6b-443e-8b4a-82dbaff56d1f",
        usable_for_mass_derivation=True,
    ),
    FacilityStatusSpec(
        slug="incheon",
        korean_name="인천발전소",
        english_name="Incheon",
        namespace="15154818",
        uddi="uddi:08b5b074-ea1e-4d67-a8fc-da094295eb1d",
        usable_for_mass_derivation=True,
    ),
)
FACILITY_STATUS_BY_SLUG = {spec.slug: spec for spec in FACILITY_STATUS_SPECS}


def get_required_env(name: str) -> str:
    load_dotenv()
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is missing. Add it to your .env file, but do not commit .env.")
    return value


def request_page(
    spec: FacilityStatusSpec,
    service_key: str,
    page: int,
    per_page: int,
    timeout: int,
) -> tuple[dict[str, Any], str]:
    """Request one odcloud facility page."""
    params = {
        "page": page,
        "perPage": per_page,
        "returnType": "JSON",
        "serviceKey": service_key,
    }
    prepared_url = requests.Request("GET", spec.api_url, params=params).prepare().url
    redacted_request_url = redact_url(prepared_url)
    try:
        response = requests.get(spec.api_url, params=params, timeout=timeout)
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

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected non-object response for {redacted_request_url}.")
    if "code" in payload and payload.get("code") != 0:
        raise RuntimeError(
            f"Facility API error for {spec.slug}: {payload.get('msg') or payload.get('code')}"
        )
    return payload, redacted_request_url


def fetch_facility_records(
    spec: FacilityStatusSpec,
    service_key: str,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int | None = None,
    timeout: int = 60,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Fetch every page for one facility status dataset."""
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    request_urls: list[str] = []
    page = 1
    total_count: int | None = None

    while True:
        payload, request_url = request_page(
            spec=spec,
            service_key=service_key,
            page=page,
            per_page=per_page,
            timeout=timeout,
        )
        page_rows = payload.get("data") or []
        if not isinstance(page_rows, list):
            raise RuntimeError(f"Unexpected data payload for {spec.slug} page {page}.")

        pages.append(payload)
        request_urls.append(request_url)
        rows.extend(page_rows)
        if total_count is None:
            total_count = int(payload.get("totalCount") or 0)
        print(f"Fetched {spec.slug} page {page}: {len(page_rows)} rows")

        if not page_rows:
            break
        if total_count and len(rows) >= total_count:
            break
        if len(page_rows) < per_page:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1

    return rows, pages, request_urls


def annotate_rows(spec: FacilityStatusSpec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add facility provenance columns while preserving provider fields."""
    return [
        {
            "source_facility": spec.slug,
            "source_korean_facility_name": spec.korean_name,
            "source_english_facility_name": spec.english_name,
            "source_namespace": spec.namespace,
            "source_endpoint_path": spec.endpoint_path,
            "usable_for_mass_derivation": spec.usable_for_mass_derivation,
            **row,
        }
        for row in rows
    ]


def save_facility_outputs(
    spec: FacilityStatusSpec,
    rows: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    request_urls: list[str],
    output_dir: Path,
    overwrite: bool,
) -> pd.DataFrame:
    facility_dir = output_dir / "facilities" / spec.slug
    csv_path = facility_dir / f"{spec.slug}_air_status.csv"
    json_path = facility_dir / f"{spec.slug}_air_status.responses.json"
    metadata_path = facility_dir / f"{spec.slug}_air_status.metadata.json"
    ensure_outputs_available((csv_path, json_path, metadata_path), overwrite)
    facility_dir.mkdir(parents=True, exist_ok=True)

    annotated = annotate_rows(spec, rows)
    data = pd.DataFrame(annotated)
    data.to_csv(csv_path, index=False, encoding="utf-8")
    json_path.write_text(
        json.dumps(pages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(
            {
                "source": "data.go.kr odcloud",
                "dataset": f"한국중부발전(주)_{spec.korean_name} 대기상태 현황",
                "facility_slug": spec.slug,
                "facility_korean_name": spec.korean_name,
                "facility_english_name": spec.english_name,
                "namespace": spec.namespace,
                "endpoint_path": spec.endpoint_path,
                "api_url_redacted": spec.api_url,
                "request_urls_redacted": request_urls,
                "row_count": len(data),
                "usable_for_mass_derivation": spec.usable_for_mass_derivation,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "output_csv": str(csv_path),
                "output_json": str(json_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(data)} {spec.slug} rows to {csv_path}")
    return data


def save_merged(data: pd.DataFrame, output_dir: Path, overwrite: bool) -> Path:
    output_path = output_dir / "facilities" / "midland_power_facility_air_status.csv"
    ensure_outputs_available((output_path,), overwrite)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(output_path, index=False, encoding="utf-8")
    print(f"Saved {len(data)} merged facility rows to {output_path}")
    return output_path


def selected_specs(slugs: Sequence[str] | None) -> list[FacilityStatusSpec]:
    if not slugs:
        return list(FACILITY_STATUS_SPECS)
    unknown = sorted(set(slugs) - set(FACILITY_STATUS_BY_SLUG))
    if unknown:
        raise ValueError(f"Unknown Midland facility slug(s): {unknown}")
    return [FACILITY_STATUS_BY_SLUG[slug] for slug in slugs]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download raw KOMIPO facility air-status datasets."
    )
    parser.add_argument(
        "--facility",
        action="append",
        choices=tuple(FACILITY_STATUS_BY_SLUG),
        help="Facility slug to fetch. Repeat to fetch multiple facilities.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    service_key = get_required_env(API_KEY_ENV)
    frames = []
    for spec in selected_specs(args.facility):
        rows, pages, request_urls = fetch_facility_records(
            spec=spec,
            service_key=service_key,
            per_page=args.per_page,
            max_pages=args.max_pages,
            timeout=args.timeout,
        )
        frames.append(
            save_facility_outputs(
                spec=spec,
                rows=rows,
                pages=pages,
                request_urls=request_urls,
                output_dir=args.out_dir,
                overwrite=args.overwrite,
            )
        )

    merged = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    save_merged(merged, args.out_dir, args.overwrite)


if __name__ == "__main__":
    main()
