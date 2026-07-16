"""Sequential factor decomposition of PM2.5-attributable mortality change.

Implements Huang & Peng (2025) Equations 3-7 and the "Decomposition analysis"
Methods subsection: the change in PM2.5-attributable deaths between a base
year and an end year, under a climate-policy scenario, is attributed in
sequence to (1) population growth, (2) population aging, (3) change in the
baseline (non-PM2.5) mortality rate, and (4) change in PM2.5 exposure -- the
last split into a business-as-usual (BAU) pollution-control component and a
climate-policy component.

Because the four socioeconomic/exposure factors are introduced one at a time
holding the others fixed, the five resulting effects are ORDER-DEPENDENT: a
different sequence (e.g. exposure before aging) would attribute a different
split of the same total change. This module fixes the order given above to
match the reference study; see docs/methods/health_impact_assessment.md.

Reading note on Equation 5 (see docs/methods/health_impact_assessment.md for
the full discussion): as transcribed, Equation 5 subscripts the population
ratio by district and age band, which would already fold the end-year age
structure into the population-growth term and force the aging effect to be
exactly zero. This module instead scales base-year mortality by the
AGGREGATE population ratio (summed across all districts and age bands),
holding age composition fixed, so that introducing the true end-year
age-specific population in the next step isolates the aging effect. This is
an interpretive reading, not a verbatim transcription of the equation.

Because the CRF (see crf.py) is age-restricted at ``crf.valid_age_min``, the
population growth factor here is growth of the RESTRICTED (e.g. 30+)
population, and the aging factor is the composition shift within that
restricted population -- not an all-ages reading of Equations 5-7. Given
Korea's demographics this is not a minor distinction.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from nzk_aphiam.health.crf import ConcentrationResponseFunction
from nzk_aphiam.health.impact import (
    REQUIRED_COLUMNS,
    _warn_truncated_rows,
    validate_inputs,
)

KEY_COLUMNS = ("district_code", "age_band")
SLICE_COLUMNS = ("pm25_ugm3", "baseline_mortality_rate_per_person", "population")


@dataclass(frozen=True)
class DecompositionResult:
    """The five sequential effects plus the three mortality totals they telescope from.

    ``total_effect`` (the sum of the five effects) equals
    ``mortality_end_year_policy - mortality_base_year`` to floating-point
    tolerance -- this is the structural invariant tests check.
    """

    base_year: int
    end_year: int
    baseline_scenario: str
    policy_scenario: str
    mortality_base_year: float
    mortality_end_year_baseline: float
    mortality_end_year_policy: float
    population_growth_effect: float
    population_aging_effect: float
    baseline_mortality_rate_effect: float
    exposure_bau_effect: float
    exposure_climate_policy_effect: float

    @property
    def total_effect(self) -> float:
        return (
            self.population_growth_effect
            + self.population_aging_effect
            + self.baseline_mortality_rate_effect
            + self.exposure_bau_effect
            + self.exposure_climate_policy_effect
        )

    def as_percentages(self) -> dict[str, float]:
        """Each effect as a percentage of mortality_base_year, as reported in the paper."""
        denominator = self.mortality_base_year
        return {
            "population_growth_effect_pct": 100 * self.population_growth_effect / denominator,
            "population_aging_effect_pct": 100 * self.population_aging_effect / denominator,
            "baseline_mortality_rate_effect_pct": (
                100 * self.baseline_mortality_rate_effect / denominator
            ),
            "exposure_bau_effect_pct": 100 * self.exposure_bau_effect / denominator,
            "exposure_climate_policy_effect_pct": (
                100 * self.exposure_climate_policy_effect / denominator
            ),
        }


def _scenario_year_slice(df: pd.DataFrame, year: int, scenario: str) -> pd.DataFrame:
    subset = df.loc[(df["year"] == year) & (df["scenario"] == scenario)]
    if subset.empty:
        raise ValueError(f"No rows found for year={year} scenario={scenario!r}")
    if subset.duplicated(list(KEY_COLUMNS)).any():
        raise ValueError(
            f"Duplicate district_code/age_band rows for year={year} scenario={scenario!r}"
        )
    return subset.set_index(list(KEY_COLUMNS))[list(SLICE_COLUMNS)]


def decompose(
    df: pd.DataFrame,
    crf: ConcentrationResponseFunction,
    *,
    base_year: int,
    end_year: int,
    baseline_scenario: str,
    policy_scenario: str,
) -> DecompositionResult:
    """Sequential population growth / aging / baseline-mortality / exposure decomposition.

    ``df`` must use the same tidy long schema as ``impact.py``
    (district_code, year, scenario, age_band, pm25_ugm3,
    baseline_mortality_rate_per_person, population) and must contain
    matching district_code/age_band combinations for all three of:
    (base_year, baseline_scenario), (end_year, baseline_scenario), and
    (end_year, policy_scenario).
    """
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Input is missing required columns: {missing}")
    validate_inputs(df, crf)
    _warn_truncated_rows(df, crf)

    base = _scenario_year_slice(df, base_year, baseline_scenario)
    end_baseline = _scenario_year_slice(df, end_year, baseline_scenario)
    end_policy = _scenario_year_slice(df, end_year, policy_scenario)

    if not (set(base.index) == set(end_baseline.index) == set(end_policy.index)):
        raise ValueError(
            "district_code/age_band combinations must match exactly across "
            "(base_year, baseline_scenario), (end_year, baseline_scenario), and "
            "(end_year, policy_scenario) for the decomposition to be well defined."
        )

    af_base = crf.apply(base["pm25_ugm3"])
    af_end_baseline = crf.apply(end_baseline["pm25_ugm3"])
    af_end_policy = crf.apply(end_policy["pm25_ugm3"])

    mortality_base_year = float(
        (base["baseline_mortality_rate_per_person"] * base["population"] * af_base).sum()
    )
    mortality_end_year_baseline = float(
        (
            end_baseline["baseline_mortality_rate_per_person"]
            * end_baseline["population"]
            * af_end_baseline
        ).sum()
    )
    mortality_end_year_policy = float(
        (
            end_policy["baseline_mortality_rate_per_person"]
            * end_policy["population"]
            * af_end_policy
        ).sum()
    )

    # A: base-year mortality scaled by the AGGREGATE population-growth ratio only
    # (age composition, Y0, and exposure all held at base-year values).
    population_ratio = end_baseline["population"].sum() / base["population"].sum()
    a_term = mortality_base_year * population_ratio

    # B: introduce the true end-year age-specific population (Y0 and exposure
    # still held at base-year values) -- B - A isolates the aging effect.
    b_term = float(
        (base["baseline_mortality_rate_per_person"] * end_baseline["population"] * af_base).sum()
    )

    # C: introduce the end-year baseline mortality rate (exposure still held
    # at base-year values) -- C - B isolates the baseline-mortality-rate effect.
    c_term = float(
        (
            end_baseline["baseline_mortality_rate_per_person"]
            * end_baseline["population"]
            * af_base
        ).sum()
    )

    population_growth_effect = a_term - mortality_base_year
    population_aging_effect = b_term - a_term
    baseline_mortality_rate_effect = c_term - b_term
    exposure_bau_effect = mortality_end_year_baseline - c_term
    exposure_climate_policy_effect = mortality_end_year_policy - mortality_end_year_baseline

    return DecompositionResult(
        base_year=base_year,
        end_year=end_year,
        baseline_scenario=baseline_scenario,
        policy_scenario=policy_scenario,
        mortality_base_year=mortality_base_year,
        mortality_end_year_baseline=mortality_end_year_baseline,
        mortality_end_year_policy=mortality_end_year_policy,
        population_growth_effect=population_growth_effect,
        population_aging_effect=population_aging_effect,
        baseline_mortality_rate_effect=baseline_mortality_rate_effect,
        exposure_bau_effect=exposure_bau_effect,
        exposure_climate_policy_effect=exposure_climate_policy_effect,
    )
