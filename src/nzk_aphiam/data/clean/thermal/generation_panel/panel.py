"""Monthly generation and capacity panel for all KEPCO thermal subsidiaries.

Aggregates the generation-side raw data for each of the five KEPCO thermal
subsidiaries into per-subsidiary CSVs and one combined flat file.  No emissions
data is read; this panel is intended for macro modelling and capacity analysis.

The schema is intentionally narrow:

    date, subsidiary_company, plant_name, plant_number, reporting_unit_id,
    observation_level, fuel_type, energy_generated_mwh, energy_capacity_mw,
    component_count, original_korean_name

Location data (lat/lon, opening/closing dates) is not included here because
the crosswalk does not cover every plant in the generation CSVs.  Teammates can
join docs/references/crosswalk/plant_location_dates.csv on
(subsidiary_company, plant_name) to add coordinates.

Run from the project root:

    make build-generation-panel
    # or
    PYTHONPATH=src python -m nzk_aphiam.data.clean.thermal.generation_panel
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nzk_aphiam.data.clean.thermal.eastwest_power.cleaner import (
    load_and_clean as _ew_load_and_clean,
)
from nzk_aphiam.data.clean.thermal.southern_power.cleaner import (
    SITE_RULES as _SP_SITE_RULES,
)
from nzk_aphiam.data.clean.thermal.southern_power.cleaner import (
    aggregate_generation as _sp_aggregate_generation,
)
from nzk_aphiam.data.clean.thermal.western_power.cleaner import (
    load_and_clean as _wp_load_and_clean,
)

PROJECT_ROOT = Path(__file__).resolve().parents[6]

GENERATION_PANEL_COLUMNS = [
    "date",
    "subsidiary_company",
    "plant_name",
    "plant_number",
    "reporting_unit_id",
    "observation_level",
    "fuel_type",
    "energy_generated_mwh",
    "energy_capacity_mw",
    "component_count",
    "original_korean_name",
]

# ---- Default input paths ---------------------------------------------------

DEFAULT_EW_INPUT = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "eastwest_power"
    / "eastwest_power_air_pollutants_generation.csv"
)
DEFAULT_WP_INPUT = (
    PROJECT_ROOT / "data" / "raw" / "western_power" / "western_power_air_pollutants_generation.csv"
)
DEFAULT_SP_GENERATION_INPUT = (
    PROJECT_ROOT / "data" / "raw" / "southern_power" / "southern_power_daily_generation.csv"
)
DEFAULT_SE_GENERATION_INPUT = (
    PROJECT_ROOT / "data" / "raw" / "southeast_power" / "southeast_power_monthly_generation.csv"
)
DEFAULT_MP_GENERATION_INPUT = (
    PROJECT_ROOT / "data" / "raw" / "midland_power" / "midland_power_monthly_generation.csv"
)
DEFAULT_KHNP_GENERATION_INPUT = (
    PROJECT_ROOT / "data" / "raw" / "khnp" / "khnp_daily_generation.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "kepco" / "generation"


# ---- East-West Power -------------------------------------------------------


def build_eastwest_generation(input_path: Path) -> pd.DataFrame:
    """Extract generation rows from the combined East-West source CSV."""
    cleaned = _ew_load_and_clean(input_path)
    gen = cleaned[cleaned["generation_coverage_status"] == "reported"].copy()
    return pd.DataFrame(
        {
            "date": gen["date"],
            "subsidiary_company": gen["subsidiary_company"],
            "plant_name": gen["plant_name"],
            "plant_number": gen["plant_number"].astype("Int64"),
            "reporting_unit_id": gen["reporting_unit_id"],
            "observation_level": gen["observation_level"],
            "fuel_type": gen["fuel_type"],
            "energy_generated_mwh": gen["energy_generated_mwh"].astype("Float64"),
            "energy_capacity_mw": gen["energy_capacity_mw"].astype("Float64"),
            "component_count": gen["component_count"].astype("Int64"),
            "original_korean_name": gen["original_korean_plant_name"],
        },
        columns=GENERATION_PANEL_COLUMNS,
    )


# ---- Western Power ---------------------------------------------------------


def build_western_generation(input_path: Path) -> pd.DataFrame:
    """Extract generation rows from the combined Western source CSV."""
    cleaned = _wp_load_and_clean(input_path)
    gen = cleaned[cleaned["generation_coverage_status"] == "reported"].copy()
    return pd.DataFrame(
        {
            "date": gen["date"],
            "subsidiary_company": gen["subsidiary_company"],
            "plant_name": gen["plant_name"],
            "plant_number": gen["plant_number"].astype("Int64"),
            "reporting_unit_id": gen["reporting_unit_id"],
            "observation_level": gen["observation_level"],
            "fuel_type": gen["fuel_type"],
            "energy_generated_mwh": gen["energy_generated_mwh"].astype("Float64"),
            "energy_capacity_mw": gen["energy_capacity_mw"].astype("Float64"),
            "component_count": gen["component_count"].astype("Int64"),
            "original_korean_name": gen["original_korean_plant_name"],
        },
        columns=GENERATION_PANEL_COLUMNS,
    )


# ---- Southern Power --------------------------------------------------------

_SP_PLANT_FUEL_TYPE: dict[str, str] = {
    plant_name: fuel_type for _, (plant_name, fuel_type, _) in _SP_SITE_RULES.items()
}

_SP_OBSERVATION_LEVEL: dict[str, str] = {
    plant_name: (
        "plant"
        if plant_name in {"Andong", "Hallim", "Namjeju Combined", "Shinsejong"}
        else "gas_turbine"
        if plant_name in {"Busan", "Shin-Incheon", "Yeongwol"}
        else "generating_unit"
    )
    for plant_name in _SP_PLANT_FUEL_TYPE
}


def build_southern_generation(generation_path: Path) -> pd.DataFrame:
    """Aggregate Southern Power daily generation to monthly and standardize."""
    raw = pd.read_csv(
        generation_path,
        encoding="utf-8-sig",
        dtype="string",
    )
    monthly = _sp_aggregate_generation(raw)
    if monthly.empty:
        return pd.DataFrame(columns=GENERATION_PANEL_COLUMNS)

    plant = monthly["plant_name"].astype("string")
    number_str = monthly["plant_number"].astype("Int64").astype("string").fillna("all")
    return pd.DataFrame(
        {
            "date": monthly["date"],
            "subsidiary_company": "Korea Southern Power",
            "plant_name": plant,
            "plant_number": monthly["plant_number"].astype("Int64"),
            "reporting_unit_id": ("southern_power:" + plant + ":" + number_str).astype("string"),
            "observation_level": plant.map(_SP_OBSERVATION_LEVEL).astype("string"),
            "fuel_type": plant.map(_SP_PLANT_FUEL_TYPE).astype("string"),
            "energy_generated_mwh": monthly["energy_generated_mwh"].astype("Float64"),
            "energy_capacity_mw": monthly["energy_capacity_mw"].astype("Float64"),
            "component_count": monthly["component_count"].astype("Int64"),
            "original_korean_name": pd.array([pd.NA] * len(monthly), dtype="string"),
        },
        columns=GENERATION_PANEL_COLUMNS,
    )


# ---- South-East Power ------------------------------------------------------

_SE_THERMAL_PLANTS = {"분당", "삼천포", "여수", "영동", "영흥"}
_SE_PLANT_NAMES: dict[str, str] = {
    "분당": "Bundang",
    "삼천포": "Samcheonpo",
    "여수": "Yeosu",
    "영동": "Yeongdong",
    "영흥": "Yeongheung",
}
_SE_FUEL_TYPES: dict[str, str] = {
    "석탄": "coal",
    "국내탄": "coal",
    "복합": "natural_gas",
    "바이오매스": "biomass",
    "중유": "oil",
    "기타": "other",
}


def build_southeast_generation(generation_path: Path) -> pd.DataFrame:
    """Parse the KOEN monthly generation CSV and return thermal-fleet rows."""
    raw = pd.read_csv(generation_path, encoding="utf-8-sig", dtype={"호기": "string"})
    source = raw[raw["사업소"].isin(_SE_THERMAL_PLANTS)].copy()
    if source.empty:
        return pd.DataFrame(columns=GENERATION_PANEL_COLUMNS)

    source["date"] = pd.to_datetime(source["일자"].astype(str), format="%Y%m")
    plant_name = source["사업소"].map(_SE_PLANT_NAMES).astype("string")
    unit_id = source["호기"].astype("string")
    return pd.DataFrame(
        {
            "date": source["date"],
            "subsidiary_company": "Korea South-East Power",
            "plant_name": plant_name,
            "plant_number": (unit_id.str.extract(r"(\d+)", expand=False).astype("Int64")),
            "reporting_unit_id": ("southeast_power:" + plant_name + ":" + unit_id).astype(
                "string"
            ),
            "observation_level": "generating_unit",
            "fuel_type": (source["발전원"].map(_SE_FUEL_TYPES).fillna("other").astype("string")),
            "energy_generated_mwh": (
                pd.to_numeric(source["발전량(MWh)"], errors="coerce").astype("Float64")
            ),
            "energy_capacity_mw": (
                pd.to_numeric(source["용량(MW)"], errors="coerce").astype("Float64")
            ),
            "component_count": pd.array([pd.NA] * len(source), dtype="Int64"),
            "original_korean_name": source["사업소"].astype("string"),
        },
        columns=GENERATION_PANEL_COLUMNS,
    )


# ---- Midland Power ---------------------------------------------------------

_MP_THERMAL_GENNM = {"가스", "국내탄", "내연", "복합", "석탄", "중유"}
_MP_PLANT_NAMES: dict[str, str] = {
    "인천기력": "Incheon",
    "인천복합": "Incheon",
    "제주기력": "Jeju",
    "제주내연": "Jeju",
    "제주복합": "Jeju",
    "세종천연가스": "Sejong",
    "신서천화력": "Shin-Seocheon",
    "서울화력": "Seoul",
    "서울복합": "Seoul",
    "보령기력": "Boryeong",
    "보령복합": "Boryeong",
    "신보령기력": "Shin-Boryeong",
    "서천화력": "Old-Seocheon",
}
_MP_FUEL_TYPES: dict[str, str] = {
    "가스": "natural_gas",
    "복합": "natural_gas",
    "국내탄": "coal",
    "석탄": "coal",
    "내연": "oil",
    "중유": "oil",
}


def build_midland_generation(generation_path: Path) -> pd.DataFrame:
    """Parse the KOMIPO monthly generation CSV and return thermal-fleet rows."""
    raw = pd.read_csv(generation_path, encoding="utf-8-sig")
    source = raw[raw["gennm"].isin(_MP_THERMAL_GENNM) & raw["orgnm"].isin(_MP_PLANT_NAMES)].copy()
    if source.empty:
        return pd.DataFrame(columns=GENERATION_PANEL_COLUMNS)

    source["date"] = pd.to_datetime(source["ym"].astype(str), format="%Y%m")
    orgnm = source["orgnm"].astype("string")
    plant_name = orgnm.map(_MP_PLANT_NAMES).astype("string")
    return pd.DataFrame(
        {
            "date": source["date"],
            "subsidiary_company": "Korea Midland Power",
            "plant_name": plant_name,
            "plant_number": pd.array([pd.NA] * len(source), dtype="Int64"),
            "reporting_unit_id": ("midland_power:" + orgnm).astype("string"),
            "observation_level": "generation_block",
            "fuel_type": (source["gennm"].map(_MP_FUEL_TYPES).fillna("other").astype("string")),
            "energy_generated_mwh": (
                pd.to_numeric(source["qvodgen"], errors="coerce").astype("Float64")
            ),
            "energy_capacity_mw": (
                pd.to_numeric(source["capacity"], errors="coerce").astype("Float64")
            ),
            "component_count": pd.array([pd.NA] * len(source), dtype="Int64"),
            "original_korean_name": orgnm,
        },
        columns=GENERATION_PANEL_COLUMNS,
    )


# ---- Korea Hydro & Nuclear Power ------------------------------------------

_KHNP_FUEL_TYPES: dict[str, str] = {
    "원자력": "nuclear",
    "수력": "hydro",
    "양수": "pumped_storage",
    "태양광": "renewable",
    "풍력": "renewable",
    "신재생": "renewable",
}
_KHNP_PLANT_NAMES: dict[str, str] = {
    "고리": "Kori",
    "신고리": "Shin-Kori",
    "새울": "Saeul",
    "월성": "Wolsong",
    "신월성": "Shin-Wolsong",
    "한빛": "Hanbit",
    "한울": "Hanul",
    "신한울": "Shin-Hanul",
    "화천": "Hwacheon",
    "춘천": "Chuncheon",
    "의암": "Uiam",
    "청평": "Cheongpyeong",
    "팔당": "Paldang",
    "괴산": "Goesan",
    "칠보": "Chilbo",
    "보성강": "Boseonggang",
    "강림": "Gangnim",
    "무주양수": "Muju Pumped Storage",
    "예천양수": "Yecheon Pumped Storage",
    "삼랑진양수": "Samrangjin Pumped Storage",
    "청평양수": "Cheongpyeong Pumped Storage",
    "양양양수": "Yangyang Pumped Storage",
    "청송양수": "Cheongsong Pumped Storage",
    "산청양수": "Sancheong Pumped Storage",
}


def build_khnp_generation(generation_path: Path) -> pd.DataFrame:
    """Aggregate KHNP's daily hourly generator records into monthly MWh."""
    raw = pd.read_csv(generation_path, encoding="utf-8-sig", dtype="string")
    hour_columns = [column for column in raw if column.startswith("qt_")]
    required = {"tradeDt", "genCd", "genNm", "resourceType"}
    missing = required - set(raw.columns)
    if missing or not hour_columns:
        detail = sorted(missing) if missing else ["qt_<hour> fields"]
        raise ValueError(f"KHNP generation CSV is missing required columns: {detail}")

    source = raw[raw["resourceType"].isin(_KHNP_FUEL_TYPES)].copy()
    if source.empty:
        return pd.DataFrame(columns=GENERATION_PANEL_COLUMNS)
    source["date"] = (
        pd.to_datetime(source["tradeDt"], format="%Y%m%d").dt.to_period("M").dt.start_time
    )
    # The qt_* fields are hourly energy in kWh; sum them and convert to MWh.
    source["daily_mwh"] = (
        source[hour_columns].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1) / 1000
    )
    keys = ["date", "genCd", "genNm", "resourceType"]
    monthly = source.groupby(keys, as_index=False, dropna=False)["daily_mwh"].sum(min_count=1)

    korean_name = monthly["genNm"].astype("string")
    base_name = korean_name.str.replace(r"#\d+$", "", regex=True)
    translated = base_name.map(_KHNP_PLANT_NAMES)
    plant_name = translated.fillna(korean_name).astype("string")
    plant_number = korean_name.str.extract(r"#(\d+)$", expand=False).astype("Int64")
    return pd.DataFrame(
        {
            "date": monthly["date"],
            "subsidiary_company": "Korea Hydro & Nuclear Power",
            "plant_name": plant_name,
            "plant_number": plant_number,
            "reporting_unit_id": ("khnp:" + monthly["genCd"].astype("string")),
            "observation_level": "generating_unit",
            "fuel_type": monthly["resourceType"].map(_KHNP_FUEL_TYPES).astype("string"),
            "energy_generated_mwh": monthly["daily_mwh"].astype("Float64"),
            "energy_capacity_mw": pd.array([pd.NA] * len(monthly), dtype="Float64"),
            "component_count": pd.array([1] * len(monthly), dtype="Int64"),
            "original_korean_name": korean_name,
        },
        columns=GENERATION_PANEL_COLUMNS,
    )


