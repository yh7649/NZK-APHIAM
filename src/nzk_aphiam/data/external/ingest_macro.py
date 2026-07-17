"""Place a team-supplied MACRO/GCAM-KAIST file under data/external/macro/ with provenance.

This replaces manually copying a file into the repository: it validates that the
file has the columns the downstream pipeline needs, copies it into the tracked
`data/external/macro/` directory, and writes a `.metadata.json` sidecar recording
who supplied it, when, and its checksum.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

import pandas as pd

from nzk_aphiam.config.paths import MACRO_EXTERNAL_DIR
from nzk_aphiam.integration.macro_kepco_validation import _find_column

VALID_KINDS = ("activity", "generation")


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if path.suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported table format for {path}; use CSV, Excel, or Parquet.")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_activity(
    data: pd.DataFrame,
    *,
    year_column: str,
    sector_column: str,
    fuel_column: str,
    activity_column: str,
) -> list[str]:
    required = [year_column, sector_column, fuel_column, activity_column]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(
            f"Activity file is missing columns {missing}. Found: {list(data.columns)}. "
            "If the source uses different names, pass --year-column/--sector-column/"
            "--fuel-column/--activity-column matching what you will later pass to "
            "`make integrate-macro-inputs`."
        )
    return required


def _validate_generation(data: pd.DataFrame) -> list[str]:
    columns = list(data.columns)
    year_column = _find_column(columns, ("year",))
    generation_column = _find_column(
        columns, ("generation_mwh", "generation_gwh", "generation", "mwh", "gwh")
    )
    fuel_column = _find_column(columns, ("macro_fuel", "fuel"))
    technology_column = _find_column(columns, ("macro_technology", "technology", "tech"))
    type_column = _find_column(columns, ("type",))
    if not year_column or not generation_column:
        raise ValueError(
            f"Generation file must have a year column and a generation column. Found: {columns}."
        )
    if not fuel_column and not technology_column and not type_column:
        raise ValueError(
            "Generation file must have a fuel, technology, or combined type column for "
            f"crosswalking. Found: {columns}."
        )
    return [
        column
        for column in (year_column, generation_column, fuel_column, technology_column, type_column)
        if column
    ]


def ingest_macro_file(
    *,
    source: Path,
    kind: str,
    dest_dir: Path = MACRO_EXTERNAL_DIR,
    dest_name: str | None = None,
    contributor: str | None = None,
    note: str | None = None,
    year_column: str = "year",
    sector_column: str = "sector",
    fuel_column: str = "fuel",
    activity_column: str = "activity",
    force: bool = False,
) -> Path:
    """Validate, copy, and record provenance for one externally supplied MACRO file."""
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}.")
    if not source.exists():
        raise FileNotFoundError(source)

    data = _read_table(source)
    if kind == "activity":
        detected_columns = _validate_activity(
            data,
            year_column=year_column,
            sector_column=sector_column,
            fuel_column=fuel_column,
            activity_column=activity_column,
        )
    else:
        detected_columns = _validate_generation(data)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / (dest_name or source.name)
    if dest_path.exists() and not force:
        raise FileExistsError(
            f"{dest_path} already exists. Pass --force to overwrite deliberately."
        )
    shutil.copy2(source, dest_path)

    manifest = {
        "kind": kind,
        "original_filename": source.name,
        "original_path": str(source.resolve()),
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
        "contributor": contributor,
        "note": note,
        "sha256": _file_sha256(dest_path),
        "size_bytes": dest_path.stat().st_size,
        "row_count": int(len(data)),
        "columns": list(data.columns),
        "detected_columns": detected_columns,
    }
    manifest_path = dest_dir / f"{dest_path.stem}.metadata.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return dest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="Path to the file you were sent."
    )
    parser.add_argument("--kind", choices=VALID_KINDS, required=True)
    parser.add_argument(
        "--dest-name", help="Filename to use under data/external/macro/ (default: keep original)."
    )
    parser.add_argument("--contributor", help="Who supplied the file, for the provenance record.")
    parser.add_argument("--note", help="Free-text provenance note, e.g. the scenario or vintage.")
    parser.add_argument("--year-column", default="year")
    parser.add_argument("--sector-column", default="sector")
    parser.add_argument("--fuel-column", default="fuel")
    parser.add_argument("--activity-column", default="activity")
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing ingested file."
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        dest_path = ingest_macro_file(
            source=args.source,
            kind=args.kind,
            dest_name=args.dest_name,
            contributor=args.contributor,
            note=args.note,
            year_column=args.year_column,
            sector_column=args.sector_column,
            fuel_column=args.fuel_column,
            activity_column=args.activity_column,
            force=args.force,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"ingest_macro: {error}", file=sys.stderr)
        raise SystemExit(1) from None

    print(f"Ingested {args.source} -> {dest_path}")
    if args.kind == "activity":
        print(f"Next: make integrate-macro-inputs MACRO_ACTIVITY={dest_path}")
    else:
        print(f"Next: make validate-macro-2021-kepco-ef MACRO_GENERATION={dest_path}")


if __name__ == "__main__":
    main()
