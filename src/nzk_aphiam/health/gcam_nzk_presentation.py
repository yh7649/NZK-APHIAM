"""Create presentation maps, component charts, GIFs, and MP4s from GCAM-NZK InMAP."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import warnings

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from PIL import Image

matplotlib.use("Agg")
from matplotlib.colors import Normalize, TwoSlopeNorm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from nzk_aphiam.air_quality.inmap.combined_runner import load_run_jobs
from nzk_aphiam.air_quality.inmap.exposure import install_national_boundary
from nzk_aphiam.config.paths import PROJECT_ROOT
from nzk_aphiam.health.combined_report import (
    SCENARIO_ALIASES,
    SCENARIO_LABELS,
)
from nzk_aphiam.mvp.peng_replication.config import load_config

KOREA_BBOX = (122.5, 32.0, 135.0, 40.0)
MAP_BOUNDS = (124.0, 132.0, 32.5, 39.5)
COMPONENTS = ("PrimPM25", "pSO4", "pNO3", "pNH4", "SOA")
COMPONENT_LABELS = {
    "PrimPM25": "Primary PM₂.₅",
    "pSO4": "Sulfate",
    "pNO3": "Nitrate",
    "pNH4": "Ammonium",
    "SOA": "Secondary organic aerosol",
}
SCENARIO_ORDER = ("no_nzk", "nzk_low", "nzk_high")
WARNING_TEXT = (
    "50-iteration maximum-coverage POC · proxy EFs and monitor-centroid locations · "
    "not for inference"
)


def _scenario_name(value: object) -> str:
    text = str(value)
    return SCENARIO_ALIASES.get(text, text)


def _korea_boundary(config_path: Path) -> gpd.GeoDataFrame:
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
    missing = sorted({"TotalPM25", "TotalPop", *COMPONENTS} - set(frame.columns))
    if missing:
        raise ValueError(f"{path} is missing InMAP fields: {missing}")
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Geometry is in a geographic CRS",
        )
        centroids = frame.geometry.centroid
    mask = centroids.within(boundary.geometry.union_all())
    frame = frame.loc[mask].copy()
    selected_centroids = centroids.loc[mask]
    frame["cell_id"] = [
        f"{longitude:.5f}_{latitude:.5f}"
        for longitude, latitude in zip(
            selected_centroids.x,
            selected_centroids.y,
            strict=True,
        )
    ]
    if frame.empty:
        raise ValueError(f"{path} has no InMAP cells assigned to South Korea.")
    return frame.reset_index(drop=True)


def load_presentation_grids(
    job_manifest_path: Path,
    boundary: gpd.GeoDataFrame,
) -> tuple[dict[tuple[str, int], gpd.GeoDataFrame], pd.DataFrame]:
    """Load all completed Korea grids and calculate population-weighted components."""
    _executable, jobs, _manifest = load_run_jobs(job_manifest_path)
    grids: dict[tuple[str, int], gpd.GeoDataFrame] = {}
    summary_rows: list[dict[str, object]] = []
    for job in jobs:
        output = Path(job["output"])
        state_path = output.parent / "run_state.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"Missing completed run state: {state_path}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") != "complete" or not output.is_file():
            raise ValueError(f"Incomplete InMAP output: {output}")
        scenario = _scenario_name(job["scenario"])
        year = int(job["year"])
        frame = _load_korea_output(output, boundary)
        grids[(scenario, year)] = frame
        population = pd.to_numeric(frame["TotalPop"], errors="coerce").fillna(0.0)
        population_total = float(population.sum())
        if population_total <= 0:
            raise ValueError(f"Korean InMAP population is not positive for {scenario} {year}.")
        row: dict[str, object] = {
            "scenario": scenario,
            "year": year,
            "represented_population": population_total,
            "grid_cell_count": int(len(frame)),
        }
        for component in ("TotalPM25", *COMPONENTS):
            concentration = pd.to_numeric(frame[component], errors="coerce").fillna(0.0)
            row[f"{component}_population_weighted_ugm3"] = float(
                np.average(concentration, weights=population)
            )
        summary_rows.append(row)
    expected = {
        (scenario, year)
        for scenario in SCENARIO_ORDER
        for year in (2025, 2030, 2035, 2040, 2045, 2050)
    }
    missing = sorted(expected - set(grids))
    if missing:
        raise ValueError(f"Presentation grids are missing scenario-years: {missing}")
    return grids, pd.DataFrame(summary_rows).sort_values(["scenario", "year"])


def _style_map_axis(axis: plt.Axes, boundary: gpd.GeoDataFrame) -> None:
    boundary.boundary.plot(ax=axis, color="#101828", linewidth=0.8, zorder=5)
    axis.set_xlim(MAP_BOUNDS[0], MAP_BOUNDS[1])
    axis.set_ylim(MAP_BOUNDS[2], MAP_BOUNDS[3])
    axis.set_aspect("equal")
    axis.set_axis_off()


def _add_footer(figure: plt.Figure, text: str = WARNING_TEXT) -> None:
    figure.text(0.025, 0.018, text, color="#667085", fontsize=8.5)


def _save_figure(figure: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def plot_2050_scenario_maps(
    grids: dict[tuple[str, int], gpd.GeoDataFrame],
    boundary: gpd.GeoDataFrame,
    path: Path,
) -> None:
    frames = [grids[(scenario, 2050)] for scenario in SCENARIO_ORDER]
    values = np.concatenate(
        [pd.to_numeric(frame["TotalPM25"], errors="coerce").to_numpy() for frame in frames]
    )
    upper = float(np.nanquantile(values, 0.995))
    normalization = Normalize(vmin=0.0, vmax=upper)
    figure, axes = plt.subplots(1, 3, figsize=(14.2, 6.4))
    figure.subplots_adjust(left=0.02, right=0.91, top=0.81, bottom=0.08, wspace=0.02)
    for axis, scenario, frame in zip(axes, SCENARIO_ORDER, frames, strict=True):
        frame.plot(
            column="TotalPM25",
            ax=axis,
            cmap="magma_r",
            norm=normalization,
            linewidth=0,
        )
        _style_map_axis(axis, boundary)
        axis.set_title(SCENARIO_LABELS[scenario], fontsize=13, color="#101828", pad=6)
    color_axis = figure.add_axes((0.925, 0.19, 0.014, 0.48))
    colorbar = figure.colorbar(
        plt.cm.ScalarMappable(norm=normalization, cmap="magma_r"),
        cax=color_axis,
    )
    colorbar.set_label("Annual PM₂.₅ contribution (µg/m³)", color="#344054")
    figure.suptitle(
        "Where modeled PM₂.₅ is concentrated in 2050",
        x=0.025,
        y=0.96,
        ha="left",
        fontsize=20,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.025,
        0.885,
        "Shared scale across all three power pathways; color capped at the 99.5th percentile",
        color="#667085",
        fontsize=10.5,
    )
    _add_footer(figure)
    _save_figure(figure, path)


def _difference_frame(
    reference: gpd.GeoDataFrame,
    policy: gpd.GeoDataFrame,
    *,
    column: str = "TotalPM25",
) -> gpd.GeoDataFrame:
    joined = reference[["cell_id", column, "geometry"]].merge(
        policy[["cell_id", column]],
        on="cell_id",
        how="inner",
        validate="one_to_one",
        suffixes=("_reference", "_policy"),
    )
    joined["reduction"] = joined[f"{column}_reference"] - joined[f"{column}_policy"]
    return gpd.GeoDataFrame(joined, geometry="geometry", crs=reference.crs)


def plot_2050_reduction_maps(
    grids: dict[tuple[str, int], gpd.GeoDataFrame],
    boundary: gpd.GeoDataFrame,
    path: Path,
) -> None:
    differences = [
        _difference_frame(grids[("no_nzk", 2050)], grids[(scenario, 2050)])
        for scenario in ("nzk_low", "nzk_high")
    ]
    absolute = np.concatenate(
        [np.abs(frame["reduction"].to_numpy(dtype=float)) for frame in differences]
    )
    limit = max(float(np.nanquantile(absolute, 0.995)), 1e-8)
    normalization = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)
    figure, axes = plt.subplots(1, 2, figsize=(10.8, 6.4))
    figure.subplots_adjust(left=0.03, right=0.89, top=0.81, bottom=0.08, wspace=0.02)
    for axis, scenario, frame in zip(axes, ("nzk_low", "nzk_high"), differences, strict=True):
        frame.plot(
            column="reduction",
            ax=axis,
            cmap="RdBu",
            norm=normalization,
            linewidth=0,
        )
        _style_map_axis(axis, boundary)
        axis.set_title(
            f"No NZK − {SCENARIO_LABELS[scenario]}",
            fontsize=13,
            color="#101828",
            pad=6,
        )
    color_axis = figure.add_axes((0.91, 0.19, 0.017, 0.48))
    colorbar = figure.colorbar(
        plt.cm.ScalarMappable(norm=normalization, cmap="RdBu"),
        cax=color_axis,
    )
    colorbar.set_label("PM₂.₅ reduction (µg/m³); blue is cleaner", color="#344054")
    figure.suptitle(
        "The power-pathway signal is small relative to shared non-power emissions",
        x=0.03,
        y=0.96,
        ha="left",
        fontsize=19,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.03,
        0.885,
        "2050 concentration difference; symmetric scale capped at the 99.5th percentile",
        color="#667085",
        fontsize=10.5,
    )
    _add_footer(figure)
    _save_figure(figure, path)


def plot_component_maps(
    grids: dict[tuple[str, int], gpd.GeoDataFrame],
    boundary: gpd.GeoDataFrame,
    path: Path,
) -> None:
    frame = grids[("nzk_high", 2050)]
    figure, axes = plt.subplots(2, 3, figsize=(13.6, 8.2))
    figure.subplots_adjust(left=0.03, right=0.92, top=0.83, bottom=0.08, wspace=0.04)
    for axis, component in zip(axes.flat, COMPONENTS, strict=False):
        upper = max(float(frame[component].quantile(0.995)), 1e-8)
        normalization = Normalize(vmin=0.0, vmax=upper)
        frame.plot(
            column=component,
            ax=axis,
            cmap="viridis",
            norm=normalization,
            linewidth=0,
        )
        _style_map_axis(axis, boundary)
        axis.set_title(COMPONENT_LABELS[component], fontsize=12, color="#101828")
        colorbar = figure.colorbar(
            plt.cm.ScalarMappable(norm=normalization, cmap="viridis"),
            ax=axis,
            fraction=0.035,
            pad=0.01,
        )
        colorbar.ax.tick_params(labelsize=7)
    axes.flat[-1].set_axis_off()
    figure.suptitle(
        "What makes up modeled PM₂.₅ under NZK high in 2050",
        x=0.03,
        y=0.96,
        ha="left",
        fontsize=20,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.03,
        0.89,
        "Each component uses its own scale; concentrations in µg/m³",
        color="#667085",
        fontsize=10.5,
    )
    _add_footer(figure)
    _save_figure(figure, path)


def plot_component_trajectories(summary: pd.DataFrame, path: Path) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(14.6, 5.8), sharey=True)
    figure.subplots_adjust(left=0.07, right=0.985, top=0.77, bottom=0.17, wspace=0.08)
    colors = ["#B35C1E", "#7451A6", "#2E6FBB", "#0F9D8A", "#E39B22"]
    for axis, scenario in zip(axes, SCENARIO_ORDER, strict=True):
        frame = summary.loc[summary["scenario"].eq(scenario)].sort_values("year")
        values = [
            frame[f"{component}_population_weighted_ugm3"].to_numpy(dtype=float)
            for component in COMPONENTS
        ]
        axis.stackplot(
            frame["year"],
            *values,
            labels=[COMPONENT_LABELS[component] for component in COMPONENTS],
            colors=colors,
            alpha=0.92,
        )
        axis.set_title(SCENARIO_LABELS[scenario], color="#101828")
        axis.set_xlabel("Scenario year")
        axis.set_xticks(frame["year"])
        axis.tick_params(axis="x", rotation=45)
        axis.grid(axis="y", color="#D9DEE7", linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Population-weighted PM₂.₅ component (µg/m³)")
    axes[-1].legend(
        frameon=False,
        fontsize=8.5,
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
    )
    figure.suptitle(
        "Secondary nitrate dominates the modeled source contribution",
        x=0.07,
        y=0.96,
        ha="left",
        fontsize=20,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.07,
        0.875,
        "Population-weighted concentration components; areas are additive",
        color="#667085",
        fontsize=10.5,
    )
    _add_footer(figure)
    _save_figure(figure, path)


def _render_pathway_frame(
    grids: dict[tuple[str, int], gpd.GeoDataFrame],
    boundary: gpd.GeoDataFrame,
    year: int,
    normalization: Normalize,
    path: Path,
) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(12.8, 7.2))
    figure.subplots_adjust(left=0.02, right=0.9, top=0.81, bottom=0.08, wspace=0.02)
    for axis, scenario in zip(axes, SCENARIO_ORDER, strict=True):
        grids[(scenario, year)].plot(
            column="TotalPM25",
            ax=axis,
            cmap="magma_r",
            norm=normalization,
            linewidth=0,
        )
        _style_map_axis(axis, boundary)
        axis.set_title(SCENARIO_LABELS[scenario], fontsize=14, color="#101828")
    color_axis = figure.add_axes((0.92, 0.18, 0.015, 0.5))
    colorbar = figure.colorbar(
        plt.cm.ScalarMappable(norm=normalization, cmap="magma_r"),
        cax=color_axis,
    )
    colorbar.set_label("Annual PM₂.₅ contribution (µg/m³)")
    figure.suptitle(
        f"Modeled PM₂.₅ across Korea · {year}",
        x=0.025,
        y=0.96,
        ha="left",
        fontsize=22,
        fontweight="bold",
        color="#101828",
    )
    figure.text(
        0.025,
        0.885,
        "Steady-state annual concentration—not a time-resolved plume",
        color="#667085",
        fontsize=11,
    )
    _add_footer(figure)
    _save_figure(figure, path)


def _render_component_build_frame(
    frame: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    components: tuple[str, ...],
    normalization: Normalize,
    path: Path,
) -> None:
    data = frame.copy()
    data["cumulative"] = data[list(components)].sum(axis=1)
    figure, axis = plt.subplots(figsize=(12.8, 7.2))
    figure.subplots_adjust(left=0.1, right=0.82, top=0.8, bottom=0.08)
    data.plot(
        column="cumulative",
        ax=axis,
        cmap="magma_r",
        norm=normalization,
        linewidth=0,
    )
    _style_map_axis(axis, boundary)
    color_axis = figure.add_axes((0.84, 0.19, 0.018, 0.48))
    colorbar = figure.colorbar(
        plt.cm.ScalarMappable(norm=normalization, cmap="magma_r"),
        cax=color_axis,
    )
    colorbar.set_label("Cumulative PM₂.₅ component (µg/m³)")
    labels = " + ".join(COMPONENT_LABELS[component] for component in components)
    figure.suptitle(
        "How InMAP components build the 2050 PM₂.₅ field",
        x=0.06,
        y=0.96,
        ha="left",
        fontsize=22,
        fontweight="bold",
        color="#101828",
    )
    figure.text(0.06, 0.87, labels, color="#344054", fontsize=11)
    figure.text(
        0.06,
        0.82,
        "Illustrative component build-up—not pollutant movement through time",
        color="#B54708",
        fontsize=10.5,
    )
    _add_footer(figure)
    _save_figure(figure, path)


def _write_gif(frame_paths: list[Path], path: Path, *, duration_ms: int) -> None:
    images = [Image.open(frame).convert("RGB") for frame in frame_paths]
    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )
    for image in images:
        image.close()


def _write_mp4(frame_directory: Path, path: Path, *, seconds_per_frame: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FileNotFoundError("ffmpeg is required to create MP4 animations.")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_rate = 1.0 / seconds_per_frame
    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        f"{frame_rate:.6f}",
        "-i",
        str(frame_directory / "frame_%02d.png"),
        "-vf",
        "scale=1600:-2:flags=lanczos,format=yuv420p",
        "-r",
        "30",
        "-movflags",
        "+faststart",
        str(path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to create {path}: {completed.stderr[-2000:]}")


def build_animations(
    grids: dict[tuple[str, int], gpd.GeoDataFrame],
    boundary: gpd.GeoDataFrame,
    output_dir: Path,
) -> dict[str, Path]:
    values = np.concatenate([frame["TotalPM25"].to_numpy(dtype=float) for frame in grids.values()])
    normalization = Normalize(vmin=0.0, vmax=float(np.nanquantile(values, 0.995)))
    pathway_frames = output_dir / "frames" / "pm25_pathways"
    pathway_frames.mkdir(parents=True, exist_ok=True)
    years = (2025, 2030, 2035, 2040, 2045, 2050)
    pathway_paths: list[Path] = []
    for index, year in enumerate(years):
        path = pathway_frames / f"frame_{index:02d}.png"
        _render_pathway_frame(grids, boundary, year, normalization, path)
        pathway_paths.append(path)

    high_2050 = grids[("nzk_high", 2050)]
    cumulative = high_2050[list(COMPONENTS)].sum(axis=1)
    component_normalization = Normalize(
        vmin=0.0,
        vmax=float(np.nanquantile(cumulative.to_numpy(dtype=float), 0.995)),
    )
    component_frames = output_dir / "frames" / "component_build"
    component_frames.mkdir(parents=True, exist_ok=True)
    component_paths: list[Path] = []
    for index in range(1, len(COMPONENTS) + 1):
        path = component_frames / f"frame_{index - 1:02d}.png"
        _render_component_build_frame(
            high_2050,
            boundary,
            COMPONENTS[:index],
            component_normalization,
            path,
        )
        component_paths.append(path)

    outputs = {
        "pm25_pathways_gif": output_dir / "korea_pm25_pathways_2025_2050.gif",
        "pm25_pathways_mp4": output_dir / "korea_pm25_pathways_2025_2050.mp4",
        "component_build_gif": output_dir / "inmap_pm25_component_build_2050.gif",
        "component_build_mp4": output_dir / "inmap_pm25_component_build_2050.mp4",
    }
    _write_gif(pathway_paths, outputs["pm25_pathways_gif"], duration_ms=1400)
    _write_mp4(pathway_frames, outputs["pm25_pathways_mp4"], seconds_per_frame=1.4)
    _write_gif(component_paths, outputs["component_build_gif"], duration_ms=1600)
    _write_mp4(component_frames, outputs["component_build_mp4"], seconds_per_frame=1.6)
    return outputs


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return path.name


def write_presentation_package(
    *,
    job_manifest_path: Path,
    config_path: Path,
    figure_dir: Path,
    video_dir: Path,
    table_dir: Path,
) -> Path:
    boundary = _korea_boundary(config_path)
    grids, component_summary = load_presentation_grids(job_manifest_path, boundary)
    table_dir.mkdir(parents=True, exist_ok=True)
    component_path = table_dir / "inmap_pm25_component_summary.csv"
    component_summary.to_csv(component_path, index=False)
    figures = {
        "scenario_maps_2050": figure_dir / "korea_pm25_scenarios_2050.png",
        "reduction_maps_2050": figure_dir / "korea_pm25_reduction_2050.png",
        "component_maps_2050": figure_dir / "korea_pm25_components_2050.png",
        "component_trajectories": figure_dir / "pm25_component_trajectories.png",
    }
    plot_2050_scenario_maps(grids, boundary, figures["scenario_maps_2050"])
    plot_2050_reduction_maps(grids, boundary, figures["reduction_maps_2050"])
    plot_component_maps(grids, boundary, figures["component_maps_2050"])
    plot_component_trajectories(component_summary, figures["component_trajectories"])
    videos = build_animations(grids, boundary, video_dir)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "job_manifest": _portable_path(job_manifest_path),
        "result_status": "50_iteration_maximum_coverage_poc_not_for_inference",
        "analytical_use_permitted": False,
        "animation_note": (
            "Animations show annual steady-state scenario fields or an illustrative "
            "component build-up; neither represents time-resolved pollutant transport."
        ),
        "figures": {key: _portable_path(path) for key, path in figures.items()},
        "videos": {key: _portable_path(path) for key, path in videos.items()},
        "tables": {"component_summary": _portable_path(component_path)},
    }
    manifest_path = table_dir / "gcam_nzk_presentation_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    parser.add_argument("--video-dir", type=Path, required=True)
    parser.add_argument("--table-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = write_presentation_package(
        job_manifest_path=args.job_manifest.resolve(),
        config_path=args.config.resolve(),
        figure_dir=args.figure_dir.resolve(),
        video_dir=args.video_dir.resolve(),
        table_dir=args.table_dir.resolve(),
    )
    print(f"Wrote GCAM-NZK presentation package: {manifest}")


if __name__ == "__main__":
    main()
