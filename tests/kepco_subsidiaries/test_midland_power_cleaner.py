from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.midland_power import cleaner
from nzk_aphiam.data.clean.thermal.midland_power.reported_mass_workbook import (
    EXPECTED_WORKBOOK_SHA256,
    REPORTED_MASS_COLUMNS,
    parse_reported_mass_workbook,
    verify_workbook_sha256,
    workbook_sha256,
)
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS


def _reported_rows(
    *,
    boundary: str = "보령기력",
    sheet: str = "보령",
    plant: str = "한국중부발전㈜보령발전본부",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2024-01-01",
                "source_sheet": sheet,
                "source_plant_name": plant,
                "source_unit": pd.NA,
                "source_outlet": outlet,
                "source_component_label": f"배출구 {outlet}",
                "generation_orgnm": boundary,
                "nox": nox,
                "sox": sox,
                "dust_tsp": dust,
            }
            for outlet, nox, sox, dust in [
                ("3", 10.0, 1.0, 0.1),
                ("4", 20.0, 2.0, 0.2),
            ]
        ],
        columns=REPORTED_MASS_COLUMNS,
    )


def _generation_row(
    *, boundary: str = "보령기력", fuel: str = "석탄"
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "orgnm": boundary,
                "ym": 202401,
                "hokinm": "소계",
                "capacity": 3000,
                "qvodgen": 500_000,
                "tper": 0,
                "uper": "50.00",
                "gennm": fuel,
            }
        ]
    )


def test_tracked_provider_workbook_checksum_and_layout() -> None:
    path = cleaner.DEFAULT_REPORTED_MASS_INPUT_PATH

    assert path.is_file()
    assert workbook_sha256(path) == EXPECTED_WORKBOOK_SHA256
    verify_workbook_sha256(path)
    reported = parse_reported_mass_workbook(path)

    assert list(reported.columns) == REPORTED_MASS_COLUMNS
    assert len(reported) == 744
    assert reported["date"].min() == pd.Timestamp("2024-01-01")
    assert reported["date"].max() == pd.Timestamp("2025-12-01")
    assert reported["source_sheet"].nunique() == 7
    assert reported["generation_orgnm"].nunique() == 10
    assert not reported.duplicated(["source_sheet", "date", "source_outlet"]).any()


def test_checksum_rejects_modified_workbook(tmp_path: Path) -> None:
    modified = tmp_path / "modified.xlsx"
    modified.write_bytes(b"not the provider workbook")

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_workbook_sha256(modified)


def test_clean_midland_power_uses_reported_mass_without_recalculation() -> None:
    result = cleaner.clean_midland_power(_reported_rows(), _generation_row())

    assert list(result.columns) == THERMAL_OUTPUT_COLUMNS
    assert len(result) == 1
    assert result.loc[0, "date"] == pd.Timestamp("2024-01-01")
    assert result.loc[0, "plant_name"] == "Boryeong"
    assert result.loc[0, "reporting_unit_id"] == "midland_power:보령기력"
    assert result.loc[0, "component_count"] == 2
    assert result.loc[0, "energy_generated_mwh"] == 500_000
    assert result.loc[0, "energy_capacity_mw"] == 3000
    assert result.loc[0, "nox"] == pytest.approx(30.0)
    assert result.loc[0, "sox"] == pytest.approx(3.0)
    assert result.loc[0, "dust_tsp"] == pytest.approx(0.3)
    assert result.loc[0, "technology"] == "conventional_steam_turbine"
    assert result.loc[0, "pollutant_measurement_basis"] == "mass"
    assert "No concentration-to-mass calculation" in result.loc[
        0, "original_korean_note"
    ]
    assert pd.notna(result.loc[0, "plant_opening_date"])
    assert pd.notna(result.loc[0, "plant_latitude"])
    assert str(result["component_count"].dtype) == "Int64"
    assert str(result["nox"].dtype) == "Float64"


def test_clean_midland_power_preserves_missing_pollutants() -> None:
    reported = _reported_rows(
        boundary="인천복합",
        sheet="인천",
        plant="한국중부발전㈜ 인천발전본부",
    )
    reported[["sox", "dust_tsp"]] = pd.NA
    generation = _generation_row(boundary="인천복합", fuel="복합")

    result = cleaner.clean_midland_power(reported, generation)

    assert result.loc[0, "nox"] == pytest.approx(30.0)
    assert pd.isna(result.loc[0, "sox"])
    assert pd.isna(result.loc[0, "dust_tsp"])
    assert result.loc[0, "pollutant_data_pattern"] == "nox_only"


def test_complete_provider_workbook_maps_to_all_generation_boundaries() -> None:
    reported = parse_reported_mass_workbook(cleaner.DEFAULT_REPORTED_MASS_INPUT_PATH)
    generation = reported[["date", "generation_orgnm"]].drop_duplicates()
    generation = generation.assign(
        ym=lambda data: data["date"].dt.strftime("%Y%m"),
        hokinm="소계",
        capacity=1,
        qvodgen=1,
        tper=0,
        uper="0",
        gennm="provider-boundary fixture",
    ).rename(columns={"generation_orgnm": "orgnm"})

    result = cleaner.clean_midland_power(reported, generation)

    assert len(result) == 240
    assert result["date"].min() == pd.Timestamp("2024-01-01")
    assert result["date"].max() == pd.Timestamp("2025-12-01")
    assert result["reporting_unit_id"].nunique() == 10
    assert result["energy_generated_mwh"].notna().all()
    assert result["energy_capacity_mw"].notna().all()
    assert result["nox"].notna().all()


def test_clean_midland_power_rejects_missing_required_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        cleaner.clean_midland_power(
            pd.DataFrame({"source_sheet": ["보령"]}), pd.DataFrame()
        )
