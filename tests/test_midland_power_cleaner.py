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
                "발전소 호기": "서천 1호기",
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
                "발전소 호기": "서천 1호기",
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

    generation = pd.DataFrame(
        [
            {
                "orgnm": "신서천화력",
                "ym": 202506,
                "hokinm": "소계",
                "capacity": 1018,
                "qvodgen": 334311,
                "tper": 0,
                "uper": "45.00",
                "gennm": "석탄",
            }
        ]
    )
    result = cleaner.clean_midland_power(raw, generation)

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == 1
    assert result.loc[0, "date"] == pd.Timestamp("2025-06-01")
    assert result.loc[0, "plant_name"] == "Seocheon"
    assert pd.isna(result.loc[0, "plant_number"])
    assert result.loc[0, "energy_generated_mwh"] == 334311
    assert result.loc[0, "energy_capacity_mw"] == 1018
    assert result.loc[0, "energy_type"] == "coal"
    assert result.loc[0, "reporting_unit_id"] == "midland_power:신서천화력"
    assert result.loc[0, "observation_level"] == "generation_block"
    assert result.loc[0, "component_count"] == 1
    expected_nox = 27.37 * 72495.55 * 46 / (22.4 * 1_000_000) + 2 * 1000 * 46 / (22.4 * 1_000_000)
    expected_sox = 11.78 * 72495.55 * 64 / (22.4 * 1_000_000) + 1 * 1000 * 64 / (22.4 * 1_000_000)
    expected_dust = 5.01 * 72495.55 / 1_000_000 + 3 * 1000 / 1_000_000
    assert result.loc[0, "nox"] == pytest.approx(expected_nox)
    assert result.loc[0, "sox"] == pytest.approx(expected_sox)
    assert result.loc[0, "dust_tsp"] == pytest.approx(expected_dust)
    assert result.loc[0, "pollutant_measurement_basis"] == "mass"
    assert result.loc[0, "nox_unit"] == "kilograms"
    assert "Generation is not allocated" in result.loc[0, "original_korean_note"]
    assert pd.notna(result.loc[0, "plant_opening_date"])
    assert pd.notna(result.loc[0, "plant_latitude"])
    assert str(result["plant_number"].dtype) == "Int64"
    assert str(result["nox"].dtype) == "Float64"


def test_clean_midland_power_rejects_missing_required_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        cleaner.clean_midland_power(
            pd.DataFrame({"source_facility": ["seocheon"]}), pd.DataFrame()
        )


def test_clean_midland_power_aggregates_components_before_joining_generation() -> None:
    facility = pd.DataFrame(
        [
            {
                "source_facility": "incheon",
                "source_korean_facility_name": "인천발전소",
                "source_english_facility_name": "Incheon",
                "usable_for_mass_derivation": True,
                "발전소 호기": unit,
                "처리일": "2024-01-01 00:00",
                "황산화물": 0,
                "질소 산화물": 10,
                "먼지": 1,
                "유량": 1000,
            }
            for unit in ["인천 GT1", "인천 GT2"]
        ]
    )
    generation = pd.DataFrame(
        [
            {
                "orgnm": "인천복합",
                "ym": 202401,
                "hokinm": "소계",
                "capacity": 1462,
                "qvodgen": 500000,
                "tper": 0,
                "uper": "50.00",
                "gennm": "복합",
            }
        ]
    )

    result = cleaner.clean_midland_power(facility, generation)

    assert len(result) == 1
    assert result.loc[0, "component_count"] == 2
    assert result.loc[0, "energy_generated_mwh"] == 500000
    expected_nox = 2 * 10 * 1000 * 46 / (22.4 * 1_000_000)
    assert result.loc[0, "nox"] == pytest.approx(expected_nox)


def _make_incheon_facility(date: str = "2024-01-01 00:00") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_facility": "incheon",
                "source_korean_facility_name": "인천발전소",
                "source_english_facility_name": "Incheon",
                "usable_for_mass_derivation": True,
                "발전소 호기": "인천 GT1",
                "처리일": date,
                "황산화물": 0,
                "질소 산화물": 20,
                "먼지": 0,
                "유량": 500_000,
            }
        ]
    )


