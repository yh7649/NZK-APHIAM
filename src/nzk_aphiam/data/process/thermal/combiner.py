"""Combine thermal interim datasets into one unit-standardized product."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from nzk_aphiam.config.paths import THERMAL_INTERIM_DIR, THERMAL_PROCESSED_DIR
from nzk_aphiam.data.clean.thermal.schema import (
    COMBINED_THERMAL_OUTPUT_COLUMNS,
    THERMAL_OUTPUT_COLUMNS,
)

OUTPUT_PATH = THERMAL_PROCESSED_DIR / "thermal_power_generation_emissions.csv"
METADATA_PATH = THERMAL_PROCESSED_DIR / "thermal_power_generation_emissions_metadata.csv"
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
    "subsidiary_company": "KEPCO subsidiary company name",
    "energy_type": "Primary energy or fuel type (categorical)",
    "energy_generated_mwh": "Monthly electricity generation (MWh)",
    "energy_capacity_mw": "Installed generating capacity (MW)",
    "nox": "Monthly nitrogen oxides emissions (kg)",
    "sox": "Monthly sulfur oxides emissions (kg)",
    "dust_tsp": "Monthly total suspended particulate emissions (kg)",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Combine East-West, Western, and Southern monthly datasets and "
            "standardize pollutant mass to kilograms."
        )
    )
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--metadata-path", type=Path, default=METADATA_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    combined = combine_thermal_datasets(load_default_datasets())
    save_combined(combined, args.output_path)
    metadata = build_variable_metadata()
    save_variable_metadata(metadata, args.metadata_path)

    mass_rows = combined["pollutant_measurement_basis"].eq("mass").sum()
    print(f"Saved {len(combined)} rows to {args.output_path}")
    print(f"Saved {len(metadata)} variable labels to {args.metadata_path}")
    print(f"Mass rows standardized to kilograms: {mass_rows}")
