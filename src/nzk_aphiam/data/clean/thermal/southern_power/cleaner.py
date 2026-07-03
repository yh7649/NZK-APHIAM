"""
Clean and combine Korea Southern Power emissions and generation data.

Monthly emissions are preserved in their reported unit, kilograms. Daily gross
generation is summed to months and converted from kWh to MWh. Explicit
granularity and fuel rules are documented in:

    docs/references/thermal/southern_power_fuel_type_mapping.csv
"""

from __future__ import annotations

import argparse
import calendar
from pathlib import Path
import re

import pandas as pd

from nzk_aphiam.data.clean.thermal.location_crosswalk import apply_location_crosswalk
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.technology import apply_technology_mapping

PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_EMISSIONS_PATH = (
    PROJECT_ROOT / "data" / "raw" / "southern_power" / "southern_power_air_pollutant_emissions.csv"
)
DEFAULT_GENERATION_PATH = (
    PROJECT_ROOT / "data" / "raw" / "southern_power" / "southern_power_daily_generation.csv"
)
DEFAULT_HOURLY_GENERATION_PATH = (
    PROJECT_ROOT / "data" / "raw" / "southern_power" / "southern_power_hourly_generation.csv"
)
DEFAULT_ANNUAL_GENERATION_PATH = (
    PROJECT_ROOT / "data" / "raw" / "southern_power" / "southern_power_annual_generation.csv"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "southern_power"
    / "southern_power_monthly_generation_emissions.csv"
)
DEFAULT_ANNUAL_VALIDATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "southern_power"
    / "southern_power_annual_generation_validation.csv"
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
GENERATION_REQUIRED_COLUMNS = ["ymd", "ipptnm", "hogi", "qvodgen"]
ANNUAL_GENERATION_COLUMNS = ["년도", "발전원", "플랜트", "호기", "용량", "발전량"]
RECONCILIATION_TOLERANCE_PCT = 1.0

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


def validate_required_columns(
    df: pd.DataFrame,
    required: list[str],
    source_name: str,
) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Southern Power {source_name} is missing columns: {missing!r}")


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
    source["fuel_type"] = source["사업장명"].map(lambda value: SITE_RULES[value][1])
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
        "fuel_type",
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
    validate_required_columns(raw, GENERATION_REQUIRED_COLUMNS, "generation")
    source = raw.copy()
    targets = source.apply(generation_target, axis=1)
    keep = targets.notna()
    source = source.loc[keep].copy()
    targets = targets.loc[keep]

    if source.empty:
        return pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                "plant_name": pd.Series(dtype="string"),
                "plant_number": pd.Series(dtype="Int64"),
                "energy_generated_mwh": pd.Series(dtype="Float64"),
                "energy_capacity_mw": pd.Series(dtype="Float64"),
                "component_count": pd.Series(dtype="Int64"),
                "generation_days_reported": pd.Series(dtype="Int64"),
                "generation_days_expected": pd.Series(dtype="Int64"),
                "generation_coverage_status": pd.Series(dtype="string"),
            }
        )

    source["plant_name"] = targets.map(lambda value: value[0])
    source["plant_number"] = targets.map(lambda value: value[1])
    source["source_day"] = pd.to_datetime(source["ymd"], format="%Y-%m-%d", errors="raise")
    source["date"] = source["source_day"].dt.to_period("M").dt.to_timestamp()
    source["energy_generated_mwh"] = pd.to_numeric(source["qvodgen"], errors="coerce") / 1000
    capacity = source["qcapdes"] if "qcapdes" in source else pd.Series(pd.NA, index=source.index)
    source["energy_capacity_mw"] = pd.to_numeric(capacity, errors="coerce") / 1000

    component_month = (
        source.groupby(
            ["date", "plant_name", "plant_number", "hogi"],
            dropna=False,
            sort=False,
        )
        .agg(
            energy_generated_mwh=("energy_generated_mwh", _sum_with_nulls),
            energy_capacity_mw=("energy_capacity_mw", "max"),
            generation_days_reported=("source_day", "nunique"),
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
            component_count=("hogi", "nunique"),
            generation_days_reported=("generation_days_reported", "min"),
        )
        .reset_index()
    )
    monthly["plant_number"] = monthly["plant_number"].astype("Int64")
    monthly["component_count"] = monthly["component_count"].astype("Int64")
    monthly["generation_days_reported"] = monthly["generation_days_reported"].astype("Int64")
    monthly["generation_days_expected"] = (
        monthly["date"]
        .map(lambda value: calendar.monthrange(value.year, value.month)[1])
        .astype("Int64")
    )
    monthly["generation_coverage_status"] = "partial"
    complete = monthly["generation_days_reported"].eq(monthly["generation_days_expected"])
    monthly.loc[complete, "generation_coverage_status"] = "complete"
    return monthly


