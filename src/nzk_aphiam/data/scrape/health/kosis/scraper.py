"""Download Korean district health and demographic statistics from KOSIS.

The public-health baseline contains:

* monthly all-cause deaths by residence district;
* annual cause-specific deaths by residence district; and
* monthly resident population denominators.

It also includes district-level demographic and socioeconomic covariates that
are useful for health analyses where public KOSIS coverage is available:
monthly age structure and sex ratio indicators, annual foreign-resident
composition, annual fiscal independence, and annual elderly one-person
household indicators.

KOSIS requires a free OpenAPI key. Put it in ``KOSIS_API_KEY`` in ``.env``.
Raw annual JSON responses are preserved before normalized CSV files are built.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
OPENAPI_PAGE_URL = "https://kosis.kr/openapi/"
PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "health" / "kosis"
DEFAULT_START_YEAR = 2001
DEFAULT_END_YEAR = 2024


@dataclass(frozen=True)
class Dataset:
    """Configuration for one KOSIS statistical table."""

    key: str
    org_id: str
    table_id: str
    title: str
    period: str
    first_year: int
    item_id: str
    dimensions: tuple[str, ...]
    output_columns: tuple[str, ...]
    normalizer: Callable[[dict[str, Any]], dict[str, Any]]
    chunk_months: int = 2
    last_year: int | None = None


def parse_integer(value: Any) -> int | None:
    """Parse KOSIS count strings while retaining suppressed/missing cells."""
    text = "" if value is None else str(value).strip().replace(",", "")
    if text in {"", "-", "--", "*", "...", "…", "NA", "N/A", "X", "x"}:
        return None
    try:
        return int(float(text))
    except ValueError as error:
        raise RuntimeError(f"Unexpected non-numeric KOSIS count: {value!r}") from error


def parse_number(value: Any) -> float | None:
    """Parse KOSIS numeric strings while retaining suppressed/missing cells."""
    text = "" if value is None else str(value).strip().replace(",", "")
    if text in {"", "-", "--", "*", "...", "…", "NA", "N/A", "X", "x"}:
        return None
    try:
        return float(text)
    except ValueError as error:
        raise RuntimeError(f"Unexpected non-numeric KOSIS value: {value!r}") from error


def clean_kosis_label(value: Any) -> str:
    """Remove KOSIS HTML break markup from labels."""
    return str(value or "").replace("＜br＞", " ").replace("<br>", " ").strip()


def admin_code_from_record(record: dict[str, Any], field: str = "C1") -> str:
    """Return the KOSIS administrative code, stripping table-specific prefixes."""
    code = str(record[field])
    if "HJG" in code:
        return code.split("HJG", 1)[1]
    return code


PROVINCE_NAMES = {
    "강원",
    "강원도",
    "강원특별자치도",
    "경기",
    "경기도",
    "경남",
    "경상남도",
    "경북",
    "경상북도",
    "광주",
    "광주광역시",
    "대구",
    "대구광역시",
    "대전",
    "대전광역시",
    "부산",
    "부산광역시",
    "서울",
    "서울특별시",
    "세종",
    "세종특별자치시",
    "울산",
    "울산광역시",
    "인천",
    "인천광역시",
    "전남",
    "전라남도",
    "전북",
    "전북특별자치도",
    "전라북도",
    "제주",
    "제주특별자치도",
    "충남",
    "충청남도",
    "충북",
    "충청북도",
}


def geography_level(code: str, name: str = "") -> str:
    """Classify KOSIS administrative codes without discarding aggregates."""
    if code == "00":
        return "national"
    if name.startswith("세종"):
        return "district_equivalent"
    if len(code) == 2:
        return "province"
    return "district"


def geography_level_from_record(record: dict[str, Any], field: str = "C1") -> str:
    """Classify area rows when provider-specific area codes are not standard."""
    code = admin_code_from_record(record, field)
    name = str(record.get(f"{field}_NM", ""))
    if name in {"전국", "총합계", "합계"}:
        return "national"
    if name in PROVINCE_NAMES:
        return "province"
    return geography_level(code, name)


def normalize_monthly_death(record: dict[str, Any]) -> dict[str, Any]:
    period = str(record["PRD_DE"])
    code = str(record["C1"])
    return {
        "district_code": code,
        "district_name": record["C1_NM"],
        "geography_level": geography_level(code, str(record["C1_NM"])),
        "year": int(period[:4]),
        "month": int(period[4:6]),
        "sex_code": str(record.get("C2", "0")),
        "sex": record.get("C2_NM", "계"),
        "deaths_all": parse_integer(record.get("DT")),
        "unit": record.get("UNIT_NM", "명"),
    }


def normalize_cause_death(record: dict[str, Any]) -> dict[str, Any]:
    code = str(record["C2"])
    return {
        "district_code": code,
        "district_name": record["C2_NM"],
        "geography_level": geography_level(code, str(record["C2_NM"])),
        "year": int(str(record["PRD_DE"])[:4]),
        "cause_code": str(record["C1"]),
        "cause_name": record["C1_NM"],
        "sex_code": str(record.get("C3", "0")),
        "sex": record.get("C3_NM", "계"),
        "deaths": parse_integer(record.get("DT")),
        "unit": record.get("UNIT_NM", "명"),
    }


def normalize_population(record: dict[str, Any]) -> dict[str, Any]:
    period = str(record["PRD_DE"])
    code = str(record["C1"])
    return {
        "district_code": code,
        "district_name": record["C1_NM"],
        "geography_level": geography_level(code, str(record["C1_NM"])),
        "year": int(period[:4]),
        "month": int(period[4:6]),
        "sex_code": str(record.get("C2", "0")),
        "sex": record.get("C2_NM", "계"),
        "population": parse_integer(record.get("DT")),
        "unit": record.get("UNIT_NM", "명"),
    }


def normalize_indicator(record: dict[str, Any]) -> dict[str, Any]:
    period = str(record["PRD_DE"])
    code = admin_code_from_record(record)
    row = {
        "district_code": code,
        "district_name": record["C1_NM"],
        "geography_level": geography_level(code, str(record["C1_NM"])),
        "year": int(period[:4]),
        "indicator_code": str(record["ITM_ID"]),
        "indicator": clean_kosis_label(record["ITM_NM"]),
        "value": parse_number(record.get("DT")),
        "unit": record.get("UNIT_NM", ""),
    }
    if len(period) > 4:
        row["month"] = int(period[4:6])
    return row


def normalize_foreign_resident(record: dict[str, Any]) -> dict[str, Any]:
    code = admin_code_from_record(record)
    return {
        "district_code": code,
        "district_name": record["C1_NM"],
        "geography_level": geography_level(code, str(record["C1_NM"])),
        "year": int(str(record["PRD_DE"])[:4]),
        "resident_category_code": str(record["C2"]),
        "resident_category": record["C2_NM"],
        "sex_code": str(record["C3"]),
        "sex": record["C3_NM"],
        "measure_code": str(record["ITM_ID"]),
        "measure": clean_kosis_label(record["ITM_NM"]),
        "population": parse_integer(record.get("DT")),
        "unit": record.get("UNIT_NM", "명"),
    }


GENERIC_CLASSIFIED_COLUMNS = (
    "source_table_id",
    "source_table_name",
    "area_code",
    "area_name",
    "geography_level",
    "year",
    "month",
    "category1_code",
    "category1",
    "category2_code",
    "category2",
    "category3_code",
    "category3",
    "measure_code",
    "measure",
    "value",
    "unit",
)


def normalize_classified_indicator(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize KOSIS tables with one area dimension and up to three categories."""
    period = str(record["PRD_DE"])
    row = {
        "source_table_id": record.get("TBL_ID", ""),
        "source_table_name": clean_kosis_label(record.get("TBL_NM", "")),
        "area_code": admin_code_from_record(record),
        "area_name": record["C1_NM"],
        "geography_level": geography_level_from_record(record),
        "year": int(period[:4]),
        "month": int(period[4:6]) if len(period) > 4 else None,
        "category1_code": str(record.get("C2", "")),
        "category1": clean_kosis_label(record.get("C2_NM", "")),
        "category2_code": str(record.get("C3", "")),
        "category2": clean_kosis_label(record.get("C3_NM", "")),
        "category3_code": str(record.get("C4", "")),
        "category3": clean_kosis_label(record.get("C4_NM", "")),
        "measure_code": str(record.get("ITM_ID", "")),
        "measure": clean_kosis_label(record.get("ITM_NM", "")),
        "value": parse_number(record.get("DT")),
        "unit": record.get("UNIT_NM", ""),
    }
    return row


