from __future__ import annotations

import pandas as pd
import pytest

from nzk_aphiam.fleet.poc_scenarios import (
    _annualized_unit_generation,
    _assign_discrete_retirements,
    _discrete_retirement_multiplier,
    _phaseout_multiplier,
    build_macro_generation,
    plot_generation_scenarios,
)


def test_generation_annualization_combines_duplicate_component_rows_by_month() -> None:
    monthly = pd.DataFrame(
        {
            "unit_id": ["site", "site", "site"],
            "date": ["2024-01-01", "2024-01-01", "2024-02-01"],
            "energy_generated_mwh": [10.0, 20.0, 30.0],
        }
    )

    annual = _annualized_unit_generation(monthly).loc["site"]

    assert annual["baseline_generation_months_reported"] == 2
    assert annual["baseline_generation_annualization_factor"] == 6.0
    assert annual["baseline_generation_mwh"] == 360.0


def test_phaseout_rules_match_requested_2050_endpoints() -> None:
    high = {"phaseout": "all_thermal", "phaseout_fuels": []}
    low = {
        "phaseout": "selected_fuels",
        "phaseout_fuels": ["coal", "oil", "bio_oil_and_diesel"],
    }
    none = {"phaseout": "none", "phaseout_fuels": []}

    assert _phaseout_multiplier(
        year=2035, start_year=2025, end_year=2050, fuel="coal", rule=high
    ) == pytest.approx(0.6)
    assert (
        _phaseout_multiplier(
            year=2050, start_year=2025, end_year=2050, fuel="natural_gas", rule=high
        )
        == 0.0
    )
    assert (
        _phaseout_multiplier(year=2050, start_year=2025, end_year=2050, fuel="coal", rule=low)
        == 0.0
    )
    assert (
        _phaseout_multiplier(
            year=2050, start_year=2025, end_year=2050, fuel="natural_gas", rule=low
        )
        == 1.0
    )
    assert (
        _phaseout_multiplier(year=2050, start_year=2025, end_year=2050, fuel="coal", rule=none)
        == 1.0
    )


def test_macro_fixture_uses_existing_schema_and_retains_zero_groups() -> None:
    detailed = pd.DataFrame(
        [
            {
                "scenario": "nzk_high",
                "year": 2050,
                "province_code": "CNA",
                "fuel": "coal",
                "technology": "conventional_steam_turbine",
                "generation_mwh": 0.0,
            },
            {
                "scenario": "nzk_low",
                "year": 2050,
                "province_code": "GGI",
                "fuel": "natural_gas",
                "technology": "cogeneration_chp",
                "generation_mwh": 2_000_000.0,
            },
            {
                "scenario": "nzk_low",
                "year": 2050,
                "province_code": "GGI",
                "fuel": "natural_gas",
                "technology": "cogeneration_chp",
                "generation_mwh": 1_000_000.0,
            },
        ]
    )

    macro = build_macro_generation(detailed)

    assert macro.columns.tolist() == [
        "Scenario",
        "Year",
        "Province",
        "Technology",
        "Generation_TWh",
    ]
    assert len(macro) == 2
    high = macro.loc[macro["Scenario"].eq("nzk_high")].iloc[0]
    low = macro.loc[macro["Scenario"].eq("nzk_low")].iloc[0]
    assert high["Technology"] == "ThermalPower{Coal}"
    assert high["Generation_TWh"] == 0.0
    assert low["Technology"] == "ThermalSteam{NaturalGas}"
    assert low["Generation_TWh"] == 3.0


def test_discrete_retirements_use_dates_then_whole_unit_priority() -> None:
    baseline = pd.DataFrame(
        {
            "unit_id": ["documented", "old_low_use", "newer", "newest"],
            "fuel": ["coal", "coal", "coal", "coal"],
            "retirement_year": [2026, pd.NA, pd.NA, pd.NA],
            "commissioning_year": [2000, 1980, 1990, 2010],
            "capacity_mw": [100.0, 100.0, 100.0, 100.0],
            "baseline_generation_mwh": [40.0, 30.0, 20.0, 10.0],
            "nox_ef_kg_per_mwh": [1.0, 1.0, 1.0, 1.0],
            "sox_ef_kg_per_mwh": [1.0, 1.0, 1.0, 1.0],
        }
    )
    rule = {"phaseout": "all_thermal", "phaseout_fuels": []}

    schedule = _assign_discrete_retirements(
        baseline,
        years=[2025, 2030, 2035, 2040, 2045, 2050],
        rule=rule,
    ).set_axis(baseline["unit_id"])

    assert schedule.loc["documented", "scenario_retirement_year"] == 2030
    assert schedule.loc["documented", "scenario_retirement_basis"] == "documented_retirement_date"
    assert schedule.loc["old_low_use", "scenario_retirement_year"] == 2040
    assert schedule.loc["newer", "scenario_retirement_year"] == 2045
    assert schedule.loc["newest", "scenario_retirement_year"] == 2050
    assert schedule.loc["old_low_use", "retirement_priority_rank"] == 1


def test_discrete_retirement_multiplier_never_partially_scales_a_unit() -> None:
    values = {
        _discrete_retirement_multiplier(
            year=year,
            targeted=True,
            retirement_year=2040,
        )
        for year in [2025, 2030, 2035, 2040, 2045, 2050]
    }

    assert values == {0.0, 1.0}
    assert (
        _discrete_retirement_multiplier(
            year=2050,
            targeted=False,
            retirement_year=pd.NA,
        )
        == 1.0
    )


def test_stacked_generation_charts_render_for_every_scenario(tmp_path) -> None:
    rows = []
    for scenario in ["no_nzk", "nzk_low", "nzk_high"]:
        for year, coal, gas in [(2025, 100.0, 30.0), (2050, 0.0, 30.0)]:
            rows.extend(
                [
                    {
                        "scenario": scenario,
                        "year": year,
                        "fuel": "coal",
                        "generation_mwh": coal,
                    },
                    {
                        "scenario": scenario,
                        "year": year,
                        "fuel": "natural_gas",
                        "generation_mwh": gas,
                    },
                ]
            )
    outputs = plot_generation_scenarios(pd.DataFrame(rows), tmp_path)

    assert set(outputs) == {
        "figure_no_nzk",
        "figure_nzk_low",
        "figure_nzk_high",
        "figure_all_scenarios",
    }
    assert all(path.exists() and path.stat().st_size > 0 for path in outputs.values())
