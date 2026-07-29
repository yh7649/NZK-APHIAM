from __future__ import annotations

from pathlib import Path
import shutil
from types import SimpleNamespace

import pandas as pd

from nzk_aphiam.data.process import nonpower_emission_factors as factors
from nzk_aphiam.data.scrape.capss import nonpower_emission_factors as scraper

REFERENCE_DIR = Path("docs/references/nonpower_emissions")


def test_first_pass_factor_collection_validates() -> None:
    result = factors.validate_collection(REFERENCE_DIR)
    assert result.errors.empty
    assert len(result.factors) == 912
    assert set(result.factors["pollutant"]) == {
        "CO",
        "NH3",
        "NOx",
        "PM10",
        "PM2.5",
        "SOx",
        "TSP",
        "VOCs",
    }


def test_every_factor_has_an_inventory_candidate_link() -> None:
    result = factors.validate_collection(REFERENCE_DIR)
    assert set(result.factors["record_id"]) == set(result.links["record_id"])
    assert result.links["inventory_id"].nunique() == 41
    cooking = result.factors["subsector"].eq("Commercial cooking")
    cooking_ids = set(
        result.links.loc[result.links["record_id"].isin(result.factors.loc[cooking, "record_id"]), "inventory_id"]
    )
    assert cooking_ids == {"aqs_commercial_cooking_aerosol"}


def test_superseded_capss_vi_rows_are_never_production_ready() -> None:
    result = factors.validate_collection(REFERENCE_DIR)
    capss_vi = result.factors.loc[
        result.factors["source_id"].eq("capss_handbook_vi_mirror")
    ]
    assert len(capss_vi) == 887
    assert capss_vi["review_status"].eq("superseded_pending_capss_vii_diff").all()
    assert capss_vi["production_ready"].eq("false").all()


def test_duplicate_mapping_rule_is_rejected(tmp_path: Path) -> None:
    reference_dir = tmp_path / "references"
    shutil.copytree(REFERENCE_DIR, reference_dir)
    path = reference_dir / factors.MAPPING_RULE_FILE
    rules = pd.read_csv(path, dtype=str, keep_default_na=False)
    duplicate = rules.iloc[[0]].copy()
    duplicate["rule_id"] = "duplicate_rule"
    pd.concat([rules, duplicate], ignore_index=True).to_csv(path, index=False)
    result = factors.validate_collection(reference_dir)
    assert "factor_mapping_rule_count" in set(result.errors["code"])


def test_build_writes_canonical_outputs_and_diagnostics(tmp_path: Path) -> None:
    output_dir = tmp_path / "processed"
    diagnostic_dir = tmp_path / "diagnostics"
    metadata = factors.build_collection(REFERENCE_DIR, output_dir, diagnostic_dir)
    assert metadata["factor_rows"] == 912
    assert metadata["production_ready_rows"] == 0
    assert set(factors.OUTPUT_FILES.values()) <= {path.name for path in output_dir.iterdir()}
    assert {
        "ef_collection_validation_issues.csv",
        "ef_collection_validation_summary.json",
        "nonpower_ef_collection_gaps.csv",
        "nonpower_ef_inventory_coverage.csv",
        "nonpower_ef_inventory_gaps.csv",
        "nonpower_ef_sector_coverage.csv",
    } <= {path.name for path in diagnostic_dir.iterdir()}


def test_capss_table_title_extraction_ignores_prose_references() -> None:
    text = """
    배출계수는 <표 2-3>과 같다.
    <표 8-38>은 건설장비 종류별 물질별 배출계수이다.
    <표 12-3>과 <표 12-4>는 배출계수 산정에 사용한다.
    <표 2-3> 비산업 연소 배출원 연료별 배출계수
    <표 2-3> 비산업 연소 배출원 연료별 배출계수(계속)
    """
    assert scraper.extract_table_titles(text) == [
        ("2-3", "비산업 연소 배출원 연료별 배출계수"),
        ("2-3", "비산업 연소 배출원 연료별 배출계수"),
    ]


def test_capss_standard_table_normalization_preserves_formulas_and_units() -> None:
    matrix = [
        ["소분류", "사용 연료", "배출계수", "", ""],
        [None, None, "PM-2.5", "SOx", "NOx"],
        [
            "1 2 3종 (보일러)",
            "비민수용\n무연탄\nB-C유",
            "79.8958c\n0.57715S +\n0.19066c",
            "19.5Sb\n14.3Sb",
            "5.83b\n6.64b",
        ],
    ]
    rows = scraper._normalized_candidates(
        target_id="target",
        table_id="2-3",
        title="배출계수",
        pdf_page=50,
        inventory_ids="bld_commercial_space_heat",
        matrix=matrix,
        source_unit_text=(
            "(단위: 석탄·고형연료=㎏/ton, 유류·LPG=㎏/㎘, LNG=㎏/천㎥)"
        ),
    )
    assert len(rows) == 6
    assert {row["source_label"] for row in rows} == {"비민수용 무연탄", "B-C유"}
    formula = next(
        row for row in rows if row["pollutant"] == "PM2.5" and row["source_label"] == "B-C유"
    )
    assert formula["ef_expression"] == "0.57715S + 0.19066"
    assert formula["unit"] == "kg/kL-fuel"
    assert formula["alignment_status"] == "aligned"


def test_capss_single_pollutant_data_rows_are_not_mistaken_for_headers() -> None:
    road_formula_matrix = [
        ["분류", "연료", "물질", "실적용연식", "배출계수"],
        ["승용", "휘발유", "NOx", "2009년 이후", "0.004×V"],
    ]
    assert scraper._factor_header(road_formula_matrix) is None


def test_capss_candidate_mapping_stays_within_declared_target_scope() -> None:
    crosswalk = pd.read_csv(
        REFERENCE_DIR / "gcam_capss_nonpower_crosswalk.csv",
        dtype=str,
        keep_default_na=False,
    )
    airport_row = SimpleNamespace(
        table_id="8-22",
        title="지상조업장비 공항별 배출계수",
        source_category="",
        source_label="국내선 공항",
        target_inventory_ids="trn_aviation_passenger_lto|trn_aviation_freight_lto",
    )
    inventory_ids, status = scraper._candidate_inventory_match(airport_row, crosswalk)
    assert inventory_ids == ""
    assert status == "unresolved"

    charcoal_row = SimpleNamespace(
        table_id="13-17",
        title="생물성 연소-숯가마 배출원 물질별 배출계수",
        source_category="",
        source_label="숯가마",
        target_inventory_ids="aqs_charcoal_kiln|aqs_open_biomass_burning",
    )
    inventory_ids, status = scraper._candidate_inventory_match(charcoal_row, crosswalk)
    assert inventory_ids == "aqs_charcoal_kiln"
    assert status == "capss_crosswalk_text_match"


def test_capss_scrape_targets_cover_all_direct_inventory_activities() -> None:
    targets, inventory = scraper.load_targets(scraper.DEFAULT_TARGET_FILE, REFERENCE_DIR)
    targeted = {
        inventory_id
        for value in targets["inventory_ids"]
        for inventory_id in value.split("|")
        if inventory_id
    }
    expected_untargeted = {
        "ene_hydrogen_electrolysis",
        "trn_rail_electric_freight",
        "trn_rail_electric_passenger",
    }
    assert set(inventory["inventory_id"]) - targeted == expected_untargeted
