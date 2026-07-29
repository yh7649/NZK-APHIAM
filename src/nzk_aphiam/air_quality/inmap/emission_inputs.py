"""Validation and scenario selection for supplemental InMAP emissions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.io import netcdf_file

POLLUTANT_FIELDS = ("VOC", "NOx", "NH3", "SOx", "PM2_5")
STACK_FIELDS = ("height", "diam", "temp", "velocity")
SHAPEFILE_UNITS = {"tons/year", "kg/year", "ug/s", "μg/s"}
COARDS_UNITS = {"tons", "tonnes", "kg", "g", "lbs"}
SUPPORTED_GEOMETRIES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
}
KOREA_BOUNDS = (124.0, 33.0, 132.0, 39.0)


def _scope_matches(value: object, target: str | int, field: str) -> bool:
    if value is None or value == "*":
        return True
    values: Sequence[object]
    if isinstance(value, (str, int)):
        values = [value]
    elif isinstance(value, Sequence):
        values = value
    else:
        raise ValueError(f"Supplemental emission {field} must be a value, list, or '*'.")
    if "*" in values:
        return True
    if isinstance(target, int):
        try:
            return target in [int(item) for item in values]
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Supplemental emission {field} must contain integer years."
            ) from error
    return target in [str(item) for item in values]


def _overlaps_korea(bounds: Sequence[float]) -> bool:
    west, south, east, north = [float(value) for value in bounds]
    korea_west, korea_south, korea_east, korea_north = KOREA_BOUNDS
    return not (
        east < korea_west or west > korea_east or north < korea_south or south > korea_north
    )


def validate_emissions_shapefile(path: Path) -> dict[str, Any]:
    """Validate an InMAP point, line, or polygon emissions shapefile."""
    path = Path(path)
    if path.suffix.lower() != ".shp":
        raise ValueError(f"Shapefile input must end in .shp: {path}")
    missing_sidecars = [
        path.with_suffix(suffix)
        for suffix in (".shp", ".shx", ".dbf", ".prj")
        if not path.with_suffix(suffix).is_file()
    ]
    if missing_sidecars:
        raise FileNotFoundError(
            f"Shapefile input is missing required components: {missing_sidecars}"
        )

    frame = gpd.read_file(path)
    if frame.empty:
        raise ValueError(f"Emissions shapefile has no features: {path}")
    if frame.crs is None:
        raise ValueError(f"Emissions shapefile has no CRS metadata: {path}")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError(f"Emissions shapefile contains missing or empty geometries: {path}")

    geometry_types = sorted(set(frame.geometry.geom_type))
    unsupported = sorted(set(geometry_types) - SUPPORTED_GEOMETRIES)
    if unsupported:
        raise ValueError(f"InMAP does not support shapefile geometries {unsupported}: {path}")

    pollutants = [field for field in POLLUTANT_FIELDS if field in frame.columns]
    if not pollutants:
        raise ValueError(
            f"Emissions shapefile must contain at least one of {list(POLLUTANT_FIELDS)}: {path}"
        )
    numeric = frame[pollutants].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError(f"Shapefile pollutant values must be finite annual totals: {path}")
    if (numeric < 0).any().any():
        raise ValueError(f"Shapefile pollutant values must be non-negative: {path}")

    present_stack_fields = [field for field in STACK_FIELDS if field in frame.columns]
    if present_stack_fields and len(present_stack_fields) != len(STACK_FIELDS):
        missing = sorted(set(STACK_FIELDS) - set(present_stack_fields))
        raise ValueError(f"Elevated shapefile is missing stack fields {missing}: {path}")
    if present_stack_fields:
        stacks = frame[list(STACK_FIELDS)].apply(pd.to_numeric, errors="coerce")
        if stacks.isna().any().any() or not np.isfinite(stacks.to_numpy(dtype=float)).all():
            raise ValueError(f"Shapefile stack values must be finite: {path}")
        if (stacks["height"] < 0).any() or (stacks[["diam", "temp", "velocity"]] <= 0).any().any():
            raise ValueError(f"Shapefile stack dimensions must be physically positive: {path}")

    bounds = frame.to_crs("EPSG:4326").total_bounds.tolist()
    if not _overlaps_korea(bounds):
        raise ValueError(f"Emissions shapefile does not overlap South Korea: {path}")
    return {
        "feature_count": len(frame),
        "geometry_types": geometry_types,
        "pollutants": pollutants,
        "elevated": bool(present_stack_fields),
        "crs": str(frame.crs),
        "wgs84_bounds": bounds,
    }


def validate_coards_netcdf(path: Path) -> dict[str, Any]:
    """Validate the NetCDF-3 subset accepted by InMAP's COARDS reader."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"COARDS emissions file does not exist: {path}")
    with path.open("rb") as file:
        magic = file.read(4)
    if magic not in {b"CDF\x01", b"CDF\x02"}:
        raise ValueError(f"InMAP v1.9.6 requires a NetCDF-3 COARDS file: {path}")

    with netcdf_file(path, mode="r", mmap=False) as dataset:
        if "lat" not in dataset.dimensions or "lon" not in dataset.dimensions:
            raise ValueError(f"COARDS emissions require lat and lon dimensions: {path}")
        if "lat" not in dataset.variables or "lon" not in dataset.variables:
            raise ValueError(f"COARDS emissions require lat and lon coordinate variables: {path}")
        latitude = np.asarray(dataset.variables["lat"][:], dtype=float)
        longitude = np.asarray(dataset.variables["lon"][:], dtype=float)
        if latitude.ndim != 1 or longitude.ndim != 1 or not latitude.size or not longitude.size:
            raise ValueError(f"COARDS lat and lon coordinates must be non-empty vectors: {path}")
        if not np.isfinite(latitude).all() or not np.isfinite(longitude).all():
            raise ValueError(f"COARDS coordinates must be finite: {path}")

        pollutants: list[str] = []
        for field in POLLUTANT_FIELDS:
            variable = dataset.variables.get(field)
            if variable is None:
                continue
            if tuple(variable.dimensions) != ("lat", "lon"):
                raise ValueError(
                    f"COARDS variable {field} must have dimensions [lat, lon]: {path}"
                )
            values = np.asarray(variable[:])
            if not np.issubdtype(values.dtype, np.floating):
                raise ValueError(f"COARDS variable {field} must be floating point: {path}")
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError(
                    f"COARDS variable {field} must contain finite non-negative totals: {path}"
                )
            pollutants.append(field)
    if not pollutants:
        raise ValueError(
            f"COARDS emissions must contain at least one of {list(POLLUTANT_FIELDS)}: {path}"
        )

    bounds = [
        float(longitude.min()),
        float(latitude.min()),
        float(longitude.max()),
        float(latitude.max()),
    ]
    if not _overlaps_korea(bounds):
        raise ValueError(f"COARDS emissions grid does not overlap South Korea: {path}")
    return {
        "grid_shape": [int(latitude.size), int(longitude.size)],
        "pollutants": pollutants,
        "wgs84_bounds": bounds,
        "netcdf_format": "NetCDF-3",
    }


