from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from nzk_aphiam.health.scenario_pm25_maps import (
    _difference_frame,
    plot_scenario_concentration_maps,
    plot_scenario_reduction_maps,
)


def _grid(values: list[float]) -> gpd.GeoDataFrame:
    cells = [box(126.0 + i * 0.1, 36.0, 126.1 + i * 0.1, 36.1) for i in range(len(values))]
    return gpd.GeoDataFrame(
        {
            "cell_id": [f"cell_{i}" for i in range(len(values))],
            "TotalPM25": values,
        },
        geometry=cells,
        crs="EPSG:4326",
    )


def _boundary() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[box(125.5, 35.5, 129.5, 38.5)], crs="EPSG:4326")


def test_difference_frame_computes_reference_minus_policy() -> None:
    reference = _grid([1.0, 2.0, 3.0])
    policy = _grid([0.4, 2.0, 1.5])
    result = _difference_frame(reference, policy)
    assert list(result["reduction"]) == pytest.approx([0.6, 0.0, 1.5])


def test_difference_frame_drops_cells_absent_from_either_grid() -> None:
    reference = _grid([1.0, 2.0])
    policy = _grid([0.5])
    policy["cell_id"] = ["cell_9"]
    result = _difference_frame(reference, policy)
    assert result.empty


def test_plot_scenario_concentration_maps_writes_one_file_per_call(tmp_path: Path) -> None:
    boundary = _boundary()
    grids = {
        ("no_nzk", 2050): _grid([1.0, 2.0, 3.0]),
        ("nzk_high", 2050): _grid([0.4, 1.5, 2.5]),
    }
    output = tmp_path / "korea_pm25_concentration_2050.png"

    plot_scenario_concentration_maps(grids, boundary, 2050, ["no_nzk", "nzk_high"], output)

    assert output.is_file()
    assert output.stat().st_size > 0


def test_plot_scenario_reduction_maps_writes_one_file_per_policy_scenario(tmp_path: Path) -> None:
    boundary = _boundary()
    grids = {
        ("no_nzk", 2050): _grid([1.0, 2.0, 3.0]),
        ("nzk_high", 2050): _grid([0.4, 1.5, 2.5]),
    }
    output = tmp_path / "korea_pm25_reduction_2050.png"

    plot_scenario_reduction_maps(grids, boundary, 2050, "no_nzk", ["nzk_high"], output)

    assert output.is_file()
    assert output.stat().st_size > 0
