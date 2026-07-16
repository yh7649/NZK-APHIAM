from __future__ import annotations

import pandas as pd

from nzk_aphiam.integration import epsis_kepco_capss_validation as validation


def test_parse_epsis_generation_html_extracts_year_rows() -> None:
    html = """
    if($("#srchDate option:selected").val()=="2021"){
      idx = "17";
      genName = "유연탄";
      c1 = "0"; c2 = "0"; c3 = "0"; c4 = "0";
      c5 = "0"; c6 = "185629"; c7 = "0"; c8 = "0"; c9 = "185629";
      c10 = "0"; c11 = "0"; c12 = "0"; c13 = "0"; c14 = "0";
      c15 = "10476"; c16 = "0"; c17 = "196105"; c18 = "0";
      c19 = "196105"; c20 = "0";
      gridData.push({"idx":idx,"genName":genName,"c1":c1});
    }
    """

    parsed = validation.parse_epsis_generation_html(html)

    assert parsed.loc[0, "year"] == 2021
    assert parsed.loc[0, "epsis_row_label_ko"] == "유연탄"
    assert parsed.loc[0, "c6"] == 185629


def test_build_observed_generation_converts_gwh_to_mwh_and_flags_unresolved() -> None:
    grid = pd.DataFrame(
        [
            {"year": 2021, "epsis_row_label_ko": "유연탄", "c6": 185629.0},
            {"year": 2021, "epsis_row_label_ko": "무연탄", "c5": 1844.0},
            {"year": 2021, "epsis_row_label_ko": "LNG", "c10": 130218.0, "c8": 1177.0},
            {"year": 2021, "epsis_row_label_ko": "유류", "c16": 491.0},
        ]
    )

    observed, diagnostics = validation.build_observed_generation(grid, 2021)

    coal = observed.loc[observed["capss_fuel_major_ko"] == "유연탄"].iloc[0]
    assert coal["generation_original_unit"] == "GWh"
    assert coal["generation_mwh"] == 185629000.0
    assert "not_in_primary_comparison" in diagnostics["diagnostic"].tolist()


def test_calculate_epsis_modeled_multiplies_generation_by_pollutant_ef() -> None:
    observed = pd.DataFrame(
        [
            {
                "scenario": "observed_epsis",
                "year": 2021,
                "province": "national",
                "epsis_row_label_ko": "유연탄",
                "epsis_generation_form_ko": "기력",
                "generation_mwh": 100.0,
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "capss_fuel_major_ko": "유연탄",
                "capss_technology_official_ko": "1,2,3종(보일러)",
                "mapping_status": "documented_proxy",
                "mapping_note": "test",
            }
        ]
    )
    ef = pd.DataFrame(
        [
            {
                "kepco_fuel": "coal",
                "kepco_technology": "conventional_steam_turbine",
                "pollutant": "NOx",
                "emission_factor_kg_per_mwh": 0.5,
            }
        ]
    )

    modeled, missing = validation.calculate_epsis_modeled(observed, ef)

    assert modeled.loc[0, "modeled_emissions_kg"] == 50.0
    assert modeled.loc[0, "modeled_emissions_tonnes"] == 0.05
    assert missing.empty
