from __future__ import annotations

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.southeast_power import cleaner


def generation_row(plant: str = "삼천포", unit: str = "3") -> pd.DataFrame:
    return pd.DataFrame(
        [[plant, unit, "202606", 560, 123456, 40, 30, "석탄"]],
        columns=cleaner.GENERATION_SOURCE_COLUMNS,
    )


def test_clean_southeast_power_derives_monthly_mass() -> None:
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
                "사업소": "삼천포",
                "호기": "3A호기",
                "일자": "20260612",
                "SOX": "1",
                "NOX": "2",
                "먼지": "122.41",
                "산소": None,
                "유량": "1000",
                "온도": None,
            },
            {
                "사업소": "삼천포",
                "호기": "3B호기",
                "일자": "20260612",
                "SOX": "3",
                "NOX": "4",
                "먼지": "6",
                "산소": None,
                "유량": "2000",
                "온도": None,
            },
        ],
        columns=cleaner.SOURCE_COLUMNS,
    )

    result = cleaner.clean_southeast_power(raw, generation_row())

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == 1
    assert result.loc[0, "date"] == pd.Timestamp("2026-06-01")
    assert result.loc[0, "plant_name"] == "Samcheonpo"
    assert result.loc[0, "plant_number"] == 3
    assert result.loc[0, "original_korean_unit_name"] == "3A호기; 3B호기"
    expected_nox = (
        27.37 * 72495.55 * 46 / (22.4 * 1_000_000) * 288
        + 2 * 1000 * 46 / (22.4 * 1_000_000) * 288
        + 4 * 2000 * 46 / (22.4 * 1_000_000) * 288
    )
    expected_sox = (
        11.78 * 72495.55 * 64 / (22.4 * 1_000_000) * 288
        + 1 * 1000 * 64 / (22.4 * 1_000_000) * 288
        + 3 * 2000 * 64 / (22.4 * 1_000_000) * 288
    )
    expected_dust = 5.01 * 72495.55 / 1_000_000 * 288 + 6 * 2000 / 1_000_000 * 288
    assert result.loc[0, "nox"] == pytest.approx(expected_nox)
    assert result.loc[0, "sox"] == pytest.approx(expected_sox)
    assert result.loc[0, "dust_tsp"] == pytest.approx(expected_dust)
    assert pd.isna(result.loc[0, "oxygen"])
    assert pd.isna(result.loc[0, "flue_gas_flow"])
    assert pd.isna(result.loc[0, "temperature_celsius"])
    assert result.loc[0, "pollutant_measurement_basis"] == "mass"
    assert result.loc[0, "nox_unit"] == "kilograms"
    assert result.loc[0, "emissions_mass_unit"] == "kilograms"
    assert "dust concentration rows >30 mg/Sm3" in result.loc[0, "original_korean_note"]
    assert result.loc[0, "component_count"] == 2
    assert result.loc[0, "energy_generated_mwh"] == 123456
    assert result.loc[0, "energy_capacity_mw"] == 560
    assert result.loc[0, "fuel_type"] == "coal"
    assert result.loc[0, "technology"] == "conventional_steam_turbine"
    assert result.loc[0, "observation_level"] == "generating_unit"
    assert str(result["plant_number"].dtype) == "Int64"
    assert str(result["nox"].dtype) == "Float64"


def test_clean_southeast_power_rejects_unknown_plant() -> None:
    raw = pd.DataFrame(
        [["새발전소", "1호기", "20260611", 1, 2, 3, 4, 5, 6]],
        columns=cleaner.SOURCE_COLUMNS,
    )

    with pytest.raises(ValueError, match="Unknown South-East Power plant names"):
        cleaner.clean_southeast_power(raw, generation_row())


def test_clean_southeast_power_rejects_source_schema_change() -> None:
    with pytest.raises(ValueError, match="Unexpected South-East Power source columns"):
        cleaner.clean_southeast_power(pd.DataFrame({"사업소": ["영흥"]}), generation_row())


def test_crosswalks_bundang_and_yeosu_unit_labels() -> None:
    assert cleaner.generation_unit_identity("분당", "8호기", emissions=True) == "CG8"
    assert cleaner.generation_unit_identity("분당", "CG8", emissions=False) == "CG8"
    assert cleaner.generation_unit_identity("여수", "-", emissions=True) == "2"
