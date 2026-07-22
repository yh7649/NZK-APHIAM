from __future__ import annotations

from pathlib import Path
import shutil

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
    <표 2-3> 비산업 연소 배출원 연료별 배출계수
    <표 2-3> 비산업 연소 배출원 연료별 배출계수(계속)
    """
    assert scraper.extract_table_titles(text) == [
        ("2-3", "비산업 연소 배출원 연료별 배출계수"),
        ("2-3", "비산업 연소 배출원 연료별 배출계수"),
    ]


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