def test_clean_midland_power_with_aggregate_back_fill() -> None:
    """Historical Incheon rows from aggregate API are estimated and appended."""
    # One odcloud row for 2024-01 (provides the flow proxy)
    facility = _make_incheon_facility("2024-01-01 00:00")

    # Aggregate row for 2015-06 (historical — not covered by odcloud)
    aggregate = pd.DataFrame(
        [["인천화력", "201506", "복합", 50, 15.0, 280, 20.0, 25, 0.5]],
        columns=cleaner.AGGREGATE_SOURCE_COLUMNS,
    )

    generation = pd.DataFrame(
        [
            {
                "orgnm": "인천복합",
                "ym": 202401,
                "hokinm": "소계",
                "capacity": 1462,
                "qvodgen": 500_000,
                "tper": 0,
                "uper": "50.00",
                "gennm": "복합",
            },
            {
                "orgnm": "인천복합",
                "ym": 201506,
                "hokinm": "소계",
                "capacity": 1012,
                "qvodgen": 400_000,
                "tper": 0,
                "uper": "45.00",
                "gennm": "복합",
            },
        ]
    )

    result = cleaner.clean_midland_power(facility, generation, aggregate)

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    # Both 2015-06 (estimated) and 2024-01 (direct) should appear
    assert len(result) == 2
    dates = set(result["date"].dt.strftime("%Y-%m"))
    assert "2015-06" in dates
    assert "2024-01" in dates

    # Estimated row uses PROXY_NOTE
    hist_row = result[result["date"] == pd.Timestamp("2015-06-01")].iloc[0]
    assert "proxy" in hist_row["original_korean_note"].lower()
    assert pd.isna(hist_row["component_count"])

    # Direct row uses DERIVATION_NOTE
    direct_row = result[result["date"] == pd.Timestamp("2024-01-01")].iloc[0]
    assert "Generation is not allocated" in direct_row["original_korean_note"]
    assert direct_row["component_count"] == 1

    # Estimated NOx should be positive (avg_nox_ppm=20, proxy_flow>0, gen=400000 MWh)
    assert hist_row["nox"] > 0


def test_aggregate_back_fill_skips_months_covered_by_odcloud() -> None:
    """Aggregate rows for months already in odcloud data are dropped."""
    facility = _make_incheon_facility("2024-01-01 00:00")
    # Aggregate row for the SAME month as the odcloud row
    aggregate = pd.DataFrame(
        [["인천화력", "202401", "복합", 50, 15.0, 280, 20.0, 25, 0.5]],
        columns=cleaner.AGGREGATE_SOURCE_COLUMNS,
    )
    generation = pd.DataFrame(
        [
            {
                "orgnm": "인천복합",
                "ym": 202401,
                "hokinm": "소계",
                "capacity": 1462,
                "qvodgen": 500_000,
                "tper": 0,
                "uper": "50.00",
                "gennm": "복합",
            }
        ]
    )
    result = cleaner.clean_midland_power(facility, generation, aggregate)
    # Overlap is excluded → only the direct odcloud row survives
    assert len(result) == 1
    direct_row = result.iloc[0]
    assert "Generation is not allocated" in direct_row["original_korean_note"]


def test_clean_midland_power_rejects_unmapped_facility_identity() -> None:
    facility = pd.DataFrame(
        [
            {
                "source_facility": "jeju",
                "source_korean_facility_name": "제주발전소",
                "source_english_facility_name": "Jeju",
                "usable_for_mass_derivation": True,
                "발전소 호기": "새로운호기",
                "처리일": "2024-01-01",
                "황산화물": 0,
                "질소 산화물": 1,
                "먼지": 0,
                "유량": 100,
            }
        ]
    )
    generation = pd.DataFrame(columns=cleaner.GENERATION_SOURCE_COLUMNS)

    with pytest.raises(ValueError, match="Unmapped Midland facility reporting identities"):
        cleaner.clean_midland_power(facility, generation)
