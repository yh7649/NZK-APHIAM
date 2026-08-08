"""Convert combined Global InMAP runs into Korea-wide diagnostic mortality."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from nzk_aphiam.air_quality.inmap.combined_runner import load_run_jobs
from nzk_aphiam.air_quality.inmap.exposure import (
    install_national_boundary,
    national_scenario_exposure,
)
from nzk_aphiam.air_quality.inmap.outputs import read_output
from nzk_aphiam.mvp.peng_replication.config import (
    DEFAULT_CONFIG_PATH,
    load_config,
)
from nzk_aphiam.mvp.peng_replication.health_adapter import (
    HealthSuiteResults,
    evaluate_national_health_specifications,
)

PRIMARY_CRF_ID = "peng_krewski_2009_all_cause"
EXPOSURE_SCOPE = (
    "incremental_korean_power_and_nonpower_source_contribution_screening_not_total_ambient"
)
POWER_ONLY_EXPOSURE_SCOPE = (
    "incremental_korean_thermal_power_source_contribution_screening_not_total_ambient"
)


def _exposure_scope(run_manifest: dict[str, Any]) -> str:
    return (
        POWER_ONLY_EXPOSURE_SCOPE
        if run_manifest.get("emissions_scope") == "thermal_power_only"
        else EXPOSURE_SCOPE
    )


def _read_run_state(output_path: Path) -> dict[str, Any]:
    state_path = output_path.parent / "run_state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"InMAP run state is missing: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("status") != "complete":
        raise ValueError(f"InMAP run is not complete: {state_path}")
    if not output_path.is_file():
        raise FileNotFoundError(f"InMAP concentration output is missing: {output_path}")
    return state


def collect_national_scenario_exposures(
    job_manifest_path: Path,
    boundary_path: Path,
    *,
    country_iso_a3: str = "KOR",
    allow_nonconverged_diagnostic: bool = False,
    allow_partial_complete: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extract population-weighted Korean PM2.5 from every completed job."""
    _executable, jobs, run_manifest = load_run_jobs(job_manifest_path)
    fixed_iterations = int(run_manifest["num_iterations"]) > 0
    if fixed_iterations and not allow_nonconverged_diagnostic:
        raise ValueError(
            "Fixed-iteration InMAP outputs are non-converged. Rerun with "
            "--allow-nonconverged-diagnostic to create explicitly labeled diagnostics."
        )
    rows: list[pd.DataFrame] = []
    incomplete: list[str] = []
    exposure_scope = _exposure_scope(run_manifest)
    for job in jobs:
        output_path = Path(job["output"])
        try:
            state = _read_run_state(output_path)
        except (FileNotFoundError, ValueError):
            incomplete.append(f"{job['scenario']} {job['year']}")
            continue
        exposure = national_scenario_exposure(
            read_output(output_path),
            boundary_path,
            scenario=str(job["scenario"]),
            year=int(job["year"]),
            country_iso_a3=country_iso_a3,
            concentration_scope=exposure_scope,
        )
        exposure["solver_mode"] = state["solver_mode"]
        exposure["inmap_num_iterations"] = int(state["num_iterations"])
        exposure["inmap_converged"] = bool(state["converged"])
        exposure["input_analytical_use_permitted"] = bool(
            state.get("input_analytical_use_permitted", False)
        )
        exposure["analytical_use_permitted"] = False
        rows.append(exposure)
    if incomplete and not allow_partial_complete:
        raise RuntimeError(
            "Health post-processing requires every InMAP job to complete. "
            f"Missing or incomplete jobs: {incomplete}"
        )
    if not rows:
        raise RuntimeError("No completed InMAP jobs are available for health post-processing.")
    exposures = pd.concat(rows, ignore_index=True).sort_values(["scenario", "year"])
    partial = bool(incomplete)
    exposures["result_status"] = (
        "nonconverged_partial_poc_diagnostic_not_for_inference"
        if fixed_iterations and partial
        else (
            "nonconverged_poc_diagnostic_not_for_inference"
            if fixed_iterations
            else "converged_screening_proxy_not_for_inference"
        )
    )
    run_manifest = dict(run_manifest)
    run_manifest["partial_results"] = partial
    run_manifest["incomplete_jobs"] = incomplete
    return exposures.reset_index(drop=True), run_manifest


