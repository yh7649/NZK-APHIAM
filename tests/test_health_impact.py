from __future__ import annotations

import logging
import math
from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.health import impact
from nzk_aphiam.health.crf import LogLinearCRF

CRF = LogLinearCRF(
    crf_id="test_crf",
    label="test",
    beta=0.01,
    ci_low=0.005,
    ci_high=0.02,
    valid_age_min=30,
    counterfactual_ugm3=10.0,
    lowest_measured_ugm3=10.0,
)


def _row(
    district_code: str = "D1",
    year: int = 2020,
    scenario: str = "baseline",
    age_band: str = "30-59",
    pm25_ugm3: float = 25.0,
    baseline_mortality_rate_per_person: float = 0.005,
    population: float = 100_000.0,
) -> dict[str, object]:
    return {
        "district_code": district_code,
        "year": year,
        "scenario": scenario,
        "age_band": age_band,
        "pm25_ugm3": pm25_ugm3,
        "baseline_mortality_rate_per_person": baseline_mortality_rate_per_person,
        "population": population,
    }


def test_compute_attributable_deaths_matches_manual_calculation() -> None:
    df = pd.DataFrame(
        [
            _row(district_code="D1", pm25_ugm3=25.0),
            _row(district_code="D2", pm25_ugm3=30.0),
        ]
    )
    totals = impact.compute_attributable_deaths(df, CRF)
    assert len(totals) == 1

    af_d1 = 1 - math.exp(-0.01 * (25.0 - 10.0))
    af_d2 = 1 - math.exp(-0.01 * (30.0 - 10.0))
    expected = af_d1 * 0.005 * 100_000.0 + af_d2 * 0.005 * 100_000.0
    assert totals.loc[0, "attributable_deaths"] == pytest.approx(expected)


def test_attributable_deaths_ci_bounds_bracket_central_estimate() -> None:
    df = pd.DataFrame([_row()])
    totals = impact.compute_attributable_deaths(df, CRF)
    row = totals.iloc[0]
    assert row["attributable_deaths_ci_low"] < row["attributable_deaths"]
    assert row["attributable_deaths"] < row["attributable_deaths_ci_high"]


def test_monotonicity_higher_delta_pm_gives_more_attributable_deaths() -> None:
    low_pm = pd.DataFrame([_row(scenario="low", pm25_ugm3=20.0)])
    high_pm = pd.DataFrame([_row(scenario="high", pm25_ugm3=40.0)])
    low_total = impact.compute_attributable_deaths(low_pm, CRF)["attributable_deaths"].iloc[0]
    high_total = impact.compute_attributable_deaths(high_pm, CRF)["attributable_deaths"].iloc[0]
    assert high_total > low_total


def test_zero_delta_marginal_for_identical_scenarios() -> None:
    df = pd.DataFrame(
        [
            _row(scenario="scenario_a", pm25_ugm3=28.0),
            _row(scenario="scenario_b", pm25_ugm3=28.0),
        ]
    )
    marginal = impact.compute_marginal_attributable_deaths(df, CRF, "scenario_a", "scenario_b")
    assert marginal.loc[0, "marginal_attributable_deaths"] == pytest.approx(0.0, abs=1e-9)
    assert marginal.loc[0, "marginal_attributable_deaths_ci_low"] == pytest.approx(0.0, abs=1e-9)
    assert marginal.loc[0, "marginal_attributable_deaths_ci_high"] == pytest.approx(0.0, abs=1e-9)


def test_marginal_deaths_is_not_af_of_concentration_difference() -> None:
    """Non-linearity guard: differencing totals != applying AF to a concentration delta."""
    df = pd.DataFrame(
        [
            _row(scenario="scenario_a", pm25_ugm3=12.0),
            _row(scenario="scenario_b", pm25_ugm3=30.0),
        ]
    )
    marginal = impact.compute_marginal_attributable_deaths(df, CRF, "scenario_a", "scenario_b")
    correct_marginal = marginal.loc[0, "marginal_attributable_deaths"]

    naive_delta_pm = 30.0 - 12.0
    naive_af = 1 - math.exp(-CRF.beta * naive_delta_pm)
    naive_shortcut = naive_af * 0.005 * 100_000.0

    assert correct_marginal != pytest.approx(naive_shortcut)


def test_rejects_per_100000_mortality_rate() -> None:
    df = pd.DataFrame([_row(baseline_mortality_rate_per_person=500.0)])
    with pytest.raises(ValueError, match="100,000"):
        impact.compute_attributable_deaths(df, CRF)


def test_rejects_age_band_below_valid_age_min() -> None:
    df = pd.DataFrame([_row(age_band="25-29")])
    with pytest.raises(ValueError, match="age_band"):
        impact.compute_attributable_deaths(df, CRF)


def test_rejects_negative_pm25() -> None:
    df = pd.DataFrame([_row(pm25_ugm3=-1.0)])
    with pytest.raises(ValueError, match="pm25_ugm3"):
        impact.compute_attributable_deaths(df, CRF)


def test_rejects_negative_population() -> None:
    df = pd.DataFrame([_row(population=-10.0)])
    with pytest.raises(ValueError):
        impact.compute_attributable_deaths(df, CRF)


def test_rejects_missing_required_column() -> None:
    df = pd.DataFrame([_row()]).drop(columns=["population"])
    with pytest.raises(ValueError, match="missing required columns"):
        impact.compute_attributable_deaths(df, CRF)


def test_truncation_below_counterfactual_is_zeroed_and_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    df = pd.DataFrame([_row(district_code="D_low", pm25_ugm3=5.0)])
    with caplog.at_level(logging.WARNING, logger="nzk_aphiam.health.impact"):
        totals = impact.compute_attributable_deaths(df, CRF)
    assert totals.loc[0, "attributable_deaths"] == pytest.approx(0.0)
    assert any("D_low" in message for message in caplog.messages)
    assert any("counterfactual" in message for message in caplog.messages)


def test_marginal_raises_for_unknown_scenario_label() -> None:
    df = pd.DataFrame([_row(scenario="scenario_a")])
    with pytest.raises(ValueError):
        impact.compute_marginal_attributable_deaths(df, CRF, "scenario_a", "missing_scenario")


def test_cli_writes_totals_csv(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    crf_path = tmp_path / "crf_parameters.csv"
    pd.DataFrame(
        [
            {
                "crf_id": "synthetic_crf",
                "label": "synthetic",
                "beta_per_ugm3": 0.01,
                "beta_ci_low_per_ugm3": 0.005,
                "beta_ci_high_per_ugm3": 0.02,
                "valid_age_min": 30,
                "lowest_measured_ugm3": 10.0,
                "counterfactual_ugm3": 10.0,
            }
        ]
    ).to_csv(crf_path, index=False)
    pd.DataFrame([_row()]).to_csv(input_path, index=False)

    impact.main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--crf-id",
            "synthetic_crf",
            "--crf-parameters",
            str(crf_path),
        ]
    )

    result = pd.read_csv(output_path)
    assert "attributable_deaths" in result.columns
    assert len(result) == 1
