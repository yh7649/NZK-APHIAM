from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.data.external import ingest_macro


def test_ingest_activity_file_copies_and_writes_provenance(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "activity.csv"
    source.parent.mkdir()
    pd.DataFrame(
        [{"scenario": "ref", "year": 2023, "sector": "industry", "fuel": "coal", "activity": 10.0}]
    ).to_csv(source, index=False)
    dest_dir = tmp_path / "external" / "macro"

    dest_path = ingest_macro.ingest_macro_file(
        source=source,
        kind="activity",
        dest_dir=dest_dir,
        contributor="test-team",
        note="unit test",
    )

    assert dest_path == dest_dir / "activity.csv"
    assert dest_path.read_text() == source.read_text()

    manifest_path = dest_dir / "activity.metadata.json"
    assert manifest_path.exists()
    manifest = manifest_path.read_text()
    assert '"kind": "activity"' in manifest
    assert '"contributor": "test-team"' in manifest
    assert '"row_count": 1' in manifest


def test_ingest_rejects_activity_file_missing_required_columns(tmp_path: Path) -> None:
    source = tmp_path / "activity.csv"
    pd.DataFrame([{"year": 2023, "sector": "industry", "activity": 10.0}]).to_csv(
        source, index=False
    )

    with pytest.raises(ValueError, match="missing columns"):
        ingest_macro.ingest_macro_file(
            source=source, kind="activity", dest_dir=tmp_path / "external" / "macro"
        )


def test_ingest_generation_file_detects_flexible_columns(tmp_path: Path) -> None:
    source = tmp_path / "generation.csv"
    pd.DataFrame(
        [{"Year": 2021, "Technology": "ThermalPower{Coal}", "Generation_GWh": 1.2}]
    ).to_csv(source, index=False)
    dest_dir = tmp_path / "external" / "macro"

    dest_path = ingest_macro.ingest_macro_file(source=source, kind="generation", dest_dir=dest_dir)

    assert dest_path.exists()
    assert (dest_dir / "generation.metadata.json").exists()


def test_ingest_rejects_generation_file_without_year_or_generation_column(tmp_path: Path) -> None:
    source = tmp_path / "generation.csv"
    pd.DataFrame([{"Technology": "Coal"}]).to_csv(source, index=False)

    with pytest.raises(ValueError, match="year column"):
        ingest_macro.ingest_macro_file(
            source=source, kind="generation", dest_dir=tmp_path / "external" / "macro"
        )


def test_ingest_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    source = tmp_path / "activity.csv"
    pd.DataFrame(
        [{"year": 2023, "sector": "industry", "fuel": "coal", "activity": 10.0}]
    ).to_csv(source, index=False)
    dest_dir = tmp_path / "external" / "macro"

    ingest_macro.ingest_macro_file(source=source, kind="activity", dest_dir=dest_dir)

    with pytest.raises(FileExistsError):
        ingest_macro.ingest_macro_file(source=source, kind="activity", dest_dir=dest_dir)

    ingest_macro.ingest_macro_file(source=source, kind="activity", dest_dir=dest_dir, force=True)
