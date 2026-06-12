from __future__ import annotations

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.southeast_power import cleaner


def test_clean_southeast_power_preserves_daily_measurements() -> None:
    raw = pd.DataFrame(
        [
            {
                "사업소": "삼천포",
                "호기": "3A호기",
                "일자": "20260611",
                "SOX": "11.78",
                "NOX": "27.37",
                "먼지": "5.01",
                "산소": "6.61",
                "유량": "72495.55",
                "온도": "91.87",
            },
            {
                "사업소": "여수",
                "호기": "-",
                "일자": "20260610",
                "SOX": None,
                "NOX": "",
                "먼지": None,
                "산소": None,
                "유량": None,
                "온도": None,
            },
        ],
        columns=cleaner.SOURCE_COLUMNS,
    )

    result = cleaner.clean_southeast_power(raw)

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == len(raw)
    assert result.loc[0, "date"] == pd.Timestamp("2026-06-11")
    assert result.loc[0, "plant_name"] == "Samcheonpo"
    assert result.loc[0, "plant_number"] == 3
    assert result.loc[0, "original_korean_unit_name"] == "3A호기"
    assert pd.isna(result.loc[1, "plant_number"])
    assert result.loc[0, "nox"] == 27.37
    assert result.loc[0, "oxygen"] == 6.61
    assert result.loc[0, "flue_gas_flow"] == 72495.55
    assert result.loc[0, "temperature_celsius"] == 91.87
    assert result.loc[0, "pollutant_measurement_basis"] == "concentration"
    assert result.loc[0, "nox_unit"] == "not_reported"
    assert pd.isna(result.loc[0, "emissions_mass_unit"])
    assert pd.isna(result.loc[0, "energy_generated_mwh"])
    assert pd.isna(result.loc[0, "energy_type"])
    assert str(result["plant_number"].dtype) == "Int64"
    assert str(result["nox"].dtype) == "Float64"


def test_clean_southeast_power_rejects_unknown_plant() -> None:
    raw = pd.DataFrame(
        [["새발전소", "1호기", "20260611", 1, 2, 3, 4, 5, 6]],
        columns=cleaner.SOURCE_COLUMNS,
    )

    with pytest.raises(ValueError, match="Unknown South-East Power plant names"):
        cleaner.clean_southeast_power(raw)


def test_clean_southeast_power_rejects_source_schema_change() -> None:
    with pytest.raises(ValueError, match="Unexpected South-East Power source columns"):
        cleaner.clean_southeast_power(pd.DataFrame({"사업소": ["영흥"]}))
