"""Audit processed KEPCO thermal subsidiary datasets for outliers.

This module generalizes the East-West-only audit script into a reusable
auditor that runs over any subsidiary's processed monthly file (the shared
schema produced by ``nzk_aphiam.data.process.thermal.combiner``). It is
deliberately non-destructive: rows are never dropped or imputed. Each row is
instead annotated with ``audit_severity`` (the worst flag raised against it,
or missing if none) and ``audit_issue_codes`` (every issue code raised),
matching the rest of the pipeline's preference for flagging known-suspect
rows over silently deleting them. Analysts choose what to exclude, with full
provenance for the decision.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from nzk_aphiam.config.paths import DATA_DIR, THERMAL_PROCESSED_DIR

KEY = ["date", "plant_name", "plant_number", "original_korean_unit_name"]
GROUP_KEY = ["plant_name", "plant_number", "original_korean_unit_name"]
MEASURES = ["energy_generated_mwh", "energy_capacity_mw", "nox", "sox", "dust_tsp"]
POLLUTANTS = ["nox", "sox", "dust_tsp"]
SEVERITY_ORDER = {"critical": 0, "warning": 1, "review": 2}
SELECT_COLUMNS = KEY + ["energy_type", "energy_generated_mwh", "energy_capacity_mw"]

SUBSIDIARY_NAMES = [
    "eastwest_power",
    "western_power",
    "southern_power",
    "southeast_power",
    "midland_power",
]
SUBSIDIARY_OUTPUT_DIR = THERMAL_PROCESSED_DIR / "subsidiaries"
RESULTS_DIR = DATA_DIR.parent / "results" / "tables"


@dataclass
class AuditResult:
    """Every output of one subsidiary's audit run."""

    name: str
    audited_data: pd.DataFrame
    flags: pd.DataFrame
    issue_summary: pd.DataFrame
    unit_summary: pd.DataFrame
    gaps: pd.DataFrame
    yearly: pd.DataFrame
    checks: pd.DataFrame


def add_flags(
    output: list[pd.DataFrame],
    data: pd.DataFrame,
    mask: pd.Series,
    issue_code: str,
    severity: str,
    field: str,
    value: pd.Series | str,
    threshold: str,
    explanation: str,
) -> None:
    """Append one long-format flag row for every selected observation."""
    selected = data.loc[mask, SELECT_COLUMNS].copy()
    if selected.empty:
        return
    selected["issue_code"] = issue_code
    selected["severity"] = severity
    selected["field"] = field
    selected["value"] = value.loc[mask].values if isinstance(value, pd.Series) else value
    selected["threshold"] = threshold
    selected["explanation"] = explanation
    output.append(selected)


def robust_high_thresholds(data: pd.DataFrame, value: pd.Series) -> pd.Series:
    """Return unit-specific Q3 + 3 IQR thresholds, requiring 12 valid values."""
    work = data[GROUP_KEY].copy()
    work["value"] = value
    grouped = work.dropna(subset=["value"]).groupby(GROUP_KEY, dropna=False)["value"]
    stats = grouped.agg(
        n="count",
        q1=lambda x: x.quantile(0.25),
        q3=lambda x: x.quantile(0.75),
    )
    stats["threshold"] = stats["q3"] + 3 * (stats["q3"] - stats["q1"])
    stats.loc[stats["n"] < 12, "threshold"] = np.nan
    index = pd.MultiIndex.from_frame(data[GROUP_KEY])
    return pd.Series(index.map(stats["threshold"]), index=data.index, dtype=float)


