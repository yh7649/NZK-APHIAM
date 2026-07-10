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
from nzk_aphiam.data.clean.thermal.technology import apply_technology_mapping

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "southeast_power"
    / "southeast_power_daily_air_pollutant_emissions.csv"
)
DEFAULT_GENERATION_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "kepco_subsidiaries"
    / "southeast_power"
    / "southeast_power_monthly_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "kepco_subsidiaries"
    / "southeast_power"
    / "southeast_power_monthly_derived_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea South-East Power"
SOURCE_COLUMNS = ["사업소", "호기", "일자", "SOX", "NOX", "먼지", "산소", "유량", "온도"]
GENERATION_SOURCE_COLUMNS = [
    "사업소",
    "호기",
    "일자",
    "용량(MW)",
    "발전량(MWh)",
    "열효율(%)",
    "이용률(%)",
    "발전원",
]
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
    "concentration rows >30 mg/Sm3. Emissions stacks are aggregated to the "
    "crosswalked KOEN monthly generation unit before joining generation."
)
PLANT_NAMES = {
    "분당": "Bundang",
    "삼천포": "Samcheonpo",
    "여수": "Yeosu",
    "영동": "Yeongdong",
    "영흥": "Yeongheung",
}
FUEL_TYPES = {
    "석탄": "coal",
    "국내탄": "coal",
    "복합": "natural_gas",
    "바이오매스": "biomass",
    "중유": "oil",
    "기타": "other",
}
GENERATION_SOURCE = "southeast_monthly_generation"
REPORTING_ID_PREFIX = "southeast_power"


def generation_unit_identity(plant: object, unit: object, emissions: bool) -> str | None:
    """Crosswalk emissions stack labels and generation labels to one unit key."""
    if pd.isna(plant) or pd.isna(unit):
        return None
    plant_text, unit_text = str(plant).strip(), str(unit).strip()
    if emissions:
        if plant_text == "여수" and unit_text == "-":
            return "2"
        number = extract_unit_number(unit_text)
        if number is None:
            return None
        return f"CG{number}" if plant_text == "분당" else str(number)
    if plant_text == "분당":
        return unit_text if re.fullmatch(r"CG[1-8]", unit_text) else None
    return unit_text if re.fullmatch(r"\d+", unit_text) else None


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
            "generation_unit": [
                generation_unit_identity(plant, unit, emissions=True)
                for plant, unit in zip(source["사업소"], source["호기"], strict=True)
            ],
            "plant_number": [
                int(identity.removeprefix("CG")) if identity else None
                for identity in (
                    generation_unit_identity(plant, unit, emissions=True)
                    for plant, unit in zip(source["사업소"], source["호기"], strict=True)
                )
            ],
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
        "generation_unit",
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

    monthly["component_count"] = monthly["original_korean_unit_name"].str.count("; ") + 1
    return monthly


