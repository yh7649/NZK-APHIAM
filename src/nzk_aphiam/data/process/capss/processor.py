"""Parse CAPSS detailed emissions workbooks into tidy long-form tables."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata

import pandas as pd

from nzk_aphiam.config.paths import CAPSS_INTERIM_DIR, CAPSS_RAW_DIR

EXPECTED_POLLUTANTS = ("TSP", "PM2.5", "PM10", "SOx", "NOx", "VOCs", "NH3", "CO", "BC")
POLLUTANT_ALIASES = {
    "PM-2.5": "PM2.5",
    "PM2.5": "PM2.5",
    "PM-10": "PM10",
    "PM10": "PM10",
    "VOC": "VOCs",
    "VOCs": "VOCs",
    "NOX": "NOx",
    "NOx": "NOx",
    "SOX": "SOx",
    "SOx": "SOx",
    "CO": "CO",
    "NH3": "NH3",
    "TSP": "TSP",
    "BC": "BC",
}
DESCRIPTOR_COLUMNS = {
    "시도": "province_name_ko",
    "시군구": "sub_district_name_ko",
    "배출원대분류": "source_category_ko",
    "배출원중분류": "source_midcategory_ko",
    "배출원소분류": "source_subcategory_ko",
    "연료대분류": "fuel_category_ko",
    "연료소분류": "fuel_type_ko",
}
OUTPUT_COLUMNS = [
    "year",
    "province_name_ko",
    "sub_district_code",
    "sub_district_name",
    "sub_district_name_ko",
    "source_category",
    "source_category_ko",
    "source_midcategory",
    "source_midcategory_ko",
    "source_subcategory",
    "source_subcategory_ko",
    "fuel_category",
    "fuel_category_ko",
    "fuel_type",
    "fuel_type_ko",
    "pollutant",
    "emissions_kg",
]


def _clean_cell(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_label(value: object) -> str | None:
    """Create a stable ASCII-ish code label while retaining Korean source labels."""
    text = _clean_cell(value)
    if text is None:
        return None
    text = text.lower()
    text = re.sub(r"[^0-9a-z가-힣]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or None


def normalize_pollutant(value: object) -> str | None:
    text = _clean_cell(value)
    if text is None:
        return None
    compact = text.replace(" ", "")
    return POLLUTANT_ALIASES.get(compact) or POLLUTANT_ALIASES.get(compact.upper())


def taxonomy_period(year: int) -> str:
    """Label known CAPSS taxonomy eras called out by CAPSS documentation."""
    if year < 2007:
        return "pre_2007"
    if year < 2011:
        return "2007_2010"
    if year < 2015:
        return "2011_2014"
    return "2015_plus"


def taxonomy_notes(year: int) -> list[str]:
    notes = []
    if year in {2007, 2011, 2015}:
        notes.append("CAPSS source classification expansion year")
    if year >= 2015:
        notes.append("Biomass burning and fugitive dust categories expected from 2015 onward")
    return notes


def infer_year(path: Path, sheet_name: str | int | None = None) -> int:
    candidates = [path.stem]
    if sheet_name is not None:
        candidates.append(str(sheet_name))
    for value in candidates:
        match = re.search(r"(19|20)\d{2}", value)
        if match:
            return int(match.group(0))
    raise ValueError(f"Could not infer CAPSS inventory year from {path.name}")


def find_header_rows(raw: pd.DataFrame) -> tuple[int, int]:
    """Find descriptor and pollutant header rows in a CAPSS workbook sheet."""
    for idx, row in raw.iterrows():
        values = {_clean_cell(value) for value in row.tolist()}
        if not {"시도", "시군구"}.issubset(values):
            continue

        descriptor_row = int(idx)
        pollutants = [normalize_pollutant(value) for value in row.tolist()]
        if sum(value is not None for value in pollutants) >= 3:
            return descriptor_row, descriptor_row

        for pollutant_row in range(descriptor_row + 1, min(descriptor_row + 5, len(raw))):
            pollutants = [normalize_pollutant(value) for value in raw.iloc[pollutant_row].tolist()]
            if sum(value is not None for value in pollutants) >= 3:
                return descriptor_row, pollutant_row
    raise ValueError("Could not find CAPSS pollutant header row.")


def extract_unit(raw: pd.DataFrame, descriptor_row: int) -> str | None:
    """Extract the workbook emissions unit string, usually kg/yr."""
    first_row = max(0, descriptor_row - 3)
    fallback: str | None = None
    for row_index in range(first_row, descriptor_row + 1):
        for value in raw.iloc[row_index].tolist():
            text = _clean_cell(value)
            if not text:
                continue
            if "kg" in text.lower():
                match = re.search(r"\(([^)]+)\)", text)
                return match.group(1) if match else text
            if ("배출량" in text or "단위" in text) and fallback is None:
                match = re.search(r"\(([^)]+)\)", text)
                fallback = match.group(1) if match else text
    return fallback


def parse_workbook(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Parse one CAPSS workbook into a long tidy emissions table and metadata."""
    excel = pd.ExcelFile(path)
    frames = []
    sheet_metadata = []
    for sheet_name in excel.sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)
        if raw.empty:
            continue
        descriptor_row, pollutant_row = find_header_rows(raw)
        year = infer_year(path, sheet_name)
        unit = extract_unit(raw, descriptor_row)
        descriptor_labels = [_clean_cell(value) for value in raw.iloc[descriptor_row].tolist()]
        pollutant_labels = [_clean_cell(value) for value in raw.iloc[pollutant_row].tolist()]

        column_names: list[str | None] = []
        pollutant_columns: dict[int, str] = {}
        for index, descriptor in enumerate(descriptor_labels):
            if descriptor in DESCRIPTOR_COLUMNS:
                column_names.append(DESCRIPTOR_COLUMNS[descriptor])
                continue
            pollutant = normalize_pollutant(
                pollutant_labels[index] if index < len(pollutant_labels) else None
            )
            if pollutant:
                column_names.append(pollutant)
                pollutant_columns[index] = pollutant
            else:
                column_names.append(None)

        data = raw.iloc[pollutant_row + 1 :].copy()
        data = data.loc[:, [idx for idx, name in enumerate(column_names) if name is not None]]
        data.columns = [name for name in column_names if name is not None]
        data = data.dropna(how="all")
        if "province_name_ko" in data:
            data = data[data["province_name_ko"].notna()]
        descriptor_output = [
            column for column in DESCRIPTOR_COLUMNS.values() if column in data.columns
        ]
        pollutant_output = sorted(set(pollutant_columns.values()), key=EXPECTED_POLLUTANTS.index)
        long = data.melt(
            id_vars=descriptor_output,
            value_vars=pollutant_output,
            var_name="pollutant",
            value_name="emissions_kg",
        )
        long["emissions_kg"] = pd.to_numeric(long["emissions_kg"], errors="coerce")
        long = long.dropna(subset=["emissions_kg"])
        long.insert(0, "year", year)
        frames.append(long)
        observed = sorted(long["pollutant"].dropna().unique(), key=EXPECTED_POLLUTANTS.index)
        sheet_metadata.append(
            {
                "sheet": sheet_name,
                "year": year,
                "unit": unit,
                "pollutants_observed": observed,
                "pollutants_missing_from_expected": [
                    pollutant for pollutant in EXPECTED_POLLUTANTS if pollutant not in observed
                ],
                "unexpected_pollutants": [
                    pollutant for pollutant in observed if pollutant not in EXPECTED_POLLUTANTS
                ],
                "taxonomy_period": taxonomy_period(year),
                "taxonomy_notes": taxonomy_notes(year),
            }
        )

    if not frames:
        raise ValueError(f"No CAPSS emissions rows parsed from {path}")
    parsed = pd.concat(frames, ignore_index=True)
    parsed["sub_district_name"] = parsed.get("sub_district_name_ko")
    parsed["sub_district_code"] = pd.NA
    for source, normalized in [
        ("source_category_ko", "source_category"),
        ("source_midcategory_ko", "source_midcategory"),
        ("source_subcategory_ko", "source_subcategory"),
        ("fuel_category_ko", "fuel_category"),
        ("fuel_type_ko", "fuel_type"),
    ]:
        parsed[normalized] = parsed[source].map(normalize_label) if source in parsed else pd.NA

    for column in OUTPUT_COLUMNS:
        if column not in parsed:
            parsed[column] = pd.NA
    parsed = parsed[OUTPUT_COLUMNS].sort_values(
        ["year", "province_name_ko", "sub_district_name_ko", "source_category_ko", "pollutant"],
        kind="stable",
    )
    metadata = {
        "source_file": path.name,
        "sheets": sheet_metadata,
        "rows": int(len(parsed)),
        "sub_district_code_note": (
            "Official sub-district codes are not present in the CAPSS detailed workbook; "
            "join an external administrative-code crosswalk before code-based geography."
        ),
    }
    return parsed.reset_index(drop=True), metadata


