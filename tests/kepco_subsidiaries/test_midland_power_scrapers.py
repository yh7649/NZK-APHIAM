from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from nzk_aphiam.archive.kepco_midland_concentration.scrape import (
    emissions_scraper,
    facility_status_scraper,
)
from nzk_aphiam.archive.kepco_midland_concentration.scrape.boryeong import (
    scraper as archived_boryeong_scraper,
)
from nzk_aphiam.data.scrape.thermal.midland_power import generation_scraper


def test_generation_build_params_preserves_filters_and_replaces_secret() -> None:
    base_url, params = generation_scraper.build_params(
        api_url="https://example.test/data?ServiceKey=old&fixed=value",
        service_key="new-secret",
        page=2,
        per_page=500,
        start_month="202401",
        end_month="202402",
        plant_code="8414",
        unit_start="004",
        unit_end="005",
    )

    assert base_url == "https://example.test/data"
    assert params == {
        "fixed": "value",
        "ServiceKey": "new-secret",
        "pageNo": 2,
        "numOfRows": 500,
        "strDateS": "202401",
        "strDateE": "202402",
        "strOrgNo": "8414",
        "strHokiS": "004",
        "strHokiE": "005",
    }


def test_generation_fetches_until_header_total(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _generation_page(["원주", "제주"], total_count=3),
        _generation_page(["신서천"], total_count=3),
    ]

    def fake_request_page(**kwargs: object) -> tuple[ET.Element, str]:
        page = int(kwargs["page"])
        return responses[page - 1], f"https://example.test?pageNo={page}"

    monkeypatch.setattr(generation_scraper, "request_page", fake_request_page)
    rows, pages, urls = generation_scraper.fetch_all_pages(
        api_url="https://example.test",
        service_key="secret",
        start_month="202401",
        end_month="202401",
        per_page=2,
    )

    assert [row["orgnm"] for row in rows] == ["원주", "제주", "신서천"]
    assert len(pages) == 2
    assert urls == [
        "https://example.test?pageNo=1",
        "https://example.test?pageNo=2",
    ]


def test_emissions_fetches_each_plant_without_transforming_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "8414": _emissions_response("서울", " 12.30"),
        "8570": _emissions_response("서천", "7"),
    }

    def fake_request_records(**kwargs: object) -> tuple[ET.Element, str]:
        plant_code = str(kwargs["plant_code"])
        return responses[plant_code], f"https://example.test?strOrgNo={plant_code}"

    monkeypatch.setattr(emissions_scraper, "request_records", fake_request_records)
    rows, pages, urls = emissions_scraper.fetch_records(
        api_url="https://example.test",
        service_key="secret",
        start_month="202401",
        end_month="202401",
        plant_codes=["8414", "8570"],
    )

    assert rows == [
        {"orgnm": "서울", "avgair01value": " 12.30"},
        {"orgnm": "서천", "avgair01value": "7"},
    ]
    assert len(pages) == 2
    assert len(urls) == 2


def test_parse_response_rejects_api_error() -> None:
    with pytest.raises(RuntimeError, match="API error 30"):
        emissions_scraper.parse_response(
            b"<response><header><resultCode>30</resultCode>"
            b"<resultMsg>KEY ERROR</resultMsg></header></response>"
        )


def test_facility_status_fetches_until_total_count(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = facility_status_scraper.FACILITY_STATUS_BY_SLUG["seocheon"]
    responses = [
        {"totalCount": 3, "data": [{"처리일": "2025-01-01"}, {"처리일": "2025-01-02"}]},
        {"totalCount": 3, "data": [{"처리일": "2025-01-03"}]},
    ]

    def fake_request_page(**kwargs: object) -> tuple[dict[str, object], str]:
        page = int(kwargs["page"])
        return responses[page - 1], f"https://example.test?page={page}"

    monkeypatch.setattr(facility_status_scraper, "request_page", fake_request_page)
    rows, pages, urls = facility_status_scraper.fetch_facility_records(
        spec=spec,
        service_key="secret",
        per_page=2,
    )

    assert [row["처리일"] for row in rows] == ["2025-01-01", "2025-01-02", "2025-01-03"]
    assert len(pages) == 2
    assert urls == ["https://example.test?page=1", "https://example.test?page=2"]


def test_facility_status_annotation_preserves_provider_fields() -> None:
    spec = facility_status_scraper.FACILITY_STATUS_BY_SLUG["sejong"]

    rows = facility_status_scraper.annotate_rows(spec, [{"발전소 호기": "1호기", "유량": 1000}])

    assert rows == [
        {
            "source_facility": "sejong",
            "source_korean_facility_name": "세종발전소",
            "source_english_facility_name": "Sejong",
            "source_namespace": "15155553",
            "source_endpoint_path": "/15155553/v1/uddi:708cb5a2-9c9e-4362-9201-f468fb37b2c8",
            "usable_for_mass_derivation": True,
            "발전소 호기": "1호기",
            "유량": 1000,
        }
    ]


def test_archived_site_wrapper_forwards_cli_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str] = []
    monkeypatch.setattr(
        facility_status_scraper, "main", lambda argv: received.extend(argv)
    )

    archived_boryeong_scraper.main(["--help"])

    assert received == ["--facility", "boryeong", "--help"]


def test_existing_raw_outputs_are_protected(tmp_path: Path) -> None:
    existing = tmp_path / "raw.xml"
    existing.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--overwrite"):
        generation_scraper.ensure_outputs_available([existing], overwrite=False)

    assert existing.read_text(encoding="utf-8") == "original"


def _generation_page(plants: list[str], total_count: int) -> ET.Element:
    items = "".join(f"<item><orgnm>{plant}</orgnm></item>" for plant in plants)
    return ET.fromstring(
        f"""\
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>정상입니다.</resultMsg>
    <totalCount>{total_count}</totalCount>
  </header>
  <body><items>{items}</items></body>
</response>
"""
    )


def _emissions_response(plant: str, value: str) -> ET.Element:
    return ET.fromstring(
        f"""\
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>정상입니다.</resultMsg>
    <totalCount>1</totalCount>
  </header>
  <body>
    <items><item><orgnm>{plant}</orgnm><avgair01value>{value}</avgair01value></item></items>
  </body>
</response>
"""
    )
