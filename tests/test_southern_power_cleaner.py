from __future__ import annotations

import pandas as pd

from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.southern_power import cleaner


def test_clean_southern_power_aggregates_daily_generation_and_stack_rows() -> None:
    emissions = pd.DataFrame(
        [
            ["2025-01", "한국남부발전㈜삼척빛드림본부", "10", "1", "1A", "2"],
            ["2025-01", "한국남부발전㈜삼척빛드림본부", "20", "3", "1B", "4"],
        ],
        columns=cleaner.EMISSIONS_COLUMNS,
    )
    generation = pd.DataFrame(
        [
            ["2025-01-01", "삼척", "복합", "삼척#1", "1", "1022000", "", "1000000", ""],
            ["2025-01-02", "삼척", "복합", "삼척#1", "1", "1022000", "", "2000000", ""],
        ],
        columns=cleaner.GENERATION_COLUMNS,
    )

    result = cleaner.clean_southern_power(emissions, generation)

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == 1
    assert result.loc[0, "plant_name"] == "Samcheok"
    assert result.loc[0, "plant_number"] == 1
    assert pd.isna(result.loc[0, "plant_opening_date"])
    assert pd.isna(result.loc[0, "plant_closing_date"])
    assert pd.isna(result.loc[0, "plant_latitude"])
    assert pd.isna(result.loc[0, "plant_longitude"])
    assert result.loc[0, "energy_type"] == "coal"
    assert result.loc[0, "energy_generated_mwh"] == 3000
    assert result.loc[0, "energy_capacity_mw"] == 1022
    assert result.loc[0, "nox"] == 30
    assert result.loc[0, "sox"] == 6
    assert result.loc[0, "dust_tsp"] == 4
    assert result.loc[0, "emissions_mass_unit"] == "kilograms"
    assert str(result["plant_latitude"].dtype) == "Float64"
    assert result.loc[0, "original_korean_unit_name"] == "1A|1B"


def test_clean_emissions_preserves_total_reported_mass() -> None:
    emissions = pd.DataFrame(
        [
            ["2025-01", "한국남부발전㈜하동빛드림본부", "10", "1", "1", "2"],
            ["2025-01", "한국남부발전㈜하동빛드림본부", "20", "3", "2", "4"],
            ["2025-01", "한국남부발전㈜남제주빛드림본부(복합)", "5", "2", "1", "1"],
            ["2025-01", "한국남부발전㈜남제주빛드림본부(복합)", "7", "4", "11", "3"],
        ],
        columns=cleaner.EMISSIONS_COLUMNS,
    )

    result = cleaner.clean_emissions(emissions)

    assert result["nox"].sum() == 42
    assert result["sox"].sum() == 10
    assert result["dust_tsp"].sum() == 10
    assert len(result) == 3


def test_generation_target_ignores_missing_plant_name() -> None:
    row = pd.Series({"ipptnm": pd.NA, "hogi": pd.NA})

    assert cleaner.generation_target(row) is None
