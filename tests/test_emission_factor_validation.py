from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.validation.emission_factors.annualize import (
    aggregate_boundary,
    apply_variant,
    prepare_project_data,
)
from nzk_aphiam.validation.emission_factors.compare import (
    build_readable_comparison_tables,
    compare_to_literature,
    prepare_literature_output,
)
from nzk_aphiam.validation.emission_factors.crosswalk import project_boundaries_from_crosswalk
from nzk_aphiam.validation.emission_factors.references import load_literature_benchmarks


REFERENCE_DIR = Path("docs/references/emission_factor_validation")


def row(
    date: str,
    *,
    plant_name: str = "Test",
    plant_number: float = 1.0,
    generation: float | None = 100.0,
    nox: float | None = 10.0,
    sox: float | None = 20.0,
    tsp: float | None = 5.0,
    row_status: str = "active_reported",
    audit_severity: str | None = None,
) -> dict[str, object]:
    return {
        "date": date,
        "plant_name": plant_name,
        "plant_number": plant_number,
        "source_dataset": "fixture",
        "subsidiary_company": "Fixture Power",
        "fuel_type": "coal",
        "technology": "conventional_steam_turbine",
        "observation_level": "generating_unit",
        "reporting_unit_id": f"{plant_name}:{plant_number}",
        "generation_coverage_status": "complete",
        "row_status": row_status,
        "energy_generated_mwh": generation,
        "nox": nox,
        "sox": sox,
        "dust_tsp": tsp,
        "audit_severity": audit_severity,
        "audit_issue_codes": "fixture_issue" if audit_severity else None,
    }


def annualize(rows: list[dict[str, object]]) -> pd.DataFrame:
    prepared = prepare_project_data(pd.DataFrame(rows))
    retained, _ = apply_variant(prepared, "reported")
    return aggregate_boundary(retained, group_columns=["plant_name"], analysis_variant="reported")


def test_annual_ef_uses_sum_mass_over_sum_generation_not_monthly_mean() -> None:
    result = annualize(
        [
            row("2022-01-01", generation=100.0, nox=100.0),
            row("2022-02-01", generation=900.0, nox=90.0),
        ]
    )
    nox = result.loc[result["pollutant"].eq("NOx")].iloc[0]
    assert nox["ef_kg_per_mwh"] == pytest.approx(0.19)
    assert nox["ef_kg_per_mwh"] != pytest.approx(((100 / 100) + (90 / 900)) / 2)


def test_zero_generation_does_not_produce_infinite_factor() -> None:
    result = annualize([row("2022-01-01", generation=0.0, nox=10.0)])
    nox = result.loc[result["pollutant"].eq("NOx")].iloc[0]
    assert pd.isna(nox["ef_kg_per_mwh"])


def test_missing_emissions_are_not_interpreted_as_zero() -> None:
    result = annualize(
        [
            row("2022-01-01", generation=100.0, nox=None),
            row("2022-02-01", generation=100.0, nox=10.0),
        ]
    )
    nox = result.loc[result["pollutant"].eq("NOx")].iloc[0]
    assert nox["n_generation_months"] == 2
    assert nox["n_pollutant_months"] == 1
    assert nox["n_matched_months"] == 1
    assert nox["generation_mwh_sum"] == 100
    assert nox["pollutant_mass_kg_sum"] == 10


def test_pollutant_specific_matched_month_coverage() -> None:
    result = annualize(
        [
            row("2022-01-01", generation=100.0, nox=10.0, sox=None),
            row("2022-02-01", generation=100.0, nox=None, sox=30.0),
        ]
    )
    nox = result.loc[result["pollutant"].eq("NOx")].iloc[0]
    sox = result.loc[result["pollutant"].eq("SOx")].iloc[0]
    assert nox["n_matched_months"] == 1
    assert sox["n_matched_months"] == 1
    assert nox["pollutant_mass_kg_sum"] == 10
    assert sox["pollutant_mass_kg_sum"] == 30


