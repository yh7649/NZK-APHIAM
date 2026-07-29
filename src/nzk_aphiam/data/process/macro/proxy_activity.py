"""Build a GCAM-KAIST-shaped non-power activity fixture for pipeline testing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from nzk_aphiam.config.paths import MACRO_PROCESSED_DIR, PROJECT_ROOT
from nzk_aphiam.data.process.capss.processor import normalize_label

DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "configs" / "scenarios" / "gcam_kaist_nonpower_proxy_2025_2050.yaml"
)
DEFAULT_OUTPUT_DIR = MACRO_PROCESSED_DIR / "scenarios" / "nonpower_proxy_2025_2050"
DETAILED_COLUMNS = [
    "fixture_status",
    "scenario",
    "year",
    "inventory_id",
    "conceptual_activity",
    "gcam_label_status",
    "gcam_cluster",
    "gcam_sector",
    "gcam_subsector",
    "gcam_technology",
    "gcam_fuel",
    "activity",
    "activity_unit",
    "reference_activity_unit",
    "activity_basis",
    "projection_profile",
    "endpoint_index_2050",
    "interpolation_method",
    "direct_emissions_scope",
    "electricity_only",
    "air_quality_supplemental",
    "double_counting_risk",
    "include_in_emissions_model",
    "model_exclusion_reason",
    "inventory_status",
    "projection_rationale",
]
COMPATIBILITY_COLUMNS = ["scenario", "year", "sector", "fuel", "activity"]
RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def _normalized_key(value: object) -> str:
    return normalize_label(value) or "missing"


def load_config(path: Path) -> dict[str, Any]:
    """Load and structurally validate the proxy scenario configuration."""
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")

    required = {
        "fixture_status",
        "base_year",
        "transition_start_year",
        "years",
        "base_activity_index",
        "activity_unit",
        "interpolation_method",
        "inputs",
        "scenarios",
        "profiles",
        "activity_profiles",
        "capss_sector_profiles",
        "pollutants",
        "assumptions",
        "sources",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"{path} is missing required configuration keys: {missing}")

    config["config_path"] = path.resolve()
    config["inputs"] = {key: _resolve_path(value) for key, value in config["inputs"].items()}
    years = [int(year) for year in config["years"]]
    if years != sorted(set(years)):
        raise ValueError("Scenario years must be unique and sorted.")
    if int(config["base_year"]) not in years:
        raise ValueError("Scenario years must include base_year.")
    if int(config["transition_start_year"]) not in years:
        raise ValueError("Scenario years must include transition_start_year.")

    scenario_names = set(config["scenarios"])
    for profile, definition in config["profiles"].items():
        endpoints = definition.get("endpoints_2050", {})
        if set(endpoints) != scenario_names:
            raise ValueError(
                f"Profile {profile!r} endpoints must exactly match scenarios "
                f"{sorted(scenario_names)}."
            )
        for scenario, endpoint in endpoints.items():
            value = float(endpoint)
            if value < 0:
                raise ValueError(
                    f"Profile {profile!r} has a negative {scenario!r} endpoint: {value}."
                )

    unknown_activity_profiles = sorted(set(config["activity_profiles"]) - set(config["profiles"]))
    if unknown_activity_profiles:
        raise ValueError(
            f"activity_profiles reference unknown profiles: {unknown_activity_profiles}"
        )
    for sector, definition in config["capss_sector_profiles"].items():
        profiles = [
            definition["default_profile"],
            *definition.get("fuel_profile_overrides", {}).values(),
        ]
        unknown = sorted(set(profiles) - set(config["profiles"]))
        if unknown:
            raise ValueError(f"CAPSS sector {sector!r} references unknown profiles: {unknown}")
    return config


def _activity_profile_map(config: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    duplicates: list[str] = []
    for profile, inventory_ids in config["activity_profiles"].items():
        for inventory_id in inventory_ids:
            if inventory_id in mapping:
                duplicates.append(inventory_id)
            mapping[inventory_id] = profile
    if duplicates:
        raise ValueError(
            f"Activities assigned to multiple projection profiles: {sorted(duplicates)}"
        )
    return mapping


def _activity_index(
    config: dict[str, Any],
    *,
    profile: str,
    scenario: str,
    year: int,
) -> float:
    base_index = float(config["base_activity_index"])
    start_year = int(config["transition_start_year"])
    end_year = max(int(value) for value in config["years"])
    if year <= start_year:
        return base_index
    endpoint = float(config["profiles"][profile]["endpoints_2050"][scenario])
    fraction = (year - start_year) / (end_year - start_year)
    return round(base_index + ((endpoint - base_index) * fraction), 6)


def _maximum_crosswalk_risk(crosswalk: pd.DataFrame) -> pd.Series:
    def maximum(values: pd.Series) -> str:
        clean = [str(value) for value in values.dropna() if str(value) in RISK_RANK]
        return max(clean, key=RISK_RANK.get) if clean else "unassessed"

    return crosswalk.groupby("inventory_id")["double_counting_risk"].apply(maximum)


def build_detailed_activity(
    inventory: pd.DataFrame,
    crosswalk: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Build the inventory-ID activity-index table for every scenario and year."""
    required_inventory = {
        "inventory_id",
        "conceptual_activity",
        "gcam_label_status",
        "priority",
        "include_in_mvp",
        "gcam_cluster",
        "gcam_sector",
        "gcam_subsector",
        "gcam_technology",
        "gcam_fuel",
        "activity_unit",
        "direct_emissions_scope",
        "electricity_only",
        "air_quality_supplemental",
        "status",
    }
    missing_inventory = sorted(required_inventory - set(inventory.columns))
    if missing_inventory:
        raise ValueError(f"Inventory is missing required columns: {missing_inventory}")
    required_crosswalk = {"inventory_id", "double_counting_risk"}
    missing_crosswalk = sorted(required_crosswalk - set(crosswalk.columns))
    if missing_crosswalk:
        raise ValueError(f"Crosswalk is missing required columns: {missing_crosswalk}")

    include = inventory["include_in_mvp"].astype(str).str.lower().eq("true")
    selected = inventory.loc[include & inventory["priority"].eq("P1")].copy()
    if selected["inventory_id"].duplicated().any():
        duplicates = selected.loc[
            selected["inventory_id"].duplicated(keep=False), "inventory_id"
        ].tolist()
        raise ValueError(f"Selected inventory has duplicate IDs: {sorted(set(duplicates))}")

    profile_map = _activity_profile_map(config)
    selected_ids = set(selected["inventory_id"])
    missing_profiles = sorted(selected_ids - set(profile_map))
    extra_profiles = sorted(set(profile_map) - selected_ids)
    if missing_profiles or extra_profiles:
        raise ValueError(
            "Activity profile coverage must exactly match P1 MVP inventory IDs; "
            f"missing={missing_profiles}, extra={extra_profiles}."
        )

    risk = _maximum_crosswalk_risk(crosswalk)
    exclusions = config.get("excluded_from_emissions_model", {})
    rows: list[dict[str, Any]] = []
    for record in selected.sort_values("inventory_id").to_dict("records"):
        inventory_id = str(record["inventory_id"])
        profile = profile_map[inventory_id]
        for scenario in config["scenarios"]:
            endpoint = float(config["profiles"][profile]["endpoints_2050"][scenario])
            for year in config["years"]:
                rows.append(
                    {
                        "fixture_status": config["fixture_status"],
                        "scenario": scenario,
                        "year": int(year),
                        "inventory_id": inventory_id,
                        "conceptual_activity": record["conceptual_activity"],
                        "gcam_label_status": record["gcam_label_status"],
                        "gcam_cluster": record["gcam_cluster"],
                        "gcam_sector": record["gcam_sector"],
                        "gcam_subsector": record["gcam_subsector"],
                        "gcam_technology": record["gcam_technology"],
                        "gcam_fuel": record["gcam_fuel"],
                        "activity": _activity_index(
                            config,
                            profile=profile,
                            scenario=scenario,
                            year=int(year),
                        ),
                        "activity_unit": config["activity_unit"],
                        "reference_activity_unit": record["activity_unit"],
                        "activity_basis": "synthetic_normalized_index_not_physical_quantity",
                        "projection_profile": profile,
                        "endpoint_index_2050": endpoint,
                        "interpolation_method": config["interpolation_method"],
                        "direct_emissions_scope": record["direct_emissions_scope"],
                        "electricity_only": record["electricity_only"],
                        "air_quality_supplemental": record["air_quality_supplemental"],
                        "double_counting_risk": risk.get(inventory_id, "unassessed"),
                        "include_in_emissions_model": inventory_id not in exclusions,
                        "model_exclusion_reason": exclusions.get(inventory_id, ""),
                        "inventory_status": record["status"],
                        "projection_rationale": config["profiles"][profile]["rationale"],
                    }
                )
    return pd.DataFrame(rows, columns=DETAILED_COLUMNS).sort_values(
        ["scenario", "year", "gcam_cluster", "inventory_id"], kind="stable"
    )


