"""
Clean Korea South-East Power daily air-pollutant measurements.

This cleaner reads the public KOEN raw CSV scraped from data.go.kr/provider
pages and derives monthly pollutant mass from those scraped values. A separate
KOEN data-request workbook is used only as methodology evidence: it confirms
the concentration-to-mass chemistry but does not serve as pipeline input.

The scraped source reports daily average concentrations and flue-gas flow, not
published mass emissions. KOEN clarified in June 2026 that each daily value is
the average of 288 five-minute readings; daily mass is therefore approximated by
multiplying the concentration-and-flow formula by 288. KOEN also confirmed that
reported concentrations are already corrected to 6% standard oxygen and that
numeric unit identifiers combine A/B labels, such as Samcheonpo 3 = 3A + 3B.
Dust rows above 30 mg/Sm3 are excluded from dust mass because they behave like
invalid/non-operating measurements and otherwise triple KOEN's reported annual
dust mass.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import pandas as pd

from nzk_aphiam.data.clean.thermal.location_crosswalk import apply_location_crosswalk
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "southeast_power"
    / "southeast_power_daily_air_pollutant_emissions.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "southeast_power"
    / "southeast_power_monthly_derived_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea South-East Power"
SOURCE_COLUMNS = ["사업소", "호기", "일자", "SOX", "NOX", "먼지", "산소", "유량", "온도"]
FIVE_MINUTE_PERIODS_PER_DAY = 288
MOLAR_VOLUME_LITERS_PER_MOL = 22.4
SOX_MOLECULAR_WEIGHT_GRAMS = 64
NOX_MOLECULAR_WEIGHT_GRAMS = 46
DUST_VALID_CONCENTRATION_MAX_MG_SM3 = 30
DERIVATION_NOTE = (
    "Derived from scraped KOEN daily concentration and flow data using KOEN's "
    "confirmed approximation for daily averages of 288 five-minute readings; "
    "reported concentrations are already corrected to 6% standard O2. The KOEN "
    "workbook/clarification was used only to verify the formulas, not as cleaner "
    "input: gas kg = ppm * flow_sm3 * molecular_weight / (22.4 * 1,000,000) "
    "* 288; dust kg = mg_per_sm3 * flow_sm3 / 1,000,000 * 288, excluding dust "
    "concentration rows >30 mg/Sm3. Numeric unit rows combine A/B labels."
)
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


def sum_with_missing(values: pd.Series) -> float | pd.NA:
    """Sum a group while preserving missingness for all-missing groups."""
    return values.sum(min_count=1)


def join_unique_non_missing(values: pd.Series) -> str | pd.NA:
    """Join source labels while preserving first-seen order."""
    labels = [str(value) for value in pd.unique(values.dropna())]
    return "; ".join(labels) if labels else pd.NA


def build_daily_derived_mass(source: pd.DataFrame) -> pd.DataFrame:
    """Convert daily source measurements to inferred daily pollutant mass."""
    flow = pd.to_numeric(source["유량"], errors="coerce")
    sox_ppm = pd.to_numeric(source["SOX"], errors="coerce")
    nox_ppm = pd.to_numeric(source["NOX"], errors="coerce")
    dust_mg_sm3 = pd.to_numeric(source["먼지"], errors="coerce")

    # Use the scraped public export as the only pipeline input. The workbook
    # from KOEN is external evidence for these formulas and constants.
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(
                source["일자"].astype("string"),
                format="%Y%m%d",
                errors="raise",
            ),
            "plant_name": source["사업소"].map(PLANT_NAMES),
            "plant_number": source["호기"].map(extract_unit_number),
            # Gas conversion follows KOEN's confirmed chemistry, then scales
            # the daily-average five-minute value to a full day.
            "nox": (
                nox_ppm
                * flow
                * NOX_MOLECULAR_WEIGHT_GRAMS
                / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000)
                * FIVE_MINUTE_PERIODS_PER_DAY
            ),
            "sox": (
                sox_ppm
                * flow
                * SOX_MOLECULAR_WEIGHT_GRAMS
                / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000)
                * FIVE_MINUTE_PERIODS_PER_DAY
            ),
            # Dust uses the same inferred 5-minute basis, but we suppress
            # implausible high-concentration rows that align with invalid or
            # non-operating conditions in KOEN's public export.
            "dust_tsp": (
                dust_mg_sm3.where(dust_mg_sm3 <= DUST_VALID_CONCENTRATION_MAX_MG_SM3)
                * flow
                / 1_000_000
                * FIVE_MINUTE_PERIODS_PER_DAY
            ),
            "original_korean_plant_name": source["사업소"],
            "original_korean_unit_name": source["호기"],
        }
    )
    daily["plant_number"] = daily["plant_number"].astype("Int64")
    return daily


def aggregate_monthly_mass(daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate inferred daily mass to the shared monthly thermal schema."""
    source = daily.copy()
    source["date"] = source["date"].dt.to_period("M").dt.to_timestamp()

    group_columns = [
        "date",
        "plant_name",
        "plant_number",
        "original_korean_plant_name",
    ]
    monthly = (
        source.groupby(group_columns, dropna=False, as_index=False)
        .agg(
            {
                "nox": sum_with_missing,
                "sox": sum_with_missing,
                "dust_tsp": sum_with_missing,
                "original_korean_unit_name": join_unique_non_missing,
            }
        )
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


def clean_southeast_power(raw: pd.DataFrame) -> pd.DataFrame:
    """Return inferred monthly pollutant mass in the shared thermal schema."""
    validate_source_columns(raw)
    source = raw.copy()

    unknown_plants = sorted(set(source["사업소"].dropna()) - set(PLANT_NAMES))
    if unknown_plants:
        raise ValueError(f"Unknown South-East Power plant names: {unknown_plants}")

    daily = build_daily_derived_mass(source)
    cleaned = aggregate_monthly_mass(daily)

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

    return apply_location_crosswalk(cleaned)


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
    print(f"Monthly coverage: {cleaned['date'].min():%Y-%m} to {cleaned['date'].max():%Y-%m}")
    print("Derived SOx/NOx/dust mass using KOEN's confirmed 5-minute average basis.")


if __name__ == "__main__":
    main()
