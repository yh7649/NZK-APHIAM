from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

import pandas as pd
import pytest

from nzk_aphiam.data.process import nonpower_sector_inventory as inventory


REFERENCE_DIR = Path("docs/references/nonpower_emissions")


@pytest.fixture
def reference_copy(tmp_path: Path) -> Path:
    destination = tmp_path / "references"
    shutil.copytree(REFERENCE_DIR, destination)
    return destination


def read_tables(path: Path) -> dict[str, pd.DataFrame]:
    return inventory.load_reference_tables(path)


def write_table(path: Path, key: str, data: pd.DataFrame) -> None:
    data.to_csv(path / inventory.REFERENCE_FILES[key], index=False)


def error_codes(tables: dict[str, pd.DataFrame]) -> set[str]:
    result = inventory.validate_tables(tables)
    return set(result.errors["code"])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_valid_inventory_passes() -> None:
    result = inventory.validate_reference_inventory(REFERENCE_DIR)
    assert result.errors.empty
    assert not result.tables["inventory"].empty


def test_duplicate_inventory_id_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    tables["inventory"].loc[1, "inventory_id"] = tables["inventory"].loc[0, "inventory_id"]
    assert "duplicate_id" in error_codes(tables)


def test_duplicate_crosswalk_id_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    tables["crosswalk"].loc[1, "crosswalk_id"] = tables["crosswalk"].loc[0, "crosswalk_id"]
    assert "duplicate_id" in error_codes(tables)


def test_missing_p1_activity_unit_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    index = tables["inventory"].index[tables["inventory"]["priority"].eq("P1")][0]
    tables["inventory"].loc[index, "activity_unit"] = ""
    assert "missing_p1_activity_unit" in error_codes(tables)


def test_missing_p1_denominator_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    inventory_id = tables["inventory"].loc[tables["inventory"]["priority"].eq("P1"), "inventory_id"].iloc[0]
    tables["denominators"] = tables["denominators"].loc[
        ~tables["denominators"]["inventory_id"].eq(inventory_id)
    ]
    assert "missing_p1_ef_denominator" in error_codes(tables)


def test_unknown_pollutant_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    tables["inventory"].loc[0, "required_pollutants"] += "|mystery_pollutant"
    assert "unknown_pollutant" in error_codes(tables)


def test_unknown_source_id_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    tables["inventory"].loc[0, "annual_activity_source_ids"] = "missing_source"
    assert "unknown_source_id" in error_codes(tables)


def test_unknown_crosswalk_inventory_id_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    tables["crosswalk"].loc[0, "inventory_id"] = "missing_inventory"
    assert "unknown_inventory_id" in error_codes(tables)


def test_electricity_only_combustion_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    index = tables["inventory"].index[tables["inventory"]["electricity_only"].eq("true")][0]
    tables["inventory"].loc[index, "combustion_emissions_possible"] = "true"
    assert "electricity_direct_emissions" in error_codes(tables)


def test_underspecified_exact_crosswalk_fails(reference_copy: Path) -> None:
    tables = read_tables(reference_copy)
    index = tables["crosswalk"].index[tables["crosswalk"]["match_status"].eq("exact")][0]
    tables["crosswalk"].loc[index, "capss_minor_category"] = ""
    assert "underspecified_exact_crosswalk" in error_codes(tables)


def test_unresolved_crosswalk_is_diagnostic_not_error() -> None:
    result = inventory.validate_tables(inventory.load_reference_tables(REFERENCE_DIR))
    assert result.errors.empty
    assert "unresolved_crosswalk" in set(result.warnings["code"])


def test_build_generates_required_outputs(reference_copy: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "processed"
    diagnostic_dir = tmp_path / "diagnostics"
    inventory.build_inventory(reference_copy, output_dir, diagnostic_dir)
    assert {path.name for path in output_dir.iterdir()} >= set(inventory.OUTPUT_FILES.values())
    assert {
        "inventory_validation_summary.json",
        "inventory_validation_issues.csv",
        "unresolved_crosswalks.csv",
        "missing_activity_sources.csv",
        "missing_ef_denominators.csv",
        "direct_emissions_boundary_issues.csv",
    } <= {path.name for path in diagnostic_dir.iterdir()}


def test_output_ordering_is_deterministic(reference_copy: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "processed"
    inventory.build_inventory(reference_copy, output_dir, tmp_path / "diagnostics")
    for key, filename in inventory.OUTPUT_FILES.items():
        values = pd.read_parquet(output_dir / filename)[inventory.ID_COLUMNS[key]].tolist()
        assert values == sorted(values)


def test_rebuild_is_byte_identical(reference_copy: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "processed"
    diagnostic_dir = tmp_path / "diagnostics"
    inventory.build_inventory(reference_copy, output_dir, diagnostic_dir)
    paths = sorted([*output_dir.iterdir(), *diagnostic_dir.iterdir()])
    before = {path.name: digest(path) for path in paths}
    inventory.build_inventory(reference_copy, output_dir, diagnostic_dir)
    after = {path.name: digest(path) for path in paths}
    assert after == before
