"""Build lightweight KEPCO-only thermal fleet scenarios for pipeline testing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from nzk_aphiam.config.paths import KEPCO_PROCESSED_DIR, PROJECT_ROOT
from nzk_aphiam.mvp.peng_replication.fleet import (
    add_canonical_unit_ids,
    build_thermal_fleet,
)
from nzk_aphiam.mvp.peng_replication.stacks import impute_stack_parameters

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "scenarios" / "kepco_poc_fleet_scenarios.yaml"
DEFAULT_OUTPUT_DIR = KEPCO_PROCESSED_DIR / "scenarios" / "poc_2025_2050"
DEFAULT_FIGURE_DIR = PROJECT_ROOT / "results" / "figures" / "kepco" / "poc_scenarios"
MASS_COLUMNS = {
    "nox": "nox_kg",
    "sox": "sox_kg",
    "dust_tsp": "dust_tsp_kg",
}
FUEL_ORDER = ["coal", "natural_gas", "oil", "bio_oil_and_diesel", "biomass"]
FUEL_LABELS = {
    "coal": "Coal",
    "natural_gas": "LNG",
    "oil": "Oil",
    "bio_oil_and_diesel": "Bio-oil & diesel",
    "biomass": "Biomass",
}
FUEL_COLORS = {
    "coal": "#4B5563",
    "natural_gas": "#3B82F6",
    "oil": "#F59E0B",
    "bio_oil_and_diesel": "#F97316",
    "biomass": "#22C55E",
}
SCENARIO_ORDER = [
    "no_nzk",
    "nzk_low",
    "nzk_high",
    "no_nzk_fleet_hold",
    "nzk_low_unit_retirement",
    "nzk_high_unit_retirement",
]
SCENARIO_LABELS = {
    "no_nzk": "No NZK",
    "nzk_low": "NZK low",
    "nzk_high": "NZK high",
    "no_nzk_fleet_hold": "No NZK — fleet hold",
    "nzk_low_unit_retirement": "NZK low — unit retirements",
    "nzk_high_unit_retirement": "NZK high — unit retirements",
}


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_config(path: Path) -> dict[str, Any]:
    """Load the scenario fixture configuration and resolve its input paths."""
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")
    for key, value in config["inputs"].items():
        config["inputs"][key] = _resolve_path(value)
    config["config_path"] = path.resolve()
    return config


def _mode(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return pd.NA
    modes = values.mode(dropna=True)
    return modes.iloc[0] if not modes.empty else values.iloc[-1]


def _annualized_sum(values: pd.Series) -> tuple[float, int, float]:
    numeric = pd.to_numeric(values, errors="coerce")
    months = int(numeric.notna().sum())
    if months == 0:
        return 0.0, 0, 0.0
    factor = 12.0 / months
    return float(numeric.sum()) * factor, months, factor


def _annualized_unit_generation(monthly: pd.DataFrame) -> pd.DataFrame:
    """Annualize after combining duplicate component rows within a unit-month."""
    unit_month = (
        monthly.groupby(["unit_id", "date"], as_index=False)["energy_generated_mwh"]
        .sum(min_count=1)
        .sort_values(["unit_id", "date"])
    )
    generation = unit_month.groupby("unit_id")["energy_generated_mwh"].apply(_annualized_sum)
    return pd.DataFrame(
        generation.tolist(),
        index=generation.index,
        columns=[
            "baseline_generation_mwh",
            "baseline_generation_months_reported",
            "baseline_generation_annualization_factor",
        ],
    )


def _prepare_baseline_monthly(monthly_path: Path, baseline_year: int) -> pd.DataFrame:
    monthly = pd.read_csv(monthly_path, low_memory=False)
    monthly = add_canonical_unit_ids(monthly)
    monthly["year"] = pd.to_datetime(monthly["date"], errors="coerce").dt.year
    monthly = monthly.loc[
        monthly["year"].eq(baseline_year)
        & monthly["fuel_type"].notna()
        & monthly["technology"].notna()
        & monthly["row_status"].ne("inactive_placeholder")
    ].copy()
    if monthly.empty:
        raise ValueError(f"{monthly_path} has no usable KEPCO rows for {baseline_year}.")
    for column in ["energy_generated_mwh", "energy_capacity_mw", *MASS_COLUMNS]:
        monthly[column] = pd.to_numeric(monthly[column], errors="coerce")
    return monthly


def _emission_factors(
    monthly: pd.DataFrame,
    roster: pd.DataFrame,
    pollutant: str,
) -> tuple[list[float], list[str]]:
    valid = monthly.loc[monthly["energy_generated_mwh"].gt(0) & monthly[pollutant].notna()].copy()
    if valid.empty:
        raise ValueError(f"No positive-generation {pollutant} observations in baseline data.")

    exact = (
        valid.groupby(["fuel_type", "technology"], dropna=False)
        .agg(mass=(pollutant, "sum"), generation=("energy_generated_mwh", "sum"))
        .assign(ef=lambda data: data["mass"] / data["generation"])["ef"]
    )
    fuel = (
        valid.groupby("fuel_type", dropna=False)
        .agg(mass=(pollutant, "sum"), generation=("energy_generated_mwh", "sum"))
        .assign(ef=lambda data: data["mass"] / data["generation"])["ef"]
    )
    all_thermal = float(valid[pollutant].sum() / valid["energy_generated_mwh"].sum())

    values: list[float] = []
    levels: list[str] = []
    for row in roster.itertuples(index=False):
        key = (row.fuel, row.technology)
        if key in exact.index and np.isfinite(exact.loc[key]):
            values.append(float(exact.loc[key]))
            levels.append("baseline_fuel_technology")
        elif row.fuel in fuel.index and np.isfinite(fuel.loc[row.fuel]):
            values.append(float(fuel.loc[row.fuel]))
            levels.append("baseline_fuel")
        else:
            values.append(all_thermal)
            levels.append("baseline_all_thermal")
    return values, levels


def build_baseline_fleet(
    monthly_path: Path,
    stack_path: Path,
    *,
    baseline_year: int,
    scenario_start_year: int,
) -> pd.DataFrame:
    """Return the complete-calendar KEPCO proxy roster used for all scenarios."""
    monthly = _prepare_baseline_monthly(monthly_path, baseline_year)
    full_roster, _ = build_thermal_fleet(monthly_path, representative_sites=[])
    baseline_unit_ids = set(monthly["unit_id"])
    roster = full_roster.loc[full_roster["unit_id"].isin(baseline_unit_ids)].copy()

    operating_attributes = monthly.groupby("unit_id", as_index=False).agg(
        baseline_fuel=("fuel_type", _mode),
        baseline_technology=("technology", _mode),
        baseline_capacity_mw=("energy_capacity_mw", "max"),
    )
    roster = roster.merge(operating_attributes, on="unit_id", how="left", validate="one_to_one")
    roster["fuel"] = roster.pop("baseline_fuel")
    roster["technology"] = roster.pop("baseline_technology")
    roster["capacity_mw"] = roster.pop("baseline_capacity_mw").fillna(roster["capacity_mw"])

    generation_frame = _annualized_unit_generation(monthly)
    roster = roster.merge(
        generation_frame,
        left_on="unit_id",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    roster["baseline_generation_mwh"] = roster["baseline_generation_mwh"].fillna(0.0)
    roster, _ = impute_stack_parameters(roster, stack_path)

    for pollutant, output_column in MASS_COLUMNS.items():
        factors, levels = _emission_factors(monthly, roster, pollutant)
        roster[f"{pollutant}_ef_kg_per_mwh"] = factors
        roster[f"{pollutant}_ef_mapping_level"] = levels
        roster[f"baseline_{output_column}"] = (
            roster["baseline_generation_mwh"] * roster[f"{pollutant}_ef_kg_per_mwh"]
        )

    roster["baseline_data_year"] = baseline_year
    roster["scenario_start_year"] = scenario_start_year
    roster["baseline_proxy_label"] = (
        f"{scenario_start_year}_proxy_from_complete_{baseline_year}_kepco_calendar_year"
    )
    roster["emissions_method"] = (
        f"{baseline_year}_kepco_generation_times_generation_weighted_fuel_technology_ef"
    )
    return roster.sort_values(["province", "plant_name", "unit_id"]).reset_index(drop=True)


def _phaseout_multiplier(
    *,
    year: int,
    start_year: int,
    end_year: int,
    fuel: str,
    rule: dict[str, Any],
) -> float:
    phaseout = rule["phaseout"]
    targeted = phaseout == "all_thermal" or (
        phaseout == "selected_fuels" and fuel in set(rule["phaseout_fuels"])
    )
    if not targeted:
        return 1.0
    return max(0.0, 1.0 - ((year - start_year) / (end_year - start_year)))


def _is_phaseout_target(fuel: str, rule: dict[str, Any]) -> bool:
    return rule["phaseout"] == "all_thermal" or (
        rule["phaseout"] == "selected_fuels" and fuel in set(rule["phaseout_fuels"])
    )


def _retirement_milestone(retirement_year: float, years: list[int]) -> int:
    """Map a dated closure to the first scenario snapshot after that closure."""
    for year in sorted(years):
        if year > retirement_year:
            return year
    return max(years)


def _retirement_priority_metrics(baseline: pd.DataFrame) -> pd.DataFrame:
    """Calculate transparent fallback-ranking metrics without changing the roster."""
    generation = pd.to_numeric(baseline["baseline_generation_mwh"], errors="coerce")
    capacity = pd.to_numeric(baseline["capacity_mw"], errors="coerce")
    capacity_factor = generation.div(capacity.mul(8_760.0)).where(capacity.gt(0))
    pollution_intensity = pd.to_numeric(baseline["nox_ef_kg_per_mwh"], errors="coerce").fillna(
        0.0
    ) + pd.to_numeric(baseline["sox_ef_kg_per_mwh"], errors="coerce").fillna(0.0)
    return pd.DataFrame(
        {
            "baseline_capacity_factor": capacity_factor,
            "retirement_priority_pollution_intensity_kg_per_mwh": pollution_intensity,
        },
        index=baseline.index,
    )


def _assign_discrete_retirements(
    baseline: pd.DataFrame,
    *,
    years: list[int],
    rule: dict[str, Any],
) -> pd.DataFrame:
    """Assign whole targeted units to five-year retirement milestones.

    Documented closure dates are honored first. Undated units are then selected to
    approximate the linear cumulative generation envelope, with no fractional unit
    scaling, using oldest commissioning year, lowest utilization, highest local
    NOx+SOx intensity, and unit ID as deterministic tie-breakers.
    """
    metrics = _retirement_priority_metrics(baseline)
    target = baseline["fuel"].astype(str).map(lambda fuel: _is_phaseout_target(fuel, rule))
    schedule = metrics.copy()
    schedule["scenario_phaseout_target"] = target
    schedule["scenario_retirement_year"] = pd.Series(pd.NA, index=baseline.index, dtype="Int64")
    schedule["scenario_retirement_basis"] = "not_targeted"
    schedule["retirement_priority_rank"] = pd.Series(pd.NA, index=baseline.index, dtype="Int64")

    if not target.any():
        return schedule

    documented_year = pd.to_numeric(baseline["retirement_year"], errors="coerce")
    documented = target & documented_year.notna()
    schedule.loc[documented, "scenario_retirement_year"] = documented_year.loc[documented].map(
        lambda value: _retirement_milestone(float(value), years)
    )
    schedule.loc[documented, "scenario_retirement_basis"] = "documented_retirement_date"

    fallback = baseline.loc[target & ~documented].copy()
    fallback["baseline_capacity_factor"] = metrics.loc[fallback.index, "baseline_capacity_factor"]
    fallback["retirement_priority_pollution_intensity_kg_per_mwh"] = metrics.loc[
        fallback.index, "retirement_priority_pollution_intensity_kg_per_mwh"
    ]
    fallback["_commissioning_sort"] = pd.to_numeric(
        fallback["commissioning_year"], errors="coerce"
    )
    fallback = fallback.sort_values(
        [
            "_commissioning_sort",
            "baseline_capacity_factor",
            "retirement_priority_pollution_intensity_kg_per_mwh",
            "unit_id",
        ],
        ascending=[True, True, False, True],
        na_position="last",
        kind="stable",
    )
    schedule.loc[fallback.index, "retirement_priority_rank"] = pd.array(
        range(1, len(fallback) + 1), dtype="Int64"
    )

    start_year = min(years)
    end_year = max(years)
    target_generation = pd.to_numeric(
        baseline.loc[target, "baseline_generation_mwh"], errors="coerce"
    ).fillna(0.0)
    total_target_generation = float(target_generation.sum())
    unassigned = list(fallback.index)
    baseline_generation = pd.to_numeric(
        baseline["baseline_generation_mwh"], errors="coerce"
    ).fillna(0.0)

    for milestone in sorted(years)[1:]:
        target_share = (milestone - start_year) / (end_year - start_year)
        required_generation = total_target_generation * target_share
        assigned_by_milestone = schedule["scenario_retirement_year"].notna() & schedule[
            "scenario_retirement_year"
        ].le(milestone)
        retired_generation = float(baseline_generation.loc[assigned_by_milestone].sum())
        while retired_generation + 1e-9 < required_generation and unassigned:
            index = unassigned.pop(0)
            schedule.loc[index, "scenario_retirement_year"] = milestone
            schedule.loc[index, "scenario_retirement_basis"] = (
                "heuristic_oldest_low_utilization_high_pollution"
            )
            retired_generation += float(baseline_generation.loc[index])

    if unassigned:
        schedule.loc[unassigned, "scenario_retirement_year"] = end_year
        schedule.loc[unassigned, "scenario_retirement_basis"] = (
            "heuristic_oldest_low_utilization_high_pollution"
        )
    return schedule


def _discrete_retirement_multiplier(
    *,
    year: int,
    targeted: bool,
    retirement_year: Any,
) -> float:
    if not targeted or pd.isna(retirement_year):
        return 1.0
    return 0.0 if year >= int(retirement_year) else 1.0


def build_scenario_rows(
    baseline: pd.DataFrame,
    *,
    years: list[int],
    scenarios: dict[str, dict[str, Any]],
    province_codes: dict[str, str],
    allocation_method: str = "proportional_generation_scaling",
) -> pd.DataFrame:
    """Expand the baseline roster into deterministic five-year scenario rows."""
    valid_methods = {"proportional_generation_scaling", "discrete_unit_retirement"}
    if allocation_method not in valid_methods:
        raise ValueError(
            f"Unknown allocation_method {allocation_method!r}; expected one of "
            f"{sorted(valid_methods)}."
        )
    start_year = min(years)
    end_year = max(years)
    rows: list[pd.DataFrame] = []
    for scenario, rule in scenarios.items():
        if allocation_method == "discrete_unit_retirement":
            schedule = _assign_discrete_retirements(baseline, years=years, rule=rule)
        else:
            metrics = _retirement_priority_metrics(baseline)
            target = baseline["fuel"].astype(str).map(lambda fuel: _is_phaseout_target(fuel, rule))
            schedule = metrics.copy()
            schedule["scenario_phaseout_target"] = target
            schedule["scenario_retirement_year"] = pd.Series(
                np.where(target, end_year, pd.NA),
                index=baseline.index,
                dtype="Int64",
            )
            schedule["scenario_retirement_basis"] = np.where(
                target, "uniform_proportional_scaling", "not_targeted"
            )
            schedule["retirement_priority_rank"] = pd.Series(
                pd.NA, index=baseline.index, dtype="Int64"
            )
        for year in years:
            frame = baseline.copy()
            frame.insert(0, "year", year)
            frame.insert(0, "scenario", scenario)
            for column in schedule.columns:
                frame[column] = schedule[column].to_numpy()
            frame["allocation_method"] = allocation_method
            if allocation_method == "discrete_unit_retirement":
                frame["scenario_generation_multiplier"] = [
                    _discrete_retirement_multiplier(
                        year=year,
                        targeted=bool(targeted),
                        retirement_year=retirement_year,
                    )
                    for targeted, retirement_year in zip(
                        frame["scenario_phaseout_target"],
                        frame["scenario_retirement_year"],
                        strict=True,
                    )
                ]
            else:
                frame["scenario_generation_multiplier"] = [
                    _phaseout_multiplier(
                        year=year,
                        start_year=start_year,
                        end_year=end_year,
                        fuel=str(fuel),
                        rule=rule,
                    )
                    for fuel in frame["fuel"]
                ]
            frame["scenario_rule"] = rule["description"]
            frame["scenario_operating_status"] = np.select(
                [
                    frame["scenario_generation_multiplier"].eq(0.0),
                    frame["scenario_generation_multiplier"].lt(1.0),
                    frame["scenario_phaseout_target"],
                ],
                ["phased_out", "phase_down", "scheduled_phaseout"],
                default="retained_at_baseline",
            )
            frame["generation_mwh"] = (
                frame["baseline_generation_mwh"] * frame["scenario_generation_multiplier"]
            )
            for pollutant, output_column in MASS_COLUMNS.items():
                frame[output_column] = (
                    frame[f"baseline_{output_column}"] * frame["scenario_generation_multiplier"]
                )
            frame["pm25_kg"] = 0.0
            frame["nh3_kg"] = 0.0
            frame["voc_kg"] = 0.0
            frame["pm25_treatment"] = "omitted_no_documented_tsp_to_primary_pm25_conversion"
            frame["nh3_treatment"] = "omitted_no_documented_factor"
            frame["voc_treatment"] = "omitted_no_documented_factor"
            frame["province_code"] = frame["province"].map(province_codes)
            if frame["province_code"].isna().any():
                missing = sorted(frame.loc[frame["province_code"].isna(), "province"].unique())
                raise ValueError(f"Missing MACRO province codes for: {missing}")
            rows.append(frame)
    scenarios_frame = pd.concat(rows, ignore_index=True)
    ordered = [
        "scenario",
        "year",
        "plant_id",
        "unit_id",
        "plant_name",
        "subsidiary_company",
        "fuel",
        "technology",
        "province",
        "province_code",
        "district",
        "latitude",
        "longitude",
        "capacity_mw",
        "commissioning_year",
        "retirement_year",
        "scenario_retirement_year",
        "scenario_retirement_basis",
        "retirement_priority_rank",
        "scenario_phaseout_target",
        "scenario_operating_status",
        "scenario_generation_multiplier",
        "allocation_method",
        "baseline_capacity_factor",
        "retirement_priority_pollution_intensity_kg_per_mwh",
        "generation_mwh",
        "nox_kg",
        "sox_kg",
        "dust_tsp_kg",
        "pm25_kg",
        "nh3_kg",
        "voc_kg",
        "nox_ef_kg_per_mwh",
        "sox_ef_kg_per_mwh",
        "dust_tsp_ef_kg_per_mwh",
        "nox_ef_mapping_level",
        "sox_ef_mapping_level",
        "dust_tsp_ef_mapping_level",
        "stack_height_m",
        "stack_diameter_m",
        "stack_temperature_k",
        "stack_velocity_m_s",
        "stack_height_m_provenance",
        "stack_diameter_m_provenance",
        "stack_temperature_k_provenance",
        "stack_velocity_m_s_provenance",
        "baseline_data_year",
        "scenario_start_year",
        "baseline_proxy_label",
        "baseline_generation_mwh",
        "baseline_generation_months_reported",
        "baseline_generation_annualization_factor",
        "emissions_method",
        "pm25_treatment",
        "nh3_treatment",
        "voc_treatment",
        "scenario_rule",
        "roster_source",
        "coordinate_provenance",
    ]
    return scenarios_frame[ordered].sort_values(
        ["scenario", "year", "province", "plant_name", "unit_id"]
    )


def _macro_technology(row: pd.Series) -> str:
    fuel_labels = {
        "coal": "Coal",
        "natural_gas": "NaturalGas",
        "oil": "Oil",
        "bio_oil_and_diesel": "Oil",
        "oil_and_natural_gas": "Oil",
        "biomass": "Biomass",
    }
    if row["fuel"] not in fuel_labels:
        raise ValueError(f"No mock MACRO fuel label for {row['fuel']!r}.")
    family = (
        "ThermalSteam"
        if row["technology"] in {"cogeneration_chp", "conventional_steam_turbine"}
        and row["fuel"] == "natural_gas"
        else "ThermalPower"
    )
    return f"{family}{{{fuel_labels[row['fuel']]}}}"


def build_macro_generation(scenarios: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the plant fixture to the existing MACRO generation-file schema."""
    data = scenarios.copy()
    data["Technology"] = data.apply(_macro_technology, axis=1)
    grouped = (
        data.groupby(
            ["scenario", "year", "province_code", "Technology"],
            as_index=False,
            dropna=False,
        )["generation_mwh"]
        .sum()
        .rename(
            columns={
                "scenario": "Scenario",
                "year": "Year",
                "province_code": "Province",
            }
        )
    )
    grouped["Generation_TWh"] = grouped.pop("generation_mwh") / 1_000_000.0
    return grouped.sort_values(["Scenario", "Year", "Province", "Technology"])


