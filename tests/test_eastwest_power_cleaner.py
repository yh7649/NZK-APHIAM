from __future__ import annotations

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.eastwest_power import cleaner
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS


def test_clean_eastwest_power_standardizes_schema_and_preserves_rows() -> None:
    raw = pd.DataFrame(
        [
            {
                "날짜": "2024-12-01",
                "먼지(TSP)": "1.25",
                "발전량(MWh)": "2000.5",
                "발전소명": "한국동서발전㈜ 당진발전본부",
                "발전용량(MW)": "500",
                "질소산화물(NOx)": "10.5",
                "호기": "1",
                "황산화물(SOx)": "",
            },
            {
                "날짜": "2024-12-01",
                "먼지(TSP)": None,
                "발전량(MWh)": "1000",
                "발전소명": "한국동서발전㈜울산발전본부",
                "발전용량(MW)": "150",
                "질소산화물(NOx)": "2",
                "호기": "10",
                "황산화물(SOx)": None,
            },
        ],
        columns=cleaner.SOURCE_COLUMNS,
    )

    result = cleaner.clean_eastwest_power(raw)

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == 2
    assert result.loc[0, "date"] == pd.Timestamp("2024-12-01")
    assert result.loc[0, "plant_name"] == "Dangjin"
    assert result.loc[0, "plant_number"] == 1
    assert pd.isna(result.loc[0, "plant_opening_date"])
    assert pd.isna(result.loc[0, "plant_closing_date"])
    assert pd.isna(result.loc[0, "plant_latitude"])
    assert pd.isna(result.loc[0, "plant_longitude"])
    assert result.loc[0, "energy_type"] == "coal"
    assert result.loc[1, "energy_type"] == "natural_gas"
    assert pd.isna(result.loc[0, "sox"])
    assert result.loc[0, "emissions_mass_unit"] == "metric_tonnes"
    assert str(result["plant_number"].dtype) == "Int64"
    assert str(result["plant_latitude"].dtype) == "Float64"
    assert str(result["nox"].dtype) == "Float64"


@pytest.mark.parametrize(
    ("plant", "unit", "expected"),
    [
        ("한국동서발전㈜ 당진발전본부", 10, "coal"),
        ("한국동서발전㈜동해바이오발전본부", 1, "coal"),
        ("한국동서발전㈜신호남건설추진본부", 2, "coal"),
        ("한국동서발전㈜울산발전본부", 6, "oil"),
        ("한국동서발전㈜울산발전본부", 7, "natural_gas"),
        ("한국동서발전㈜일산발전본부", 1, "natural_gas"),
    ],
)
def test_classify_energy_type(plant: str, unit: int, expected: str) -> None:
    assert cleaner.classify_energy_type(plant, unit) == expected


def test_clean_eastwest_power_rejects_source_schema_change() -> None:
    with pytest.raises(ValueError, match="Unexpected East-West Power source columns"):
        cleaner.clean_eastwest_power(pd.DataFrame({"날짜": ["2024-12-01"]}))
