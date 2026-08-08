"""Monitor-residual interpolation onto an InMAP concentration grid."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
import yaml

from nzk_aphiam.air_quality.monitor_aggregation import DEFAULT_ANNUAL_PARQUET
from nzk_aphiam.air_quality.monitor_qc import DEFAULT_CONFIG, _portable_path
from nzk_aphiam.config.paths import AIRKOREA_PROCESSED_DIR

DEFAULT_GRID_OUTPUT_DIR = AIRKOREA_PROCESSED_DIR / "inmap_bias_correction"


@dataclass(frozen=True)
class GridConfig:
    interpolation: str = "idw_monitor_residual"
    neighbor_count: int = 8
    power: float = 2.0
    max_distance_km: float = 250.0


def load_grid_config(path: Path = DEFAULT_CONFIG) -> GridConfig:
    settings = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = GridConfig(**settings.get("grid", {}))
    if config.interpolation != "idw_monitor_residual":
        raise ValueError("Only idw_monitor_residual interpolation is implemented")
    if config.neighbor_count < 1:
        raise ValueError("grid neighbor_count must be positive")
    if config.power <= 0:
        raise ValueError("grid IDW power must be positive")
    if config.max_distance_km <= 0:
        raise ValueError("grid max_distance_km must be positive")
    return config


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    frame.to_csv(partial, index=False, encoding="utf-8-sig")
    partial.replace(path)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    frame.to_parquet(partial, index=False)
    partial.replace(path)


def _atomic_gpkg(frame: gpd.GeoDataFrame, path: Path, layer: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.stem}.part.gpkg")
    partial.unlink(missing_ok=True)
    frame.to_file(partial, layer=layer, driver="GPKG")
    partial.replace(path)


def _ensure_total_pm25(grid: gpd.GeoDataFrame, model_column: str) -> gpd.GeoDataFrame:
    data = grid.copy()
    if model_column in data:
        data[model_column] = pd.to_numeric(data[model_column], errors="coerce")
        return data
    if model_column != "TotalPM25":
        raise ValueError(f"InMAP grid is missing model concentration column {model_column!r}")
    aliases = {
        "PrimaryPM25": ("PrimaryPM25", "PrimPM25", "PrimaryPM2"),
        "pSO4": ("pSO4",),
        "pNO3": ("pNO3",),
        "pNH4": ("pNH4",),
        "SOA": ("SOA",),
    }
    selected: list[str] = []
    for canonical, candidates in aliases.items():
        source = next((name for name in candidates if name in data), None)
        if source is None:
            raise ValueError(f"InMAP grid lacks {model_column} and component {canonical}")
        selected.append(source)
    data[model_column] = data[selected].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    return data


def monitor_grid_comparison(
    annual: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    *,
    year: int,
    pollutant: str = "PM25",
    observed_column: str = "annual_mean",
    model_column: str = "TotalPM25",
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Sample the model at monitors and return observed-minus-modeled residuals."""
    if grid.crs is None:
        raise ValueError("InMAP grid has no CRS metadata")
    grid = _ensure_total_pm25(grid, model_column).reset_index(names="grid_source_index")
    grid["grid_cell_id"] = grid["grid_source_index"].astype("string")
    selected = annual[
        annual["reporting_year"].eq(year)
        & annual["pollutant"].eq(pollutant)
        & annual["analysis_ready"].astype(bool)
    ].copy()
    selected[observed_column] = pd.to_numeric(selected[observed_column], errors="coerce")
    selected["latitude"] = pd.to_numeric(selected["latitude"], errors="coerce")
    selected["longitude"] = pd.to_numeric(selected["longitude"], errors="coerce")
    selected = selected.dropna(subset=[observed_column, "latitude", "longitude"]).reset_index(
        drop=True
    )
    if selected.empty:
        raise ValueError(
            f"No analysis-ready {pollutant} monitor observations with coordinates for {year}"
        )
    selected["monitor_record_id"] = selected.index.astype("Int64")
    points = gpd.GeoDataFrame(
        selected,
        geometry=gpd.points_from_xy(selected["longitude"], selected["latitude"]),
        crs="EPSG:4326",
    ).to_crs(grid.crs)
    joined = gpd.sjoin(
        points,
        grid[["grid_cell_id", model_column, "geometry"]],
        how="left",
        predicate="intersects",
    )
    joined = (
        joined.sort_values(["monitor_record_id", "grid_cell_id"], kind="stable")
        .drop_duplicates("monitor_record_id")
        .drop(columns=["index_right"], errors="ignore")
    )
    joined = joined.dropna(subset=[model_column]).copy()
    if joined.empty:
        raise ValueError("No AirKorea monitor falls within a usable InMAP grid cell")
    joined["observed_pm25_ugm3"] = joined[observed_column]
    joined["modeled_pm25_ugm3"] = joined[model_column]
    joined["monitor_bias_ugm3"] = joined["observed_pm25_ugm3"] - joined["modeled_pm25_ugm3"]
    comparison = pd.DataFrame(joined.drop(columns="geometry"))
    return comparison, grid


