"""Clean and join Korea Midland Power generation and facility air-status data.

KOMIPO's usable facility APIs report pollutant concentrations and stack flow at
unit/turbine level, while its generation API reports monthly plant/technology
subtotals (``호기 == 소계``).  This cleaner therefore derives pollutant mass at
the source-row level, aggregates it to the generation reporting boundary, and
only then joins monthly generation.  It never repeats a plant subtotal across
component turbines.

The usable facilities are Incheon, Jeju, Sejong, and Seocheon. Boryeong, Seoul,
and Shin-Boryeong expose TMS diagnostic fields rather than stack pollutant and
flow fields and remain raw-only sources.

An optional historical back-fill path extends Incheon combined-cycle coverage
to 2012 using monthly average concentrations from KOMIPO's aggregate emissions
API (data.go.kr dataset 15084758) scaled by a flow proxy (Sm³/MWh) derived
from the 2024--2025 odcloud facility data.  These rows are marked with a
separate note and have no component_count.  Pass ``aggregate_raw`` to enable.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nzk_aphiam.config.paths import ARCHIVE_INTERIM_DIR, ARCHIVE_RAW_DIR, DATA_DIR
from nzk_aphiam.data.clean.thermal.location_crosswalk import apply_location_crosswalk
from nzk_aphiam.data.clean.thermal.schema import THERMAL_OUTPUT_COLUMNS
from nzk_aphiam.data.clean.thermal.technology import apply_technology_mapping

DEFAULT_FACILITY_INPUT_PATH = (
    ARCHIVE_RAW_DIR
    / "kepco_midland_concentration"
    / "facilities"
    / "midland_power_facility_air_status.csv"
)
DEFAULT_GENERATION_INPUT_PATH = (
    DATA_DIR
    / "raw"
    / "kepco_subsidiaries"
    / "midland_power"
    / "midland_power_monthly_generation.csv"
)
DEFAULT_AGGREGATE_INPUT_PATH = (
    ARCHIVE_RAW_DIR / "kepco_midland_concentration" / "midland_power_air_pollutant_emissions.csv"
)
DEFAULT_OUTPUT_PATH = (
    ARCHIVE_INTERIM_DIR
    / "kepco_midland_concentration"
    / "midland_power_monthly_derived_emissions.csv"
)

SUBSIDIARY_COMPANY = "Korea Midland Power"
FACILITY_SOURCE_COLUMNS = [
    "source_facility",
    "source_korean_facility_name",
    "source_english_facility_name",
    "usable_for_mass_derivation",
    "발전소 호기",
    "처리일",
    "황산화물",
    "질소 산화물",
    "먼지",
    "유량",
]
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
MOLAR_VOLUME_LITERS_PER_MOL = 22.4
SOX_MOLECULAR_WEIGHT_GRAMS = 64
NOX_MOLECULAR_WEIGHT_GRAMS = 46
GENERATION_SOURCE = "midland_monthly_generation_api"
REPORTING_ID_PREFIX = "midland_power"

# Historical back-fill for Incheon combined-cycle (2012 onward) using the
# aggregate emissions API.  Only "복합" rows are used; old boiler units (#1~2호기)
# have no odcloud flow reference and are excluded.
AGGREGATE_SOURCE_COLUMNS = [
    "orgnm",
    "ym",
    "hokinm",
    "airsox",
    "avgair01value",
    "airnox",
    "avgair02value",
    "airdst",
    "avgair03value",
]
PROXY_NOTE = (
    "Monthly NOx mass estimated from monthly average concentration "
    "(data.go.kr dataset 15084758, 인천화력 복합) × proxy stack flow derived from "
    "2024-2025 KOMIPO odcloud Incheon facility data (total Sm³ per MWh of "
    "인천복합 generation). SOx and dust are near-zero for gas combined-cycle and "
    "are treated as zero here. Proxy flow is an approximation; these rows should "
    "be treated as indicative rather than directly measured."
)

# Crosswalk from each emissions component to the coarser generation subtotal.
# Seocheon's current facility data are mapped to 신서천화력: the facility rows
# cover 2024 onward, while old 서천화력 is a retired zero-generation placeholder;
# the project location crosswalk likewise identifies Seocheon with the 2021
# Shin-Seocheon unit.
BOUNDARY_RULES = (
    ("incheon", r"^인천 GT\d+$", "인천복합", "Incheon Combined", "natural_gas"),
    ("jeju", r"^제주기력\d+호기$", "제주기력", "Jeju Steam", "oil"),
    ("jeju", r"^제주내연\d+호기$", "제주내연", "Jeju Internal Combustion", "oil"),
    ("jeju", r"^제주복합\d+호기$", "제주복합", "Jeju Combined", "natural_gas"),
    ("sejong", r"^세종복합\d+호기$", "세종천연가스", "Sejong Combined", "natural_gas"),
    ("seocheon", r"^서천 1호기$", "신서천화력", "Shin-Seocheon Steam", "coal"),
)
BOUNDARY_METADATA = {
    generation_name: {
        "plant_name": {
            "인천복합": "Incheon",
            "제주기력": "Jeju",
            "제주내연": "Jeju",
            "제주복합": "Jeju",
            "세종천연가스": "Sejong",
            "신서천화력": "Seocheon",
        }[generation_name],
        "reporting_label": reporting_label,
        "fuel_type": fuel_type,
    }
    for _, _, generation_name, reporting_label, fuel_type in BOUNDARY_RULES
}
DERIVATION_NOTE = (
    "Pollutant mass derived from KOMIPO facility concentration and stack-flow rows, "
    "then summed to the matching monthly generation subtotal. Gas kg = ppm * flow_sm3 "
    "* molecular_weight / (22.4 * 1,000,000); dust kg = mg_per_sm3 * flow_sm3 / "
    "1,000,000. Generation is not allocated back to component turbines."
)


def validate_source_columns(facility_raw: pd.DataFrame, generation_raw: pd.DataFrame) -> None:
    """Fail clearly when either upstream source can no longer support the join."""
    missing_facility = [c for c in FACILITY_SOURCE_COLUMNS if c not in facility_raw.columns]
    missing_generation = [c for c in GENERATION_SOURCE_COLUMNS if c not in generation_raw.columns]
    if missing_facility:
        raise ValueError(f"Midland facility raw data is missing columns: {missing_facility}")
    if missing_generation:
        raise ValueError(f"Midland generation raw data is missing columns: {missing_generation}")


def is_usable(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_datetime(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.isna().any():
        parsed = parsed.fillna(
            pd.to_datetime(values.astype("string"), format="%Y%m%d%H%M", errors="coerce")
        )
    if parsed.isna().any():
        bad = values[parsed.isna()].dropna().head(5).tolist()
        raise ValueError(f"Could not parse Midland facility 처리일 values: {bad}")
    return parsed


def assign_generation_boundary(source: pd.DataFrame) -> pd.DataFrame:
    """Attach the one documented generation subtotal matching each emissions component."""
    result = source.copy()
    result["generation_orgnm"] = pd.Series(pd.NA, index=result.index, dtype="string")
    for facility, pattern, generation_name, _, _ in BOUNDARY_RULES:
        matches = result["source_facility"].eq(facility) & result["발전소 호기"].str.match(
            pattern, na=False
        )
        result.loc[matches, "generation_orgnm"] = generation_name

    unmatched = result.loc[result["generation_orgnm"].isna(), ["source_facility", "발전소 호기"]]
    if not unmatched.empty:
        identities = list(unmatched.drop_duplicates().itertuples(index=False, name=None))
        raise ValueError(f"Unmapped Midland facility reporting identities: {identities}")
    return result


def build_monthly_emissions(facility_raw: pd.DataFrame) -> pd.DataFrame:
    """Derive row-level mass and aggregate it to generation reporting boundaries."""
    source = facility_raw[facility_raw["usable_for_mass_derivation"].map(is_usable)].copy()
    source = source.dropna(subset=["발전소 호기", "처리일"])
    source["발전소 호기"] = source["발전소 호기"].astype("string")
    source = assign_generation_boundary(source)

    flow = pd.to_numeric(source["유량"], errors="coerce")
    sox_ppm = pd.to_numeric(source["황산화물"], errors="coerce")
    nox_ppm = pd.to_numeric(source["질소 산화물"], errors="coerce")
    dust_mg_sm3 = pd.to_numeric(source["먼지"], errors="coerce")
    rows = pd.DataFrame(
        {
            "date": parse_datetime(source["처리일"]).dt.to_period("M").dt.to_timestamp(),
            "generation_orgnm": source["generation_orgnm"],
            "nox": nox_ppm
            * flow
            * NOX_MOLECULAR_WEIGHT_GRAMS
            / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000),
            "sox": sox_ppm
            * flow
            * SOX_MOLECULAR_WEIGHT_GRAMS
            / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000),
            "dust_tsp": dust_mg_sm3 * flow / 1_000_000,
            "component": source["발전소 호기"],
        }
    )
    return (
        rows.groupby(["date", "generation_orgnm"], as_index=False)
        .agg(
            nox=("nox", lambda x: x.sum(min_count=1)),
            sox=("sox", lambda x: x.sum(min_count=1)),
            dust_tsp=("dust_tsp", lambda x: x.sum(min_count=1)),
            component_count=("component", "nunique"),
        )
        .sort_values(["date", "generation_orgnm"], ignore_index=True)
    )


def compute_incheon_flow_proxy(facility_raw: pd.DataFrame, generation_raw: pd.DataFrame) -> float:
    """Return Sm³ of flue gas per MWh of Incheon combined generation.

    Computed from the 2024-2025 odcloud Incheon GT rows joined to the monthly
    인천복합 generation subtotal.  The resulting scalar is used to scale
    historical generation into an estimated total monthly stack flow.
    """
    incheon = facility_raw[
        facility_raw["source_facility"].eq("incheon")
        & facility_raw["usable_for_mass_derivation"].map(is_usable)
    ].copy()
    if incheon.empty:
        raise ValueError("No usable Incheon facility rows for flow proxy computation.")
    incheon["_date"] = parse_datetime(incheon["처리일"]).dt.to_period("M").dt.to_timestamp()
    incheon["_flow"] = pd.to_numeric(incheon["유량"], errors="coerce")
    monthly_flow = (
        incheon.groupby("_date", as_index=False)["_flow"]
        .sum(min_count=1)
        .rename(columns={"_date": "date", "_flow": "total_flow_sm3"})
    )
    gen = clean_generation(generation_raw)
    gen_incheon = gen[gen["generation_orgnm"] == "인천복합"][["date", "energy_generated_mwh"]]
    merged = monthly_flow.merge(gen_incheon, on="date", how="inner")
    valid = merged.dropna(subset=["total_flow_sm3", "energy_generated_mwh"])
    valid = valid[valid["energy_generated_mwh"] > 0]
    if valid.empty:
        raise ValueError(
            "No overlapping Incheon flow and generation months for proxy computation."
        )
    return float(valid["total_flow_sm3"].sum() / valid["energy_generated_mwh"].sum())


def build_aggregate_incheon_emissions(
    aggregate_raw: pd.DataFrame,
    flow_proxy_sm3_per_mwh: float,
    generation_raw: pd.DataFrame,
    exclude_dates: set | None = None,
) -> pd.DataFrame:
    """Estimate Incheon combined-cycle monthly emissions from aggregate concentrations.

    Filters the monthly aggregate emissions API to 인천화력 복합 rows, applies
    the proxy flow (Sm³/MWh × generation), and returns a DataFrame in the same
    shape as ``build_monthly_emissions()`` with a ``_is_estimated`` marker.
    Months already covered by odcloud data should be passed as ``exclude_dates``
    to avoid duplicate rows.
    """
    missing = [c for c in AGGREGATE_SOURCE_COLUMNS if c not in aggregate_raw.columns]
    if missing:
        raise ValueError(f"Midland aggregate raw data is missing columns: {missing}")

    src = aggregate_raw[
        aggregate_raw["orgnm"].eq("인천화력") & aggregate_raw["hokinm"].eq("복합")
    ].copy()

    if src.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "generation_orgnm",
                "nox",
                "sox",
                "dust_tsp",
                "component_count",
                "_is_estimated",
            ]
        )

    src["date"] = pd.to_datetime(src["ym"].astype(str), format="%Y%m", errors="raise")
    if exclude_dates:
        src = src[~src["date"].isin(exclude_dates)]

    if src.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "generation_orgnm",
                "nox",
                "sox",
                "dust_tsp",
                "component_count",
                "_is_estimated",
            ]
        )

    nox_ppm = pd.to_numeric(src["avgair02value"], errors="coerce")
    sox_ppm = pd.to_numeric(src["avgair01value"], errors="coerce")
    dust_mg_sm3 = pd.to_numeric(src["avgair03value"], errors="coerce")

    gen = clean_generation(generation_raw)
    gen_incheon = gen[gen["generation_orgnm"] == "인천복합"][["date", "energy_generated_mwh"]]

    rows = pd.DataFrame(
        {
            "date": src["date"].values,
            "generation_orgnm": "인천복합",
            "nox_ppm": nox_ppm.values,
            "sox_ppm": sox_ppm.values,
            "dust_mg_sm3": dust_mg_sm3.values,
        }
    )
    rows = rows.merge(gen_incheon, on="date", how="left")
    estimated_flow = flow_proxy_sm3_per_mwh * rows["energy_generated_mwh"]
    rows["nox"] = (
        rows["nox_ppm"]
        * estimated_flow
        * NOX_MOLECULAR_WEIGHT_GRAMS
        / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000)
    )
    rows["sox"] = (
        rows["sox_ppm"]
        * estimated_flow
        * SOX_MOLECULAR_WEIGHT_GRAMS
        / (MOLAR_VOLUME_LITERS_PER_MOL * 1_000_000)
    )
    rows["dust_tsp"] = rows["dust_mg_sm3"] * estimated_flow / 1_000_000
    rows["component_count"] = pd.array([pd.NA] * len(rows), dtype="Int64")
    rows["_is_estimated"] = True
    return rows[
        ["date", "generation_orgnm", "nox", "sox", "dust_tsp", "component_count", "_is_estimated"]
    ]


def clean_generation(generation_raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize and restrict generation to boundaries represented by emissions data."""
    source = generation_raw.copy()
    source = source[source["orgnm"].isin(BOUNDARY_METADATA)].copy()
    if not source["hokinm"].astype("string").eq("소계").all():
        unexpected = sorted(source.loc[source["hokinm"].ne("소계"), "hokinm"].unique())
        raise ValueError(f"Unexpected Midland generation unit labels: {unexpected}")
    source["date"] = pd.to_datetime(source["ym"].astype("string"), format="%Y%m", errors="raise")
    if source.duplicated(["date", "orgnm"]).any():
        raise ValueError("Midland generation contains duplicate plant/technology months.")
    source["energy_generated_mwh"] = pd.to_numeric(source["qvodgen"], errors="coerce")
    source["energy_capacity_mw"] = pd.to_numeric(source["capacity"], errors="coerce")
    return source[
        ["date", "orgnm", "energy_generated_mwh", "energy_capacity_mw", "gennm", "hokinm"]
    ].rename(columns={"orgnm": "generation_orgnm"})


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


