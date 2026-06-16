from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
import requests

from nzk_aphiam.data.scrape.thermal.southern_power import (
    emissions_scraper,
    generation_scraper,
)


def test_generation_parse_response_preserves_utf8_korean() -> None:
    xml_content = """\
<response>
  <header>
    <resultCode>800</resultCode>
    <resultMsg>NORMAL_SERVICE.</resultMsg>
  </header>
  <body>
    <items>
      <item><ipptnm>하동화력</ipptnm><ins>석탄</ins></item>
    </items>
  </body>
</response>
""".encode()

    root = generation_scraper.parse_response(xml_content)

    assert root.findtext("./body/items/item/ipptnm") == "하동화력"
    assert root.findtext("./body/items/item/ins") == "석탄"


def test_generation_parse_response_rejects_api_error() -> None:
    xml_content = b"""\
<response>
  <header>
    <resultCode>30</resultCode>
    <resultMsg>SERVICE KEY IS NOT REGISTERED ERROR.</resultMsg>
  </header>
</response>
"""

    with pytest.raises(RuntimeError, match="API error 30"):
        generation_scraper.parse_response(xml_content)


def test_generation_build_params_replaces_embedded_secret() -> None:
    base_url, params = generation_scraper.build_params(
        api_url="http://example.test/data?serviceKey=old&fixed=value",
        service_key="new-secret",
        page=2,
        per_page=500,
        start_date="20240101",
        end_date="20240131",
    )

    assert base_url == "http://example.test/data"
    assert params == {
        "fixed": "value",
        "serviceKey": "new-secret",
        "pageNo": 2,
        "numOfRows": 500,
        "strSdate": "20240101",
        "strEdate": "20240131",
    }


def test_generation_fetches_until_source_total(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _generation_page(["2024-01-02", "2024-01-01"], total_count=3),
        _generation_page(["2023-12-31"], total_count=3),
    ]

    def fake_request_page(**kwargs: object) -> tuple[ET.Element, str]:
        page = int(kwargs["page"])
        return responses[page - 1], f"http://example.test?pageNo={page}"

    monkeypatch.setattr(generation_scraper, "request_page", fake_request_page)

    rows, pages, request_urls = generation_scraper.fetch_all_pages(
        api_url="http://example.test",
        service_key="secret",
        start_date="20230101",
        end_date="20240102",
        per_page=2,
    )

    assert [row["ymd"] for row in rows] == ["2024-01-02", "2024-01-01", "2023-12-31"]
    assert len(pages) == 2
    assert request_urls == [
        "http://example.test?pageNo=1",
        "http://example.test?pageNo=2",
    ]


def test_generation_request_page_retries_transient_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _response(502, b"<html><body>Bad Gateway</body></html>"),
        _response(
            200,
            b"""\
<response>
  <header><resultCode>800</resultCode><resultMsg>NORMAL_SERVICE.</resultMsg></header>
  <body>
    <items><item><ymd>2024-01-01</ymd></item></items>
    <paginginfo><totalCnt>1</totalCnt></paginginfo>
  </body>
</response>
""",
        ),
    ]

    def fake_get(*args: object, **kwargs: object) -> requests.Response:
        return responses.pop(0)

    monkeypatch.setattr(generation_scraper.requests, "get", fake_get)
    monkeypatch.setattr(generation_scraper.time, "sleep", lambda _: None)

    root, request_url = generation_scraper.request_page(
        api_url="http://example.test/data",
        service_key="secret",
        page=30,
        per_page=10000,
        start_date="19000101",
        end_date="20260616",
        timeout=10,
        retries=2,
    )

    assert root.findtext("./body/items/item/ymd") == "2024-01-01"
    assert "secret" not in request_url
    assert not responses


def test_emissions_extracts_rows_and_total_count() -> None:
    payload = {
        "data": [{"발전소": "하동"}, "invalid", {"발전소": "삼척"}],
        "totalCount": "2",
    }

    assert emissions_scraper.extract_rows(payload) == [
        {"발전소": "하동"},
        {"발전소": "삼척"},
    ]
    assert emissions_scraper.get_total_count(payload) == 2


def test_redact_url_hides_service_keys() -> None:
    url = "https://example.test/data?page=1&serviceKey=secret&api_key=other"

    redacted = generation_scraper.redact_url(url)

    assert "secret" not in redacted
    assert "other" not in redacted
    assert redacted.count("REDACTED") == 2


def _generation_page(dates: list[str], total_count: int) -> ET.Element:
    items = "".join(f"<item><ymd>{value}</ymd></item>" for value in dates)
    return ET.fromstring(
        f"""\
<response>
  <header><resultCode>800</resultCode><resultMsg>NORMAL_SERVICE.</resultMsg></header>
  <body>
    <items>{items}</items>
    <paginginfo><totalCnt>{total_count}</totalCnt></paginginfo>
  </body>
</response>
"""
    )


def _response(status_code: int, content: bytes) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = content
    response.url = "http://example.test/data"
    return response