def summarize_scenarios(scenarios: pd.DataFrame) -> pd.DataFrame:
    """Return compact fuel-level mass and generation checks."""
    summary = (
        scenarios.groupby(["scenario", "year", "fuel", "allocation_method"], as_index=False)
        .agg(
            roster_rows=("unit_id", "size"),
            operating_rows=(
                "scenario_operating_status",
                lambda values: int(values.ne("phased_out").sum()),
            ),
            generation_mwh=("generation_mwh", "sum"),
            nox_kg=("nox_kg", "sum"),
            sox_kg=("sox_kg", "sum"),
            dust_tsp_kg=("dust_tsp_kg", "sum"),
        )
        .sort_values(["scenario", "year", "fuel"])
    )
    return summary


def plot_generation_scenarios(
    summary: pd.DataFrame,
    figure_dir: Path,
) -> dict[str, Path]:
    """Write consistent stacked-area generation charts for every scenario."""
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator

    data = (
        summary.pivot_table(
            index=["scenario", "year"],
            columns="fuel",
            values="generation_mwh",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reindex(columns=FUEL_ORDER, fill_value=0.0)
        .div(1_000_000.0)
    )
    scenarios = [scenario for scenario in SCENARIO_ORDER if scenario in data.index]
    if not scenarios:
        raise ValueError("No recognized scenarios are available for plotting.")
    stepwise_scenarios = (
        set(summary.loc[summary["allocation_method"].eq("discrete_unit_retirement"), "scenario"])
        if "allocation_method" in summary
        else set()
    )
    maximum = float(data.sum(axis=1).max())
    y_limit = max(10.0, np.ceil(maximum / 20.0) * 20.0)
    figure_dir.mkdir(parents=True, exist_ok=True)

    def draw(axis: Any, scenario: str, *, show_y_label: bool) -> None:
        frame = data.loc[scenario].sort_index()
        years = frame.index.to_numpy()
        values = [frame[fuel].to_numpy() for fuel in FUEL_ORDER]
        stackplot_options: dict[str, Any] = {}
        if scenario in stepwise_scenarios:
            stackplot_options["step"] = "post"
        axis.stackplot(
            years,
            *values,
            colors=[FUEL_COLORS[fuel] for fuel in FUEL_ORDER],
            labels=[FUEL_LABELS[fuel] for fuel in FUEL_ORDER],
            alpha=0.9,
            **stackplot_options,
        )
        totals = frame.sum(axis=1).to_numpy()
        axis.plot(
            years,
            totals,
            color="#111827",
            linewidth=1.2,
            marker="o",
            markersize=3,
            drawstyle="steps-post" if scenario in stepwise_scenarios else "default",
        )
        axis.set_title(SCENARIO_LABELS[scenario], loc="left", fontweight="bold")
        axis.set_xlim(int(years.min()), int(years.max()))
        axis.set_ylim(0.0, y_limit)
        axis.set_xticks(years)
        axis.yaxis.set_major_locator(MultipleLocator(20))
        axis.grid(axis="y", color="#D1D5DB", linewidth=0.6)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_xlabel("Scenario year")
        if show_y_label:
            axis.set_ylabel("Generation (TWh)")
        axis.text(
            years[-1],
            totals[-1] + (y_limit * 0.025),
            f"{totals[-1]:.1f}",
            ha="right",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )

    outputs: dict[str, Path] = {}
    for scenario in scenarios:
        figure, axis = plt.subplots(figsize=(8.2, 4.8), layout="constrained")
        draw(axis, scenario, show_y_label=True)
        handles, labels = axis.get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="outside upper center",
            ncols=3,
            frameon=False,
        )
        destination = figure_dir / f"generation_stack_{scenario}.png"
        figure.savefig(destination, dpi=180, bbox_inches="tight")
        plt.close(figure)
        outputs[f"figure_{scenario}"] = destination

    figure, axes = plt.subplots(
        1,
        len(scenarios),
        figsize=(14.8, 4.8),
        sharey=True,
        layout="constrained",
    )
    axes_array = np.atleast_1d(axes)
    for index, (axis, scenario) in enumerate(zip(axes_array, scenarios, strict=True)):
        draw(axis, scenario, show_y_label=index == 0)
    handles, labels = axes_array[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="outside upper center",
        ncols=len(FUEL_ORDER),
        frameon=False,
    )
    combined = figure_dir / "generation_stack_all_scenarios.png"
    figure.savefig(combined, dpi=180, bbox_inches="tight")
    plt.close(figure)
    outputs["figure_all_scenarios"] = combined
    return outputs