def audit_subsidiary(name: str, data: pd.DataFrame) -> AuditResult:
    """Flag outliers and reporting anomalies in one subsidiary's processed data."""
    data = data.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data = data.sort_values(KEY, na_position="last", ignore_index=False)
    data["days_in_month"] = data["date"].dt.days_in_month
    data["capacity_factor"] = data["energy_generated_mwh"] / (
        data["energy_capacity_mw"] * data["days_in_month"] * 24
    )

    inactive = (
        data["row_status"].eq("inactive_placeholder")
        if "row_status" in data
        else (pd.Series(False, index=data.index))
    )
    active = ~inactive.fillna(False)

    flags: list[pd.DataFrame] = []

    duplicate = data.duplicated(KEY, keep=False)
    add_flags(
        flags,
        data,
        duplicate,
        "duplicate_unit_month",
        "critical",
        "key",
        "duplicate",
        "unique date + plant + unit + original unit name",
        "More than one row has the same unit-month key.",
    )

    for column in MEASURES:
        add_flags(
            flags,
            data,
            data[column].lt(0),
            f"negative_{column}",
            "critical",
            column,
            data[column],
            ">= 0",
            "Negative physical quantities are invalid.",
        )

    generation = data["energy_generated_mwh"]
    cf = data["capacity_factor"]
    add_flags(
        flags,
        data,
        active & generation.eq(0),
        "generation_zero",
        "review",
        "energy_generated_mwh",
        generation,
        "> 0 MWh",
        "Zero may be a genuine outage or an inactive placeholder; row_status does not "
        "already explain this row as inactive.",
    )
    add_flags(
        flags,
        data,
        generation.gt(0) & cf.lt(0.01),
        "generation_very_low_nonzero",
        "warning",
        "capacity_factor",
        cf,
        "< 0.01",
        "Positive generation is below 1% of the unit's monthly nameplate maximum.",
    )
    add_flags(
        flags,
        data,
        cf.gt(1) & cf.le(1.05),
        "generation_above_nameplate",
        "warning",
        "capacity_factor",
        cf,
        "1.00 < CF <= 1.05",
        "Generation exceeds capacity multiplied by all calendar hours; gross/net rating "
        "differences may explain small exceedances.",
    )
    add_flags(
        flags,
        data,
        cf.gt(1.05),
        "generation_far_above_nameplate",
        "critical",
        "capacity_factor",
        cf,
        "CF > 1.05",
        "Generation exceeds the nameplate calendar-hour maximum by more than 5%.",
    )

    pollution_positive = data[POLLUTANTS].fillna(0).gt(0).any(axis=1)
    add_flags(
        flags,
        data,
        active & generation.eq(0) & pollution_positive,
        "emissions_with_zero_generation",
        "warning",
        "cross_field",
        "mismatch",
        "generation = 0 and emissions > 0",
        "Could reflect startup, shutdown, auxiliary fuel use, or mismatched reporting boundaries.",
    )
    add_flags(
        flags,
        data,
        generation.gt(0) & data["nox"].eq(0),
        "zero_nox_with_generation",
        "warning",
        "nox",
        data["nox"],
        "NOx > 0 when generation > 0",
        "A combustion unit reports positive generation but zero NOx.",
    )
    for pollutant in ["sox", "dust_tsp"]:
        mask = generation.gt(0) & data["energy_type"].eq("coal") & data[pollutant].eq(0)
        add_flags(
            flags,
            data,
            mask,
            f"zero_{pollutant}_coal_generation",
            "warning",
            pollutant,
            data[pollutant],
            f"{pollutant} > 0 for coal generation",
            "A coal unit reports positive generation but zero pollutant mass.",
        )

    for pollutant in POLLUTANTS:
        add_flags(
            flags,
            data,
            active & generation.gt(0) & data[pollutant].isna(),
            f"missing_{pollutant}",
            "warning",
            pollutant,
            "missing",
            "nonmissing",
            "The source row does not supply this pollutant for an active generating row.",
        )
        absolute_threshold = robust_high_thresholds(data, data[pollutant])
        absolute_high = data[pollutant].gt(absolute_threshold)
        add_flags(
            flags,
            data,
            absolute_high,
            f"high_{pollutant}_mass",
            "review",
            pollutant,
            data[pollutant],
            "unit Q3 + 3 IQR",
            "Unusually high monthly mass relative to the same unit's history.",
        )

        ef = data[pollutant] / generation.where(generation.gt(0))
        ef_threshold = robust_high_thresholds(data, ef)
        ef_high = ef.gt(ef_threshold)
        add_flags(
            flags,
            data,
            ef_high,
            f"high_{pollutant}_emission_factor",
            "warning",
            f"{pollutant}_kg_per_mwh",
            ef,
            "unit Q3 + 3 IQR",
            "Unusually high emissions per MWh relative to the same unit's history; often "
            "driven by very low generation.",
        )

    flag_data = (
        pd.concat(flags, ignore_index=False)
        if flags
        else pd.DataFrame(
            columns=[
                *SELECT_COLUMNS,
                "issue_code",
                "severity",
                "field",
                "value",
                "threshold",
                "explanation",
            ]
        )
    )
    if not flag_data.empty:
        flag_data["severity_rank"] = flag_data["severity"].map(SEVERITY_ORDER)
        flag_data = flag_data.sort_values(
            ["severity_rank", "date", "plant_name", "plant_number", "issue_code"]
        ).drop(columns="severity_rank")

    audited_data = append_audit_columns(
        data.drop(columns=["days_in_month", "capacity_factor"]), flag_data
    )

    missing_months: list[dict[str, object]] = []
    for group_values, group in data.groupby(GROUP_KEY, dropna=False):
        expected = pd.date_range(group["date"].min(), group["date"].max(), freq="MS")
        for month in expected.difference(group["date"]):
            missing_months.append(
                dict(zip(GROUP_KEY, group_values, strict=True), missing_month=month)
            )
    gaps = pd.DataFrame(missing_months, columns=[*GROUP_KEY, "missing_month"])

    unit_summary = data.groupby(GROUP_KEY + ["energy_type"], as_index=False, dropna=False).agg(
        rows=("date", "size"),
        start_date=("date", "min"),
        end_date=("date", "max"),
        generation_min_mwh=("energy_generated_mwh", "min"),
        generation_median_mwh=("energy_generated_mwh", "median"),
        generation_max_mwh=("energy_generated_mwh", "max"),
        generation_zero_months=("energy_generated_mwh", lambda x: int(x.eq(0).sum())),
        capacity_factor_min=("capacity_factor", "min"),
        capacity_factor_max=("capacity_factor", "max"),
        missing_dust_tsp_months=("dust_tsp", lambda x: int(x.isna().sum())),
    )

    checks = pd.DataFrame(
        [
            {
                "check": "unique_unit_month_keys",
                "passed": not duplicate.any(),
                "detail": f"{int(duplicate.sum())} rows on duplicate keys",
            },
            {
                "check": "all_dates_are_month_starts",
                "passed": bool(data["date"].dt.is_month_start.all()),
                "detail": f"{data['date'].min():%Y-%m} to {data['date'].max():%Y-%m}",
            },
            {
                "check": "no_internal_unit_month_gaps",
                "passed": gaps.empty,
                "detail": f"{len(gaps)} missing unit-months",
            },
            {
                "check": "no_negative_numeric_values",
                "passed": not data[MEASURES].lt(0).any().any(),
                "detail": f"{int(data[MEASURES].lt(0).sum().sum())} negative values",
            },
            {
                "check": "all_generation_within_nameplate",
                "passed": not cf.gt(1).any(),
                "detail": f"{int(cf.gt(1).sum())} rows above capacity factor 1",
            },
        ]
    )

    if flag_data.empty:
        issue_summary = pd.DataFrame(
            columns=["severity", "issue_code", "flag_count", "affected_rows"]
        )
    else:
        issue_summary = flag_data.groupby(["severity", "issue_code"], as_index=False).agg(
            flag_count=("date", "size"), affected_rows=("date", lambda x: x.index.nunique())
        )
        issue_summary["severity_rank"] = issue_summary["severity"].map(SEVERITY_ORDER)
        issue_summary = issue_summary.sort_values(
            ["severity_rank", "flag_count"], ascending=[True, False]
        ).drop(columns="severity_rank")

    yearly = (
        data.assign(year=data["date"].dt.year)
        .groupby("year", as_index=False)
        .agg(
            rows=("date", "size"),
            generation_mwh=("energy_generated_mwh", "sum"),
            generation_zero_months=("energy_generated_mwh", lambda x: int(x.eq(0).sum())),
            nox_kg=("nox", "sum"),
            sox_kg=("sox", "sum"),
            dust_tsp_kg=("dust_tsp", lambda x: x.sum(min_count=1)),
            dust_tsp_missing=("dust_tsp", lambda x: int(x.isna().sum())),
        )
    )

    return AuditResult(
        name=name,
        audited_data=audited_data,
        flags=flag_data,
        issue_summary=issue_summary,
        unit_summary=unit_summary,
        gaps=gaps,
        yearly=yearly,
        checks=checks,
    )


