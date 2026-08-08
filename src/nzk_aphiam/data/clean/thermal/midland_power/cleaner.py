"""Join KOMIPO's directly reported monthly pollutant mass to generation."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nzk_aphiam.config.paths import DATA_DIR, THERMAL_INTERIM_DIR
from nzk_aphiam.data.clean.thermal.location_crosswalk import apply_location_crosswalk
from nzk_aphiam.data.clean.thermal.midland_power.reported_mass_workbook import (
    REPORTED_MASS_COLUMNS,
    parse_reported_mass_workbook,
    verify_workbook_sha256,
)
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.technology import apply_technology_mapping

DEFAULT_REPORTED_MASS_INPUT_PATH = (
    DATA_DIR
    / "raw"
    / "kepco_subsidiaries"
    / "midland_power"
    / "provider_responses"
    / "대기오염물질 배출량(24-25년)_kg자료.xlsx"
)
DEFAULT_GENERATION_INPUT_PATH = (
    DATA_DIR
    / "raw"
    / "kepco_subsidiaries"
    / "midland_power"
    / "generation"
    / "midland_power_monthly_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    THERMAL_INTERIM_DIR
    / "kepco_subsidiaries"
    / "midland_power"
    / "midland_power_monthly_generation_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea Midland Power"
GENERATION_SOURCE = "midland_monthly_generation_api"
REPORTING_ID_PREFIX = "midland_power"
GENERATION_SOURCE_COLUMNS = [
    "orgnm",
    "ym",
    "hokinm",
    "capacity",
    "qvodgen",
    "tper",
    "uper",
    "gennm",
]
BOUNDARY_METADATA = {
    "보령기력": {
        "plant_name": "Boryeong",
        "reporting_label": "Boryeong Steam",
        "fuel_type": "coal",
    },
    "보령복합": {
        "plant_name": "Boryeong",
        "reporting_label": "Boryeong Combined",
        "fuel_type": "natural_gas",
    },
    "신보령기력": {
        "plant_name": "Shin-Boryeong",
        "reporting_label": "Shin-Boryeong Steam",
        "fuel_type": "coal",
    },
    "신서천화력": {
        "plant_name": "Seocheon",
        "reporting_label": "Shin-Seocheon Steam",
        "fuel_type": "coal",
    },
    "인천복합": {
        "plant_name": "Incheon",
        "reporting_label": "Incheon Combined",
        "fuel_type": "natural_gas",
    },
    "서울복합": {
        "plant_name": "Seoul",
        "reporting_label": "Seoul Combined",
        "fuel_type": "natural_gas",
    },
    "세종천연가스": {
        "plant_name": "Sejong",
        "reporting_label": "Sejong Combined",
        "fuel_type": "natural_gas",
    },
    "제주기력": {
        "plant_name": "Jeju",
        "reporting_label": "Jeju Steam",
        "fuel_type": "oil",
    },
    "제주내연": {
        "plant_name": "Jeju",
        "reporting_label": "Jeju Internal Combustion",
        "fuel_type": "oil",
    },
    "제주복합": {
        "plant_name": "Jeju",
        "reporting_label": "Jeju Combined",
        "fuel_type": "natural_gas",
    },
}
REPORTED_MASS_NOTE = (
    "Monthly pollutant mass reported directly by Korea Midland Power in the "
    "provider-response workbook 대기오염물질 배출량(24-25년)_kg자료.xlsx. "
    "Source stack/outlet values are summed to the matching generation subtotal; "
    "blank pollutant cells remain missing and reported zeros remain zero. No "
    "concentration-to-mass calculation is applied."
)


def _join_unique(values: pd.Series) -> str | pd.NA:
    labels = [str(value) for value in pd.unique(values.dropna())]
    return "; ".join(labels) if labels else pd.NA


def validate_inputs(reported_mass: pd.DataFrame, generation_raw: pd.DataFrame) -> None:
    missing_reported = [column for column in REPORTED_MASS_COLUMNS if column not in reported_mass]
    missing_generation = [
        column for column in GENERATION_SOURCE_COLUMNS if column not in generation_raw
    ]
    if missing_reported:
        raise ValueError(f"Midland reported-mass data is missing columns: {missing_reported}")
    if missing_generation:
        raise ValueError(f"Midland generation data is missing columns: {missing_generation}")
    unknown_boundaries = sorted(
        set(reported_mass["generation_orgnm"].dropna()) - set(BOUNDARY_METADATA)
    )
    if unknown_boundaries:
        raise ValueError(f"Unknown Midland reported-mass boundaries: {unknown_boundaries}")


def build_monthly_emissions(reported_mass: pd.DataFrame) -> pd.DataFrame:
    """Aggregate provider-reported stack mass to generation reporting boundaries."""
    source = reported_mass.copy()
    source["date"] = pd.to_datetime(source["date"], errors="raise")
    if not source["date"].dt.is_month_start.all():
        raise ValueError("Midland reported-mass dates must be month starts.")
    if source.duplicated(["source_sheet", "date", "source_outlet"]).any():
        raise ValueError("Midland reported-mass data has duplicate sheet/month/outlet rows.")

    return (
        source.groupby(["date", "generation_orgnm"], as_index=False)
        .agg(
            nox=("nox", lambda values: values.sum(min_count=1)),
            sox=("sox", lambda values: values.sum(min_count=1)),
            dust_tsp=("dust_tsp", lambda values: values.sum(min_count=1)),
            component_count=("source_outlet", "nunique"),
            source_plant_name=("source_plant_name", _join_unique),
            source_component_label=("source_component_label", _join_unique),
        )
        .sort_values(["date", "generation_orgnm"], ignore_index=True)
    )


def clean_generation(generation_raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize Midland's existing public monthly generation API rows."""
    source = generation_raw.copy()
    source = source[source["orgnm"].isin(BOUNDARY_METADATA)].copy()
    if not source["hokinm"].astype("string").str.strip().eq("소계").all():
        unexpected = sorted(source.loc[source["hokinm"].ne("소계"), "hokinm"].unique())
        raise ValueError(f"Unexpected Midland generation unit labels: {unexpected}")
    source["date"] = pd.to_datetime(
        source["ym"].astype("string").str.strip(), format="%Y%m", errors="raise"
    )
    if source.duplicated(["date", "orgnm"]).any():
        raise ValueError("Midland generation contains duplicate plant/technology months.")
    source["energy_generated_mwh"] = pd.to_numeric(source["qvodgen"], errors="coerce")
    source["energy_capacity_mw"] = pd.to_numeric(source["capacity"], errors="coerce")
    return source[["date", "orgnm", "energy_generated_mwh", "energy_capacity_mw"]].rename(
        columns={"orgnm": "generation_orgnm"}
    )