def clean_midland_power(
    facility_raw: pd.DataFrame,
    generation_raw: pd.DataFrame,
    aggregate_raw: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return joined Midland monthly generation and derived mass in the shared schema.

    When ``aggregate_raw`` is provided the cleaner also estimates historical
    Incheon combined-cycle emissions (2012 onward) from monthly average
    concentrations scaled by a flow proxy from the 2024-2025 odcloud data.
    These rows are appended before the generation join and are marked in
    ``original_korean_note`` as approximate.
    """
    validate_source_columns(facility_raw, generation_raw)
    odcloud_emissions = build_monthly_emissions(facility_raw)
    odcloud_emissions["_is_estimated"] = False

    if aggregate_raw is not None:
        proxy = compute_incheon_flow_proxy(facility_raw, generation_raw)
        exclude_dates = set(
            odcloud_emissions.loc[odcloud_emissions["generation_orgnm"] == "인천복합", "date"]
        )
        historical = build_aggregate_incheon_emissions(
            aggregate_raw, proxy, generation_raw, exclude_dates
        )
        emissions = (
            pd.concat([historical, odcloud_emissions], ignore_index=True)
            if not historical.empty
            else odcloud_emissions
        )
    else:
        emissions = odcloud_emissions

    generation = clean_generation(generation_raw)
    joined = emissions.merge(
        generation, on=["date", "generation_orgnm"], how="left", validate="one_to_one"
    )
    missing_generation = joined["energy_generated_mwh"].isna()
    metadata = joined["generation_orgnm"].map(BOUNDARY_METADATA)
    plant_name = metadata.map(lambda item: item["plant_name"])
    reporting_label = metadata.map(lambda item: item["reporting_label"])
    fuel_type = metadata.map(lambda item: item["fuel_type"])

    first_activity = joined["date"].groupby(joined["generation_orgnm"]).transform("min")
    row_status = missing_generation.map({True: "active_partial", False: "active_reported"})
    row_status_basis = missing_generation.map(
        {
            True: "derived_pollutants_without_matching_generation",
            False: "generation_and_derived_pollutants_reported",
        }
    )
    note = joined["_is_estimated"].map({True: PROXY_NOTE, False: DERIVATION_NOTE})
    cleaned = pd.DataFrame(
        {
            "date": joined["date"],
            "plant_name": plant_name,
            # Generation is a plant/technology subtotal, not a numbered unit.
            "plant_number": pd.Series(pd.NA, index=joined.index, dtype="Int64"),
            "plant_opening_date": pd.Series(pd.NaT, index=joined.index),
            "plant_closing_date": pd.Series(pd.NaT, index=joined.index),
            "plant_latitude": pd.Series(pd.NA, index=joined.index, dtype="Float64"),
            "plant_longitude": pd.Series(pd.NA, index=joined.index, dtype="Float64"),
            "subsidiary_company": SUBSIDIARY_COMPANY,
            "fuel_type": fuel_type,
            "energy_generated_mwh": joined["energy_generated_mwh"],
            "energy_capacity_mw": joined["energy_capacity_mw"],
            "reporting_unit_id": REPORTING_ID_PREFIX
            + ":"
            + joined["generation_orgnm"].astype("string"),
            "reporting_start_date": first_activity,
            "reporting_end_date": pd.Series(pd.NaT, index=joined.index),
            "reporting_window_basis": "first_derived_emissions_activity",
            "observation_level": "generation_block",
            "component_count": joined["component_count"],
            "generation_source": GENERATION_SOURCE,
            "generation_coverage_status": missing_generation.map(
                {True: "missing", False: "reported"}
            ),
            "row_status": row_status,
            "row_status_basis": row_status_basis,
            "nox": joined["nox"],
            "sox": joined["sox"],
            "dust_tsp": joined["dust_tsp"],
            "pollutant_data_pattern": pollutant_pattern(joined),
            "pollutant_measurement_basis": "mass",
            "nox_unit": "kilograms",
            "sox_unit": "kilograms",
            "dust_tsp_unit": "kilograms",
            "emissions_mass_unit": "kilograms",
            "original_korean_plant_name": joined["generation_orgnm"],
            "original_korean_unit_name": reporting_label,
            "original_korean_note": note,
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
    ]:
        cleaned[column] = cleaned[column].astype("Float64")
    cleaned["component_count"] = cleaned["component_count"].astype("Int64")
    string_columns = cleaned.select_dtypes(include=["object", "string"]).columns
    cleaned[string_columns] = cleaned[string_columns].astype("string")
    return apply_technology_mapping(apply_location_crosswalk(cleaned)).sort_values(
        ["date", "plant_name", "original_korean_unit_name"], ignore_index=True
    )


def load_and_clean(
    facility_input_path: Path,
    generation_input_path: Path,
    aggregate_input_path: Path | None = None,
) -> pd.DataFrame:
    facility_raw = pd.read_csv(facility_input_path, low_memory=False)
    generation_raw = pd.read_csv(generation_input_path, encoding="utf-8-sig")
    aggregate_raw = (
        pd.read_csv(aggregate_input_path, encoding="utf-8-sig")
        if aggregate_input_path is not None and aggregate_input_path.exists()
        else None
    )
    return clean_midland_power(facility_raw, generation_raw, aggregate_raw)


def save_cleaned(data: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(output_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facility-input-path", type=Path, default=DEFAULT_FACILITY_INPUT_PATH)
    parser.add_argument(
        "--generation-input-path", type=Path, default=DEFAULT_GENERATION_INPUT_PATH
    )
    parser.add_argument(
        "--aggregate-input-path",
        type=Path,
        default=DEFAULT_AGGREGATE_INPUT_PATH,
        help="Monthly aggregate concentration CSV for historical Incheon back-fill. "
        "Pass an empty string or a non-existent path to skip.",
    )
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cleaned = load_and_clean(
        args.facility_input_path,
        args.generation_input_path,
        args.aggregate_input_path,
    )
    save_cleaned(cleaned, args.output_path)
    print(f"Saved {len(cleaned)} cleaned rows to {args.output_path}")
    print(f"Monthly coverage: {cleaned['date'].min():%Y-%m} to {cleaned['date'].max():%Y-%m}")
    matched = cleaned["energy_generated_mwh"].notna().sum()
    print(f"Matched monthly generation for {matched}/{len(cleaned)} reporting-boundary rows.")
    estimated = cleaned["original_korean_note"].str.startswith("Monthly NOx mass estimated").sum()
    if estimated:
        print(f"  of which {estimated} rows use the Incheon aggregate proxy back-fill.")


if __name__ == "__main__":
    main()
