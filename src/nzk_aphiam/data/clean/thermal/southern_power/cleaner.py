"""
Clean and combine Korea Southern Power emissions and generation data.

Monthly emissions are preserved in their reported unit, kilograms. Daily gross
generation is summed to months and converted from kWh to MWh. Explicit
granularity and fuel rules are documented in:

    docs/references/thermal/southern_power_energy_type_mapping.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import pandas as pd

from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_EMISSIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "southern_power"
    / "southern_power_air_pollutant_emissions.csv"
)
DEFAULT_GENERATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "southern_power"
    / "southern_power_daily_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "southern_power"
    / "southern_power_monthly_generation_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea Southern Power"
EMISSIONS_COLUMNS = [
    "년월",
    "사업장명",
    "질소산화물 배출량",
    "총먼지 배출량",
    "호기",
    "황산화물 배출량",
]
GENERATION_COLUMNS = [
    "ymd",
    "ipptnm",
    "ins",
    "hogigb",
    "hogi",
    "qcapdes",
    "qcapdes24",
    "qvodgen",
    "qvodtrn",
]

SITE_RULES = {
    "한국남부발전㈜하동빛드림본부": ("Hadong", "coal", "unit"),
    "한국남부발전㈜삼척빛드림본부": ("Samcheok", "coal", "unit"),
    "한국남부발전㈜남제주빛드림본부(기력)": (
        "Namjeju Steam",
        "bio_oil_and_diesel",
        "unit",
    ),
    "한국남부발전㈜남제주빛드림본부(복합)": (
        "Namjeju Combined",
        "natural_gas",
        "plant",
    ),
    "한국남부발전㈜신인천빛드림본부": (
        "Shin-Incheon",
        "natural_gas",
        "unit",
    ),
    "한국남부발전㈜부산빛드림본부": ("Busan", "natural_gas", "unit"),
    "한국남부발전㈜영월빛드림본부": ("Yeongwol", "natural_gas", "unit"),
    "한국남부발전㈜안동빛드림본부": ("Andong", "natural_gas", "plant"),
    "한국남부발전㈜남제주발전본부한림발전소": (
        "Hallim",
        "natural_gas",
        "plant",
    ),
    "한국남부발전㈜신세종빛드림본부": (
        "Shinsejong",
        "natural_gas",
        "plant",
    ),
}


def validate_columns(
    df: pd.DataFrame,
    expected: list[str],
    source_name: str,
) -> None:
    actual = list(df.columns)
    if actual != expected:
        raise ValueError(
            f"Unexpected Southern Power {source_name} columns. "
            f"Expected {expected!r}, received {actual!r}."
        )


def extract_number(value: object) -> int | None:
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def emissions_target_number(site_name: str, unit_name: str) -> int | None:
    """Return the output unit, or None for documented plant-level matches."""
    _, _, granularity = SITE_RULES[site_name]
    if granularity == "plant":
        return None
    return extract_number(unit_name)


def _sum_with_nulls(series: pd.Series) -> float:
    return series.sum(min_count=1)


def clean_emissions(raw: pd.DataFrame) -> pd.DataFrame:
    """Standardize and aggregate only source subunits that share generation."""
    validate_columns(raw, EMISSIONS_COLUMNS, "emissions")
    source = raw.copy()

    unknown_sites = sorted(set(source["사업장명"].dropna()) - set(SITE_RULES))
    if unknown_sites:
        raise ValueError(f"Unknown Southern Power emissions sites: {unknown_sites}")

    source["date"] = pd.to_datetime(source["년월"], format="%Y-%m", errors="raise")
    source["plant_name"] = source["사업장명"].map(lambda value: SITE_RULES[value][0])
    source["energy_type"] = source["사업장명"].map(lambda value: SITE_RULES[value][1])
    source["plant_number"] = [
        emissions_target_number(site, unit)
        for site, unit in zip(source["사업장명"], source["호기"], strict=True)
    ]
    source["nox"] = pd.to_numeric(source["질소산화물 배출량"], errors="coerce")
    source["sox"] = pd.to_numeric(source["황산화물 배출량"], errors="coerce")
    source["dust_tsp"] = pd.to_numeric(source["총먼지 배출량"], errors="coerce")

    group_columns = [
        "date",
        "plant_name",
        "plant_number",
        "energy_type",
        "사업장명",
    ]
    grouped = (
        source.groupby(group_columns, dropna=False, sort=False)
        .agg(
            nox=("nox", _sum_with_nulls),
            sox=("sox", _sum_with_nulls),
            dust_tsp=("dust_tsp", _sum_with_nulls),
            original_korean_unit_name=(
                "호기",
                lambda values: "|".join(sorted(set(values.astype(str)))),
            ),
        )
        .reset_index()
    )
    grouped["plant_number"] = grouped["plant_number"].astype("Int64")
    return grouped


def generation_target(row: pd.Series) -> tuple[str, int | None] | None:
    """Map one daily generation component to the emissions output granularity."""
    plant = row["ipptnm"]
    if pd.isna(plant):
        return None
    component = str(row["hogi"])

    if plant == "하동화력":
        return "Hadong", extract_number(component)
    if plant == "삼척":
        return "Samcheok", extract_number(component)
    if plant == "남제주기력":
        return "Namjeju Steam", extract_number(component)
    if plant in {"남제주복합 시운전", "남제주빛드림본부"}:
        return "Namjeju Combined", None
    if plant == "신인천복합" and component.startswith("CG"):
        return "Shin-Incheon", extract_number(component)
    if plant == "부산복합" and component.startswith("CG"):
        return "Busan", extract_number(component)
    if plant == "영월복합" and component.startswith("CG"):
        return "Yeongwol", extract_number(component)
    if plant == "안동복합":
        return "Andong", None
    if plant == "한림복합":
        return "Hallim", None
    if plant == "신세종복합":
        return "Shinsejong", None
    return None


def aggregate_generation(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily gross generation to the documented monthly granularity."""
    validate_columns(raw, GENERATION_COLUMNS, "generation")
    source = raw.copy()
    targets = source.apply(generation_target, axis=1)
    keep = targets.notna()
    source = source.loc[keep].copy()
    targets = targets.loc[keep]

    source["plant_name"] = targets.map(lambda value: value[0])
    source["plant_number"] = targets.map(lambda value: value[1])
    source["date"] = (
        pd.to_datetime(source["ymd"], format="%Y-%m-%d", errors="raise")
        .dt.to_period("M")
        .dt.to_timestamp()
    )
    source["energy_generated_mwh"] = pd.to_numeric(source["qvodgen"], errors="coerce") / 1000
    source["energy_capacity_mw"] = pd.to_numeric(source["qcapdes"], errors="coerce") / 1000

    component_month = (
        source.groupby(
            ["date", "plant_name", "plant_number", "hogi"],
            dropna=False,
            sort=False,
        )
        .agg(
            energy_generated_mwh=("energy_generated_mwh", _sum_with_nulls),
            energy_capacity_mw=("energy_capacity_mw", "max"),
        )
        .reset_index()
    )
    monthly = (
        component_month.groupby(
            ["date", "plant_name", "plant_number"],
            dropna=False,
            sort=False,
        )
        .agg(
            energy_generated_mwh=("energy_generated_mwh", _sum_with_nulls),
            energy_capacity_mw=("energy_capacity_mw", _sum_with_nulls),
        )
        .reset_index()
    )
    monthly["plant_number"] = monthly["plant_number"].astype("Int64")
    return monthly


