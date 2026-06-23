"""
Clean raw CleanSYS TMS JSON files into a wide CSV.

Unit of observation:
    facility/stack at a measurement time

Run from project root:

    python -m nzk_aphiam.archive.cleansys_tms_wide

Optional:

    python -m nzk_aphiam.archive.cleansys_tms_wide \
        --raw-dir data/archive/raw/cleansys_tms \
        --out-path data/archive/interim/cleansys_tms/cleansys_tms_wide.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from nzk_aphiam.config.paths import ARCHIVE_INTERIM_DIR, CLEANSYS_DIR

POLLUTANTS = ["nox", "sox", "tsp", "co", "nh3", "hf", "hcl"]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract rows from common data.go.kr JSON response structures.
    """
    candidate: Any = data

    if isinstance(candidate, dict) and "response" in candidate:
        candidate = candidate["response"]

    if isinstance(candidate, dict) and "body" in candidate:
        candidate = candidate["body"]

    if isinstance(candidate, dict) and "items" in candidate:
        candidate = candidate["items"]

    if isinstance(candidate, dict) and "item" in candidate:
        candidate = candidate["item"]

    if isinstance(candidate, list):
        return candidate

    if isinstance(candidate, dict):
        return [candidate]

    return []


def to_numeric_or_none(raw_value: Any) -> float | None:
    """
    Convert numeric-looking API values to floats.
    Return None for missing values or nonnumeric status strings.
    """
    if raw_value is None:
        return None

    raw_str = str(raw_value).strip()

    if raw_str == "":
        return None

    numeric = pd.to_numeric(raw_str, errors="coerce")

    if pd.isna(numeric):
        return None

    return float(numeric)


def normalize_status(raw_value: Any) -> str | None:
    """
    Convert nonnumeric measurement strings into simple status labels.

    Example:
        측정자료확인중(가동중지) -> shutdown
    """
    if raw_value is None:
        return None

    raw_str = str(raw_value).strip()

    if raw_str == "":
        return None

    numeric = pd.to_numeric(raw_str, errors="coerce")

    if pd.notna(numeric):
        return None

    if "가동중지" in raw_str:
        return "shutdown"

    if "측정자료확인중" in raw_str:
        return "under_review"

    return raw_str


def records_to_wide_df(records: list[dict[str, Any]], source_file: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for record in records:
        row = {
            "mesure_dt": record.get("mesure_dt"),
            "area_nm": record.get("area_nm"),
            "fact_manage_nm": record.get("fact_manage_nm"),
            "stack_code": record.get("stack_code"),
            "source_file": source_file,
        }

        for pollutant in POLLUTANTS:
            measure_key = f"{pollutant}_mesure_value"
            limit_key = f"{pollutant}_exhst_perm_stdr_value"

            raw_measure = record.get(measure_key)
            raw_limit = record.get(limit_key)

            row[f"{pollutant}_value_raw"] = raw_measure
            row[f"{pollutant}_value"] = to_numeric_or_none(raw_measure)
            row[f"{pollutant}_status"] = normalize_status(raw_measure)

            row[f"{pollutant}_limit_raw"] = raw_limit
            row[f"{pollutant}_limit"] = to_numeric_or_none(raw_limit)

        rows.append(row)

    df = pd.DataFrame(rows)

    df["mesure_dt"] = pd.to_datetime(df["mesure_dt"], errors="coerce")

    return df


def read_raw_files(raw_dir: Path) -> pd.DataFrame:
    json_paths = sorted(
        path for path in raw_dir.glob("*.json") if not path.name.endswith(".metadata.json")
    )

    if not json_paths:
        raise FileNotFoundError(f"No raw JSON files found in {raw_dir}")

    frames: list[pd.DataFrame] = []

    for path in json_paths:
        print(f"Reading {path}")

        data = load_json(path)
        records = extract_items(data)

        if not records:
            print(f"Warning: no records found in {path}")
            continue

        frames.append(records_to_wide_df(records, source_file=path.name))

    if not frames:
        raise ValueError("No records extracted from raw JSON files.")

    return pd.concat(frames, ignore_index=True)


def save_csv(df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Saved wide cleaned CSV to {out_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean raw CleanSYS TMS JSON files into wide CSV."
    )

    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=CLEANSYS_DIR,
        help="Directory containing raw CleanSYS TMS JSON files.",
    )

    parser.add_argument(
        "--out-path",
        type=Path,
        default=ARCHIVE_INTERIM_DIR / "cleansys_tms" / "cleansys_tms_wide.csv",
        help="Path where cleaned wide-format CSV will be written.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    df = read_raw_files(args.raw_dir)

    print("\nPreview:")
    print(df.head())

    print("\nShape:")
    print(df.shape)

    save_csv(df, args.out_path)


if __name__ == "__main__":
    main()