def _capss_profile(
    config: dict[str, Any],
    *,
    sector: str,
    fuel: str,
) -> str:
    definition = config["capss_sector_profiles"][sector]
    return definition.get("fuel_profile_overrides", {}).get(fuel, definition["default_profile"])


def build_capss_compatibility(
    capss: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a five-column CAPSS-aligned activity-index smoke-test input."""
    required = {"year", "source_category", "fuel_category", "pollutant"}
    missing = sorted(required - set(capss.columns))
    if missing:
        raise ValueError(f"CAPSS emissions are missing required columns: {missing}")

    base_year = int(config["base_year"])
    filtered = capss.loc[
        capss["year"].eq(base_year) & capss["pollutant"].isin(config["pollutants"])
    ].copy()
    if filtered.empty:
        raise ValueError(f"CAPSS emissions have no {base_year} rows for {config['pollutants']}.")
    filtered["sector"] = filtered["source_category"].map(_normalized_key)
    filtered["fuel"] = filtered["fuel_category"].map(_normalized_key)

    configured_sectors = {
        _normalized_key(sector): definition
        for sector, definition in config["capss_sector_profiles"].items()
    }
    excluded_sectors = {
        _normalized_key(sector): reason
        for sector, reason in config.get("excluded_capss_sectors", {}).items()
    }
    observed_sectors = set(filtered["sector"])
    uncovered = sorted(observed_sectors - set(configured_sectors) - set(excluded_sectors))
    if uncovered:
        raise ValueError(f"Observed CAPSS sectors lack a proxy profile or exclusion: {uncovered}")

    pairs = (
        filtered.loc[filtered["sector"].isin(configured_sectors), ["sector", "fuel"]]
        .drop_duplicates()
        .sort_values(["sector", "fuel"], kind="stable")
    )
    compatibility_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for pair in pairs.itertuples(index=False):
        profile = _capss_profile(config, sector=pair.sector, fuel=pair.fuel)
        for scenario in config["scenarios"]:
            endpoint = float(config["profiles"][profile]["endpoints_2050"][scenario])
            for year in config["years"]:
                activity = _activity_index(
                    config,
                    profile=profile,
                    scenario=scenario,
                    year=int(year),
                )
                compatibility_rows.append(
                    {
                        "scenario": scenario,
                        "year": int(year),
                        "sector": pair.sector,
                        "fuel": pair.fuel,
                        "activity": activity,
                    }
                )
                audit_rows.append(
                    {
                        "fixture_status": config["fixture_status"],
                        "scenario": scenario,
                        "year": int(year),
                        "sector": pair.sector,
                        "fuel": pair.fuel,
                        "activity": activity,
                        "activity_unit": config["activity_unit"],
                        "activity_basis": "synthetic_normalized_index_not_physical_quantity",
                        "projection_profile": profile,
                        "endpoint_index_2050": endpoint,
                        "interpolation_method": config["interpolation_method"],
                        "projection_rationale": config["profiles"][profile]["rationale"],
                    }
                )

    compatibility = pd.DataFrame(compatibility_rows, columns=COMPATIBILITY_COLUMNS)
    audit = pd.DataFrame(audit_rows)
    sort_columns = ["scenario", "year", "sector", "fuel"]
    return (
        compatibility.sort_values(sort_columns, kind="stable"),
        audit.sort_values(sort_columns, kind="stable"),
    )


def summarize_proxy(detailed: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    """Return compact mean-index checks for the detailed and compatibility tables."""
    detailed_summary = (
        detailed.groupby(["scenario", "year", "gcam_cluster"], as_index=False)
        .agg(
            rows=("inventory_id", "size"),
            included_rows=("include_in_emissions_model", "sum"),
            mean_activity_index=("activity", "mean"),
            minimum_activity_index=("activity", "min"),
            maximum_activity_index=("activity", "max"),
        )
        .rename(columns={"gcam_cluster": "group"})
    )
    detailed_summary.insert(0, "table", "inventory_id_activity")

    compatibility_summary = (
        audit.groupby(["scenario", "year", "sector"], as_index=False)
        .agg(
            rows=("fuel", "size"),
            mean_activity_index=("activity", "mean"),
            minimum_activity_index=("activity", "min"),
            maximum_activity_index=("activity", "max"),
        )
        .rename(columns={"sector": "group"})
    )
    compatibility_summary["included_rows"] = compatibility_summary["rows"]
    compatibility_summary.insert(0, "table", "capss_sector_fuel_compatibility")
    return pd.concat(
        [detailed_summary, compatibility_summary],
        ignore_index=True,
    ).sort_values(["table", "scenario", "year", "group"], kind="stable")


def _metadata(
    *,
    config: dict[str, Any],
    outputs: dict[str, Path],
    detailed: pd.DataFrame,
    compatibility: pd.DataFrame,
) -> dict[str, Any]:
    input_paths = {"config": config["config_path"], **config["inputs"]}
    excluded_sectors = {
        _normalized_key(sector): reason
        for sector, reason in config.get("excluded_capss_sectors", {}).items()
    }
    return {
        "fixture_status": config["fixture_status"],
        "warning": (
            "Synthetic normalized activity indices for pipeline testing only; "
            "not GCAM-KAIST model output and not a forecast."
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator": "nzk_aphiam.data.process.macro.proxy_activity",
        "config_path": _relative_path(config["config_path"]),
        "inputs": {
            key: {"path": _relative_path(path), "sha256": _sha256(path)}
            for key, path in input_paths.items()
        },
        "outputs": {
            key: {"path": _relative_path(path), "sha256": _sha256(path)}
            for key, path in outputs.items()
            if path.exists()
        },
        "base_year": int(config["base_year"]),
        "transition_start_year": int(config["transition_start_year"]),
        "scenario_years": [int(year) for year in config["years"]],
        "scenarios": config["scenarios"],
        "activity_unit": config["activity_unit"],
        "detailed_activity_rows": int(len(detailed)),
        "detailed_inventory_ids": int(detailed["inventory_id"].nunique()),
        "compatibility_rows": int(len(compatibility)),
        "compatibility_sector_fuel_pairs": int(
            compatibility[["sector", "fuel"]].drop_duplicates().shape[0]
        ),
        "excluded_from_emissions_model": config.get("excluded_from_emissions_model", {}),
        "excluded_capss_sectors": excluded_sectors,
        "assumptions": config["assumptions"],
        "sources": config["sources"],
    }


def generate_proxy(config_path: Path, output_dir: Path) -> dict[str, Path]:
    """Generate detailed, compatibility, audit, summary, and metadata outputs."""
    config = load_config(config_path)
    inventory = pd.read_csv(config["inputs"]["inventory"])
    crosswalk = pd.read_csv(config["inputs"]["crosswalk"])
    capss = pd.read_parquet(config["inputs"]["capss_emissions"])

    detailed = build_detailed_activity(inventory, crosswalk, config)
    compatibility, audit = build_capss_compatibility(capss, config)
    summary = summarize_proxy(detailed, audit)

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "detailed_csv": output_dir / "gcam_kaist_nonpower_activity_proxy_2023_2050.csv",
        "detailed_parquet": output_dir / "gcam_kaist_nonpower_activity_proxy_2023_2050.parquet",
        "compatibility_csv": output_dir / "gcam_kaist_sector_fuel_activity_proxy_2023_2050.csv",
        "compatibility_audit_csv": output_dir
        / "gcam_kaist_sector_fuel_activity_proxy_2023_2050.audit.csv",
        "summary_csv": output_dir / "gcam_kaist_nonpower_activity_proxy_summary.csv",
    }
    detailed.to_csv(outputs["detailed_csv"], index=False)
    detailed.to_parquet(outputs["detailed_parquet"], index=False)
    compatibility.to_csv(outputs["compatibility_csv"], index=False)
    audit.to_csv(outputs["compatibility_audit_csv"], index=False)
    summary.to_csv(outputs["summary_csv"], index=False)

    metadata_path = output_dir / "gcam_kaist_nonpower_activity_proxy_2023_2050.metadata.json"
    outputs["metadata_json"] = metadata_path
    metadata_path.write_text(
        json.dumps(
            _metadata(
                config=config,
                outputs=outputs,
                detailed=detailed,
                compatibility=compatibility,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    outputs = generate_proxy(args.config.resolve(), args.output_dir.resolve())
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
