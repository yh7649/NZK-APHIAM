"""Prepare and run combined power/non-power Global InMAP scenario jobs."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from nzk_aphiam.air_quality.inmap.emission_inputs import (
    select_supplemental_emissions,
)
from nzk_aphiam.air_quality.inmap.inventory import write_config
from nzk_aphiam.air_quality.inmap.outputs import read_output
from nzk_aphiam.air_quality.inmap.runner import run_scenario
from nzk_aphiam.config.paths import PROCESSED_DIR, PROJECT_ROOT, RESULTS_RUNS_DIR

DEFAULT_BUNDLE_DIR = PROCESSED_DIR / "inmap" / "combined_proxy_2025_2050"
DEFAULT_INSTALLATION_MANIFEST = PROJECT_ROOT / ".cache" / "inmap" / "installation_manifest.json"
DEFAULT_RUN_DIR = RESULTS_RUNS_DIR / "inmap" / "combined_proxy_2025_2050" / "strict"
INSTALLATION_FIELDS = {
    "executable",
    "inmap_data",
    "variable_grid_data",
    "population_file",
    "mortality_rate_file",
}


def _relative_path(path: Path, base: Path) -> str:
    return os.path.relpath(path.resolve(), start=base.resolve())


def _resolve_relative(path: str | Path, base: Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()


def load_installation_manifest(path: Path) -> dict[str, Any]:
    """Load and validate the pinned InMAP installation paths."""
    if not path.is_file():
        raise FileNotFoundError(
            f"InMAP installation manifest does not exist: {path}. "
            "Run `make peng-mvp-install-inmap PYTHON_INTERPRETER=.venv/bin/python` first."
        )
    installation = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(INSTALLATION_FIELDS - set(installation))
    if missing:
        raise ValueError(f"InMAP installation manifest is missing fields: {missing}")
    absent = [
        Path(installation[field])
        for field in sorted(INSTALLATION_FIELDS)
        if not Path(installation[field]).is_file()
    ]
    if absent:
        raise FileNotFoundError(f"InMAP installation files are missing: {absent}")
    if not os.access(installation["executable"], os.X_OK):
        raise PermissionError(f"InMAP executable is not executable: {installation['executable']}")
    installation["manifest_path"] = path.resolve()
    return installation


def _load_bundle_manifest(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "combined_inmap_input_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Combined input manifest does not exist: {manifest_path}. "
            "Run `make build-inmap-combined-inputs` first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("jobs"):
        raise ValueError(f"Combined input manifest contains no jobs: {manifest_path}")
    return manifest


def _job_inputs(bundle_dir: Path, job: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    input_manifest_path = _resolve_relative(job["manifest"], bundle_dir)
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    inputs = input_manifest.get("inputs", [])
    point = [item for item in inputs if item.get("format") == "shapefile"]
    grid = [item for item in inputs if item.get("format") == "coards"]
    if len(point) != 1 or len(grid) != 1:
        raise ValueError(
            f"Expected one point shapefile and one COARDS grid in {input_manifest_path}; "
            f"found point={len(point)}, grid={len(grid)}."
        )
    base = input_manifest_path.parent
    point[0]["path"] = _resolve_relative(point[0]["path"], base)
    grid[0]["path"] = _resolve_relative(grid[0]["path"], base)
    return {"point": point[0], "grid": grid[0], "manifest": input_manifest}, input_manifest_path


def prepare_run_instructions(
    bundle_dir: Path,
    installation_manifest_path: Path,
    run_dir: Path,
    *,
    num_iterations: int = 0,
    power_only: bool = False,
    scenarios: Sequence[str] | None = None,
    years: Sequence[int] | None = None,
) -> Path:
    """Write one runnable TOML per scenario-year and a resumable job manifest."""
    if num_iterations < 0:
        raise ValueError("num_iterations must be zero or positive.")
    bundle_dir = bundle_dir.resolve()
    run_dir = run_dir.resolve()
    installation = load_installation_manifest(installation_manifest_path.resolve())
    bundle = _load_bundle_manifest(bundle_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    instructions: list[dict[str, Any]] = []

    selected_scenarios = set(scenarios or ())
    selected_years = {int(year) for year in years or ()}
    selected_jobs = [
        job
        for job in bundle["jobs"]
        if (not selected_scenarios or str(job["scenario"]) in selected_scenarios)
        and (not selected_years or int(job["year"]) in selected_years)
    ]
    if not selected_jobs:
        raise ValueError(
            "No bundle jobs match the requested scenario/year filters: "
            f"scenarios={sorted(selected_scenarios)}, years={sorted(selected_years)}"
        )

    for job in selected_jobs:
        scenario = str(job["scenario"])
        year = int(job["year"])
        label = f"{scenario}_{year}"
        resolved, input_manifest_path = _job_inputs(bundle_dir, job)
        point = resolved["point"]
        grid = resolved["grid"]
        supplemental = (
            []
            if power_only
            else select_supplemental_emissions(
                [
                    {
                        "id": grid["id"],
                        "sector": grid["sector"],
                        "format": "coards",
                        "path": grid["path"],
                        "units": grid["units"],
                        "coards_year": grid["coards_year"],
                        "scenarios": [scenario],
                        "years": [year],
                    }
                ],
                scenario=scenario,
                year=year,
                shapefile_units=str(point["units"]),
            )
        )
        output_path = run_dir / "outputs" / scenario / str(year) / "concentrations.shp"
        config_path = run_dir / "configs" / f"{label}.toml"
        write_config(
            scenario=scenario,
            year=year,
            inventory_path=Path(point["path"]),
            inmap_data=Path(installation["inmap_data"]),
            variable_grid_data=Path(installation["variable_grid_data"]),
            population_file=Path(installation["population_file"]),
            mortality_rate_file=Path(installation["mortality_rate_file"]),
            output_path=output_path,
            config_path=config_path,
            num_iterations=num_iterations,
            supplemental_inputs=supplemental,
            emission_units=str(point["units"]),
        )
        instructions.append(
            {
                "scenario": scenario,
                "year": year,
                "label": label,
                "config": _relative_path(config_path, run_dir),
                "output": _relative_path(output_path, run_dir),
                "shapefile": _relative_path(Path(point["path"]), run_dir),
                "emission_files": [
                    _relative_path(Path(point["path"]), run_dir),
                    *([] if power_only else [_relative_path(Path(grid["path"]), run_dir)]),
                ],
                "input_manifest": _relative_path(input_manifest_path, run_dir),
                "num_iterations": num_iterations,
                "input_analytical_use_permitted": bool(
                    resolved["manifest"].get("analytical_use_permitted", False)
                ),
            }
        )

    solver_mode = "automatic_convergence" if num_iterations == 0 else "fixed_iterations_poc"
    job_manifest = {
        "name": "combined_power_nonpower_global_inmap_runs",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bundle_manifest": _relative_path(
            bundle_dir / "combined_inmap_input_manifest.json", run_dir
        ),
        "installation_manifest": _relative_path(installation["manifest_path"], run_dir),
        "solver_mode": solver_mode,
        "num_iterations": num_iterations,
        "strict_solver_convergence_requested": num_iterations == 0,
        "emissions_scope": "thermal_power_only" if power_only else "power_and_nonpower",
        "selected_scenarios": sorted({str(job["scenario"]) for job in selected_jobs}),
        "selected_years": sorted({int(job["year"]) for job in selected_jobs}),
        "input_analytical_use_permitted": bool(bundle.get("analytical_use_permitted", False)),
        "analytical_use_permitted": False,
        "analytical_use_note": (
            "The emissions bundle is a screening fixture. Automatic solver convergence "
            "does not make proxy factors or proxy spatialization analytical."
        ),
        "job_count": len(instructions),
        "path_resolution": "relative_to_this_manifest",
        "jobs": instructions,
    }
    path = run_dir / "run_jobs.json"
    path.write_text(
        json.dumps(job_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_run_jobs(path: Path) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    """Resolve a portable run manifest into runner-ready paths."""
    manifest_path = path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    installation_path = _resolve_relative(manifest["installation_manifest"], base)
    installation = load_installation_manifest(installation_path)
    jobs: list[dict[str, Any]] = []
    for raw in manifest["jobs"]:
        job = dict(raw)
        for field in ("config", "output", "shapefile", "input_manifest"):
            job[field] = _resolve_relative(job[field], base)
        job["emission_files"] = [_resolve_relative(item, base) for item in job["emission_files"]]
        job["analytical_use_permitted"] = bool(raw.get("input_analytical_use_permitted", False))
        jobs.append(job)
    return Path(installation["executable"]), jobs, manifest


def run_all(
    job_manifest_path: Path,
    *,
    force: bool = False,
    resume: bool = True,
    max_workers: int = 1,
    threads_per_job: int | None = None,
) -> Path:
    """Run configured jobs with bounded parallelism and cache-aware resumption."""
    if max_workers < 1:
        raise ValueError("max_workers must be positive.")
    if threads_per_job is not None and threads_per_job < 1:
        raise ValueError("threads_per_job must be positive when provided.")
    executable, jobs, manifest = load_run_jobs(job_manifest_path)
    worker_count = min(max_workers, len(jobs))
    detected_cpus = os.cpu_count() or 1
    resolved_threads = threads_per_job or max(1, detected_cpus // worker_count)
    summary_path = job_manifest_path.resolve().parent / "run_summary.json"
    states_by_index: dict[int, dict[str, Any]] = {}
    print(
        f"Launching {len(jobs)} jobs with {worker_count} concurrent worker(s) "
        f"and {resolved_threads} InMAP thread(s) per worker.",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        for index, job in enumerate(jobs, start=1):
            future = executor.submit(
                run_scenario,
                executable,
                job,
                force=force,
                resume=resume,
                max_threads=resolved_threads,
            )
            futures[future] = (index, job)
        for completed_count, future in enumerate(as_completed(futures), start=1):
            index, job = futures[future]
            state = future.result()
            output = read_output(Path(job["output"]))
            state["validated_output_cells"] = int(len(output))
            state["input_analytical_use_permitted"] = bool(job["analytical_use_permitted"])
            state["analytical_use_permitted"] = bool(
                state["converged"] and job["analytical_use_permitted"]
            )
            states_by_index[index] = state
            states = [states_by_index[key] for key in sorted(states_by_index)]
            print(
                f"[{completed_count}/{len(jobs)}] Completed {job['scenario']} {job['year']}",
                flush=True,
            )
            summary = {
                "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "solver_mode": manifest["solver_mode"],
                "num_iterations": manifest["num_iterations"],
                "max_workers": worker_count,
                "threads_per_job": resolved_threads,
                "job_count": len(jobs),
                "completed_jobs": len(states),
                "all_complete": len(states) == len(jobs),
                "analytical_use_permitted": False,
                "runs": states,
            }
            summary_path.write_text(
                json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Write TOMLs and the run job manifest.")
    prepare.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    prepare.add_argument(
        "--installation-manifest",
        type=Path,
        default=DEFAULT_INSTALLATION_MANIFEST,
    )
    prepare.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    prepare.add_argument("--num-iterations", type=int, default=0)
    prepare.add_argument(
        "--power-only",
        action="store_true",
        help="Exclude all supplemental non-power emissions from every selected job.",
    )
    prepare.add_argument(
        "--scenario",
        action="append",
        help="Prepare only this scenario; repeat to select multiple scenarios.",
    )
    prepare.add_argument(
        "--year",
        action="append",
        type=int,
        help="Prepare only this year; repeat to select multiple years.",
    )

    run = subparsers.add_parser("run", help="Run every job in an instruction manifest.")
    run.add_argument("--job-manifest", type=Path, required=True)
    run.add_argument("--force", action="store_true")
    run.add_argument("--no-resume", action="store_true")
    run.add_argument("--max-workers", type=int, default=1)
    run.add_argument("--threads-per-job", type=int)

    args = parser.parse_args()
    if args.command == "prepare":
        path = prepare_run_instructions(
            args.bundle_dir,
            args.installation_manifest,
            args.run_dir,
            num_iterations=args.num_iterations,
            power_only=args.power_only,
            scenarios=args.scenario,
            years=args.year,
        )
        print(f"Wrote runnable Global InMAP instructions to {path}")
    else:
        summary = run_all(
            args.job_manifest,
            force=args.force,
            resume=not args.no_resume,
            max_workers=args.max_workers,
            threads_per_job=args.threads_per_job,
        )
        print(f"Completed all configured Global InMAP jobs; summary: {summary}")


if __name__ == "__main__":
    main()