def make_join_key(plant_name: pd.Series, plant_number: pd.Series) -> pd.Series:
    number = plant_number.astype("Int64").astype("string").fillna("all")
    return plant_name.astype("string") + ":" + number


def clean_southern_power(
    emissions_raw: pd.DataFrame,
    generation_raw: pd.DataFrame,
) -> pd.DataFrame:
    """Combine monthly emissions and safely matched monthly generation."""
    emissions = clean_emissions(emissions_raw)
    generation = aggregate_generation(generation_raw)
    emissions["_join_key"] = make_join_key(emissions["plant_name"], emissions["plant_number"])
    generation["_join_key"] = make_join_key(generation["plant_name"], generation["plant_number"])

    merged = emissions.merge(
        generation[
            [
                "date",
                "_join_key",
                "energy_generated_mwh",
                "energy_capacity_mw",
            ]
        ],
        on=["date", "_join_key"],
        how="left",
        validate="many_to_one",
    )

    cleaned = pd.DataFrame(
        {
            "date": merged["date"],
            "plant_name": merged["plant_name"],
            "plant_number": merged["plant_number"],
            "plant_opening_date": pd.Series(pd.NaT, index=merged.index),
            "plant_closing_date": pd.Series(pd.NaT, index=merged.index),
            "plant_latitude": pd.Series(pd.NA, index=merged.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=merged.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "energy_type": merged["energy_type"],
            "energy_generated_mwh": merged["energy_generated_mwh"],
            "energy_capacity_mw": merged["energy_capacity_mw"],
            "nox": merged["nox"],
            "sox": merged["sox"],
            "dust_tsp": merged["dust_tsp"],
            "pollutant_measurement_basis": "mass",
            "nox_unit": "kilograms",
            "sox_unit": "kilograms",
            "dust_tsp_unit": "kilograms",
            "emissions_mass_unit": "kilograms",
            "temperature_celsius": pd.Series(pd.NA, index=merged.index, dtype="Float64"),
            "original_korean_plant_name": merged["사업장명"],
            "original_korean_unit_name": merged["original_korean_unit_name"],
            "original_korean_note": pd.Series(pd.NA, index=merged.index, dtype="string"),
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


def load_and_clean(
    emissions_path: Path,
    generation_path: Path,
) -> pd.DataFrame:
    emissions = pd.read_csv(emissions_path, encoding="utf-8-sig", dtype={"호기": "string"})
    generation = pd.read_csv(
        generation_path,
        encoding="utf-8-sig",
        dtype="string",
    )
    return clean_southern_power(emissions, generation)


def save_cleaned(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emissions-path", type=Path, default=DEFAULT_EMISSIONS_PATH)
    parser.add_argument("--generation-path", type=Path, default=DEFAULT_GENERATION_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cleaned = load_and_clean(args.emissions_path, args.generation_path)
    save_cleaned(cleaned, args.output_path)
    matched = cleaned["energy_generated_mwh"].notna().sum()
    print(f"Saved {len(cleaned)} cleaned rows to {args.output_path}")
    print(f"Monthly coverage: {cleaned['date'].min():%Y-%m} to {cleaned['date'].max():%Y-%m}")
    print(f"Rows with safely matched generation: {matched} / {len(cleaned)}")


if __name__ == "__main__":
    main()
