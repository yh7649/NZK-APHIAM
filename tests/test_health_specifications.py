from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.health.crf import DEFAULT_CRF_PARAMETERS_PATH
from nzk_aphiam.mvp.peng_replication.health_adapter import (
    RECOMMENDED_CRF_IDS,
    evaluate_national_health_specifications,
)

AGE_BANDS = (
    "20-24",
    "25-29",
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
    pd.DataFrame(
        [
            {
                "year": 2030,
                "geography_level": "province",
                "sex_code": 0,
                "age_band": age_band,
                "population_projected": 10_000 + index * 100,
            }
            for index, age_band in enumerate(AGE_BANDS)
        ]
    ).to_csv(path, index=False)


def _write_mortality(path: Path, endpoint: str) -> None:
    pd.DataFrame(
        [
            {
                "year": 2024,
                "geography_level": "national",
                "sex_code": 0,
                "age_band": age_band,
                "mortality_rate_per_100k": 100 + index * 25,
                "mortality_endpoint": endpoint,
            }
            for index, age_band in enumerate(AGE_BANDS)
        ]
    ).to_csv(path, index=False)


def _exposures() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": "reference",
                "year": 2021,
                "population_weighted_pm25_ugm3": 20.0,
            },
            {
                "scenario": "policy",
                "year": 2030,
                "population_weighted_pm25_ugm3": 15.0,
            },
        ]
    )


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    population_path = tmp_path / "population.csv"
    all_cause_path = tmp_path / "all_cause.csv"
    non_accidental_path = tmp_path / "non_accidental.csv"
    ncd_lri_path = tmp_path / "ncd_lri.csv"
    _write_population(population_path)
    _write_mortality(all_cause_path, "all_cause")
    _write_mortality(non_accidental_path, "non_accidental")
    _write_mortality(ncd_lri_path, "ncd_lri")
    return population_path, all_cause_path, non_accidental_path, ncd_lri_path


def test_recommended_suite_runs_every_specification_from_inmap_exposure(
    tmp_path: Path,
) -> None:
    population_path, all_cause_path, non_accidental_path, ncd_lri_path = _paths(tmp_path)
    suite = evaluate_national_health_specifications(
        scenario_exposures=_exposures(),
        population_path=population_path,
        mortality_paths={
            "all_cause": all_cause_path,
            "non_accidental": non_accidental_path,
            "ncd_lri": ncd_lri_path,
        },
        target_year=2030,
        mortality_year=2024,
        reference_scenario="reference",
        policy_scenario="policy",
        crf_parameters_path=DEFAULT_CRF_PARAMETERS_PATH,
        exposure_scope="all_source_total_ambient_pm25",
        analytical_use_permitted=True,
    )

    assert suite.status.set_index("crf_id")["status"].to_dict() == {
        crf_id: "complete" for crf_id in RECOMMENDED_CRF_IDS
    }
    assert set(suite.impacts["crf_id"]) == set(RECOMMENDED_CRF_IDS)
    assert len(suite.impacts) == len(RECOMMENDED_CRF_IDS)
    assert (suite.impacts["avoided_deaths"] > 0).all()
    assert (suite.impacts["avoided_deaths_ci_low"] <= suite.impacts["avoided_deaths"]).all()
    assert (suite.impacts["avoided_deaths"] <= suite.impacts["avoided_deaths_ci_high"]).all()
    assert len(suite.scenario_totals) == 2 * len(RECOMMENDED_CRF_IDS)
    assert suite.impacts["analytical_use_permitted"].all()
    assert suite.status["analytical_use_permitted"].all()

    inputs = suite.model_inputs
    kim_ages = inputs.loc[inputs["crf_id"].eq("kim_2020_korea_all_cause"), "age_band"].unique()
    lim_ages = inputs.loc[
        inputs["crf_id"].eq("lim_2020_korea_elderly_all_cause"), "age_band"
    ].unique()
    gemm_ages = inputs.loc[
        inputs["crf_id"].eq("gemm_2018_ncd_lri_with_china"), "age_band"
    ].unique()
    assert "20-24" in kim_ages
    assert set(lim_ages) == {"65-69", "70-74", "75-79", "80+"}
    assert "20-24" not in gemm_ages
    assert "25-29" in gemm_ages


