"""
Clean Korea South-East Power daily air-pollutant measurements.

The source reports daily values for SOX, NOX, dust, oxygen, flue-gas flow, and
temperature, but its export does not state the pollutant or flow units. The
cleaner therefore preserves the reported values without converting them or
mislabeling them as emissions mass.
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
    / "power_generation"
    / "thermal"
    / "raw"
    / "southeast_power"
    / "southeast_power_daily_air_pollutant_emissions.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "power_generation"
    / "thermal"
    / "interim"
    / "southeast_power"
    / "southeast_power_daily_air_pollutant_measurements.csv"
)

SUBSIDIARY_COMPANY = "Korea South-East Power"
SOURCE_COLUMNS = ["사업소", "호기", "일자", "SOX", "NOX", "먼지", "산소", "유량", "온도"]
PLANT_NAMES = {
    "분당": "Bundang",
    "삼천포": "Samcheonpo",
    "여수": "Yeosu",
    "영동": "Yeongdong",
    "영흥": "Yeongheung",
}


def validate_source_columns(df: pd.DataFrame) -> None:
    """Fail clearly if the provider changes the export schema."""
    actual = list(df.columns)
    if actual != SOURCE_COLUMNS:
        raise ValueError(
            "Unexpected South-East Power source columns. "
            f"Expected {SOURCE_COLUMNS!r}, received {actual!r}."
        )


def extract_unit_number(value: object) -> int | None:
    """Extract a numeric unit while retaining the full source label elsewhere."""
    if pd.isna(value):
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def clean_southeast_power(raw: pd.DataFrame) -> pd.DataFrame:
    """Return every source row in the shared thermal schema."""
    validate_source_columns(raw)
    source = raw.copy()

    unknown_plants = sorted(set(source["사업소"].dropna()) - set(PLANT_NAMES))
    if unknown_plants:
        raise ValueError(f"Unknown South-East Power plant names: {unknown_plants}")

    cleaned = pd.DataFrame(
        {
            "date": pd.to_datetime(
                source["일자"].astype("string"),
                format="%Y%m%d",
                errors="raise",
            ),
            "plant_name": source["사업소"].map(PLANT_NAMES),
            "plant_number": source["호기"].map(extract_unit_number),
            "plant_opening_date": pd.Series(pd.NaT, index=source.index),
            "plant_closing_date": pd.Series(pd.NaT, index=source.index),
            "plant_latitude": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "energy_type": pd.Series(pd.NA, index=source.index, dtype="string"),
            "energy_generated_mwh": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "energy_capacity_mw": pd.Series(pd.NA, index=source.index, dtype="Float64"),
            "nox": pd.to_numeric(source["NOX"], errors="coerce"),
            "sox": pd.to_numeric(source["SOX"], errors="coerce"),
            "dust_tsp": pd.to_numeric(source["먼지"], errors="coerce"),
            "pollutant_measurement_basis": "concentration",
            "nox_unit": "not_reported",
            "sox_unit": "not_reported",
            "dust_tsp_unit": "not_reported",
            "emissions_mass_unit": pd.Series(pd.NA, index=source.index, dtype="string"),
            "oxygen": pd.to_numeric(source["산소"], errors="coerce"),
            "oxygen_unit": "not_reported",
            "flue_gas_flow": pd.to_numeric(source["유량"], errors="coerce"),
            "flue_gas_flow_unit": "not_reported",
            "temperature_celsius": pd.to_numeric(source["온도"], errors="coerce"),
            "original_korean_plant_name": source["사업소"],
            "original_korean_unit_name": source["호기"],
            "original_korean_note": pd.Series(pd.NA, index=source.index, dtype="string"),
        },
        columns=THERMAL_OUTPUT_COLUMNS,
    )

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
    raw = pd.read_csv(input_path, encoding="utf-8-sig", dtype={"호기": "string"})
    return clean_southeast_power(raw)


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
    print(f"Daily coverage: {cleaned['date'].min():%Y-%m-%d} to {cleaned['date'].max():%Y-%m-%d}")
    print("Pollutant and flue-gas-flow units are not reported by the source export.")


if __name__ == "__main__":
    main()
