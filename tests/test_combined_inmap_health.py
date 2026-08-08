from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from nzk_aphiam.health.combined_inmap import (
    PRIMARY_CRF_ID,
    evaluate_all_scenario_mortality,
    population_source_years,
    select_balanced_partial_exposures,
    write_health_outputs,
)
from nzk_aphiam.health.crf import (
    DEFAULT_CRF_PARAMETERS_PATH,
    DEFAULT_GEMM_PARAMETERS_PATH,
)

AGE_BANDS = (
    "30-34",
    "35-39",
    "40-44",
    "45-49",
    "50-54",
    "55-59",
    "60-64",
    "65-69",
    "70-74",
    "75-79",
    "80+",
)


def _write_population(path: Path) -> None:
    rows = []
    for year in (2030, 2042):
        for index, age_band in enumerate(AGE_BANDS):
            rows.append(
                {
                    "year": year,
                    "geography_level": "province",
                    "sex_code": 0,
                    "age_band": age_band,
                    "population_projected": 100_000 - index * 1_000,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_mortality(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "year": 2024,
                "geography_level": "national",
                "sex_code": 0,
                "age_band": age_band,
                "mortality_rate_per_100k": 100 + index * 50,
            }
            for index, age_band in enumerate(AGE_BANDS)
        ]
    ).to_csv(path, index=False)


def _exposures() -> pd.DataFrame:
    rows = []
    concentrations = {"no_nzk": 20.0, "nzk_low": 15.0, "nzk_high": 10.0}
    for year in (2030, 2050):
        for scenario, concentration in concentrations.items():
            rows.append(
                {
                    "scenario": scenario,
                    "year": year,
                    "population_weighted_pm25_ugm3": concentration,
                }
            )
    return pd.DataFrame(rows)


def _config(tmp_path: Path) -> dict:
    population = tmp_path / "population.csv"
    mortality = tmp_path / "mortality.csv"
    _write_population(population)
    _write_mortality(mortality)
    return {
        "inputs": {
            "population_projection": population,
            "age_mortality_all_cause": mortality,
            "crf_parameters": DEFAULT_CRF_PARAMETERS_PATH,
            "gemm_parameters": DEFAULT_GEMM_PARAMETERS_PATH,
        },
        "health": {
            "mortality_inputs": {"all_cause": "age_mortality_all_cause"},
            "mortality_year": 2024,
            "crf_ids": [PRIMARY_CRF_ID],
        },
    }


def test_population_year_uses_latest_prior_projection(tmp_path: Path) -> None:
    config = _config(tmp_path)
    selected = population_source_years(
        config["inputs"]["population_projection"],
        [2030, 2050],
    )
    assert selected == {2030: 2030, 2050: 2042}


def test_partial_exposures_keep_shared_reference_policy_years() -> None:
    exposures = pd.DataFrame(
        {
            "scenario": ["no_nzk", "no_nzk", "nzk_low", "nzk_high"],
            "year": [2025, 2030, 2025, 2030],
            "population_weighted_pm25_ugm3": [0.5, 0.5, 0.4, 0.3],
        }
    )
    selected = select_balanced_partial_exposures(
        exposures,
        policy_scenarios=["nzk_low"],
    )
    assert selected[["scenario", "year"]].to_records(index=False).tolist() == [
        ("no_nzk", 2025),
        ("nzk_low", 2025),
    ]


def test_all_scenario_mortality_and_outputs_are_labeled_diagnostic(
    tmp_path: Path,
) -> None:
    run_manifest = {
        "solver_mode": "fixed_iterations_poc",
        "num_iterations": 200,
    }
    suite = evaluate_all_scenario_mortality(
        _exposures(),
        _config(tmp_path),
        run_manifest,
    )
    assert len(suite.scenario_totals) == 6
    assert len(suite.impacts) == 4
    assert set(
        suite.scenario_totals.loc[suite.scenario_totals["year"].eq(2050), "population_year"]
    ) == {2042}
    assert (suite.impacts["avoided_deaths"] > 0).all()
    assert not suite.scenario_totals["analytical_use_permitted"].any()

    output_dir = tmp_path / "health"
    manifest_path = write_health_outputs(
        _exposures(),
        suite,
        run_manifest,
        output_dir,
    )
    manifest = json.loads(manifest_path.read_text())
    assert not manifest["analytical_use_permitted"]
    assert manifest["primary_scenario_rows"] == 6
    assert (output_dir / "diagnostic_nonconverged_scenario_mortality_primary.csv").is_file()


def test_all_scenario_mortality_accepts_a_named_reference_scenario(
    tmp_path: Path,
) -> None:
    names = {
        "no_nzk": "nzk_nonpower_no_nzk_power",
        "nzk_low": "nzk_nonpower_low_nzk_power",
        "nzk_high": "nzk_nonpower_high_nzk_power",
    }
    exposures = _exposures()
    exposures["scenario"] = exposures["scenario"].replace(names)
    reference = names["no_nzk"]
    run_manifest = {
        "solver_mode": "fixed_iterations_poc",
        "num_iterations": 50,
        "emissions_scope": "thermal_power_only",
    }

    suite = evaluate_all_scenario_mortality(
        exposures,
        _config(tmp_path),
        run_manifest,
        reference_scenario=reference,
    )

    assert set(suite.impacts["reference_scenario"]) == {reference}
    assert set(suite.impacts["policy_scenario"]) == {
        names["nzk_low"],
        names["nzk_high"],
    }
    assert set(suite.scenario_totals["exposure_scope"]) == {
        "incremental_korean_thermal_power_source_contribution_screening_not_total_ambient"
    }
    manifest_path = write_health_outputs(
        exposures,
        suite,
        run_manifest,
        tmp_path / "health",
        reference_scenario=reference,
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["reference_scenario"] == reference
