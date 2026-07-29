"""Validate and export provisional Korean non-power emission-factor evidence."""

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
from nzk_aphiam.data.process.nonpower_sector_inventory import (
    DELIMITER,
)
from nzk_aphiam.data.process.nonpower_sector_inventory import (
    REFERENCE_FILES as INVENTORY_REFERENCE_FILES,
)
from nzk_aphiam.data.process.nonpower_sector_inventory import (
    load_reference_tables as load_inventory_tables,
)
from nzk_aphiam.data.process.nonpower_sector_inventory import (
    validate_tables as validate_inventory_tables,
)

COLLECTION_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"

FACTOR_FILE = "nonpower_emission_factors.csv"
MAPPING_RULE_FILE = "nonpower_ef_inventory_mapping_rules.csv"
REVIEW_MAP_FILE = "capss_vii_review_map.csv"
EVIDENCE_FILE = "non_mass_normalized_evidence.csv"
GAP_FILE = "nonpower_ef_collection_gaps.csv"

OUTPUT_FILES = {
    "factors": "nonpower_emission_factors.parquet",
    "links": "nonpower_emission_factor_inventory_links.parquet",
    "evidence": "non_mass_normalized_evidence.parquet",
}

REQUIRED_FACTOR_COLUMNS = (
    "record_id",
    "collection_version",
    "review_status",
    "production_ready",
    "sector",
    "subsector",
    "technology",
    "fuel_or_material",
    "pollutant",
    "ef_value",
    "ef_expression",
    "ef_lower",
    "ef_upper",
    "unit",
    "activity_basis",
    "control_basis",
    "geographic_scope",
    "applicability",
    "evidence_origin",
    "factor_reference_period_start",
    "factor_reference_period_end",
    "source_id",
    "source_table_or_location",
    "quality_flag",
    "notes",
    "source_title",
    "publication_year",
    "source_url",
)

REQUIRED_RULE_COLUMNS = (
    "rule_id",
    "sector",
    "subsector",
    "technology_pattern",
    "fuel_pattern",
    "inventory_ids",
    "match_status",
    "allocation_note",
)

REQUIRED_REVIEW_COLUMNS = (
    "v1_source_table_or_location",
    "capss_vii_table_ids",
    "review_status",
    "notes",
)

REQUIRED_EVIDENCE_COLUMNS = (
    "evidence_id",
    "collection_version",
    "sector",
    "subsector",
    "technology",
    "pollutant",
    "reported_value",
    "unit",
    "source_id",
    "candidate_inventory_ids",
    "use",
    "notes",
)

REQUIRED_GAP_COLUMNS = (
    "gap_id",
    "collection_version",
    "gap_area",
    "priority",
    "status",
    "next_source",
    "inventory_ids",
)

ALLOWED_MATCH_STATUSES = {"exact", "documented_proxy", "aggregate_proxy"}
ALLOWED_REVIEW_STATUSES = {
    "superseded_pending_capss_vii_diff",
    "candidate_literature_validation",
}
ISSUE_COLUMNS = ("severity", "code", "file", "row_id", "field", "message")

SOURCE_ID_MAP = {
    "CAPSS_VI_2023": "capss_handbook_vi_mirror",
    "CAPSS_VII_2025": "capss_handbook_vii",
    "KIM_EAF_2021": "korean_eaf_paper",
    "KOREA_STEEL_2004": "korean_steel_melting_paper_2004",
    "KOSAE_RESIDUE_2022": "korean_residue_burning_paper_2022",
    "KOREA_INCINERATOR_2018": "korean_small_incinerator_paper_2018",
    "MOF_SHIP_2025": "mof_ship_ef",
}

EVIDENCE_INVENTORY_MAP = {
    ("Industry", "Iron and steel"): "ind_steel_eaf",
    ("Waste", "Small industrial waste incineration"): "wst_industrial_incineration",
    ("Transport", "Shipping"): "trn_shipping_passenger",
}