def append_audit_columns(data: pd.DataFrame, flag_data: pd.DataFrame) -> pd.DataFrame:
    """Return data with non-destructive audit_severity/audit_issue_codes columns."""
    result = data.copy()
    if flag_data.empty:
        result["audit_severity"] = pd.Series(pd.NA, index=result.index, dtype="string")
        result["audit_issue_codes"] = pd.Series(pd.NA, index=result.index, dtype="string")
        return result

    severity_rank = flag_data["severity"].map(SEVERITY_ORDER)
    worst_rank = severity_rank.groupby(flag_data.index).min()
    rank_to_severity = {rank: severity for severity, rank in SEVERITY_ORDER.items()}
    audit_severity = worst_rank.map(rank_to_severity)
    audit_issue_codes = flag_data.groupby(flag_data.index)["issue_code"].agg(
        lambda codes: ";".join(sorted(set(codes)))
    )

    result["audit_severity"] = audit_severity.reindex(result.index).astype("string")
    result["audit_issue_codes"] = audit_issue_codes.reindex(result.index).astype("string")
    return result


def load_subsidiary_data(name: str, processed_dir: Path) -> pd.DataFrame:
    path = processed_dir / f"{name}_monthly_generation_emissions.csv"
    return pd.read_csv(path, low_memory=False)


