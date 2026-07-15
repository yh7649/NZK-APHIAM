from __future__ import annotations

from pathlib import Path

import pandas as pd

from nzk_aphiam.data.process.macro import integrator


def write_capss(path: Path) -> None:
    capss = pd.DataFrame(
        [
            {
                "year": 2023,
                "source_category": "industry",
                "source_midcategory": "industry_mid",
                "source_subcategory": "industry_sub",
                "fuel_category": "coal",
                "fuel_type": "bituminous",
                "pollutant": "NOx",
                "emissions_kg": 1000.0,
            },
            {
                "year": 2023,
                "source_category": "industry",
                "source_midcategory": "industry_mid",
                "source_subcategory": "industry_sub",
                "fuel_category": "coal",
                "fuel_type": "bituminous",
                "pollutant": "SOx",
                "emissions_kg": 500.0,
            },
        ]
    )
    capss.to_parquet(path, index=False)


def test_integrator_projects_emissions_from_capss_base_intensity(tmp_path: Path) -> None:
    capss_path = tmp_path / "capss.parquet"
    gcam_path = tmp_path / "gcam.csv"
    output_dir = tmp_path / "out"
    write_capss(capss_path)
    pd.DataFrame(
        [
            {"scenario": "ref", "year": 2023, "sector": "Industry", "fuel": "Coal", "activity": 100.0},
            {"scenario": "ref", "year": 2030, "sector": "Industry", "fuel": "Coal", "activity": 80.0},
        ]
    ).to_csv(gcam_path, index=False)

    metadata = integrator.integrate_macro_inputs(
        gcam_path=gcam_path,
        capss_path=capss_path,
        output_dir=output_dir,
        base_year=2023,
        scenario_columns=["scenario"],
        pollutants=["NOx", "SOx"],
    )

    projected = pd.read_csv(output_dir / "macro_projected_emissions.csv")
    nox_2030 = projected[(projected["year"] == 2030) & (projected["pollutant"] == "NOx")].iloc[0]
    sox_2030 = projected[(projected["year"] == 2030) & (projected["pollutant"] == "SOx")].iloc[0]
    assert nox_2030["projected_emissions_kg"] == 800.0
    assert sox_2030["projected_emissions_kg"] == 400.0
    assert metadata["base_year"] == 2023
    assert pd.read_csv(output_dir / "macro_input_diagnostics.csv").empty


def test_integrator_uses_mapping_and_reports_unmatched_activity(tmp_path: Path) -> None:
    capss_path = tmp_path / "capss.parquet"
    gcam_path = tmp_path / "gcam.csv"
    mapping_path = tmp_path / "mapping.csv"
    output_dir = tmp_path / "out"
    write_capss(capss_path)
    pd.DataFrame(
        [
            {"scenario": "nz", "year": 2023, "sector": "Industrial boilers", "fuel": "Hard coal", "activity": 50.0},
            {"scenario": "nz", "year": 2030, "sector": "Transport", "fuel": "Diesel", "activity": 70.0},
        ]
    ).to_csv(gcam_path, index=False)
    pd.DataFrame(
        [
            {
                "gcam_sector": "Industrial boilers",
                "gcam_fuel": "Hard coal",
                "capss_sector": "industry",
                "capss_fuel": "coal",
            }
        ]
    ).to_csv(mapping_path, index=False)

    integrator.integrate_macro_inputs(
        gcam_path=gcam_path,
        capss_path=capss_path,
        output_dir=output_dir,
        mapping_path=mapping_path,
        base_year=2023,
        scenario_columns=["scenario"],
        pollutants=["NOx"],
    )

    projected = pd.read_csv(output_dir / "macro_projected_emissions.csv")
    mapped = projected[projected["gcam_sector"] == "Industrial boilers"].iloc[0]
    assert mapped["capss_sector"] == "industry"
    assert mapped["capss_fuel"] == "coal"

    diagnostics = pd.read_csv(output_dir / "macro_input_diagnostics.csv")
    assert "gcam_activity_without_capss_emissions" in diagnostics["diagnostic"].tolist()


def test_integrator_reports_future_activity_without_base_year_denominator(tmp_path: Path) -> None:
    capss_path = tmp_path / "capss.parquet"
    gcam_path = tmp_path / "gcam.csv"
    output_dir = tmp_path / "out"
    write_capss(capss_path)
    pd.DataFrame(
        [
            {"scenario": "ref", "year": 2030, "sector": "Industry", "fuel": "Coal", "activity": 80.0},
        ]
    ).to_csv(gcam_path, index=False)

    integrator.integrate_macro_inputs(
        gcam_path=gcam_path,
        capss_path=capss_path,
        output_dir=output_dir,
        base_year=2023,
        scenario_columns=["scenario"],
        pollutants=["NOx"],
    )

    projected = pd.read_csv(output_dir / "macro_projected_emissions.csv")
    assert projected["projected_emissions_kg"].isna().all()

    diagnostics = pd.read_csv(output_dir / "macro_input_diagnostics.csv")
    assert "gcam_activity_without_emission_factor" in diagnostics["diagnostic"].tolist()