GAP_INVENTORY_MAP = {
    "Road transport LDV/HDV/bus": (
        "trn_road_passenger_gasoline_ldv|trn_road_passenger_diesel_ldv|"
        "trn_road_passenger_lpg_ldv|trn_road_passenger_hybrid_ldv|trn_road_bus|"
        "trn_road_freight_lcv|trn_road_freight_mdv|trn_road_freight_hdv"
    ),
    "Aviation": (
        "trn_aviation_passenger_lto|trn_aviation_passenger_cruise|"
        "trn_aviation_freight_lto|trn_aviation_freight_cruise"
    ),
    "Construction equipment": "trn_nonroad_construction",
    "Cement kiln combustion": "ind_cement_kiln_combustion",
    "Oil refining process/fugitive": ("ene_refining_process|ene_flaring|ene_fuel_storage_loading"),
    "Aluminium/non-ferrous metals": ("ind_nonferrous_primary|ind_nonferrous_secondary"),
    "Landfill VOC": "wst_landfills",
    "Hydrogen production": (
        "ene_hydrogen_smr|ene_hydrogen_coal|ene_hydrogen_byproduct|"
        "ene_hydrogen_electrolysis|ene_hydrogen_biomass"
    ),
    "CAPSS VII version update": "",
}


class EmissionFactorValidationError(ValueError):
    """Raised when the tracked first-pass collection is structurally invalid."""


@dataclass(frozen=True)
class ValidationResult:
    """Validated factor evidence, inventory links, and human-readable issues."""

    factors: pd.DataFrame
    links: pd.DataFrame
    evidence: pd.DataFrame
    gaps: pd.DataFrame
    issues: pd.DataFrame

    @property
    def errors(self) -> pd.DataFrame:
        return self.issues.loc[self.issues["severity"].eq("error")]

    @property
    def warnings(self) -> pd.DataFrame:
        return self.issues.loc[self.issues["severity"].eq("warning")]


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def _split(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [item.strip() for item in str(value).split(DELIMITER) if item.strip()]


def _issue(
    issues: list[dict[str, str]],
    severity: str,
    code: str,
    file: str,
    row_id: str,
    field: str,
    message: str,
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "file": file,
            "row_id": row_id,
            "field": field,
            "message": message,
        }
    )


def _require_columns(
    frame: pd.DataFrame,
    required: Iterable[str],
    file: str,
    issues: list[dict[str, str]],
) -> bool:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        _issue(
            issues,
            "error",
            "missing_columns",
            file,
            "",
            "",
            f"Missing required columns: {missing}",
        )
    return not missing


