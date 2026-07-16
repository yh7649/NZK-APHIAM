from __future__ import annotations

import math

import pandas as pd
import pytest

from nzk_aphiam.health import decomposition
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


def _row(district_code, year, scenario, age_band, pm25_ugm3, mortality_rate, population):
    return {
        "district_code": district_code,
        "year": year,
        "scenario": scenario,
        "age_band": age_band,
        "pm25_ugm3": pm25_ugm3,
        "baseline_mortality_rate_per_person": mortality_rate,
        "population": population,
    }


def test_telescoping_invariant_holds_exactly() -> None:
    rows = [
        # 2015 baseline
        _row("D1", 2015, "baseline", "30-59", 30.0, 0.004, 100_000.0),
        _row("D1", 2015, "baseline", "60+", 30.0, 0.02, 50_000.0),
        _row("D2", 2015, "baseline", "30-59", 25.0, 0.005, 80_000.0),
        _row("D2", 2015, "baseline", "60+", 25.0, 0.025, 40_000.0),
        # 2030 baseline (BAU pollution control: population grows/ages, mortality
        # rate falls, PM2.5 falls somewhat)
        _row("D1", 2030, "baseline", "30-59", 22.0, 0.0035, 120_000.0),
        _row("D1", 2030, "baseline", "60+", 22.0, 0.018, 70_000.0),
        _row("D2", 2030, "baseline", "30-59", 20.0, 0.0045, 90_000.0),
        _row("D2", 2030, "baseline", "60+", 20.0, 0.022, 55_000.0),
        # 2030 climate policy (same demographics/mortality as baseline end
        # year, additional PM2.5 reduction from climate policy)
        _row("D1", 2030, "climate_policy", "30-59", 16.0, 0.0035, 120_000.0),
        _row("D1", 2030, "climate_policy", "60+", 16.0, 0.018, 70_000.0),
        _row("D2", 2030, "climate_policy", "30-59", 14.0, 0.0045, 90_000.0),
        _row("D2", 2030, "climate_policy", "60+", 14.0, 0.022, 55_000.0),
    ]
    df = pd.DataFrame(rows)

    result = decomposition.decompose(
        df,
        CRF,
        base_year=2015,
        end_year=2030,
        baseline_scenario="baseline",
        policy_scenario="climate_policy",
    )

    assert result.total_effect == pytest.approx(
        result.mortality_end_year_policy - result.mortality_base_year, abs=1e-6
    )


def test_population_growth_isolated_effect() -> None:
    """Uniform population growth with everything else fixed should show up only
    as the population-growth effect, with aging/mortality/exposure effects at
    (approximately) zero."""
    rows = [
        _row("D1", 2015, "baseline", "30-59", 20.0, 0.004, 100_000.0),
        _row("D1", 2015, "baseline", "60+", 20.0, 0.004, 50_000.0),
        _row("D1", 2030, "baseline", "30-59", 20.0, 0.004, 150_000.0),
        _row("D1", 2030, "baseline", "60+", 20.0, 0.004, 75_000.0),
        _row("D1", 2030, "climate_policy", "30-59", 20.0, 0.004, 150_000.0),
        _row("D1", 2030, "climate_policy", "60+", 20.0, 0.004, 75_000.0),
    ]
    df = pd.DataFrame(rows)

    result = decomposition.decompose(
        df,
        CRF,
        base_year=2015,
        end_year=2030,
        baseline_scenario="baseline",
        policy_scenario="climate_policy",
    )

    assert result.population_aging_effect == pytest.approx(0.0, abs=1e-6)
    assert result.baseline_mortality_rate_effect == pytest.approx(0.0, abs=1e-6)
    assert result.exposure_bau_effect == pytest.approx(0.0, abs=1e-6)
    assert result.exposure_climate_policy_effect == pytest.approx(0.0, abs=1e-6)
    assert result.population_growth_effect == pytest.approx(0.5 * result.mortality_base_year)


def test_population_aging_isolated_effect() -> None:
    """Fixed total population with a shift toward the higher-mortality age band,
    everything else fixed, should show up only as the aging effect."""
    af = 1 - math.exp(-0.01 * (20.0 - 10.0))
    rows = [
        _row("D1", 2015, "baseline", "30-59", 20.0, 0.002, 800.0),
        _row("D1", 2015, "baseline", "60+", 20.0, 0.01, 200.0),
        _row("D1", 2030, "baseline", "30-59", 20.0, 0.002, 500.0),
        _row("D1", 2030, "baseline", "60+", 20.0, 0.01, 500.0),
        _row("D1", 2030, "climate_policy", "30-59", 20.0, 0.002, 500.0),
        _row("D1", 2030, "climate_policy", "60+", 20.0, 0.01, 500.0),
    ]
    df = pd.DataFrame(rows)

    result = decomposition.decompose(
        df,
        CRF,
        base_year=2015,
        end_year=2030,
        baseline_scenario="baseline",
        policy_scenario="climate_policy",
    )

    assert result.population_growth_effect == pytest.approx(0.0, abs=1e-6)
    assert result.baseline_mortality_rate_effect == pytest.approx(0.0, abs=1e-6)
    assert result.exposure_bau_effect == pytest.approx(0.0, abs=1e-6)
    assert result.exposure_climate_policy_effect == pytest.approx(0.0, abs=1e-6)
    assert result.population_aging_effect == pytest.approx(2.4 * af, rel=1e-6)


def test_decompose_raises_for_mismatched_district_age_keys() -> None:
    rows = [
        _row("D1", 2015, "baseline", "30-59", 20.0, 0.004, 100_000.0),
        _row("D1", 2015, "baseline", "60+", 20.0, 0.01, 50_000.0),
        _row("D1", 2030, "baseline", "30-59", 20.0, 0.004, 120_000.0),
        _row("D1", 2030, "baseline", "60+", 20.0, 0.01, 60_000.0),
        # climate_policy end year is missing the "60+" band present elsewhere
        _row("D1", 2030, "climate_policy", "30-59", 15.0, 0.004, 120_000.0),
    ]
    df = pd.DataFrame(rows)
    with pytest.raises(ValueError):
        decomposition.decompose(
            df,
            CRF,
            base_year=2015,
            end_year=2030,
            baseline_scenario="baseline",
            policy_scenario="climate_policy",
        )


def test_decompose_raises_for_missing_required_column() -> None:
    df = pd.DataFrame(
        [_row("D1", 2015, "baseline", "30-59", 20.0, 0.004, 100_000.0)]
    ).drop(columns=["population"])
    with pytest.raises(ValueError):
        decomposition.decompose(
            df,
            CRF,
            base_year=2015,
            end_year=2030,
            baseline_scenario="baseline",
            policy_scenario="climate_policy",
        )
