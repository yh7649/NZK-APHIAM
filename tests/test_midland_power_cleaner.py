from __future__ import annotations

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.midland_power import cleaner
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS


def test_clean_midland_power_derives_monthly_mass_from_usable_facility_rows() -> None:
    raw = pd.DataFrame(
        [
            {
                "source_facility": "seocheon",
                "source_korean_facility_name": "서천발전소",
                "source_english_facility_name": "Seocheon",
                "usable_for_mass_derivation": True,
                "발전소 호기": "1호기",
                "처리일": "2025-06-01 00:00",
                "황산화물": "11.78",
                "질소 산화물": "27.37",
                "먼지": "5.01",
                "산소": "6.61",
                "유량": "72495.55",
                "온도": "91.87",
            },
            {
                "source_facility": "seocheon",
                "source_korean_facility_name": "서천발전소",
                "source_english_facility_name": "Seocheon",
                "usable_for_mass_derivation": True,
                "발전소 호기": "1호기",
                "처리일": "202506010100",
                "황산화물": "1",
                "질소 산화물": "2",
                "먼지": "3",
                "산소": None,
                "유량": "1000",
                "온도": None,
            },
            {
                "source_facility": "boryeong",
                "source_korean_facility_name": "보령발전소",
                "source_english_facility_name": "Boryeong",
                "usable_for_mass_derivation": False,
                "발전소 호기": None,
                "처리일": "2025-06-01 00:00",
                "황산화물": None,
                "질소 산화물": None,
                "먼지": None,
                "산소": None,
                "유량": None,
                "온도": None,
            },
        ]
    )

    result = cleaner.clean_midland_power(raw)

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == 1
    assert result.loc[0, "date"] == pd.Timestamp("2025-06-01")
    assert result.loc[0, "plant_name"] == "Seocheon"
    assert result.loc[0, "plant_number"] == 1
    expected_nox = 27.37 * 72495.55 * 46 / (22.4 * 1_000_000) + 2 * 1000 * 46 / (22.4 * 1_000_000)
    expected_sox = 11.78 * 72495.55 * 64 / (22.4 * 1_000_000) + 1 * 1000 * 64 / (22.4 * 1_000_000)
    expected_dust = 5.01 * 72495.55 / 1_000_000 + 3 * 1000 / 1_000_000
    assert result.loc[0, "nox"] == pytest.approx(expected_nox)
    assert result.loc[0, "sox"] == pytest.approx(expected_sox)
    assert result.loc[0, "dust_tsp"] == pytest.approx(expected_dust)
    assert result.loc[0, "pollutant_measurement_basis"] == "mass"
    assert result.loc[0, "nox_unit"] == "kilograms"
    assert "Row-level approximation" in result.loc[0, "original_korean_note"]
    assert str(result["plant_number"].dtype) == "Int64"
    assert str(result["nox"].dtype) == "Float64"


def test_clean_midland_power_rejects_missing_required_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        cleaner.clean_midland_power(pd.DataFrame({"source_facility": ["seocheon"]}))
