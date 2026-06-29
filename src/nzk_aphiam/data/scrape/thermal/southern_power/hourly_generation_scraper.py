"""Scrape Southern Power's independent hourly generation cross-check source."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd

from nzk_aphiam.data.scrape.thermal.southern_power import generation_scraper as common

DATASET_NAME = "한국남부발전(주)_시간대별 발전량및송전량 정보조회_GW"
DATASET_URL = "https://www.data.go.kr/data/15125317/openapi.do"
DEFAULT_API_URL = "https://apis.data.go.kr/B552520/PwrGenTran/getDataService"
API_URL_ENV = "SOUTHERN_POWER_HOURLY_GENERATION_API_URL"
DEFAULT_OUTPUT_DIR = common.DEFAULT_OUTPUT_DIR


def build_params(
    api_url: str,
    service_key: str,
    page: int,
    per_page: int,
    start_date: str,
    end_date: str,
    plant_code: str | None = None,
    unit_code: str | None = None,
) -> tuple[str, dict[str, str | int]]:
    """Build one hourly-source request without leaking embedded credentials."""
    base_url, params = common.split_url_params(api_url)
    for key in list(params):
        if key.lower() in common.SECRET_QUERY_KEYS:
            del params[key]
    params.update(
        {
            "serviceKey": service_key,
            "pageNo": page,
            "numOfRows": per_page,
            "strSdate": start_date,
            "strEdate": end_date,
        }
    )
    if plant_code:
        params["strOrgCd"] = plant_code
    if unit_code:
        params["strHoki"] = unit_code
    return base_url, params


def date_chunks(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split a request into API-safe intervals of at most one year."""
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    chunks: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=364))
        chunks.append((cursor.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def request_page(**kwargs: object):
    """Request one page using the hourly API's additional code filters."""
    extra_params = {}
    if kwargs.get("plant_code"):
        extra_params["strOrgCd"] = str(kwargs["plant_code"])
    if kwargs.get("unit_code"):
        extra_params["strHoki"] = str(kwargs["unit_code"])
    forwarded = {
        key: value for key, value in kwargs.items() if key not in {"plant_code", "unit_code"}
    }
    return common.request_page(**forwarded, extra_params=extra_params)


def fetch_all_pages(
    *,
    api_url: str,
    service_key: str,
    start_date: str,
    end_date: str,
    plant_code: str | None = None,
    unit_code: str | None = None,
    per_page: int = 10000,
    timeout: int = 60,
    retries: int = common.DEFAULT_RETRIES,
) -> tuple[list[dict[str, str]], list[object], list[str]]:
    """Fetch every page across one-year request chunks."""
    rows: list[dict[str, str]] = []
    pages: list[object] = []
    urls: list[str] = []
    for chunk_start, chunk_end in date_chunks(start_date, end_date):
        page = 1
        while True:
            root, url = request_page(
                api_url=api_url,
                service_key=service_key,
                page=page,
                per_page=per_page,
                start_date=chunk_start,
                end_date=chunk_end,
                plant_code=plant_code,
                unit_code=unit_code,
                timeout=timeout,
                retries=retries,
            )
            page_rows = common.extract_rows(root)
            rows.extend(page_rows)
            pages.append(root)
            urls.append(url)
            total = common.get_total_count(root)
            if (
                not page_rows
                or len(page_rows) < per_page
                or (total is not None and page * per_page >= total)
            ):
                break
            page += 1
    return rows, pages, urls


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--start-date", type=common.validate_date, default="20050101")
    parser.add_argument(
        "--end-date", type=common.validate_date, default=date.today().strftime("%Y%m%d")
    )
    parser.add_argument("--plant-code", default=None)
    parser.add_argument("--unit-code", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-page", type=int, default=10000)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=common.DEFAULT_RETRIES)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    load_dotenv()
    service_key = common.get_required_env(common.API_KEY_ENV)
    api_url = args.api_url or os.getenv(API_URL_ENV, DEFAULT_API_URL)
    rows, pages, urls = fetch_all_pages(
        api_url=api_url,
        service_key=service_key,
        start_date=args.start_date,
        end_date=args.end_date,
        plant_code=args.plant_code,
        unit_code=args.unit_code,
        per_page=args.per_page,
        timeout=args.timeout,
        retries=args.retries,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.out_dir / "southern_power_hourly_generation"
    common.save_xml_pages(pages, stem.with_suffix(".xml"))
    pd.DataFrame(rows).to_csv(stem.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    with stem.with_suffix(".metadata.json").open("w", encoding="utf-8") as file:
        json.dump(
            {
                "source": "data.go.kr",
                "dataset": DATASET_NAME,
                "dataset_url": DATASET_URL,
                "api_url_redacted": common.redact_url(api_url),
                "request_urls_redacted": urls,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "plant_code": args.plant_code,
                "unit_code": args.unit_code,
                "row_count": len(rows),
            },
            file,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Saved {len(rows)} hourly-source rows to {stem.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
