from __future__ import annotations

import pandas as pd

from nzk_aphiam.data.audit.thermal.auditor import append_audit_columns, audit_subsidiary
from nzk_aphiam.data.clean.thermal.schema import COMBINED_THERMAL_OUTPUT_COLUMNS


def make_row(
    *,
    date: str = "2025-01-01",
    plant_name: str = "Test Plant",
    plant_number: float = 1,
    unit_name: str = "1",
    energy_generated_mwh: float = 100.0,
    energy_capacity_mw: float = 10.0,
    nox: float = 1.5,
    sox: float = 2.0,
    dust_tsp: float = 0.5,
    energy_type: str = "coal",
    row_status: str = "active_reported",
) -> dict[str, object]:
    row = {column: pd.NA for column in COMBINED_THERMAL_OUTPUT_COLUMNS}
    row.update(
        {
            "date": date,
            "plant_name": plant_name,
            "plant_number": plant_number,
            "original_korean_unit_name": unit_name,
            "energy_type": energy_type,
            "energy_generated_mwh": energy_generated_mwh,
            "energy_capacity_mw": energy_capacity_mw,
            "nox": nox,
            "sox": sox,
            "dust_tsp": dust_tsp,
            "row_status": row_status,
        }
    )
    return row


def make_data(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COMBINED_THERMAL_OUTPUT_COLUMNS)


def test_duplicate_unit_month_flagged_critical() -> None:
    data = make_data([make_row(), make_row()])
    result = audit_subsidiary("test", data)

    codes = set(result.flags["issue_code"])
    assert "duplicate_unit_month" in codes
    assert (
        result.flags.loc[result.flags["issue_code"] == "duplicate_unit_month", "severity"]
        == "critical"
    ).all()


def test_negative_generation_flagged_critical() -> None:
    data = make_data([make_row(energy_generated_mwh=-5.0)])
    result = audit_subsidiary("test", data)

    assert "negative_energy_generated_mwh" in set(result.flags["issue_code"])


def test_generation_far_above_nameplate_flagged_critical() -> None:
    data = make_data([make_row(energy_generated_mwh=2000.0, energy_capacity_mw=1.0)])
    result = audit_subsidiary("test", data)

    flagged = result.flags[result.flags["issue_code"] == "generation_far_above_nameplate"]
    assert len(flagged) == 1
    assert flagged["severity"].iloc[0] == "critical"


def test_inactive_placeholder_zero_generation_is_not_flagged() -> None:
    data = make_data(
        [
            make_row(date="2025-01-01", energy_generated_mwh=0.0, row_status="active_reported"),
            make_row(
                date="2025-02-01", energy_generated_mwh=0.0, row_status="inactive_placeholder"
            ),
        ]
    )
    result = audit_subsidiary("test", data)

    zero_flags = result.flags[result.flags["issue_code"] == "generation_zero"]
    assert zero_flags["date"].tolist() == [pd.Timestamp("2025-01-01")]


def test_audit_never_drops_or_reorders_rows() -> None:
    data = make_data([make_row(date="2025-01-01"), make_row(date="2025-02-01")])
    result = audit_subsidiary("test", data)

    assert len(result.audited_data) == len(data)
    assert "audit_severity" in result.audited_data.columns
    assert "audit_issue_codes" in result.audited_data.columns


def test_append_audit_columns_reports_worst_severity_and_all_codes() -> None:
    data = make_data([make_row()])
    flags = pd.DataFrame(
        {
            "issue_code": ["warning_issue", "critical_issue"],
            "severity": ["warning", "critical"],
        },
        index=[0, 0],
    )
    result = append_audit_columns(data, flags)

    assert result.loc[0, "audit_severity"] == "critical"
    assert result.loc[0, "audit_issue_codes"] == "critical_issue;warning_issue"


def test_append_audit_columns_handles_no_flags() -> None:
    data = make_data([make_row()])
    result = append_audit_columns(data, pd.DataFrame())

    assert pd.isna(result.loc[0, "audit_severity"])
    assert pd.isna(result.loc[0, "audit_issue_codes"])
