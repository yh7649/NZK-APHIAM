"""Render Korea PM2.5 concentration maps for an arbitrary InMAP scenario comparison.

`gcam_nzk_presentation` is hardcoded to the three-pathway GCAM-NZK POC
(no_nzk/nzk_low/nzk_high across six years). This renders whatever scenario-years
are actually present in a run manifest, for smaller ad hoc comparisons such as
`gcam_reference_vs_nzk_poc_2025_2050`'s two-job, single-year bundle.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import warnings

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

from nzk_aphiam.air_quality.inmap.combined_runner import load_run_jobs
from nzk_aphiam.air_quality.inmap.exposure import install_national_boundary
from nzk_aphiam.config.paths import PROJECT_ROOT
from nzk_aphiam.mvp.peng_replication.config import load_config

matplotlib.use("Agg")
from matplotlib.colors import Normalize, TwoSlopeNorm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

KOREA_BBOX = (122.5, 32.0, 135.0, 40.0)
MAP_BOUNDS = (124.0, 132.0, 32.5, 39.5)
WARNING_TEXT = "Fixed-iteration POC diagnostic -- proxy inputs, not for inference"


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return path.name


def _scenario_label(scenario: str) -> str:
    return scenario.replace("_", " ").strip().title()


def korea_boundary(config_path: Path) -> gpd.GeoDataFrame:
    config = load_config(config_path)
    boundary_path = install_national_boundary(
        Path(config["inmap"]["cache_path"]),
        config["exposure"]["national_boundary_url"],
    )
    countries = gpd.read_file(boundary_path)
    korea = countries.loc[countries["ADM0_A3"].astype(str).eq("KOR")].copy()
    if korea.empty:
        raise ValueError(f"South Korea is absent from {boundary_path}.")
    return korea.to_crs("EPSG:4326")


def _load_korea_output(path: Path, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path, bbox=KOREA_BBOX).to_crs("EPSG:4326")
    if "TotalPM25" not in frame.columns:
        raise ValueError(f"{path} is missing the InMAP TotalPM25 field.")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")
        centroids = frame.geometry.centroid
    mask = centroids.within(boundary.geometry.union_all())
    frame = frame.loc[mask].copy()
    selected_centroids = centroids.loc[mask]
    frame["cell_id"] = [
        f"{longitude:.5f}_{latitude:.5f}"
        for longitude, latitude in zip(selected_centroids.x, selected_centroids.y, strict=True)
    ]
    if frame.empty:
        raise ValueError(f"{path} has no InMAP cells assigned to South Korea.")
    return frame.reset_index(drop=True)


def load_scenario_grids(
    job_manifest_path: Path,
    boundary: gpd.GeoDataFrame,
) -> dict[tuple[str, int], gpd.GeoDataFrame]:
    """Load every completed Korea-clipped InMAP output referenced by a run manifest."""
    _executable, jobs, _manifest = load_run_jobs(job_manifest_path)
    grids: dict[tuple[str, int], gpd.GeoDataFrame] = {}
    for job in jobs:
        output = Path(job["output"])
        state_path = output.parent / "run_state.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"Missing completed run state: {state_path}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") != "complete" or not output.is_file():
            raise ValueError(f"Incomplete InMAP output: {output}")
        grids[(str(job["scenario"]), int(job["year"]))] = _load_korea_output(output, boundary)
    if not grids:
        raise ValueError(f"{job_manifest_path} lists no completed jobs.")
    return grids


def _style_map_axis(axis: plt.Axes, boundary: gpd.GeoDataFrame) -> None:
    boundary.boundary.plot(ax=axis, color="#101828", linewidth=0.8, zorder=5)
    axis.set_xlim(MAP_BOUNDS[0], MAP_BOUNDS[1])
    axis.set_ylim(MAP_BOUNDS[2], MAP_BOUNDS[3])
    axis.set_aspect("equal")
    axis.set_axis_off()


def _save_figure(figure: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.text(0.015, 0.012, WARNING_TEXT, color="#667085", fontsize=8.5)
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def plot_scenario_concentration_maps(
    grids: dict[tuple[str, int], gpd.GeoDataFrame],
    boundary: gpd.GeoDataFrame,
    year: int,
    scenarios: list[str],
    path: Path,
) -> None:
    """One shared-scale PM2.5 concentration map per scenario, for one year."""
    frames = [grids[(scenario, year)] for scenario in scenarios]
    values = np.concatenate(
        [pd.to_numeric(frame["TotalPM25"], errors="coerce").to_numpy() for frame in frames]
    )
    upper = max(float(np.nanquantile(values, 0.995)), 1e-8)
    normalization = Normalize(vmin=0.0, vmax=upper)
    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios) + 1.4, 6.4))
    axes = np.atleast_1d(axes)
    figure.subplots_adjust(left=0.02, right=0.9, top=0.82, bottom=0.08, wspace=0.03)
    for axis, scenario, frame in zip(axes, scenarios, frames, strict=True):
        frame.plot(column="TotalPM25", ax=axis, cmap="magma_r", norm=normalization, linewidth=0)
        _style_map_axis(axis, boundary)
        axis.set_title(_scenario_label(scenario), fontsize=13, color="#101828", pad=6)
    color_axis = figure.add_axes((0.92, 0.19, 0.016, 0.5))
    colorbar = figure.colorbar(
        plt.cm.ScalarMappable(norm=normalization, cmap="magma_r"), cax=color_axis
    )
    colorbar.set_label("Modeled PM₂.₅ concentration (µg/m³)", color="#344054")
    figure.suptitle(
        f"Modeled PM₂.₅ across Korea · {year}",
        x=0.02,
        y=0.965,
        ha="left",
        fontsize=19,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.02,
        0.885,
        "Shared color scale across scenarios; capped at the 99.5th percentile",
        color="#667085",
        fontsize=10.5,
    )
    _save_figure(figure, path)


def _difference_frame(reference: gpd.GeoDataFrame, policy: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    joined = reference[["cell_id", "TotalPM25", "geometry"]].merge(
        policy[["cell_id", "TotalPM25"]],
        on="cell_id",
        how="inner",
        validate="one_to_one",
        suffixes=("_reference", "_policy"),
    )
    joined["reduction"] = joined["TotalPM25_reference"] - joined["TotalPM25_policy"]
    return gpd.GeoDataFrame(joined, geometry="geometry", crs=reference.crs)


def plot_scenario_reduction_maps(
    grids: dict[tuple[str, int], gpd.GeoDataFrame],
    boundary: gpd.GeoDataFrame,
    year: int,
    reference_scenario: str,
    policy_scenarios: list[str],
    path: Path,
) -> None:
    """Reference-minus-policy PM2.5 difference maps for one year."""
    reference = grids[(reference_scenario, year)]
    differences = [
        _difference_frame(reference, grids[(scenario, year)]) for scenario in policy_scenarios
    ]
    absolute = np.concatenate(
        [np.abs(frame["reduction"].to_numpy(dtype=float)) for frame in differences]
    )
    limit = max(float(np.nanquantile(absolute, 0.995)), 1e-8)
    normalization = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)
    figure, axes = plt.subplots(
        1, len(policy_scenarios), figsize=(5.4 * len(policy_scenarios) + 1.4, 6.4)
    )
    axes = np.atleast_1d(axes)
    figure.subplots_adjust(left=0.02, right=0.88, top=0.82, bottom=0.08, wspace=0.03)
    for axis, scenario, frame in zip(axes, policy_scenarios, differences, strict=True):
        frame.plot(column="reduction", ax=axis, cmap="RdBu", norm=normalization, linewidth=0)
        _style_map_axis(axis, boundary)
        axis.set_title(
            f"{_scenario_label(reference_scenario)} − {_scenario_label(scenario)}",
            fontsize=13,
            color="#101828",
            pad=6,
        )
    color_axis = figure.add_axes((0.9, 0.19, 0.018, 0.5))
    colorbar = figure.colorbar(
        plt.cm.ScalarMappable(norm=normalization, cmap="RdBu"), cax=color_axis
    )
    colorbar.set_label("PM₂.₅ reduction (µg/m³); blue is cleaner", color="#344054")
    figure.suptitle(
        f"Where PM₂.₅ changes most · {year}",
        x=0.02,
        y=0.965,
        ha="left",
        fontsize=19,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.02,
        0.885,
        "Concentration difference vs the reference scenario; symmetric scale capped at the "
        "99.5th percentile",
        color="#667085",
        fontsize=10.5,
    )
    _save_figure(figure, path)


def write_scenario_maps(
    *,
    job_manifest_path: Path,
    config_path: Path,
    figure_dir: Path,
    reference_scenario: str = "no_nzk",
) -> Path:
    """Write one concentration map and one reduction map per year in a run manifest."""
    boundary = korea_boundary(config_path)
    grids = load_scenario_grids(job_manifest_path, boundary)
    years = sorted({year for _scenario, year in grids})
    figure_dir.mkdir(parents=True, exist_ok=True)
    figures: dict[str, str] = {}
    for year in years:
        scenarios = sorted({scenario for scenario, grid_year in grids if grid_year == year})
        if len(scenarios) < 2:
            continue
        ordered = (
            [reference_scenario, *[s for s in scenarios if s != reference_scenario]]
            if reference_scenario in scenarios
            else scenarios
        )
        concentration_path = figure_dir / f"korea_pm25_concentration_{year}.png"
        plot_scenario_concentration_maps(grids, boundary, year, ordered, concentration_path)
        figures[f"concentration_{year}"] = _portable_path(concentration_path)
        if reference_scenario in scenarios:
            policy_scenarios = [s for s in scenarios if s != reference_scenario]
            reduction_path = figure_dir / f"korea_pm25_reduction_{year}.png"
            plot_scenario_reduction_maps(
                grids, boundary, year, reference_scenario, policy_scenarios, reduction_path
            )
            figures[f"reduction_{year}"] = _portable_path(reduction_path)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "job_manifest": _portable_path(job_manifest_path),
        "reference_scenario": reference_scenario,
        "years": years,
        "analytical_use_permitted": False,
        "figures": figures,
    }
    manifest_path = figure_dir / "scenario_pm25_maps_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    parser.add_argument("--reference-scenario", default="no_nzk")
    args = parser.parse_args()
    manifest = write_scenario_maps(
        job_manifest_path=args.job_manifest.resolve(),
        config_path=args.config.resolve(),
        figure_dir=args.figure_dir.resolve(),
        reference_scenario=args.reference_scenario,
    )
    print(f"Wrote scenario PM2.5 map manifest: {manifest}")


if __name__ == "__main__":
    main()
