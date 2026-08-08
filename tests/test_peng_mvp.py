from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import box

from nzk_aphiam.fleet.scenario_allocator import allocate_generation, eligible_fleet
from nzk_aphiam.mvp.peng_replication.config import _validate_health_config
from nzk_aphiam.mvp.peng_replication.emissions import (
    construct_emissions,
    prepare_ef_table,
)
from nzk_aphiam.mvp.peng_replication.health_adapter import (
    build_national_health_inputs,
    calculate_avoided_deaths,
)
from nzk_aphiam.mvp.peng_replication.pipeline import (
    _label_diagnostic_poc_health,
    _pm_change_figure,
    _write_report,
)
from nzk_aphiam.mvp.peng_replication.scenarios import (
    normalize_macro_scenarios,
    select_scenarios,
)
from nzk_aphiam.mvp.peng_replication.stacks import impute_stack_parameters


def _fleet(**updates: object) -> pd.DataFrame:
    base = {
        "plant_id": "p1",
        "plant_name": "Plant 1",
        "unit_id": "u1",
        "subsidiary_company": "Company",
        "province": "A",
        "fuel": "coal",
        "technology": "steam",
        "capacity_mw": 100.0,
        "commissioning_year": 2000.0,
        "retirement_year": float("nan"),
        "recent_historical_generation_mwh": 10.0,
        "latitude": 36.0,
        "longitude": 127.0,
        "synthetic_site_flag": False,
    }
    base.update(updates)
    return pd.DataFrame([base])


def _generation(**updates: object) -> pd.DataFrame:
    base = {
        "scenario": "scenario",
        "year": 2030,
        "province": "A",
        "fuel": "coal",
        "technology": "steam",
        "generation_mwh": 1000.0,
    }
    base.update(updates)
    return pd.DataFrame([base])


def test_macro_normalization_filters_non_emitting_and_maps_province(tmp_path: Path) -> None:
    path = tmp_path / "macro.csv"
    pd.DataFrame(
        [
            {
                "Year": 2030,
                "Province": "AAA",
                "Technology": "ThermalPower{Coal}",
                "Generation_TWh": 0.25,
            },
            {
                "Year": 2030,
                "Province": "AAA",
                "Technology": "VRE",
                "Generation_TWh": 1.0,
            },
        ]
    ).to_csv(path, index=False)
    normalized = normalize_macro_scenarios(
        path,
        scenario_label="only_pathway",
        province_crosswalk={"AAA": "Province A"},
        fuel_crosswalk={"Coal": "coal"},
        technology_crosswalk={"ThermalPower": {"Coal": "steam"}},
    )
    assert len(normalized) == 1
    assert normalized.loc[0, "scenario"] == "only_pathway"
    assert normalized.loc[0, "province"] == "Province A"
    assert normalized.loc[0, "generation_mwh"] == 250_000.0


def test_single_pathway_forces_historical_to_scenario_label() -> None:
    macro = pd.DataFrame([{"scenario": "only", "year": 2030}])
    selected = select_scenarios(
        macro,
        historical_year=2021,
        target_year=2030,
        reference_scenario=None,
        policy_scenario="only",
        historical_scenario_label="observed_2021",
    )
    assert selected["comparison_type"] == "historical_to_scenario"
    assert selected["reference_scenario"] == "observed_2021"
    assert not selected["causal_policy_claim_permitted"]


def test_pm_change_figure_renders(tmp_path: Path) -> None:
    import geopandas as gpd

    cells = gpd.GeoDataFrame(
        {"delta_TotalPM25": [-0.1, 0.2]},
        geometry=[box(126.0, 35.0, 127.0, 36.0), box(127.0, 35.0, 128.0, 36.0)],
        crs="EPSG:4326",
    )
    destination = tmp_path / "pm_change.png"
    _pm_change_figure(cells, destination)
    assert destination.exists()
    assert destination.stat().st_size > 0


