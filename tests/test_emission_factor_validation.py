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
    INCLUDED_DIRECT,
    build_readable_comparison_tables,
    compare_fuel_technology_year,
    compare_to_literature,
    prepare_literature_output,
)
from nzk_aphiam.validation.emission_factors.crosswalk import (
    project_boundaries_from_crosswalk,
)
from nzk_aphiam.validation.emission_factors.figures import write_comparison_table_images
from nzk_aphiam.validation.emission_factors.pipeline import run_validation
from nzk_aphiam.validation.emission_factors.references import (
    apply_comparison_rules,
    load_catalog,
    load_comparison_rules,
    load_literature_benchmarks,
    load_pdf_inventory,
)


REFERENCE_DIR = Path("docs/references/emission_factor_validation")


def reviewed_literature() -> pd.DataFrame:
    literature = prepare_literature_output(load_literature_benchmarks(REFERENCE_DIR))
    return apply_comparison_rules(literature, load_comparison_rules(REFERENCE_DIR))


@pytest.fixture(scope="module")
def validation_outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pd.DataFrame]:
    root = tmp_path_factory.mktemp("ef-validation")
    return run_validation(
        table_output_dir=root / "tables",
        figure_output_dir=root / "figures",
    )


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


def test_incomplete_pollutant_year_coverage_blocks_direct_comparison(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    direct = validation_outputs["direct_validation_comparisons"]
    assert direct.loc[
        direct["plant_group_id"].eq("lee_taean_1_10")
        & direct["pollutant"].eq("NOx")
    ].empty
    reconciliation = validation_outputs["plant_input_reconciliation"]
    taean = reconciliation.loc[
        reconciliation["plant_group_id"].eq("lee_taean_1_10")
        & reconciliation["pollutant"].eq("NOx")
        & reconciliation["analysis_variant"].eq("reported")
    ].iloc[0]
    assert taean["comparison_status"] == "excluded_coverage_mismatch"
    assert taean["comparison_class"] == "D_contextual_benchmark"
    assert taean["coverage_fraction"] < 1


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
        ["reference_id", "plant_group_id", "data_year", "pollutant_scope", "normalization_basis"]
    ).any()


def test_audit_flags_remain_available_in_output() -> None:
    result = annualize([row("2022-01-01", audit_severity="critical")])
    nox = result.loc[result["pollutant"].eq("NOx")].iloc[0]
    assert nox["audit_severity_values"] == "critical"
    assert nox["audit_issue_code_values"] == "fixture_issue"


def test_readable_comparison_tables_include_mass_generation_and_ef_reconciliation() -> None:
    comparisons = pd.DataFrame(
        {
            "reference_id": ["lee_2025_kosae", "lee_2025_kosae"],
            "year": [2022, 2022],
            "plant_name_en": ["Plant", "Plant"],
            "pollutant": ["NOx", "SOx"],
            "external_generation_mwh": [100.0, 100.0],
            "kepco_generation_mwh": [101.0, 102.0],
            "generation_difference_mwh": [1.0, 2.0],
            "external_pollutant_mass_kg": [20.0, 10.0],
            "kepco_pollutant_mass_kg": [22.22, 9.18],
            "mass_difference_kg": [2.22, -0.82],
            "external_ef_kg_per_mwh": [0.2, 0.1],
            "kepco_ef_kg_per_mwh": [0.22, 0.09],
            "absolute_difference_kg_per_mwh": [0.02, -0.01],
            "percent_difference": [10.0, -10.0],
            "ratio": [1.1, 0.9],
            "symmetric_percent_difference": [9.52, -10.53],
            "small_external_denominator_flag": [False, False],
            "coverage_fraction": [1.0, 1.0],
            "comparison_status": [INCLUDED_DIRECT, INCLUDED_DIRECT],
            "analysis_variant": ["reported", "reported"],
        }
    )
    tidy, wide = build_readable_comparison_tables(comparisons)

    assert {
        "external_generation_mwh",
        "kepco_generation_mwh",
        "external_pollutant_mass_kg",
        "kepco_pollutant_mass_kg",
        "external_ef_kg_per_mwh",
        "kepco_ef_kg_per_mwh",
        "percent_difference",
    }.issubset(tidy.columns)
    assert wide.loc[0, "nox_external_ef_kg_per_mwh"] == 0.2
    assert wide.loc[0, "nox_kepco_ef_kg_per_mwh"] == 0.22
    assert wide.loc[0, "nox_percent_difference"] == 10.0


