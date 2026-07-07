from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.retirement_crosswalk import (
    EVIDENCE_COLUMNS,
    REFERENCE_COLUMNS,
    apply_retirement_crosswalk,
    load_retirement_crosswalk,
)


def mapping(
    *,
    scope: str,
    unit: str = "",
    date: str = "2030-12-31",
    status: str = "planned",
) -> dict[str, str]:
    return {
        "subsidiary_company": "Test Power",
        "plant_name": "Test Plant",
        "scope": scope,
        "reporting_unit_id": unit,
        "plant_closing_date": date,
        "plant_closing_date_status": status,
        "evidence_id": "e1",
        "notes": "test",
    }


def source_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "subsidiary_company": ["Test Power", "Test Power"],
            "plant_name": ["Test Plant", "Test Plant"],
            "reporting_unit_id": ["test:1", "test:2"],
            "plant_closing_date": [pd.NaT, pd.NaT],
        }
    )


def test_unit_mapping_overrides_explicit_plant_fallback() -> None:
    crosswalk = pd.DataFrame(
        [
            mapping(scope="plant", date="2035-12-31"),
            mapping(scope="unit", unit="test:1", date="2030-12-31"),
        ],
        columns=REFERENCE_COLUMNS,
    )
    crosswalk["plant_closing_date"] = pd.to_datetime(crosswalk["plant_closing_date"])

    result = apply_retirement_crosswalk(source_rows(), crosswalk)

    assert result.loc[0, "plant_closing_date"] == pd.Timestamp("2030-12-31")
    assert result.loc[1, "plant_closing_date"] == pd.Timestamp("2035-12-31")
    assert result["plant_closing_date_status"].tolist() == ["planned", "planned"]


def test_unit_mapping_never_propagates_to_sibling_unit() -> None:
    crosswalk = pd.DataFrame(
        [mapping(scope="unit", unit="test:1")], columns=REFERENCE_COLUMNS
    )
    crosswalk["plant_closing_date"] = pd.to_datetime(crosswalk["plant_closing_date"])

    result = apply_retirement_crosswalk(source_rows(), crosswalk)

    assert result.loc[0, "plant_closing_date"] == pd.Timestamp("2030-12-31")
    assert pd.isna(result.loc[1, "plant_closing_date"])
    assert pd.isna(result.loc[1, "plant_closing_date_status"])


def test_unknown_unit_fails_loudly() -> None:
    crosswalk = pd.DataFrame(
        [mapping(scope="unit", unit="test:missing")], columns=REFERENCE_COLUMNS
    )
    crosswalk["plant_closing_date"] = pd.to_datetime(crosswalk["plant_closing_date"])

    with pytest.raises(ValueError, match="unknown reporting units"):
        apply_retirement_crosswalk(source_rows(), crosswalk)


def test_unreviewed_existing_closing_date_fails_loudly() -> None:
    source = source_rows()
    source.loc[0, "plant_closing_date"] = "2029-01-01"
    unrelated = pd.DataFrame(
        [
            {
                **mapping(scope="unit", unit="other:1"),
                "subsidiary_company": "Other Power",
                "plant_name": "Other Plant",
            }
        ],
        columns=REFERENCE_COLUMNS,
    )
    unrelated["plant_closing_date"] = pd.to_datetime(unrelated["plant_closing_date"])

    with pytest.raises(ValueError, match="reviewed retirement mapping"):
        apply_retirement_crosswalk(source, unrelated)


def test_loader_requires_valid_status_and_evidence(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.csv"
    evidence_path = tmp_path / "evidence.csv"
    bad = mapping(scope="unit", unit="test:1", status="estimated")
    pd.DataFrame([bad], columns=REFERENCE_COLUMNS).to_csv(reference_path, index=False)
    pd.DataFrame(
        [["e1", "title", "https://example.com", "2025-01-01", "2025-01-02", "text"]],
        columns=EVIDENCE_COLUMNS,
    ).to_csv(evidence_path, index=False)

    with pytest.raises(ValueError, match="Unknown plant_closing_date_status"):
        load_retirement_crosswalk(reference_path, evidence_path)
