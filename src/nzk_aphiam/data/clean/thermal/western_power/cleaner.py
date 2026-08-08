"""
Clean Korea Western Power monthly generation and air-pollutant data.

The source reports pollutant mass in metric tonnes. It does not contain
temperature, so ``temperature_celsius`` is retained as a nullable column for
compatibility with the shared thermal output schema.

The source data also does not contain fuel type. ``fuel_type`` is enriched
from Korea Western Power's official plant and operating-history pages. The
mapping evidence is recorded in:

    docs/references/thermal/western_power_fuel_type_mapping.csv

Run from the project root:

    python -m nzk_aphiam.data.clean.thermal.western_power
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import pandas as pd

from nzk_aphiam.config.paths import PROJECT_ROOT
from nzk_aphiam.data.clean.thermal.location_crosswalk import apply_location_crosswalk
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.technology import apply_technology_mapping

DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "kepco_subsidiaries"
    / "western_power"
    / "western_power_air_pollutants_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "kepco_subsidiaries"
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

REPORTING_ID_PREFIX = "western_power"


def make_reporting_unit_id(plant_name: str, unit_name: str) -> str:
    """Return a stable ID that preserves the source reporting boundary."""
    return f"{REPORTING_ID_PREFIX}:{PLANT_NAMES[plant_name]}:{unit_name}"


def classify_observation_level(plant_name: str, unit_name: str) -> str:
    """Classify what the source row represents without inventing unit detail."""
    if plant_name == "태안" and re.fullmatch(r"\d+호기", unit_name):
        return "generating_unit"
    if plant_name == "평택" and unit_name.startswith("기력"):
        return "generating_unit"
    if "복합" in unit_name or unit_name == "IGCC":
        return "generation_block"
    if plant_name == "김포" and unit_name == "열병합":
        return "plant"
    return "unresolved"


def pollutant_data_pattern(source: pd.DataFrame) -> pd.Series:
    """Describe reported pollutant fields; source blanks remain missing."""
    reported = source[["NOx", "SOx", "먼지(TSP)"]].notna()
    labels = {
        (True, True, True): "nox_sox_dust",
        (True, True, False): "nox_sox",
        (True, False, True): "nox_dust",
        (False, True, True): "sox_dust",
        (True, False, False): "nox_only",
        (False, True, False): "sox_only",
        (False, False, True): "dust_only",
        (False, False, False): "none",
    }
    return reported.apply(lambda row: labels[tuple(row)], axis=1).astype("string")


def derive_reporting_windows(
    source: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Derive observed starts and explicit retirements without calling them openings."""
    identity = source["발전소"].astype(str) + "\x1f" + source["호기"].astype(str)
    activity = source[["발전량(MWh)", "NOx", "SOx", "먼지(TSP)"]].notna().any(axis=1)
    start = source["_date"].where(activity).groupby(identity).transform("min")

    retirement_text = (
        source["비고"].fillna("").str.extract(r"(\d{4}-\d{2}-\d{2}).*폐지", expand=False)
    )
    retirement = (
        pd.to_datetime(retirement_text, errors="coerce").groupby(identity).transform("min")
    )

    basis = pd.Series("not_established", index=source.index, dtype="string")
    basis.loc[start.notna()] = "first_reported_activity"
    basis.loc[start.notna() & retirement.notna()] = (
        "first_reported_activity_and_source_retirement_note"
    )
    basis.loc[start.isna() & retirement.notna()] = "source_retirement_note"
    return start, retirement, basis


def assign_row_status(source: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Assign conservative row statuses from values, notes, and observed windows."""
    measure_columns = ["발전량(MWh)", "NOx", "SOx", "먼지(TSP)"]
    activity = source[measure_columns].notna().any(axis=1)
    generation = source["발전량(MWh)"].notna()
    pollutants = source[["NOx", "SOx", "먼지(TSP)"]].notna().any(axis=1)
    explicit_retirement = source["비고"].fillna("").str.contains("폐지", regex=False)

    identity = source["발전소"].astype(str) + "\x1f" + source["호기"].astype(str)
    activity_dates = source["_date"].where(activity)
    first_activity = activity_dates.groupby(identity).transform("min")
    before_first_activity = first_activity.notna() & source["_date"].lt(first_activity)

    status = pd.Series("unknown_status", index=source.index, dtype="string")
    basis = pd.Series("no_generation_or_pollutant_value", index=source.index, dtype="string")

    complete_pair = generation & pollutants
    status.loc[complete_pair] = "active_reported"
    basis.loc[complete_pair] = "generation_and_at_least_one_pollutant_reported"

    partial = activity & ~complete_pair
    status.loc[partial] = "active_partial"
    basis.loc[partial & generation] = "generation_reported_without_pollutants"
    basis.loc[partial & pollutants] = "pollutants_reported_without_generation"

    status.loc[before_first_activity] = "inactive_placeholder"
    basis.loc[before_first_activity] = "before_first_reported_activity"
    status.loc[explicit_retirement] = "inactive_placeholder"
    basis.loc[explicit_retirement] = "source_note_reports_retirement"
    return status, basis


def classify_fuel_type(
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
    source["_date"] = date

    numeric_columns = ["발전량(MWh)", "발전용량(MW)", "NOx", "SOx", "먼지(TSP)"]
    for column in numeric_columns:
        source[column] = pd.to_numeric(source[column], errors="coerce")

    reporting_start, reporting_end, reporting_window_basis = derive_reporting_windows(source)
    row_status, row_status_basis = assign_row_status(source)

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
            "fuel_type": [
                classify_fuel_type(plant, unit, month)
                for plant, unit, month in zip(
                    source["발전소"],
                    source["호기"],
                    date,
                    strict=True,
                )
            ],
            "energy_generated_mwh": source["발전량(MWh)"],
            "energy_capacity_mw": source["발전용량(MW)"],
            "reporting_unit_id": [
                make_reporting_unit_id(plant, unit)
                for plant, unit in zip(source["발전소"], source["호기"], strict=True)
            ],
            "reporting_start_date": reporting_start,
            "reporting_end_date": reporting_end,
            "reporting_window_basis": reporting_window_basis,
            "observation_level": [
                classify_observation_level(plant, unit)
                for plant, unit in zip(source["발전소"], source["호기"], strict=True)
            ],
            "generation_source": "western_monthly_combined_source",
            "generation_coverage_status": source["발전량(MWh)"]
            .notna()
            .map({True: "reported", False: "missing"}),
            "row_status": row_status,
            "row_status_basis": row_status_basis,
            "nox": source["NOx"],
            "sox": source["SOx"],
            "dust_tsp": source["먼지(TSP)"],
            "pollutant_data_pattern": pollutant_data_pattern(source),
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
        "fuel_type",
        "reporting_unit_id",
        "reporting_window_basis",
        "observation_level",
        "generation_source",
        "generation_coverage_status",
        "row_status",
        "row_status_basis",
        "pollutant_data_pattern",
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

    return apply_technology_mapping(apply_location_crosswalk(cleaned))


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