def test_diagnostic_health_label_orients_additional_deaths() -> None:
    health = pd.DataFrame(
        {
            "avoided_deaths": [-10.0],
            "avoided_deaths_ci_low": [-7.0],
            "avoided_deaths_ci_high": [-13.0],
        }
    )
    diagnostic = _label_diagnostic_poc_health(health, num_iterations=200)
    assert diagnostic.loc[0, "additional_deaths_policy_minus_reference"] == 10.0
    assert diagnostic.loc[0, "additional_deaths_crf_ci_low"] == 7.0
    assert diagnostic.loc[0, "additional_deaths_crf_ci_high"] == 13.0
    assert not diagnostic.loc[0, "inmap_converged"]
    assert not diagnostic.loc[0, "analytical_use_permitted"]


def test_retirement_handling_keeps_target_year_but_excludes_earlier_retirement() -> None:
    fleet = pd.concat(
        [
            _fleet(unit_id="retire_in_target", retirement_year=2030),
            _fleet(unit_id="retired_before", retirement_year=2029),
            _fleet(unit_id="future", commissioning_year=2031),
        ],
        ignore_index=True,
    )
    eligible = eligible_fleet(fleet, 2030)
    assert eligible["unit_id"].tolist() == ["retire_in_target"]


def test_capacity_allocation_and_group_mass_balance() -> None:
    fleet = pd.concat(
        [_fleet(unit_id="u1", capacity_mw=100), _fleet(unit_id="u2", capacity_mw=300)],
        ignore_index=True,
    )
    allocated, diagnostics = allocate_generation(
        _generation(), fleet, fuel_compatibility={"coal": ["coal"]}
    )
    assert allocated.set_index("unit_id")["generation_mwh"].to_dict() == {
        "u1": 250.0,
        "u2": 750.0,
    }
    assert diagnostics.loc[0, "mass_balance_error_mwh"] == pytest.approx(0.0)
    assert diagnostics.loc[0, "match_level"] == "exact_fuel_technology"


def test_zero_generation_preserves_scenario_rows_for_phaseout_endpoint() -> None:
    allocated, diagnostics = allocate_generation(
        _generation(generation_mwh=0.0),
        _fleet(),
        fuel_compatibility={"coal": ["coal"]},
    )
    assert len(allocated) == 1
    assert allocated.loc[0, "scenario"] == "scenario"
    assert allocated.loc[0, "generation_mwh"] == 0.0
    assert allocated.loc[0, "allocation_rule"] == "zero_generation:exact_fuel_technology"
    assert diagnostics.loc[0, "status"] == "zero_generation"


def test_historical_then_equal_allocation_hierarchy() -> None:
    fleet = pd.concat(
        [
            _fleet(unit_id="u1", capacity_mw=float("nan"), recent_historical_generation_mwh=1),
            _fleet(unit_id="u2", capacity_mw=float("nan"), recent_historical_generation_mwh=3),
        ],
        ignore_index=True,
    )
    allocated, _ = allocate_generation(_generation(), fleet, fuel_compatibility={"coal": ["coal"]})
    assert set(allocated["allocation_rule"]) == {
        "recent_historical_generation:exact_fuel_technology"
    }
    fleet["recent_historical_generation_mwh"] = float("nan")
    allocated, _ = allocate_generation(_generation(), fleet, fuel_compatibility={"coal": ["coal"]})
    assert allocated["generation_mwh"].tolist() == [500.0, 500.0]


def test_technology_and_fuel_fallbacks_are_explicit() -> None:
    technology, diagnostics = allocate_generation(
        _generation(technology="chp"),
        _fleet(),
        fuel_compatibility={"coal": ["coal"]},
    )
    assert technology["synthetic_technology_assignment"].all()
    assert diagnostics.loc[0, "match_level"] == "technology_aggregate_within_fuel"
    fuel, diagnostics = allocate_generation(
        _generation(fuel="gas", technology="ccgt"),
        _fleet(),
        fuel_compatibility={"gas": ["gas"]},
    )
    assert fuel["synthetic_fuel_assignment"].all()
    assert diagnostics.loc[0, "match_level"] == "same_province_synthetic_technology"


