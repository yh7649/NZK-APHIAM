from __future__ import annotations

from pathlib import Path

import pandas as pd

from nzk_aphiam.data.process.capss import processor


def write_capss_like_workbook(path: Path) -> None:
    rows = [
        ["2023년 행정구역 배출량", None, None, None, None, None, None, None, None, None],
        [None, None, None, None, None, None, None, None, None, None],
        [
            "시도",
            "시군구",
            "배출원대분류",
            "배출원중분류",
            "배출원소분류",
            "연료대분류",
            "연료소분류",
            "2023년 배출량 (kg/yr)",
            None,
            None,
        ],
        [None, None, None, None, None, None, None, "CO", "NOx", "PM-2.5"],
        [
            "서울특별시",
            "종로구",
            "비산업 연소",
            "상업 및 공공기관시설",
            "기타",
            "LNG",
            "LNG",
            1.5,
            2,
            None,
        ],
        [
            "서울특별시",
            "중구",
            "도로이동오염원",
            "승용차",
            "경형",
            "휘발유",
            "휘발유",
            3,
            4,
            5,
        ],
    ]
    pd.DataFrame(rows).to_excel(path, sheet_name="2023년", header=False, index=False)


def test_parse_workbook_returns_tidy_pollutant_rows_and_metadata(tmp_path: Path) -> None:
    workbook = tmp_path / "capss_emissions_statistics_2023.xlsx"
    write_capss_like_workbook(workbook)

    parsed, metadata = processor.parse_workbook(workbook)

    assert list(parsed["pollutant"].unique()) == ["CO", "NOx", "PM2.5"]
    assert set(parsed.columns).issuperset(
        {
            "year",
            "sub_district_code",
            "sub_district_name",
            "source_category_ko",
            "source_subcategory",
            "fuel_type_ko",
            "emissions_kg",
        }
    )
    assert parsed["year"].unique().tolist() == [2023]
    assert parsed["sub_district_code"].isna().all()
    assert parsed.loc[parsed["pollutant"] == "PM2.5", "emissions_kg"].tolist() == [5.0]
    assert metadata["sheets"][0]["unit"] == "kg/yr"
    assert "TSP" in metadata["sheets"][0]["pollutants_missing_from_expected"]
    assert metadata["sheets"][0]["taxonomy_period"] == "2015_plus"


def test_process_files_writes_per_year_combined_and_metadata(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "interim"
    raw.mkdir()
    write_capss_like_workbook(raw / "capss_emissions_statistics_2023.xlsx")

    metadata = processor.process_files(raw, output)

    assert (output / "capss_emissions_tidy_2023.parquet").exists()
    assert (output / "capss_emissions_tidy.parquet").exists()
    assert (output / "capss_emissions_tidy.metadata.json").exists()
    assert metadata["files"][0]["rows"] == 5
