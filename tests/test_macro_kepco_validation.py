from __future__ import annotations

from pathlib import Path

import pandas as pd

from nzk_aphiam.integration import macro_kepco_validation as validation


def test_generation_unit_conversion_requires_explicit_or_column_unit(tmp_path: Path) -> None:
    raw = pd.DataFrame(
        [
            {
                "scenario": "ref",
                "year": 2021,
                "province": "A",
                "fuel": "LNG",
                "technology": "combined cycle",
                "generation_gwh": 2.5,
            }
        ]
    )

    standardized = validation.standardize_macro_generation(
        raw, source_file=tmp_path / "macro.csv", year=2021
    )

    assert standardized.loc[0, "generation_original_unit"] == "GWh"
    assert standardized.loc[0, "generation_mwh"] == 2500.0


def test_combined_macro_type_is_split_into_fuel_and_technology(tmp_path: Path) -> None:
    raw = pd.DataFrame(
        [
            {
                "Year": 2021,
                "Province": "CNA",
                "Technology": "ThermalPower{Coal}",
                "Generation_TWh": 0.1,
            },
            {
                "Year": 2021,
                "Province": "CNA",
                "Technology": "VRE",
                "Generation_TWh": 0.2,
            },
        ]
    )

    standardized = validation.standardize_macro_generation(
        raw, source_file=tmp_path / "macro.csv", year=2021
    )

    assert standardized.loc[0, "macro_fuel"] == "Coal"
    assert standardized.loc[0, "macro_technology"] == "ThermalPower"
    assert standardized.loc[0, "macro_type"] == "ThermalPower{Coal}"
    assert standardized.loc[1, "macro_fuel"] == "VRE"
    assert standardized.loc[1, "macro_technology"] == "VRE"
    assert standardized.loc[0, "generation_mwh"] == 100000.0


def test_prepare_kepco_ef_uses_generation_weighted_field(tmp_path: Path) -> None:
    path = tmp_path / "kepco.csv"
    pd.DataFrame(
        [
            {
                "year": 2021,
                "fuel_type_clean": "coal",
                "technology": "conventional_steam_turbine",
                "pollutant": "nox",
                "ef_kg_per_mwh": 0.5,
                "plant_ef_mean_kg_per_mwh": 99.0,
                "valid_generation_mwh": 100.0,
                "plant_count": 2,
            }
        ]
    ).to_csv(path, index=False)

    ef = validation.prepare_kepco_ef(path, 2021)

    assert ef.loc[0, "emission_factor_kg_per_mwh"] == 0.5
    assert ef.loc[0, "emissions_kg_used_for_ef"] == 50.0
    assert ef.loc[0, "pollutant"] == "NOx"


def test_crosswalk_duplicate_matches_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "crosswalk.csv"
    rows = [
        {
            "macro_fuel": "coal",
            "macro_technology": "steam",
            "kepco_fuel": "coal",
            "kepco_technology": "conventional_steam_turbine",
            "capss_fuel_major_ko": "유연탄",
            "capss_technology_official_ko": "1,2,3종(보일러)",
            "mapping_status": "documented_proxy",
            "mapping_note": "a",
        },
        {
            "macro_fuel": "coal",
            "macro_technology": "steam",
            "kepco_fuel": "coal",
            "kepco_technology": "other",
            "capss_fuel_major_ko": "유연탄",
            "capss_technology_official_ko": "1,2,3종(보일러)",
            "mapping_status": "documented_proxy",
            "mapping_note": "b",
        },
    ]
    pd.DataFrame(rows).to_csv(path, index=False)

    usable, duplicates = validation.load_crosswalk(path)

    assert len(usable) == 2
    assert len(duplicates) == 2