def _idw_values(
    source_xy: np.ndarray,
    source_values: np.ndarray,
    target_xy: np.ndarray,
    config: GridConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    tree = cKDTree(source_xy)
    neighbor_count = min(config.neighbor_count, len(source_xy))
    distances, indices = tree.query(target_xy, k=neighbor_count)
    if neighbor_count == 1:
        distances = distances[:, None]
        indices = indices[:, None]
    allowed = distances <= config.max_distance_km * 1000
    estimates = np.full(len(target_xy), np.nan)
    uncertainty = np.full(len(target_xy), np.nan)
    nearest_km = np.full(len(target_xy), np.nan)
    counts = allowed.sum(axis=1).astype(int)
    for row in range(len(target_xy)):
        mask = allowed[row]
        if not mask.any():
            continue
        local_distances = distances[row, mask]
        local_values = source_values[indices[row, mask]]
        nearest_km[row] = float(local_distances.min() / 1000)
        zero = local_distances == 0
        if zero.any():
            values = local_values[zero]
            estimates[row] = float(values.mean())
            uncertainty[row] = float(values.std(ddof=0))
            continue
        weights = 1 / np.power(local_distances, config.power)
        estimate = float(np.average(local_values, weights=weights))
        estimates[row] = estimate
        uncertainty[row] = float(
            np.sqrt(np.average(np.square(local_values - estimate), weights=weights))
        )
    return estimates, uncertainty, nearest_km, counts


def interpolate_monitor_bias(
    comparison: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    config: GridConfig,
    *,
    model_column: str = "TotalPM25",
) -> gpd.GeoDataFrame:
    """Interpolate monitor residuals to grid centroids using Korea-projected IDW."""
    monitor_points = gpd.GeoDataFrame(
        comparison.copy(),
        geometry=gpd.points_from_xy(
            comparison["longitude"],
            comparison["latitude"],
        ),
        crs="EPSG:4326",
    ).to_crs("EPSG:5179")
    projected_grid = grid.to_crs("EPSG:5179")
    centroids = projected_grid.geometry.centroid
    source_xy = np.column_stack(
        [monitor_points.geometry.x.to_numpy(), monitor_points.geometry.y.to_numpy()]
    )
    target_xy = np.column_stack([centroids.x.to_numpy(), centroids.y.to_numpy()])
    estimates, uncertainty, nearest_km, counts = _idw_values(
        source_xy,
        comparison["monitor_bias_ugm3"].to_numpy(dtype=float),
        target_xy,
        config,
    )
    result = grid.copy()
    result["bias_correction_ugm3"] = estimates
    result["bias_uncertainty_ugm3"] = uncertainty
    result["nearest_monitor_km"] = nearest_km
    result["interpolation_monitor_count"] = counts
    result["corrected_pm25_unbounded_ugm3"] = result[model_column] + result["bias_correction_ugm3"]
    result["correction_floor_applied"] = result["corrected_pm25_unbounded_ugm3"].lt(0)
    result["corrected_pm25_ugm3"] = result["corrected_pm25_unbounded_ugm3"].clip(lower=0)
    result["bias_interpolation_method"] = config.interpolation
    return result


def _leave_one_out_diagnostics(
    comparison: pd.DataFrame,
    config: GridConfig,
) -> dict[str, float | int | None]:
    raw_bias = comparison["monitor_bias_ugm3"].to_numpy(dtype=float)
    diagnostics: dict[str, float | int | None] = {
        "monitor_count": len(comparison),
        "uncorrected_mean_bias_ugm3": float(raw_bias.mean()),
        "uncorrected_rmse_ugm3": float(np.sqrt(np.mean(np.square(raw_bias)))),
        "leave_one_out_corrected_rmse_ugm3": None,
    }
    if len(comparison) < 2:
        return diagnostics
    points = gpd.GeoSeries(
        gpd.points_from_xy(comparison["longitude"], comparison["latitude"]),
        crs="EPSG:4326",
    ).to_crs("EPSG:5179")
    xy = np.column_stack([points.x.to_numpy(), points.y.to_numpy()])
    predicted = np.full(len(comparison), np.nan)
    for index in range(len(comparison)):
        mask = np.arange(len(comparison)) != index
        estimate, _, _, _ = _idw_values(
            xy[mask],
            raw_bias[mask],
            xy[index : index + 1],
            config,
        )
        predicted[index] = estimate[0]
    valid = np.isfinite(predicted)
    if valid.any():
        residual = raw_bias[valid] - predicted[valid]
        diagnostics["leave_one_out_corrected_rmse_ugm3"] = float(
            np.sqrt(np.mean(np.square(residual)))
        )
    return diagnostics


def build_inmap_bias_grid(
    *,
    annual_path: Path = DEFAULT_ANNUAL_PARQUET,
    inmap_grid_path: Path,
    year: int,
    output_dir: Path = DEFAULT_GRID_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG,
    pollutant: str = "PM25",
    observed_column: str = "annual_mean",
    model_column: str = "TotalPM25",
) -> Path:
    """Build a year-specific observed-minus-modeled InMAP correction grid."""
    if not annual_path.exists():
        raise FileNotFoundError(
            f"Annual AirKorea monitor dataset is absent: {annual_path}; "
            "run the aggregate stage first"
        )
    if not inmap_grid_path.exists():
        raise FileNotFoundError(f"InMAP grid is absent: {inmap_grid_path}")
    annual = pd.read_parquet(annual_path)
    grid = gpd.read_file(inmap_grid_path)
    comparison, prepared_grid = monitor_grid_comparison(
        annual,
        grid,
        year=year,
        pollutant=pollutant,
        observed_column=observed_column,
        model_column=model_column,
    )
    config = load_grid_config(config_path)
    corrected = interpolate_monitor_bias(
        comparison,
        prepared_grid,
        config,
        model_column=model_column,
    )
    corrected["bias_correction_year"] = year
    corrected["monitor_pollutant"] = pollutant

    year_dir = output_dir / f"year={year}"
    gpkg_path = year_dir / "inmap_pm25_bias_corrected.gpkg"
    comparison_parquet = year_dir / "monitor_model_comparison.parquet"
    comparison_csv = year_dir / "monitor_model_comparison.csv"
    metadata_path = year_dir / "manifest.json"
    _atomic_gpkg(corrected, gpkg_path, "pm25_bias_corrected")
    _atomic_parquet(comparison, comparison_parquet)
    _atomic_csv(comparison, comparison_csv)
    diagnostics = _leave_one_out_diagnostics(comparison, config)
    payload = {
        "dataset": "AirKorea monitor-residual InMAP PM2.5 bias correction",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "pollutant": pollutant,
        "observed_column": observed_column,
        "model_column": model_column,
        "inmap_grid": _portable_path(inmap_grid_path),
        "annual_monitor_data": _portable_path(annual_path),
        "output_grid": _portable_path(gpkg_path),
        "monitor_comparison": _portable_path(comparison_parquet),
        "interpolation": {
            "method": config.interpolation,
            "neighbor_count": config.neighbor_count,
            "power": config.power,
            "max_distance_km": config.max_distance_km,
            "projected_crs": "EPSG:5179",
            "interpolated_quantity": "observed_minus_modeled_monitor_residual",
        },
        "diagnostics": diagnostics,
        "grid_cells": len(corrected),
        "grid_cells_with_correction": int(corrected["bias_correction_ugm3"].notna().sum()),
        "negative_floor_count": int(corrected["correction_floor_applied"].sum()),
    }
    _atomic_json(metadata_path, payload)
    return metadata_path
