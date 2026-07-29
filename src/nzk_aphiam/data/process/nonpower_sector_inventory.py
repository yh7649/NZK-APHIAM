"""Validate and export the version-controlled Korean non-power inventory taxonomy."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Iterable

import pandas as pd

from nzk_aphiam.config.paths import (
    NONPOWER_DIAGNOSTIC_DIR,
    NONPOWER_PROCESSED_DIR,
    NONPOWER_REFERENCE_DIR,
)

INVENTORY_VERSION = "0.2.0"
SCHEMA_VERSION = "1.0.0"
DELIMITER = "|"

REFERENCE_FILES = {
    "inventory": "gcam_kaist_nonpower_sector_inventory.csv",
    "crosswalk": "gcam_capss_nonpower_crosswalk.csv",
    "denominators": "nonpower_ef_denominator_registry.csv",
    "sources": "nonpower_source_registry.csv",
    "pollutants": "pollutant_registry.csv",
}

OUTPUT_FILES = {
    key: Path(filename).with_suffix(".parquet").name for key, filename in REFERENCE_FILES.items()
}

REQUIRED_COLUMNS = {
    "inventory": (
        "inventory_id",
        "inventory_version",
        "priority",
        "include_in_mvp",
        "gcam_cluster",
        "gcam_sector",
        "gcam_subsector",
        "gcam_technology",
        "gcam_fuel",
        "activity_variable",
        "activity_unit",
        "direct_emissions_scope",
        "process_emissions_possible",
        "combustion_emissions_possible",
        "electricity_only",
        "air_quality_supplemental",
        "scenario_driver",
        "required_pollutants",
        "preferred_ef_basis",
        "annual_activity_source_ids",
        "status",
        "rationale",
        "notes",
    ),
    "crosswalk": (
        "crosswalk_id",
        "inventory_id",
        "gcam_cluster",
        "gcam_sector",
        "gcam_subsector",
        "gcam_technology",
        "gcam_fuel",
        "capss_major_category",
        "capss_intermediate_category",
        "capss_minor_category",
        "capss_detail_category",
        "capss_fuel_or_process",
        "match_status",
        "allocation_rule",
        "double_counting_risk",
        "boundary_note",
        "source_id",
        "notes",
    ),
    "denominators": (
        "denominator_id",
        "inventory_id",
        "sector",
        "subsector",
        "technology",
        "pollutant",
        "preferred_activity_denominator",
        "preferred_ef_unit",
        "compatible_activity_units",
        "conversion_required",
        "conversion_description",
        "controlled_or_uncontrolled",
        "temporal_weighting_needed",
        "technology_weighting_needed",
        "control_weighting_needed",
        "notes",
    ),
    "sources": (
        "source_id",
        "source_priority",
        "organization",
        "title",
        "source_type",
        "sector_scope",
        "pollutant_scope",
        "activity_or_ef",
        "publication_year",
        "measurement_year_start",
        "measurement_year_end",
        "geographic_scope",
        "update_frequency",
        "url",
        "access_status",
        "license_or_use_note",
        "official_or_literature",
        "expected_variables",
        "known_limitations",
        "retrieval_date",
        "notes",
    ),
    "pollutants": (
        "pollutant",
        "canonical_name",
        "capss_name",
        "aliases",
        "mass_unit",
        "included_in_mvp",
        "notes",
    ),
}

ID_COLUMNS = {
    "inventory": "inventory_id",
    "crosswalk": "crosswalk_id",
    "denominators": "denominator_id",
    "sources": "source_id",
    "pollutants": "pollutant",
}

ALLOWED_VALUES = {
    ("inventory", "priority"): {"P1", "P2", "P3"},
    ("inventory", "status"): {
        "available",
        "partially_available",
        "proxy_required",
        "restricted_source",
        "not_yet_researched",
        "not_applicable",
        "excluded",
    },
    ("inventory", "direct_emissions_scope"): {
        "combustion",
        "process",
        "combustion_and_process",
        "fugitive",
        "mobile_combustion",
        "mixed_direct",
        "none_on_site",
        "supplemental_direct",
    },
    ("crosswalk", "match_status"): {
        "exact",
        "documented_proxy",
        "aggregate_proxy",
        "unresolved",
        "excluded",
        "not_applicable",
    },
    ("denominators", "controlled_or_uncontrolled"): {
        "controlled",
        "uncontrolled",
        "both",
        "not_applicable",
    },
    ("sources", "source_priority"): {"Tier 1", "Tier 2", "Tier 3"},
    ("sources", "access_status"): {
        "public",
        "restricted_source",
        "not_yet_researched",
    },
    ("sources", "official_or_literature"): {"official", "literature", "model_documentation"},
}

BOOLEAN_COLUMNS = {
    "inventory": (
        "include_in_mvp",
        "process_emissions_possible",
        "combustion_emissions_possible",
        "electricity_only",
        "air_quality_supplemental",
    ),
    "denominators": (
        "conversion_required",
        "temporal_weighting_needed",
        "technology_weighting_needed",
        "control_weighting_needed",
    ),
    "pollutants": ("included_in_mvp",),
}

ISSUE_COLUMNS = ("severity", "code", "file", "row_id", "field", "message")


class InventoryValidationError(ValueError):
    """Raised when reference files contain structural validation errors."""


@dataclass(frozen=True)
class ValidationResult:
    """Validated tables and their human-readable issues."""

    tables: dict[str, pd.DataFrame]
    issues: pd.DataFrame

    @property
    def errors(self) -> pd.DataFrame:
        return self.issues.loc[self.issues["severity"].eq("error")]

    @property
    def warnings(self) -> pd.DataFrame:
        return self.issues.loc[self.issues["severity"].eq("warning")]


def _split(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [item.strip() for item in str(value).split(DELIMITER) if item.strip()]


def _normalized_alias(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def load_reference_tables(reference_dir: Path = NONPOWER_REFERENCE_DIR) -> dict[str, pd.DataFrame]:
    """Load all tracked reference CSVs without coercing identifiers or units."""
    missing = [
        filename
        for filename in REFERENCE_FILES.values()
        if not (reference_dir / filename).is_file()
    ]
    if missing:
        raise InventoryValidationError(f"Missing non-power reference files: {missing}")
    return {key: _read_csv(reference_dir / filename) for key, filename in REFERENCE_FILES.items()}


def _issue(
    issues: list[dict[str, str]],
    severity: str,
    code: str,
    table: str,
    row_id: object,
    field: str,
    message: str,
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "file": REFERENCE_FILES[table],
            "row_id": str(row_id),
            "field": field,
            "message": message,
        }
    )


def _validate_shape(tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]) -> bool:
    valid = True
    for table, required in REQUIRED_COLUMNS.items():
        if table not in tables:
            _issue(
                issues, "error", "missing_table", table, "", "", "Required table was not loaded."
            )
            valid = False
            continue
        missing = [column for column in required if column not in tables[table].columns]
        if missing:
            _issue(
                issues,
                "error",
                "missing_required_columns",
                table,
                "",
                "",
                f"Missing required columns: {missing}",
            )
            valid = False
    return valid


def _validate_ids(tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]) -> None:
    for table, column in ID_COLUMNS.items():
        values = tables[table][column].astype(str).str.strip()
        for index in values.index[values.eq("")]:
            _issue(issues, "error", "missing_id", table, index + 2, column, "Identifier is empty.")
        duplicate = values.ne("") & values.duplicated(keep=False)
        for value in sorted(values.loc[duplicate].unique()):
            _issue(
                issues,
                "error",
                "duplicate_id",
                table,
                value,
                column,
                f"Identifier {value!r} appears more than once.",
            )


def _validate_enums(tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]) -> None:
    for (table, column), allowed in ALLOWED_VALUES.items():
        invalid = tables[table].loc[
            ~tables[table][column].isin(allowed), [ID_COLUMNS[table], column]
        ]
        for _, row in invalid.iterrows():
            _issue(
                issues,
                "error",
                "invalid_enum",
                table,
                row[ID_COLUMNS[table]],
                column,
                f"Value {row[column]!r} is not one of {sorted(allowed)}.",
            )
    for table, columns in BOOLEAN_COLUMNS.items():
        for column in columns:
            invalid = tables[table].loc[
                ~tables[table][column].isin({"true", "false"}), [ID_COLUMNS[table], column]
            ]
            for _, row in invalid.iterrows():
                _issue(
                    issues,
                    "error",
                    "invalid_boolean",
                    table,
                    row[ID_COLUMNS[table]],
                    column,
                    f"Boolean value must be 'true' or 'false', not {row[column]!r}.",
                )


def _pollutant_alias_map(pollutants: pd.DataFrame, issues: list[dict[str, str]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for _, row in pollutants.iterrows():
        pollutant = row["pollutant"]
        for alias in [
            pollutant,
            row["canonical_name"],
            row["capss_name"],
            *_split(row["aliases"]),
        ]:
            key = _normalized_alias(alias)
            if not key:
                _issue(
                    issues,
                    "error",
                    "empty_pollutant_alias",
                    "pollutants",
                    pollutant,
                    "aliases",
                    "Pollutant aliases must normalize to a nonempty key.",
                )
            elif key in aliases and aliases[key] != pollutant:
                _issue(
                    issues,
                    "error",
                    "contradictory_pollutant_alias",
                    "pollutants",
                    pollutant,
                    "aliases",
                    f"Alias {alias!r} also maps to {aliases[key]!r}.",
                )
            else:
                aliases[key] = pollutant
    return aliases


def _validate_pollutants(tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]) -> None:
    registry = set(tables["pollutants"]["pollutant"])
    _pollutant_alias_map(tables["pollutants"], issues)
    for _, row in tables["inventory"].iterrows():
        listed = _split(row["required_pollutants"])
        if len(listed) != len(set(listed)):
            _issue(
                issues,
                "error",
                "duplicate_required_pollutant",
                "inventory",
                row["inventory_id"],
                "required_pollutants",
                "A required pollutant is listed more than once.",
            )
        for pollutant in listed:
            if pollutant not in registry:
                _issue(
                    issues,
                    "error",
                    "unknown_pollutant",
                    "inventory",
                    row["inventory_id"],
                    "required_pollutants",
                    f"Unknown canonical pollutant {pollutant!r}.",
                )
    for _, row in tables["denominators"].iterrows():
        if row["pollutant"] not in registry:
            _issue(
                issues,
                "error",
                "unknown_pollutant",
                "denominators",
                row["denominator_id"],
                "pollutant",
                f"Unknown canonical pollutant {row['pollutant']!r}.",
            )


def _validate_foreign_keys(tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]) -> None:
    inventory_ids = set(tables["inventory"]["inventory_id"])
    source_ids = set(tables["sources"]["source_id"])
    for table in ("crosswalk", "denominators"):
        for _, row in (
            tables[table].loc[~tables[table]["inventory_id"].isin(inventory_ids)].iterrows()
        ):
            _issue(
                issues,
                "error",
                "unknown_inventory_id",
                table,
                row[ID_COLUMNS[table]],
                "inventory_id",
                f"Unknown inventory_id {row['inventory_id']!r}.",
            )
    for _, row in (
        tables["crosswalk"].loc[~tables["crosswalk"]["source_id"].isin(source_ids)].iterrows()
    ):
        _issue(
            issues,
            "error",
            "unknown_source_id",
            "crosswalk",
            row["crosswalk_id"],
            "source_id",
            f"Unknown source_id {row['source_id']!r}.",
        )
    for _, row in tables["inventory"].iterrows():
        for source_id in _split(row["annual_activity_source_ids"]):
            if source_id not in source_ids:
                _issue(
                    issues,
                    "error",
                    "unknown_source_id",
                    "inventory",
                    row["inventory_id"],
                    "annual_activity_source_ids",
                    f"Unknown source_id {source_id!r}.",
                )


def _validate_inventory_requirements(
    tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]
) -> None:
    inventory = tables["inventory"]
    crosswalk_ids = set(tables["crosswalk"]["inventory_id"])
    denominator_ids = set(tables["denominators"]["inventory_id"])
    for _, row in inventory.iterrows():
        row_id = row["inventory_id"]
        if row["inventory_version"] != INVENTORY_VERSION:
            _issue(
                issues,
                "error",
                "inventory_version_mismatch",
                "inventory",
                row_id,
                "inventory_version",
                f"Expected inventory version {INVENTORY_VERSION}.",
            )
        if row["priority"] == "P1":
            for field in (
                "activity_variable",
                "activity_unit",
                "preferred_ef_basis",
                "annual_activity_source_ids",
            ):
                if not row[field].strip():
                    _issue(
                        issues,
                        "error",
                        f"missing_p1_{field}",
                        "inventory",
                        row_id,
                        field,
                        f"P1 inventory rows require a nonempty {field}.",
                    )
            if row_id not in denominator_ids:
                _issue(
                    issues,
                    "error",
                    "missing_p1_ef_denominator",
                    "inventory",
                    row_id,
                    "preferred_ef_basis",
                    "P1 inventory row has no EF denominator entry.",
                )
            if row_id not in crosswalk_ids:
                _issue(
                    issues,
                    "error",
                    "missing_p1_crosswalk",
                    "inventory",
                    row_id,
                    "inventory_id",
                    "P1 inventory row has no CAPSS crosswalk row, including unresolved rows.",
                )
        electricity_only = row["electricity_only"] == "true"
        direct_sources = (
            row["process_emissions_possible"] == "true"
            or row["combustion_emissions_possible"] == "true"
        )
        if electricity_only and (
            direct_sources or row["direct_emissions_scope"] != "none_on_site"
        ):
            _issue(
                issues,
                "error",
                "electricity_direct_emissions",
                "inventory",
                row_id,
                "electricity_only",
                "Electricity-only technologies must have no on-site process or combustion emissions.",
            )


def _validate_denominators(tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]) -> None:
    units = tables["inventory"].set_index("inventory_id")["activity_unit"].to_dict()
    for _, row in tables["denominators"].iterrows():
        row_id = row["denominator_id"]
        inventory_unit = units.get(row["inventory_id"], "")
        compatible = _split(row["compatible_activity_units"])
        required = row["conversion_required"] == "true"
        for field in (
            "preferred_activity_denominator",
            "preferred_ef_unit",
            "compatible_activity_units",
        ):
            if not row[field].strip():
                _issue(
                    issues,
                    "error",
                    "missing_denominator_field",
                    "denominators",
                    row_id,
                    field,
                    f"Denominator registry requires nonempty {field}.",
                )
        if inventory_unit and inventory_unit not in compatible and not required:
            _issue(
                issues,
                "error",
                "incompatible_activity_ef_units",
                "denominators",
                row_id,
                "compatible_activity_units",
                f"Inventory unit {inventory_unit!r} is neither compatible nor marked for conversion.",
            )
        if required and not row["conversion_description"].strip():
            _issue(
                issues,
                "error",
                "missing_unit_conversion",
                "denominators",
                row_id,
                "conversion_description",
                "A required unit conversion must be described.",
            )


def _validate_crosswalks(tables: dict[str, pd.DataFrame], issues: list[dict[str, str]]) -> None:
    crosswalk = tables["crosswalk"]
    capss_columns = [
        "inventory_id",
        "capss_major_category",
        "capss_intermediate_category",
        "capss_minor_category",
        "capss_detail_category",
        "capss_fuel_or_process",
    ]
    duplicate = crosswalk.duplicated(capss_columns, keep=False)
    for _, group in crosswalk.loc[duplicate].groupby(capss_columns, dropna=False, sort=True):
        ids = sorted(group["crosswalk_id"].tolist())
        statuses = sorted(group["match_status"].unique())
        code = "contradictory_crosswalk" if len(statuses) > 1 else "duplicate_crosswalk"
        _issue(
            issues,
            "error",
            code,
            "crosswalk",
            DELIMITER.join(ids),
            "match_status",
            f"Duplicate CAPSS target for one inventory row has statuses {statuses}.",
        )
    for _, row in crosswalk.iterrows():
        row_id = row["crosswalk_id"]
        if row["match_status"] == "exact":
            missing = [
                column
                for column in (
                    "capss_major_category",
                    "capss_intermediate_category",
                    "capss_minor_category",
                )
                if not row[column].strip()
            ]
            aggregate_rule = "aggregate" in row["allocation_rule"].lower()
            if missing or aggregate_rule or row["allocation_rule"] != "one_to_one":
                _issue(
                    issues,
                    "error",
                    "underspecified_exact_crosswalk",
                    "crosswalk",
                    row_id,
                    "match_status",
                    "Exact mappings require major/intermediate/minor CAPSS labels and one_to_one allocation.",
                )
        if row["match_status"] == "unresolved":
            _issue(
                issues,
                "warning",
                "unresolved_crosswalk",
                "crosswalk",
                row_id,
                "match_status",
                "Research gap is preserved as unresolved and does not block the build.",
            )


def validate_tables(tables: dict[str, pd.DataFrame]) -> ValidationResult:
    """Validate schemas, enums, identifiers, foreign keys, boundaries, and legal joins."""
    issues: list[dict[str, str]] = []
    if _validate_shape(tables, issues):
        _validate_ids(tables, issues)
        _validate_enums(tables, issues)
        _validate_pollutants(tables, issues)
        _validate_foreign_keys(tables, issues)
        _validate_inventory_requirements(tables, issues)
        _validate_denominators(tables, issues)
        _validate_crosswalks(tables, issues)
    issue_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    if not issue_frame.empty:
        issue_frame = issue_frame.sort_values(
            ["severity", "file", "row_id", "code"], kind="stable"
        ).reset_index(drop=True)
    return ValidationResult(tables=tables, issues=issue_frame)


def validate_reference_inventory(reference_dir: Path = NONPOWER_REFERENCE_DIR) -> ValidationResult:
    """Load and validate tracked reference data without writing generated outputs."""
    result = validate_tables(load_reference_tables(reference_dir))
    if not result.errors.empty:
        codes = result.errors["code"].value_counts().sort_index().to_dict()
        raise InventoryValidationError(f"Non-power inventory validation failed: {codes}")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or None if completed.returncode == 0 else None


def _build_timestamp(paths: Iterable[Path]) -> str:
    """Return a reproducible timestamp keyed to inputs unless SOURCE_DATE_EPOCH is set."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    timestamp = int(epoch) if epoch else int(max(path.stat().st_mtime for path in paths))
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _empty_diagnostic(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _write_diagnostics(
    result: ValidationResult,
    diagnostic_dir: Path,
    summary: dict[str, object],
) -> None:
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    result.issues.to_csv(diagnostic_dir / "inventory_validation_issues.csv", index=False)
    crosswalk = result.tables["crosswalk"]
    crosswalk.loc[crosswalk["match_status"].eq("unresolved")].sort_values(
        "crosswalk_id", kind="stable"
    ).to_csv(diagnostic_dir / "unresolved_crosswalks.csv", index=False)

    sources = set(result.tables["sources"]["source_id"])
    missing_source_rows = []
    for _, row in result.tables["inventory"].iterrows():
        listed = _split(row["annual_activity_source_ids"])
        missing = [source_id for source_id in listed if source_id not in sources]
        if not listed or missing:
            missing_source_rows.append(
                {
                    "inventory_id": row["inventory_id"],
                    "priority": row["priority"],
                    "missing_source_ids": DELIMITER.join(missing),
                    "reason": "no_source_lead" if not listed else "unknown_source_id",
                }
            )
    pd.DataFrame(
        missing_source_rows,
        columns=("inventory_id", "priority", "missing_source_ids", "reason"),
    ).to_csv(diagnostic_dir / "missing_activity_sources.csv", index=False)

    denominator_ids = set(result.tables["denominators"]["inventory_id"])
    missing_denominators = result.tables["inventory"].loc[
        ~result.tables["inventory"]["inventory_id"].isin(denominator_ids)
        & result.tables["inventory"]["required_pollutants"].ne("")
        & result.tables["inventory"]["status"].ne("not_applicable"),
        ["inventory_id", "priority", "preferred_ef_basis", "status"],
    ]
    missing_denominators.to_csv(diagnostic_dir / "missing_ef_denominators.csv", index=False)

    boundary = result.issues.loc[result.issues["code"].eq("electricity_direct_emissions")]
    if boundary.empty:
        boundary = _empty_diagnostic(ISSUE_COLUMNS)
    boundary.to_csv(diagnostic_dir / "direct_emissions_boundary_issues.csv", index=False)
    (diagnostic_dir / "inventory_validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _summary(result: ValidationResult) -> dict[str, object]:
    inventory = result.tables["inventory"]
    crosswalk = result.tables["crosswalk"]
    return {
        "inventory_version": INVENTORY_VERSION,
        "schema_version": SCHEMA_VERSION,
        "structural_status": "failed" if not result.errors.empty else "passed",
        "inventory_rows": int(len(inventory)),
        "priority_counts": {
            priority: int(inventory["priority"].eq(priority).sum())
            for priority in ("P1", "P2", "P3")
        },
        "crosswalk_rows": int(len(crosswalk)),
        "match_status_counts": {
            status: int(crosswalk["match_status"].eq(status).sum())
            for status in sorted(crosswalk["match_status"].unique())
        },
        "denominator_rows": int(len(result.tables["denominators"])),
        "source_rows": int(len(result.tables["sources"])),
        "pollutant_rows": int(len(result.tables["pollutants"])),
        "error_count": int(len(result.errors)),
        "warning_count": int(len(result.warnings)),
    }


def build_inventory(
    reference_dir: Path = NONPOWER_REFERENCE_DIR,
    output_dir: Path = NONPOWER_PROCESSED_DIR,
    diagnostic_dir: Path = NONPOWER_DIAGNOSTIC_DIR,
) -> dict[str, object]:
    """Validate references, export deterministic Parquet tables, and write diagnostics."""
    paths = [reference_dir / filename for filename in REFERENCE_FILES.values()]
    result = validate_tables(load_reference_tables(reference_dir))
    summary = _summary(result)
    summary.update(
        {
            "build_timestamp_utc": _build_timestamp(paths),
            "git_commit": _git_commit(),
            "input_sha256": {path.name: _sha256(path) for path in sorted(paths)},
        }
    )
    _write_diagnostics(result, diagnostic_dir, summary)
    if not result.errors.empty:
        codes = result.errors["code"].value_counts().sort_index().to_dict()
        raise InventoryValidationError(f"Non-power inventory validation failed: {codes}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for table, frame in result.tables.items():
        ordered = frame.sort_values(ID_COLUMNS[table], kind="stable").reset_index(drop=True)
        ordered.to_parquet(output_dir / OUTPUT_FILES[table], index=False)
    metadata = {
        **summary,
        "outputs": {table: OUTPUT_FILES[table] for table in sorted(OUTPUT_FILES)},
        "method_note": (
            "Tracked taxonomy and compatibility registries only; no emission-factor values are "
            "extracted by this build. Unresolved research gaps are retained in diagnostics."
        ),
    }
    (output_dir / "nonpower_sector_inventory.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and export the GCAM-KAIST/CAPSS non-power inventory framework."
    )
    parser.add_argument("--reference-dir", type=Path, default=NONPOWER_REFERENCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=NONPOWER_PROCESSED_DIR)
    parser.add_argument("--diagnostic-dir", type=Path, default=NONPOWER_DIAGNOSTIC_DIR)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate tracked reference files without writing processed outputs or diagnostics.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.validate_only:
            result = validate_reference_inventory(args.reference_dir)
            summary = _summary(result)
        else:
            summary = build_inventory(args.reference_dir, args.output_dir, args.diagnostic_dir)
    except InventoryValidationError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
