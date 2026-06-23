"""
Clean Korea Midland Power facility air-status data.

The usable KOMIPO facility-status APIs report time-level pollutant
concentrations and stack flue-gas flow for Seocheon, Sejong, Jeju, and Incheon.
This cleaner derives row-level pollutant mass from concentration and flow, then
sums to monthly facility/unit rows in the shared thermal schema. Boryeong,
Seoul, and Shin-Boryeong facility-status APIs expose TMS instrument diagnostic
fields rather than stack pollutant/flow fields and are retained only as raw
source data by the scraper.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import pandas as pd

from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "midland_power"
    / "facilities"
    / "midland_power_facility_air_status.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "midland_power"
    / "midland_power_monthly_derived_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea Midland Power"
USABLE_SOURCE_COLUMNS = [
    "source_facility",
    "source_korean_facility_name",
    "source_english_facility_name",
    "usable_for_mass_derivation",
    "발전소 호기",
    "처리일",
    "황산화물",
    "질소 산화물",
    "먼지",
    "산소",
    "유량",
    "온도",
]
MOLAR_VOLUME_LITERS_PER_MOL = 22.4
SOX_MOLECULAR_WEIGHT_GRAMS = 64
NOX_MOLECULAR_WEIGHT_GRAMS = 46
DERIVATION_NOTE = (
    "Derived from KOMIPO facility air-status rows with pollutant concentrations "
    "and stack flow. Row-level approximation: gas kg = ppm * flow_sm3 * "
    "molecular_weight / (22.4 * 1,000,000); dust kg = mg_per_sm3 * flow_sm3 / "
    "1,000,000. Boryeong, Seoul, and Shin-Boryeong diagnostic-status rows are "
    "excluded because they do not report stack pollutant concentrations and flow."
)


def validate_source_columns(raw: pd.DataFrame) -> None:
    """Fail if the merged raw file cannot support the derivation."""
    missing = [column for column in USABLE_SOURCE_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"Midland facility raw data is missing columns: {missing}")


def is_usable(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def extract_unit_number(value: object) -> int | None:
    if pd.isna(value):
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def sum_with_missing(values: pd.Series) -> float | pd.NA:
    return values.sum(min_count=1)


def parse_datetime(values: pd.Series) -> pd.Series:
    """Parse provider timestamps without assuming one exact text format."""
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.isna().any():
        compact = pd.to_datetime(values.astype("string"), format="%Y%m%d%H%M", errors="coerce")
        parsed = parsed.fillna(compact)
    if parsed.isna().any():
        bad = values[parsed.isna()].dropna().head(5).tolist()
        raise ValueError(f"Could not parse Midland facility 처리일 values: {bad}")
    return parsed


def build_row_derived_mass(source: pd.DataFrame) -> pd.DataFrame:
    """Convert usable facility rows to row-level pollutant mass."""
    source = source[source["usable_for_mass_derivation"].map(is_usable)].copy()
    source = source.dropna(subset=["발전소 호기", "처리일"], how="any")

    flow = pd.to_numeric(source["유량"], errors="coerce")
    sox_ppm = pd.to_numeric(source["황산화물"], errors="coerce")
    nox_ppm = pd.to_numeric(source["질소 산화물"], errors="coerce")
    dust_mg_sm3 = pd.to_numeric(source["먼지"], errors="coerce")

    rows = pd.DataFrame(
        {
            "date": parse_datetime(source["처리일"]),
            "plant_name": source["source_english_facility_name"].astype("string"),
            "plant_number": source["발전소 호기"].map(extract_unit_number),
            "nox": (
                nox_ppm
                * flow
                * NOX_MOLECULAR_WEIGHT_GRAMS
                / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000)
            ),
            "sox": (
                sox_ppm
                * flow
                * SOX_MOLECULAR_WEIGHT_GRAMS
                / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000)
            ),
            "dust_tsp": dust_mg_sm3 * flow / 1_000_000,
            "original_korean_plant_name": source["source_korean_facility_name"],
            "original_korean_unit_name": source["발전소 호기"],
        }
    )
    rows["plant_number"] = rows["plant_number"].astype("Int64")
    return rows


def aggregate_monthly_mass(rows: pd.DataFrame) -> pd.DataFrame:
    """Aggregate row-level mass to monthly rows in the shared thermal schema."""
    source = rows.copy()
    source["date"] = source["date"].dt.to_period("M").dt.to_timestamp()

    group_columns = [
        "date",
        "plant_name",
        "plant_number",
        "original_korean_plant_name",
        "original_korean_unit_name",
    ]
    monthly = (
        source.groupby(group_columns, dropna=False, as_index=False)
        .agg({"nox": sum_with_missing, "sox": sum_with_missing, "dust_tsp": sum_with_missing})
        .sort_values(["date", "plant_name", "original_korean_unit_name"], ignore_index=True)
    )

    cleaned = pd.DataFrame(
        {
            "date": monthly["date"],
            "plant_name": monthly["plant_name"],
            "plant_number": monthly["plant_number"],
            "plant_opening_date": pd.Series(pd.NaT, index=monthly.index),
            "plant_closing_date": pd.Series(pd.NaT, index=monthly.index),
            "plant_latitude": pd.Series(pd.NA, index=monthly.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=monthly.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "energy_type": pd.Series(pd.NA, index=monthly.index, dtype="string"),
            "energy_generated_mwh": pd.Series(pd.NA, index=monthly.index, dtype="Float64"),
            "energy_capacity_mw": pd.Series(pd.NA, index=monthly.index, dtype="Float64"),
            "nox": monthly["nox"],
            "sox": monthly["sox"],
            "dust_tsp": monthly["dust_tsp"],
            "pollutant_measurement_basis": "mass",
            "nox_unit": "kilograms",
            "sox_unit": "kilograms",
            "dust_tsp_unit": "kilograms",
            "emissions_mass_unit": "kilograms",
            "oxygen": pd.Series(pd.NA, index=monthly.index, dtype="Float64"),
            "oxygen_unit": pd.Series(pd.NA, index=monthly.index, dtype="string"),
            "flue_gas_flow": pd.Series(pd.NA, index=monthly.index, dtype="Float64"),
            "flue_gas_flow_unit": pd.Series(pd.NA, index=monthly.index, dtype="string"),
            "temperature_celsius": pd.Series(pd.NA, index=monthly.index, dtype="Float64"),
            "original_korean_plant_name": monthly["original_korean_plant_name"],
            "original_korean_unit_name": monthly["original_korean_unit_name"],
            "original_korean_note": DERIVATION_NOTE,
        },
        columns=THERMAL_OUTPUT_COLUMNS,
    )
    return cleaned


def clean_midland_power(raw: pd.DataFrame) -> pd.DataFrame:
    """Return inferred monthly pollutant mass in the shared thermal schema."""
    validate_source_columns(raw)
    rows = build_row_derived_mass(raw)
    cleaned = aggregate_monthly_mass(rows)

    cleaned["plant_number"] = cleaned["plant_number"].astype("Int64")
    for column in [
        "plant_latitude",
        "plant_longitude",
        "energy_generated_mwh",
        "energy_capacity_mw",
        "nox",
        "sox",
        "dust_tsp",
        "oxygen",
        "flue_gas_flow",
        "temperature_celsius",
    ]:
        cleaned[column] = cleaned[column].astype("Float64")

    for column in [
        "plant_name",
        "subsidiary_company",
        "energy_type",
        "pollutant_measurement_basis",
        "nox_unit",
        "sox_unit",
        "dust_tsp_unit",
        "emissions_mass_unit",
        "oxygen_unit",
        "flue_gas_flow_unit",
        "original_korean_plant_name",
        "original_korean_unit_name",
        "original_korean_note",
    ]:
        cleaned[column] = cleaned[column].astype("string")

    return cleaned


def load_and_clean(input_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(input_path, low_memory=False)
    return clean_midland_power(raw)


def save_cleaned(data: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(output_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cleaned = load_and_clean(args.input_path)
    save_cleaned(cleaned, args.output_path)
    print(f"Saved {len(cleaned)} cleaned rows to {args.output_path}")
    print(f"Monthly coverage: {cleaned['date'].min():%Y-%m} to {cleaned['date'].max():%Y-%m}")
    print("Derived SOx/NOx/dust mass from Midland facility concentration and flow rows.")


if __name__ == "__main__":
    main()