def select_balanced_partial_exposures(
    exposures: pd.DataFrame,
    *,
    reference_scenario: str = "no_nzk",
    policy_scenarios: list[str] | None = None,
) -> pd.DataFrame:
    """Retain completed years shared by a reference and selected policies."""
    observed_scenarios = set(exposures["scenario"].astype(str))
    if reference_scenario not in observed_scenarios:
        raise ValueError(f"Reference scenario {reference_scenario!r} is not complete yet.")
    policies = policy_scenarios or sorted(observed_scenarios - {reference_scenario})
    missing = sorted(set(policies) - observed_scenarios)
    if missing:
        raise ValueError(f"Requested policy scenarios have no completed jobs: {missing}")
    if not policies:
        raise ValueError("No completed policy scenario is available for comparison.")
    years_by_scenario = {
        scenario: set(
            pd.to_numeric(
                exposures.loc[exposures["scenario"].eq(scenario), "year"],
                errors="raise",
            ).astype(int)
        )
        for scenario in [reference_scenario, *policies]
    }
    common_years = set.intersection(*years_by_scenario.values())
    if not common_years:
        raise ValueError("The completed reference and policy jobs have no shared years.")
    selected = exposures.loc[
        exposures["scenario"].isin([reference_scenario, *policies])
        & exposures["year"].isin(common_years)
    ].copy()
    return selected.sort_values(["scenario", "year"]).reset_index(drop=True)


def population_source_years(
    population_path: Path,
    target_years: list[int],
) -> dict[int, int]:
    """Use the exact KOSIS projection year or the latest prior available year."""
    population = pd.read_csv(
        population_path,
        usecols=[
            "year",
            "geography_level",
            "sex_code",
            "age_band",
            "population_projected",
        ],
    )
    available = sorted(
        pd.to_numeric(
            population.loc[
                population["geography_level"].eq("province") & population["sex_code"].eq(0),
                "year",
            ],
            errors="coerce",
        )
        .dropna()
        .astype(int)
        .unique()
    )
    if not available:
        raise ValueError(f"{population_path} has no province-level all-sex projection years.")
    selected: dict[int, int] = {}
    for target in sorted(set(target_years)):
        eligible = [year for year in available if year <= target]
        if not eligible:
            raise ValueError(f"No population projection year at or before scenario year {target}.")
        selected[target] = max(eligible)
    return selected


def _annotate_suite(
    suite: HealthSuiteResults,
    *,
    reference_scenario: str,
    policy_scenario: str,
    scenario_year: int,
    population_year: int,
    run_manifest: dict[str, Any],
) -> HealthSuiteResults:
    fixed_iterations = int(run_manifest["num_iterations"]) > 0
    partial = bool(run_manifest.get("partial_results", False))
    result_status = (
        "nonconverged_partial_poc_diagnostic_not_for_inference"
        if fixed_iterations and partial
        else (
            "nonconverged_poc_diagnostic_not_for_inference"
            if fixed_iterations
            else "converged_screening_proxy_not_for_inference"
        )
    )
    frames = []
    for frame in (
        suite.model_inputs,
        suite.scenario_totals,
        suite.impacts,
        suite.status,
    ):
        annotated = frame.copy()
        annotated["reference_scenario"] = reference_scenario
        annotated["policy_scenario"] = policy_scenario
        annotated["scenario_year"] = scenario_year
        annotated["population_year"] = population_year
        annotated["solver_mode"] = run_manifest["solver_mode"]
        annotated["inmap_num_iterations"] = int(run_manifest["num_iterations"])
        annotated["inmap_converged"] = not fixed_iterations
        annotated["result_status"] = result_status
        annotated["analytical_use_permitted"] = False
        frames.append(annotated)
    return HealthSuiteResults(*frames)


