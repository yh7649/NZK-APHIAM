from __future__ import annotations

import json
from pathlib import Path

import pytest

from nzk_aphiam.data.scrape.health.kosis import scraper


def test_parser_defaults_to_all_datasets() -> None:
    assert scraper.build_parser().parse_args([]).datasets == []


def test_build_params_uses_year_chunks_and_all_required_dimensions() -> None:
    params = scraper.build_params(scraper.DATASETS["cause-deaths"], 2024, "secret")

    assert params["startPrdDe"] == "2024"
    assert params["endPrdDe"] == "2024"
    assert params["objL1"] == "ALL"
    assert params["objL2"] == "ALL"
    assert params["objL3"] == "0"
    assert params["apiKey"] == "secret"


def test_build_params_uses_dataset_organization() -> None:
    params = scraper.build_params(scraper.DATASETS["foreign-residents"], 2024, "secret")

    assert params["orgId"] == "110"
    assert params["objL1"] == "ALL"
    assert params["objL2"] == "ALL"
    assert params["objL3"] == "ALL"


def test_session_uses_kosis_compatible_identifiable_user_agent() -> None:
    user_agent = scraper.build_session().headers["User-Agent"]

    assert user_agent.startswith("Mozilla/5.0")
    assert "NZK-APHIAM" in user_agent


def test_normalize_monthly_death_preserves_code_and_count() -> None:
    record = {
        "PRD_DE": "202412",
        "C1": "11110",
        "C1_NM": "종로구",
        "C2": "0",
        "C2_NM": "계",
        "DT": "1,234",
        "UNIT_NM": "명",
    }

    assert scraper.normalize_monthly_death(record) == {
        "district_code": "11110",
        "district_name": "종로구",
        "geography_level": "district",
        "year": 2024,
        "month": 12,
        "sex_code": "0",
        "sex": "계",
        "deaths_all": 1234,
        "unit": "명",
    }


def test_normalize_cause_death_retains_suppressed_values_as_missing() -> None:
    record = {
        "PRD_DE": "2024",
        "C1": "9",
        "C1_NM": "순환계통의 질환",
        "C2": "11110",
        "C2_NM": "종로구",
        "C3": "0",
        "C3_NM": "계",
        "DT": "-",
    }

    assert scraper.normalize_cause_death(record)["deaths"] is None


def test_parse_integer_retains_asterisk_suppression_as_missing() -> None:
    assert scraper.parse_integer("*") is None
    assert scraper.parse_number("X") is None


def test_geography_level_retains_sejong_as_district_equivalent() -> None:
    assert scraper.geography_level("00") == "national"
    assert scraper.geography_level("11") == "province"
    assert scraper.geography_level("29", "세종특별자치시") == "district_equivalent"
    assert scraper.geography_level("36", "세종특별자치시") == "district_equivalent"
    assert scraper.geography_level("11110") == "district"


def test_population_table_uses_total_population_item_without_sex_dimension() -> None:
    dataset = scraper.DATASETS["population"]

    assert dataset.item_id == "T20"
    assert dataset.dimensions == ("ALL",)
    assert dataset.first_year == 2011


def test_monthly_indicator_tables_use_one_month_chunks() -> None:
    assert scraper.DATASETS["aging"].chunk_months == 1
    assert scraper.DATASETS["sex-ratio"].chunk_months == 1
    assert scraper.DATASETS["aging"].first_year == 2008
    assert scraper.DATASETS["sex-ratio"].first_year == 2008
    assert scraper.DATASETS["elderly-living-alone"].first_year == 2015
    assert scraper.DATASETS["one-person-households"].first_year == 2015


def test_normalize_indicator_cleans_labels_and_parses_decimal_values() -> None:
    record = {
        "PRD_DE": "202405",
        "C1": "11110",
        "C1_NM": "종로구",
        "ITM_ID": "T10",
        "ITM_NM": "고령인구비율＜br＞(A÷B×100)",
        "DT": "19.4",
        "UNIT_NM": "%",
    }

    assert scraper.normalize_indicator(record) == {
        "district_code": "11110",
        "district_name": "종로구",
        "geography_level": "district",
        "year": 2024,
        "month": 5,
        "indicator_code": "T10",
        "indicator": "고령인구비율 (A÷B×100)",
        "value": 19.4,
        "unit": "%",
    }


