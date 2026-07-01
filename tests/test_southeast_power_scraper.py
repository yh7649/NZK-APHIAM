from __future__ import annotations

import pytest

from nzk_aphiam.data.scrape.thermal.southeast_power import generation_scraper, scraper


def test_extract_export_fields_targets_data_form() -> None:
    html = """\
<form id="searchFrm"><input name="ptSignature" value="wrong"></form>
<form id="frmDefault">
  <input type="hidden" name="ptSignature" value="signed-token">
  <input type="hidden" name="pageIndex" value="1">
  <input type="hidden" name="menuCd" value="FN0912020205">
</form>
"""

    assert scraper.extract_export_fields(html) == {
        "ptSignature": "signed-token",
        "pageIndex": "1",
        "menuCd": "FN0912020205",
    }


def test_extract_export_fields_requires_signature() -> None:
    with pytest.raises(RuntimeError, match="signature was not found"):
        scraper.extract_export_fields('<form id="frmDefault"></form>')


def test_build_year_ranges_splits_calendar_years() -> None:
    assert scraper.build_year_ranges("20241230", "20260102") == [
        ("20241230", "20241231"),
        ("20250101", "20251231"),
        ("20260101", "20260102"),
    ]


def test_build_export_fields_preserves_signature_and_applies_filters() -> None:
    fields = scraper.build_export_fields(
        form_fields={"ptSignature": "signed-token"},
        start_date="20260101",
        end_date="20260131",
        plant_code="YH",
    )

    assert fields == {
        "ptSignature": "signed-token",
        "pageIndex": "1",
        "menuCd": "FN0912020205",
        "strOrgNo": "YH",
        "strDateS": "20260101",
        "strDateE": "20260131",
    }


def test_request_export_retries_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []

    def fake_request_export(**kwargs: object) -> tuple[bytes, str, str]:
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")
        return b"csv", "source", "export"

    monkeypatch.setattr(scraper, "request_export", fake_request_export)
    monkeypatch.setattr(scraper.time, "sleep", lambda _: None)

    result = scraper.request_export_with_retries(
        start_date="20260101",
        end_date="20261231",
        plant_code="",
        timeout=30,
        verify_tls=False,
        attempts=2,
        retry_delay=0,
    )

    assert result == (b"csv", "source", "export")
    assert len(attempts) == 2


def test_parse_source_csv_decodes_cp949_and_trims_delimiter_spaces() -> None:
    content = (
        "사업소, 호기, 일자, SOX, NOX, 먼지, 산소, 유량, 온도\n"
        "영흥, 1호기, 20260101, 1.2, 3.4, 5.6, 7.8, 9.0, 12.3\n"
    ).encode("cp949")

    columns, rows = scraper.parse_source_csv(content)

    assert columns == scraper.EXPECTED_COLUMNS
    assert rows == [
        [
            "영흥",
            "1호기",
            "20260101",
            "1.2",
            "3.4",
            "5.6",
            "7.8",
            "9.0",
            "12.3",
        ]
    ]


def test_parse_source_csv_rejects_changed_schema() -> None:
    content = "사업소, 일자\n영흥, 20260101\n".encode("cp949")

    with pytest.raises(RuntimeError, match="Unexpected Southeast Power CSV columns"):
        scraper.parse_source_csv(content)


def test_parse_generation_pipe_delimited_csv() -> None:
    content = (
        "사업소| 호기 | 일자| 용량(MW)| 발전량(MWh)| 열효율(%)| 이용률(%)| 발전원\n"
        "영흥| 3| 202501| 870| 527077.21| 40| 81.4| 석탄\n"
    ).encode("cp949")

    columns, rows = generation_scraper.parse_source_csv(content)

    assert columns == generation_scraper.EXPECTED_COLUMNS
    assert rows[0][0:3] == ["영흥", "3", "202501"]


def test_generation_year_ranges() -> None:
    assert generation_scraper.year_ranges("202411", "202602") == [
        ("202411", "202412"),
        ("202501", "202512"),
        ("202601", "202602"),
    ]
