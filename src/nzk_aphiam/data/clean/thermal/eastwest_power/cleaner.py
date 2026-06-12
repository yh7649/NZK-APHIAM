"""
Clean Korea East-West Power monthly generation and air-pollutant data.

The source reports pollutant mass in metric tonnes. Fuel type is enriched from
official East-West Power reports documented in:

    references/thermal/eastwest_power_energy_type_mapping.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "power_generation"
    / "thermal"
    / "raw"
    / "eastwest_power"
    / "eastwest_power_air_pollutants_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "power_generation"
    / "thermal"
    / "interim"
    / "eastwest_power"
    / "eastwest_power_monthly_generation_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea East-West Power"
SOURCE_COLUMNS = [
    "날짜",
    "먼지(TSP)",
    "발전량(MWh)",
    "발전소명",
    "발전용량(MW)",
    "질소산화물(NOx)",
    "호기",
    "황산화물(SOx)",
]
PLANT_NAMES = {
    "한국동서발전㈜ 당진발전본부": "Dangjin",
    "한국동서발전㈜동해바이오발전본부": "Donghae",
    "한국동서발전㈜동해발전본부": "Donghae",
    "한국동서발전㈜신호남건설추진본부": "Honam",
    "한국동서발전㈜울산발전본부": "Ulsan",
    "한국동서발전㈜일산발전본부": "Ilsan",
}


def classify_energy_type(plant_name: str, unit_number: int) -> str:
    """Map source plant and unit identifiers to documented primary fuels."""
    if plant_name in {
        "한국동서발전㈜ 당진발전본부",
        "한국동서발전㈜동해바이오발전본부",
        "한국동서발전㈜동해발전본부",
        "한국동서발전㈜신호남건설추진본부",
    }:
        return "coal"
    if plant_name == "한국동서발전㈜일산발전본부":
        return "natural_gas"
    if plant_name == "한국동서발전㈜울산발전본부":
        return "oil" if unit_number <= 6 else "natural_gas"

    raise ValueError(f"Unknown East-West Power plant/unit: {plant_name!r} / {unit_number!r}")


def validate_source_columns(df: pd.DataFrame) -> None:
    """Fail clearly if the upstream source schema changes."""
    actual = list(df.columns)
    if actual != SOURCE_COLUMNS:
        raise ValueError(
            "Unexpected East-West Power source columns. "
            f"Expected {SOURCE_COLUMNS!r}, received {actual!r}."
        )


def clean_eastwest_power(raw: pd.DataFrame) -> pd.DataFrame:
    """Return every East-West source row in the shared monthly schema."""
    validate_source_columns(raw)
    source = raw.copy()
    date = pd.to_datetime(source["날짜"], errors="raise").dt.to_period("M").dt.to_timestamp()
    unit_number = pd.to_numeric(source["호기"], errors="raise").astype("Int64")

    unknown_plants = sorted(set(source["발전소명"].dropna()) - set(PLANT_NAMES))
    if unknown_plants:
        raise ValueError(f"Unknown East-West Power plant names: {unknown_plants}")

    cleaned = pd.DataFrame(
        {
            "date": date,
            "plant_name": source["발전소명"].map(PLANT_NAMES),
            "plant_number": unit_number,
            "plant_opening_date": pd.Series(pd.NaT, index=source.index),
            "plant_closing_date": pd.Series(pd.NaT, index=source.index),
            "plant_latitude": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "energy_type": [
                classify_energy_type(plant, int(unit))
                for plant, unit in zip(source["발전소명"], unit_number, strict=True)
            ],
            "energy_generated_mwh": pd.to_numeric(source["발전량(MWh)"], errors="coerce"),
            "energy_capacity_mw": pd.to_numeric(source["발전용량(MW)"], errors="coerce"),
            "nox": pd.to_numeric(source["질소산화물(NOx)"], errors="coerce"),
            "sox": pd.to_numeric(source["황산화물(SOx)"], errors="coerce"),
            "dust_tsp": pd.to_numeric(source["먼지(TSP)"], errors="coerce"),
            "pollutant_measurement_basis": "mass",
            "nox_unit": "metric_tonnes",
            "sox_unit": "metric_tonnes",
            "dust_tsp_unit": "metric_tonnes",
            "emissions_mass_unit": "metric_tonnes",
            "temperature_celsius": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "original_korean_plant_name": source["발전소명"],
            "original_korean_unit_name": source["호기"].astype("string"),
            "original_korean_note": pd.Series(pd.NA, index=source.index, dtype="string"),
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
    raw = pd.read_csv(input_path, encoding="utf-8-sig")
    return clean_eastwest_power(raw)


def save_cleaned(df: pd.DataFrame, output_path: Path) -> None:
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
