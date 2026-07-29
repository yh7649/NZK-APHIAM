"""South-Korea-only population-weighted exposure from real InMAP output."""

from __future__ import annotations

from pathlib import Path
import shutil
from urllib.request import Request, urlopen
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd


def _korean_cells(
    data: gpd.GeoDataFrame, boundary_path: Path, country_iso_a3: str
) -> gpd.GeoDataFrame:
    countries = gpd.read_file(boundary_path)
    iso_column = next(
        (column for column in ["ISO_A3", "ADM0_A3", "SOV_A3"] if column in countries), None
    )
    if iso_column is None:
        raise ValueError("National boundary has no recognized ISO-A3 column.")
    korea = countries.loc[countries[iso_column].eq(country_iso_a3)]
    if len(korea) != 1:
        raise ValueError(f"Boundary selection for {country_iso_a3} returned {len(korea)} rows.")
    cells = data.to_crs(korea.crs)
    projected_centroids = cells.to_crs("EPSG:6933").geometry.centroid
    centroids = gpd.GeoSeries(projected_centroids, crs="EPSG:6933").to_crs(korea.crs)
    selected = cells.loc[centroids.within(korea.geometry.iloc[0])].copy()
    if selected.empty:
        raise ValueError("No Korean cells appeared in the Global InMAP output.")
    return selected


def install_national_boundary(cache_path: Path, url: str) -> Path:
    archive = cache_path / "boundaries" / "ne_10m_admin_0_countries.zip"
    destination = cache_path / "boundaries" / "natural_earth_10m_admin0"
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": "NZK-APHIAM/0.2 exposure adapter"})
        with urlopen(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    if not destination.exists():
        destination.mkdir(parents=True, exist_ok=True)
        with ZipFile(archive) as zip_file:
            zip_file.extractall(destination)
    candidates = sorted(destination.rglob("*.shp"))
    if len(candidates) != 1:
        raise FileNotFoundError(f"Expected one Natural Earth shapefile in {destination}.")
    return candidates[0]


def national_population_weighted_exposure(
    difference: gpd.GeoDataFrame,
    boundary_path: Path,
    *,
    country_iso_a3: str = "KOR",
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Filter by cell centroid and calculate the mandatory national statistic."""
    selected = _korean_cells(difference, boundary_path, country_iso_a3)
    population = pd.to_numeric(selected["TotalPop"], errors="coerce")
    delta = pd.to_numeric(selected["delta_TotalPM25"], errors="coerce")
    valid = population.notna() & delta.notna() & (population >= 0)
    if not valid.any() or population.loc[valid].sum() <= 0:
        raise ValueError("Korean InMAP cells have no usable positive population.")
    values = delta.loc[valid]
    weights = population.loc[valid]
    summary = pd.DataFrame(
        [
            {
                "population_weighted_delta_pm25_ugm3": float(np.average(values, weights=weights)),
                "unweighted_mean_delta_pm25_ugm3": float(values.mean()),
                "median_delta_pm25_ugm3": float(values.median()),
                "minimum_delta_pm25_ugm3": float(values.min()),
                "maximum_delta_pm25_ugm3": float(values.max()),
                "represented_population": float(weights.sum()),
                "grid_cell_count": int(valid.sum()),
                "offshore_cells": "excluded_by_centroid",
                "foreign_cells": "excluded_by_national_boundary",
                "border_cells": "assigned_by_cell_centroid",
                "sign_convention": "reference_minus_policy_positive_is_cleaner",
            }
        ]
    )
    return summary, selected


def national_scenario_exposure(
    output: gpd.GeoDataFrame,
    boundary_path: Path,
    *,
    scenario: str,
    year: int,
    country_iso_a3: str = "KOR",
    concentration_scope: str = "incremental_modeled_source_contribution",
) -> pd.DataFrame:
    """Calculate a scenario's population-weighted PM2.5 over Korean cells.

    The generic concentration column supports either an all-source InMAP run or
    a source-contribution run. ``concentration_scope`` records which
    interpretation is valid; the legacy incremental column is retained for
    backward compatibility.
    """
    selected = _korean_cells(output, boundary_path, country_iso_a3)
    population = pd.to_numeric(selected["TotalPop"], errors="coerce")
    concentration = pd.to_numeric(selected["TotalPM25"], errors="coerce")
    valid = population.notna() & concentration.notna() & (population >= 0)
    if not valid.any() or population.loc[valid].sum() <= 0:
        raise ValueError("Korean InMAP cells have no usable positive population.")
    population_weighted = float(
        np.average(concentration.loc[valid], weights=population.loc[valid])
    )
    return pd.DataFrame(
        [
            {
                "scenario": scenario,
                "year": year,
                "population_weighted_pm25_ugm3": population_weighted,
                "population_weighted_incremental_pm25_ugm3": population_weighted,
                "concentration_scope": concentration_scope,
                "represented_population": float(population.loc[valid].sum()),
                "grid_cell_count": int(valid.sum()),
            }
        ]
    )
