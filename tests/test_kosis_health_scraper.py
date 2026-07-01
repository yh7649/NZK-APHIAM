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


def test_validate_payload_surfaces_kosis_error() -> None:
    with pytest.raises(RuntimeError, match="KOSIS error 11"):
        scraper.validate_payload(
            {"err": "11", "errMsg": "유효하지 않은 인증KEY입니다."},
            scraper.DATASETS["monthly-deaths"],
            2024,
        )


def test_scrape_dataset_rebuilds_from_preserved_raw_file(tmp_path: Path) -> None:
    dataset = scraper.DATASETS["monthly-deaths"]
    raw_dir = tmp_path / "monthly_deaths" / "raw"
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
        output_dir=tmp_path,
        start_year=2024,
        end_year=2024,
        api_key="unused",
        timeout=1,
        overwrite=False,
    )

    assert result["normalized_rows"] == 1
    csv_text = (tmp_path / "monthly_deaths" / "monthly_deaths.csv").read_text()
    assert "종로구" in csv_text
    assert result["files"][0]["status"] == "reused"