def test_missing_province_category_fails_instead_of_dropping_generation() -> None:
    with pytest.raises(ValueError, match="No compatible thermal site"):
        allocate_generation(
            _generation(province="missing"),
            _fleet(),
            fuel_compatibility={"coal": ["coal"]},
        )


def _ef_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "year": 2021,
                "fuel_type_clean": "coal",
                "technology": "steam",
                "pollutant": pollutant,
                "ef_kg_per_mwh": value,
                "valid_generation_mwh": 100.0,
                "plant_count": 2,
                "start_date": "2021-01-01",
                "end_date": "2021-12-01",
            }
            for pollutant, value in [("nox", 0.5), ("sox", 0.2)]
        ]
    )


def test_ef_exact_emissions_and_omitted_pollutants(tmp_path: Path) -> None:
    path = tmp_path / "ef.csv"
    _ef_rows().to_csv(path, index=False)
    ef = prepare_ef_table(path, year=2021)
    allocations, _ = allocate_generation(
        _generation(), _fleet(), fuel_compatibility={"coal": ["coal"]}
    )
    emissions, diagnostics = construct_emissions(
        allocations, ef, ef_source_path=path, ef_year=2021
    )
    assert emissions.loc[0, "nox_kg"] == 500.0
    assert emissions.loc[0, "sox_kg"] == 200.0
    assert emissions.loc[0, "pm25_kg"] == 0.0
    assert "omitted" in emissions.loc[0, "pm25_treatment"]
    assert not diagnostics["ef_fallback"].any()


def test_ef_fallback_is_generation_weighted_and_missing_fails(tmp_path: Path) -> None:
    path = tmp_path / "ef.csv"
    rows = pd.concat(
        [
            _ef_rows(),
            _ef_rows().assign(
                technology="other", ef_kg_per_mwh=[1.5, 1.2], valid_generation_mwh=300.0
            ),
        ],
        ignore_index=True,
    )
    rows.to_csv(path, index=False)
    ef = prepare_ef_table(path, year=2021)
    allocations, _ = allocate_generation(
        _generation(technology="unknown"),
        _fleet(technology="unknown"),
        fuel_compatibility={"coal": ["coal"]},
    )
    emissions, diagnostics = construct_emissions(
        allocations, ef, ef_source_path=path, ef_year=2021
    )
    assert emissions.loc[0, "nox_ef_kg_per_mwh"] == pytest.approx(1.25)
    assert diagnostics["ef_fallback"].all()
    with pytest.raises(ValueError, match="No defensible"):
        construct_emissions(
            allocations.assign(fuel="unknown", requested_fuel="unknown"),
            ef,
            ef_source_path=path,
            ef_year=2021,
        )


def test_stack_imputation_uses_unit_then_all_thermal(tmp_path: Path) -> None:
    stack_path = tmp_path / "stack.csv"
    pd.DataFrame(
        [
            {
                "subsidiary_company": "Company",
                "plant_name": "Plant 1",
                "reporting_unit_id": "u1",
                "stack_height_m": 100.0,
                "stack_diameter_m": 5.0,
                "exit_temp_c": 100.0,
                "flue_gas_velocity_m_s": 20.0,
                "match_status": "matched",
            }
        ]
    ).to_csv(stack_path, index=False)
    fleet = pd.concat([_fleet(), _fleet(unit_id="u2", plant_id="p2", plant_name="Other")])
    resolved, diagnostics = impute_stack_parameters(fleet, stack_path)
    assert resolved.set_index("unit_id").loc["u1", "stack_temperature_k"] == pytest.approx(373.15)
    assert (
        diagnostics.set_index("unit_id").loc["u1", "stack_height_m_provenance"] == "unit_observed"
    )
    assert (
        diagnostics.set_index("unit_id").loc["u2", "stack_height_m_provenance"]
        == "fuel_technology_median"
    )


