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
    assert pd.isna(result.loc[0, "plant_opening_date"])
    assert pd.isna(result.loc[0, "plant_closing_date"])
    assert pd.isna(result.loc[0, "plant_latitude"])
    assert pd.isna(result.loc[0, "plant_longitude"])
    assert result.loc[0, "energy_type"] == "coal"
    assert result.loc[0, "nox"] == 12.5
    assert result.loc[0, "emissions_mass_unit"] == "metric_tonnes"
    assert result.loc[0, "original_korean_plant_name"] == "태안"
    assert result.loc[0, "original_korean_unit_name"] == "1호기"
    assert pd.isna(result.loc[1, "plant_number"])
    assert pd.isna(result.loc[1, "energy_generated_mwh"])
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
def test_classify_energy_type(
    plant: str,
    unit: str,
    month: str,
    expected: str,
) -> None:
    assert cleaner.classify_energy_type(plant, unit, pd.Timestamp(month)) == expected


def test_clean_western_power_rejects_source_schema_change() -> None:
    raw = pd.DataFrame({"날짜": ["2025-06"]})

    with pytest.raises(ValueError, match="Unexpected Western Power source columns"):
        cleaner.clean_western_power(raw)