def make_join_key(plant_name: pd.Series, plant_number: pd.Series) -> pd.Series:
    number = plant_number.astype("Int64").astype("string").fillna("all")
    return plant_name.astype("string") + ":" + number


def clean_southern_power(
    emissions_raw: pd.DataFrame,
    generation_raw: pd.DataFrame,
    hourly_generation_raw: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine monthly emissions and safely matched monthly generation."""
    emissions = clean_emissions(emissions_raw)
    generation = aggregate_generation(generation_raw)
    hourly = (
        aggregate_generation(hourly_generation_raw)
        if hourly_generation_raw is not None and not hourly_generation_raw.empty
        else pd.DataFrame()
    )
    emissions["_join_key"] = make_join_key(emissions["plant_name"], emissions["plant_number"])
    generation["_join_key"] = make_join_key(generation["plant_name"], generation["plant_number"])

    generation = generation.rename(
        columns={
            "energy_generated_mwh": "primary_energy_generated_mwh",
            "component_count": "primary_component_count",
            "generation_days_reported": "primary_generation_days_reported",
            "generation_days_expected": "primary_generation_days_expected",
            "generation_coverage_status": "primary_generation_coverage_status",
        }
    )

    merged = emissions.merge(
        generation[
            [
                "date",
                "_join_key",
                "primary_energy_generated_mwh",
                "energy_capacity_mw",
                "primary_component_count",
                "primary_generation_days_reported",
                "primary_generation_days_expected",
                "primary_generation_coverage_status",
            ]
        ],
        on=["date", "_join_key"],
        how="left",
        validate="many_to_one",
    )

    if not hourly.empty:
        hourly["_join_key"] = make_join_key(hourly["plant_name"], hourly["plant_number"])
        hourly = hourly.rename(
            columns={
                "energy_generated_mwh": "alternate_energy_generated_mwh",
                "component_count": "alternate_component_count",
                "generation_days_reported": "alternate_generation_days_reported",
                "generation_days_expected": "alternate_generation_days_expected",
                "generation_coverage_status": "alternate_generation_coverage_status",
            }
        )
        merged = merged.merge(
            hourly[
                [
                    "date",
                    "_join_key",
                    "alternate_energy_generated_mwh",
                    "alternate_component_count",
                    "alternate_generation_days_reported",
                    "alternate_generation_days_expected",
                    "alternate_generation_coverage_status",
                ]
            ],
            on=["date", "_join_key"],
            how="left",
            validate="many_to_one",
        )
    else:
        for column in [
            "alternate_energy_generated_mwh",
            "alternate_component_count",
            "alternate_generation_days_reported",
            "alternate_generation_days_expected",
            "alternate_generation_coverage_status",
        ]:
            merged[column] = pd.NA

    primary_present = merged["primary_energy_generated_mwh"].notna()
    alternate_present = merged["alternate_energy_generated_mwh"].notna()
    merged["energy_generated_mwh"] = merged["primary_energy_generated_mwh"].combine_first(
        merged["alternate_energy_generated_mwh"]
    )
    merged["generation_source"] = pd.Series("missing", index=merged.index, dtype="string")
    merged.loc[primary_present, "generation_source"] = "daily_api"
    merged.loc[~primary_present & alternate_present, "generation_source"] = "hourly_api_fallback"
    for output, primary, alternate in [
        ("component_count", "primary_component_count", "alternate_component_count"),
        (
            "generation_days_reported",
            "primary_generation_days_reported",
            "alternate_generation_days_reported",
        ),
        (
            "generation_days_expected",
            "primary_generation_days_expected",
            "alternate_generation_days_expected",
        ),
        (
            "generation_coverage_status",
            "primary_generation_coverage_status",
            "alternate_generation_coverage_status",
        ),
    ]:
        merged[output] = merged[primary].combine_first(merged[alternate])
    merged["generation_coverage_status"] = merged["generation_coverage_status"].fillna("missing")

    both = primary_present & alternate_present
    denominator = (
        merged[["primary_energy_generated_mwh", "alternate_energy_generated_mwh"]]
        .abs()
        .max(axis=1)
        .clip(lower=1)
    )
    merged["generation_difference_pct"] = (
        100
        * (merged["primary_energy_generated_mwh"] - merged["alternate_energy_generated_mwh"]).abs()
        / denominator
    ).where(both)
    merged["generation_reconciliation_status"] = pd.Series(
        "not_checked", index=merged.index, dtype="string"
    )
    merged.loc[~primary_present & alternate_present, "generation_reconciliation_status"] = (
        "alternate_fill"
    )
    merged.loc[both, "generation_reconciliation_status"] = "mismatch"
    merged.loc[
        both & merged["generation_difference_pct"].le(RECONCILIATION_TOLERANCE_PCT),
        "generation_reconciliation_status",
    ] = "matched"

    def observation_level(plant: str) -> str:
        if plant in {"Andong", "Hallim", "Namjeju Combined", "Shinsejong"}:
            return "plant"
        if plant in {"Busan", "Shin-Incheon", "Yeongwol"}:
            return "gas_turbine"
        return "generating_unit"

    merged["observation_level"] = merged["plant_name"].map(observation_level)

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
            "fuel_type": merged["fuel_type"],
            "energy_generated_mwh": merged["energy_generated_mwh"],
            "energy_capacity_mw": merged["energy_capacity_mw"],
            "observation_level": merged["observation_level"],
            "component_count": merged["component_count"],
            "generation_source": merged["generation_source"],
            "generation_days_reported": merged["generation_days_reported"],
            "generation_days_expected": merged["generation_days_expected"],
            "generation_coverage_status": merged["generation_coverage_status"],
            "alternate_energy_generated_mwh": merged["alternate_energy_generated_mwh"],
            "generation_difference_pct": merged["generation_difference_pct"],
            "generation_reconciliation_status": merged["generation_reconciliation_status"],
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
    for column in ["component_count", "generation_days_reported", "generation_days_expected"]:
        cleaned[column] = cleaned[column].astype("Int64")
    for column in [
        "energy_generated_mwh",
        "energy_capacity_mw",
        "alternate_energy_generated_mwh",
        "generation_difference_pct",
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
        "observation_level",
        "generation_source",
        "generation_coverage_status",
        "generation_reconciliation_status",
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


def load_and_clean(
    emissions_path: Path,
    generation_path: Path,
    hourly_generation_path: Path | None = None,
) -> pd.DataFrame:
    emissions = pd.read_csv(emissions_path, encoding="utf-8-sig", dtype={"호기": "string"})
    generation = pd.read_csv(
        generation_path,
        encoding="utf-8-sig",
        dtype="string",
    )
    hourly = None
    if hourly_generation_path is not None and hourly_generation_path.exists():
        hourly = pd.read_csv(hourly_generation_path, encoding="utf-8-sig", dtype="string")
    return clean_southern_power(emissions, generation, hourly)


def build_annual_validation(cleaned: pd.DataFrame, annual_raw: pd.DataFrame) -> pd.DataFrame:
    """Compare monthly plant-year sums with Southern's official annual file."""
    validate_columns(annual_raw, ANNUAL_GENERATION_COLUMNS, "annual generation")
    source = annual_raw.copy()

    def annual_plant(row: pd.Series) -> str | None:
        plant = str(row["플랜트"])
        unit = str(row["호기"])
        fuel = str(row["발전원"])
        if "하동" in plant:
            return "Hadong"
        if "영월" in plant:
            return "Yeongwol"
        if "안동" in plant:
            return "Andong"
        if "신인천" in plant:
            return "Shin-Incheon"
        if "신세종" in plant:
            return "Shinsejong"
        if "삼척" in plant:
            return "Samcheok"
        if "부산" in plant:
            return "Busan"
        if "남제주" in plant:
            if "한림" in unit:
                return "Hallim"
            if "복합" in fuel or "CC" in unit.upper():
                return "Namjeju Combined"
            return "Namjeju Steam"
        return None

    source["plant_name"] = source.apply(annual_plant, axis=1)
    source = source[source["plant_name"].notna()].copy()
    source["year"] = pd.to_numeric(source["년도"], errors="raise").astype(int)
    source["annual_reported_generation_mwh"] = (
        pd.to_numeric(source["발전량"], errors="coerce") / 1000
    )
    annual = source.groupby(["year", "plant_name"], as_index=False).agg(
        annual_reported_generation_mwh=("annual_reported_generation_mwh", _sum_with_nulls)
    )
    monthly = cleaned.copy()
    monthly["date"] = pd.to_datetime(monthly["date"])
    monthly["year"] = monthly["date"].dt.year
    plant_month = monthly.groupby(["year", "plant_name", "date"], as_index=False).agg(
        monthly_generation_mwh=("energy_generated_mwh", _sum_with_nulls),
        partial_months=(
            "generation_coverage_status",
            lambda values: int(values.ne("complete").any()),
        ),
    )
    monthly = plant_month.groupby(["year", "plant_name"], as_index=False).agg(
        monthly_generation_mwh=("monthly_generation_mwh", _sum_with_nulls),
        months_present=("date", "nunique"),
        partial_months=("partial_months", "sum"),
    )
    result = annual.merge(monthly, on=["year", "plant_name"], how="left", validate="one_to_one")
    denominator = result["annual_reported_generation_mwh"].abs().clip(lower=1)
    result["difference_pct"] = (
        100
        * (result["monthly_generation_mwh"] - result["annual_reported_generation_mwh"]).abs()
        / denominator
    )
    result["validation_status"] = "mismatch"
    result.loc[result["monthly_generation_mwh"].isna(), "validation_status"] = "monthly_missing"
    incomplete = result["months_present"].fillna(0).lt(12) | result["partial_months"].fillna(0).gt(
        0
    )
    result.loc[incomplete & result["monthly_generation_mwh"].notna(), "validation_status"] = (
        "incomplete_monthly_coverage"
    )
    matched = ~incomplete & result["difference_pct"].le(RECONCILIATION_TOLERANCE_PCT)
    result.loc[matched, "validation_status"] = "matched"
    return result.sort_values(["year", "plant_name"], ignore_index=True)


def save_cleaned(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")


def read_annual_generation(path: Path) -> pd.DataFrame:
    """Read the provider file, which has appeared in UTF-8 and CP949 variants."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp949")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emissions-path", type=Path, default=DEFAULT_EMISSIONS_PATH)
    parser.add_argument("--generation-path", type=Path, default=DEFAULT_GENERATION_PATH)
    parser.add_argument(
        "--hourly-generation-path", type=Path, default=DEFAULT_HOURLY_GENERATION_PATH
    )
    parser.add_argument(
        "--annual-generation-path", type=Path, default=DEFAULT_ANNUAL_GENERATION_PATH
    )
    parser.add_argument(
        "--annual-validation-path", type=Path, default=DEFAULT_ANNUAL_VALIDATION_PATH
    )
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cleaned = load_and_clean(
        args.emissions_path, args.generation_path, args.hourly_generation_path
    )
    save_cleaned(cleaned, args.output_path)
    if args.annual_generation_path.exists():
        annual_raw = read_annual_generation(args.annual_generation_path)
        validation = build_annual_validation(cleaned, annual_raw)
        save_cleaned(validation, args.annual_validation_path)
        print(f"Saved {len(validation)} annual validation rows to {args.annual_validation_path}")
    matched = cleaned["energy_generated_mwh"].notna().sum()
    print(f"Saved {len(cleaned)} cleaned rows to {args.output_path}")
    print(f"Monthly coverage: {cleaned['date'].min():%Y-%m} to {cleaned['date'].max():%Y-%m}")
    print(f"Rows with safely matched generation: {matched} / {len(cleaned)}")


if __name__ == "__main__":
    main()
