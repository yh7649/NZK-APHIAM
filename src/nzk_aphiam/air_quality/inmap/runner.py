"""Subprocess execution, logging, and cache checks for Global InMAP."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from nzk_aphiam.air_quality.inmap.emission_inputs import emission_dependency_files
from nzk_aphiam.air_quality.inmap.installation import executable_version, file_checksum


def _run_key(executable: Path, config_path: Path, emission_paths: list[Path]) -> str:
    digest = sha256()
    digest.update(executable_version(executable).encode())
    dependencies = [config_path.resolve(), *emission_dependency_files(emission_paths)]
    for path in dependencies:
        digest.update(str(path).encode())
        digest.update(file_checksum(path).encode())
    return digest.hexdigest()


def run_scenario(
    executable: Path,
    job: dict[str, Any],
    *,
    force: bool = False,
    resume: bool = False,
    max_threads: int | None = None,
) -> dict[str, Any]:
    """Run one scenario or reuse a successful identical cached output."""
    if max_threads is not None and max_threads < 1:
        raise ValueError("max_threads must be positive when provided.")
    config_path = Path(job["config"])
    output_path = Path(job["output"])
    emission_paths = [Path(path) for path in job.get("emission_files", [Path(job["shapefile"])])]
    state_path = output_path.parent / "run_state.json"
    run_key = _run_key(executable, config_path, emission_paths)
    dependencies = emission_dependency_files(emission_paths)
    num_iterations = int(job.get("num_iterations", 0))
    input_analytical_use_permitted = bool(job.get("analytical_use_permitted", num_iterations == 0))
    if state_path.exists() and output_path.exists() and not force:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("run_key") == run_key and state.get("status") == "complete":
            state["cache_hit"] = True
            return state
    if resume and output_path.exists() and not state_path.exists():
        raise ValueError(
            "--resume found an unverified output without run_state.json; use --force."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(executable), "run", "steady", "--static", f"--config={config_path}"]
    stdout_path = output_path.parent / "stdout.log"
    stderr_path = output_path.parent / "stderr.log"
    started = time.time()
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        environment = os.environ.copy()
        if max_threads is not None:
            environment["GOMAXPROCS"] = str(max_threads)
        completed = subprocess.run(
            command,
            stdout=stdout,
            stderr=stderr,
            check=False,
            env=environment,
        )
    status = "complete" if completed.returncode == 0 and output_path.exists() else "failed"
    if completed.returncode < 0:
        status = "interrupted"
    state = {
        "scenario": job["scenario"],
        "year": job["year"],
        "run_key": run_key,
        "status": status,
        "returncode": completed.returncode,
        "command": command,
        "runtime_seconds": time.time() - started,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "output": str(output_path),
        "emission_files": [str(path) for path in emission_paths],
        "emission_dependency_sha256": {str(path): file_checksum(path) for path in dependencies},
        "cache_hit": False,
        "solver_mode": "automatic_convergence" if num_iterations == 0 else "fixed_iterations_poc",
        "num_iterations": num_iterations,
        "inmap_max_threads": max_threads,
        "converged": num_iterations == 0,
        "input_analytical_use_permitted": input_analytical_use_permitted,
        "analytical_use_permitted": num_iterations == 0 and input_analytical_use_permitted,
    }
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if state["status"] != "complete":
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        outcome = "was interrupted" if state["status"] == "interrupted" else "failed"
        raise RuntimeError(
            f"Global InMAP {outcome} for {job['scenario']} {job['year']} with "
            f"return code {completed.returncode}. stderr tail:\n{tail}"
        )
    return state