def evaluate_all_scenario_mortality(
    exposures: pd.DataFrame,
    config: dict[str, Any],
    run_manifest: dict[str, Any],
    *,
    reference_scenario: str = "no_nzk",
) -> HealthSuiteResults:
    """Calculate scenario totals and same-year avoided deaths for every CRF."""
    scenarios = sorted(exposures["scenario"].astype(str).unique())
    if reference_scenario not in scenarios:
        raise ValueError(f"Reference scenario {reference_scenario!r} is absent.")
    policy_scenarios = [scenario for scenario in scenarios if scenario != reference_scenario]
    if not policy_scenarios:
        raise ValueError("At least one policy scenario is required.")
    years = sorted(pd.to_numeric(exposures["year"], errors="raise").astype(int).unique())
    population_year_map = population_source_years(
        config["inputs"]["population_projection"],
        years,
    )
    mortality_paths = {
        endpoint: config["inputs"].get(input_key) if input_key else None
        for endpoint, input_key in config["health"]["mortality_inputs"].items()
    }

    model_inputs: list[pd.DataFrame] = []
    totals: list[pd.DataFrame] = []
    impacts: list[pd.DataFrame] = []
    statuses: list[pd.DataFrame] = []
    for year in years:
        year_exposures = exposures.loc[exposures["year"].eq(year)].copy()
        observed = set(year_exposures["scenario"])
        missing = sorted(set(scenarios) - observed)
        if missing:
            raise ValueError(f"Scenario year {year} is missing exposures for: {missing}")
        for policy_scenario in policy_scenarios:
            pair = year_exposures.loc[
                year_exposures["scenario"].isin([reference_scenario, policy_scenario])
            ].copy()
            suite = evaluate_national_health_specifications(
                scenario_exposures=pair,
                population_path=config["inputs"]["population_projection"],
                mortality_paths=mortality_paths,
                target_year=year,
                population_year=population_year_map[year],
                mortality_year=int(config["health"]["mortality_year"]),
                reference_scenario=reference_scenario,
                policy_scenario=policy_scenario,
                crf_parameters_path=config["inputs"]["crf_parameters"],
                crf_ids=config["health"]["crf_ids"],
                gemm_parameters_path=config["inputs"]["gemm_parameters"],
                concentration_column="population_weighted_pm25_ugm3",
                concentration_mode="direct_scenario_concentration",
                background_pm25_ugm3=None,
                exposure_scope=_exposure_scope(run_manifest),
                comparison_type="same_year_scenario_comparison",
                analytical_use_permitted=False,
            )
            suite = _annotate_suite(
                suite,
                reference_scenario=reference_scenario,
                policy_scenario=policy_scenario,
                scenario_year=year,
                population_year=population_year_map[year],
                run_manifest=run_manifest,
            )
            model_inputs.append(suite.model_inputs)
            totals.append(suite.scenario_totals)
            impacts.append(suite.impacts)
            statuses.append(suite.status)

    combined_inputs = pd.concat(model_inputs, ignore_index=True)
    combined_inputs.loc[combined_inputs["scenario"].eq(reference_scenario), "policy_scenario"] = (
        pd.NA
    )
    combined_inputs = combined_inputs.drop_duplicates(
        ["crf_id", "scenario", "year", "age_band"]
    ).reset_index(drop=True)
    combined_totals = pd.concat(totals, ignore_index=True)
    total_identity = ["crf_id", "scenario", "year"]
    value_columns = [
        "attributable_deaths",
        "attributable_deaths_ci_low",
        "attributable_deaths_ci_high",
    ]
    variation = combined_totals.groupby(total_identity)[value_columns].nunique(dropna=False)
    if variation.gt(1).any().any():
        raise AssertionError("Duplicated reference mortality totals disagree across comparisons.")
    combined_totals = (
        combined_totals.sort_values(total_identity)
        .drop_duplicates(total_identity, keep="first")
        .reset_index(drop=True)
    )
    combined_totals.loc[combined_totals["scenario"].eq(reference_scenario), "policy_scenario"] = (
        pd.NA
    )
    combined_totals["mortality_metric"] = (
        "annual_deaths_attributable_to_modeled_pm25_source_contribution"
    )
    combined_impacts = pd.concat(impacts, ignore_index=True)
    combined_impacts["comparison_metric"] = "reference_minus_policy_positive_is_avoided_deaths"
    combined_status = pd.concat(statuses, ignore_index=True)
    return HealthSuiteResults(
        model_inputs=combined_inputs,
        scenario_totals=combined_totals,
        impacts=combined_impacts,
        status=combined_status,
    )


