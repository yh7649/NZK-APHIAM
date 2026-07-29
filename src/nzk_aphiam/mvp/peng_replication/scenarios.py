"""MACRO normalization and scientifically constrained scenario selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from nzk_aphiam.integration.macro_kepco_validation import (
    split_macro_type,
    standardize_macro_generation,
)


def normalize_macro_scenarios(
    path: Path,
    *,
    scenario_label: str,
    province_crosswalk: dict[str, str],
    fuel_crosswalk: dict[str, str],
    technology_crosswalk: dict[str, dict[str, str]],
) -> pd.DataFrame:
    """Reuse the validated MACRO normalizer and retain emitting thermal rows."""
    raw = pd.read_csv(path)
    combined_column = next(
        (
            column
            for column in ("Technology", "technology", "Type", "type")
            if column in raw.columns
            and raw[column].astype(str).str.fullmatch(r"[^{}]+\{[^{}]+\}").all()
        ),
        None,
    )
    explicit_fuel = {"Fuel", "fuel", "macro_fuel"} & set(raw.columns)
    if combined_column and not explicit_fuel:
        parsed = raw[combined_column].map(split_macro_type)
        raw["macro_fuel"] = parsed.map(lambda value: value[0])
        raw["macro_technology"] = parsed.map(lambda value: value[1])
    if "Year" in raw:
        years = sorted(pd.to_numeric(raw["Year"], errors="raise").astype(int).unique())
    elif "year" in raw:
        years = sorted(pd.to_numeric(raw["year"], errors="raise").astype(int).unique())
    else:
        raise ValueError(f"{path} has no year column.")
    normalized = pd.concat(
        [standardize_macro_generation(raw, source_file=path, year=year) for year in years],
        ignore_index=True,
    )
    if "scenario" not in raw.columns and "Scenario" not in raw.columns:
        normalized["scenario"] = scenario_label
    normalized["province_code"] = normalized["province"]
    normalized["province"] = normalized["province_code"].map(province_crosswalk)
    missing_provinces = normalized.loc[normalized["province"].isna(), "province_code"].unique()
    if len(missing_provinces):
        raise ValueError(f"Unmapped MACRO province codes: {sorted(missing_provinces)}")
    thermal = normalized["macro_technology"].astype(str).str.startswith("Thermal")
    emitting = normalized["macro_fuel"].astype(str).isin(fuel_crosswalk)
    normalized = normalized.loc[thermal & emitting].copy()
    normalized["fuel"] = normalized["macro_fuel"].map(fuel_crosswalk)

    def map_technology(row: pd.Series) -> str | None:
        mapping = technology_crosswalk.get(str(row["macro_technology"]), {})
        return mapping.get(str(row["macro_fuel"]))

    normalized["technology"] = normalized.apply(map_technology, axis=1)
    missing = normalized.loc[
        normalized["technology"].isna() & (normalized["generation_mwh"] > 0),
        ["macro_fuel", "macro_technology"],
    ].drop_duplicates()
    if not missing.empty:
        raise ValueError(f"Unmapped positive MACRO thermal categories:\n{missing}")
    normalized = normalized.loc[normalized["technology"].notna()].copy()
    normalized["macro_mapping_status"] = "explicit_config_crosswalk"
    normalized["synthetic_technology_requested"] = normalized["macro_technology"].eq(
        "ThermalPowerCCS"
    )
    columns = [
        "scenario",
        "year",
        "province",
        "province_code",
        "fuel",
        "technology",
        "generation_mwh",
        "macro_fuel",
        "macro_technology",
        "macro_type",
        "macro_mapping_status",
        "synthetic_technology_requested",
        "generation_original",
        "generation_original_unit",
        "source_file",
    ]
    return (
        normalized[columns]
        .sort_values(["scenario", "year", "province", "fuel", "technology"])
        .reset_index(drop=True)
    )


def prepare_observed_generation(path: Path, *, year: int, scenario_label: str) -> pd.DataFrame:
    """Normalize the existing observed EPSIS national generation handoff."""
    observed = pd.read_csv(path)
    observed = observed.loc[pd.to_numeric(observed["year"]) == year].copy()
    if observed.empty:
        raise ValueError(f"{path} contains no observed generation rows for {year}.")
    observed = observed.rename(columns={"kepco_fuel": "fuel", "kepco_technology": "technology"})
    observed["scenario"] = scenario_label
    observed["province"] = "national"
    observed["source_file"] = str(path)
    grouped = (
        observed.groupby(
            ["scenario", "year", "province", "fuel", "technology", "source_file"],
            as_index=False,
            dropna=False,
        )["generation_mwh"]
        .sum()
        .sort_values(["fuel", "technology"])
    )
    grouped["macro_fuel"] = pd.NA
    grouped["macro_technology"] = pd.NA
    grouped["macro_type"] = pd.NA
    grouped["macro_mapping_status"] = "observed_epsis_existing_crosswalk"
    grouped["synthetic_technology_requested"] = False
    return grouped


def select_scenarios(
    macro: pd.DataFrame,
    *,
    historical_year: int,
    target_year: int,
    reference_scenario: str | None,
    policy_scenario: str | None,
    historical_scenario_label: str,
) -> dict[str, Any]:
    """Apply the requested priority without inventing a reference scenario."""
    coverage = {
        str(scenario): sorted(group["year"].astype(int).unique().tolist())
        for scenario, group in macro.groupby("scenario")
    }
    if reference_scenario and policy_scenario and reference_scenario != policy_scenario:
        common = sorted(
            set(coverage.get(reference_scenario, []))
            & set(coverage.get(policy_scenario, []))
            & {year for years in coverage.values() for year in years if year > historical_year}
        )
        if common:
            selected_year = target_year if target_year in common else common[0]
            return {
                "comparison_type": "policy_scenario_comparison",
                "reference_scenario": reference_scenario,
                "policy_scenario": policy_scenario,
                "historical_year": historical_year,
                "target_year": selected_year,
                "scenario_coverage": coverage,
                "causal_policy_claim_permitted": False,
            }
    scenarios = sorted(coverage)
    if not scenarios:
        raise ValueError("No MACRO scenarios are available.")
    selected = policy_scenario if policy_scenario in scenarios else scenarios[0]
    future_years = [year for year in coverage[selected] if year > historical_year]
    if not future_years:
        raise ValueError(f"Scenario {selected!r} has no year after {historical_year}.")
    selected_year = target_year if target_year in future_years else min(future_years)
    return {
        "comparison_type": "historical_to_scenario",
        "reference_scenario": historical_scenario_label,
        "policy_scenario": selected,
        "historical_year": historical_year,
        "target_year": selected_year,
        "scenario_coverage": coverage,
        "causal_policy_claim_permitted": False,
        "limitation": (
            "Only one unlabeled future MACRO pathway exists locally; this is an observed "
            "historical-to-modeled-future comparison, not a causal net-zero policy benefit."
        ),
    }
