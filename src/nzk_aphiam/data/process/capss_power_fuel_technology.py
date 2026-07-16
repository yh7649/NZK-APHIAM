"""Export CAPSS power-sector emissions by fuel and official technology."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from nzk_aphiam.config.paths import CAPSS_INTERIM_DIR, PROCESSED_DIR, PROJECT_ROOT

DEFAULT_INPUT = CAPSS_INTERIM_DIR / "emissions_statistics" / "capss_emissions_tidy.parquet"
DEFAULT_RAW_METADATA = (
    PROJECT_ROOT / "data" / "raw" / "capss" / "emissions_statistics" / "metadata.json"
)
DEFAULT_OUTPUT_DIR = PROCESSED_DIR / "capss"
DEFAULT_TABLE_DIR = PROJECT_ROOT / "results" / "tables" / "capss"
DEFAULT_DIAGNOSTIC_DIR = PROJECT_ROOT / "results" / "diagnostics" / "capss"

POWER_SOURCE_CATEGORY = "에너지산업 연소"
POWER_MIDCATEGORIES = ("공공발전시설", "민간발전시설")
POLLUTANT_ORDER = ("CO", "NOx", "SOx", "TSP", "PM10", "PM2.5", "VOCs", "NH3", "BC")
PRESENTATION_POLLUTANTS = ("CO", "NOx", "SOx", "TSP", "PM10", "PM2.5", "VOC", "NH3", "BC")

FACILITY_CLASS_EN = {
    "공공발전시설": "Public power-generation facilities",
    "민간발전시설": "Private power-generation facilities",
}
TECHNOLOGY_EN = {
    "1,2,3종(보일러)": "Boiler, Classes 1-3",
    "가스터빈": "Gas turbine",
    "내연기관": "Internal-combustion engine",
}
FUEL_MAJOR_EN = {
    "유연탄": "Bituminous coal",
    "무연탄": "Anthracite",
    "LNG": "LNG",
    "B-C유": "Bunker C oil",
}
KEY_FUEL_TECHNOLOGIES = (
    ("유연탄", "1,2,3종(보일러)"),
    ("무연탄", "1,2,3종(보일러)"),
    ("LNG", "가스터빈"),
    ("LNG", "1,2,3종(보일러)"),
    ("B-C유", "내연기관"),
)
REFERENCE_2021_TONNES = {
    ("유연탄", "1,2,3종(보일러)", "CO"): 20631.7,
    ("유연탄", "1,2,3종(보일러)", "NOx"): 25038.3,
    ("유연탄", "1,2,3종(보일러)", "SOx"): 25108.5,
    ("유연탄", "1,2,3종(보일러)", "TSP"): 1857.7,
    ("유연탄", "1,2,3종(보일러)", "PM2.5"): 1430.1,
    ("무연탄", "1,2,3종(보일러)", "CO"): 269.9,
    ("무연탄", "1,2,3종(보일러)", "NOx"): 428.9,
    ("무연탄", "1,2,3종(보일러)", "SOx"): 1270.4,
    ("무연탄", "1,2,3종(보일러)", "TSP"): 18.7,
    ("무연탄", "1,2,3종(보일러)", "PM2.5"): 5.7,
    ("LNG", "가스터빈", "CO"): 36866.1,
    ("LNG", "가스터빈", "NOx"): 12168.5,
    ("LNG", "가스터빈", "SOx"): 238.0,
    ("LNG", "가스터빈", "TSP"): 836.2,
    ("LNG", "가스터빈", "PM2.5"): 836.2,
    ("LNG", "1,2,3종(보일러)", "CO"): 1814.2,
    ("LNG", "1,2,3종(보일러)", "NOx"): 1283.8,
    ("LNG", "1,2,3종(보일러)", "SOx"): 76.2,
    ("LNG", "1,2,3종(보일러)", "TSP"): 31.2,
    ("LNG", "1,2,3종(보일러)", "PM2.5"): 31.2,
    ("B-C유", "내연기관", "CO"): 546.5,
    ("B-C유", "내연기관", "NOx"): 433.5,
    ("B-C유", "내연기관", "SOx"): 15.7,
    ("B-C유", "내연기관", "TSP"): 8.7,
    ("B-C유", "내연기관", "PM2.5"): 1.9,
}


def _write_table(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        data.to_parquet(path, index=False)
    else:
        data.to_csv(path, index=False, encoding="utf-8")


def _load_source_metadata(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["year", "source_page_url", "source_attachment_url"])
    metadata = json.loads(path.read_text(encoding="utf-8"))
    records = pd.DataFrame(metadata.get("records", []))
    if records.empty:
        return pd.DataFrame(columns=["year", "source_page_url", "source_attachment_url"])
    return records.rename(
        columns={"article_url": "source_page_url", "download_url": "source_attachment_url"}
    )[["year", "source_page_url", "source_attachment_url"]]


def filter_power_sector(capss: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    required = {
        "year",
        "source_category_ko",
        "source_midcategory_ko",
        "source_subcategory_ko",
        "fuel_category_ko",
        "fuel_type_ko",
        "pollutant",
        "emissions_kg",
    }
    missing = required - set(capss.columns)
    if missing:
        raise ValueError(f"CAPSS tidy data is missing required columns: {sorted(missing)}")
    filtered = capss.loc[
        capss["year"].between(start_year, end_year)
        & (capss["source_category_ko"] == POWER_SOURCE_CATEGORY)
        & capss["source_midcategory_ko"].isin(POWER_MIDCATEGORIES)
    ].copy()
    filtered["emissions_kg"] = pd.to_numeric(filtered["emissions_kg"], errors="coerce")
    if filtered["emissions_kg"].isna().any():
        raise ValueError("Filtered CAPSS power data contains nonnumeric emissions_kg values.")
    return filtered


def add_labels(data: pd.DataFrame) -> pd.DataFrame:
    labeled = data.copy()
    labeled["power_facility_class_ko"] = labeled["source_midcategory_ko"]
    labeled["power_facility_class_en"] = labeled["source_midcategory_ko"].map(FACILITY_CLASS_EN)
    labeled["technology_official_ko"] = labeled["source_subcategory_ko"]
    labeled["technology_en"] = labeled["source_subcategory_ko"].map(TECHNOLOGY_EN)
    labeled["fuel_major_ko"] = labeled["fuel_category_ko"]
    labeled["fuel_major_en"] = labeled["fuel_category_ko"].map(FUEL_MAJOR_EN)
    labeled["fuel_minor_ko"] = labeled["fuel_type_ko"]
    return labeled


def aggregate_detailed(power: pd.DataFrame, source_metadata: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "year",
        "source_midcategory_ko",
        "source_subcategory_ko",
        "fuel_category_ko",
        "fuel_type_ko",
        "pollutant",
    ]
    detailed = power.groupby(keys, dropna=False, as_index=False)["emissions_kg"].sum()
    detailed = add_labels(detailed)
    detailed["emissions_tonnes"] = detailed["emissions_kg"] / 1000.0
    detailed = detailed.merge(source_metadata, on="year", how="left")
    return detailed[
        [
            "year",
            "power_facility_class_ko",
            "power_facility_class_en",
            "technology_official_ko",
            "technology_en",
            "fuel_major_ko",
            "fuel_major_en",
            "fuel_minor_ko",
            "pollutant",
            "emissions_kg",
            "emissions_tonnes",
            "source_page_url",
            "source_attachment_url",
        ]
    ].sort_values(
        [
            "year",
            "power_facility_class_ko",
            "technology_official_ko",
            "fuel_major_ko",
            "fuel_minor_ko",
            "pollutant",
        ],
        kind="stable",
    )


def aggregate_combined(detailed: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "year",
        "technology_official_ko",
        "technology_en",
        "fuel_major_ko",
        "fuel_major_en",
        "pollutant",
        "source_page_url",
        "source_attachment_url",
    ]
    combined = detailed.groupby(keys, dropna=False, as_index=False)["emissions_kg"].sum()
    combined["emissions_tonnes"] = combined["emissions_kg"] / 1000.0
    return combined[
        [
            "year",
            "technology_official_ko",
            "technology_en",
            "fuel_major_ko",
            "fuel_major_en",
            "pollutant",
            "emissions_kg",
            "emissions_tonnes",
            "source_page_url",
            "source_attachment_url",
        ]
    ].sort_values(["year", "technology_official_ko", "fuel_major_ko", "pollutant"])


def pivot_pollutants(
    data: pd.DataFrame, *, value_column: str, suffix: str, include_source_url: bool
) -> pd.DataFrame:
    frame = data.copy()
    frame["pollutant_column"] = frame["pollutant"].replace({"VOCs": "VOC"}) + suffix
    keys = ["year", "technology_official_ko", "technology_en", "fuel_major_ko", "fuel_major_en"]
    if include_source_url:
        frame["source_url"] = frame["source_page_url"]
        keys.append("source_url")
    wide = (
        frame.pivot_table(
            index=keys,
            columns="pollutant_column",
            values=value_column,
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
        .rename_axis(columns=None)
    )
    columns = [*keys, *[f"{pollutant}{suffix}" for pollutant in PRESENTATION_POLLUTANTS]]
    for column in columns:
        if column not in wide:
            wide[column] = 0.0
    return wide[columns].sort_values(keys)


def build_key_table(combined: pd.DataFrame) -> pd.DataFrame:
    key = combined.merge(
        pd.DataFrame(KEY_FUEL_TECHNOLOGIES, columns=["fuel_major_ko", "technology_official_ko"]),
        on=["fuel_major_ko", "technology_official_ko"],
        how="inner",
    )
    return pivot_pollutants(
        key, value_column="emissions_tonnes", suffix="_t", include_source_url=False
    )


def unmapped_labels(power: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column, mapping, label in [
        ("source_midcategory_ko", FACILITY_CLASS_EN, "power_facility_class"),
        ("source_subcategory_ko", TECHNOLOGY_EN, "technology"),
        ("fuel_category_ko", FUEL_MAJOR_EN, "fuel_major"),
    ]:
        counts = power[column].value_counts(dropna=False).reset_index()
        counts.columns = ["label_ko", "row_count"]
        counts["label_type"] = label
        counts["mapping_status"] = (
            counts["label_ko"].map(mapping).notna().map({True: "mapped", False: "unmapped"})
        )
        rows.append(counts)
    return pd.concat(rows, ignore_index=True)[
        ["label_type", "label_ko", "mapping_status", "row_count"]
    ].sort_values(["label_type", "mapping_status", "label_ko"])


def validate_outputs(
    *,
    power: pd.DataFrame,
    detailed: pd.DataFrame,
    combined: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    checks: list[dict[str, object]] = []

    def add(check: str, passed: bool, observed: object = "", expected: object = "") -> None:
        checks.append(
            {"check": check, "passed": bool(passed), "observed": observed, "expected": expected}
        )

    detailed_keys = [
        "year",
        "power_facility_class_ko",
        "technology_official_ko",
        "fuel_major_ko",
        "fuel_minor_ko",
        "pollutant",
    ]
    combined_keys = ["year", "technology_official_ko", "fuel_major_ko", "pollutant"]
    add("detailed_keys_unique", not detailed.duplicated(detailed_keys).any())
    add("combined_keys_unique", not combined.duplicated(combined_keys).any())
    add("no_negative_emissions", not (detailed["emissions_kg"] < 0).any())
    add(
        "tonnes_equal_kg_div_1000",
        (detailed["emissions_tonnes"] - detailed["emissions_kg"] / 1000.0).abs().max() < 1e-9,
    )
    detailed_to_combined = detailed.groupby(combined_keys, dropna=False)["emissions_kg"].sum()
    combined_totals = combined.set_index(combined_keys)["emissions_kg"].sort_index()
    add(
        "detailed_totals_equal_combined",
        detailed_to_combined.sort_index().round(9).equals(combined_totals.round(9)),
    )
    add(
        "source_urls_populated",
        detailed[["source_page_url", "source_attachment_url"]].notna().all().all(),
    )
    add(
        "inventory_years_populated",
        set(range(start_year, end_year + 1)).issubset(set(detailed["year"])),
    )
    add(
        "power_filter_satisfied",
        bool(
            (power["source_category_ko"] == POWER_SOURCE_CATEGORY).all()
            and power["source_midcategory_ko"].isin(POWER_MIDCATEGORIES).all()
        ),
    )

    reference_rows = []
    actual_2021 = combined.loc[combined["year"] == 2021].set_index(
        ["fuel_major_ko", "technology_official_ko", "pollutant"]
    )["emissions_tonnes"]
    for key, expected in REFERENCE_2021_TONNES.items():
        observed = float(actual_2021.get(key, float("nan")))
        passed = pd.notna(observed) and abs(observed - expected) <= 0.15
        reference_rows.append(passed)
        add(
            f"reference_2021_{key[0]}_{key[1]}_{key[2]}",
            passed,
            round(observed, 6) if pd.notna(observed) else "",
            expected,
        )
    add("reference_2021_all_requested_values", all(reference_rows))
    return pd.DataFrame(checks)


def export_power_fuel_technology(
    *,
    input_path: Path = DEFAULT_INPUT,
    raw_metadata_path: Path = DEFAULT_RAW_METADATA,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    table_dir: Path = DEFAULT_TABLE_DIR,
    diagnostic_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
    start_year: int = 2016,
    end_year: int = 2023,
) -> dict[str, object]:
    capss = pd.read_parquet(input_path)
    source_metadata = _load_source_metadata(raw_metadata_path)
    power = filter_power_sector(capss, start_year, end_year)
    detailed = aggregate_detailed(power, source_metadata)
    combined = aggregate_combined(detailed)
    wide = pivot_pollutants(
        combined, value_column="emissions_kg", suffix="_kg", include_source_url=True
    )
    key = build_key_table(combined)
    labels = unmapped_labels(power)
    validation = validate_outputs(
        power=power, detailed=detailed, combined=combined, start_year=start_year, end_year=end_year
    )

    stem = f"{start_year}_{end_year}"
    _write_table(detailed, output_dir / f"power_fuel_technology_detailed_{stem}.parquet")
    _write_table(detailed, output_dir / f"power_fuel_technology_detailed_{stem}.csv")
    _write_table(combined, output_dir / f"power_fuel_technology_{stem}.parquet")
    _write_table(combined, output_dir / f"power_fuel_technology_{stem}.csv")
    _write_table(wide, output_dir / f"power_fuel_technology_{stem}_wide.csv")
    _write_table(key, table_dir / f"capss_key_fuel_technology_{stem}_tonnes.csv")
    _write_table(labels, diagnostic_dir / "power_fuel_technology_unmapped_labels.csv")
    _write_table(validation, diagnostic_dir / "power_fuel_technology_validation.csv")
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "raw_metadata_path": str(raw_metadata_path),
        "years": [start_year, end_year],
        "power_filter": {
            "source_category_ko": POWER_SOURCE_CATEGORY,
            "source_midcategory_ko": list(POWER_MIDCATEGORIES),
        },
        "row_counts": {
            "filtered_power_long": int(len(power)),
            "detailed": int(len(detailed)),
            "combined": int(len(combined)),
            "wide": int(len(wide)),
            "key_table": int(len(key)),
        },
        "validation_passed": bool(validation["passed"].all()),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"power_fuel_technology_{stem}.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--raw-metadata", type=Path, default=DEFAULT_RAW_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--table-dir", type=Path, default=DEFAULT_TABLE_DIR)
    parser.add_argument("--diagnostic-dir", type=Path, default=DEFAULT_DIAGNOSTIC_DIR)
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2023)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    metadata = export_power_fuel_technology(
        input_path=args.input,
        raw_metadata_path=args.raw_metadata,
        output_dir=args.output_dir,
        table_dir=args.table_dir,
        diagnostic_dir=args.diagnostic_dir,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    print(json.dumps(metadata["row_counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
