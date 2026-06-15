from __future__ import annotations

from pathlib import Path

import pytest

from nzk_aphiam.data.scrape.cleansys import scraper


def make_record(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "examin_year": "2024",
        "fact_code": "170056",
        "biz_no": "316-85-00178",
        "fact_manage_nm": "한국서부발전㈜ 태안발전본부",
        "fact_adres": "충청남도 태안군",
        "dscamt_sm": 6858073,
        "tsp_dscamt": 209473,
        "sox_dscamt": 3622880,
        "nox_dscamt": 3025720,
        "hcl_dscamt": None,
        "hf_dscamt": None,
        "nh3_dscamt": None,
        "co_dscamt": None,
    }
    record.update(updates)
    return record


def test_parse_payload_normalizes_columns_and_drops_subtotal() -> None:
    subtotal = make_record(fact_code="0", biz_no=None, fact_manage_nm="소계")
    payload = {"ResultList": [subtotal, make_record()]}

    assert scraper.parse_payload(payload, expected_year=2024) == [
        {
            "year": "2024",
            "facility_code": "170056",
            "business_registration_number": "316-85-00178",
            "facility_name": "한국서부발전㈜ 태안발전본부",
            "address": "충청남도 태안군",
            "total_kg": 6858073,
            "tsp_kg": 209473,
            "sox_kg": 3622880,
            "nox_kg": 3025720,
            "hcl_kg": None,
            "hf_kg": None,
            "nh3_kg": None,
            "co_kg": None,
        }
    ]


def test_parse_payload_rejects_wrong_year() -> None:
    with pytest.raises(RuntimeError, match="Expected CleanSYS year"):
        scraper.parse_payload({"ResultList": [make_record(examin_year="2023")]}, 2024)


def test_parse_payload_rejects_missing_fields() -> None:
    record = make_record()
    del record["co_dscamt"]

    with pytest.raises(RuntimeError, match="missing fields"):
        scraper.parse_payload({"ResultList": [record]}, 2024)


def test_offline_rebuild_requires_preserved_raw(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing raw file"):
        scraper.scrape(tmp_path, 2024, 2024, 1, False, offline=True)
