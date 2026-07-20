"""Orchestrate the Korean thermal-power Huang and Peng replication MVP."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from nzk_aphiam.air_quality.inmap.exposure import (
    install_national_boundary,
    national_population_weighted_exposure,
    national_scenario_exposure,
)
from nzk_aphiam.air_quality.inmap.installation import install_global_inmap
from nzk_aphiam.air_quality.inmap.inventory import generate_scenario_inputs
from nzk_aphiam.air_quality.inmap.outputs import difference_outputs, read_output
from nzk_aphiam.air_quality.inmap.runner import run_scenario
from nzk_aphiam.air_quality.inmap.validation import validate_global_domain
from nzk_aphiam.config.paths import PROJECT_ROOT
from nzk_aphiam.fleet.scenario_allocator import allocate_generation
from nzk_aphiam.health.impact import compute_attributable_deaths
from nzk_aphiam.mvp.peng_replication.audit import build_input_audit, write_input_audit
from nzk_aphiam.mvp.peng_replication.config import (
    DEFAULT_CONFIG_PATH,
    load_config,
    serializable_config,
)
from nzk_aphiam.mvp.peng_replication.emissions import (
    construct_emissions,
    difference_totals,
    prepare_ef_table,
    summarize_emissions,
)
from nzk_aphiam.mvp.peng_replication.fleet import build_thermal_fleet
from nzk_aphiam.mvp.peng_replication.health_adapter import (
    build_national_health_inputs,
    calculate_avoided_deaths,
)
from nzk_aphiam.mvp.peng_replication.scenarios import (
    normalize_macro_scenarios,
    prepare_observed_generation,
    select_scenarios,
)
from nzk_aphiam.mvp.peng_replication.stacks import impute_stack_parameters

RESULT_ROOT = PROJECT_ROOT / "results" / "mvp" / "peng_replication"


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_id(selection: dict[str, Any], inmap_num_iterations: int = 0) -> str:
    reference = str(selection["reference_scenario"]).replace("/", "_")
    policy = str(selection["policy_scenario"]).replace("/", "_")
    identifier = (
        f"{selection['comparison_type']}_{reference}_{selection['historical_year']}_"
        f"to_{policy}_{selection['target_year']}"
    )
    if inmap_num_iterations > 0:
        identifier += f"_inmap_poc_{inmap_num_iterations}_iterations"
    return identifier


def _prepare_generation(
    macro: pd.DataFrame,
    observed_path: Path,
    selection: dict[str, Any],
) -> pd.DataFrame:
    target = macro.loc[
        macro["scenario"].eq(selection["policy_scenario"])
        & macro["year"].eq(selection["target_year"])
    ].copy()
    if selection["comparison_type"] == "historical_to_scenario":
        historical = prepare_observed_generation(
            observed_path,
            year=selection["historical_year"],
            scenario_label=selection["reference_scenario"],
        )
        return pd.concat([historical, target], ignore_index=True, sort=False)
    reference = macro.loc[
        macro["scenario"].eq(selection["reference_scenario"])
        & macro["year"].eq(selection["target_year"])
    ].copy()
    return pd.concat([reference, target], ignore_index=True, sort=False)


def _plant_change_figure(
    emissions: pd.DataFrame,
    destination: Path,
    reference_scenario: str,
    policy_scenario: str,
) -> None:
    grouped = emissions.groupby(["scenario", "plant_id"], as_index=False).agg(
        longitude=("longitude", "first"),
        latitude=("latitude", "first"),
        nox_kg=("nox_kg", "sum"),
        sox_kg=("sox_kg", "sum"),
    )
    reference = grouped.loc[grouped["scenario"].eq(reference_scenario)].set_index("plant_id")
    policy = grouped.loc[grouped["scenario"].eq(policy_scenario)].set_index("plant_id")
    plants = reference.join(policy, how="outer", lsuffix="_reference", rsuffix="_policy").fillna(0)
    plants["reduction_tonnes"] = (
        plants["nox_kg_reference"]
        + plants["sox_kg_reference"]
        - plants["nox_kg_policy"]
        - plants["sox_kg_policy"]
    ) / 1000
    longitude = plants["longitude_policy"].where(
        plants["longitude_policy"].ne(0), plants["longitude_reference"]
    )
    latitude = plants["latitude_policy"].where(
        plants["latitude_policy"].ne(0), plants["latitude_reference"]
    )
    figure, axis = plt.subplots(figsize=(6, 7))
    scatter = axis.scatter(
        longitude,
        latitude,
        c=plants["reduction_tonnes"],
        s=20 + plants["reduction_tonnes"].abs().clip(upper=10000) / 100,
        cmap="coolwarm",
        edgecolor="black",
        linewidth=0.3,
    )
    axis.set(title="Thermal-plant NOx + SOx change", xlabel="Longitude", ylabel="Latitude")
    figure.colorbar(scatter, ax=axis, label="Historical/reference minus scenario (tonnes/year)")
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _summary_figure(
    emissions: pd.DataFrame,
    destination: Path,
    reference_scenario: str,
    policy_scenario: str,
) -> None:
    totals = emissions.groupby("scenario")[["nox_kg", "sox_kg"]].sum() / 1_000_000
    totals = totals.reindex([reference_scenario, policy_scenario])
    figure, axis = plt.subplots(figsize=(7, 4))
    totals.rename(columns={"nox_kg": "NOx", "sox_kg": "SOx"}).plot.bar(ax=axis)
    axis.set(ylabel="thousand tonnes/year", xlabel="", title="Included thermal-power emissions")
    axis.tick_params(axis="x", rotation=0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _pm_change_figure(cells: Any, destination: Path) -> None:
    """Map the real South-Korea-cell concentration difference."""
    values = pd.to_numeric(cells["delta_TotalPM25"], errors="coerce")
    limit = max(float(values.abs().max()), 1e-12)
    figure, axis = plt.subplots(figsize=(6, 7))
    cells.plot(
        column="delta_TotalPM25",
        ax=axis,
        cmap="RdBu_r",
        vmin=-limit,
        vmax=limit,
        legend=True,
        legend_kwds={"label": "Reference minus scenario PM2.5 (µg/m³)"},
    )
    axis.set_title("Modeled Korean thermal-power PM2.5 change")
    axis.set_axis_off()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _label_diagnostic_poc_health(health: pd.DataFrame, *, num_iterations: int) -> pd.DataFrame:
    """Make the sign and non-converged status unambiguous for opt-in POC output."""
    diagnostic = health.copy()
    diagnostic["additional_deaths_policy_minus_reference"] = -diagnostic["avoided_deaths"]
    inverted_low = -diagnostic["avoided_deaths_ci_low"]
    inverted_high = -diagnostic["avoided_deaths_ci_high"]
    diagnostic["additional_deaths_crf_ci_low"] = pd.concat(
        [inverted_low, inverted_high], axis=1
    ).min(axis=1)
    diagnostic["additional_deaths_crf_ci_high"] = pd.concat(
        [inverted_low, inverted_high], axis=1
    ).max(axis=1)
    diagnostic["result_status"] = "nonconverged_poc_diagnostic_not_for_inference"
    diagnostic["inmap_num_iterations"] = num_iterations
    diagnostic["inmap_converged"] = False
    diagnostic["analytical_use_permitted"] = False
    return diagnostic


def prepare_inventory(
    config: dict[str, Any], selection: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    """Build all emissions-side artifacts through valid point-source inventories."""
    inputs = config["inputs"]
    fleet, fleet_diagnostics = build_thermal_fleet(
        inputs["kepco_monthly"],
        representative_sites=config["representative_thermal_sites"],
    )
    fleet, stack_diagnostics = impute_stack_parameters(fleet, inputs["stack_properties"])
    macro = normalize_macro_scenarios(
        inputs["macro_generation"],
        scenario_label=config["comparison"]["single_scenario_label"],
        province_crosswalk=config["province_crosswalk"],
        fuel_crosswalk=config["fuel_crosswalk"],
        technology_crosswalk=config["macro_technology_crosswalk"],
    )
    generation = _prepare_generation(macro, inputs["observed_generation"], selection)
    allocations, allocation_diagnostics = allocate_generation(
        generation,
        fleet,
        fuel_compatibility=config["fuel_compatibility"],
        tolerance_mwh=config["allocation"]["mass_balance_absolute_tolerance_mwh"],
    )
    ef = prepare_ef_table(inputs["ef_table"], year=int(inputs["ef_year"]))
    emissions, ef_diagnostics = construct_emissions(
        allocations,
        ef,
        ef_source_path=inputs["ef_table"],
        ef_year=int(inputs["ef_year"]),
    )
    summary = summarize_emissions(emissions)
    differences = difference_totals(
        emissions,
        reference_scenario=selection["reference_scenario"],
        policy_scenario=selection["policy_scenario"],
    )
    fleet.to_parquet(run_dir / "plant_roster.parquet", index=False)
    fleet_diagnostics.to_csv(run_dir / "plant_roster_diagnostics.csv", index=False)
    allocations.to_parquet(run_dir / "scenario_generation_by_plant.parquet", index=False)
    allocation_diagnostics.to_csv(run_dir / "scenario_generation_diagnostics.csv", index=False)
    emissions.to_parquet(run_dir / "scenario_emissions_by_plant.parquet", index=False)
    summary.to_csv(run_dir / "scenario_emissions_summary.csv", index=False)
    differences.to_csv(run_dir / "scenario_emissions_difference.csv", index=False)
    ef_diagnostics.to_csv(run_dir / "ef_mapping_diagnostics.csv", index=False)
    stack_diagnostics.to_csv(run_dir / "stack_imputation_diagnostics.csv", index=False)
    _plant_change_figure(
        emissions,
        run_dir / "plant_emissions_changes.png",
        selection["reference_scenario"],
        selection["policy_scenario"],
    )
    _summary_figure(
        emissions,
        run_dir / "national_summary.png",
        selection["reference_scenario"],
        selection["policy_scenario"],
    )
    return {
        "fleet": fleet,
        "emissions": emissions,
        "allocation_diagnostics": allocation_diagnostics,
        "ef_diagnostics": ef_diagnostics,
        "stack_diagnostics": stack_diagnostics,
        "emissions_difference": differences,
    }


def _load_inventory_artifacts(run_dir: Path) -> dict[str, Any]:
    return {
        "fleet": pd.read_parquet(run_dir / "plant_roster.parquet"),
        "emissions": pd.read_parquet(run_dir / "scenario_emissions_by_plant.parquet"),
        "allocation_diagnostics": pd.read_csv(run_dir / "scenario_generation_diagnostics.csv"),
        "ef_diagnostics": pd.read_csv(run_dir / "ef_mapping_diagnostics.csv"),
        "stack_diagnostics": pd.read_csv(run_dir / "stack_imputation_diagnostics.csv"),
        "emissions_difference": pd.read_csv(run_dir / "scenario_emissions_difference.csv"),
    }


def _write_report(
    run_dir: Path,
    selection: dict[str, Any],
    artifacts: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> None:
    lines = [
        "# Korean thermal-power replication MVP",
        "",
        f"Run: `{run_dir.name}`",
        "",
    ]
    run_profile = manifest.get("inmap_run_profile", {})
    if run_profile.get("solver_mode") == "fixed_iterations_poc":
        lines.extend(
            [
                "## Proof-of-concept warning",
                "",
                f"Global InMAP stopped after `{run_profile['num_iterations']}` fixed iterations. "
                "This proves real-binary execution and the exposure-data path, but it does not "
                "satisfy InMAP's automatic 0.1% convergence criterion.",
                "",
                "These concentrations are diagnostic only. The workflow prohibits using them for "
                "health impacts or analytical claims.",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            f"Comparison type: `{selection['comparison_type']}`.",
            "This workflow models the incremental PM2.5 response to included Korean thermal-power "
            "emissions only. It is not total ambient PM2.5, does not include non-power or foreign "
            "emissions, and is not a causal policy estimate.",
            "",
            "Future generation uses `existing_site_allocation`; this is an allocation device, not a "
            "prediction of future siting.",
            "",
            "Primary PM2.5, NH3, and VOC are omitted (input as zero) because no documented factor or "
            "TSP-to-primary-PM2.5 conversion was found in the repository. TSP is never treated as PM2.5.",
            "",
            "## Scenario selection",
            "",
            f"- Historical/reference: `{selection['reference_scenario']}` ({selection['historical_year']})",
            f"- Future/policy label: `{selection['policy_scenario']}` ({selection['target_year']})",
            f"- Causal policy claim permitted: `{selection['causal_policy_claim_permitted']}`",
            "",
        ]
    )
    if artifacts:
        allocations = artifacts["allocation_diagnostics"]
        ef_diagnostics = artifacts["ef_diagnostics"]
        stack = artifacts["stack_diagnostics"]
        difference = artifacts["emissions_difference"].iloc[0]
        lines.extend(
            [
                "## Completed emissions-side results",
                "",
                f"- Fleet rows: {len(artifacts['fleet']):,}",
                f"- Allocation groups: {len(allocations):,}",
                f"- Maximum absolute mass-balance error: {allocations['mass_balance_error_mwh'].abs().max():.6g} MWh",
                f"- Synthetic technology groups: {int(allocations.get('synthetic_technology_assignment', pd.Series(dtype=bool)).fillna(False).sum())}",
                f"- EF fallback rows: {int(ef_diagnostics['ef_fallback'].sum())}",
                f"- Fully unit-observed stack rows: {int(stack['all_stack_values_observed'].sum())} / {len(stack)}",
                f"- NOx reduction (historical/reference minus scenario): {difference['nox_kg_reduction'] / 1_000_000:.6g} thousand tonnes/year",
                f"- SOx reduction (historical/reference minus scenario): {difference['sox_kg_reduction'] / 1_000_000:.6g} thousand tonnes/year",
                "",
            ]
        )
    lines.extend(["## Execution state", ""])
    for step, value in manifest["steps"].items():
        lines.append(f"- {step}: `{value}`")
    if manifest.get("blockers"):
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in manifest["blockers"])
    installation_path = run_dir / "inmap" / "installation_manifest.json"
    if installation_path.exists():
        installation = json.loads(installation_path.read_text(encoding="utf-8"))
        lines.extend(
            [
                "",
                "## Global InMAP provenance",
                "",
                f"- Requested release: `{installation['source_release']}`",
                f"- Requested version and source commit: `{installation['requested_version']}` / "
                f"`{installation['source_commit']}`",
                f"- Executable asset: `{installation['executable_asset']}`",
                f"- Executable version output: `{installation['executable_version_output']}`",
                f"- Executable SHA-256: `{installation['executable_sha256']}`",
                f"- Version-output note: {installation['version_output_note']}",
                f"- Model dataset: `{installation['model_data_version']}` "
                f"({installation['model_data_record']})",
                f"- Model archive MD5: `{installation['model_data_archive_md5']}`",
            ]
        )
    exposure_path = run_dir / "national_exposure.csv"
    if exposure_path.exists():
        exposure = pd.read_csv(exposure_path).iloc[0]
        lines.extend(
            [
                "",
                (
                    "## Diagnostic exposure from fixed-iteration Global InMAP output"
                    if run_profile.get("solver_mode") == "fixed_iterations_poc"
                    else "## Exposure from converged Global InMAP output"
                ),
                "",
                "- Population-weighted PM2.5 change "
                f"(reference minus scenario): {exposure['population_weighted_delta_pm25_ugm3']:.6g} µg/m³",
                f"- Represented population: {exposure['represented_population']:.6g}",
                f"- South Korean grid cells: {int(exposure['grid_cell_count'])}",
            ]
        )
    health_path = run_dir / "health_impacts.csv"
    if health_path.exists():
        health = pd.read_csv(health_path)
        lines.extend(
            [
                "",
                "## Health result from real exposure",
                "",
                f"- Avoided deaths: {health['avoided_deaths'].sum():.6g}",
                f"- Lower confidence estimate: {health['avoided_deaths_ci_low'].sum():.6g}",
                f"- Upper confidence estimate: {health['avoided_deaths_ci_high'].sum():.6g}",
                "- Negative values mean additional deaths under the future scenario, not a benefit.",
            ]
        )
    diagnostic_health_path = run_dir / "diagnostic_nonconverged_health_impacts.csv"
    if diagnostic_health_path.exists() and manifest.get("diagnostic_health_postprocessing"):
        health = pd.read_csv(diagnostic_health_path).iloc[0]
        lines.extend(
            [
                "",
                "## Opt-in diagnostic health calculation (not for inference)",
                "",
                "This calculation uses fixed-iteration, non-converged POC concentrations. "
                "It is a sign-and-plumbing diagnostic, not a health-impact result.",
                "",
                "- Additional deaths under future/policy minus historical/reference: "
                f"{health['additional_deaths_policy_minus_reference']:.6g}",
                "- CRF-coefficient-only interval: "
                f"{health['additional_deaths_crf_ci_low']:.6g} to "
                f"{health['additional_deaths_crf_ci_high']:.6g}",
                f"- InMAP iterations: {int(health['inmap_num_iterations'])}; converged: `False`",
                "- Analytical use permitted: `False`",
            ]
        )
    lines.extend(
        ["", "## Exact resume command", "", f"```bash\n{manifest['resume_command']}\n```", ""]
    )
    (run_dir / "MVP_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def execute(args: argparse.Namespace) -> Path:
    config = load_config(args.config)
    if args.target_year:
        config["comparison"]["target_year"] = args.target_year
        config["health"]["population_year"] = args.target_year
    if args.reference_scenario:
        config["comparison"]["reference_scenario"] = args.reference_scenario
    if args.policy_scenario:
        config["comparison"]["policy_scenario"] = args.policy_scenario
    if args.inmap_poc_iterations is not None:
        if args.inmap_poc_iterations <= 0:
            raise ValueError("--inmap-poc-iterations must be a positive integer.")
        config["inmap"]["num_iterations"] = args.inmap_poc_iterations
    inmap_num_iterations = int(config["inmap"].get("num_iterations", 0))
    if inmap_num_iterations < 0:
        raise ValueError("inmap.num_iterations must be zero or positive.")
    poc_mode = inmap_num_iterations > 0
    if args.write_diagnostic_poc_health and not poc_mode:
        raise ValueError("--write-diagnostic-poc-health requires fixed-iteration POC mode.")
    if poc_mode and args.stage == "health" and not args.write_diagnostic_poc_health:
        raise ValueError("Fixed-iteration InMAP POC output may not be used for health impacts.")
    audit = build_input_audit(config)
    macro = normalize_macro_scenarios(
        config["inputs"]["macro_generation"],
        scenario_label=config["comparison"]["single_scenario_label"],
        province_crosswalk=config["province_crosswalk"],
        fuel_crosswalk=config["fuel_crosswalk"],
        technology_crosswalk=config["macro_technology_crosswalk"],
    )
    selection = select_scenarios(
        macro,
        historical_year=config["comparison"]["historical_year"],
        target_year=config["comparison"]["target_year"],
        reference_scenario=config["comparison"]["reference_scenario"],
        policy_scenario=config["comparison"]["policy_scenario"],
        historical_scenario_label=config["comparison"]["historical_scenario_label"],
    )
    run_dir = RESULT_ROOT / _run_id(selection, inmap_num_iterations)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_input_audit(
        audit,
        RESULT_ROOT / "input_audit.json",
        run_dir / "input_audit.json",
    )
    _write_json(selection, run_dir / "scenario_selection.json")
    assumptions = serializable_config(config)
    (run_dir / "assumptions.yaml").write_text(
        yaml.safe_dump(assumptions, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    resume = (
        "PYTHONPATH=src .venv/bin/python -m nzk_aphiam.mvp.peng_replication "
        f"--config {args.config.relative_to(PROJECT_ROOT)} --stage all --resume"
    )
    if poc_mode:
        resume += f" --inmap-poc-iterations {inmap_num_iterations}"
    if args.write_diagnostic_poc_health:
        resume += " --write-diagnostic-poc-health"
    manifest: dict[str, Any] = {
        "run_id": run_dir.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "comparison": selection,
        "inmap_run_profile": {
            "solver_mode": "fixed_iterations_poc" if poc_mode else "automatic_convergence",
            "num_iterations": inmap_num_iterations,
            "convergence_criterion": (
                "not_evaluated_fixed_iteration_diagnostic"
                if poc_mode
                else "all_nonzero_species_mass_and_population_weighted_concentration_below_0.1_percent"
            ),
            "analytical_use_permitted": not poc_mode,
            "health_use_permitted": not poc_mode,
        },
        "steps": {
            "audit": "complete",
            "inventory": "pending",
            "inmap_install": "pending",
            "inmap_run": "pending",
            "exposure": "pending",
            "health": "pending",
        },
        "blockers": [],
        "resume_command": resume,
        "input_checksums": {
            key: _sha256(value)
            for key, value in config["inputs"].items()
            if isinstance(value, Path) and value.is_file()
        },
    }
    if args.dry_run:
        manifest["steps"]["inventory"] = "dry_run_not_executed"
        _write_json(manifest, run_dir / "manifest.json")
        _write_report(run_dir, selection, None, manifest)
        return run_dir

    artifacts: dict[str, Any] | None = None
    installation: dict[str, Any] | None = None
    jobs: list[dict[str, Any]] = []
    try:
        if args.stage in {"inventory", "run", "exposure", "health", "all"}:
            inventory_path = run_dir / "scenario_emissions_by_plant.parquet"
            if inventory_path.exists() and not args.force:
                artifacts = _load_inventory_artifacts(run_dir)
            else:
                artifacts = prepare_inventory(config, selection, run_dir)
            manifest["steps"]["inventory"] = "complete"
        if args.stage in {"install", "run", "exposure", "health", "all"}:
            installation = install_global_inmap(
                config,
                force=args.force,
                skip_download=args.skip_inmap_download,
            )
            _write_json(installation, run_dir / "inmap" / "installation_manifest.json")
            manifest["steps"]["inmap_install"] = "complete"
        if args.stage in {"run", "exposure", "health", "all"}:
            if artifacts is None:
                artifacts = _load_inventory_artifacts(run_dir)
            if installation is None:
                installation = install_global_inmap(
                    config, force=args.force, skip_download=args.skip_inmap_download
                )
            validate_global_domain(artifacts["emissions"], installation, config)
            jobs = generate_scenario_inputs(
                artifacts["emissions"],
                run_dir,
                installation,
                num_iterations=inmap_num_iterations,
            )
            states = [
                run_scenario(
                    Path(installation["executable"]),
                    job,
                    force=args.force,
                    resume=args.resume,
                )
                for job in jobs
            ]
            manifest["inmap_runs"] = states
            manifest["steps"]["inmap_run"] = (
                "complete_fixed_iteration_poc_not_converged"
                if poc_mode
                else "complete_converged_real_global_inmap"
            )
        if args.stage in {"exposure", "health", "all"}:
            if not jobs:
                raise RuntimeError("InMAP jobs are unavailable; run the model stage first.")
            by_scenario = {job["scenario"]: job for job in jobs}
            reference_job = by_scenario[selection["reference_scenario"]]
            policy_job = by_scenario[selection["policy_scenario"]]
            difference = difference_outputs(
                Path(reference_job["output"]),
                Path(policy_job["output"]),
                run_dir / "concentration_difference.gpkg",
            )
            boundary = install_national_boundary(
                Path(config["inmap"]["cache_path"]),
                config["exposure"]["national_boundary_url"],
            )
            national, selected_cells = national_population_weighted_exposure(
                difference,
                boundary,
                country_iso_a3=config["exposure"]["country_iso_a3"],
            )
            national["comparison_type"] = selection["comparison_type"]
            national["reference_scenario"] = selection["reference_scenario"]
            national["policy_scenario"] = selection["policy_scenario"]
            scenario_exposures = pd.concat(
                [
                    national_scenario_exposure(
                        read_output(Path(job["output"])),
                        boundary,
                        scenario=job["scenario"],
                        year=job["year"],
                        country_iso_a3=config["exposure"]["country_iso_a3"],
                    )
                    for job in jobs
                ],
                ignore_index=True,
            )
            national.to_csv(run_dir / "national_exposure.csv", index=False)
            scenario_exposures.to_csv(run_dir / "national_scenario_exposures.csv", index=False)
            selected_cells.to_file(
                run_dir / "concentration_difference.gpkg",
                layer="south_korea_cells",
                driver="GPKG",
                mode="a",
            )
            _pm_change_figure(selected_cells, run_dir / "modeled_pm25_changes.png")
            manifest["steps"]["exposure"] = (
                "complete_diagnostic_poc_output_not_for_inference"
                if poc_mode
                else "complete_converged_real_global_inmap_output"
            )
        health_requested = args.stage in {"health", "all"} and (
            not poc_mode or args.write_diagnostic_poc_health
        )
        if health_requested:
            scenario_exposures = pd.read_csv(
                run_dir / "national_scenario_exposures.csv"
            ).set_index("scenario")
            health_inputs, crf = build_national_health_inputs(
                population_path=config["inputs"]["population_projection"],
                mortality_path=config["inputs"]["age_mortality"],
                target_year=config["health"]["population_year"],
                mortality_year=config["health"]["mortality_year"],
                age_min=config["health"]["age_min"],
                reference_scenario=selection["reference_scenario"],
                policy_scenario=selection["policy_scenario"],
                reference_incremental_pm25=float(
                    scenario_exposures.loc[
                        selection["reference_scenario"],
                        "population_weighted_incremental_pm25_ugm3",
                    ]
                ),
                policy_incremental_pm25=float(
                    scenario_exposures.loc[
                        selection["policy_scenario"],
                        "population_weighted_incremental_pm25_ugm3",
                    ]
                ),
                crf_parameters_path=config["inputs"]["crf_parameters"],
                crf_id=config["health"]["crf_id"],
            )
            health = calculate_avoided_deaths(
                health_inputs,
                crf,
                reference_scenario=selection["reference_scenario"],
                policy_scenario=selection["policy_scenario"],
                mortality_year=config["health"]["mortality_year"],
                comparison_type=selection["comparison_type"],
            )
            if poc_mode:
                diagnostic = _label_diagnostic_poc_health(
                    health, num_iterations=inmap_num_iterations
                )
                totals = compute_attributable_deaths(health_inputs, crf)
                totals["result_status"] = "nonconverged_poc_diagnostic_not_for_inference"
                totals["inmap_num_iterations"] = inmap_num_iterations
                totals["inmap_converged"] = False
                totals["analytical_use_permitted"] = False
                health_inputs.to_csv(
                    run_dir / "diagnostic_nonconverged_health_model_inputs.csv", index=False
                )
                diagnostic.to_csv(
                    run_dir / "diagnostic_nonconverged_health_impacts.csv", index=False
                )
                totals.to_csv(
                    run_dir / "diagnostic_nonconverged_health_scenario_totals.csv", index=False
                )
                manifest["steps"]["health"] = "not_run_fixed_iteration_poc_prohibited"
                manifest["diagnostic_health_postprocessing"] = {
                    "status": "complete_nonconverged_not_for_inference",
                    "normal_health_output_written": False,
                    "analytical_use_permitted": False,
                    "additional_deaths_policy_minus_reference": float(
                        diagnostic["additional_deaths_policy_minus_reference"].sum()
                    ),
                    "additional_deaths_crf_ci_low": float(
                        diagnostic["additional_deaths_crf_ci_low"].sum()
                    ),
                    "additional_deaths_crf_ci_high": float(
                        diagnostic["additional_deaths_crf_ci_high"].sum()
                    ),
                }
            else:
                health_inputs.to_csv(run_dir / "health_model_inputs.csv", index=False)
                health.to_csv(run_dir / "health_impacts.csv", index=False)
                manifest["steps"]["health"] = "complete_from_real_exposure"
        elif args.stage == "all" and poc_mode:
            manifest["steps"]["health"] = "not_run_fixed_iteration_poc_prohibited"
    except Exception as error:
        manifest["blockers"].append(f"{type(error).__name__}: {error}")
        failed = next(
            (step for step, status in manifest["steps"].items() if status == "pending"), None
        )
        if failed:
            manifest["steps"][failed] = "blocked"
        _write_json(manifest, run_dir / "manifest.json")
        _write_report(run_dir, selection, artifacts, manifest)
        if args.stage == "all":
            return run_dir
        raise
    _write_json(manifest, run_dir / "manifest.json")
    _write_report(run_dir, selection, artifacts, manifest)
    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--stage",
        choices=["audit", "inventory", "install", "run", "exposure", "health", "all"],
        default="all",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--target-year", type=int)
    parser.add_argument("--reference-scenario")
    parser.add_argument("--policy-scenario")
    parser.add_argument("--skip-inmap-download", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--inmap-poc-iterations",
        type=int,
        help=(
            "Run an isolated fixed-iteration diagnostic proof of concept. "
            "Its output is not converged and cannot be used for health impacts."
        ),
    )
    parser.add_argument(
        "--write-diagnostic-poc-health",
        action="store_true",
        help=(
            "Opt in to separately named health post-processing from non-converged POC "
            "concentrations. Normal health output remains prohibited."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.config = args.config.resolve()
    run_dir = execute(args)
    print(run_dir)


if __name__ == "__main__":
    main()