def test_comparison_table_image_outputs_are_written(tmp_path: Path) -> None:
    tidy = pd.DataFrame(
        {
            "plant": ["Plant"],
            "pollutant": ["NOx"],
            "external_generation_mwh": [100.0],
            "kepco_generation_mwh": [101.0],
            "external_pollutant_mass_kg": [20.0],
            "kepco_pollutant_mass_kg": [22.22],
            "external_ef_kg_per_mwh": [0.2],
            "kepco_ef_kg_per_mwh": [0.22],
            "percent_difference": [10.0],
            "coverage_fraction": [1.0],
        }
    )
    wide = pd.DataFrame(
        {
            "reference_id": ["lee_2025_kosae"],
            "year": [2022],
            "plant": ["Plant"],
            "nox_external_ef_kg_per_mwh": [0.2],
            "nox_kepco_ef_kg_per_mwh": [0.22],
            "nox_percent_difference": [10.0],
        }
    )

    write_comparison_table_images(tidy, wide, tmp_path)

    assert (tmp_path / "plant_level_external_validation_table.svg").exists()
    assert (tmp_path / "plant_level_external_validation_ef_table.svg").exists()
    assert (tmp_path / "plant_level_external_validation_table.png").exists()
    assert (tmp_path / "plant_level_external_validation_ef_table.png").exists()


def test_seo_kim_jeon_is_present_in_catalog() -> None:
    catalog = load_catalog(REFERENCE_DIR)
    assert "seo_2019_bio_heavy_oil" in set(catalog["reference_id"])


def test_seo_rows_cover_2015_2017_fuels_and_pollutants() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    seo = literature.loc[literature["reference_id"].eq("seo_2019_bio_heavy_oil")]
    assert set(seo["data_year"].dropna().astype(int)) == {2015, 2016, 2017}
    assert set(seo["fuel_type"]) == {"oil", "bio_oil_and_diesel"}
    assert {"NOx", "SOx", "TSP", "PM2.5"}.issubset(set(seo["pollutant"]))


def test_seo_reported_and_reference_efs_agree_within_rounding() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    seo = literature.loc[
        literature["reference_id"].eq("seo_2019_bio_heavy_oil")
        & literature["pollutant"].eq("SOx")
        & literature["fuel_type"].eq("oil")
        & literature["data_year"].eq(2015)
    ].iloc[0]
    assert seo["reported_ef_kg_per_mwh"] == pytest.approx(1.314)
    assert seo["reference_ef_kg_per_mwh"] == pytest.approx(1.314)


def test_publication_year_is_not_substituted_for_seo_data_year() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    seo_years = set(
        literature.loc[
            literature["reference_id"].eq("seo_2019_bio_heavy_oil"), "data_year"
        ].astype(int)
    )
    assert 2019 not in seo_years


def test_input_based_factors_do_not_enter_direct_fuel_comparison() -> None:
    project = pd.DataFrame(
        {
            "year": [2022],
            "fuel_type": ["coal"],
            "technology": ["public_generation_boiler"],
            "pollutant": ["NOx"],
            "pollutant_scope": ["NOx"],
            "analysis_variant": ["reported"],
            "ef_kg_per_mwh": [0.1],
        }
    )
    literature = pd.DataFrame(
        {
            "reference_id": ["capss"],
            "source_title": ["CAPSS"],
            "data_year": [2022],
            "fuel_type": ["coal"],
            "technology": ["public_generation_boiler"],
            "pollutant": ["NOx"],
            "pollutant_scope": ["NOx"],
            "normalization_basis": ["fuel_input_kg_per_tonne_coal"],
            "direct_comparator": ["no"],
            "reference_ef_kg_per_mwh": [7.5],
        }
    )
    assert compare_fuel_technology_year(project, literature).empty


def test_national_fuel_average_is_not_plant_level_match() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    motie = literature.loc[literature["reference_id"].eq("motie_2019_lng_coal_clarification")]
    assert set(motie["aggregation_scope"]) == {"national_fuel_fleet"}
    assert motie["plant_group_id"].str.contains("motie_2017").all()


def test_missing_seo_technology_is_explicitly_unknown() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    seo = literature.loc[literature["reference_id"].eq("seo_2019_bio_heavy_oil")]
    assert set(seo["technology"]) == {"unspecified_oil_thermal"}


def test_every_benchmark_has_page_and_table_provenance() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    assert literature["source_page"].notna().all()
    assert literature["source_table"].fillna("").ne("").all()