DATASETS = {
    "monthly-deaths": Dataset(
        key="monthly-deaths",
        org_id="101",
        table_id="DT_1B82A01",
        title="KOSIS monthly deaths by city, county, and district",
        period="M",
        first_year=1997,
        item_id="T1",
        dimensions=("ALL", "0"),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "month",
            "sex_code",
            "sex",
            "deaths_all",
            "unit",
        ),
        normalizer=normalize_monthly_death,
    ),
    "cause-deaths": Dataset(
        key="cause-deaths",
        org_id="101",
        table_id="DT_1B34E13",
        title="KOSIS annual deaths by district, 50-cause group, and sex",
        period="Y",
        first_year=1998,
        item_id="T1",
        dimensions=("ALL", "ALL", "0"),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "cause_code",
            "cause_name",
            "sex_code",
            "sex",
            "deaths",
            "unit",
        ),
        normalizer=normalize_cause_death,
    ),
    "population": Dataset(
        key="population",
        org_id="101",
        table_id="DT_1B040A3",
        title="KOSIS monthly resident population by district and sex",
        period="M",
        # This table advertises annual history from 1992, but its monthly
        # series returns KOSIS error 30 before 2011.
        first_year=2011,
        item_id="T20",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "month",
            "sex_code",
            "sex",
            "population",
            "unit",
        ),
        normalizer=normalize_population,
    ),
    "aging": Dataset(
        key="aging",
        org_id="101",
        table_id="DT_1YL20631",
        title="KOSIS monthly aged population indicators by district",
        period="M",
        # The table page advertises older history, but monthly API queries
        # return KOSIS error 30 before 2008.
        first_year=2008,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "month",
            "indicator_code",
            "indicator",
            "value",
            "unit",
        ),
        normalizer=normalize_indicator,
        chunk_months=1,
    ),
    "sex-ratio": Dataset(
        key="sex-ratio",
        org_id="101",
        table_id="DT_1YL20701",
        title="KOSIS monthly male and female population indicators by district",
        period="M",
        # The table page advertises older history, but monthly API queries
        # return KOSIS error 30 before 2008.
        first_year=2008,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "month",
            "indicator_code",
            "indicator",
            "value",
            "unit",
        ),
        normalizer=normalize_indicator,
        chunk_months=1,
    ),
    "foreign-residents": Dataset(
        key="foreign-residents",
        org_id="110",
        table_id="TX_11025_A001_A",
        title="KOSIS annual foreign resident composition by district, category, and sex",
        period="Y",
        first_year=2015,
        item_id="ALL",
        dimensions=("ALL", "ALL", "ALL"),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "resident_category_code",
            "resident_category",
            "sex_code",
            "sex",
            "measure_code",
            "measure",
            "population",
            "unit",
        ),
        normalizer=normalize_foreign_resident,
    ),
    "fiscal-independence": Dataset(
        key="fiscal-independence",
        org_id="101",
        table_id="DT_1YL20921",
        title="KOSIS annual local fiscal independence indicators by district",
        period="Y",
        first_year=2003,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "indicator_code",
            "indicator",
            "value",
            "unit",
        ),
        normalizer=normalize_indicator,
    ),
    "elderly-living-alone": Dataset(
        key="elderly-living-alone",
        org_id="101",
        table_id="DT_1YL12701",
        title="KOSIS annual elderly one-person household indicators by district",
        period="Y",
        # Early census-style years exist for 2000, 2005, and 2010, but the
        # annual API series is continuous from 2015.
        first_year=2015,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "indicator_code",
            "indicator",
            "value",
            "unit",
        ),
        normalizer=normalize_indicator,
    ),
}