def test_existing_health_adapter_uses_target_population_and_observed_mortality(
    tmp_path: Path,
) -> None:
    population_path = tmp_path / "population.csv"
    mortality_path = tmp_path / "mortality.csv"
    crf_path = tmp_path / "crf.csv"
    pd.DataFrame(
        [
            {
                "district_code": 11,
                "district_name": "A",
                "geography_level": "province",
                "year": 2030,
                "sex_code": 0,
                "sex": "all",
                "age_band": "30-34",
                "population_projected": 1000,
                "unit": "people",
            }
        ]
    ).to_csv(population_path, index=False)
    pd.DataFrame(
        [
            {
                "district_code": 0,
                "district_name": "national",
                "geography_level": "national",
                "year": 2024,
                "sex_code": 0,
                "sex": "all",
                "age_band": "30-34",
                "deaths": 10,
                "mortality_rate_per_100k": 1000.0,
            }
        ]
    ).to_csv(mortality_path, index=False)
    pd.DataFrame(
        [
            {
                "crf_id": "test",
                "label": "test",
                "beta_per_ugm3": 0.01,
                "beta_ci_low_per_ugm3": 0.005,
                "beta_ci_high_per_ugm3": 0.02,
                "valid_age_min": 30,
                "lowest_measured_ugm3": 10.0,
                "counterfactual_ugm3": 10.0,
            }
        ]
    ).to_csv(crf_path, index=False)
    health_inputs, crf = build_national_health_inputs(
        population_path=population_path,
        mortality_path=mortality_path,
        target_year=2030,
        mortality_year=2024,
        age_min=30,
        reference_scenario="historical",
        policy_scenario="future",
        reference_incremental_pm25=2.0,
        policy_incremental_pm25=1.0,
        crf_parameters_path=crf_path,
        crf_id="test",
    )
    result = calculate_avoided_deaths(
        health_inputs,
        crf,
        reference_scenario="historical",
        policy_scenario="future",
        mortality_year=2024,
    )
    assert result.loc[0, "avoided_deaths"] > 0
    assert result.loc[0, "comparison_type"] == "historical_to_scenario"


def test_health_config_requires_background_and_explicit_analytical_flag() -> None:
    config = {
        "inputs": {"all_cause_file": Path("mortality.csv")},
        "health": {
            "crf_ids": ["peng_krewski_2009_all_cause"],
            "mortality_inputs": {"all_cause": "all_cause_file"},
            "concentration_column": "population_weighted_pm25_ugm3",
            "concentration_mode": "background_plus_inmap_contribution",
            "background_pm25_ugm3": None,
            "exposure_scope": "source_contribution",
            "analytical_use_permitted": False,
        },
    }
    with pytest.raises(ValueError, match="background_pm25_ugm3 is required"):
        _validate_health_config(config)
    config["health"]["background_pm25_ugm3"] = 8.0
    config["health"]["analytical_use_permitted"] = "false"
    with pytest.raises(ValueError, match="must be true or false"):
        _validate_health_config(config)


def test_audit_report_tolerates_legacy_installation_manifest(tmp_path: Path) -> None:
    installation_dir = tmp_path / "inmap"
    installation_dir.mkdir()
    (installation_dir / "installation_manifest.json").write_text(
        json.dumps({"source_release": "legacy"}),
        encoding="utf-8",
    )
    selection = {
        "comparison_type": "historical_to_scenario",
        "reference_scenario": "observed",
        "historical_year": 2021,
        "policy_scenario": "macro",
        "target_year": 2030,
        "causal_policy_claim_permitted": False,
    }
    manifest = {
        "steps": {"audit": "complete"},
        "blockers": [],
        "resume_command": "make peng-mvp",
    }

    _write_report(tmp_path, selection, None, manifest)

    report = (tmp_path / "MVP_REPORT.md").read_text(encoding="utf-8")
    assert "Requested release: `legacy`" in report
    assert "Requested version and source commit: `not recorded`" in report
