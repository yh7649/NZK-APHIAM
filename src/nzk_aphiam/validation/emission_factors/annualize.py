"""Annualize monthly KEPCO project data for plant emission-factor validation."""

from __future__ import annotations

import pandas as pd

from nzk_aphiam.validation.emission_factors.schema import (
    COMBINED_POLLUTANT,
    POLLUTANT_COLUMNS,
    SEVERE_AUDIT_SEVERITIES,
)

IDENTITY_COLUMNS = [
    "source_dataset",
    "subsidiary_company",
    "fuel_type",
    "technology",
    "observation_level",
    "reporting_unit_id",
    "generation_coverage_status",
    "row_status",
    "audit_severity",
    "audit_issue_codes",
]
OUTPUT_METADATA_COLUMNS = [
    "subsidiary_company",
    "fuel_type",
    "technology",
    "observation_level",
    "reporting_boundary",
    "audit_severity_values",
    "audit_issue_code_values",
    "generation_coverage_status_values",
]


def prepare_project_data(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize dates and reject physically impossible negative observations."""
    work = data.copy()
    work["date"] = pd.to_datetime(work["date"], errors="raise")
    work["year"] = work["date"].dt.year
    work["month"] = work["date"].dt.month
    for column in ["energy_generated_mwh", *POLLUTANT_COLUMNS.values()]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    negative_columns = ["energy_generated_mwh", *POLLUTANT_COLUMNS.values()]
    work["exclusion_reason"] = ""
    for column in negative_columns:
        mask = work[column].lt(0)
        reason = f"negative_{column}"
        work.loc[mask, "exclusion_reason"] = work.loc[mask, "exclusion_reason"].map(
            lambda value: ";".join(filter(None, [value, reason]))
        )
    return work


def apply_variant(data: pd.DataFrame, variant: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return rows retained for a variant plus row/generation exclusion summary."""
    work = data.copy()
    base_excluded = work["row_status"].eq("inactive_placeholder") | work["exclusion_reason"].ne("")
    if variant == "reported":
        excluded = base_excluded
    elif variant == "audit_clean":
        severe = work.get("audit_severity", pd.Series(index=work.index, dtype=object)).isin(
            SEVERE_AUDIT_SEVERITIES
        )
        excluded = base_excluded | severe
    else:
        raise ValueError(f"Unknown analysis variant: {variant}")

    reasons = []
    for label, mask in [
        ("inactive_placeholder", work["row_status"].eq("inactive_placeholder")),
        ("impossible_negative_value", work["exclusion_reason"].ne("")),
        (
            "severe_audit_error",
            work.get("audit_severity", pd.Series(index=work.index, dtype=object)).isin(
                SEVERE_AUDIT_SEVERITIES
            )
            if variant == "audit_clean"
            else pd.Series(False, index=work.index),
        ),
    ]:
        selected = work.loc[mask]
        reasons.append(
            {
                "analysis_variant": variant,
                "exclusion_reason": label,
                "excluded_rows": int(len(selected)),
                "excluded_generation_mwh": selected["energy_generated_mwh"].sum(min_count=1),
            }
        )
    return work.loc[~excluded].copy(), pd.DataFrame(reasons)


def _unique_join(values: pd.Series) -> str:
    clean = sorted({str(value) for value in values.dropna() if str(value) != ""})
    return ";".join(clean)


def aggregate_boundary(
    data: pd.DataFrame,
    *,
    group_columns: list[str],
    analysis_variant: str,
    reference_id: str | None = None,
    plant_group_id: str | None = None,
) -> pd.DataFrame:
    """Calculate annual project EFs for pollutant-specific and combined scopes."""
    rows: list[dict[str, object]] = []
    if data.empty:
        return pd.DataFrame()

    group_columns = [*group_columns, "year"]
    for group_values, group in data.groupby(group_columns, dropna=False):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)
        group_key = dict(zip(group_columns, group_values, strict=True))
        metadata = {
            "subsidiary_company": _unique_join(group.get("subsidiary_company", pd.Series())),
            "fuel_type": _unique_join(group.get("fuel_type", pd.Series())),
            "technology": _unique_join(group.get("technology", pd.Series())),
            "observation_level": _unique_join(group.get("observation_level", pd.Series())),
            "reporting_boundary": _unique_join(group.get("reporting_unit_id", pd.Series())),
            "audit_severity_values": _unique_join(group.get("audit_severity", pd.Series())),
            "audit_issue_code_values": _unique_join(group.get("audit_issue_codes", pd.Series())),
            "generation_coverage_status_values": _unique_join(
                group.get("generation_coverage_status", pd.Series())
            ),
        }
        for pollutant, column in POLLUTANT_COLUMNS.items():
            matched = group["energy_generated_mwh"].notna() & group[column].notna()
            generation = group.loc[matched, "energy_generated_mwh"].sum(min_count=1)
            mass = group.loc[matched, column].sum(min_count=1)
            rows.append(
                {
                    **group_key,
                    **metadata,
                    "reference_id": reference_id,
                    "plant_group_id": plant_group_id,
                    "analysis_variant": analysis_variant,
                    "pollutant": pollutant,
                    "pollutant_scope": pollutant,
                    "generation_mwh_sum": generation,
                    "pollutant_mass_kg_sum": mass,
                    "n_generation_months": int(group["energy_generated_mwh"].notna().sum()),
                    "n_pollutant_months": int(group[column].notna().sum()),
                    "n_matched_months": int(matched.sum()),
                    "complete_calendar_year": bool(
                        set(group.loc[matched, "month"]) == set(range(1, 13))
                    ),
                    "ef_kg_per_mwh": mass / generation
                    if pd.notna(generation) and generation > 0
                    else pd.NA,
                }
            )

        all_columns = list(POLLUTANT_COLUMNS.values())
        matched_all = group["energy_generated_mwh"].notna() & group[all_columns].notna().all(
            axis=1
        )
        generation = group.loc[matched_all, "energy_generated_mwh"].sum(min_count=1)
        mass = group.loc[matched_all, all_columns].sum(min_count=1).sum()
        rows.append(
            {
                **group_key,
                **metadata,
                "reference_id": reference_id,
                "plant_group_id": plant_group_id,
                "analysis_variant": analysis_variant,
                "pollutant": COMBINED_POLLUTANT,
                "pollutant_scope": "NOx+SOx+TSP",
                "generation_mwh_sum": generation,
                "pollutant_mass_kg_sum": mass,
                "n_generation_months": int(group["energy_generated_mwh"].notna().sum()),
                "n_pollutant_months": int(group[all_columns].notna().all(axis=1).sum()),
                "n_matched_months": int(matched_all.sum()),
                "complete_calendar_year": bool(
                    set(group.loc[matched_all, "month"]) == set(range(1, 13))
                ),
                "ef_kg_per_mwh": mass / generation
                if pd.notna(generation) and generation > 0
                else pd.NA,
            }
        )

    return pd.DataFrame(rows)
