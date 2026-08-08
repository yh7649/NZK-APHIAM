"""Create presentation-ready InMAP and mortality result figures and tables."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from nzk_aphiam.health.combined_inmap import PRIMARY_CRF_ID

SCENARIO_ORDER = ("no_nzk", "nzk_low", "nzk_high")
SCENARIO_ALIASES = {
    "nzk_nonpower_no_nzk_power": "no_nzk",
    "nzk_nonpower_low_nzk_power": "nzk_low",
    "nzk_nonpower_high_nzk_power": "nzk_high",
}
SCENARIO_LABELS = {
    "no_nzk": "No NZK",
    "nzk_low": "NZK low",
    "nzk_high": "NZK high",
}
SCENARIO_COLORS = {
    "no_nzk": "#667085",
    "nzk_low": "#2E6FBB",
    "nzk_high": "#0F9D8A",
}
PM25_COLUMN = "population_weighted_pm25_ugm3"


def _normalize_scenario_names(data: pd.DataFrame) -> pd.DataFrame:
    normalized = data.copy()
    for column in ("scenario", "reference_scenario", "policy_scenario"):
        if column in normalized:
            normalized[column] = normalized[column].replace(SCENARIO_ALIASES)
    return normalized


def _read_health_outputs(
    health_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    manifest_path = health_dir / "health_postprocess_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Health manifest is missing: {manifest_path}. Complete health post-processing first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_names = manifest["outputs"]
    required = {"exposures", "primary_totals", "comparisons"}
    missing = sorted(required - set(output_names))
    if missing:
        raise ValueError(f"Health manifest is missing report inputs: {missing}")
    frames = {
        name: _normalize_scenario_names(pd.read_csv(health_dir / output_names[name]))
        for name in ("exposures", "primary_totals", "comparisons")
    }
    manifest["reference_scenario"] = SCENARIO_ALIASES.get(
        str(manifest.get("reference_scenario", "no_nzk")),
        str(manifest.get("reference_scenario", "no_nzk")),
    )
    return (
        frames["exposures"],
        frames["primary_totals"],
        frames["comparisons"],
        manifest,
    )


def build_report_tables(
    exposures: pd.DataFrame,
    primary_totals: pd.DataFrame,
    comparisons: pd.DataFrame,
    *,
    reference_scenario: str = "no_nzk",
) -> dict[str, pd.DataFrame]:
    """Build concise scenario, mortality, avoided-death, and headline tables."""
    required_exposure = {"scenario", "year", PM25_COLUMN}
    missing_exposure = sorted(required_exposure - set(exposures))
    if missing_exposure:
        raise ValueError(f"Exposure results are missing columns: {missing_exposure}")
    exposure = exposures.copy()
    exposure["year"] = pd.to_numeric(exposure["year"], errors="raise").astype(int)
    if exposure.duplicated(["scenario", "year"]).any():
        raise ValueError("Exposure results contain duplicate scenario-year rows.")
    reference = exposure.loc[
        exposure["scenario"].eq(reference_scenario),
        ["year", PM25_COLUMN],
    ].rename(columns={PM25_COLUMN: "reference_pm25_ugm3"})
    if reference.empty:
        raise ValueError(f"Reference scenario {reference_scenario!r} is absent from exposures.")
    exposure = exposure.merge(reference, on="year", how="left", validate="many_to_one")
    exposure["pm25_reduction_vs_no_nzk_ugm3"] = (
        exposure["reference_pm25_ugm3"] - exposure[PM25_COLUMN]
    )
    exposure["pm25_reduction_vs_no_nzk_percent"] = np.where(
        exposure["reference_pm25_ugm3"].gt(0),
        100 * exposure["pm25_reduction_vs_no_nzk_ugm3"] / exposure["reference_pm25_ugm3"],
        np.nan,
    )

    primary = primary_totals.loc[primary_totals["crf_id"].eq(PRIMARY_CRF_ID)].copy()
    if primary.empty:
        raise ValueError(f"Primary mortality results for {PRIMARY_CRF_ID!r} are absent.")
    primary["year"] = pd.to_numeric(primary["year"], errors="raise").astype(int)
    if primary.duplicated(["scenario", "year"]).any():
        raise ValueError("Primary mortality results contain duplicate scenario-year rows.")
    exposure_keys = exposure[
        [
            "scenario",
            "year",
            PM25_COLUMN,
            "pm25_reduction_vs_no_nzk_ugm3",
            "pm25_reduction_vs_no_nzk_percent",
        ]
    ]
    scenario_mortality = primary.merge(
        exposure_keys,
        on=["scenario", "year"],
        how="inner",
        validate="one_to_one",
    )
    if len(scenario_mortality) != len(exposure):
        raise ValueError("Exposure and primary mortality scenario-year coverage do not match.")

    avoided = comparisons.loc[comparisons["crf_id"].eq(PRIMARY_CRF_ID)].copy()
    if avoided.empty:
        raise ValueError(f"Primary avoided-death results for {PRIMARY_CRF_ID!r} are absent.")
    avoided["year"] = pd.to_numeric(avoided["year"], errors="raise").astype(int)
    if "policy_scenario" not in avoided:
        raise ValueError("Avoided-death results do not identify policy_scenario.")
    policy_exposure = exposure_keys.rename(columns={"scenario": "policy_scenario"})
    avoided = avoided.merge(
        policy_exposure,
        on=["policy_scenario", "year"],
        how="inner",
        validate="one_to_one",
    )
    if avoided.duplicated(["policy_scenario", "year"]).any():
        raise ValueError("Primary avoided-death results contain duplicate policy-year rows.")

    headline_year = int(exposure["year"].max())
    headline = scenario_mortality.loc[
        scenario_mortality["year"].eq(headline_year)
        & ~scenario_mortality["scenario"].eq(reference_scenario)
    ].merge(
        avoided[
            [
                "policy_scenario",
                "year",
                "avoided_deaths",
                "avoided_deaths_ci_low",
                "avoided_deaths_ci_high",
            ]
        ],
        left_on=["scenario", "year"],
        right_on=["policy_scenario", "year"],
        how="inner",
        validate="one_to_one",
    )
    headline = headline[
        [
            "scenario",
            "year",
            PM25_COLUMN,
            "pm25_reduction_vs_no_nzk_ugm3",
            "pm25_reduction_vs_no_nzk_percent",
            "attributable_deaths",
            "attributable_deaths_ci_low",
            "attributable_deaths_ci_high",
            "avoided_deaths",
            "avoided_deaths_ci_low",
            "avoided_deaths_ci_high",
            "population_year",
            "mortality_year",
            "result_status",
            "analytical_use_permitted",
        ]
    ]
    return {
        "inmap_scenario_results": exposure.sort_values(["year", "scenario"]).reset_index(
            drop=True
        ),
        "benmap_scenario_mortality": scenario_mortality.sort_values(
            ["year", "scenario"]
        ).reset_index(drop=True),
        "benmap_avoided_mortality": avoided.sort_values(["year", "policy_scenario"]).reset_index(
            drop=True
        ),
        f"headline_results_{headline_year}": headline.sort_values("scenario").reset_index(
            drop=True
        ),
    }


def _scenario_sequence(values: pd.Series) -> list[str]:
    observed = set(values.astype(str))
    ordered = [scenario for scenario in SCENARIO_ORDER if scenario in observed]
    return ordered + sorted(observed - set(ordered))


def _style_axis(axis: plt.Axes, *, grid_axis: str = "y") -> None:
    axis.grid(axis=grid_axis, color="#D9DEE7", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#AAB2C0")
    axis.tick_params(colors="#344054")


def _subtitle(manifest: dict[str, Any]) -> str:
    iterations = int(manifest["inmap_num_iterations"])
    partial = "partial run · " if manifest.get("partial_results", False) else ""
    source_scope = (
        "thermal-power source contribution"
        if "thermal_power" in str(manifest.get("exposure_scope", ""))
        else "included Korean source contribution"
    )
    return (
        f"Global InMAP · {partial}{iterations}-iteration non-converged diagnostic · {source_scope}"
        if iterations > 0
        else f"Global InMAP · automatic-convergence screening result · {source_scope}"
    )


def plot_inmap_results(
    exposure: pd.DataFrame,
    manifest: dict[str, Any],
    path: Path,
) -> None:
    """Plot PM2.5 contribution levels and reductions relative to the reference scenario."""
    reference_scenario = str(manifest.get("reference_scenario", "no_nzk"))
    scenarios = _scenario_sequence(exposure["scenario"])
    policies = [scenario for scenario in scenarios if scenario != reference_scenario]
    figure, (levels_axis, reduction_axis) = plt.subplots(
        1,
        2,
        figsize=(13.8, 6.7),
        gridspec_kw={"width_ratios": [1.08, 1]},
    )
    figure.subplots_adjust(left=0.075, right=0.97, top=0.77, bottom=0.17, wspace=0.28)
    for scenario in scenarios:
        frame = exposure.loc[exposure["scenario"].eq(scenario)].sort_values("year")
        color = SCENARIO_COLORS.get(scenario, "#7F56D9")
        levels_axis.plot(
            frame["year"],
            frame[PM25_COLUMN],
            color=color,
            linewidth=3,
            marker="o",
            markersize=6,
            label=SCENARIO_LABELS.get(scenario, scenario),
        )
        endpoint = frame.iloc[-1]
        levels_axis.annotate(
            f"{endpoint[PM25_COLUMN]:.3f}",
            (endpoint["year"], endpoint[PM25_COLUMN]),
            xytext=(-4, 9),
            textcoords="offset points",
            ha="right",
            color=color,
            fontsize=10,
            fontweight="bold",
        )
    levels_axis.set_title("A. Population-weighted PM₂.₅ contribution", loc="left", pad=13)
    levels_axis.set_ylabel("Annual-average PM₂.₅ (µg/m³)")
    levels_axis.set_xlabel("Scenario year")
    levels_axis.set_xticks(sorted(exposure["year"].unique()))
    levels_axis.set_ylim(bottom=0)
    levels_axis.legend(frameon=False, ncol=min(3, len(scenarios)), loc="upper left")
    _style_axis(levels_axis)

    for scenario in policies:
        frame = exposure.loc[exposure["scenario"].eq(scenario)].sort_values("year")
        color = SCENARIO_COLORS.get(scenario, "#7F56D9")
        reduction_axis.plot(
            frame["year"],
            frame["pm25_reduction_vs_no_nzk_percent"],
            color=color,
            linewidth=3,
            marker="o",
            markersize=6,
            label=SCENARIO_LABELS.get(scenario, scenario),
        )
        endpoint = frame.iloc[-1]
        reduction_axis.annotate(
            f"{endpoint['pm25_reduction_vs_no_nzk_percent']:.3f}%",
            (endpoint["year"], endpoint["pm25_reduction_vs_no_nzk_percent"]),
            xytext=(-4, 9),
            textcoords="offset points",
            ha="right",
            color=color,
            fontsize=10,
            fontweight="bold",
        )
    reduction_axis.axhline(0, color="#98A2B3", linewidth=1)
    reduction_axis.set_title("B. Reduction relative to No NZK", loc="left", pad=13)
    reduction_axis.set_ylabel("Population-weighted PM₂.₅ reduction (%)")
    reduction_axis.set_xlabel("Scenario year")
    reduction_axis.set_xticks(sorted(exposure["year"].unique()))
    reduction_axis.legend(frameon=False, loc="upper left")
    _style_axis(reduction_axis)

    figure.suptitle(
        "Modeled PM₂.₅ contribution across the NZK pathways",
        x=0.075,
        y=0.95,
        ha="left",
        fontsize=19,
        fontweight="bold",
        color="#101828",
    )
    figure.text(0.075, 0.875, _subtitle(manifest), color="#667085", fontsize=11)
    figure.text(
        0.075,
        0.055,
        "Screening proxy; not total ambient PM₂.₅ and not for inference.",
        color="#667085",
        fontsize=9.5,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def plot_avoided_mortality(
    avoided: pd.DataFrame,
    manifest: dict[str, Any],
    path: Path,
) -> None:
    """Plot annual avoided deaths and coefficient intervals."""
    figure, axis = plt.subplots(figsize=(10.8, 6.7))
    figure.subplots_adjust(left=0.105, right=0.97, top=0.77, bottom=0.17)
    for scenario in _scenario_sequence(avoided["policy_scenario"]):
        frame = avoided.loc[avoided["policy_scenario"].eq(scenario)].sort_values("year")
        color = SCENARIO_COLORS.get(scenario, "#7F56D9")
        years = frame["year"].to_numpy(dtype=float)
        central = frame["avoided_deaths"].to_numpy(dtype=float)
        low = frame["avoided_deaths_ci_low"].to_numpy(dtype=float)
        high = frame["avoided_deaths_ci_high"].to_numpy(dtype=float)
        axis.fill_between(years, low, high, color=color, alpha=0.14, linewidth=0)
        axis.plot(
            years,
            central,
            color=color,
            linewidth=3,
            marker="o",
            markersize=6,
            label=SCENARIO_LABELS.get(scenario, scenario),
        )
        axis.annotate(
            f"{central[-1]:,.2f}",
            (years[-1], central[-1]),
            xytext=(-4, 9),
            textcoords="offset points",
            ha="right",
            color=color,
            fontsize=10,
            fontweight="bold",
        )
    axis.axhline(0, color="#98A2B3", linewidth=1)
    axis.set_ylabel("Annual avoided attributable deaths")
    axis.set_xlabel("Scenario year")
    axis.set_xticks(sorted(avoided["year"].unique()))
    axis.legend(frameon=False, loc="upper left")
    _style_axis(axis)
    figure.suptitle(
        "Estimated avoided mortality from the power pathways",
        x=0.105,
        y=0.95,
        ha="left",
        fontsize=19,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.105,
        0.875,
        f"Primary CRF: {PRIMARY_CRF_ID} · shaded bands are coefficient intervals",
        color="#667085",
        fontsize=11,
    )
    reference_scenario = str(manifest.get("reference_scenario", "no_nzk"))
    reference_label = SCENARIO_LABELS.get(reference_scenario, reference_scenario)
    figure.text(
        0.105,
        0.055,
        f"{reference_label} minus policy; positive values are avoided deaths. "
        "Diagnostic screening result—not total national mortality.",
        color="#667085",
        fontsize=9.5,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def plot_headline_summary(
    headline: pd.DataFrame,
    manifest: dict[str, Any],
    path: Path,
) -> None:
    """Plot endpoint-year PM2.5 reductions and avoided deaths side by side."""
    frame = headline.sort_values(
        "scenario",
        key=lambda values: values.map({"nzk_low": 0, "nzk_high": 1}).fillna(99),
    )
    labels = [SCENARIO_LABELS.get(value, value) for value in frame["scenario"]]
    colors = [SCENARIO_COLORS.get(value, "#7F56D9") for value in frame["scenario"]]
    figure, (pm_axis, death_axis) = plt.subplots(1, 2, figsize=(11.8, 6.5))
    figure.subplots_adjust(left=0.09, right=0.97, top=0.75, bottom=0.19, wspace=0.36)
    positions = np.arange(len(frame))
    pm_values = frame["pm25_reduction_vs_no_nzk_percent"].to_numpy(dtype=float)
    pm_bars = pm_axis.bar(positions, pm_values, color=colors, width=0.62)
    pm_axis.bar_label(pm_bars, labels=[f"{value:.3f}%" for value in pm_values], padding=4)
    pm_axis.set_xticks(positions, labels)
    pm_axis.set_ylabel("PM₂.₅ reduction from No NZK (%)")
    pm_axis.set_title("A. Population-weighted PM₂.₅", loc="left", pad=13)
    pm_axis.set_ylim(0, max(0.001, float(np.nanmax(pm_values)) * 1.28))
    _style_axis(pm_axis)

    death_values = frame["avoided_deaths"].to_numpy(dtype=float)
    death_low = frame["avoided_deaths_ci_low"].to_numpy(dtype=float)
    death_high = frame["avoided_deaths_ci_high"].to_numpy(dtype=float)
    error = np.vstack([death_values - death_low, death_high - death_values])
    death_bars = death_axis.bar(
        positions,
        death_values,
        color=colors,
        width=0.62,
        yerr=error,
        capsize=5,
        error_kw={"elinewidth": 1.3, "ecolor": "#344054"},
    )
    death_axis.bar_label(
        death_bars,
        labels=[f"{value:,.2f}" for value in death_values],
        padding=8,
    )
    death_axis.set_xticks(positions, labels)
    death_axis.set_ylabel("Annual avoided attributable deaths")
    death_axis.set_title("B. Avoided mortality", loc="left", pad=13)
    death_axis.set_ylim(bottom=0)
    _style_axis(death_axis)

    year = int(frame["year"].iloc[0])
    figure.suptitle(
        f"{year} air-quality and health results",
        x=0.09,
        y=0.95,
        ha="left",
        fontsize=19,
        fontweight="bold",
        color="#101828",
    )
    figure.text(0.09, 0.865, _subtitle(manifest), color="#667085", fontsize=11)
    figure.text(
        0.09,
        0.055,
        "Primary all-cause CRF; screening proxy and non-converged diagnostic.",
        color="#667085",
        fontsize=9.5,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def write_combined_report(
    health_dir: Path,
    figure_dir: Path,
    table_dir: Path,
) -> Path:
    """Read health results and write all report tables, figures, and a manifest."""
    exposures, primary, comparisons, health_manifest = _read_health_outputs(health_dir)
    tables = build_report_tables(
        exposures,
        primary,
        comparisons,
        reference_scenario=str(health_manifest.get("reference_scenario", "no_nzk")),
    )
    table_dir.mkdir(parents=True, exist_ok=True)
    table_paths: dict[str, Path] = {}
    for name, frame in tables.items():
        path = table_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        table_paths[name] = path

    headline_name = next(name for name in tables if name.startswith("headline_results_"))
    figure_paths = {
        "inmap_pm25_trajectories": figure_dir / "inmap_pm25_trajectories.png",
        "benmap_avoided_mortality": figure_dir / "benmap_avoided_mortality.png",
        "air_quality_health_summary": figure_dir / "air_quality_health_summary.png",
    }
    plot_inmap_results(
        tables["inmap_scenario_results"],
        health_manifest,
        figure_paths["inmap_pm25_trajectories"],
    )
    plot_avoided_mortality(
        tables["benmap_avoided_mortality"],
        health_manifest,
        figure_paths["benmap_avoided_mortality"],
    )
    plot_headline_summary(
        tables[headline_name],
        health_manifest,
        figure_paths["air_quality_health_summary"],
    )
    report_manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_health_manifest": str((health_dir / "health_postprocess_manifest.json").resolve()),
        "result_status": health_manifest["result_status"],
        "analytical_use_permitted": False,
        "primary_crf_id": PRIMARY_CRF_ID,
        "tables": {name: str(path.resolve()) for name, path in table_paths.items()},
        "figures": {name: str(path.resolve()) for name, path in figure_paths.items()},
    }
    manifest_path = table_dir / "combined_results_report_manifest.json"
    manifest_path.write_text(
        json.dumps(report_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-dir", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    parser.add_argument("--table-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = write_combined_report(
        args.health_dir.resolve(),
        args.figure_dir.resolve(),
        args.table_dir.resolve(),
    )
    print(f"Wrote combined InMAP and mortality report: {manifest}")


if __name__ == "__main__":
    main()
