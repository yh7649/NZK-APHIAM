"""Subprocess execution, logging, and cache checks for Global InMAP."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from nzk_aphiam.air_quality.inmap.installation import executable_version, file_checksum


def _run_key(executable: Path, config_path: Path, shapefile_path: Path) -> str:
    digest = sha256()
    digest.update(executable_version(executable).encode())
    for path in [config_path, *sorted(shapefile_path.parent.glob(f"{shapefile_path.stem}.*"))]:
        digest.update(path.name.encode())
        digest.update(file_checksum(path).encode())
    return digest.hexdigest()


def run_scenario(
    executable: Path,
    job: dict[str, Any],
    *,
    force: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    """Run one scenario or reuse a successful identical cached output."""
    config_path = Path(job["config"])
    output_path = Path(job["output"])
    shapefile_path = Path(job["shapefile"])
    state_path = output_path.parent / "run_state.json"
    run_key = _run_key(executable, config_path, shapefile_path)
    num_iterations = int(job.get("num_iterations", 0))
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
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
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
        "cache_hit": False,
        "solver_mode": "automatic_convergence" if num_iterations == 0 else "fixed_iterations_poc",
        "num_iterations": num_iterations,
        "converged": num_iterations == 0,
        "analytical_use_permitted": num_iterations == 0,
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
