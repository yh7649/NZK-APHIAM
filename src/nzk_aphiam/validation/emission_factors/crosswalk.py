"""Apply reviewed literature plant-boundary crosswalks."""

from __future__ import annotations

import pandas as pd

from nzk_aphiam.validation.emission_factors.annualize import aggregate_boundary
from nzk_aphiam.validation.emission_factors.references import parse_unit_scope


def project_boundaries_from_crosswalk(
    project_data: pd.DataFrame,
    crosswalk: pd.DataFrame,
    *,
    analysis_variant: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate project data to each accepted literature boundary."""
    frames: list[pd.DataFrame] = []
    status_rows: list[dict[str, object]] = []
    accepted = crosswalk.loc[crosswalk["match_status"].eq("accepted")]

    for row in accepted.to_dict("records"):
        subset = project_data.loc[project_data["plant_name"].eq(row["project_plant_name"])].copy()
        units = parse_unit_scope(row["included_unit_numbers"])
        if units is not None:
            subset = subset.loc[subset["plant_number"].astype(float).isin(units)]
        if row["project_reporting_unit_id"]:
            subset = subset.loc[subset["reporting_unit_id"].eq(row["project_reporting_unit_id"])]

        status_rows.append(
            {
                "reference_id": row["reference_id"],
                "plant_group_id": row["literature_plant_group_id"],
                "project_plant_name": row["project_plant_name"],
                "included_unit_numbers": row["included_unit_numbers"],
                "analysis_variant": analysis_variant,
                "match_status": row["match_status"],
                "boundary_match_status": row["boundary_match_status"],
                "project_rows_after_crosswalk": int(len(subset)),
                "project_generation_mwh_after_crosswalk": subset["energy_generated_mwh"].sum(
                    min_count=1
                ),
                "notes": row["notes"],
            }
        )
        if subset.empty:
            continue
        aggregated = aggregate_boundary(
            subset,
            group_columns=[],
            analysis_variant=analysis_variant,
            reference_id=row["reference_id"],
            plant_group_id=row["literature_plant_group_id"],
        )
        aggregated["project_plant_name"] = row["project_plant_name"]
        aggregated["included_unit_numbers"] = row["included_unit_numbers"]
        aggregated["boundary_match_status"] = row["boundary_match_status"]
        frames.append(aggregated)

    project_boundaries = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return project_boundaries, pd.DataFrame(status_rows)


def nonmatched_crosswalk_rows(crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Return crosswalk rows that must be reported as unmatched/non-comparable."""
    rows = crosswalk.loc[~crosswalk["match_status"].eq("accepted")].copy()
    return rows.rename(columns={"literature_plant_group_id": "plant_group_id"})
