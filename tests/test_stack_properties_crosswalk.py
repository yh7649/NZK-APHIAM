from __future__ import annotations

import pandas as pd

from nzk_aphiam.config.paths import PROJECT_ROOT
from nzk_aphiam.data.scrape.references.stack_properties import (
    EVIDENCE_COLUMNS,
    REFERENCE_COLUMNS,
    UNIT_MAP_COLUMNS,
)

CROSSWALK_DIR = PROJECT_ROOT / "docs" / "references" / "crosswalk"
STACK_PROPERTIES_PATH = CROSSWALK_DIR / "stack_properties.csv"
STACK_UNIT_MAP_PATH = CROSSWALK_DIR / "stack_unit_map.csv"
STACK_EVIDENCE_PATH = CROSSWALK_DIR / "stack_properties_official_evidence.csv"
KEPCO_PANEL_PATH = (
    PROJECT_ROOT / "data" / "processed" / "kepco" / "kepco_monthly_generation_emissions.csv"
)


def load_stack_reference() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    reference = pd.read_csv(STACK_PROPERTIES_PATH, dtype="string", keep_default_na=False)
    unit_map = pd.read_csv(STACK_UNIT_MAP_PATH, dtype="string", keep_default_na=False)
    evidence = pd.read_csv(STACK_EVIDENCE_PATH, dtype="string", keep_default_na=False)
    return reference, unit_map, evidence


def test_stack_crosswalk_schema_keys_and_evidence_links() -> None:
    reference, unit_map, evidence = load_stack_reference()

    assert list(reference.columns) == REFERENCE_COLUMNS
    assert list(unit_map.columns) == UNIT_MAP_COLUMNS
    assert list(evidence.columns) == EVIDENCE_COLUMNS
    assert reference["stack_id"].ne("").all()
    assert not reference["stack_id"].duplicated().any()
    assert evidence["evidence_id"].ne("").all()
    assert not evidence["evidence_id"].duplicated().any()
    assert set(reference["match_status"]) == {"matched", "unmatched"}
    assert set(reference["evidence_id"]).issubset(set(evidence["evidence_id"]))
    assert set(unit_map["stack_id"]).issubset(set(reference["stack_id"]))


def test_matched_rows_have_physical_stack_properties_and_unmatched_rows_do_not() -> None:
    reference, _, _ = load_stack_reference()
    property_columns = [
        "stack_height_m",
        "stack_diameter_m",
        "exit_temp_c",
        "flue_gas_velocity_m_s",
        "stack_latitude",
        "stack_longitude",
    ]

    matched = reference["match_status"].eq("matched")
    assert reference.loc[matched, property_columns].ne("").all().all()
    for column in property_columns:
        pd.to_numeric(reference.loc[matched, column], errors="raise")

    unmatched = reference["match_status"].eq("unmatched")
    assert reference.loc[unmatched, property_columns].eq("").all().all()
    assert reference.loc[unmatched, ["subsidiary_company", "plant_name"]].to_dict("records") == [
        {"subsidiary_company": "Korea South-East Power", "plant_name": "Yeongdong"}
    ]


def test_every_current_kepco_coal_plant_has_stack_reference_status() -> None:
    reference, unit_map, _ = load_stack_reference()
    panel = pd.read_csv(
        KEPCO_PANEL_PATH,
        dtype="string",
        keep_default_na=False,
        usecols=["subsidiary_company", "plant_name", "fuel_type", "reporting_unit_id"],
    )
    coal = panel[panel["fuel_type"].eq("coal")]

    coal_plants = set(
        map(tuple, coal[["subsidiary_company", "plant_name"]].drop_duplicates().to_numpy())
    )
    stack_plants = set(
        map(tuple, reference[["subsidiary_company", "plant_name"]].drop_duplicates().to_numpy())
    )
    assert coal_plants - stack_plants == set()

    statuses = {
        key: set(group["match_status"])
        for key, group in reference.groupby(["subsidiary_company", "plant_name"])
    }
    assert all(status_set <= {"matched", "unmatched"} for status_set in statuses.values())
    assert statuses[("Korea South-East Power", "Yeongdong")] == {"unmatched"}

    coal_reporting_units = set(coal["reporting_unit_id"]) - {""}
    referenced_units = set(reference["reporting_unit_id"]) - {""}
    mapped_units = set(unit_map["reporting_unit_id"]) - {""}
    assert referenced_units.issubset(coal_reporting_units)
    assert mapped_units.issubset(coal_reporting_units)


def test_crea_aliases_resolve_to_project_canonical_plants() -> None:
    reference, _, _ = load_stack_reference()

    assert "Samcheok GreenPower" not in set(reference["plant_name"])
    assert ("Korea Southern Power", "Samcheok") in set(
        map(tuple, reference[["subsidiary_company", "plant_name"]].to_numpy())
    )
    assert "Shin Seocheon" not in set(reference["plant_name"])
    assert ("Korea Midland Power", "Seocheon") in set(
        map(tuple, reference[["subsidiary_company", "plant_name"]].to_numpy())
    )
