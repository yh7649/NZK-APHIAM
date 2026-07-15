"""Build projected sector-fuel emissions from GCAM-KAIST activity and CAPSS."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from nzk_aphiam.config.paths import CAPSS_INTERIM_DIR, MACRO_PROCESSED_DIR, MACRO_RAW_DIR
from nzk_aphiam.data.process.capss.processor import normalize_label

DEFAULT_CAPSS_PATH = CAPSS_INTERIM_DIR / "emissions_statistics" / "capss_emissions_tidy.parquet"
DEFAULT_GCAM_PATH = MACRO_RAW_DIR / "gcam_kaist_sector_fuel_activity.csv"
DEFAULT_POLLUTANTS = ("SOx", "NOx", "NH3", "VOCs", "PM2.5")
MAPPING_COLUMNS = ("gcam_sector", "gcam_fuel", "capss_sector", "capss_fuel")


def _normalized_key(value: object) -> str:
    return normalize_label(value) or "missing"


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if path.suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported table format for {path}; use CSV, Excel, or Parquet.")


def _write_table(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        data.to_parquet(path, index=False)
    else:
        data.to_csv(path, index=False)


def _split_csv(value: str | None) -> list[str]:
    if value is None or value == "":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _capss_sector_column(level: str) -> str:
    return {
        "category": "source_category",
        "midcategory": "source_midcategory",
        "subcategory": "source_subcategory",
    }[level]


def _capss_fuel_column(level: str) -> str:
    return {
        "category": "fuel_category",
        "type": "fuel_type",
    }[level]


def _validate_columns(data: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _prepare_mapping(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    mapping = _read_table(path)
    _validate_columns(mapping, MAPPING_COLUMNS, "mapping file")
    mapping = mapping.loc[:, MAPPING_COLUMNS].copy()
    mapping["gcam_sector_key"] = mapping["gcam_sector"].map(_normalized_key)
    mapping["gcam_fuel_key"] = mapping["gcam_fuel"].map(_normalized_key)
    mapping["capss_sector"] = mapping["capss_sector"].map(_normalized_key)
    mapping["capss_fuel"] = mapping["capss_fuel"].map(_normalized_key)
    duplicate = mapping.duplicated(["gcam_sector_key", "gcam_fuel_key"], keep=False)
    if duplicate.any():
        pairs = mapping.loc[duplicate, ["gcam_sector", "gcam_fuel"]].drop_duplicates()
        raise ValueError(
            f"mapping file has duplicate GCAM sector/fuel rows: {pairs.to_dict('records')}"
        )
    return mapping[["gcam_sector_key", "gcam_fuel_key", "capss_sector", "capss_fuel"]]


def prepare_gcam_activity(
    activity: pd.DataFrame,
    *,
    year_column: str,
    sector_column: str,
    fuel_column: str,
    activity_column: str,
    scenario_columns: list[str],
    mapping: pd.DataFrame | None,
) -> pd.DataFrame:
    required = [year_column, sector_column, fuel_column, activity_column, *scenario_columns]
    _validate_columns(activity, required, "GCAM activity")

    prepared = activity.copy()
    prepared["year"] = pd.to_numeric(prepared[year_column], errors="raise").astype(int)
    prepared["activity"] = pd.to_numeric(prepared[activity_column], errors="coerce")
    prepared["gcam_sector"] = prepared[sector_column].astype("string")
    prepared["gcam_fuel"] = prepared[fuel_column].astype("string")
    prepared["gcam_sector_key"] = prepared["gcam_sector"].map(_normalized_key)
    prepared["gcam_fuel_key"] = prepared["gcam_fuel"].map(_normalized_key)

    if mapping is not None:
        prepared = prepared.merge(mapping, how="left", on=["gcam_sector_key", "gcam_fuel_key"])
        prepared["mapping_status"] = (
            prepared["capss_sector"].notna().map({True: "mapped", False: "unmapped_passthrough"})
        )
    else:
        prepared["capss_sector"] = pd.NA
        prepared["capss_fuel"] = pd.NA
        prepared["mapping_status"] = "no_mapping_file"

    prepared["capss_sector"] = prepared["capss_sector"].fillna(prepared["gcam_sector_key"])
    prepared["capss_fuel"] = prepared["capss_fuel"].fillna(prepared["gcam_fuel_key"])
    return prepared


def prepare_capss_emissions(
    capss: pd.DataFrame,
    *,
    base_year: int,
    pollutants: list[str],
    sector_level: str,
    fuel_level: str,
) -> pd.DataFrame:
    sector_column = _capss_sector_column(sector_level)
    fuel_column = _capss_fuel_column(fuel_level)
    required = ["year", sector_column, fuel_column, "fuel_category", "pollutant", "emissions_kg"]
    _validate_columns(capss, required, "CAPSS emissions")

    filtered = capss.loc[
        (capss["year"] == base_year) & (capss["pollutant"].isin(pollutants))
    ].copy()
    if filtered.empty:
        raise ValueError(
            f"CAPSS emissions have no rows for base year {base_year} and pollutants {pollutants}."
        )

    filtered["capss_sector"] = filtered[sector_column].map(_normalized_key)
    fuel_source = filtered[fuel_column]
    if fuel_column == "fuel_type":
        fuel_source = fuel_source.fillna(filtered["fuel_category"])
    filtered["capss_fuel"] = fuel_source.map(_normalized_key)
    filtered["emissions_kg"] = pd.to_numeric(filtered["emissions_kg"], errors="coerce")
    return (
        filtered.groupby(
            ["capss_sector", "capss_fuel", "pollutant"], dropna=False, as_index=False
        )["emissions_kg"]
        .sum()
        .sort_values(["capss_sector", "capss_fuel", "pollutant"])
    )


def choose_base_year(
    capss: pd.DataFrame, activity: pd.DataFrame, explicit_base_year: int | None
) -> int:
    if explicit_base_year is not None:
        return explicit_base_year
    capss_years = set(pd.to_numeric(capss["year"], errors="coerce").dropna().astype(int))
    activity_years = set(pd.to_numeric(activity["year"], errors="coerce").dropna().astype(int))
    common_years = sorted(capss_years & activity_years)
    if not common_years:
        raise ValueError(
            "Could not infer base year: CAPSS and GCAM activity have no overlapping years."
        )
    return common_years[-1]


def build_projection(
    *,
    gcam_activity: pd.DataFrame,
    capss_emissions: pd.DataFrame,
    base_year: int,
    scenario_columns: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key_columns = [*scenario_columns, "capss_sector", "capss_fuel"]
    base_activity = (
        gcam_activity.loc[gcam_activity["year"] == base_year]
        .groupby(key_columns, dropna=False, as_index=False)["activity"]
        .sum()
        .rename(columns={"activity": "base_activity"})
    )

    factors = capss_emissions.merge(base_activity, how="left", on=["capss_sector", "capss_fuel"])
    factors["emission_factor_kg_per_activity"] = factors["emissions_kg"] / factors["base_activity"]
    factors.loc[factors["base_activity"] <= 0, "emission_factor_kg_per_activity"] = pd.NA

    projection = gcam_activity.merge(
        factors[
            [
                *key_columns,
                "pollutant",
                "emissions_kg",
                "base_activity",
                "emission_factor_kg_per_activity",
            ]
        ],
        how="left",
        on=key_columns,
    )
    projection = projection.rename(columns={"emissions_kg": "capss_base_emissions_kg"})
    projection["projected_emissions_kg"] = (
        projection["activity"] * projection["emission_factor_kg_per_activity"]
    )

    factor_key = capss_emissions.loc[:, ["capss_sector", "capss_fuel"]].drop_duplicates()
    activity_keys = gcam_activity.loc[:, key_columns].drop_duplicates()
    no_capss_match = activity_keys.merge(
        factor_key, how="left", on=["capss_sector", "capss_fuel"], indicator=True
    )
    no_capss_match = no_capss_match.loc[no_capss_match["_merge"] == "left_only", key_columns]
    no_capss_match["diagnostic"] = "gcam_activity_without_capss_emissions"

    factor_keys = factors.loc[
        factors["emission_factor_kg_per_activity"].notna(), key_columns
    ].drop_duplicates()
    no_emission_factor = activity_keys.merge(
        factor_keys, how="left", on=key_columns, indicator=True
    )
    no_emission_factor = no_emission_factor.loc[
        no_emission_factor["_merge"] == "left_only", key_columns
    ]
    no_emission_factor["diagnostic"] = "gcam_activity_without_emission_factor"

    zero_base_activity = base_activity.loc[
        base_activity["base_activity"].isna() | (base_activity["base_activity"] <= 0)
    ]
    zero_base_activity = zero_base_activity.loc[:, key_columns].copy()
    zero_base_activity["diagnostic"] = "missing_or_zero_base_activity"

    factor_without_base = factors.loc[
        factors["base_activity"].isna(), key_columns
    ].drop_duplicates()
    factor_without_base["diagnostic"] = "capss_emissions_without_gcam_base_activity"

    diagnostics = pd.concat(
        [no_capss_match, no_emission_factor, zero_base_activity, factor_without_base],
        ignore_index=True,
    ).drop_duplicates()
    return projection, factors, diagnostics


def integrate_macro_inputs(
    *,
    gcam_path: Path,
    capss_path: Path,
    output_dir: Path,
    mapping_path: Path | None = None,
    base_year: int | None = None,
    year_column: str = "year",
    sector_column: str = "sector",
    fuel_column: str = "fuel",
    activity_column: str = "activity",
    scenario_columns: list[str] | None = None,
    pollutants: list[str] | None = None,
    capss_sector_level: str = "category",
    capss_fuel_level: str = "category",
    output_format: str = "csv",
) -> dict[str, object]:
    pollutants = pollutants or list(DEFAULT_POLLUTANTS)
    scenario_columns = scenario_columns or []
    suffix = ".parquet" if output_format == "parquet" else ".csv"

    raw_gcam = _read_table(gcam_path)
    capss = _read_table(capss_path)
    mapping = _prepare_mapping(mapping_path)

    prepared_gcam = prepare_gcam_activity(
        raw_gcam,
        year_column=year_column,
        sector_column=sector_column,
        fuel_column=fuel_column,
        activity_column=activity_column,
        scenario_columns=scenario_columns,
        mapping=mapping,
    )
    resolved_base_year = choose_base_year(capss, prepared_gcam, base_year)
    capss_base = prepare_capss_emissions(
        capss,
        base_year=resolved_base_year,
        pollutants=pollutants,
        sector_level=capss_sector_level,
        fuel_level=capss_fuel_level,
    )
    projection, factors, diagnostics = build_projection(
        gcam_activity=prepared_gcam,
        capss_emissions=capss_base,
        base_year=resolved_base_year,
        scenario_columns=scenario_columns,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    projection_path = output_dir / f"macro_projected_emissions{suffix}"
    factors_path = output_dir / f"macro_capss_emission_factors{suffix}"
    diagnostics_path = output_dir / "macro_input_diagnostics.csv"
    metadata_path = output_dir / "macro_input_integration.metadata.json"

    _write_table(projection, projection_path)
    _write_table(factors, factors_path)
    diagnostics.to_csv(diagnostics_path, index=False)

    metadata: dict[str, object] = {
        "dataset": "GCAM-KAIST/MACRO activity integrated with CAPSS sector-fuel emission intensities",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "gcam_activity_path": str(gcam_path),
        "capss_emissions_path": str(capss_path),
        "mapping_path": str(mapping_path) if mapping_path else None,
        "base_year": resolved_base_year,
        "pollutants": pollutants,
        "capss_sector_level": capss_sector_level,
        "capss_fuel_level": capss_fuel_level,
        "scenario_columns": scenario_columns,
        "activity_column": activity_column,
        "activity_units": "as supplied by GCAM-KAIST input",
        "projection_rows": int(len(projection)),
        "factor_rows": int(len(factors)),
        "diagnostic_rows": int(len(diagnostics)),
        "outputs": {
            "projected_emissions": str(projection_path),
            "emission_factors": str(factors_path),
            "diagnostics": str(diagnostics_path),
        },
        "method_note": (
            "CAPSS base-year emissions are aggregated by selected sector/fuel keys, divided by "
            "base-year GCAM-KAIST activity, then multiplied by projected activity. Diagnostics "
            "must be reviewed before using unmatched rows."
        ),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Integrate GCAM-KAIST/MACRO sector-fuel activity with CAPSS emission intensities."
    )
    parser.add_argument("--gcam-activity", type=Path, default=DEFAULT_GCAM_PATH)
    parser.add_argument("--capss-emissions", type=Path, default=DEFAULT_CAPSS_PATH)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--output-dir", type=Path, default=MACRO_PROCESSED_DIR)
    parser.add_argument("--base-year", type=int)
    parser.add_argument("--year-column", default="year")
    parser.add_argument("--sector-column", default="sector")
    parser.add_argument("--fuel-column", default="fuel")
    parser.add_argument("--activity-column", default="activity")
    parser.add_argument("--scenario-columns", default="")
    parser.add_argument("--pollutants", default=",".join(DEFAULT_POLLUTANTS))
    parser.add_argument(
        "--capss-sector-level",
        choices=["category", "midcategory", "subcategory"],
        default="category",
    )
    parser.add_argument("--capss-fuel-level", choices=["category", "type"], default="category")
    parser.add_argument("--output-format", choices=["csv", "parquet"], default="csv")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    metadata = integrate_macro_inputs(
        gcam_path=args.gcam_activity,
        capss_path=args.capss_emissions,
        output_dir=args.output_dir,
        mapping_path=args.mapping,
        base_year=args.base_year,
        year_column=args.year_column,
        sector_column=args.sector_column,
        fuel_column=args.fuel_column,
        activity_column=args.activity_column,
        scenario_columns=_split_csv(args.scenario_columns),
        pollutants=_split_csv(args.pollutants),
        capss_sector_level=args.capss_sector_level,
        capss_fuel_level=args.capss_fuel_level,
        output_format=args.output_format,
    )
    print(json.dumps(metadata["outputs"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