MORE_SOCIAL_DETERMINANTS = {
    "registered-disability": Dataset(
        key="registered-disability",
        org_id="117",
        table_id="DT_11761_N009",
        title="KOSIS annual registered disabled population by district, severity, and sex",
        period="Y",
        first_year=2019,
        item_id="ALL",
        dimensions=("ALL", "ALL"),
        output_columns=GENERIC_CLASSIFIED_COLUMNS,
        normalizer=normalize_classified_indicator,
    ),
    "health-insurance-population": Dataset(
        key="health-insurance-population",
        org_id="101",
        table_id="DT_1YL202114E",
        title="KOSIS annual health-insurance covered population by district",
        period="Y",
        first_year=2004,
        item_id="ALL",
        dimensions=("ALL", "ALL"),
        output_columns=GENERIC_CLASSIFIED_COLUMNS,
        normalizer=normalize_classified_indicator,
    ),
    "one-person-households": Dataset(
        key="one-person-households",
        org_id="101",
        table_id="DT_1YL21161",
        title="KOSIS annual one-person household indicators by district",
        period="Y",
        # Early census-style years exist for 2000, 2005, and 2010, but the
        # annual API series is continuous from 2015.
        first_year=2015,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "indicator_code",
            "indicator",
            "value",
            "unit",
        ),
        normalizer=normalize_indicator,
    ),
    "one-person-households-age-sex": Dataset(
        key="one-person-households-age-sex",
        org_id="101",
        table_id="DT_1PL1502",
        title="KOSIS annual one-person households by district, age, and sex",
        period="Y",
        first_year=2015,
        item_id="ALL",
        dimensions=("ALL", "ALL"),
        output_columns=GENERIC_CLASSIFIED_COLUMNS,
        normalizer=normalize_classified_indicator,
    ),
    "migration": Dataset(
        key="migration",
        org_id="101",
        table_id="DT_1B26001_A01",
        title="KOSIS monthly migration counts by district",
        period="M",
        first_year=1970,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=GENERIC_CLASSIFIED_COLUMNS,
        normalizer=normalize_classified_indicator,
        chunk_months=1,
    ),
    "old-housing": Dataset(
        key="old-housing",
        org_id="101",
        table_id="DT_1YL202004",
        title="KOSIS annual old-housing indicators by district",
        period="Y",
        first_year=2015,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "indicator_code",
            "indicator",
            "value",
            "unit",
        ),
        normalizer=normalize_indicator,
    ),
    "vacant-housing": Dataset(
        key="vacant-housing",
        org_id="101",
        table_id="DT_1YL202005",
        title="KOSIS annual vacant-housing indicators by district",
        period="Y",
        first_year=2015,
        item_id="ALL",
        dimensions=("ALL",),
        output_columns=(
            "district_code",
            "district_name",
            "geography_level",
            "year",
            "indicator_code",
            "indicator",
            "value",
            "unit",
        ),
        normalizer=normalize_indicator,
    ),
    "longterm-care-facilities": Dataset(
        key="longterm-care-facilities",
        org_id="350",
        table_id="DT_35006_N021",
        title="KOSIS annual long-term-care institutions and capacity by district",
        period="Y",
        first_year=2010,
        item_id="ALL",
        dimensions=("ALL", "ALL"),
        output_columns=GENERIC_CLASSIFIED_COLUMNS,
        normalizer=normalize_classified_indicator,
    ),
}