def _metadata(
    *,
    config: dict[str, Any],
    outputs: dict[str, Path],
    baseline: pd.DataFrame,
    scenarios: pd.DataFrame,
) -> dict[str, Any]:
    return {
        "fixture_status": "proof_of_concept_not_forecast",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config["config_path"].relative_to(PROJECT_ROOT)),
        "inputs": {
            key: {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "sha256": _sha256(path),
            }
            for key, path in config["inputs"].items()
        },
        "outputs": {
            key: {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "sha256": _sha256(path),
            }
            for key, path in outputs.items()
            if path.exists()
        },
        "scenario_years": config["years"],
        "scenarios": config["scenarios"],
        "allocation_method": config.get("allocation_method", "proportional_generation_scaling"),
        "baseline_data_year": config["baseline_data_year"],
        "baseline_proxy_year": min(config["years"]),
        "roster_rows": len(baseline),
        "scenario_rows": len(scenarios),
        "assumptions": config["assumptions"],
        "sources": config["sources"],
    }


def generate_scenarios(
    config_path: Path,
    output_dir: Path,
    figure_dir: Path = DEFAULT_FIGURE_DIR,
) -> dict[str, Path]:
    """Generate detailed, aggregate, and audit-ready scenario files."""
    config = load_config(config_path)
    years = [int(year) for year in config["years"]]
    if years != list(range(min(years), max(years) + 1, 5)):
        raise ValueError("Scenario years must be complete five-year increments.")
    baseline = build_baseline_fleet(
        config["inputs"]["kepco_monthly"],
        config["inputs"]["stack_properties"],
        baseline_year=int(config["baseline_data_year"]),
        scenario_start_year=min(years),
    )
    scenarios = build_scenario_rows(
        baseline,
        years=years,
        scenarios=config["scenarios"],
        province_codes=config["province_codes"],
        allocation_method=config.get("allocation_method", "proportional_generation_scaling"),
    )
    macro = build_macro_generation(scenarios)
    summary = summarize_scenarios(scenarios)
    retirement_schedule = scenarios.loc[scenarios["year"].eq(min(years))][
        [
            "scenario",
            "plant_id",
            "unit_id",
            "plant_name",
            "fuel",
            "technology",
            "province",
            "district",
            "capacity_mw",
            "baseline_generation_mwh",
            "commissioning_year",
            "retirement_year",
            "scenario_retirement_year",
            "scenario_retirement_basis",
            "retirement_priority_rank",
            "baseline_capacity_factor",
            "retirement_priority_pollution_intensity_kg_per_mwh",
            "scenario_phaseout_target",
            "scenario_rule",
            "allocation_method",
        ]
    ].copy()

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "detailed_csv": output_dir / "kepco_thermal_fleet_scenarios_2025_2050.csv",
        "detailed_parquet": output_dir / "kepco_thermal_fleet_scenarios_2025_2050.parquet",
        "macro_csv": output_dir / "macro_generation_scenarios_2025_2050.csv",
        "summary_csv": output_dir / "kepco_thermal_fleet_scenario_summary.csv",
        "retirement_schedule_csv": output_dir / "kepco_unit_retirement_schedule.csv",
    }
    scenarios.to_csv(outputs["detailed_csv"], index=False)
    scenarios.to_parquet(outputs["detailed_parquet"], index=False)
    macro.to_csv(outputs["macro_csv"], index=False)
    summary.to_csv(outputs["summary_csv"], index=False)
    retirement_schedule.to_csv(outputs["retirement_schedule_csv"], index=False)
    outputs.update(plot_generation_scenarios(summary, figure_dir))

    metadata_path = output_dir / "macro_generation_scenarios_2025_2050.metadata.json"
    outputs["metadata_json"] = metadata_path
    metadata_path.write_text(
        json.dumps(
            _metadata(
                config=config,
                outputs=outputs,
                baseline=baseline,
                scenarios=scenarios,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURE_DIR)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    outputs = generate_scenarios(
        args.config.resolve(),
        args.output_dir.resolve(),
        args.figure_dir.resolve(),
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
