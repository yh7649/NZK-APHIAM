from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.air_quality.inmap.nonpower_spatial import (
    SpatialSurrogateError,
    build_capss_admin_surrogates,
    build_monitor_coordinate_surrogates,
    build_spatial_readiness,
    expand_admin_surrogates_for_poc,
    load_spatial_geometry,
)


def test_capss_admin_surrogate_weights_preserve_inventory_pollutant_mass() -> None:
    capss = pd.DataFrame(
        [
            {
                "year": 2021,
                "province_name_ko": "서울특별시",
                "sub_district_name_ko": "서울",
                "source_category": "생산공정",
                "source_midcategory": "제철제강업",
                "source_subcategory": "고로 장입",
                "pollutant": "NOx",
                "emissions_kg": 25.0,
            },
            {
                "year": 2021,
                "province_name_ko": "충청남도",
                "sub_district_name_ko": "당진시",
                "source_category": "생산공정",
                "source_midcategory": "제철제강업",
                "source_subcategory": "고로 장입",
                "pollutant": "NOx",
                "emissions_kg": 75.0,
            },
        ]
    )
    crosswalk = pd.DataFrame(
        [
            {
                "crosswalk_id": "cw1",
                "inventory_id": "ind_steel_bf_bof",
                "capss_major_category": "생산공정",
                "capss_intermediate_category": "제철제강업",
                "capss_minor_category": "고로 장입",
                "match_status": "documented_proxy",
            }
        ]
    )
    weights, audit = build_capss_admin_surrogates(capss, crosswalk, base_year=2021)
    assert weights["weight"].sum() == pytest.approx(1.0)
    assert sorted(weights["weight"]) == pytest.approx([0.25, 0.75])
    assert audit.loc[0, "status"] == "admin_weights_ready_geometry_missing"


def test_spatial_geometry_fails_closed_on_invalid_weights(tmp_path: Path) -> None:
    path = tmp_path / "geometry.csv"
    pd.DataFrame(
        [
            {
                "spatial_id": "g1",
                "inventory_id": "activity",
                "geometry_type": "Grid",
                "latitude": 36.0,
                "longitude": 127.0,
                "weight": 0.8,
                "stack_height_m": "",
                "stack_diameter_m": "",
                "stack_temperature_k": "",
                "stack_velocity_m_s": "",
                "status": "candidate",
                "source_id": "test",
                "notes": "",
            }
        ]
    ).to_csv(path, index=False)
    with pytest.raises(SpatialSurrogateError, match="sum to one"):
        load_spatial_geometry(path)


def test_candidate_geometry_does_not_clear_production_block() -> None:
    inventory = pd.DataFrame([{"inventory_id": "activity", "priority": "P1"}])
    crosswalk = pd.DataFrame(
        [
            {
                "inventory_id": "activity",
                "capss_major_category": "생산공정",
            }
        ]
    )
    admin_audit = pd.DataFrame(
        [
            {
                "inventory_id": "activity",
                "status": "admin_weights_ready_geometry_missing",
            }
        ]
    )
    geometry = pd.DataFrame(
        [{"inventory_id": "activity", "status": "candidate"}]
    )
    readiness = build_spatial_readiness(
        inventory, crosswalk, admin_audit, geometry
    )
    assert not readiness.loc[0, "coordinate_geometry_available"]
    assert readiness.loc[0, "routing_status"].startswith("blocked_")


def test_poc_spatial_surrogate_fills_sector_and_uses_monitor_coordinates() -> None:
    weights = pd.DataFrame(
        [
            {
                "inventory_id": "donor",
                "pollutant": pollutant,
                "province_name_ko": "서울특별시",
                "sub_district_name_ko": "강남구",
                "base_emissions_kg": 10.0,
                "weight": 1.0,
                "base_year": 2021,
                "surrogate_source": "test",
                "geometry_status": "names_only",
                "analytical_use_permitted": False,
            }
            for pollutant in ("VOCs", "NOx", "NH3", "SOx", "PM2.5")
        ]
    )
    inventory = pd.DataFrame([{"inventory_id": "target", "priority": "P1"}])
    expanded = expand_admin_surrogates_for_poc(weights, inventory)
    target = expanded.loc[expanded["inventory_id"].eq("target")]
    assert target["pollutant"].nunique() == 5
    assert set(target["allocation_origin"]) == {
        "national_capss_pollutant_fallback_missing_inventory_crosswalk"
    }

    stations = pd.DataFrame(
        [
            {
                "address": "서울특별시 강남구 테헤란로 1",
                "latitude": 37.5,
                "longitude": 127.0,
                "station_name": "강남",
            }
        ]
    )
    surrogate, audit = build_monitor_coordinate_surrogates(target, stations)
    assert surrogate["latitude"].eq(37.5).all()
    assert surrogate["longitude"].eq(127.0).all()
    assert surrogate.groupby(["inventory_id", "pollutant"])["weight"].sum().eq(1.0).all()
    assert audit["district_monitor_centroid_count"].eq(1).all()
    assert not surrogate["analytical_use_permitted"].any()