# ---- Panel builder ---------------------------------------------------------


def build_panel(
    ew_input: Path = DEFAULT_EW_INPUT,
    wp_input: Path = DEFAULT_WP_INPUT,
    sp_generation_input: Path = DEFAULT_SP_GENERATION_INPUT,
    se_generation_input: Path = DEFAULT_SE_GENERATION_INPUT,
    mp_generation_input: Path = DEFAULT_MP_GENERATION_INPUT,
    khnp_generation_input: Path = DEFAULT_KHNP_GENERATION_INPUT,
) -> dict[str, pd.DataFrame]:
    """Return per-subsidiary DataFrames keyed by slug name."""
    return {
        "eastwest_power": build_eastwest_generation(ew_input),
        "western_power": build_western_generation(wp_input),
        "southern_power": build_southern_generation(sp_generation_input),
        "southeast_power": build_southeast_generation(se_generation_input),
        "midland_power": build_midland_generation(mp_generation_input),
        "khnp": build_khnp_generation(khnp_generation_input),
    }


def save_panel(frames: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        path = output_dir / f"{name}_monthly_generation.csv"
        df.to_csv(path, index=False, encoding="utf-8")
        print(
            f"  {name}: {len(df):,} rows  "
            f"{df['date'].min():%Y-%m} – {df['date'].max():%Y-%m}  → {path.name}"
        )
    combined = pd.concat(list(frames.values()), ignore_index=True)
    combined_path = output_dir / "kepco_subsidiaries_monthly_generation.csv"
    combined.to_csv(combined_path, index=False, encoding="utf-8")
    print(f"\nCombined: {len(combined):,} rows → {combined_path.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ew-input", type=Path, default=DEFAULT_EW_INPUT)
    parser.add_argument("--wp-input", type=Path, default=DEFAULT_WP_INPUT)
    parser.add_argument("--sp-generation-input", type=Path, default=DEFAULT_SP_GENERATION_INPUT)
    parser.add_argument("--se-generation-input", type=Path, default=DEFAULT_SE_GENERATION_INPUT)
    parser.add_argument("--mp-generation-input", type=Path, default=DEFAULT_MP_GENERATION_INPUT)
    parser.add_argument(
        "--khnp-generation-input", type=Path, default=DEFAULT_KHNP_GENERATION_INPUT
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print("Building KEPCO subsidiaries monthly generation panel...")
    frames = build_panel(
        ew_input=args.ew_input,
        wp_input=args.wp_input,
        sp_generation_input=args.sp_generation_input,
        se_generation_input=args.se_generation_input,
        mp_generation_input=args.mp_generation_input,
        khnp_generation_input=args.khnp_generation_input,
    )
    save_panel(frames, args.output_dir)


if __name__ == "__main__":
    main()
