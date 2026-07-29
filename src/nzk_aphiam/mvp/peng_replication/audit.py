"""Machine-readable audit of selected and unavailable MVP inputs."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

import pandas as pd

from nzk_aphiam.config.paths import PROJECT_ROOT


def _git_state(path: Path) -> str:
    relative = (
        str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path)
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )
    if tracked.returncode == 0:
        return "tracked"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", relative], cwd=PROJECT_ROOT, check=False
    )
    return "gitignored" if ignored.returncode == 0 else "untracked_not_ignored"


def _checksum(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> pd.DataFrame:
    if path.suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported audit table: {path}")


def profile_input(
    *,
    name: str,
    candidates: list[Path],
    selected: Path | None,
    units: str,
    provenance: str,
    classification: str,
    reason: str,
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "name": name,
        "candidate_paths": [str(path.relative_to(PROJECT_ROOT)) for path in candidates],
        "selected_path": (
            str(selected.relative_to(PROJECT_ROOT)) if selected and selected.exists() else None
        ),
        "available": bool(selected and selected.exists()),
        "units": units,
        "provenance": provenance,
        "classification": classification,
        "selection_reason": reason,
    }
    if not selected or not selected.exists():
        profile.update(
            {
                "git_state": "unavailable",
                "schema": [],
                "row_count": 0,
                "year_coverage": [],
                "scenario_coverage": [],
                "missingness_fraction": {},
            }
        )
        return profile
    profile["git_state"] = _git_state(selected)
    profile["sha256"] = _checksum(selected)
    if selected.suffix == ".json":
        value = json.loads(selected.read_text(encoding="utf-8"))
        profile.update(
            {
                "schema": sorted(value) if isinstance(value, dict) else ["json_array"],
                "row_count": len(value) if isinstance(value, list) else 1,
                "year_coverage": [],
                "scenario_coverage": [],
                "missingness_fraction": {},
            }
        )
        return profile
    data = _read(selected)
    year_column = next((column for column in data if column.lower() == "year"), None)
    scenario_column = next((column for column in data if column.lower() == "scenario"), None)
    profile.update(
        {
            "schema": [{"name": column, "dtype": str(data[column].dtype)} for column in data],
            "row_count": len(data),
            "year_coverage": (
                sorted(
                    pd.to_numeric(data[year_column], errors="coerce")
                    .dropna()
                    .astype(int)
                    .unique()
                    .tolist()
                )
                if year_column
                else []
            ),
            "scenario_coverage": (
                sorted(data[scenario_column].dropna().astype(str).unique().tolist())
                if scenario_column
                else []
            ),
            "missingness_fraction": data.isna().mean().round(6).to_dict(),
        }
    )
    return profile


def build_input_audit(config: dict[str, Any]) -> dict[str, Any]:
    inputs = config["inputs"]
    specifications = [
        (
            "macro_generation",
            inputs["macro_generation"],
            "TWh converted to MWh",
            "team-supplied MACRO/GCAM-KAIST deliverable",
            "external modeled",
            "only local MACRO generation table",
        ),
        (
            "macro_metadata",
            inputs["macro_metadata"],
            "metadata",
            "existing ingestion provenance sidecar",
            "processed provenance",
            "checksum and contributor record for selected MACRO deliverable",
        ),
        (
            "observed_generation",
            inputs["observed_generation"],
            "MWh",
            "existing EPSIS 2021 validation handoff",
            "processed observed",
            "national observed thermal generation with existing crosswalk",
        ),
        (
            "kepco_monthly",
            inputs["kepco_monthly"],
            "MWh, MW, kg",
            "existing five-subsidiary canonical processed panel",
            "processed observed",
            "canonical current data layout",
        ),
        (
            "annual_fuel_technology_ef",
            inputs["ef_table"],
            "kg/MWh",
            "existing KEPCO annual handoff",
            "processed observed",
            "contains generation-weighted central ef_kg_per_mwh",
        ),
        (
            "plant_location_dates",
            inputs["plant_location_dates"],
            "degrees and ISO dates",
            "existing evidence-backed crosswalk",
            "processed crosswalk",
            "canonical name-matched coordinates and commissioning dates",
        ),
        (
            "plant_geography",
            inputs["plant_geography"],
            "administrative labels",
            "existing crosswalk",
            "processed crosswalk",
            "canonical province labels",
        ),
        (
            "retirement_dates",
            inputs["retirement_dates"],
            "ISO dates",
            "existing official-evidence crosswalk",
            "processed crosswalk",
            "unit-specific actual/planned dates",
        ),
        (
            "stack_properties",
            inputs["stack_properties"],
            "m, C, m/s",
            "existing CREA-based evidence crosswalk",
            "processed crosswalk",
            "only local observed stack table",
        ),
        (
            "stack_unit_map",
            inputs["stack_unit_map"],
            "identifiers",
            "existing stack-to-reporting-unit crosswalk",
            "processed crosswalk",
            "explicit unit links without fuzzy matching",
        ),
        (
            "technology_mapping",
            inputs["technology_mapping"],
            "technology labels",
            "existing evidence-backed KEPCO technology crosswalk",
            "processed crosswalk",
            "canonical reporting-boundary technologies",
        ),
        (
            "province_level_power",
            inputs["province_level_power"],
            "MW, coordinates, years",
            "existing province-level plant workbook",
            "processed reference",
            "evidence for explicitly configured representative thermal sites",
        ),
        (
            "population_projection",
            inputs["population_projection"],
            "persons",
            "KOSIS DT_1BPB002E",
            "observed official projection",
            "documented target-year projection through 2042",
        ),
        (
            "age_mortality_all_cause",
            inputs["age_mortality_all_cause"],
            "deaths and deaths/100,000",
            "KOSIS DT_1B80A18",
            "observed official",
            "latest compatible age-specific all-cause mortality",
        ),
        (
            "crf_parameters",
            inputs["crf_parameters"],
            "per ug/m3",
            "literature-backed Peng and Korean CRF registry",
            "processed literature evidence",
            "recommended primary and sensitivity specifications",
        ),
        (
            "gemm_parameters",
            inputs["gemm_parameters"],
            "dimensionless model parameters and ug/m3",
            "Burnett et al. 2018 SI Table S2",
            "processed literature evidence",
            "age-specific GEMM NCD+LRI sensitivity parameters",
        ),
    ]
    profiles = [
        profile_input(
            name=name,
            candidates=[path],
            selected=path,
            units=units,
            provenance=provenance,
            classification=classification,
            reason=reason,
        )
        for name, path, units, provenance, classification, reason in specifications
    ]
    profiles.extend(
        [
            profile_input(
                name="age_mortality_non_accidental",
                candidates=(
                    [inputs["age_mortality_non_accidental"]]
                    if inputs.get("age_mortality_non_accidental")
                    else []
                ),
                selected=inputs.get("age_mortality_non_accidental"),
                units="deaths and deaths/100,000",
                provenance="endpoint-matched national age-specific mortality input",
                classification=(
                    "observed official"
                    if inputs.get("age_mortality_non_accidental")
                    else "unavailable"
                ),
                reason=(
                    "required by the Byun non-accidental specification; "
                    "all-cause mortality is never substituted"
                ),
            ),
            profile_input(
                name="age_mortality_ncd_lri",
                candidates=(
                    [inputs["age_mortality_ncd_lri"]]
                    if inputs.get("age_mortality_ncd_lri")
                    else []
                ),
                selected=inputs.get("age_mortality_ncd_lri"),
                units="deaths and deaths/100,000",
                provenance="endpoint-matched national age-specific mortality input",
                classification=(
                    "observed official" if inputs.get("age_mortality_ncd_lri") else "unavailable"
                ),
                reason=(
                    "required by GEMM NCD+LRI; generic non-accidental and all-cause "
                    "mortality are never substituted"
                ),
            ),
            profile_input(
                name="district_boundaries",
                candidates=[],
                selected=None,
                units="geometry",
                provenance="not present locally",
                classification="unavailable",
                reason="district exposure excluded; uniform population allocation is forbidden",
            ),
            profile_input(
                name="population_raster",
                candidates=[],
                selected=None,
                units="persons per grid cell",
                provenance="Global InMAP v1.1.0 TotalPop used after installation",
                classification="external model data",
                reason="preferred model-compatible population field",
            ),
        ]
    )
    return {
        "audit_version": 1,
        "project_root": ".",
        "inputs": profiles,
        "scientific_scope": {
            "sector": "Korean thermal power only",
            "ambient_interpretation": "incremental included-source PM2.5, not total ambient PM2.5",
            "foreign_emissions": "excluded",
            "non_power_emissions": "excluded",
            "district_exposure": "unavailable because compatible boundaries/raster are absent",
        },
    }


def write_input_audit(audit: dict[str, Any], *paths: Path) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