NHIS_REGIONAL_TABLES = {
    "medical-coverage": (
        ("seoul-incheon-gyeonggi-gangwon", "TX_35003_A018", 2024),
        ("daejeon-sejong-chungcheong", "TX_35003_A047", 2024),
        ("gwangju-jeolla-jeju", "TX_35003_A076", 2024),
        ("busan-daegu-ulsan-gyeongsang", "TX_35003_A105", 2024),
    ),
    "medical-institutions": (
        ("seoul-incheon-gyeonggi-gangwon", "TX_35003_A019", 2023),
        ("daejeon-sejong-chungcheong", "TX_35003_A048", 2023),
        ("gwangju-jeolla-jeju", "TX_35003_A077", 2023),
        ("busan-daegu-ulsan-gyeongsang", "TX_35003_A106", 2023),
    ),
    "medical-workforce": (
        ("seoul-incheon-gyeonggi-gangwon", "TX_35003_A020", 2023),
        ("daejeon-sejong-chungcheong", "TX_35003_A049", 2023),
        ("gwangju-jeolla-jeju", "TX_35003_A078", 2023),
        ("busan-daegu-ulsan-gyeongsang", "TX_35003_A107", 2023),
    ),
    "insurance-premiums": (
        ("seoul-incheon-gyeonggi-gangwon", "TX_35003_A021", 2024),
        ("daejeon-sejong-chungcheong", "TX_35003_A050", 2024),
        ("gwangju-jeolla-jeju", "TX_35003_A079", 2024),
        ("busan-daegu-ulsan-gyeongsang", "TX_35003_A108", 2024),
    ),
}

