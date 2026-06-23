"""
Clean Korea Western Power monthly generation and air-pollutant data.

The source reports pollutant mass in metric tonnes. It does not contain
temperature, so ``temperature_celsius`` is retained as a nullable column for
compatibility with the shared thermal output schema.

The source data also does not contain fuel type. ``energy_type`` is enriched
from Korea Western Power's official plant and operating-history pages. The
mapping evidence is recorded in:

    docs/references/thermal/western_power_energy_type_mapping.csv

Run from the project root:

    python -m nzk_aphiam.data.clean.thermal.western_power
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
    / "western_power"
    / "western_power_air_pollutants_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "western_power"
    / "western_power_monthly_generation_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea Western Power"

SOURCE_COLUMNS = [
    "NOx",
    "SOx",
    "날짜",
    "먼지(TSP)",
    "발전량(MWh)",
    "발전소",
    "발전용량(MW)",
    "비고",
    "호기",
]

PLANT_NAMES = {
    "태안": "Taean",
    "평택": "Pyeongtaek",
    "서인천": "Seoincheon",
    "군산": "Gunsan",
    "김포": "Gimpo",
}

PYEONGTAEK_FULL_LNG_START_MONTH = pd.Timestamp("2020-03-01")


def classify_energy_type(
    plant_name: str,
    unit_name: str,
    month: pd.Timestamp,
) -> str:
    """Map Western Power plants, units, and operating month to a fuel label."""
    if plant_name == "태안":
        return "coal"
    if plant_name == "평택" and unit_name.startswith("기력"):
        if month < PYEONGTAEK_FULL_LNG_START_MONTH:
            return "oil_and_natural_gas"
        return "natural_gas"
    if plant_name in {"평택", "서인천", "군산", "김포"}:
        return "natural_gas"

    raise ValueError(f"Unknown Western Power plant/unit: {plant_name!r} / {unit_name!r}")


def extract_plant_number(unit_name: str) -> int | None:
    """Extract the numeric unit identifier when the source provides one."""
    match = re.search(r"\d+", unit_name)
    if match is None:
        return None
    return int(match.group())


def validate_source_columns(df: pd.DataFrame) -> None:
    """Fail clearly if the upstream source schema changes."""
    actual = list(df.columns)
    if actual != SOURCE_COLUMNS:
        raise ValueError(
            "Unexpected Western Power source columns. "
            f"Expected {SOURCE_COLUMNS!r}, received {actual!r}."
        )


def clean_western_power(raw: pd.DataFrame) -> pd.DataFrame:
    """Return all Western Power source rows in the shared monthly schema."""
    validate_source_columns(raw)

    source = raw.copy()
    date = pd.to_datetime(source["날짜"], format="%Y-%m", errors="raise")

    unknown_plants = sorted(set(source["발전소"].dropna()) - set(PLANT_NAMES))
    if unknown_plants:
        raise ValueError(f"Unknown Western Power plant names: {unknown_plants}")

    cleaned = pd.DataFrame(
        {
            "date": date,
            "plant_name": source["발전소"].map(PLANT_NAMES),
            "plant_number": source["호기"].map(extract_plant_number),
            "plant_opening_date": pd.Series(pd.NaT, index=source.index),
            "plant_closing_date": pd.Series(pd.NaT, index=source.index),
            "plant_latitude": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "energy_type": [
                classify_energy_type(plant, unit, month)
                for plant, unit, month in zip(
                    source["발전소"],
                    source["호기"],
                    date,
                    strict=True,
                )
            ],
            "energy_generated_mwh": pd.to_numeric(source["발전량(MWh)"], errors="coerce"),
            "energy_capacity_mw": pd.to_numeric(source["발전용량(MW)"], errors="coerce"),
            "nox": pd.to_numeric(source["NOx"], errors="coerce"),
            "sox": pd.to_numeric(source["SOx"], errors="coerce"),
            "dust_tsp": pd.to_numeric(source["먼지(TSP)"], errors="coerce"),
            "pollutant_measurement_basis": "mass",
            "nox_unit": "metric_tonnes",
            "sox_unit": "metric_tonnes",
            "dust_tsp_unit": "metric_tonnes",
            "emissions_mass_unit": "metric_tonnes",
            "temperature_celsius": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "original_korean_plant_name": source["발전소"],
            "original_korean_unit_name": source["호기"],
            "original_korean_note": source["비고"],
        },
        columns=THERMAL_OUTPUT_COLUMNS,
    )

    cleaned["plant_number"] = cleaned["plant_number"].astype("Int64")
    for column in [
        "energy_generated_mwh",
        "energy_capacity_mw",
        "nox",
        "sox",
        "dust_tsp",
        "temperature_celsius",
        "plant_latitude",
        "plant_longitude",
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
        "original_korean_plant_name",
        "original_korean_unit_name",
        "original_korean_note",
    ]:
        cleaned[column] = cleaned[column].astype("string")

    return cleaned


def load_and_clean(input_path: Path) -> pd.DataFrame:
    """Read the preserved raw CSV and return its cleaned representation."""
    raw = pd.read_csv(input_path, encoding="utf-8-sig")
    return clean_western_power(raw)


def save_cleaned(df: pd.DataFrame, output_path: Path) -> None:
    """Write the cleaned CSV without modifying the source data."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")


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


if __name__ == "__main__":
    main()
