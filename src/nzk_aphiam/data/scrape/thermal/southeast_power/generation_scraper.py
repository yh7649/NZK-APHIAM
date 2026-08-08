"""Download KOEN monthly unit-level generation from its public signed CSV form.

The same dataset is registered as a data.go.kr OpenAPI at:
https://www.data.go.kr/data/15120379/openapi.do
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
from datetime import date, datetime
import io
from pathlib import Path
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning

from nzk_aphiam.config.paths import PROJECT_ROOT
from nzk_aphiam.data.scrape.thermal.southeast_power.scraper import (
    FormFieldsParser,
    save_json,
    save_raw,
)

DATASET_NAME = "한국남동발전㈜_발전실적 현황"
DATASET_URL = "https://www.data.go.kr/data/15120379/openapi.do"
API_BASE_URL = "https://apis.data.go.kr/B551893/ndod-gen-perform"
SOURCE_URL = "https://www.koenergy.kr/kosep/gv/nf/dt/nfdt01/main.do?menuCd=FN0912020207"
EXPORT_URL = "https://www.koenergy.kr/kosep/gv/nf/dt/nfdt01/csvDown.do"
MENU_CODE = "FN0912020207"
DEFAULT_START_MONTH = "201501"
SOURCE_ENCODING = "cp949"
EXPECTED_COLUMNS = [
    "사업소",
    "호기",
    "일자",
    "용량(MW)",
    "발전량(MWh)",
    "열효율(%)",
    "이용률(%)",
    "발전원",
]

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "kepco_subsidiaries" / "southeast_power"


def validate_month(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m")
    except ValueError as error:
        raise argparse.ArgumentTypeError("Month must use YYYYMM format.") from error
    return value


def year_ranges(start_month: str, end_month: str) -> list[tuple[str, str]]:
    return [
        (max(start_month, f"{year}01"), min(end_month, f"{year}12"))
        for year in range(int(start_month[:4]), int(end_month[:4]) + 1)
    ]


def parse_source_csv(content: bytes) -> tuple[list[str], list[list[str]]]:
    try:
        text = content.decode(SOURCE_ENCODING)
    except UnicodeDecodeError as error:
        raise RuntimeError("KOEN generation CSV was not valid CP949.") from error
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text), delimiter="|")
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        raise RuntimeError("KOEN generation CSV response was empty.")
    if rows[0] != EXPECTED_COLUMNS:
        raise RuntimeError(f"Unexpected KOEN generation CSV columns: {rows[0]}")
    if any(len(row) != len(EXPECTED_COLUMNS) for row in rows[1:]):
        raise RuntimeError("Unexpected KOEN generation CSV row width.")
    return rows[0], rows[1:]


def request_export(
    start_month: str, end_month: str, timeout: int, verify_tls: bool
) -> tuple[bytes, str, str]:
    session = requests.Session()
    session.verify = verify_tls
    session.headers["User-Agent"] = "NZK-APHIAM data scraper"
    with warnings.catch_warnings():
        if not verify_tls:
            warnings.simplefilter("ignore", InsecureRequestWarning)
        try:
            page = session.get(SOURCE_URL, timeout=timeout)
            page.raise_for_status()
            parser = FormFieldsParser("frmDefault")
            parser.feed(page.text)
            if "ptSignature" not in parser.fields:
                raise RuntimeError("KOEN generation export signature was not found.")
            fields = dict(parser.fields)
            fields.update(
                pageIndex="1",
                menuCd=MENU_CODE,
                strOrgNo="",
                strHokiS="",
                strHokiE="",
                strDateS=start_month,
                strDateE=end_month,
            )
            response = session.post(EXPORT_URL, data=fields, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(
                f"KOEN generation export failed: {error.__class__.__name__}"
            ) from None
    if "text/csv" not in response.headers.get("Content-Type", "").lower():
        raise RuntimeError("KOEN generation export did not return CSV.")
    return response.content, page.url, response.url


def save_utf8_csv(columns: list[str], rows: list[list[str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", type=validate_month, default=DEFAULT_START_MONTH)
    parser.add_argument("--end-month", type=validate_month, default=date.today().strftime("%Y%m"))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--reuse-existing-source", action="store_true")
    parser.add_argument("--verify-tls", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.start_month > args.end_month:
        raise ValueError("--start-month must be on or before --end-month.")
    stem = args.out_dir / "southeast_power_monthly_generation"
    all_rows: list[list[str]] = []
    chunks = []
    for start, end in reversed(year_ranges(args.start_month, args.end_month)):
        raw_path = stem.with_name(f"{stem.name}.source.{start}_{end}.csv")
        if args.reuse_existing_source and raw_path.exists():
            content = raw_path.read_bytes()
            source_url, export_url = SOURCE_URL, EXPORT_URL
        else:
            content, source_url, export_url = request_export(
                start, end, args.timeout, args.verify_tls
            )
            save_raw(content, raw_path)
        columns, rows = parse_source_csv(content)
        all_rows.extend(rows)
        chunks.append(
            {
                "start_month": start,
                "end_month": end,
                "row_count": len(rows),
                "source_file": str(raw_path),
                "source_url": source_url,
                "export_url": export_url,
            }
        )
        print(f"Fetched {len(rows)} rows for {start}-{end}")
    all_rows.sort(key=lambda row: (row[2], row[0], row[1]))
    save_utf8_csv(EXPECTED_COLUMNS, all_rows, stem.with_suffix(".csv"))
    save_json(
        {
            "dataset_name": DATASET_NAME,
            "dataset_url": DATASET_URL,
            "api_base_url": API_BASE_URL,
            "retrieved_at": datetime.now().astimezone().isoformat(),
            "row_count": len(all_rows),
            "chunks": chunks,
        },
        stem.with_suffix(".metadata.json"),
    )
    print(f"Saved {len(all_rows)} rows to {stem.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
