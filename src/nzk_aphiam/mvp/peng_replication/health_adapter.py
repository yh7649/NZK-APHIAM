"""Adapter from real national InMAP exposure to the existing health model."""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from nzk_aphiam.health.crf import load_crf
from nzk_aphiam.health.impact import compute_marginal_attributable_deaths


def _age_lower(value: object) -> int:
    match = re.match(r"(\d+)", str(value))
    if not match:
        raise ValueError(f"Cannot parse KOSIS age band {value!r}.")
    return int(match.group(1))


def build_national_health_inputs(
    *,
    population_path: Path,
    mortality_path: Path,
    target_year: int,
    mortality_year: int,
    age_min: int,
    reference_scenario: str,
    policy_scenario: str,
    reference_incremental_pm25: float,
    policy_incremental_pm25: float,
    crf_parameters_path: Path,
    crf_id: str,
) -> tuple[pd.DataFrame, object]:
    """Construct the existing tidy health schema using documented KOSIS inputs."""
    crf = load_crf(crf_id, crf_parameters_path)
    if crf.valid_age_min != age_min:
        raise ValueError(
            f"Configured age_min={age_min} does not match CRF valid_age_min={crf.valid_age_min}."
        )
    population = pd.read_csv(population_path)
    population = population.loc[
        population["year"].eq(target_year)
        & population["geography_level"].eq("province")
        & population["sex_code"].eq(0)
    ].copy()
    population = population.loc[population["age_band"].map(_age_lower) >= age_min]
    population = population.groupby("age_band", as_index=False)["population_projected"].sum()
    mortality = pd.read_csv(mortality_path)
    mortality = mortality.loc[
        mortality["year"].eq(mortality_year)
        & mortality["geography_level"].eq("national")
        & mortality["sex_code"].eq(0)
    ].copy()
    mortality = mortality.loc[mortality["age_band"].map(_age_lower) >= age_min]
    mortality = mortality[["age_band", "mortality_rate_per_100k"]]
    denominators = population.merge(mortality, on="age_band", how="inner", validate="one_to_one")
    if denominators.empty or len(denominators) != len(population):
        raise ValueError("Projected population and observed mortality age bands do not align.")
    denominators["baseline_mortality_rate_per_person"] = (
        denominators["mortality_rate_per_100k"] / 100_000.0
    )
    denominators = denominators.rename(columns={"population_projected": "population"})
    rows: list[pd.DataFrame] = []
    for scenario, increment in [
        (reference_scenario, reference_incremental_pm25),
        (policy_scenario, policy_incremental_pm25),
    ]:
        frame = denominators.copy()
        frame["district_code"] = "KOR"
        frame["year"] = target_year
        frame["scenario"] = scenario
        frame["pm25_ugm3"] = crf.counterfactual_ugm3 + increment
        rows.append(frame)
    columns = [
        "district_code",
        "year",
        "scenario",
        "age_band",
        "pm25_ugm3",
        "baseline_mortality_rate_per_person",
        "population",
    ]
    return pd.concat(rows, ignore_index=True)[columns], crf


def calculate_avoided_deaths(
    health_inputs: pd.DataFrame,
    crf: object,
    *,
    reference_scenario: str,
    policy_scenario: str,
    mortality_year: int,
    comparison_type: str = "historical_to_scenario",
) -> pd.DataFrame:
    """Reuse the verified marginal API and orient it as reference minus policy."""
    avoided = compute_marginal_attributable_deaths(
        health_inputs,
        crf,
        baseline_scenario=policy_scenario,
        comparison_scenario=reference_scenario,
    ).rename(
        columns={
            "marginal_attributable_deaths": "avoided_deaths",
            "marginal_attributable_deaths_ci_low": "avoided_deaths_ci_low",
            "marginal_attributable_deaths_ci_high": "avoided_deaths_ci_high",
        }
    )
    avoided["comparison_type"] = comparison_type
    avoided["sign_convention"] = "reference_or_historical_minus_policy_or_scenario"
    avoided["exposure_scope"] = "incremental_korean_thermal_power_pm25_not_total_ambient"
    avoided["population_year"] = avoided["year"]
    avoided["mortality_year"] = mortality_year
    avoided["mortality_assumption"] = "latest_observed_rates_held_constant"
    return avoided