for topic, tables in NHIS_REGIONAL_TABLES.items():
    for region_key, table_id, last_year in tables:
        MORE_SOCIAL_DETERMINANTS[f"{topic}-{region_key}"] = Dataset(
            key=f"{topic}-{region_key}",
            org_id="350",
            table_id=table_id,
            title=f"KOSIS/NHIS annual {topic.replace('-', ' ')} for {region_key}",
            period="Y",
            first_year=2006,
            last_year=last_year,
            item_id="ALL",
            dimensions=("ALL", "ALL"),
            output_columns=GENERIC_CLASSIFIED_COLUMNS,
            normalizer=normalize_classified_indicator,
        )

DATASETS.update(MORE_SOCIAL_DETERMINANTS)


def build_session() -> requests.Session:
    """Create a retrying KOSIS API session."""
    session = requests.Session()
    # KOSIS's web-application firewall closes connections for some bot-like
    # user-agent phrases. Keep a browser-compatible prefix while identifying
    # this academic project explicitly.
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (compatible; NZK-APHIAM/0.1; academic research)"}
    )
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


def build_params(
    dataset: Dataset,
    year: int,
    api_key: str,
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    dimensions: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Build a documented KOSIS parameter-query request."""
    default_start = str(year) if dataset.period == "Y" else f"{year}01"
    default_end = str(year) if dataset.period == "Y" else f"{year}12"
    params = {
        "method": "getList",
        "apiKey": api_key,
        "orgId": dataset.org_id,
        "tblId": dataset.table_id,
        "itmId": dataset.item_id,
        "prdSe": dataset.period,
        "startPrdDe": start_period or default_start,
        "endPrdDe": end_period or default_end,
        "format": "json",
        "jsonVD": "Y",
    }
    selected_dimensions = dataset.dimensions if dimensions is None else dimensions
    params.update({f"objL{index}": value for index, value in enumerate(selected_dimensions, 1)})
    return params


def validate_payload(payload: Any, dataset: Dataset, year: int) -> list[dict[str, Any]]:
    """Validate KOSIS errors and the fields needed for normalization."""
    if isinstance(payload, dict) and "err" in payload:
        raise RuntimeError(
            f"KOSIS error {payload.get('err')} for {dataset.key} {year}: "
            f"{payload.get('errMsg', 'unknown error')}"
        )
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"KOSIS returned no rows for {dataset.key} {year}.")

    required = {"PRD_DE", "C1", "C1_NM", "DT"}
    if dataset.key == "cause-deaths":
        required.update({"C2", "C2_NM"})
    if dataset.key == "foreign-residents":
        required.update({"C2", "C2_NM", "C3", "C3_NM", "ITM_ID", "ITM_NM"})
    if dataset.normalizer in {normalize_indicator, normalize_classified_indicator}:
        required.update({"ITM_ID", "ITM_NM"})
    for record in payload:
        missing = required.difference(record)
        if missing:
            raise RuntimeError(
                f"KOSIS {dataset.key} response is missing fields: {sorted(missing)}"
            )
    return payload


def request_year(
    session: requests.Session,
    dataset: Dataset,
    year: int,
    api_key: str,
    timeout: int,
) -> tuple[list[dict[str, Any]], bytes]:
    """Download one table-year response in chunks below KOSIS's row cap."""

    def request_chunk(params: dict[str, str]) -> list[dict[str, Any]]:
        for attempt in range(1, 4):
            try:
                response = session.get(API_URL, params=params, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as error:
                if attempt == 3:
                    raise RuntimeError(
                        f"KOSIS request failed for {dataset.key} {year}: "
                        f"{error.__class__.__name__}"
                    ) from None
        return validate_payload(payload, dataset, year)

    records: list[dict[str, Any]] = []
    try:
        if dataset.period == "M":
            # KOSIS closes large responses; tables with multiple indicators
            # need one-month chunks while count-only tables fit two months.
            for first_month in range(1, 13, dataset.chunk_months):
                last_month = min(first_month + dataset.chunk_months - 1, 12)
                records.extend(
                    request_chunk(
                        build_params(
                            dataset,
                            year,
                            api_key,
                            start_period=f"{year}{first_month:02d}",
                            end_period=f"{year}{last_month:02d}",
                        )
                    )
                )
        elif dataset.key == "cause-deaths":
            # Discover the current cause codes using the national row, then
            # request two causes at a time across all geographies (about 770
            # rows). Cause codes include letters and are not safely enumerable.
            cause_index = request_chunk(
                build_params(
                    dataset,
                    year,
                    api_key,
                    dimensions=("ALL", "00", "0"),
                )
            )
            cause_codes = list(dict.fromkeys(str(row["C1"]) for row in cause_index))
            for index in range(0, len(cause_codes), 2):
                cause_batch = "+".join(cause_codes[index : index + 2])
                records.extend(
                    request_chunk(
                        build_params(
                            dataset,
                            year,
                            api_key,
                            dimensions=(cause_batch, "ALL", "0"),
                        )
                    )
                )
        else:
            records.extend(request_chunk(build_params(dataset, year, api_key)))
    except RuntimeError:
        raise

    raw_bytes = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return validate_payload(records, dataset, year), raw_bytes


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """Write one normalized table with deterministic columns."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scrape_dataset(
    session: requests.Session,
    dataset: Dataset,
    output_dir: Path,
    start_year: int,
    end_year: int,
    api_key: str,
    timeout: int,
    overwrite: bool,
) -> dict[str, Any]:
    """Download, preserve, and normalize one configured KOSIS dataset."""
    effective_start = max(start_year, dataset.first_year)
    effective_end = min(end_year, dataset.last_year) if dataset.last_year else end_year
    if effective_start > effective_end:
        raise RuntimeError(
            f"No requested years overlap available coverage for {dataset.key}: "
            f"{dataset.first_year}-{dataset.last_year or 'present'}."
        )
    dataset_dir = output_dir / dataset.key.replace("-", "_")
    raw_dir = dataset_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []

    for year in range(effective_start, effective_end + 1):
        raw_path = raw_dir / f"{dataset.table_id}_{year}.json"
        if raw_path.exists() and not overwrite:
            raw_bytes = raw_path.read_bytes()
            payload = validate_payload(json.loads(raw_bytes), dataset, year)
            status = "reused"
        else:
            payload, raw_bytes = request_year(session, dataset, year, api_key, timeout)
            raw_path.write_bytes(raw_bytes)
            status = "downloaded"

        normalized = [dataset.normalizer(record) for record in payload]
        rows.extend(normalized)
        files.append(
            {
                "year": year,
                "raw_file": str(raw_path.relative_to(output_dir)),
                "raw_rows": len(payload),
                "raw_sha256": sha256(raw_bytes).hexdigest(),
                "status": status,
            }
        )
        print(f"{dataset.key} {year}: {len(payload)} rows ({status})")

    csv_path = dataset_dir / f"{dataset.key.replace('-', '_')}.csv"
    write_csv(csv_path, dataset.output_columns, rows)
    return {
        "key": dataset.key,
        "title": dataset.title,
        "table_id": dataset.table_id,
        "period": dataset.period,
        "coverage": [effective_start, effective_end],
        "normalized_file": str(csv_path.relative_to(output_dir)),
        "normalized_rows": len(rows),
        "normalized_sha256": file_sha256(csv_path),
        "files": files,
    }


def resolve_api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("KOSIS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "KOSIS_API_KEY is missing. Request a free key at the KOSIS OpenAPI site "
            "and add it to .env."
        )
    return api_key


def scrape(
    output_dir: Path,
    start_year: int,
    end_year: int,
    dataset_keys: list[str],
    timeout: int,
    overwrite: bool,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Collect selected public-health tables and write a provenance manifest."""
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")
    selected = list(DATASETS) if not dataset_keys or "all" in dataset_keys else dataset_keys
    unknown = sorted(set(selected).difference(DATASETS))
    if unknown:
        raise ValueError(f"Unknown KOSIS health dataset(s): {', '.join(unknown)}")

    key = api_key or resolve_api_key()
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    results = [
        scrape_dataset(
            session,
            DATASETS[dataset_key],
            output_dir,
            start_year,
            end_year,
            key,
            timeout,
            overwrite,
        )
        for dataset_key in selected
    ]

    metadata = {
        "dataset": "KOSIS public health, population, and demographic baseline for NZK-APHIAM",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_url": API_URL,
        "openapi_page_url": OPENAPI_PAGE_URL,
        "requested_coverage": [start_year, end_year],
        "geographic_basis": "Published administrative area; mortality is by residence.",
        "analysis_notes": [
            "Keep death counts and use log(population) as a count-model offset.",
            "Monthly public mortality is all-cause; cause-specific district data are annual.",
            "Race is not published in the US Census sense; foreign-resident composition is the closest district-level aggregate proxy included here.",
            "Fiscal independence is a local-government socioeconomic proxy, not household income or wealth.",
            "Administrative boundaries and codes must be harmonized before spatial modeling.",
            "National and province aggregates are retained and labeled in geography_level.",
        ],
        "datasets": results,
    }
    metadata_name = "metadata.json"
    if selected != list(DATASETS):
        selection_hash = sha256(",".join(selected).encode("utf-8")).hexdigest()[:12]
        metadata_name = f"metadata_selected_{selection_hash}.json"
        metadata["selection"] = selected
    (output_dir / metadata_name).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Korean district health and demographic statistics from KOSIS."
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        default=[],
        metavar="DATASET",
        help="Datasets to collect; defaults to all.",
    )
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scrape(
        output_dir=args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        dataset_keys=args.datasets,
        timeout=args.timeout,
        overwrite=args.overwrite,
    )
