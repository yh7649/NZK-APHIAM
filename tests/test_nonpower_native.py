from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.data.process.nonpower_native import (
    apply_poc_activity_assumptions,
    build_approved_factor_projection,
    build_candidate_factor_screening_projection,
    build_maximum_coverage_projection,
    load_native_crosswalk,
    map_native_activity,
)


def _activity() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": "nzk",
                "source_scenario": "CORE_9_NZ",
                "region": "South Korea",
                "year": 2025,
                "record_type": "output",
                "sector_type": "supplysector",
                "sector": "iron and steel",
                "subsector_type": "subsector",
                "subsector": "BLASTFUR",
                "technology_type": "technology",
                "technology": "BLASTFUR",
                "node_type": "output-primary",
                "node": "iron and steel",
                "activity": 1.5,
                "activity_unit": "Mt",
            }
        ]
    )


def test_native_crosswalk_maps_mt_to_tonnes() -> None:
    crosswalk = load_native_crosswalk(
        Path("docs/references/nonpower_emissions/gcam_kaist_native_activity_crosswalk.csv")
    )
    canonical, audit, unmapped = map_native_activity(_activity(), crosswalk)
    row = canonical.loc[canonical["inventory_id"].eq("ind_steel_bf_bof")].iloc[0]
    assert row["activity"] == pytest.approx(1_500_000.0)
    assert row["activity_unit"] == "tonne crude steel"
    assert audit.loc[
        audit["mapping_id"].eq("native_steel_blastfurnace"), "matched_native_rows"
    ].iloc[0] == 1
    assert unmapped.empty


def _inventory() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "inventory_id": "ind_steel_bf_bof",
                "gcam_cluster": "industry",
                "gcam_sector": "steel",
                "gcam_technology": "blast_furnace_basic_oxygen_furnace",
            }
        ]
    )


