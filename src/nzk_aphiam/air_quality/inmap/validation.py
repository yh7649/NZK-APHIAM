"""Pre-run Global InMAP safeguards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def validate_global_domain(
    inventory: pd.DataFrame, installation: dict[str, Any], config: dict[str, Any]
) -> dict[str, object]:
    """Reject US-only/missing data and coordinates outside Global InMAP/Korea."""
    model_data = Path(installation["inmap_data"])
    variable_grid = Path(installation["variable_grid_data"])
    if "InMAPData_v1" not in model_data.name or "global_inmap" not in variable_grid.name:
        raise ValueError("Selected files are not the official Global InMAP model/grid data.")
    if not model_data.is_file() or not variable_grid.is_file():
        raise FileNotFoundError("Global InMAP model-data files are missing.")
    lon_min, lon_max = config["inmap"]["global_domain_longitude"]
    lat_min, lat_max = config["inmap"]["global_domain_latitude"]
    in_domain = inventory["longitude"].between(lon_min, lon_max) & inventory["latitude"].between(
        lat_min, lat_max
    )
    in_korea = inventory["longitude"].between(124.0, 132.0) & inventory["latitude"].between(
        33.0, 39.0
    )
    if not in_domain.all() or not in_korea.all():
        raise ValueError("At least one source is outside Global InMAP or the Korean envelope.")
    return {
        "global_model_data": str(model_data),
        "global_variable_grid": str(variable_grid),
        "source_count": len(inventory),
        "korea_inside_domain": True,
        "coordinate_crs": "EPSG:4326",
    }