def import_first_pass_collection(source_dir: Path, reference_dir: Path) -> None:
    """Normalize the supplied v1 bundle into the repository reference schemas."""
    inputs = {
        "factors": source_dir / "korea_nonpower_ef_long_v1.csv",
        "evidence": source_dir / "non_mass_normalized_evidence_v1.csv",
        "gaps": source_dir / "collection_gaps_v1.csv",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise EmissionFactorValidationError(f"Missing supplied collection files: {missing}")

    factors = _read_csv(inputs["factors"])
    factors["source_id"] = factors["source_id"].replace(SOURCE_ID_MAP)
    factors["pollutant"] = factors["pollutant"].replace({"VOC": "VOCs"})
    factors.insert(1, "collection_version", COLLECTION_VERSION)
    capss_vi = factors["source_id"].eq("capss_handbook_vi_mirror")
    factors.insert(
        2,
        "review_status",
        capss_vi.map(
            {
                True: "superseded_pending_capss_vii_diff",
                False: "candidate_literature_validation",
            }
        ),
    )
    factors.insert(3, "production_ready", "false")
    factors = factors.loc[:, REQUIRED_FACTOR_COLUMNS].sort_values("record_id", kind="stable")

    evidence = _read_csv(inputs["evidence"])
    evidence["source_id"] = evidence["source_id"].replace(SOURCE_ID_MAP)
    evidence["pollutant"] = evidence["pollutant"].replace({"VOC": "VOCs"})
    evidence.insert(0, "evidence_id", [f"EVIDENCE{i:03d}" for i in range(1, len(evidence) + 1)])
    evidence.insert(1, "collection_version", COLLECTION_VERSION)
    evidence.insert(
        9,
        "candidate_inventory_ids",
        [
            EVIDENCE_INVENTORY_MAP.get((row.sector, row.subsector), "")
            for row in evidence.itertuples(index=False)
        ],
    )
    evidence = evidence.loc[:, REQUIRED_EVIDENCE_COLUMNS]

    gaps = _read_csv(inputs["gaps"])
    gaps.insert(0, "gap_id", [f"GAP{i:03d}" for i in range(1, len(gaps) + 1)])
    gaps.insert(1, "collection_version", COLLECTION_VERSION)
    gaps["inventory_ids"] = gaps["gap_area"].map(GAP_INVENTORY_MAP).fillna("")
    gaps = gaps.loc[:, REQUIRED_GAP_COLUMNS]

    reference_dir.mkdir(parents=True, exist_ok=True)
    factors.to_csv(reference_dir / FACTOR_FILE, index=False, encoding="utf-8")
    evidence.to_csv(reference_dir / EVIDENCE_FILE, index=False, encoding="utf-8")
    gaps.to_csv(reference_dir / GAP_FILE, index=False, encoding="utf-8")


def load_collection(reference_dir: Path = NONPOWER_REFERENCE_DIR) -> dict[str, pd.DataFrame]:
    """Load all tracked emission-factor collection files as strings."""
    paths = {
        "factors": reference_dir / FACTOR_FILE,
        "rules": reference_dir / MAPPING_RULE_FILE,
        "review": reference_dir / REVIEW_MAP_FILE,
        "evidence": reference_dir / EVIDENCE_FILE,
        "gaps": reference_dir / GAP_FILE,
    }
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        raise EmissionFactorValidationError(f"Missing non-power EF files: {missing}")
    return {key: _read_csv(path) for key, path in paths.items()}


def _match_rules(row: object, rules: pd.DataFrame) -> pd.DataFrame:
    candidates = rules.loc[rules["sector"].eq(row.sector) & rules["subsector"].eq(row.subsector)]
    matches = []
    for index, rule in candidates.iterrows():
        if re.fullmatch(rule["technology_pattern"], row.technology) and re.fullmatch(
            rule["fuel_pattern"], row.fuel_or_material
        ):
            matches.append(index)
    return rules.loc[matches]


def _build_links(
    factors: pd.DataFrame,
    rules: pd.DataFrame,
    denominators: pd.DataFrame,
    issues: list[dict[str, str]],
) -> pd.DataFrame:
    link_rows: list[dict[str, str]] = []
    missing_denominator_pairs: set[tuple[str, str]] = set()
    for row in factors.itertuples(index=False):
        matches = _match_rules(row, rules)
        if len(matches) != 1:
            _issue(
                issues,
                "error",
                "factor_mapping_rule_count",
                FACTOR_FILE,
                row.record_id,
                "technology",
                f"Expected exactly one inventory mapping rule, found {len(matches)}.",
            )
            continue
        rule = matches.iloc[0]
        for inventory_id in _split(rule["inventory_ids"]):
            denominator = denominators.loc[
                denominators["inventory_id"].eq(inventory_id)
                & denominators["pollutant"].eq(row.pollutant)
            ]
            denominator_ids = DELIMITER.join(sorted(denominator["denominator_id"].tolist()))
            link_rows.append(
                {
                    "record_id": row.record_id,
                    "inventory_id": inventory_id,
                    "rule_id": rule["rule_id"],
                    "match_status": rule["match_status"],
                    "pollutant": row.pollutant,
                    "ef_unit": row.unit,
                    "denominator_ids": denominator_ids,
                    "denominator_match_status": (
                        "candidate_denominator" if denominator_ids else "missing_denominator"
                    ),
                    "review_status": row.review_status,
                    "production_ready": row.production_ready,
                    "allocation_note": rule["allocation_note"],
                }
            )
            if not denominator_ids:
                missing_denominator_pairs.add((inventory_id, row.pollutant))
    for inventory_id, pollutant in sorted(missing_denominator_pairs):
        _issue(
            issues,
            "warning",
            "missing_candidate_denominator",
            FACTOR_FILE,
            inventory_id,
            "pollutant",
            f"No {pollutant} denominator is registered for this candidate inventory activity.",
        )
    return pd.DataFrame(
        link_rows,
        columns=(
            "record_id",
            "inventory_id",
            "rule_id",
            "match_status",
            "pollutant",
            "ef_unit",
            "denominator_ids",
            "denominator_match_status",
            "review_status",
            "production_ready",
            "allocation_note",
        ),
    )


def validate_collection(reference_dir: Path = NONPOWER_REFERENCE_DIR) -> ValidationResult:
    """Validate evidence, source keys, mapping decisions, and factor sanity."""
    collection = load_collection(reference_dir)
    inventory = load_inventory_tables(reference_dir)
    inventory_result = validate_inventory_tables(inventory)
    issues: list[dict[str, str]] = []
    for issue in inventory_result.errors.to_dict("records"):
        issues.append(issue)

    shapes_ok = all(
        (
            _require_columns(collection["factors"], REQUIRED_FACTOR_COLUMNS, FACTOR_FILE, issues),
            _require_columns(
                collection["rules"], REQUIRED_RULE_COLUMNS, MAPPING_RULE_FILE, issues
            ),
            _require_columns(
                collection["review"], REQUIRED_REVIEW_COLUMNS, REVIEW_MAP_FILE, issues
            ),
            _require_columns(
                collection["evidence"], REQUIRED_EVIDENCE_COLUMNS, EVIDENCE_FILE, issues
            ),
            _require_columns(collection["gaps"], REQUIRED_GAP_COLUMNS, GAP_FILE, issues),
        )
    )
    if not shapes_ok:
        issue_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
        return ValidationResult(
            collection["factors"],
            pd.DataFrame(),
            collection["evidence"],
            collection["gaps"],
            issue_frame,
        )

    factors = collection["factors"]
    rules = collection["rules"]
    review = collection["review"]
    evidence = collection["evidence"]
    gaps = collection["gaps"]
    inventory_ids = set(inventory["inventory"]["inventory_id"])
    source_ids = set(inventory["sources"]["source_id"])
    pollutants = set(inventory["pollutants"]["pollutant"])

    for file, frame, id_column in (
        (FACTOR_FILE, factors, "record_id"),
        (MAPPING_RULE_FILE, rules, "rule_id"),
        (EVIDENCE_FILE, evidence, "evidence_id"),
        (GAP_FILE, gaps, "gap_id"),
    ):
        blank = frame[id_column].str.strip().eq("")
        duplicate = frame[id_column].duplicated(keep=False)
        for row_id in sorted(frame.loc[blank | duplicate, id_column].unique()):
            _issue(
                issues,
                "error",
                "blank_or_duplicate_id",
                file,
                row_id,
                id_column,
                f"{id_column} must be nonempty and unique.",
            )

    bad_pollutants = sorted(set(factors["pollutant"]) - pollutants)
    if bad_pollutants:
        _issue(
            issues,
            "error",
            "unknown_pollutant",
            FACTOR_FILE,
            "",
            "pollutant",
            f"Unregistered pollutants: {bad_pollutants}",
        )
    bad_sources = sorted((set(factors["source_id"]) | set(evidence["source_id"])) - source_ids)
    if bad_sources:
        _issue(
            issues,
            "error",
            "unknown_source",
            FACTOR_FILE,
            "",
            "source_id",
            f"Unregistered source IDs: {bad_sources}",
        )

    for column in ("ef_value", "ef_lower", "ef_upper"):
        values = pd.to_numeric(factors[column], errors="coerce")
        invalid = factors[column].ne("") & values.isna()
        for row_id in factors.loc[invalid, "record_id"]:
            _issue(
                issues,
                "error",
                "invalid_numeric_factor",
                FACTOR_FILE,
                row_id,
                column,
                f"{column} must be blank or numeric.",
            )
        negative = factors[column].ne("") & values.lt(0)
        for row_id in factors.loc[negative, "record_id"]:
            _issue(
                issues,
                "error",
                "negative_factor",
                FACTOR_FILE,
                row_id,
                column,
                "Emission-factor values cannot be negative.",
            )

    has_point = factors["ef_value"].ne("")
    has_expression = factors["ef_expression"].ne("")
    has_range = factors["ef_lower"].ne("") | factors["ef_upper"].ne("")
    missing_factor = ~(has_point | has_expression | has_range)
    for row_id in factors.loc[missing_factor, "record_id"]:
        _issue(
            issues,
            "error",
            "missing_factor_value",
            FACTOR_FILE,
            row_id,
            "ef_value",
            "A point, expression, or range is required.",
        )
    lower = pd.to_numeric(factors["ef_lower"], errors="coerce")
    upper = pd.to_numeric(factors["ef_upper"], errors="coerce")
    invalid_range = lower.notna() & upper.notna() & lower.gt(upper)
    for row_id in factors.loc[invalid_range, "record_id"]:
        _issue(
            issues,
            "error",
            "invalid_factor_range",
            FACTOR_FILE,
            row_id,
            "ef_lower",
            "The lower factor bound exceeds the upper bound.",
        )

    for row in factors.itertuples(index=False):
        if row.collection_version != COLLECTION_VERSION:
            _issue(
                issues,
                "error",
                "collection_version_mismatch",
                FACTOR_FILE,
                row.record_id,
                "collection_version",
                f"Expected collection version {COLLECTION_VERSION}.",
            )
        if row.review_status not in ALLOWED_REVIEW_STATUSES:
            _issue(
                issues,
                "error",
                "invalid_review_status",
                FACTOR_FILE,
                row.record_id,
                "review_status",
                f"Unexpected review status {row.review_status!r}.",
            )
        if row.production_ready not in {"true", "false"}:
            _issue(
                issues,
                "error",
                "invalid_boolean",
                FACTOR_FILE,
                row.record_id,
                "production_ready",
                "production_ready must be true or false.",
            )
        if row.source_id == "capss_handbook_vi_mirror" and row.production_ready != "false":
            _issue(
                issues,
                "error",
                "superseded_capss_factor_enabled",
                FACTOR_FILE,
                row.record_id,
                "production_ready",
                "Handbook VI mirror transcriptions cannot be production-ready.",
            )
        if not row.unit.strip():
            _issue(
                issues,
                "error",
                "blank_factor_unit",
                FACTOR_FILE,
                row.record_id,
                "unit",
                "Every mass-normalized factor requires a unit.",
            )

    for row in rules.itertuples(index=False):
        if row.match_status not in ALLOWED_MATCH_STATUSES:
            _issue(
                issues,
                "error",
                "invalid_match_status",
                MAPPING_RULE_FILE,
                row.rule_id,
                "match_status",
                f"Unexpected match status {row.match_status!r}.",
            )
        for field in ("technology_pattern", "fuel_pattern"):
            try:
                re.compile(getattr(row, field))
            except re.error as error:
                _issue(
                    issues,
                    "error",
                    "invalid_regex",
                    MAPPING_RULE_FILE,
                    row.rule_id,
                    field,
                    str(error),
                )
        unknown = sorted(set(_split(row.inventory_ids)) - inventory_ids)
        if unknown:
            _issue(
                issues,
                "error",
                "unknown_inventory_id",
                MAPPING_RULE_FILE,
                row.rule_id,
                "inventory_ids",
                f"Unknown inventory IDs: {unknown}",
            )

    for row in evidence.itertuples(index=False):
        unknown = sorted(set(_split(row.candidate_inventory_ids)) - inventory_ids)
        if unknown:
            _issue(
                issues,
                "error",
                "unknown_inventory_id",
                EVIDENCE_FILE,
                row.evidence_id,
                "candidate_inventory_ids",
                f"Unknown inventory IDs: {unknown}",
            )
    for row in gaps.itertuples(index=False):
        unknown = sorted(set(_split(row.inventory_ids)) - inventory_ids)
        if unknown:
            _issue(
                issues,
                "error",
                "unknown_inventory_id",
                GAP_FILE,
                row.gap_id,
                "inventory_ids",
                f"Unknown inventory IDs: {unknown}",
            )

    source_locations = set(factors["source_table_or_location"])
    reviewed_locations = set(review["v1_source_table_or_location"])
    missing_review = sorted(source_locations - reviewed_locations)
    if missing_review:
        _issue(
            issues,
            "error",
            "missing_capss_vii_review_map",
            REVIEW_MAP_FILE,
            "",
            "v1_source_table_or_location",
            f"Unreviewed source-table labels: {missing_review}",
        )

    links = _build_links(factors, rules, inventory["denominators"], issues)
    issue_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    if not issue_frame.empty:
        issue_frame = issue_frame.sort_values(
            ["severity", "file", "row_id", "code"], kind="stable"
        ).reset_index(drop=True)
    return ValidationResult(factors, links, evidence, gaps, issue_frame)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _build_timestamp(paths: Iterable[Path]) -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    timestamp = int(epoch) if epoch else int(max(path.stat().st_mtime for path in paths))
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or None if completed.returncode == 0 else None


def _summary(result: ValidationResult) -> dict[str, object]:
    factors = result.factors
    links = result.links
    mapped_inventory = set(links["inventory_id"]) if not links.empty else set()
    return {
        "collection_version": COLLECTION_VERSION,
        "schema_version": SCHEMA_VERSION,
        "structural_status": "failed" if not result.errors.empty else "passed",
        "factor_rows": int(len(factors)),
        "factor_source_counts": {
            key: int(value)
            for key, value in factors["source_id"].value_counts().sort_index().items()
        },
        "factor_pollutant_counts": {
            key: int(value)
            for key, value in factors["pollutant"].value_counts().sort_index().items()
        },
        "inventory_link_rows": int(len(links)),
        "inventory_ids_with_candidate_factors": int(len(mapped_inventory)),
        "production_ready_rows": int(factors["production_ready"].eq("true").sum()),
        "capss_vi_rows_pending_vii_diff": int(
            factors["source_id"].eq("capss_handbook_vi_mirror").sum()
        ),
        "evidence_only_rows": int(len(result.evidence)),
        "gap_rows": int(len(result.gaps)),
        "error_count": int(len(result.errors)),
        "warning_count": int(len(result.warnings)),
    }


def build_collection(
    reference_dir: Path = NONPOWER_REFERENCE_DIR,
    output_dir: Path = NONPOWER_PROCESSED_DIR,
    diagnostic_dir: Path = NONPOWER_DIAGNOSTIC_DIR,
) -> dict[str, object]:
    """Export deterministic evidence tables and inventory-coverage diagnostics."""
    result = validate_collection(reference_dir)
    summary = _summary(result)
    input_paths = [
        reference_dir / name
        for name in (
            FACTOR_FILE,
            MAPPING_RULE_FILE,
            REVIEW_MAP_FILE,
            EVIDENCE_FILE,
            GAP_FILE,
        )
    ]
    input_paths.extend(reference_dir / name for name in INVENTORY_REFERENCE_FILES.values())
    summary.update(
        {
            "build_timestamp_utc": _build_timestamp(input_paths),
            "git_commit": _git_commit(),
            "input_sha256": {path.name: _sha256(path) for path in sorted(input_paths)},
        }
    )

    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    result.issues.to_csv(diagnostic_dir / "ef_collection_validation_issues.csv", index=False)
    inventory = load_inventory_tables(reference_dir)["inventory"]
    coverage = (
        result.links.groupby("inventory_id", as_index=False)
        .agg(
            candidate_factor_rows=("record_id", "nunique"),
            candidate_pollutants=("pollutant", lambda values: DELIMITER.join(sorted(set(values)))),
            production_ready_rows=(
                "production_ready",
                lambda values: int(pd.Series(values).eq("true").sum()),
            ),
        )
        .merge(
            inventory[["inventory_id", "priority", "required_pollutants", "status"]],
            on="inventory_id",
            how="right",
        )
    )
    coverage["candidate_factor_rows"] = coverage["candidate_factor_rows"].fillna(0).astype(int)
    coverage["production_ready_rows"] = coverage["production_ready_rows"].fillna(0).astype(int)
    coverage["candidate_pollutants"] = coverage["candidate_pollutants"].fillna("")
    coverage = coverage.sort_values("inventory_id", kind="stable")
    coverage.to_csv(diagnostic_dir / "nonpower_ef_inventory_coverage.csv", index=False)
    coverage.loc[
        coverage["required_pollutants"].ne("") & coverage["candidate_factor_rows"].eq(0)
    ].to_csv(diagnostic_dir / "nonpower_ef_inventory_gaps.csv", index=False)
    sector_coverage = (
        result.factors.groupby(["sector", "subsector"], as_index=False)
        .agg(
            records=("record_id", "size"),
            technologies=("technology", "nunique"),
            pollutants=("pollutant", lambda values: DELIMITER.join(sorted(set(values)))),
            sources=("source_id", "nunique"),
            numeric_factors=("ef_value", lambda values: int(pd.Series(values).ne("").sum())),
            formula_factors=(
                "ef_expression",
                lambda values: int(pd.Series(values).ne("").sum()),
            ),
            range_factors=("ef_lower", lambda values: int(pd.Series(values).ne("").sum())),
        )
        .sort_values(["sector", "subsector"], kind="stable")
    )
    sector_coverage.to_csv(diagnostic_dir / "nonpower_ef_sector_coverage.csv", index=False)
    result.gaps.to_csv(diagnostic_dir / "nonpower_ef_collection_gaps.csv", index=False)
    (diagnostic_dir / "ef_collection_validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not result.errors.empty:
        codes = result.errors["code"].value_counts().sort_index().to_dict()
        raise EmissionFactorValidationError(f"Non-power EF validation failed: {codes}")

    output_dir.mkdir(parents=True, exist_ok=True)
    result.factors.sort_values("record_id", kind="stable").to_parquet(
        output_dir / OUTPUT_FILES["factors"], index=False
    )
    result.links.sort_values(["record_id", "inventory_id"], kind="stable").to_parquet(
        output_dir / OUTPUT_FILES["links"], index=False
    )
    result.evidence.sort_values("evidence_id", kind="stable").to_parquet(
        output_dir / OUTPUT_FILES["evidence"], index=False
    )
    metadata = {
        **summary,
        "outputs": OUTPUT_FILES,
        "method_note": (
            "All imported factors remain candidate evidence. CAPSS Handbook VI mirror rows are "
            "superseded and require a row-level Handbook VII diff before production use."
        ),
    }
    (output_dir / "nonpower_emission_factors.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and export provisional Korean non-power emission factors."
    )
    parser.add_argument("--reference-dir", type=Path, default=NONPOWER_REFERENCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=NONPOWER_PROCESSED_DIR)
    parser.add_argument("--diagnostic-dir", type=Path, default=NONPOWER_DIAGNOSTIC_DIR)
    parser.add_argument(
        "--import-source-dir",
        type=Path,
        help="Normalize a supplied korea_nonpower_ef_collection_v1_with_scripts directory.",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.import_source_dir:
            import_first_pass_collection(args.import_source_dir, args.reference_dir)
        if args.validate_only:
            summary = _summary(validate_collection(args.reference_dir))
        else:
            summary = build_collection(
                args.reference_dir,
                args.output_dir,
                args.diagnostic_dir,
            )
    except EmissionFactorValidationError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