def pollutant_pattern(data: pd.DataFrame) -> pd.Series:
    reported = data[["nox", "sox", "dust_tsp"]].notna()
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


def clean_midland_power(reported_mass: pd.DataFrame, generation_raw: pd.DataFrame) -> pd.DataFrame:
    """Return directly reported monthly mass joined to existing generation."""
    validate_inputs(reported_mass, generation_raw)
    emissions = build_monthly_emissions(reported_mass)
    generation = clean_generation(generation_raw)
    joined = emissions.merge(
        generation, on=["date", "generation_orgnm"], how="left", validate="one_to_one"
    )

    missing_generation = joined["energy_generated_mwh"].isna()
    metadata = joined["generation_orgnm"].map(BOUNDARY_METADATA)
    plant_name = metadata.map(lambda item: item["plant_name"])
    fuel_type = metadata.map(lambda item: item["fuel_type"])
    first_activity = joined["date"].groupby(joined["generation_orgnm"]).transform("min")
    cleaned = pd.DataFrame(
        {
            "date": joined["date"],
            "plant_name": plant_name,
            "plant_number": pd.Series(pd.NA, index=joined.index, dtype="Int64"),
            "plant_opening_date": pd.Series(pd.NaT, index=joined.index),
            "plant_closing_date": pd.Series(pd.NaT, index=joined.index),
            "plant_latitude": pd.Series(pd.NA, index=joined.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=joined.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "fuel_type": fuel_type,
            "energy_generated_mwh": joined["energy_generated_mwh"],
            "energy_capacity_mw": joined["energy_capacity_mw"],
            "reporting_unit_id": (
                REPORTING_ID_PREFIX + ":" + joined["generation_orgnm"].astype("string")
            ),
            "reporting_start_date": first_activity,
            "reporting_end_date": pd.Series(pd.NaT, index=joined.index),
            "reporting_window_basis": "provider_reported_mass_coverage",
            "observation_level": "generation_block",
            "component_count": joined["component_count"],
            "generation_source": GENERATION_SOURCE,
            "generation_coverage_status": missing_generation.map(
                {True: "missing", False: "reported"}
            ),
            "row_status": missing_generation.map(
                {True: "active_partial", False: "active_reported"}
            ),
            "row_status_basis": missing_generation.map(
                {
                    True: "reported_pollutants_without_matching_generation",
                    False: "generation_and_reported_pollutants_reported",
                }
            ),
            "nox": joined["nox"],
            "sox": joined["sox"],
            "dust_tsp": joined["dust_tsp"],
            "pollutant_data_pattern": pollutant_pattern(joined),
            "pollutant_measurement_basis": "mass",
            "nox_unit": "kilograms",
            "sox_unit": "kilograms",
            "dust_tsp_unit": "kilograms",
            "emissions_mass_unit": "kilograms",
            "original_korean_plant_name": joined["source_plant_name"],
            "original_korean_unit_name": joined["source_component_label"],
            "original_korean_note": REPORTED_MASS_NOTE,
        },
        columns=THERMAL_OUTPUT_COLUMNS,
    )

    cleaned["plant_number"] = cleaned["plant_number"].astype("Int64")
    cleaned["component_count"] = cleaned["component_count"].astype("Int64")
    for column in [
        "plant_latitude",
        "plant_longitude",
        "energy_generated_mwh",
        "energy_capacity_mw",
        "nox",
        "sox",
        "dust_tsp",
    ]:
        cleaned[column] = cleaned[column].astype("Float64")
    string_columns = cleaned.select_dtypes(include=["object", "string"]).columns
    cleaned[string_columns] = cleaned[string_columns].astype("string")
    return apply_technology_mapping(apply_location_crosswalk(cleaned)).sort_values(
        ["date", "plant_name", "original_korean_unit_name"], ignore_index=True
    )


def load_and_clean(reported_mass_input_path: Path, generation_input_path: Path) -> pd.DataFrame:
    verify_workbook_sha256(reported_mass_input_path)
    reported_mass = parse_reported_mass_workbook(reported_mass_input_path)
    generation_raw = pd.read_csv(generation_input_path, encoding="utf-8-sig")
    return clean_midland_power(reported_mass, generation_raw)


def save_cleaned(data: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(output_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reported-mass-input-path", type=Path, default=DEFAULT_REPORTED_MASS_INPUT_PATH
    )
    parser.add_argument(
        "--generation-input-path", type=Path, default=DEFAULT_GENERATION_INPUT_PATH
    )
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cleaned = load_and_clean(args.reported_mass_input_path, args.generation_input_path)
    save_cleaned(cleaned, args.output_path)
    matched = cleaned["energy_generated_mwh"].notna().sum()
    print(f"Saved {len(cleaned)} cleaned rows to {args.output_path}")
    print(f"Monthly coverage: {cleaned['date'].min():%Y-%m} to {cleaned['date'].max():%Y-%m}")
    print(f"Matched monthly generation for {matched}/{len(cleaned)} reporting-boundary rows.")
    print("Pollutant mass comes directly from KOMIPO's provider-response workbook.")


if __name__ == "__main__":
    main()