def save_audit_outputs(result: AuditResult, processed_dir: Path, results_dir: Path) -> None:
    """Write the augmented processed file and the long-format audit reports."""
    audit_dir = results_dir / result.name / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    result.flags.to_csv(audit_dir / f"{result.name}_record_flags.csv", index=False)
    result.issue_summary.to_csv(audit_dir / f"{result.name}_issue_summary.csv", index=False)
    result.unit_summary.to_csv(audit_dir / f"{result.name}_unit_summary.csv", index=False)
    result.gaps.to_csv(audit_dir / f"{result.name}_missing_unit_months.csv", index=False)
    result.checks.to_csv(audit_dir / f"{result.name}_integrity_checks.csv", index=False)
    result.yearly.to_csv(audit_dir / f"{result.name}_yearly_summary.csv", index=False)

    processed_dir.mkdir(parents=True, exist_ok=True)
    output_path = processed_dir / f"{result.name}_monthly_generation_emissions.csv"
    result.audited_data.to_csv(output_path, index=False, date_format="%Y-%m-%d")


def audit_all(
    names: list[str],
    processed_dir: Path = SUBSIDIARY_OUTPUT_DIR,
    results_dir: Path = RESULTS_DIR,
) -> dict[str, AuditResult]:
    """Audit every named subsidiary's processed file and write its outputs."""
    results: dict[str, AuditResult] = {}
    for name in names:
        data = load_subsidiary_data(name, processed_dir)
        result = audit_subsidiary(name, data)
        save_audit_outputs(result, processed_dir, results_dir)
        results[name] = result
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit processed KEPCO thermal subsidiary datasets for outliers and "
            "reporting anomalies. Rows are never dropped; each row is annotated with "
            "audit_severity and audit_issue_codes so analysts choose what to exclude."
        )
    )
    parser.add_argument("--subsidiaries", nargs="+", default=SUBSIDIARY_NAMES)
    parser.add_argument("--processed-dir", type=Path, default=SUBSIDIARY_OUTPUT_DIR)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results = audit_all(args.subsidiaries, args.processed_dir, args.results_dir)
    for name, result in results.items():
        flagged_rows = result.audited_data["audit_severity"].notna().sum()
        critical = (
            int(result.flags["severity"].eq("critical").sum()) if not result.flags.empty else 0
        )
        print(
            f"{name}: audited {len(result.audited_data):,} rows, "
            f"{flagged_rows:,} flagged ({critical:,} critical flags)"
        )


if __name__ == "__main__":
    main()