def select_supplemental_emissions(
    entries: Sequence[Mapping[str, Any]] | None,
    *,
    scenario: str,
    year: int,
    shapefile_units: str,
) -> list[dict[str, Any]]:
    """Select, validate, and normalize external emissions for one scenario-year."""
    if shapefile_units not in SHAPEFILE_UNITS:
        raise ValueError(f"Unsupported InMAP shapefile units: {shapefile_units}")
    if entries is None:
        return []
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ValueError("inmap.supplemental_emissions must be a list.")

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    selected_paths: set[Path] = set()
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise ValueError("Each supplemental emission input must be a mapping.")
        input_id = str(raw.get("id", "")).strip()
        if not input_id:
            raise ValueError("Each supplemental emission input requires a non-empty id.")
        if input_id in seen_ids:
            raise ValueError(f"Duplicate supplemental emission input id: {input_id}")
        seen_ids.add(input_id)
        if not _scope_matches(raw.get("scenarios"), scenario, "scenarios"):
            continue
        if not _scope_matches(raw.get("years"), year, "years"):
            continue

        input_format = str(raw.get("format", "")).strip().lower()
        if input_format not in {"shapefile", "coards"}:
            raise ValueError(
                f"Supplemental emission {input_id} format must be shapefile or coards."
            )
        if "path" not in raw:
            raise ValueError(f"Supplemental emission {input_id} requires a path.")
        path = Path(raw["path"]).resolve()
        if path in selected_paths:
            raise ValueError(f"Supplemental emissions path would be counted twice: {path}")
        selected_paths.add(path)
        sector = str(raw.get("sector", input_id)).strip()
        if not sector:
            raise ValueError(f"Supplemental emission {input_id} requires a sector.")

        if input_format == "shapefile":
            units = str(raw.get("units", shapefile_units))
            if units != shapefile_units:
                raise ValueError(
                    f"Supplemental shapefile {input_id} uses {units}; all shapefiles in a run "
                    f"must use {shapefile_units}."
                )
            details = validate_emissions_shapefile(path)
            coards_year = None
        else:
            units = str(raw.get("units", "kg"))
            if units not in COARDS_UNITS:
                raise ValueError(f"Unsupported COARDS units for {input_id}: {units}")
            coards_year = int(raw.get("coards_year", year))
            details = validate_coards_netcdf(path)

        selected.append(
            {
                "id": input_id,
                "sector": sector,
                "format": input_format,
                "path": path,
                "units": units,
                "scenario": scenario,
                "year": year,
                "coards_year": coards_year,
                **details,
            }
        )

    coards = [item for item in selected if item["format"] == "coards"]
    coards_units = {item["units"] for item in coards}
    coards_years = {item["coards_year"] for item in coards}
    if len(coards_units) > 1:
        raise ValueError(f"All COARDS inputs in one run must use the same units: {coards_units}")
    if len(coards_years) > 1:
        raise ValueError(f"All COARDS inputs in one run must use the same year: {coards_years}")
    return selected


def emission_dependency_files(paths: Sequence[Path]) -> list[Path]:
    """Expand primary input paths to the exact files that determine a model run."""
    dependencies: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() == ".shp":
            related = path.parent.glob(f"{path.stem}.*")
            dependencies.update(
                candidate.resolve() for candidate in related if candidate.is_file()
            )
        elif path.is_file():
            dependencies.add(path.resolve())
        else:
            raise FileNotFoundError(f"InMAP emissions input does not exist: {path}")
    return sorted(dependencies, key=str)
