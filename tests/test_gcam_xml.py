from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd
import pytest

from nzk_aphiam.model_inputs.gcam_xml import (
    GcamXmlError,
    extract_gcam_source,
    inspect_gcam_source,
)

GCAM_XML = """\
<scenario name="CORE_9_NZ" date="2026-08-07">
  <model-version>ver_9.1_rgcam-v9.1</model-version>
  <modeltime><model-year>2021</model-year><model-year>2025</model-year></modeltime>
  <world>
    <region name="Other"><demographics /></region>
    <region name="South Korea">
      <supplysector name="iron and steel">
        <subsector name="BLASTFUR">
          <technology name="BLASTFUR">
            <output-primary name="iron and steel">
              <physical-output unit="Mt" vintage="2025">1.2</physical-output>
            </output-primary>
            <input-energy name="delivered coal">
              <demand-physical unit="EJ" vintage="2025">0.2</demand-physical>
            </input-energy>
            <Non-CO2 name="NOx">
              <emissions unit="Tg" vintage="2025">0.001</emissions>
            </Non-CO2>
          </technology>
        </subsector>
      </supplysector>
    </region>
  </world>
</scenario>
"""


def _zip_xml(tmp_path: Path, text: str = GCAM_XML) -> Path:
    path = tmp_path / "scenario.xml.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("scenario.xml", text)
    return path


def test_inspect_and_extract_gcam_zip_without_materializing_xml(tmp_path: Path) -> None:
    source = _zip_xml(tmp_path)
    inspected = inspect_gcam_source(source)
    assert inspected["source_scenario"] == "CORE_9_NZ"
    assert inspected["model_version"] == "ver_9.1_rgcam-v9.1"
    assert inspected["model_years"] == [2021, 2025]
    assert "South Korea" in inspected["regions"]

    output = tmp_path / "aphiam"
    metadata = extract_gcam_source(
        source,
        output_dir=output,
        scenario_label="nzk",
        years=[2025],
    )
    assert metadata["activity_rows"] == 2
    assert metadata["native_emissions_rows"] == 1
    activity = pd.read_parquet(output / "gcam_kaist_nzk_activity.parquet")
    assert set(activity["record_type"]) == {"input", "output"}
    output_row = activity.loc[activity["record_type"].eq("output")].iloc[0]
    assert output_row["sector"] == "iron and steel"
    assert output_row["subsector"] == "BLASTFUR"
    assert output_row["activity"] == pytest.approx(1.2)
    emissions = pd.read_parquet(output / "gcam_kaist_nzk_native_emissions.parquet")
    assert emissions.loc[0, "pollutant"] == "NOx"
    assert emissions.loc[0, "emissions_kg"] == pytest.approx(1_000_000.0)


def test_gcam_inspection_rejects_incomplete_xml(tmp_path: Path) -> None:
    source = _zip_xml(tmp_path, GCAM_XML.replace("</scenario>", ""))
    with pytest.raises(GcamXmlError, match="incomplete or invalid XML"):
        inspect_gcam_source(source)


def test_gcam_inspection_requires_one_xml_member(tmp_path: Path) -> None:
    source = tmp_path / "two.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("one.xml", GCAM_XML)
        archive.writestr("two.xml", GCAM_XML)
    with pytest.raises(GcamXmlError, match="exactly one XML"):
        inspect_gcam_source(source)