def test_combined_factor_requires_all_three_pollutants_in_same_month() -> None:
    result = annualize(
        [
            row("2022-01-01", generation=100.0, nox=10.0, sox=20.0, tsp=None),
            row("2022-02-01", generation=100.0, nox=10.0, sox=20.0, tsp=5.0),
        ]
    )
    combined = result.loc[result["pollutant"].eq("combined")].iloc[0]
    assert combined["n_matched_months"] == 1
    assert combined["generation_mwh_sum"] == 100
    assert combined["pollutant_mass_kg_sum"] == 35


def test_one_to_many_crosswalk_aggregation_does_not_double_count_generation() -> None:
    data = prepare_project_data(
        pd.DataFrame(
            [
                row("2022-01-01", plant_name="Plant", plant_number=1, generation=100.0),
                row("2022-01-01", plant_name="Plant", plant_number=2, generation=200.0),
                row("2022-01-01", plant_name="Plant", plant_number=3, generation=300.0),
            ]
        )
    )
    crosswalk = pd.DataFrame(
        [
            {
                "reference_id": "ref",
                "literature_plant_group_id": "group",
                "project_plant_name": "Plant",
                "project_reporting_unit_id": "",
                "included_unit_numbers": "1-2",
                "match_status": "accepted",
                "boundary_match_status": "exact",
                "evidence": "fixture",
                "notes": "fixture",
            }
        ]
    )
    project, _ = project_boundaries_from_crosswalk(data, crosswalk, analysis_variant="reported")
    nox = project.loc[project["pollutant"].eq("NOx")].iloc[0]
    assert nox["generation_mwh_sum"] == 300


def test_tsp_cannot_be_matched_to_pm25() -> None:
    project = pd.DataFrame(
        {
            "reference_id": ["ref"],
            "plant_group_id": ["group"],
            "year": [2022],
            "pollutant": ["TSP"],
            "pollutant_scope": ["TSP"],
            "analysis_variant": ["reported"],
            "generation_mwh_sum": [100.0],
            "pollutant_mass_kg_sum": [1.0],
            "ef_kg_per_mwh": [0.01],
            "n_matched_months": [12],
            "complete_calendar_year": [True],
            "boundary_match_status": ["exact"],
            "project_plant_name": ["Plant"],
        }
    )
    literature = pd.DataFrame(
        {
            "reference_id": ["ref"],
            "plant_group_id": ["group"],
            "data_year": [2022],
            "pollutant": ["PM2.5"],
            "pollutant_scope": ["PM2.5"],
            "reference_ef_kg_per_mwh": [0.01],
        }
    )
    assert compare_to_literature(project, literature).empty


def test_combined_keei_factor_cannot_match_individual_pollutant() -> None:
    project = pd.DataFrame(
        {
            "reference_id": ["keei"],
            "plant_group_id": ["group"],
            "year": [2016],
            "pollutant": ["NOx"],
            "pollutant_scope": ["NOx"],
            "analysis_variant": ["reported"],
            "generation_mwh_sum": [100.0],
            "pollutant_mass_kg_sum": [10.0],
            "ef_kg_per_mwh": [0.1],
            "n_matched_months": [12],
            "complete_calendar_year": [True],
            "boundary_match_status": ["exact"],
            "project_plant_name": ["Plant"],
        }
    )
    literature = pd.DataFrame(
        {
            "reference_id": ["keei"],
            "plant_group_id": ["group"],
            "data_year": [2016],
            "pollutant": ["combined"],
            "pollutant_scope": ["NOx+SOx+TSP"],
            "reference_ef_kg_per_mwh": [0.5],
        }
    )
    assert compare_to_literature(project, literature).empty


