"""Place a MACRO/GCAM-KAIST handoff in a mutable model-input bundle.

This replaces manually copying a file into the repository. It validates the
downstream schema, copies the handoff under
``model_inputs/scenarios/<bundle>/upstream/<model>/``, and writes a provenance
sidecar recording who supplied it, when, and its checksum.
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

from nzk_aphiam.config.paths import MODEL_SCENARIO_INPUTS_DIR
from nzk_aphiam.integration.macro_kepco_validation import _find_column
from nzk_aphiam.model_inputs.gcam_xml import inspect_gcam_source

VALID_KINDS = ("activity", "generation", "gcam_xml_archive")
VALID_SOURCE_MODELS = ("macro", "gcam_kaist")
DEFAULT_SCENARIO_BUNDLE = "team_handoff"
DEFAULT_SOURCE_MODEL = "macro"


def upstream_input_dir(scenario_bundle: str, source_model: str) -> Path:
    """Return the upstream handoff directory for one scenario bundle."""
    if not scenario_bundle or Path(scenario_bundle).name != scenario_bundle:
        raise ValueError("scenario_bundle must be one non-empty directory name.")
    if source_model not in VALID_SOURCE_MODELS:
        raise ValueError(
            f"source_model must be one of {VALID_SOURCE_MODELS}, got {source_model!r}."
        )
    return MODEL_SCENARIO_INPUTS_DIR / scenario_bundle / "upstream" / source_model


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
    dest_dir: Path | None = None,
    scenario_bundle: str = DEFAULT_SCENARIO_BUNDLE,
    source_model: str = DEFAULT_SOURCE_MODEL,
    dest_name: str | None = None,
    contributor: str | None = None,
    note: str | None = None,
    year_column: str = "year",
    sector_column: str = "sector",
    fuel_column: str = "fuel",
    activity_column: str = "activity",
    upstream_scenario: str | None = None,
    force: bool = False,
) -> Path:
    """Validate, copy, and record one upstream model handoff."""
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}.")
    if not source.exists():
        raise FileNotFoundError(source)
    destination_dir = dest_dir or upstream_input_dir(scenario_bundle, source_model)
    if upstream_scenario:
        if Path(upstream_scenario).name != upstream_scenario:
            raise ValueError("upstream_scenario must be one directory name.")
        destination_dir /= upstream_scenario

    source_details: dict[str, object] = {}
    data: pd.DataFrame | None = None
    if kind == "gcam_xml_archive":
        if source_model != "gcam_kaist":
            raise ValueError("gcam_xml_archive inputs require source_model='gcam_kaist'.")
        source_details = inspect_gcam_source(source)
        detected_columns: list[str] = []
    else:
        data = _read_table(source)
    if kind == "activity" and data is not None:
        detected_columns = _validate_activity(
            data,
            year_column=year_column,
            sector_column=sector_column,
            fuel_column=fuel_column,
            activity_column=activity_column,
        )
    elif kind == "generation" and data is not None:
        detected_columns = _validate_generation(data)

    destination_dir.mkdir(parents=True, exist_ok=True)
    dest_path = destination_dir / (dest_name or source.name)
    if dest_path.exists() and not force:
        raise FileExistsError(
            f"{dest_path} already exists. Pass --force to overwrite deliberately."
        )
    shutil.copy2(source, dest_path)

    manifest = {
        "kind": kind,
        "scenario_bundle": scenario_bundle,
        "source_model": source_model,
        "original_filename": source.name,
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
        "contributor": contributor,
        "note": note,
        "sha256": _file_sha256(dest_path),
        "size_bytes": dest_path.stat().st_size,
        "row_count": int(len(data)) if data is not None else None,
        "columns": list(data.columns) if data is not None else [],
        "detected_columns": detected_columns,
        **source_details,
    }
    manifest_path = destination_dir / f"{dest_path.stem}.metadata.json"
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
    parser.add_argument("--scenario-bundle", default=DEFAULT_SCENARIO_BUNDLE)
    parser.add_argument(
        "--source-model",
        choices=VALID_SOURCE_MODELS,
        default=DEFAULT_SOURCE_MODEL,
    )
    parser.add_argument(
        "--dest-name", help="Filename to use in the upstream bundle (default: keep original)."
    )
    parser.add_argument("--contributor", help="Who supplied the file, for the provenance record.")
    parser.add_argument("--note", help="Free-text provenance note, e.g. the scenario or vintage.")
    parser.add_argument("--year-column", default="year")
    parser.add_argument("--sector-column", default="sector")
    parser.add_argument("--fuel-column", default="fuel")
    parser.add_argument("--activity-column", default="activity")
    parser.add_argument(
        "--upstream-scenario",
        help="Optional source-scenario subdirectory, e.g. nzk or reference.",
    )
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
            scenario_bundle=args.scenario_bundle,
            source_model=args.source_model,
            dest_name=args.dest_name,
            contributor=args.contributor,
            note=args.note,
            year_column=args.year_column,
            sector_column=args.sector_column,
            fuel_column=args.fuel_column,
            activity_column=args.activity_column,
            upstream_scenario=args.upstream_scenario,
            force=args.force,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"ingest_macro: {error}", file=sys.stderr)
        raise SystemExit(1) from None

    print(f"Ingested {args.source} -> {dest_path}")
    if args.kind == "gcam_xml_archive":
        print(
            "Next: track the large archive with DVC, then run "
            f"`make extract-gcam-nzk GCAM_XML_SOURCE={dest_path}`."
        )
    elif args.kind == "activity":
        print(
            "Next: make integrate-macro-inputs "
            f"MODEL_INPUT_SCENARIO={args.scenario_bundle} MACRO_ACTIVITY={dest_path}"
        )
    else:
        print(f"Next: make validate-macro-2021-kepco-ef MACRO_GENERATION={dest_path}")


if __name__ == "__main__":
    main()
