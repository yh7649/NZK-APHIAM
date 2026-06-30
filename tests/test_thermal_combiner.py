from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.schema import (
    COMBINED_THERMAL_OUTPUT_COLUMNS,
    THERMAL_OUTPUT_COLUMNS,
)
from nzk_aphiam.data.process.thermal.combiner import (
    DatasetSpec,
    build_subsidiary_coverage,
    build_variable_metadata,
    combine_thermal_datasets,
    process_subsidiary_datasets,
)


def make_row(
    *,
    unit: str,
    nox: float = 1.5,
    basis: str = "mass",
) -> pd.DataFrame:
    row = {column: pd.NA for column in THERMAL_OUTPUT_COLUMNS}
    row.update(
        {
            "date": "2025-01-01",
            "plant_name": "Test Plant",
            "plant_number": 1,
            "subsidiary_company": "Test Power",
            "energy_type": "coal",
            "energy_generated_mwh": 100.0,
            "energy_capacity_mw": 10.0,
            "nox": nox,
            "sox": 2.0,
            "dust_tsp": 0.5,
            "pollutant_measurement_basis": basis,
            "nox_unit": unit,
            "sox_unit": unit,
            "dust_tsp_unit": unit,
            "emissions_mass_unit": unit,
        }
    )
    return pd.DataFrame([row], columns=THERMAL_OUTPUT_COLUMNS)


def test_combiner_standardizes_metric_tonnes_to_kilograms() -> None:
    tonnes = DatasetSpec("tonnes_source", "monthly", Path("unused.csv"))
    kilograms = DatasetSpec("kilograms_source", "monthly", Path("unused.csv"))

    result = combine_thermal_datasets(
        [
            (tonnes, make_row(unit="metric_tonnes", nox=1.5)),
            (kilograms, make_row(unit="kilograms", nox=1.5)),
        ]
    )

    assert list(result.columns) == COMBINED_THERMAL_OUTPUT_COLUMNS
    assert result["source_dataset"].tolist() == ["kilograms_source", "tonnes_source"]
    assert result["operator_category"].eq("kepco").all()
    assert result["observation_frequency"].eq("monthly").all()
    assert result["emissions_mass_unit"].eq("kilograms").all()
    assert result["nox_unit"].eq("kilograms").all()
    assert result.loc[result["source_dataset"].eq("tonnes_source"), "nox"].item() == 1500
    assert result.loc[result["source_dataset"].eq("kilograms_source"), "nox"].item() == 1.5
    assert result["energy_generated_mwh"].eq(100).all()


def test_combiner_rejects_non_mass_observations() -> None:
    spec = DatasetSpec("concentration_source", "monthly", Path("unused.csv"))
    data = make_row(unit="not_reported", basis="concentration")
    data["emissions_mass_unit"] = pd.NA

    with pytest.raises(ValueError, match="only pollutant mass observations"):
        combine_thermal_datasets([(spec, data)])


def test_combiner_rejects_non_month_start_dates() -> None:
    spec = DatasetSpec("daily_source", "monthly", Path("unused.csv"))
    data = make_row(unit="kilograms")
    data["date"] = "2025-01-02"

    with pytest.raises(ValueError, match="not month starts"):
        combine_thermal_datasets([(spec, data)])


def test_variable_metadata_matches_combined_schema_and_labels_units() -> None:
    metadata = build_variable_metadata()

    assert metadata["varname"].tolist() == COMBINED_THERMAL_OUTPUT_COLUMNS
    assert metadata["varname"].is_unique
    labels = metadata.set_index("varname")["label"]
    assert "(MWh)" in labels["energy_generated_mwh"]
    assert "(MW)" in labels["energy_capacity_mw"]
    assert "(kg)" in labels["nox"]
    assert "(kg)" in labels["sox"]
    assert "(kg)" in labels["dust_tsp"]
    assert "oxygen" not in labels
    assert "oxygen_unit" not in labels
    assert "flue_gas_flow" not in labels
    assert "flue_gas_flow_unit" not in labels
    assert "temperature_celsius" not in labels


def test_processes_each_subsidiary_without_cross_source_concatenation() -> None:
    tonnes = DatasetSpec("tonnes_source", "monthly", Path("unused.csv"))
    kilograms = DatasetSpec("kilograms_source", "monthly", Path("unused.csv"))

    result = process_subsidiary_datasets(
        [
            (tonnes, make_row(unit="metric_tonnes", nox=1.5)),
            (kilograms, make_row(unit="kilograms", nox=2.5)),
        ]
    )

    assert set(result) == {"tonnes_source", "kilograms_source"}
    assert result["tonnes_source"]["nox"].item() == 1500
    assert result["kilograms_source"]["nox"].item() == 2.5
    assert result["tonnes_source"]["source_dataset"].eq("tonnes_source").all()


def test_subsidiary_coverage_reports_nonmissing_counts_and_percentages() -> None:
    spec = DatasetSpec("test_source", "monthly", Path("unused.csv"))
    data = pd.concat(
        [make_row(unit="kilograms"), make_row(unit="kilograms")],
        ignore_index=True,
    )
    data.loc[1, "energy_generated_mwh"] = pd.NA
    processed = process_subsidiary_datasets([(spec, data)])

    coverage = build_subsidiary_coverage(processed).iloc[0]

    assert coverage["rows"] == 2
    assert coverage["energy_generated_mwh_nonmissing"] == 1
    assert coverage["energy_generated_mwh_coverage_pct"] == 50.0
    assert coverage["nox_coverage_pct"] == 100.0


def test_subsidiary_coverage_excludes_inactive_placeholders_from_denominator() -> None:
    spec = DatasetSpec("test_source", "monthly", Path("unused.csv"))
    data = pd.concat(
        [make_row(unit="kilograms"), make_row(unit="kilograms")],
        ignore_index=True,
    )
    data.loc[1, "row_status"] = "inactive_placeholder"
    data.loc[1, ["energy_generated_mwh", "nox", "sox", "dust_tsp"]] = pd.NA
    processed = process_subsidiary_datasets([(spec, data)])

    coverage = build_subsidiary_coverage(processed).iloc[0]

    assert coverage["rows"] == 2
    assert coverage["analysis_rows"] == 1
    assert coverage["inactive_placeholder_rows"] == 1
    assert coverage["energy_generated_mwh_coverage_pct"] == 100.0
