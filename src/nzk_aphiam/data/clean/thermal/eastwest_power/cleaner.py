"""
Clean Korea East-West Power monthly generation and air-pollutant data.

The source reports pollutant mass in metric tonnes. Fuel type is enriched from
official East-West Power reports documented in:

    docs/references/thermal/eastwest_power_fuel_type_mapping.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nzk_aphiam.data.clean.thermal.location_crosswalk import apply_location_crosswalk
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.technology import apply_technology_mapping

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "kepco_subsidiaries"
    / "eastwest_power"
    / "eastwest_power_air_pollutants_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "kepco_subsidiaries"
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

REPORTING_ID_PREFIX = "eastwest_power"
GENERATION_SOURCE = "eastwest_monthly_combined_source"
MEASURE_COLUMNS = ["발전량(MWh)", "질소산화물(NOx)", "황산화물(SOx)", "먼지(TSP)"]
POLLUTANT_COLUMNS = ["질소산화물(NOx)", "황산화물(SOx)", "먼지(TSP)"]


def make_reporting_unit_id(plant_name: str, unit_number: int) -> str:
    """Return a stable ID that preserves the source reporting boundary."""
    return f"{REPORTING_ID_PREFIX}:{PLANT_NAMES[plant_name]}:{unit_number}"


def pollutant_data_pattern(source: pd.DataFrame) -> pd.Series:
    """Describe reported pollutant fields; source blanks remain missing."""
    reported = source[POLLUTANT_COLUMNS].notna()
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


def derive_reporting_windows(source: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Derive the first reported activity month per generating unit.

    The source has no retirement-note column, so the reporting window can only
    establish a start, never an explicit end.
    """
    identity = source["발전소명"].astype(str) + "\x1f" + source["호기"].astype(str)
    activity = source[MEASURE_COLUMNS].notna().any(axis=1)
    start = source["_date"].where(activity).groupby(identity).transform("min")

    basis = pd.Series("not_established", index=source.index, dtype="string")
    basis.loc[start.notna()] = "first_reported_activity"
    return start, basis


def assign_row_status(source: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Assign conservative row statuses from observed activity, without imputation."""
    activity = source[MEASURE_COLUMNS].notna().any(axis=1)
    generation = source["발전량(MWh)"].notna()
    pollutants = source[POLLUTANT_COLUMNS].notna().any(axis=1)

    identity = source["발전소명"].astype(str) + "\x1f" + source["호기"].astype(str)
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
    return status, basis


def classify_fuel_type(plant_name: str, unit_number: int) -> str:
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
    source["_date"] = date
    unit_number = pd.to_numeric(source["호기"], errors="raise").astype("Int64")

    for column in MEASURE_COLUMNS + ["발전용량(MW)"]:
        source[column] = pd.to_numeric(source[column], errors="coerce")

    unknown_plants = sorted(set(source["발전소명"].dropna()) - set(PLANT_NAMES))
    if unknown_plants:
        raise ValueError(f"Unknown East-West Power plant names: {unknown_plants}")

    reporting_start, reporting_window_basis = derive_reporting_windows(source)
    row_status, row_status_basis = assign_row_status(source)

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
            "fuel_type": [
                classify_fuel_type(plant, int(unit))
                for plant, unit in zip(source["발전소명"], unit_number, strict=True)
            ],
            "energy_generated_mwh": source["발전량(MWh)"],
            "energy_capacity_mw": source["발전용량(MW)"],
            "reporting_unit_id": [
                make_reporting_unit_id(plant, unit)
                for plant, unit in zip(source["발전소명"], unit_number, strict=True)
            ],
            "reporting_start_date": reporting_start,
            "reporting_end_date": pd.Series(pd.NaT, index=source.index),
            "reporting_window_basis": reporting_window_basis,
            "observation_level": "generating_unit",
            "generation_source": GENERATION_SOURCE,
            "generation_coverage_status": source["발전량(MWh)"]
            .notna()
            .map({True: "reported", False: "missing"}),
            "row_status": row_status,
            "row_status_basis": row_status_basis,
            "nox": source["질소산화물(NOx)"],
            "sox": source["황산화물(SOx)"],
            "dust_tsp": source["먼지(TSP)"],
            "pollutant_data_pattern": pollutant_data_pattern(source),
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