def write_health_outputs(
    exposures: pd.DataFrame,
    suite: HealthSuiteResults,
    run_manifest: dict[str, Any],
    output_dir: Path,
    *,
    reference_scenario: str = "no_nzk",
) -> Path:
    """Write explicitly labeled exposure, mortality, comparison, and audit files."""
    fixed_iterations = int(run_manifest["num_iterations"]) > 0
    partial = bool(run_manifest.get("partial_results", False))
    prefix = (
        "diagnostic_partial_nonconverged"
        if fixed_iterations and partial
        else ("diagnostic_nonconverged" if fixed_iterations else "screening_proxy")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "exposures": output_dir / f"{prefix}_national_scenario_exposures.csv",
        "model_inputs": output_dir / f"{prefix}_health_model_inputs.csv",
        "all_crf_totals": output_dir / f"{prefix}_scenario_mortality_all_crfs.csv",
        "primary_totals": output_dir / f"{prefix}_scenario_mortality_primary.csv",
        "comparisons": output_dir / f"{prefix}_avoided_deaths_vs_no_nzk.csv",
        "status": output_dir / f"{prefix}_health_specification_status.csv",
    }
    primary = suite.scenario_totals.loc[suite.scenario_totals["crf_id"].eq(PRIMARY_CRF_ID)].copy()
    if primary.empty:
        raise ValueError(f"Primary CRF {PRIMARY_CRF_ID!r} did not produce mortality totals.")
    exposures.to_csv(paths["exposures"], index=False)
    suite.model_inputs.to_csv(paths["model_inputs"], index=False)
    suite.scenario_totals.to_csv(paths["all_crf_totals"], index=False)
    primary.to_csv(paths["primary_totals"], index=False)
    suite.impacts.to_csv(paths["comparisons"], index=False)
    suite.status.to_csv(paths["status"], index=False)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "solver_mode": run_manifest["solver_mode"],
        "inmap_num_iterations": int(run_manifest["num_iterations"]),
        "inmap_converged": not fixed_iterations,
        "analytical_use_permitted": False,
        "result_status": (
            "nonconverged_partial_poc_diagnostic_not_for_inference"
            if fixed_iterations and partial
            else (
                "nonconverged_poc_diagnostic_not_for_inference"
                if fixed_iterations
                else "converged_screening_proxy_not_for_inference"
            )
        ),
        "partial_results": partial,
        "included_scenarios": sorted(exposures["scenario"].astype(str).unique()),
        "reference_scenario": reference_scenario,
        "included_years": sorted(
            pd.to_numeric(exposures["year"], errors="raise").astype(int).unique().tolist()
        ),
        "incomplete_jobs": run_manifest.get("incomplete_jobs", []),
        "exposure_scope": _exposure_scope(run_manifest),
        "primary_crf_id": PRIMARY_CRF_ID,
        "scenario_mortality_definition": (
            "Annual deaths attributable to the modeled Korean power and non-power "
            "PM2.5 source contribution, not total ambient PM2.5 mortality."
        ),
        "population_projection_rule": (
            "Use the exact scenario year when available; otherwise hold the latest "
            "available prior KOSIS age-specific projection."
        ),
        "mortality_rate_rule": "Hold 2024 national age-specific rates constant.",
        "outputs": {name: path.name for name, path in paths.items()},
        "primary_scenario_rows": int(len(primary)),
        "all_crf_scenario_rows": int(len(suite.scenario_totals)),
        "comparison_rows": int(len(suite.impacts)),
        "specification_status_counts": {
            str(key): int(value) for key, value in suite.status["status"].value_counts().items()
        },
    }
    manifest_path = output_dir / "health_postprocess_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def run_health_postprocess(
    job_manifest_path: Path,
    config_path: Path,
    output_dir: Path,
    *,
    allow_nonconverged_diagnostic: bool = False,
    allow_partial_complete: bool = False,
    partial_policy_scenarios: list[str] | None = None,
    reference_scenario: str = "no_nzk",
) -> Path:
    """Run exposure extraction and the existing health suite across all jobs."""
    config = load_config(config_path)
    boundary = install_national_boundary(
        Path(config["inmap"]["cache_path"]),
        config["exposure"]["national_boundary_url"],
    )
    exposures, run_manifest = collect_national_scenario_exposures(
        job_manifest_path,
        boundary,
        country_iso_a3=config["exposure"]["country_iso_a3"],
        allow_nonconverged_diagnostic=allow_nonconverged_diagnostic,
        allow_partial_complete=allow_partial_complete,
    )
    if allow_partial_complete and run_manifest["partial_results"]:
        exposures = select_balanced_partial_exposures(
            exposures,
            reference_scenario=reference_scenario,
            policy_scenarios=partial_policy_scenarios,
        )
    suite = evaluate_all_scenario_mortality(
        exposures,
        config,
        run_manifest,
        reference_scenario=reference_scenario,
    )
    return write_health_outputs(
        exposures,
        suite,
        run_manifest,
        output_dir,
        reference_scenario=reference_scenario,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--allow-nonconverged-diagnostic", action="store_true")
    parser.add_argument("--allow-partial-complete", action="store_true")
    parser.add_argument("--partial-policy-scenario", action="append")
    parser.add_argument("--reference-scenario", default="no_nzk")
    args = parser.parse_args()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else args.job_manifest.resolve().parent / "health"
    )
    manifest = run_health_postprocess(
        args.job_manifest.resolve(),
        args.config.resolve(),
        output_dir,
        allow_nonconverged_diagnostic=args.allow_nonconverged_diagnostic,
        allow_partial_complete=args.allow_partial_complete,
        partial_policy_scenarios=args.partial_policy_scenario,
        reference_scenario=args.reference_scenario,
    )
    print(f"Wrote combined InMAP health post-processing outputs to {manifest.parent}")


if __name__ == "__main__":
    main()
