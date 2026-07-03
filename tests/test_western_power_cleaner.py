from __future__ import annotations

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.western_power import cleaner


def test_clean_western_power_standardizes_schema_and_types() -> None:
    raw = pd.DataFrame(
        [
            {
                "NOx": "12.5",
                "SOx": "",
                "날짜": "2025-06",
                "먼지(TSP)": None,
                "발전량(MWh)": "1234.5",
                "발전소": "태안",
                "발전용량(MW)": "500",
                "비고": None,
                "호기": "1호기",
            },
            {
                "NOx": "3.2",
                "SOx": None,
                "날짜": "2025-06",
                "먼지(TSP)": None,
                "발전량(MWh)": None,
                "발전소": "군산",
                "발전용량(MW)": "718.4",
                "비고": "",
                "호기": "복합 CC",
            },
        ],
        columns=cleaner.SOURCE_COLUMNS,
    )

    result = cleaner.clean_western_power(raw)

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == len(raw)
    assert result.loc[0, "date"] == pd.Timestamp("2025-06-01")
    assert result.loc[0, "plant_name"] == "Taean"
    assert result.loc[0, "plant_number"] == 1
    assert result.loc[0, "plant_opening_date"] == pd.Timestamp("1995-01-01")
    assert pd.isna(result.loc[0, "plant_closing_date"])
    assert result.loc[0, "plant_latitude"] == pytest.approx(36.903)
    assert result.loc[0, "plant_longitude"] == pytest.approx(126.231)
    assert result.loc[0, "fuel_type"] == "coal"
    assert result.loc[0, "technology"] == "conventional_steam_turbine"
    assert result.loc[0, "reporting_unit_id"] == "western_power:Taean:1호기"
    assert result.loc[0, "reporting_start_date"] == pd.Timestamp("2025-06-01")
    assert pd.isna(result.loc[0, "reporting_end_date"])
    assert result.loc[0, "observation_level"] == "generating_unit"
    assert result.loc[0, "generation_coverage_status"] == "reported"
    assert result.loc[0, "row_status"] == "active_reported"
    assert result.loc[0, "pollutant_data_pattern"] == "nox_only"
    assert result.loc[0, "nox"] == 12.5
    assert result.loc[0, "emissions_mass_unit"] == "metric_tonnes"
    assert result.loc[0, "original_korean_plant_name"] == "태안"
    assert result.loc[0, "original_korean_unit_name"] == "1호기"
    assert pd.isna(result.loc[1, "plant_number"])
    assert pd.isna(result.loc[1, "energy_generated_mwh"])
    assert result.loc[1, "observation_level"] == "generation_block"
    assert result.loc[1, "row_status"] == "active_partial"
    assert pd.isna(result.loc[1, "temperature_celsius"])
    assert str(result["plant_number"].dtype) == "Int64"
    assert str(result["energy_generated_mwh"].dtype) == "Float64"
    assert str(result["plant_latitude"].dtype) == "Float64"
    assert str(result["plant_name"].dtype) == "string"


@pytest.mark.parametrize(
    ("plant", "unit", "month", "expected"),
    [
        ("태안", "IGCC", "2025-06", "coal"),
        ("평택", "기력 1호기", "2020-02", "oil_and_natural_gas"),
        ("평택", "기력 1호기", "2020-03", "natural_gas"),
        ("평택", "복합 2CC", "2002-01", "natural_gas"),
        ("서인천", "복합 8CC", "2025-06", "natural_gas"),
        ("김포", "열병합", "2025-06", "natural_gas"),
    ],
)
def test_classify_fuel_type(
    plant: str,
    unit: str,
    month: str,
    expected: str,
) -> None:
    assert cleaner.classify_fuel_type(plant, unit, pd.Timestamp(month)) == expected


def test_clean_western_power_rejects_source_schema_change() -> None:
    raw = pd.DataFrame({"날짜": ["2025-06"]})

    with pytest.raises(ValueError, match="Unexpected Western Power source columns"):
        cleaner.clean_western_power(raw)


def test_reporting_ids_distinguish_pyeongtaek_steam_and_combined_unit_one() -> None:
    assert cleaner.make_reporting_unit_id("평택", "기력 1호기") != (
        cleaner.make_reporting_unit_id("평택", "복합 1CC")
    )


def test_status_marks_pre_activity_and_explicit_retirement_without_imputation() -> None:
    rows = [
        {
            "NOx": None,
            "SOx": None,
            "날짜": "2016-12",
            "먼지(TSP)": None,
            "발전량(MWh)": None,
            "발전소": "평택",
            "발전용량(MW)": None,
            "비고": None,
            "호기": "복합 1CC",
        },
        {
            "NOx": "1",
            "SOx": None,
            "날짜": "2017-01",
            "먼지(TSP)": None,
            "발전량(MWh)": "10",
            "발전소": "평택",
            "발전용량(MW)": "480",
            "비고": None,
            "호기": "복합 1CC",
        },
        {
            "NOx": None,
            "SOx": None,
            "날짜": "2018-01",
            "먼지(TSP)": None,
            "발전량(MWh)": None,
            "발전소": "평택",
            "발전용량(MW)": None,
            "비고": "2018-01-01 부 폐지",
            "호기": "복합 1CC",
        },
    ]
    result = cleaner.clean_western_power(pd.DataFrame(rows, columns=cleaner.SOURCE_COLUMNS))

    assert result["row_status"].tolist() == [
        "inactive_placeholder",
        "active_reported",
        "inactive_placeholder",
    ]
    assert result.loc[0, "row_status_basis"] == "before_first_reported_activity"
    assert result.loc[2, "row_status_basis"] == "source_note_reports_retirement"
    assert result.loc[0, "reporting_start_date"] == pd.Timestamp("2017-01-01")
    assert result.loc[2, "reporting_end_date"] == pd.Timestamp("2018-01-01")
    assert pd.isna(result.loc[0, "energy_generated_mwh"])
    assert pd.isna(result.loc[0, "nox"])