def _factors(ready: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    factors = pd.DataFrame(
        [
            {
                "record_id": "EF1",
                "production_ready": ready,
                "pollutant": "NOx",
                "ef_value": "2.5",
                "unit": "kg/ton-crude-steel",
            }
        ]
    )
    links = pd.DataFrame(
        [
            {
                "record_id": "EF1",
                "inventory_id": "ind_steel_bf_bof",
                "pollutant": "NOx",
                "production_ready": ready,
                "match_status": "exact",
            }
        ]
    )
    return factors, links


def test_approved_factor_projection_applies_only_ready_compatible_factor() -> None:
    crosswalk = load_native_crosswalk(
        Path("docs/references/nonpower_emissions/gcam_kaist_native_activity_crosswalk.csv")
    )
    canonical, _, _ = map_native_activity(_activity(), crosswalk)
    factors, links = _factors("true")
    projected, gaps = build_approved_factor_projection(
        canonical, _inventory(), factors, links
    )
    assert gaps.empty
    assert projected.loc[0, "projected_emissions_kg"] == pytest.approx(3_750_000.0)
    assert projected.loc[0, "factor_production_ready"]


def test_unapproved_factor_is_reported_as_gap_not_used() -> None:
    crosswalk = load_native_crosswalk(
        Path("docs/references/nonpower_emissions/gcam_kaist_native_activity_crosswalk.csv")
    )
    canonical, _, _ = map_native_activity(_activity(), crosswalk)
    factors, links = _factors("false")
    projected, gaps = build_approved_factor_projection(
        canonical, _inventory(), factors, links
    )
    assert projected.empty
    assert set(gaps["gap_reason"]) == {"no_production_ready_factor_link"}


def test_unreviewed_activity_conversion_blocks_approved_factor() -> None:
    crosswalk = load_native_crosswalk(
        Path("docs/references/nonpower_emissions/gcam_kaist_native_activity_crosswalk.csv")
    )
    canonical, _, _ = map_native_activity(_activity(), crosswalk)
    canonical["activity_mapping_production_ready"] = False
    factors, links = _factors("true")
    projected, gaps = build_approved_factor_projection(
        canonical, _inventory(), factors, links
    )
    assert projected.empty
    assert set(gaps["gap_reason"]) == {
        "activity_mapping_requires_conversion_review"
    }


def test_candidate_screening_uses_median_compatible_unapproved_factors() -> None:
    crosswalk = load_native_crosswalk(
        Path("docs/references/nonpower_emissions/gcam_kaist_native_activity_crosswalk.csv")
    )
    canonical, _, _ = map_native_activity(_activity(), crosswalk)
    factors = pd.DataFrame(
        [
            {
                "record_id": "EF1",
                "production_ready": "false",
                "pollutant": "NOx",
                "ef_value": "2.0",
                "unit": "kg/ton-crude-steel",
            },
            {
                "record_id": "EF2",
                "production_ready": "false",
                "pollutant": "NOx",
                "ef_value": "4.0",
                "unit": "kg/ton-crude-steel",
            },
        ]
    )
    links = pd.DataFrame(
        [
            {
                "record_id": record_id,
                "inventory_id": "ind_steel_bf_bof",
                "pollutant": "NOx",
                "production_ready": "false",
                "match_status": "documented_proxy",
            }
            for record_id in ("EF1", "EF2")
        ]
    )
    projected, gaps = build_candidate_factor_screening_projection(
        canonical, _inventory(), factors, links
    )
    assert gaps.empty
    assert projected.loc[0, "emission_factor_kg_per_activity"] == pytest.approx(
        3.0
    )
    assert projected.loc[0, "projected_emissions_kg"] == pytest.approx(
        4_500_000.0
    )
    assert projected.loc[0, "candidate_factor_count"] == 2
    assert not projected.loc[0, "factor_production_ready"]


def test_poc_assumptions_enable_previously_blocked_native_selector() -> None:
    crosswalk = load_native_crosswalk(
        Path("docs/references/nonpower_emissions/gcam_kaist_native_activity_crosswalk.csv")
    )
    assumptions = pd.read_csv(
        "docs/references/nonpower_emissions/"
        "gcam_nzk_poc_activity_conversion_assumptions.csv",
        dtype=str,
    )
    converted = apply_poc_activity_assumptions(crosswalk, assumptions)
    road = converted.loc[converted["mapping_id"].eq("gap_road_hybrid")].iloc[0]
    assert road["include_in_emissions_model"] == "true"
    assert float(road["native_to_canonical_multiplier"]) == pytest.approx(
        1_000_000_000 / 1.5
    )
    assert road["match_status"] == "maximum_coverage_poc_assumption"


def test_maximum_coverage_assigns_every_inmap_pollutant_with_ranked_fallbacks() -> None:
    activity = pd.DataFrame(
        [
            {
                "scenario": "nzk",
                "source_scenario": "CORE_9_NZ",
                "region": "South Korea",
                "year": 2025,
                "inventory_id": "activity_1",
                "activity": 100.0,
                "activity_unit": "tonne crude steel",
                "mapping_ids": "mapping_1",
            }
        ]
    )
    inventory = pd.DataFrame(
        [{"inventory_id": "activity_1", "gcam_technology": "test_technology"}]
    )
    factors = pd.DataFrame(
        [
            {
                "record_id": f"EF_{pollutant}",
                "pollutant": pollutant,
                "ef_value": value,
                "unit": unit,
            }
            for pollutant, value, unit in [
                ("NOx", 2.0, "kg/ton-crude-steel"),
                ("NH3", 3.0, "kg/animal-year"),
                ("PM2.5", 4.0, "kg/animal-year"),
                ("SOx", 5.0, "kg/animal-year"),
                ("VOCs", 6.0, "kg/animal-year"),
            ]
        ]
    )
    links = pd.DataFrame(
        [
            {
                "record_id": "EF_NOx",
                "inventory_id": "activity_1",
                "match_status": "documented_proxy",
            }
        ]
    )
    capss = pd.DataFrame(
        [
            {
                "inventory_id": "activity_1",
                "pollutant": "SOx",
                "base_emissions_kg": 500.0,
            }
        ]
    )
    projected, audit = build_maximum_coverage_projection(
        activity, inventory, factors, links, capss
    )
    assert set(projected["pollutant"]) == {"VOCs", "NOx", "NH3", "SOx", "PM2.5"}
    methods = projected.set_index("pollutant")["factor_method"]
    assert methods["NOx"] == "median_denominator_compatible_linked_factor_poc"
    assert methods["SOx"] == "capss_base_emissions_per_gcam_activity_poc"
    assert (
        methods["NH3"]
        == "global_pollutant_median_ignoring_sector_and_denominator_poc"
    )
    assert len(audit) == 5
    assert not projected["analytical_use_permitted"].any()