def clean_generation(generation_raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize KOEN generation and retain units represented by emissions."""
    if list(generation_raw.columns) != GENERATION_SOURCE_COLUMNS:
        raise ValueError(
            "Unexpected South-East Power generation columns. "
            f"Expected {GENERATION_SOURCE_COLUMNS!r}, received {list(generation_raw.columns)!r}."
        )
    source = generation_raw[generation_raw["사업소"].isin(PLANT_NAMES)].copy()
    source["generation_unit"] = [
        generation_unit_identity(plant, unit, emissions=False)
        for plant, unit in zip(source["사업소"], source["호기"], strict=True)
    ]
    source = source.dropna(subset=["generation_unit"])
    source["date"] = pd.to_datetime(source["일자"].astype("string"), format="%Y%m")
    if source.duplicated(["date", "사업소", "generation_unit"]).any():
        raise ValueError("South-East Power generation contains duplicate unit months.")
    source["energy_generated_mwh"] = pd.to_numeric(source["발전량(MWh)"], errors="coerce")
    source["energy_capacity_mw"] = pd.to_numeric(source["용량(MW)"], errors="coerce")
    source["fuel_type"] = source["발전원"].map(FUEL_TYPES)
    unknown = sorted(source.loc[source["fuel_type"].isna(), "발전원"].dropna().unique())
    if unknown:
        raise ValueError(f"Unknown South-East Power generation energy types: {unknown}")
    return source[
        [
            "date",
            "사업소",
            "generation_unit",
            "energy_generated_mwh",
            "energy_capacity_mw",
            "fuel_type",
            "호기",
        ]
    ].rename(columns={"사업소": "original_korean_plant_name", "호기": "generation_unit_label"})


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


def assemble_cleaned(monthly: pd.DataFrame, generation_raw: pd.DataFrame) -> pd.DataFrame:
    generation = clean_generation(generation_raw)
    joined = monthly.merge(
        generation,
        on=["date", "original_korean_plant_name", "generation_unit"],
        how="left",
        validate="one_to_one",
    )
    missing_generation = joined["energy_generated_mwh"].isna()
    first_activity = (
        joined["date"]
        .groupby([joined["original_korean_plant_name"], joined["generation_unit"]])
        .transform("min")
    )
    cleaned = pd.DataFrame(
        {
            "date": joined["date"],
            "plant_name": joined["plant_name"],
            "plant_number": joined["plant_number"],
            "plant_opening_date": pd.Series(pd.NaT, index=joined.index),
            "plant_closing_date": pd.Series(pd.NaT, index=joined.index),
            "plant_latitude": pd.Series(pd.NA, index=joined.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=joined.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "fuel_type": joined["fuel_type"],
            "energy_generated_mwh": joined["energy_generated_mwh"],
            "energy_capacity_mw": joined["energy_capacity_mw"],
            "reporting_unit_id": REPORTING_ID_PREFIX
            + ":"
            + joined["original_korean_plant_name"].astype("string")
            + ":"
            + joined["generation_unit"].astype("string"),
            "reporting_start_date": first_activity,
            "reporting_end_date": pd.Series(pd.NaT, index=joined.index),
            "reporting_window_basis": "first_derived_emissions_activity",
            "observation_level": "generating_unit",
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
                    True: "derived_pollutants_without_matching_generation",
                    False: "generation_and_derived_pollutants_reported",
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
            "original_korean_plant_name": joined["original_korean_plant_name"],
            "original_korean_unit_name": joined["original_korean_unit_name"],
            "original_korean_note": DERIVATION_NOTE,
        },
        columns=THERMAL_OUTPUT_COLUMNS,
    )

    return cleaned


def clean_southeast_power(raw: pd.DataFrame, generation_raw: pd.DataFrame) -> pd.DataFrame:
    """Join monthly generation to inferred pollutant mass at unit level."""
    validate_source_columns(raw)
    source = raw.copy()

    unknown_plants = sorted(set(source["사업소"].dropna()) - set(PLANT_NAMES))
    if unknown_plants:
        raise ValueError(f"Unknown South-East Power plant names: {unknown_plants}")

    daily = build_daily_derived_mass(source)
    monthly = aggregate_monthly_mass(daily)
    cleaned = assemble_cleaned(monthly, generation_raw)

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
        "fuel_type",
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

    cleaned["component_count"] = cleaned["component_count"].astype("Int64")
    return apply_technology_mapping(apply_location_crosswalk(cleaned)).sort_values(
        ["date", "plant_name", "plant_number"], ignore_index=True
    )


def load_and_clean(input_path: Path, generation_input_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(input_path, encoding="utf-8-sig", dtype={"호기": "string"})
    generation_raw = pd.read_csv(
        generation_input_path, encoding="utf-8-sig", dtype={"호기": "string"}
    )
    return clean_southeast_power(raw, generation_raw)


def save_cleaned(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument(
        "--generation-input-path", type=Path, default=DEFAULT_GENERATION_INPUT_PATH
    )
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cleaned = load_and_clean(args.input_path, args.generation_input_path)
    save_cleaned(cleaned, args.output_path)
    print(f"Saved {len(cleaned)} cleaned rows to {args.output_path}")
    print(f"Monthly coverage: {cleaned['date'].min():%Y-%m} to {cleaned['date'].max():%Y-%m}")
    matched = cleaned["energy_generated_mwh"].notna().sum()
    print(f"Matched monthly generation for {matched}/{len(cleaned)} unit rows.")


if __name__ == "__main__":
    main()