def test_modeled_emissions_are_calculated_per_pollutant_and_unmatched_rows_diagnosed() -> None:
    macro = pd.DataFrame(
        [
            {
                "scenario": "ref",
                "year": 2021,
                "province": "A",
                "macro_fuel": "coal",
                "macro_technology": "steam",
                "generation_mwh": 100.0,
            },
            {
                "scenario": "ref",
                "year": 2021,
                "province": "A",
                "macro_fuel": "unknown",
                "macro_technology": "steam",
                "generation_mwh": 100.0,
            },
        ]
    )
    ef = pd.DataFrame(
        [
            {
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "pollutant": "NOx",
                "emission_factor_kg_per_mwh": 0.5,
            },
            {
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "pollutant": "SOx",
                "emission_factor_kg_per_mwh": 0.2,
            },
        ]
    )
    crosswalk = pd.DataFrame(
        [
            {
                "macro_fuel": "coal",
                "macro_technology": "steam",
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "capss_fuel_major_ko": "유연탄",
                "capss_technology_official_ko": "1,2,3종(보일러)",
                "mapping_status": "documented_proxy",
                "mapping_note": "test",
            }
        ]
    )

    modeled, unmapped, missing_ef = validation.calculate_modeled_emissions(macro, ef, crosswalk)

    assert set(modeled["modeled_emissions_kg"]) == {50.0, 20.0}
    assert len(unmapped) == 1
    assert missing_ef.empty


def test_comparison_handles_zero_actual_and_aggregates_two_provinces() -> None:
    modeled = pd.DataFrame(
        [
            {
                "scenario": "ref",
                "year": 2021,
                "province": "A",
                "macro_fuel": "coal",
                "macro_technology": "steam",
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "capss_fuel_major_ko": "유연탄",
                "capss_technology_official_ko": "1,2,3종(보일러)",
                "pollutant": "NOx",
                "generation_mwh": 100.0,
                "emission_factor_kg_per_mwh": 0.5,
                "modeled_emissions_kg": 50.0,
                "mapping_status": "documented_proxy",
                "mapping_note": "test",
            },
            {
                "scenario": "ref",
                "year": 2021,
                "province": "B",
                "macro_fuel": "coal",
                "macro_technology": "steam",
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "capss_fuel_major_ko": "유연탄",
                "capss_technology_official_ko": "1,2,3종(보일러)",
                "pollutant": "NOx",
                "generation_mwh": 25.0,
                "emission_factor_kg_per_mwh": 0.5,
                "modeled_emissions_kg": 12.5,
                "mapping_status": "documented_proxy",
                "mapping_note": "test",
            },
            {
                "scenario": "ref",
                "year": 2021,
                "province": "A",
                "macro_fuel": "coal",
                "macro_technology": "steam",
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "capss_fuel_major_ko": "유연탄",
                "capss_technology_official_ko": "1,2,3종(보일러)",
                "pollutant": "SOx",
                "generation_mwh": 100.0,
                "emission_factor_kg_per_mwh": 0.1,
                "modeled_emissions_kg": 10.0,
                "mapping_status": "documented_proxy",
                "mapping_note": "test",
            },
        ]
    )
    capss = pd.DataFrame(
        [
            {
                "year": 2021,
                "fuel_major_ko": "유연탄",
                "technology_official_ko": "1,2,3종(보일러)",
                "pollutant": "NOx",
                "actual_capss_emissions_kg": 50.0,
                "actual_capss_emissions_tonnes": 0.05,
            },
            {
                "year": 2021,
                "fuel_major_ko": "유연탄",
                "technology_official_ko": "1,2,3종(보일러)",
                "pollutant": "SOx",
                "actual_capss_emissions_kg": 0.0,
                "actual_capss_emissions_tonnes": 0.0,
            },
        ]
    )

    comparison, missing = validation.compare_to_capss(modeled, capss)

    nox = comparison.loc[comparison["pollutant"] == "NOx"].iloc[0]
    sox = comparison.loc[comparison["pollutant"] == "SOx"].iloc[0]
    assert nox["modeled_emissions_kg"] == 62.5
    assert nox["generation_mwh"] == 125.0
    assert nox["percent_error"] == 25.0
    assert pd.isna(sox["percent_error"])
    assert missing.empty
