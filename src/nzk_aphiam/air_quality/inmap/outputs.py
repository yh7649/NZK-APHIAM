"""Global InMAP component validation and scenario differencing."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np

COMPONENTS = ["PrimaryPM25", "pSO4", "pNO3", "pNH4", "SOA"]


def read_output(path: Path) -> gpd.GeoDataFrame:
    data = gpd.read_file(path)
    # ESRI Shapefile DBF names are limited to ten characters. Generated real-run
    # configs request PrimPM25; PrimaryPM2 supports older/truncated test outputs.
    primary_alias = next(
        (name for name in ["PrimPM25", "PrimaryPM2"] if name in data.columns), None
    )
    if "PrimaryPM25" not in data and primary_alias:
        data = data.rename(columns={primary_alias: "PrimaryPM25"})
    missing = [column for column in COMPONENTS if column not in data.columns]
    if missing:
        raise ValueError(f"{path} is missing InMAP components: {missing}")
    calculated = data[COMPONENTS].sum(axis=1)
    if "TotalPM25" in data:
        if not np.allclose(data["TotalPM25"], calculated, rtol=1e-6, atol=1e-10):
            raise ValueError("InMAP TotalPM25 does not equal the requested component sum.")
    else:
        data["TotalPM25"] = calculated
    if "TotalPop" not in data.columns:
        raise ValueError(
            "Global InMAP output has no TotalPop field; uniform population is forbidden."
        )
    if data.crs is None:
        raise ValueError("Global InMAP output has no CRS metadata.")
    return data


def difference_outputs(
    reference_path: Path,
    policy_path: Path,
    destination: Path,
) -> gpd.GeoDataFrame:
    """Calculate reference minus policy; positive values mean cleaner policy air."""
    reference = read_output(reference_path)
    policy = read_output(policy_path)
    if len(reference) != len(policy) or reference.crs != policy.crs:
        raise ValueError("Scenario output grids or coordinate reference systems differ.")
    if not reference.geometry.geom_equals(policy.geometry).all():
        raise ValueError("Scenario output geometries differ; positional subtraction is unsafe.")
    difference = reference[["geometry", "TotalPop"]].copy()
    for component in [*COMPONENTS, "TotalPM25"]:
        difference[f"delta_{component}"] = reference[component] - policy[component]
    difference["sign_convention"] = "reference_minus_policy_positive_is_cleaner"
    destination.parent.mkdir(parents=True, exist_ok=True)
    difference.to_file(destination, layer="concentration_difference", driver="GPKG")
    return difference