def test_normalize_foreign_resident_strips_kosis_area_prefix() -> None:
    record = {
        "PRD_DE": "2024",
        "C1": "11101HJG11010",
        "C1_NM": "종로구",
        "C2": "15110AA000",
        "C2_NM": "합계",
        "C3": "C001",
        "C3_NM": "계",
        "ITM_ID": "16110AAA0",
        "ITM_NM": "외국인",
        "DT": "13,429",
        "UNIT_NM": "명",
    }

    assert scraper.normalize_foreign_resident(record) == {
        "district_code": "11010",
        "district_name": "종로구",
        "geography_level": "district",
        "year": 2024,
        "resident_category_code": "15110AA000",
        "resident_category": "합계",
        "sex_code": "C001",
        "sex": "계",
        "measure_code": "16110AAA0",
        "measure": "외국인",
        "population": 13429,
        "unit": "명",
    }


def test_normalize_classified_indicator_keeps_source_and_categories() -> None:
    record = {
        "TBL_ID": "DT_11761_N009",
        "TBL_NM": "시군구별,장애정도별,성별 등록장애인수",
        "PRD_DE": "2024",
        "C1": "11110",
        "C1_NM": "종로구",
        "C2": "01",
        "C2_NM": "심한장애",
        "ITM_ID": "T001",
        "ITM_NM": "소계",
        "DT": "1,234",
        "UNIT_NM": "명",
    }

    normalized = scraper.normalize_classified_indicator(record)

    assert normalized["source_table_id"] == "DT_11761_N009"
    assert normalized["area_code"] == "11110"
    assert normalized["geography_level"] == "district"
    assert normalized["category1"] == "심한장애"
    assert normalized["measure"] == "소계"
    assert normalized["value"] == 1234.0


def test_nhis_regional_tables_are_bounded_by_latest_published_year() -> None:
    dataset = scraper.DATASETS["medical-workforce-seoul-incheon-gyeonggi-gangwon"]

    assert dataset.first_year == 2006
    assert dataset.last_year == 2023


def test_validate_payload_surfaces_kosis_error() -> None:
    with pytest.raises(RuntimeError, match="KOSIS error 11"):
        scraper.validate_payload(
            {"err": "11", "errMsg": "유효하지 않은 인증KEY입니다."},
            scraper.DATASETS["monthly-deaths"],
            2024,
        )


def test_scrape_dataset_rebuilds_from_preserved_raw_file(tmp_path: Path) -> None:
    dataset = scraper.DATASETS["monthly-deaths"]
    raw_root = tmp_path / "raw"
    interim_root = tmp_path / "interim"
    raw_dir = raw_root / "monthly_deaths"
    raw_dir.mkdir(parents=True)
    payload = [
        {
            "PRD_DE": "202401",
            "C1": "11110",
            "C1_NM": "종로구",
            "C2": "0",
            "C2_NM": "계",
            "DT": "100",
            "UNIT_NM": "명",
        }
    ]
    (raw_dir / f"{dataset.table_id}_2024.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    result = scraper.scrape_dataset(
        session=None,  # type: ignore[arg-type]
        dataset=dataset,
        raw_root=raw_root,
        interim_root=interim_root,
        start_year=2024,
        end_year=2024,
        api_key="unused",
        timeout=1,
        overwrite=False,
    )

    assert result["normalized_rows"] == 1
    csv_text = (interim_root / "monthly_deaths" / "monthly_deaths.csv").read_text()
    assert "종로구" in csv_text
    assert result["files"][0]["status"] == "reused"
    assert result["files"][0]["raw_file"] == "monthly_deaths/DT_1B82A01_2024.json"
    assert result["normalized_file"] == "monthly_deaths/monthly_deaths.csv"