def process_files(
    input_dir: Path, output_dir: Path, years: list[int] | None = None
) -> dict[str, object]:
    """Parse selected raw CAPSS workbooks and write tidy Parquet plus metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(input_dir.glob("capss_emissions_statistics_*.xlsx"))
    if years is not None:
        wanted = set(years)
        files = [path for path in files if infer_year(path) in wanted]
    if not files:
        raise ValueError(f"No CAPSS XLSX files found in {input_dir}")

    frames = []
    file_metadata = []
    for path in files:
        parsed, metadata = parse_workbook(path)
        year = int(parsed["year"].iloc[0])
        parsed.to_parquet(output_dir / f"capss_emissions_tidy_{year}.parquet", index=False)
        frames.append(parsed)
        file_metadata.append(metadata)
        print(f"{year}: parsed {len(parsed)} long rows from {path.name}")

    combined = pd.concat(frames, ignore_index=True)
    combined.to_parquet(output_dir / "capss_emissions_tidy.parquet", index=False)
    metadata = {
        "dataset": "CAPSS detailed national air pollutant emissions statistics, tidy long form",
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_unit_policy": "Units are extracted per workbook sheet; emissions_kg is used only for kg/yr sheets.",
        "expected_pollutants": list(EXPECTED_POLLUTANTS),
        "taxonomy_change_notes": {
            "2007": "CAPSS source classification expanded.",
            "2011": "CAPSS source classification expanded; PM2.5 appears in public inventory coverage from 2011.",
            "2015": "CAPSS source classification expanded; fugitive dust and biomass burning are expected from 2015 onward.",
            "BC": "Do not assume by date; rely on pollutants_observed in this metadata for each workbook.",
        },
        "files": file_metadata,
    }
    (output_dir / "capss_emissions_tidy.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=CAPSS_RAW_DIR / "emissions_statistics")
    parser.add_argument(
        "--output-dir", type=Path, default=CAPSS_INTERIM_DIR / "emissions_statistics"
    )
    parser.add_argument("--years", nargs="*", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    process_files(args.input_dir, args.output_dir, args.years)