def test_partial_unit_boundaries_are_marked_non_strict() -> None:
    literature = pd.DataFrame(
        {
            "reference_id": ["ref"],
            "plant_group_id": ["group"],
            "data_year": [2022],
            "pollutant": ["NOx"],
            "pollutant_scope": ["NOx"],
            "reference_ef_kg_per_mwh": [0.1],
            "reference_generation_mwh": [100.0],
            "reference_emissions_kg": [10.0],
            "validation_role": ["primary_same_year_external_pipeline_validation"],
            "comparability_notes": [""],
            "plant_name_en": ["Plant"],
        }
    )
    project = pd.DataFrame(
        {
            "reference_id": ["ref"],
            "plant_group_id": ["group"],
            "year": [2022],
            "pollutant": ["NOx"],
            "pollutant_scope": ["NOx"],
            "analysis_variant": ["reported"],
            "generation_mwh_sum": [100.0],
            "pollutant_mass_kg_sum": [10.0],
            "ef_kg_per_mwh": [0.1],
            "n_matched_months": [12],
            "complete_calendar_year": [True],
            "boundary_match_status": ["partial_units"],
            "project_plant_name": ["Plant"],
        }
    )
    comparison = compare_to_literature(project, literature)
    assert comparison["comparability_status"].iloc[0] == "non_strict_or_historical_benchmark"


def test_taean_2022_literature_fixture_reproduces_expected_values() -> None:
    literature = prepare_literature_output(load_literature_benchmarks(REFERENCE_DIR))
    taean = literature.loc[
        literature["plant_group_id"].eq("lee_taean_1_10"),
        ["pollutant", "reference_ef_kg_per_mwh"],
    ].set_index("pollutant")["reference_ef_kg_per_mwh"]
    assert taean["NOx"] == pytest.approx(0.145220, abs=1e-6)
    assert taean["SOx"] == pytest.approx(0.133259, abs=1e-6)
    assert taean["TSP"] == pytest.approx(0.010250, abs=1e-6)
    assert taean["combined"] == pytest.approx(0.288729, abs=1e-6)


def test_reference_csvs_have_no_duplicate_keys() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    assert not literature.duplicated(
        ["reference_id", "plant_group_id", "data_year", "pollutant_scope"]
    ).any()


def test_audit_flags_remain_available_in_output() -> None:
    result = annualize([row("2022-01-01", audit_severity="critical")])
    nox = result.loc[result["pollutant"].eq("NOx")].iloc[0]
    assert nox["audit_severity_values"] == "critical"
    assert nox["audit_issue_code_values"] == "fixture_issue"


def test_readable_comparison_tables_include_source_hand_calc_and_percent_error() -> None:
    comparisons = pd.DataFrame(
        {
            "reference_id": ["lee_2025_kosae", "lee_2025_kosae"],
            "year": [2022, 2022],
            "plant_name_en": ["Plant", "Plant"],
            "pollutant": ["NOx", "SOx"],
            "reference_ef_kg_per_mwh": [0.2, 0.1],
            "project_ef_kg_per_mwh": [0.22, 0.09],
            "ef_percent_difference": [10.0, -10.0],
            "generation_percent_difference": [1.0, 2.0],
            "emissions_percent_difference": [11.0, -8.0],
            "n_matched_months": [12, 12],
            "coverage_status": ["complete_matched_calendar_year", "complete_matched_calendar_year"],
            "boundary_match_status": ["exact", "exact"],
            "comparability_status": [
                "strict_same_year_comparable",
                "strict_same_year_comparable",
            ],
            "analysis_variant": ["reported", "reported"],
        }
    )
    tidy, wide = build_readable_comparison_tables(comparisons)

    assert {
        "other_source_ef_kg_per_mwh",
        "hand_calculated_ef_kg_per_mwh",
        "ef_percent_error",
    }.issubset(tidy.columns)
    assert wide.loc[0, "nox_other_source_ef_kg_per_mwh"] == 0.2
    assert wide.loc[0, "nox_hand_calculated_ef_kg_per_mwh"] == 0.22
    assert wide.loc[0, "nox_percent_error"] == 10.0
