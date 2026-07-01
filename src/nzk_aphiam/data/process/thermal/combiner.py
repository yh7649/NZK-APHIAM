"""Build subsidiary-level and combined unit-standardized, audited KEPCO products.

Each subsidiary is cleaned, unit-standardized, and audited for outliers
before the final combined dataset is built, so the merged file is
analysis-ready the moment this command finishes -- there is no unaudited
intermediate state to forget to follow up on.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from nzk_aphiam.config.paths import THERMAL_INTERIM_DIR, THERMAL_PROCESSED_DIR
from nzk_aphiam.data.audit.thermal.auditor import RESULTS_DIR, audit_all
from nzk_aphiam.data.clean.thermal.schema import (
    COMBINED_THERMAL_OUTPUT_COLUMNS,
    THERMAL_OUTPUT_COLUMNS,
)

OUTPUT_PATH = THERMAL_PROCESSED_DIR / "kepco_monthly_generation_emissions.csv"
METADATA_PATH = THERMAL_PROCESSED_DIR / "kepco_monthly_generation_emissions_metadata.csv"
SUBSIDIARY_OUTPUT_DIR = THERMAL_PROCESSED_DIR / "subsidiaries"
COVERAGE_PATH = SUBSIDIARY_OUTPUT_DIR / "subsidiary_coverage.csv"
POLLUTANT_COLUMNS = ("nox", "sox", "dust_tsp")
POLLUTANT_UNIT_COLUMNS = {
    "nox": "nox_unit",
    "sox": "sox_unit",
    "dust_tsp": "dust_tsp_unit",
}
MASS_TO_KILOGRAMS = {
    "kilograms": 1.0,
    "metric_tonnes": 1000.0,
}
VARIABLE_LABELS = {
    "source_dataset": "Source interim dataset (categorical identifier)",
    "operator_category": "Operator category for the combined dataset (kepco)",
    "observation_frequency": "Observation frequency (monthly)",
    "date": "Observation month (YYYY-MM-DD; first day of month)",
    "plant_name": "Power plant name (English)",
    "plant_number": "Generating unit number (unitless identifier)",
    "plant_opening_date": "Plant opening date (YYYY-MM-DD)",
    "plant_closing_date": "Plant closing date (YYYY-MM-DD)",
    "plant_latitude": "Plant latitude (WGS84 decimal degrees north)",
    "plant_longitude": "Plant longitude (WGS84 decimal degrees east)",
    "plant_province": "Plant province or metropolitan city (current English name)",
    "plant_district": "Plant city, county, or autonomous district (current English name)",
    "subsidiary_company": "KEPCO subsidiary company name",
    "energy_type": "Primary energy or fuel type (categorical)",
    "energy_generated_mwh": "Monthly electricity generation (MWh)",
    "energy_capacity_mw": "Installed generating capacity (MW)",
    "reporting_unit_id": "Stable source reporting-boundary identifier",
    "reporting_start_date": "First month with reported generation or pollutant activity (YYYY-MM-DD)",
    "reporting_end_date": "Documented reporting-boundary retirement date (YYYY-MM-DD)",
    "reporting_window_basis": "Evidence defining the reporting activity window",
    "observation_level": "Physical reporting boundary (generating_unit, gas_turbine, generation_block, plant, or unresolved)",
    "component_count": "Number of source generation components aggregated to the observation",
    "generation_source": "Generation source selected for the monthly value",
    "generation_days_reported": "Minimum distinct source days reported across contributing components",
    "generation_days_expected": "Calendar days expected in the observation month",
    "generation_coverage_status": "Generation day coverage status (complete, partial, or missing)",
    "alternate_energy_generated_mwh": "Monthly generation from the alternate official source (MWh)",
    "generation_difference_pct": "Absolute percent difference between primary and alternate generation",
    "generation_reconciliation_status": "Cross-source generation comparison or fallback status",
    "row_status": "Evidence-based row status (active_reported, active_partial, inactive_placeholder, or unknown_status)",
    "row_status_basis": "Evidence used to assign row_status",
    "nox": "Monthly nitrogen oxides emissions (kg)",
    "sox": "Monthly sulfur oxides emissions (kg)",
    "dust_tsp": "Monthly total suspended particulate emissions (kg)",
    "pollutant_data_pattern": "Pollutant fields reported on the source row",
    "pollutant_measurement_basis": "Pollutant measurement basis (mass)",
    "nox_unit": "Nitrogen oxides unit (canonical value: kilograms)",
    "sox_unit": "Sulfur oxides unit (canonical value: kilograms)",
    "dust_tsp_unit": "Total suspended particulate unit (canonical value: kilograms)",
    "emissions_mass_unit": "Common pollutant mass unit (canonical value: kilograms)",
    "original_korean_plant_name": "Original Korean plant name",
    "original_korean_unit_name": "Original Korean generating unit name",
    "original_korean_note": "Original Korean source note",
}


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    frequency: str
    path: Path


DATASET_SPECS = (
    DatasetSpec(
        "eastwest_power",
        "monthly",
        THERMAL_INTERIM_DIR / "eastwest_power" / "eastwest_power_monthly_generation_emissions.csv",
    ),
    DatasetSpec(
        "western_power",
        "monthly",
        THERMAL_INTERIM_DIR / "western_power" / "western_power_monthly_generation_emissions.csv",
    ),
    DatasetSpec(
        "southern_power",
        "monthly",
        THERMAL_INTERIM_DIR / "southern_power" / "southern_power_monthly_generation_emissions.csv",
    ),
    DatasetSpec(
        "southeast_power",
        "monthly",
        THERMAL_INTERIM_DIR / "southeast_power" / "southeast_power_monthly_derived_emissions.csv",
    ),
    DatasetSpec(
        "midland_power",
        "monthly",
        THERMAL_INTERIM_DIR / "midland_power" / "midland_power_monthly_derived_emissions.csv",
    ),
)


def validate_interim_dataset(data: pd.DataFrame, spec: DatasetSpec) -> None:
    """Reject schema or unit changes that would make concatenation ambiguous."""
    if list(data.columns) != THERMAL_OUTPUT_COLUMNS:
        raise ValueError(
            f"Unexpected columns in {spec.name}. "
            f"Expected {THERMAL_OUTPUT_COLUMNS!r}, received {list(data.columns)!r}."
        )

    dates = pd.to_datetime(data["date"], errors="raise")
    if spec.frequency == "monthly" and not dates.dt.is_month_start.all():
        raise ValueError(f"{spec.name} contains dates that are not month starts.")

    bases = set(data["pollutant_measurement_basis"].dropna())
    if bases != {"mass"}:
        raise ValueError(
            f"{spec.name} must contain only pollutant mass observations; received {sorted(bases)}."
        )

    mass_rows = data["pollutant_measurement_basis"].eq("mass")

    mass_units = set(data.loc[mass_rows, "emissions_mass_unit"].dropna())
    unsupported_mass_units = mass_units - set(MASS_TO_KILOGRAMS)
    if unsupported_mass_units:
        raise ValueError(
            f"{spec.name} contains unsupported emissions mass units: "
            f"{sorted(unsupported_mass_units)}"
        )
    if mass_rows.any() and data.loc[mass_rows, "emissions_mass_unit"].isna().any():
        raise ValueError(f"{spec.name} has mass rows without emissions_mass_unit.")

    for pollutant, unit_column in POLLUTANT_UNIT_COLUMNS.items():
        reported = data[pollutant].notna()
        if data.loc[reported, unit_column].isna().any():
            raise ValueError(f"{spec.name} has reported {pollutant} values without units.")

        pollutant_mass_units = set(data.loc[mass_rows & reported, unit_column].dropna())
        unsupported = pollutant_mass_units - set(MASS_TO_KILOGRAMS)
        if unsupported:
            raise ValueError(
                f"{spec.name} contains unsupported {pollutant} mass units: {sorted(unsupported)}"
            )


def standardize_mass_to_kilograms(data: pd.DataFrame) -> pd.DataFrame:
    """Convert every reported pollutant mass to kilograms."""
    result = data.copy()
    mass_rows = result["pollutant_measurement_basis"].eq("mass")

    for pollutant, unit_column in POLLUTANT_UNIT_COLUMNS.items():
        factors = result[unit_column].map(MASS_TO_KILOGRAMS)
        rows = mass_rows & result[pollutant].notna()
        result.loc[rows, pollutant] = result.loc[rows, pollutant] * factors.loc[rows]
        result.loc[mass_rows, unit_column] = "kilograms"

    result.loc[mass_rows, "emissions_mass_unit"] = "kilograms"
    return result


def prepare_dataset(data: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    """Validate and annotate one cleaned subsidiary dataset."""
    validate_interim_dataset(data, spec)
    prepared = standardize_mass_to_kilograms(data)
    prepared.insert(0, "observation_frequency", spec.frequency)
    prepared.insert(0, "operator_category", "kepco")
    prepared.insert(0, "source_dataset", spec.name)
    return prepared[COMBINED_THERMAL_OUTPUT_COLUMNS]


def combine_thermal_datasets(
    datasets: list[tuple[DatasetSpec, pd.DataFrame]],
) -> pd.DataFrame:
    """Return monthly pollutant-mass datasets in one canonical schema."""
    prepared = [prepare_dataset(data, spec) for spec, data in datasets]
    if not prepared:
        return pd.DataFrame(columns=COMBINED_THERMAL_OUTPUT_COLUMNS)

    combined = pd.concat(prepared, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="raise")
    return combined.sort_values(
        ["date", "source_dataset", "plant_name", "plant_number"],
        na_position="last",
        ignore_index=True,
    )


def process_subsidiary_datasets(
    datasets: list[tuple[DatasetSpec, pd.DataFrame]],
) -> dict[str, pd.DataFrame]:
    """Return one validated, unit-standardized dataset per subsidiary source."""
    return {
        spec.name: prepare_dataset(data, spec).sort_values(
            ["date", "plant_name", "plant_number"],
            na_position="last",
            ignore_index=True,
        )
        for spec, data in datasets
    }


def build_subsidiary_coverage(
    datasets: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Summarize field availability so analysts can choose fit-for-purpose sources."""
    value_columns = (
        "energy_type",
        "energy_generated_mwh",
        "energy_capacity_mw",
        "nox",
        "sox",
        "dust_tsp",
    )
    rows: list[dict[str, object]] = []
    for name, data in datasets.items():
        dates = pd.to_datetime(data["date"], errors="raise")
        if "row_status" in data:
            analysis_rows = ~data["row_status"].eq("inactive_placeholder").fillna(False)
        else:
            analysis_rows = pd.Series(True, index=data.index)
        row: dict[str, object] = {
            "source_dataset": name,
            "subsidiary_company": (
                data["subsidiary_company"].dropna().iloc[0]
                if data["subsidiary_company"].notna().any()
                else pd.NA
            ),
            "rows": len(data),
            "analysis_rows": int(analysis_rows.sum()),
            "inactive_placeholder_rows": int((~analysis_rows).sum()),
            "start_date": dates.min(),
            "end_date": dates.max(),
            "plant_count": data["plant_name"].nunique(dropna=True),
        }
        for column in value_columns:
            count = int(data.loc[analysis_rows, column].notna().sum())
            row[f"{column}_nonmissing"] = count
            denominator = int(analysis_rows.sum())
            row[f"{column}_coverage_pct"] = (
                round(100 * count / denominator, 2) if denominator else 0.0
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("source_dataset", ignore_index=True)


def save_subsidiary_datasets(datasets: dict[str, pd.DataFrame], output_dir: Path) -> None:
    """Write each subsidiary product under a stable source-specific filename."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in datasets.items():
        save_combined(data, output_dir / f"{name}_monthly_generation_emissions.csv")


def load_default_datasets() -> list[tuple[DatasetSpec, pd.DataFrame]]:
    """Read every implemented thermal interim dataset."""
    missing = [str(spec.path) for spec in DATASET_SPECS if not spec.path.exists()]
    if missing:
        raise FileNotFoundError("Missing thermal interim datasets:\n" + "\n".join(missing))
    return [(spec, pd.read_csv(spec.path, low_memory=False)) for spec in DATASET_SPECS]


def save_combined(data: pd.DataFrame, output_path: Path) -> None:
    """Write the canonical processed CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(output_path, index=False, date_format="%Y-%m-%d")


def build_variable_metadata() -> pd.DataFrame:
    """Return ordered variable names and labels for the processed dataset."""
    missing_labels = set(COMBINED_THERMAL_OUTPUT_COLUMNS) - set(VARIABLE_LABELS)
    extra_labels = set(VARIABLE_LABELS) - set(COMBINED_THERMAL_OUTPUT_COLUMNS)
    if missing_labels or extra_labels:
        raise ValueError(
            "Variable labels do not match the combined schema. "
            f"Missing: {sorted(missing_labels)}; extra: {sorted(extra_labels)}."
        )
    return pd.DataFrame(
        {
            "varname": COMBINED_THERMAL_OUTPUT_COLUMNS,
            "label": [VARIABLE_LABELS[name] for name in COMBINED_THERMAL_OUTPUT_COLUMNS],
        }
    )


def save_variable_metadata(metadata: pd.DataFrame, metadata_path: Path) -> None:
    """Write the processed dataset's variable dictionary."""
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata.to_csv(metadata_path, index=False)


def build_local_readme(combined: pd.DataFrame, coverage: pd.DataFrame) -> str:
    """Render current-value coverage matching the placeholders in
    docs/datasets/kepco_monthly_generation_emissions.md, so the local snapshot
    tracks whatever combine-kepco just produced.
    """
    dates = pd.to_datetime(combined["date"], errors="raise")
    unit_reporting = combined[
        ["source_dataset", "plant_name", "plant_number", "original_korean_unit_name"]
    ].drop_duplicates()
    numeric_units = combined.loc[
        combined["plant_number"].notna(),
        ["source_dataset", "plant_name", "plant_number"],
    ].drop_duplicates()

    def counts_block(column: str) -> str:
        counts = combined[column].fillna("unknown").value_counts()
        return "\n".join(f"- `{name}`: `{count:,}`" for name, count in counts.items())

    coordinates = combined[["plant_name", "plant_latitude", "plant_longitude"]].dropna(
        subset=["plant_latitude", "plant_longitude"]
    )
    distinct_pairs = coordinates.drop_duplicates(["plant_latitude", "plant_longitude"])
    total_rows = len(combined)

    def field_coverage_line(label: str, column: str) -> str:
        count = int(combined[column].notna().sum())
        return f"- {label}: `{count:,}` of `{total_rows:,}` rows (`{100 * count / total_rows:.0f}%`)"

    subsidiary_lines = []
    for _, row in coverage.sort_values("source_dataset").iterrows():
        parts = [
            f"{row['energy_type_coverage_pct']:.2f}% fuel"
            if row["energy_type_coverage_pct"] != 100
            else None,
            f"{row['energy_generated_mwh_coverage_pct']:.2f}% generation"
            if row["energy_generated_mwh_coverage_pct"] != 100
            else None,
            f"{row['energy_capacity_mw_coverage_pct']:.2f}% capacity"
            if row["energy_capacity_mw_coverage_pct"] != 100
            else None,
            f"{row['nox_coverage_pct']:.2f}% NOx",
            f"{row['sox_coverage_pct']:.2f}% SOx",
            f"{row['dust_tsp_coverage_pct']:.2f}% dust/TSP",
        ]
        detail = ", ".join(part for part in parts if part)
        placeholder_note = (
            f" and {row['inactive_placeholder_rows']:,} inactive placeholders excluded"
            if row["inactive_placeholder_rows"]
            else ""
        )
        subsidiary_lines.append(
            f"- {row['subsidiary_company']}: `{row['rows']:,}` rows"
            f"{placeholder_note}; {detail}."
        )

    return f"""# KEPCO Monthly Dataset: Current Local Values

This local file records the current generated values for:

- `kepco_monthly_generation_emissions.csv`
- `kepco_monthly_generation_emissions_metadata.csv`
- `subsidiaries/*_monthly_generation_emissions.csv`
- `subsidiaries/subsidiary_coverage.csv`

The tracked dataset description is:

- `docs/datasets/kepco_monthly_generation_emissions.md`

This folder is ignored by git, so these values are local snapshots. `make
combine-kepco` regenerates this file every time it regenerates the dataset, so
it should never go stale relative to the data actually on disk.

## Current Coverage

- Rows: `{total_rows:,}`
- Date range: `{dates.min().date()}` to `{dates.max().date()}`
- Plants: `{combined["plant_name"].nunique():,}`
- Unit/reporting identities: `{len(unit_reporting):,}`
- Numeric unit identities: `{len(numeric_units):,}`

Rows by source dataset:

{counts_block("source_dataset")}

Rows by KEPCO subsidiary:

{counts_block("subsidiary_company")}

Rows by cleaned fuel/energy type:

{counts_block("energy_type")}

Non-missing value counts:

- `energy_generated_mwh`: `{int(combined["energy_generated_mwh"].notna().sum()):,}`
- `energy_capacity_mw`: `{int(combined["energy_capacity_mw"].notna().sum()):,}`
- `nox`: `{int(combined["nox"].notna().sum()):,}`
- `sox`: `{int(combined["sox"].notna().sum()):,}`
- `dust_tsp`: `{int(combined["dust_tsp"].notna().sum()):,}`

## Plant Locations and Dates

Every current row is joined to the reviewed plant crosswalk before the
subsidiary datasets are combined and audited. The merged dataset includes
`plant_latitude`, `plant_longitude`, `plant_province`, `plant_district`,
`plant_opening_date`, and `plant_closing_date`.

{field_coverage_line("Coordinates", "plant_latitude")}
{field_coverage_line("Province", "plant_province")}
{field_coverage_line("District", "plant_district")}
{field_coverage_line("Opening date", "plant_opening_date")}
{field_coverage_line("Closing date", "plant_closing_date")}
- Distinct coordinate pairs: `{len(distinct_pairs):,}` across `{combined["plant_name"].nunique():,}` plant names

The source crosswalk is
`docs/references/crosswalk/plant_location_dates.csv`; reviewed administrative
geography is in `docs/references/crosswalk/plant_geography.csv`.

## Subsidiary Products

The preferred analysis inputs are the five files under `subsidiaries/`. Their
core-field coverage is summarized in `subsidiaries/subsidiary_coverage.csv`.

{chr(10).join(subsidiary_lines)}

## Refresh

These values are written automatically by:

```bash
make combine-kepco
```
"""


def save_local_readme(readme_text: str, readme_path: Path) -> None:
    """Write the local current-values README, replacing it atomically."""
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    partial = readme_path.with_suffix(".md.part")
    partial.write_text(readme_text, encoding="utf-8")
    partial.replace(readme_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build individual KEPCO subsidiary monthly datasets, standardize pollutant "
            "mass to kilograms, audit each subsidiary for outliers, and merge the "
            "audited subsidiary data into the final combined dataset."
        )
    )
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--metadata-path", type=Path, default=METADATA_PATH)
    parser.add_argument("--subsidiary-output-dir", type=Path, default=SUBSIDIARY_OUTPUT_DIR)
    parser.add_argument("--coverage-path", type=Path, default=COVERAGE_PATH)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--readme-path", type=Path, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    inputs = load_default_datasets()
    subsidiaries = process_subsidiary_datasets(inputs)
    save_subsidiary_datasets(subsidiaries, args.subsidiary_output_dir)
    coverage = build_subsidiary_coverage(subsidiaries)
    save_combined(coverage, args.coverage_path)

    metadata = build_variable_metadata()
    save_variable_metadata(metadata, args.metadata_path)

    # Audit each subsidiary's freshly standardized data and merge the
    # combined dataset from the audited results, not the raw inputs --
    # so the file at --output-path is never unaudited, even momentarily.
    audit_results = audit_all(
        list(subsidiaries.keys()),
        processed_dir=args.subsidiary_output_dir,
        results_dir=args.results_dir,
        combined_output_path=args.output_path,
        metadata_path=args.metadata_path,
    )
    combined_rows = sum(len(result.audited_data) for result in audit_results.values())

    readme_path = args.readme_path or args.output_path.parent / "README.md"
    combined = pd.read_csv(args.output_path, low_memory=False)
    save_local_readme(build_local_readme(combined, coverage), readme_path)

    print(f"Saved {len(subsidiaries)} subsidiary datasets to {args.subsidiary_output_dir}")
    print(f"Saved subsidiary coverage to {args.coverage_path}")
    print(f"Saved {len(metadata)} variable labels to {args.metadata_path}")
    print(
        f"Audited each subsidiary before merging; saved {combined_rows} rows to {args.output_path}"
    )
    for name, result in audit_results.items():
        flagged = result.audited_data["audit_severity"].notna().sum()
        critical = (
            int(result.flags["severity"].eq("critical").sum()) if not result.flags.empty else 0
        )
        print(f"  {name}: {flagged} flagged ({critical} critical)")
