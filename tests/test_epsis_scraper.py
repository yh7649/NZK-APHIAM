from __future__ import annotations

from pathlib import Path

import pytest

from nzk_aphiam.data.scrape.epsis import scraper


def test_parse_annual_payload_extracts_all_fields() -> None:
    assignments = "\n".join(f'c{number} = "value {number}";' for number in range(1, 19))
    payload = f"""{assignments}
gridData.push({{"year": "2024",
                "c1":c1,
                "c18":c18
                }});
"""

    rows = scraper.parse_annual_payload(payload, expected_year=2024)

    assert rows == [
        {
            "year": "2024",
            **{
                column: f"value {number}"
                for number, column in enumerate(scraper.ANNUAL_COLUMNS[1:], start=1)
            },
        }
    ]


def test_parse_annual_payload_rejects_missing_fields() -> None:
    payload = 'c1 = "thermal";\ngridData.push({"year": "2024",\n'

    with pytest.raises(RuntimeError, match="missing fields"):
        scraper.parse_annual_payload(payload, expected_year=2024)


def test_parse_annual_generation_payload_uses_detailed_branch_only() -> None:
    assignments = "\n".join(f'c{number} = "value {number}";' for number in range(1, 10))
    payload = f"""\
if(""=="Y"){{
{assignments}
gridData.push({{"Period":"2024",
  "Power":"기력", "Fuel":"화력", "Fuel2":"유연탄",
  "Comp":"남동", "Comp2":"한전 및 자회사",
  "Equip":"영흥#1", "Equip2":"Yeongheung #1",
  "c1":c1, "c2":c2, "c3":c3, "c4":c4, "c5":c5,
  "c6":c6, "c7":c7, "c8":c8, "c9":c9
}});
}}else{{
gridData.push({{"Period":year, "Power":power, "Equip":equip}});
}}
"""

    assert scraper.parse_annual_generation_payload(payload, expected_year=2024) == [
        {
            "year": "2024",
            "generation_source": "기력",
            "fuel_group": "화력",
            "fuel_detail": "유연탄",
            "company": "남동",
            "company_category": "한전 및 자회사",
            "source_record_name": "영흥#1",
            "source_record_name_english": "Yeongheung #1",
            "capacity_kw": "value 1",
            "gross_generation_mwh": "value 2",
            "station_use_mwh": "value 3",
            "net_generation_mwh": "value 4",
            "maximum_output_kw": "value 5",
            "average_output_kw": "value 6",
            "load_factor_percent": "value 7",
            "utilization_rate_percent": "value 8",
            "station_use_rate_percent": "value 9",
        }
    ]


def test_parse_snapshot_list() -> None:
    html = """\
<table><tr>
  <td>6061</td>
  <td class="title" onclick="viewPage(6060); return false;">
    <a href="#">2026년 05월 27일 기준 발전기 목록</a>
  </td>
  <td>운영자</td><td>2026-05-27</td><td>2026-05-27</td><td>208</td>
</tr></table>
"""

    assert scraper.parse_snapshot_list(html) == [
        {
            "no_index": 6060,
            "display_number": "6061",
            "title": "2026년 05월 27일 기준 발전기 목록",
            "author": "운영자",
            "created_date": "2026-05-27",
            "modified_date": "2026-05-27",
            "view_count": "208",
        }
    ]


def test_parse_snapshot_coverage() -> None:
    html = """\
<p>TOTAL : 321</p>
<button class="end" onclick="linkPage(33); return false;">맨끝으로</button>
"""
    assert scraper.parse_snapshot_coverage(html) == (321, 33)


def test_parse_attachment_and_snapshot_date() -> None:
    html = """\
<a href="/epsisnew/fileDownload.do?cdBbs=080000&amp;noIndex=6060&amp;noFile=1">
  roster_20260527.zip
</a>
"""
    assert scraper.parse_attachments(html) == [
        {
            "url": (
                "https://epsis.kpx.or.kr/epsisnew/fileDownload.do?"
                "cdBbs=080000&noIndex=6060&noFile=1"
            ),
            "filename": "roster_20260527.zip",
        }
    ]
    assert scraper.snapshot_date_from_title("2026년 05월 27일 기준 발전기 목록") == ("2026-05-27")


def test_offline_annual_rebuild_requires_preserved_raw(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing raw file"):
        scraper.scrape_annual(tmp_path, 2024, 2024, 1, False, offline=True)