def test_missing_non_accidental_mortality_blocks_only_endpoint_specific_specs(
    tmp_path: Path,
) -> None:
    population_path, all_cause_path, _, _ = _paths(tmp_path)
    suite = evaluate_national_health_specifications(
        scenario_exposures=_exposures(),
        population_path=population_path,
        mortality_paths={
            "all_cause": all_cause_path,
            "non_accidental": None,
            "ncd_lri": None,
        },
        target_year=2030,
        mortality_year=2024,
        reference_scenario="reference",
        policy_scenario="policy",
        crf_parameters_path=DEFAULT_CRF_PARAMETERS_PATH,
    )

    statuses = suite.status.set_index("crf_id")["status"]
    assert statuses.eq("complete").sum() == 4
    assert statuses.eq("blocked_missing_endpoint_mortality").sum() == 2
    assert set(suite.impacts["mortality_endpoint"]) == {"all_cause"}


def test_mortality_endpoint_mismatch_is_rejected(tmp_path: Path) -> None:
    population_path, all_cause_path, _, _ = _paths(tmp_path)
    suite = evaluate_national_health_specifications(
        scenario_exposures=_exposures(),
        population_path=population_path,
        mortality_paths={
            "all_cause": all_cause_path,
            "non_accidental": all_cause_path,
        },
        target_year=2030,
        mortality_year=2024,
        reference_scenario="reference",
        policy_scenario="policy",
        crf_parameters_path=DEFAULT_CRF_PARAMETERS_PATH,
        crf_ids=["byun_2024_korea_non_accidental"],
    )
    assert suite.impacts.empty
    assert suite.status.loc[0, "status"] == "blocked_invalid_mortality_input"
    assert "no mortality_endpoint='non_accidental'" in suite.status.loc[0, "reason"]


def test_background_is_added_only_in_background_plus_contribution_mode(
    tmp_path: Path,
) -> None:
    population_path, all_cause_path, _, _ = _paths(tmp_path)
    common = {
        "scenario_exposures": _exposures(),
        "population_path": population_path,
        "mortality_paths": {"all_cause": all_cause_path},
        "target_year": 2030,
        "mortality_year": 2024,
        "reference_scenario": "reference",
        "policy_scenario": "policy",
        "crf_parameters_path": DEFAULT_CRF_PARAMETERS_PATH,
        "crf_ids": ["peng_krewski_2009_all_cause"],
    }
    direct = evaluate_national_health_specifications(
        **common,
        concentration_mode="direct_scenario_concentration",
    )
    with_background = evaluate_national_health_specifications(
        **common,
        concentration_mode="background_plus_inmap_contribution",
        background_pm25_ugm3={"reference": 3.0, "policy": 2.0},
    )

    direct_pm = direct.model_inputs.groupby("scenario")["pm25_ugm3"].first().to_dict()
    background_pm = with_background.model_inputs.groupby("scenario")["pm25_ugm3"].first().to_dict()
    assert direct_pm == {"policy": 15.0, "reference": 20.0}
    assert background_pm == {"policy": 17.0, "reference": 23.0}


def test_background_mode_requires_background_input(tmp_path: Path) -> None:
    population_path, all_cause_path, _, _ = _paths(tmp_path)
    with pytest.raises(ValueError, match="background_pm25_ugm3 is required"):
        evaluate_national_health_specifications(
            scenario_exposures=_exposures(),
            population_path=population_path,
            mortality_paths={"all_cause": all_cause_path},
            target_year=2030,
            mortality_year=2024,
            reference_scenario="reference",
            policy_scenario="policy",
            crf_parameters_path=DEFAULT_CRF_PARAMETERS_PATH,
            crf_ids=["peng_krewski_2009_all_cause"],
            concentration_mode="background_plus_inmap_contribution",
        )