def test_every_pdf_has_checksum_and_inventory_entry() -> None:
    inventory = load_pdf_inventory(REFERENCE_DIR)
    assert len(inventory) == 7
    assert inventory["sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert "Seo_Kim_Jeon_2019_bio_heavy_oil_EFs.pdf" in set(inventory["filename"])


def test_keei_combined_factor_recalculation_still_matches() -> None:
    literature = load_literature_benchmarks(REFERENCE_DIR)
    dangjin = literature.loc[
        literature["plant_group_id"].eq("keei_dangjin_1_8")
        & literature["pollutant"].eq("combined")
    ].iloc[0]
    assert dangjin["reported_ef_kg_per_mwh"] == pytest.approx(0.680)
    assert dangjin["recalculated_ef_kg_per_mwh"] == pytest.approx(17890000 / 26303000)


def test_lee_exact_plant_year_matches_are_allowed(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    direct = validation_outputs["direct_validation_comparisons"]
    dangjin = direct.loc[
        direct["plant_group_id"].eq("lee_dangjin_1_10")
        & direct["analysis_variant"].eq("reported")
    ]
    assert set(dangjin["pollutant"]) == {"NOx", "SOx", "TSP", "combined"}
    assert set(dangjin["comparison_class"]) == {"B_plant_pipeline_validation"}
    assert dangjin["comparison_status"].eq(INCLUDED_DIRECT).all()
    assert dangjin["coverage_fraction"].eq(1).all()


def test_dangjin_reproduces_within_rounding_tolerance(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    direct = validation_outputs["direct_validation_comparisons"]
    dangjin = direct.loc[
        direct["plant_group_id"].eq("lee_dangjin_1_10")
        & direct["analysis_variant"].eq("reported")
    ]
    assert dangjin["generation_difference_mwh"].abs().max() < 1
    assert dangjin["mass_difference_kg"].abs().max() < 100
    assert dangjin["percent_difference"].abs().max() < 0.02


def test_keei_plant_factor_cannot_match_generic_fuel_technology_group() -> None:
    project = pd.DataFrame(
        {
            "year": [2016],
            "fuel_type": ["coal"],
            "technology": ["conventional_steam_turbine"],
            "pollutant": ["combined"],
            "pollutant_scope": ["NOx+SOx+TSP"],
            "analysis_variant": ["reported"],
            "generation_mwh_sum": [100.0],
            "pollutant_mass_kg_sum": [50.0],
            "coverage_fraction": [1.0],
            "calendar_month_coverage_fraction": [1.0],
            "complete_calendar_year": [True],
            "missing_months": [""],
        }
    )
    result = compare_fuel_technology_year(project, reviewed_literature())
    assert result.empty


def test_motie_coal_is_one_fuel_fleet_check_not_an_igcc_match(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    checks = validation_outputs["aggregate_consistency_checks"]
    coal = checks.loc[
        checks["required_fuel"].eq("coal")
        & checks["analysis_variant"].eq("reported")
    ]
    assert len(coal) == 4
    assert coal["comparison_class"].eq("C_aggregate_consistency_check").all()
    assert coal["operator_coverage"].eq("kepco_subsidiaries_only").all()
    assert coal["technology_project"].str.contains(
        "conventional_steam_turbine"
    ).all()
    assert coal["technology_project"].str.contains(
        "integrated_gasification_combined_cycle"
    ).all()


def test_motie_lng_is_one_fuel_fleet_check_not_chp_or_ngcc_rows(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    checks = validation_outputs["aggregate_consistency_checks"]
    lng = checks.loc[
        checks["required_fuel"].eq("natural_gas")
        & checks["analysis_variant"].eq("reported")
    ]
    assert len(lng) == 1
    assert lng.iloc[0]["pollutant"] == "NOx"
    assert "cogeneration_chp" in lng.iloc[0]["technology_project"]
    assert "combined_cycle_gas_turbine" in lng.iloc[0]["technology_project"]


def test_seo_produces_no_direct_percent_error_rows(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    direct = validation_outputs["direct_validation_comparisons"]
    assert direct.loc[direct["reference_id"].eq("seo_2019_bio_heavy_oil")].empty
    contextual = validation_outputs["contextual_literature_benchmarks"]
    seo = contextual.loc[contextual["reference_id"].eq("seo_2019_bio_heavy_oil")]
    assert not seo.empty
    assert seo["comparison_class"].eq("D_contextual_benchmark").all()
    assert not any("percent_difference" in column for column in contextual.columns)


@pytest.mark.parametrize("reference_id", ["capss_manual_vii_2025", "yu_2021_ajae"])
def test_fuel_input_sources_cannot_enter_kg_per_mwh_validation(
    validation_outputs: dict[str, pd.DataFrame], reference_id: str
) -> None:
    direct = validation_outputs["direct_validation_comparisons"]
    aggregate = validation_outputs["aggregate_consistency_checks"]
    assert direct.loc[direct["reference_id"].eq(reference_id)].empty
    assert aggregate.loc[aggregate["reference_id"].eq(reference_id)].empty
    literature = reviewed_literature()
    source = literature.loc[literature["reference_id"].eq(reference_id)]
    assert source["comparison_class"].eq("X_not_comparable").all()


def test_pm25_cannot_match_tsp_in_production_outputs(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    direct = validation_outputs["direct_validation_comparisons"]
    aggregate = validation_outputs["aggregate_consistency_checks"]
    assert "PM2.5" not in set(direct["pollutant"])
    assert "PM2.5" not in set(aggregate["pollutant"])
    rejected = validation_outputs["rejected_or_noncomparable_comparisons"]
    assert "pm25_not_tsp" in set(rejected["exclusion_reason"])


def test_historical_fuel_ambiguity_causes_exclusion() -> None:
    literature = reviewed_literature()
    external = literature.loc[
        literature["plant_group_id"].eq("lee_dangjin_1_10")
        & literature["pollutant"].eq("NOx")
    ]
    project = pd.DataFrame(
        {
            "reference_id": ["lee_2025_kosae"],
            "plant_group_id": ["lee_dangjin_1_10"],
            "year": [2022],
            "pollutant": ["NOx"],
            "pollutant_scope": ["NOx"],
            "analysis_variant": ["reported"],
            "generation_mwh_sum": [100.0],
            "pollutant_mass_kg_sum": [10.0],
            "ef_kg_per_mwh": [0.1],
            "coverage_fraction": [1.0],
            "n_boundary_units": [10],
            "complete_calendar_year": [True],
            "missing_months": [""],
            "boundary_match_status": ["exact"],
            "project_plant_name": ["Dangjin"],
            "fuel_type": ["coal;oil"],
            "technology": ["conventional_steam_turbine"],
        }
    )
    attempt = compare_to_literature(project, external).iloc[0]
    assert attempt["comparison_status"] == "excluded_historical_fuel_ambiguity"
    assert attempt["comparison_class"] == "D_contextual_benchmark"
    assert attempt["exclusion_reason"] == "historical_fuel_mapping_unresolved"


def test_every_rejected_comparison_has_an_exclusion_reason(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    rejected = validation_outputs["rejected_or_noncomparable_comparisons"]
    assert not rejected.empty
    assert rejected["exclusion_reason"].notna().all()
    assert rejected["exclusion_reason"].astype(str).str.strip().ne("").all()


def test_existing_complete_lee_results_are_preserved(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    direct = validation_outputs["direct_validation_comparisons"]
    lee = direct.loc[
        direct["reference_id"].eq("lee_2025_kosae")
        & direct["analysis_variant"].eq("reported")
    ]
    expected_plants = {
        "Dangjin",
        "Yeongheung",
        "Yeosu",
        "SamcheokGreen",
        "Donghae",
        "Samcheonpo",
        "Hadong",
    }
    assert expected_plants.issubset(set(lee["plant_name_en"]))
    assert lee["comparison_class"].eq("B_plant_pipeline_validation").all()


def test_required_output_classes_and_reconciliation_fields(
    validation_outputs: dict[str, pd.DataFrame],
) -> None:
    assert set(validation_outputs) == {
        "direct_validation_comparisons",
        "aggregate_consistency_checks",
        "contextual_literature_benchmarks",
        "rejected_or_noncomparable_comparisons",
        "plant_input_reconciliation",
        "literature_coverage_matrix",
    }
    reconciliation = validation_outputs["plant_input_reconciliation"]
    assert {
        "external_generation_mwh",
        "kepco_generation_mwh",
        "generation_difference_mwh",
        "external_pollutant_mass_kg",
        "kepco_pollutant_mass_kg",
        "mass_difference_kg",
        "external_ef_kg_per_mwh",
        "kepco_ef_kg_per_mwh",
        "ef_difference_kg_per_mwh",
        "coverage_fraction",
        "missing_months",
    }.issubset(reconciliation.columns)
