from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.data.process.merge_nonpower_scenarios import merge_projected_emissions

COLUMNS = ["scenario", "year", "pollutant", "projected_emissions_kg"]


def _write(path: Path, scenario: str) -> Path:
    pd.DataFrame(
        {
            "scenario": [scenario, scenario],
            "year": [2050, 2050],
            "pollutant": ["NOx", "SOx"],
            "projected_emissions_kg": [1.0, 2.0],
        },
        columns=COLUMNS,
    ).to_csv(path, index=False)
    return path


def test_merge_concatenates_distinct_single_scenario_files(tmp_path: Path) -> None:
    reference = _write(tmp_path / "reference.csv", "reference")
    nzk = _write(tmp_path / "nzk.csv", "nzk")
    output = tmp_path / "merged.csv"

    merged = merge_projected_emissions([reference, nzk], output)

    assert sorted(merged["scenario"].unique()) == ["nzk", "reference"]
    assert len(merged) == 4
    assert output.is_file()


def test_merge_rejects_multi_scenario_input(tmp_path: Path) -> None:
    mixed = tmp_path / "mixed.csv"
    pd.DataFrame(
        {
            "scenario": ["reference", "nzk"],
            "year": [2050, 2050],
            "pollutant": ["NOx", "NOx"],
            "projected_emissions_kg": [1.0, 2.0],
        },
        columns=COLUMNS,
    ).to_csv(mixed, index=False)
    other = _write(tmp_path / "nzk.csv", "nzk")

    with pytest.raises(ValueError, match="exactly one scenario label"):
        merge_projected_emissions([mixed, other], tmp_path / "merged.csv")


def test_merge_rejects_duplicate_scenario_labels(tmp_path: Path) -> None:
    first = _write(tmp_path / "a.csv", "nzk")
    second = _write(tmp_path / "b.csv", "nzk")

    with pytest.raises(ValueError, match="more than one input file"):
        merge_projected_emissions([first, second], tmp_path / "merged.csv")
