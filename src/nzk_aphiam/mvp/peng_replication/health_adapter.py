"""Endpoint-safe adapter from national InMAP exposure to the health CRF suite."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from nzk_aphiam.health.crf import (
    DEFAULT_GEMM_PARAMETERS_PATH,
    ConcentrationResponseFunction,
    load_crf,
)
from nzk_aphiam.health.impact import (
    compute_attributable_deaths,
    compute_marginal_attributable_deaths,
)

RECOMMENDED_CRF_IDS = (
    "peng_krewski_2009_all_cause",
    "gemm_2018_ncd_lri_with_china",
    "byun_2024_korea_non_accidental",
    "kim_2020_korea_all_cause",
    "korea_guide_hoek_2013_policy",
    "lim_2020_korea_elderly_all_cause",
)
CONCENTRATION_MODES = (
    "direct_scenario_concentration",
    "background_plus_inmap_contribution",
)


@dataclass(frozen=True)
class HealthSuiteResults:
    """Combined outputs and audit status for a multi-CRF health run."""

    model_inputs: pd.DataFrame
    scenario_totals: pd.DataFrame
    impacts: pd.DataFrame
    status: pd.DataFrame


def _age_lower(value: object) -> int:
    match = re.match(r"(\d+)", str(value))
    if not match:
        raise ValueError(f"Cannot parse KOSIS age band {value!r}.")
    return int(match.group(1))


def _load_population(population_path: Path, target_year: int) -> pd.DataFrame:
    population = pd.read_csv(population_path)
    required = {
        "year",
        "geography_level",
        "sex_code",
        "age_band",
        "population_projected",
    }
    missing = sorted(required - set(population.columns))
    if missing:
        raise ValueError(f"{population_path} is missing population columns: {missing}")
    population = population.loc[
        population["year"].eq(target_year)
        & population["geography_level"].eq("province")
        & population["sex_code"].eq(0)
    ].copy()
    population["population_projected"] = pd.to_numeric(
        population["population_projected"],
        errors="coerce",
    )
    invalid_population = ~np.isfinite(population["population_projected"]) | population[
        "population_projected"
    ].lt(0)
    if invalid_population.any():
        raise ValueError(
            f"{population_path} contains missing, non-finite, or negative target-year "
            "population values."
        )
    population = population.groupby("age_band", as_index=False)["population_projected"].sum()
    if population.empty:
        raise ValueError(f"No province-level all-sex population rows for year {target_year}.")
    return population


def _load_mortality(
    mortality_path: Path,
    *,
    mortality_year: int,
    endpoint: str,
) -> pd.DataFrame:
    mortality = pd.read_csv(mortality_path)
    required = {
        "year",
        "geography_level",
        "sex_code",
        "age_band",
        "mortality_rate_per_100k",
    }
    missing = sorted(required - set(mortality.columns))
    if missing:
        raise ValueError(f"{mortality_path} is missing mortality columns: {missing}")
    if "mortality_endpoint" in mortality.columns:
        available = sorted(mortality["mortality_endpoint"].dropna().unique())
        mortality = mortality.loc[mortality["mortality_endpoint"].eq(endpoint)].copy()
        if mortality.empty:
            raise ValueError(
                f"{mortality_path} has no mortality_endpoint={endpoint!r}; available={available}."
            )
    elif endpoint != "all_cause":
        raise ValueError(
            f"{mortality_path} must contain mortality_endpoint={endpoint!r}. "
            "Only the canonical KOSIS all-cause table may omit mortality_endpoint."
        )
    mortality = mortality.loc[
        mortality["year"].eq(mortality_year)
        & mortality["geography_level"].eq("national")
        & mortality["sex_code"].eq(0)
    ].copy()
    mortality = mortality[["age_band", "mortality_rate_per_100k"]]
    if mortality.empty:
        raise ValueError(
            f"No national all-sex mortality rows for endpoint={endpoint!r}, year={mortality_year}."
        )
    if mortality["age_band"].duplicated().any():
        duplicates = sorted(mortality.loc[mortality["age_band"].duplicated(), "age_band"])
        raise ValueError(f"Duplicate mortality age bands in {mortality_path}: {duplicates}")
    mortality["mortality_rate_per_100k"] = pd.to_numeric(
        mortality["mortality_rate_per_100k"],
        errors="coerce",
    )
    invalid_mortality = (
        ~np.isfinite(mortality["mortality_rate_per_100k"])
        | mortality["mortality_rate_per_100k"].lt(0)
        | mortality["mortality_rate_per_100k"].gt(100_000)
    )
    if invalid_mortality.any():
        raise ValueError(
            f"{mortality_path} contains missing, non-finite, negative, or "
            "greater-than-100,000 mortality rates per 100,000."
        )
    return mortality


def _build_inputs_from_concentrations(
    *,
    population: pd.DataFrame,
    mortality: pd.DataFrame,
    concentrations: Mapping[str, float],
    inmap_years: Mapping[str, int],
    target_year: int,
    population_year: int | None,
    crf: ConcentrationResponseFunction,
    exposure_mode: str,
    exposure_scope: str,
    analytical_use_permitted: bool,
) -> pd.DataFrame:
    population = population.loc[population["age_band"].map(_age_lower) >= crf.valid_age_min].copy()
    mortality = mortality.loc[mortality["age_band"].map(_age_lower) >= crf.valid_age_min].copy()
    if crf.valid_age_max is not None:
        population = population.loc[population["age_band"].map(_age_lower) <= crf.valid_age_max]
        mortality = mortality.loc[mortality["age_band"].map(_age_lower) <= crf.valid_age_max]

    denominators = population.merge(mortality, on="age_band", how="inner", validate="one_to_one")
    if denominators.empty or len(denominators) != len(population):
        missing_bands = sorted(set(population["age_band"]) - set(denominators["age_band"]))
        raise ValueError(
            f"Projected population and {crf.endpoint} mortality age bands do not align; "
            f"missing mortality bands={missing_bands}."
        )
    denominators["baseline_mortality_rate_per_person"] = (
        denominators["mortality_rate_per_100k"] / 100_000.0
    )
    denominators = denominators.rename(columns={"population_projected": "population"})

    rows: list[pd.DataFrame] = []
    for scenario, concentration in concentrations.items():
        frame = denominators.copy()
        frame["district_code"] = "KOR"
        frame["year"] = target_year
        frame["population_year"] = target_year if population_year is None else population_year
        frame["scenario"] = scenario
        frame["pm25_ugm3"] = concentration
        frame["inmap_exposure_year"] = inmap_years[scenario]
        frame["mortality_endpoint"] = crf.endpoint
        frame["crf_id"] = crf.crf_id
        frame["exposure_mode"] = exposure_mode
        frame["exposure_scope"] = exposure_scope
        frame["analytical_use_permitted"] = analytical_use_permitted
        rows.append(frame)
    columns = [
        "district_code",
        "year",
        "scenario",
        "age_band",
        "population_year",
        "pm25_ugm3",
        "baseline_mortality_rate_per_person",
        "population",
        "inmap_exposure_year",
        "mortality_endpoint",
        "crf_id",
        "exposure_mode",
        "exposure_scope",
        "analytical_use_permitted",
    ]
    return pd.concat(rows, ignore_index=True)[columns]


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
    gemm_parameters_path: Path = DEFAULT_GEMM_PARAMETERS_PATH,
) -> tuple[pd.DataFrame, ConcentrationResponseFunction]:
    """Backward-compatible single-CRF adapter using the legacy explicit anchor.

    New pipeline code uses :func:`evaluate_national_health_specifications`,
    which never hides the concentration interpretation.
    """
    crf = load_crf(crf_id, crf_parameters_path, gemm_parameters_path)
    if crf.valid_age_min != age_min:
        raise ValueError(
            f"Configured age_min={age_min} does not match CRF valid_age_min={crf.valid_age_min}."
        )
    population = _load_population(population_path, target_year)
    mortality = _load_mortality(
        mortality_path,
        mortality_year=mortality_year,
        endpoint=crf.endpoint,
    )
    concentrations = {
        reference_scenario: crf.counterfactual_ugm3 + reference_incremental_pm25,
        policy_scenario: crf.counterfactual_ugm3 + policy_incremental_pm25,
    }
    inputs = _build_inputs_from_concentrations(
        population=population,
        mortality=mortality,
        concentrations=concentrations,
        inmap_years={reference_scenario: target_year, policy_scenario: target_year},
        target_year=target_year,
        population_year=target_year,
        crf=crf,
        exposure_mode="legacy_crf_counterfactual_plus_inmap_contribution",
        exposure_scope="incremental_korean_thermal_power_pm25_not_total_ambient",
        analytical_use_permitted=False,
    )
    return inputs, crf


def calculate_avoided_deaths(
    health_inputs: pd.DataFrame,
    crf: ConcentrationResponseFunction,
    *,
    reference_scenario: str,
    policy_scenario: str,
    mortality_year: int,
    population_year: int | None = None,
    comparison_type: str = "historical_to_scenario",
    exposure_scope: str | None = None,
) -> pd.DataFrame:
    """Difference scenario totals and orient the result as reference minus policy."""
    avoided = compute_marginal_attributable_deaths(
        health_inputs,
        crf,
        baseline_scenario=policy_scenario,
        comparison_scenario=reference_scenario,
    ).rename(
        columns={
            "marginal_attributable_deaths": "avoided_deaths",
            "marginal_attributable_deaths_ci_low": "_coefficient_low",
            "marginal_attributable_deaths_ci_high": "_coefficient_high",
        }
    )
    avoided["avoided_deaths_ci_low"] = avoided[["_coefficient_low", "_coefficient_high"]].min(
        axis=1
    )
    avoided["avoided_deaths_ci_high"] = avoided[["_coefficient_low", "_coefficient_high"]].max(
        axis=1
    )
    avoided = avoided.drop(columns=["_coefficient_low", "_coefficient_high"])
    avoided["crf_id"] = crf.crf_id
    avoided["crf_label"] = crf.label
    avoided["crf_model_type"] = crf.model_type
    avoided["mortality_endpoint"] = crf.endpoint
    avoided["specification_role"] = crf.specification_role
    avoided["comparison_type"] = comparison_type
    avoided["sign_convention"] = "reference_or_historical_minus_policy_or_scenario"
    if exposure_scope is None:
        exposure_scope = str(health_inputs["exposure_scope"].iloc[0])
    avoided["exposure_mode"] = str(health_inputs["exposure_mode"].iloc[0])
    avoided["exposure_scope"] = exposure_scope
    avoided["analytical_use_permitted"] = bool(
        health_inputs.get("analytical_use_permitted", pd.Series([False])).iloc[0]
    )
    avoided["population_year"] = avoided["year"] if population_year is None else population_year
    avoided["mortality_year"] = mortality_year
    avoided["mortality_assumption"] = "latest_observed_rates_held_constant"
    return avoided


def _scenario_concentrations(
    scenario_exposures: pd.DataFrame,
    *,
    scenarios: Sequence[str],
    concentration_column: str,
    concentration_mode: str,
    background_pm25_ugm3: float | Mapping[str, float] | None,
) -> tuple[dict[str, float], dict[str, int]]:
    if concentration_mode not in CONCENTRATION_MODES:
        raise ValueError(
            f"concentration_mode must be one of {CONCENTRATION_MODES}; got {concentration_mode!r}."
        )
    required = {"scenario", "year", concentration_column}
    missing = sorted(required - set(scenario_exposures.columns))
    if missing:
        raise ValueError(f"InMAP exposure table is missing columns: {missing}")

    concentrations: dict[str, float] = {}
    years: dict[str, int] = {}
    for scenario in scenarios:
        rows = scenario_exposures.loc[scenario_exposures["scenario"].eq(scenario)]
        if len(rows) != 1:
            raise ValueError(
                f"Expected one InMAP exposure row for scenario={scenario!r}; found {len(rows)}."
            )
        inmap_value = float(rows.iloc[0][concentration_column])
        if not np.isfinite(inmap_value) or inmap_value < 0:
            raise ValueError(
                f"Missing, non-finite, or negative InMAP scenario concentration for {scenario!r}."
            )
        concentration = inmap_value
        if concentration_mode == "background_plus_inmap_contribution":
            if background_pm25_ugm3 is None:
                raise ValueError(
                    "background_pm25_ugm3 is required for background_plus_inmap_contribution."
                )
            background = (
                float(background_pm25_ugm3[scenario])
                if isinstance(background_pm25_ugm3, Mapping) and scenario in background_pm25_ugm3
                else (
                    float(background_pm25_ugm3)
                    if not isinstance(background_pm25_ugm3, Mapping)
                    else float("nan")
                )
            )
            if not np.isfinite(background) or background < 0:
                raise ValueError(
                    "background_pm25_ugm3 must contain a finite, non-negative value "
                    f"for scenario={scenario!r}."
                )
            concentration += background
        concentrations[scenario] = concentration
        years[scenario] = int(rows.iloc[0]["year"])
    return concentrations, years


def evaluate_national_health_specifications(
    *,
    scenario_exposures: pd.DataFrame,
    population_path: Path,
    mortality_paths: Mapping[str, Path | None],
    target_year: int,
    population_year: int | None = None,
    mortality_year: int,
    reference_scenario: str,
    policy_scenario: str,
    crf_parameters_path: Path,
    crf_ids: Sequence[str] = RECOMMENDED_CRF_IDS,
    gemm_parameters_path: Path = DEFAULT_GEMM_PARAMETERS_PATH,
    concentration_column: str = "population_weighted_pm25_ugm3",
    concentration_mode: str = "direct_scenario_concentration",
    background_pm25_ugm3: float | Mapping[str, float] | None = None,
    exposure_scope: str = "unspecified",
    comparison_type: str = "historical_to_scenario",
    analytical_use_permitted: bool = False,
) -> HealthSuiteResults:
    """Evaluate every requested CRF against the same InMAP scenario exposure table.

    Missing endpoint-specific mortality does not silently fall back to all-cause
    mortality. The affected specification receives a blocked status row while
    compatible specifications continue. ``analytical_use_permitted`` is an
    explicit caller assertion copied to every result; the adapter does not infer
    scientific fitness from free-text exposure labels.
    """
    scenarios = (reference_scenario, policy_scenario)
    concentrations, inmap_years = _scenario_concentrations(
        scenario_exposures,
        scenarios=scenarios,
        concentration_column=concentration_column,
        concentration_mode=concentration_mode,
        background_pm25_ugm3=background_pm25_ugm3,
    )
    population_source_year = target_year if population_year is None else int(population_year)
    population = _load_population(population_path, population_source_year)

    input_frames: list[pd.DataFrame] = []
    total_frames: list[pd.DataFrame] = []
    impact_frames: list[pd.DataFrame] = []
    status_rows: list[dict[str, object]] = []
    for crf_id in crf_ids:
        crf = load_crf(crf_id, crf_parameters_path, gemm_parameters_path)
        mortality_path = mortality_paths.get(crf.endpoint)
        base_status = {
            "crf_id": crf.crf_id,
            "crf_label": crf.label,
            "crf_model_type": crf.model_type,
            "mortality_endpoint": crf.endpoint,
            "specification_role": crf.specification_role,
            "valid_age_min": crf.valid_age_min,
            "valid_age_max": crf.valid_age_max,
            "counterfactual_ugm3": crf.counterfactual_ugm3,
            "scenario_year": target_year,
            "population_year": population_source_year,
            "mortality_year": mortality_year,
            "exposure_mode": concentration_mode,
            "exposure_scope": exposure_scope,
            "analytical_use_permitted": analytical_use_permitted,
        }
        if mortality_path is None:
            status_rows.append(
                {
                    **base_status,
                    "status": "blocked_missing_endpoint_mortality",
                    "reason": (
                        f"No age-specific mortality input configured for endpoint={crf.endpoint!r}."
                    ),
                    "mortality_path": "",
                }
            )
            continue
        mortality_path = Path(mortality_path)
        if not mortality_path.is_file():
            status_rows.append(
                {
                    **base_status,
                    "status": "blocked_missing_mortality_file",
                    "reason": f"Configured mortality file does not exist: {mortality_path}",
                    "mortality_path": str(mortality_path),
                }
            )
            continue

        try:
            mortality = _load_mortality(
                mortality_path,
                mortality_year=mortality_year,
                endpoint=crf.endpoint,
            )
            model_inputs = _build_inputs_from_concentrations(
                population=population,
                mortality=mortality,
                concentrations=concentrations,
                inmap_years=inmap_years,
                target_year=target_year,
                population_year=population_source_year,
                crf=crf,
                exposure_mode=concentration_mode,
                exposure_scope=exposure_scope,
                analytical_use_permitted=analytical_use_permitted,
            )
        except ValueError as error:
            status_rows.append(
                {
                    **base_status,
                    "status": "blocked_invalid_mortality_input",
                    "reason": str(error),
                    "mortality_path": str(mortality_path),
                }
            )
            continue
        totals = compute_attributable_deaths(model_inputs, crf)
        totals.insert(0, "crf_id", crf.crf_id)
        totals.insert(1, "crf_label", crf.label)
        totals.insert(2, "crf_model_type", crf.model_type)
        totals.insert(3, "mortality_endpoint", crf.endpoint)
        totals.insert(4, "specification_role", crf.specification_role)
        totals["exposure_mode"] = concentration_mode
        totals["exposure_scope"] = exposure_scope
        totals["population_year"] = population_source_year
        totals["mortality_year"] = mortality_year
        totals["analytical_use_permitted"] = analytical_use_permitted
        impacts = calculate_avoided_deaths(
            model_inputs,
            crf,
            reference_scenario=reference_scenario,
            policy_scenario=policy_scenario,
            mortality_year=mortality_year,
            population_year=population_source_year,
            comparison_type=comparison_type,
            exposure_scope=exposure_scope,
        )
        input_frames.append(model_inputs)
        total_frames.append(totals)
        impact_frames.append(impacts)
        status_rows.append(
            {
                **base_status,
                "status": "complete",
                "reason": "",
                "mortality_path": str(mortality_path),
            }
        )

    return HealthSuiteResults(
        model_inputs=pd.concat(input_frames, ignore_index=True)
        if input_frames
        else pd.DataFrame(),
        scenario_totals=(
            pd.concat(total_frames, ignore_index=True) if total_frames else pd.DataFrame()
        ),
        impacts=pd.concat(impact_frames, ignore_index=True) if impact_frames else pd.DataFrame(),
        status=pd.DataFrame(status_rows),
    )
