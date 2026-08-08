from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from nzk_aphiam.model_inputs import ingest_macro


def test_ingest_activity_file_copies_and_writes_provenance(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "activity.csv"
    source.parent.mkdir()
    pd.DataFrame(
        [{"scenario": "ref", "year": 2023, "sector": "industry", "fuel": "coal", "activity": 10.0}]
    ).to_csv(source, index=False)
    dest_dir = tmp_path / "model_inputs" / "upstream" / "macro"

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
    manifest = json.loads(manifest_path.read_text())
    assert manifest["kind"] == "activity"
    assert manifest["scenario_bundle"] == "team_handoff"
    assert manifest["source_model"] == "macro"
    assert manifest["contributor"] == "test-team"
    assert manifest["row_count"] == 1
    assert manifest["original_filename"] == "activity.csv"
    assert "original_path" not in manifest
    assert str(tmp_path) not in manifest_path.read_text()


def test_ingest_rejects_activity_file_missing_required_columns(tmp_path: Path) -> None:
    source = tmp_path / "activity.csv"
    pd.DataFrame([{"year": 2023, "sector": "industry", "activity": 10.0}]).to_csv(
        source, index=False
    )

    with pytest.raises(ValueError, match="missing columns"):
        ingest_macro.ingest_macro_file(
            source=source,
            kind="activity",
            dest_dir=tmp_path / "model_inputs" / "upstream" / "macro",
        )


def test_ingest_generation_file_detects_flexible_columns(tmp_path: Path) -> None:
    source = tmp_path / "generation.csv"
    pd.DataFrame(
        [{"Year": 2021, "Technology": "ThermalPower{Coal}", "Generation_GWh": 1.2}]
    ).to_csv(source, index=False)
    dest_dir = tmp_path / "model_inputs" / "upstream" / "macro"

    dest_path = ingest_macro.ingest_macro_file(source=source, kind="generation", dest_dir=dest_dir)

    assert dest_path.exists()
    assert (dest_dir / "generation.metadata.json").exists()


def test_ingest_rejects_generation_file_without_year_or_generation_column(tmp_path: Path) -> None:
    source = tmp_path / "generation.csv"
    pd.DataFrame([{"Technology": "Coal"}]).to_csv(source, index=False)

    with pytest.raises(ValueError, match="year column"):
        ingest_macro.ingest_macro_file(
            source=source,
            kind="generation",
            dest_dir=tmp_path / "model_inputs" / "upstream" / "macro",
        )


def test_ingest_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    source = tmp_path / "activity.csv"
    pd.DataFrame(
        [{"year": 2023, "sector": "industry", "fuel": "coal", "activity": 10.0}]
    ).to_csv(source, index=False)
    dest_dir = tmp_path / "model_inputs" / "upstream" / "macro"

    ingest_macro.ingest_macro_file(source=source, kind="activity", dest_dir=dest_dir)

    with pytest.raises(FileExistsError):
        ingest_macro.ingest_macro_file(source=source, kind="activity", dest_dir=dest_dir)

    ingest_macro.ingest_macro_file(source=source, kind="activity", dest_dir=dest_dir, force=True)


def test_ingest_gcam_xml_archive_validates_and_uses_scenario_subdirectory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "gcam.xml.zip"
    xml = """<scenario name="NZK"><model-version>v9.1</model-version><modeltime>
    <model-year>2025</model-year></modeltime><world><region name="South Korea"/>
    </world></scenario>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("gcam.xml", xml)
    dest_dir = tmp_path / "upstream" / "gcam_kaist"

    destination = ingest_macro.ingest_macro_file(
        source=source,
        kind="gcam_xml_archive",
        source_model="gcam_kaist",
        dest_dir=dest_dir,
        upstream_scenario="nzk",
    )

    assert destination == dest_dir / "nzk" / "gcam.xml.zip"
    metadata = json.loads((dest_dir / "nzk" / "gcam.xml.metadata.json").read_text())
    assert metadata["source_scenario"] == "NZK"
    assert metadata["model_years"] == [2025]
    assert metadata["row_count"] is None
