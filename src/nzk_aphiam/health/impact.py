"""Attributable-deaths calculation from PM2.5, population, and baseline mortality.

Implements Huang & Peng (2025) Equations 2-4:

    AF = 1 - exp(-beta * DeltaPM)                          (attributable fraction)
    DeltaY = AF * Y0 * Pop, summed over district c and age band a   (attributable deaths)

This module is deliberately self-contained: it consumes PM2.5 concentrations,
population, and baseline mortality rates as arguments in the tidy long input
schema below. It does not run, call, or depend on any air quality model.

Input schema (tidy long, one row per district x age band x scenario x year)::

    district_code, year, scenario, age_band, pm25_ugm3,
    baseline_mortality_rate_per_person, population

``baseline_mortality_rate_per_person`` is an annual PER-PERSON rate (deaths
per person per year), NOT the per-100,000 rate KOSIS mortality tables report.
Divide KOSIS rates by 100,000 before calling anything here; a rate above 1 is
rejected as a probable per-100,000 mix-up rather than silently rescaled.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import re

import pandas as pd

from nzk_aphiam.health.crf import (
    DEFAULT_CRF_ID,
    DEFAULT_CRF_PARAMETERS_PATH,
    ConcentrationResponseFunction,
    load_crf,
)

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "district_code",
    "year",
    "scenario",
    "age_band",
    "pm25_ugm3",
    "baseline_mortality_rate_per_person",
    "population",
)

TOTAL_COLUMNS = (
    "attributable_deaths",
    "attributable_deaths_ci_low",
    "attributable_deaths_ci_high",
)


def _age_band_lower_bound(age_band: object) -> int:
    match = re.match(r"(\d+)", str(age_band))
    if not match:
        raise ValueError(f"Cannot parse a lower age bound from age_band={age_band!r}")
    return int(match.group(1))


def validate_inputs(df: pd.DataFrame, crf: ConcentrationResponseFunction) -> None:
    """Reject inputs that are missing columns, out of range, or wrong units.

    Raises on: missing required columns, negative pm25_ugm3, negative or
    implausible (>1, i.e. likely per-100,000) baseline_mortality_rate_per_person,
    negative population, and age_band values below crf.valid_age_min.
    """
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Input is missing required columns: {missing}")

    if (df["pm25_ugm3"] < 0).any():
        bad = df.loc[df["pm25_ugm3"] < 0, ["district_code", "year", "scenario", "age_band"]]
        raise ValueError(f"Negative pm25_ugm3 found:\n{bad}")

    mortality = df["baseline_mortality_rate_per_person"]
    if (mortality > 1).any():
        raise ValueError(
            "baseline_mortality_rate_per_person > 1 found. This function requires an "
            "annual per-person rate. KOSIS mortality tables report deaths per "
            "100,000 -- divide by 100,000 before calling, do not pass the raw rate."
        )
    if (mortality < 0).any():
        raise ValueError("Negative baseline_mortality_rate_per_person found.")

    if (df["population"] < 0).any():
        raise ValueError("Negative population found.")

    lower_bounds = df["age_band"].map(_age_band_lower_bound)
    below_min = lower_bounds < crf.valid_age_min
    if below_min.any():
        bad_bands = sorted(df.loc[below_min, "age_band"].unique())
        raise ValueError(
            f"age_band values below crf.valid_age_min={crf.valid_age_min} found: "
            f"{bad_bands}. Restrict Pop and Y0 to bands at or above valid_age_min "
            "before calling -- this module does not drop or include them silently."
        )


def _warn_truncated_rows(df: pd.DataFrame, crf: ConcentrationResponseFunction) -> None:
    truncated = crf.is_truncated(df["pm25_ugm3"])
    if not truncated.any():
        return
    rows = df.loc[truncated, ["district_code", "year"]].drop_duplicates()
    for _, row in rows.iterrows():
        logger.warning(
            "pm25_ugm3 below counterfactual_ugm3=%.4f for district_code=%s year=%s; "
            "attributable fraction truncated to 0 (max(0, pm25 - counterfactual)) for "
            "that district-year.",
            crf.counterfactual_ugm3,
            row["district_code"],
            row["year"],
        )


def _attributable_deaths(
    df: pd.DataFrame, crf: ConcentrationResponseFunction, beta: float
) -> pd.Series:
    attributable_fraction = crf.apply(df["pm25_ugm3"], beta=beta)
    return attributable_fraction * df["baseline_mortality_rate_per_person"] * df["population"]


def compute_attributable_deaths(
    df: pd.DataFrame, crf: ConcentrationResponseFunction
) -> pd.DataFrame:
    """Total attributable deaths in each scenario-year (Equations 2-4).

    Sums AF * Y0 * Pop over district and age band for every (scenario, year)
    present in ``df``. This is the single-scenario-year total; use
    ``compute_marginal_attributable_deaths`` for the difference between two
    scenarios, which is the project's actual estimand.

    Returns one row per (scenario, year) with the central attributable-death
    estimate plus CI bounds obtained by substituting crf.ci_low / crf.ci_high
    for beta. This propagates uncertainty in the CRF coefficient only -- not
    uncertainty in PM2.5, population, or baseline mortality inputs.
    """
    validate_inputs(df, crf)
    _warn_truncated_rows(df, crf)

    working = df.copy()
    working["attributable_deaths"] = _attributable_deaths(working, crf, crf.beta)
    working["attributable_deaths_ci_low"] = _attributable_deaths(working, crf, crf.ci_low)
    working["attributable_deaths_ci_high"] = _attributable_deaths(working, crf, crf.ci_high)

    totals = (
        working.groupby(["scenario", "year"], as_index=False)[list(TOTAL_COLUMNS)]
        .sum()
        .sort_values(["scenario", "year"])
        .reset_index(drop=True)
    )
    return totals


def compute_marginal_attributable_deaths(
    df: pd.DataFrame,
    crf: ConcentrationResponseFunction,
    baseline_scenario: str,
    comparison_scenario: str,
) -> pd.DataFrame:
    """Marginal attributable deaths between two scenarios, by year.

    This is the estimand the project actually cares about. It is computed by
    differencing two single-scenario-year totals (comparison minus baseline),
    NOT by substituting a concentration difference into the attributable
    fraction formula: AF = 1 - exp(-beta*DeltaPM) is non-linear in PM2.5, so
    ``total(pm25_b) - total(pm25_a) != apply(pm25_b - pm25_a)``. Do not
    "simplify" this into the latter.
    """
    totals = compute_attributable_deaths(df, crf)
    baseline = totals.loc[totals["scenario"] == baseline_scenario].set_index("year")
    comparison = totals.loc[totals["scenario"] == comparison_scenario].set_index("year")
    if baseline.empty:
        raise ValueError(f"No rows found for baseline_scenario={baseline_scenario!r}")
    if comparison.empty:
        raise ValueError(f"No rows found for comparison_scenario={comparison_scenario!r}")

    common_years = sorted(set(baseline.index) & set(comparison.index))
    if not common_years:
        raise ValueError(
            f"baseline_scenario={baseline_scenario!r} and "
            f"comparison_scenario={comparison_scenario!r} share no years."
        )

    marginal = pd.DataFrame({"year": common_years})
    marginal.insert(1, "baseline_scenario", baseline_scenario)
    marginal.insert(2, "comparison_scenario", comparison_scenario)
    for column in TOTAL_COLUMNS:
        marginal[column] = [
            comparison.loc[year, column] - baseline.loc[year, column] for year in common_years
        ]
    return marginal.rename(
        columns={
            "attributable_deaths": "marginal_attributable_deaths",
            "attributable_deaths_ci_low": "marginal_attributable_deaths_ci_low",
            "attributable_deaths_ci_high": "marginal_attributable_deaths_ci_high",
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help=(
            "Tidy long CSV with columns: district_code, year, scenario, age_band, "
            "pm25_ugm3, baseline_mortality_rate_per_person, population"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crf-id", default=DEFAULT_CRF_ID)
    parser.add_argument("--crf-parameters", type=Path, default=DEFAULT_CRF_PARAMETERS_PATH)
    parser.add_argument("--mode", choices=["totals", "marginal"], default="totals")
    parser.add_argument("--baseline-scenario", help="Required for --mode marginal")
    parser.add_argument("--comparison-scenario", help="Required for --mode marginal")
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    df = pd.read_csv(args.input)
    crf = load_crf(args.crf_id, args.crf_parameters)

    if args.mode == "totals":
        result = compute_attributable_deaths(df, crf)
    else:
        if not args.baseline_scenario or not args.comparison_scenario:
            raise SystemExit(
                "--baseline-scenario and --comparison-scenario are required for --mode marginal"
            )
        result = compute_marginal_attributable_deaths(
            df, crf, args.baseline_scenario, args.comparison_scenario
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
