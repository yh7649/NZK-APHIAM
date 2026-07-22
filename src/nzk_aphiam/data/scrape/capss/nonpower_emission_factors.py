"""Extract an inventory-targeted first pass from the official CAPSS VII PDF."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import pandas as pd
from pypdf import PdfReader

from nzk_aphiam.config.paths import (
    NONPOWER_INTERIM_DIR,
    NONPOWER_REFERENCE_DIR,
    PROJECT_ROOT,
)
from nzk_aphiam.data.process.nonpower_sector_inventory import DELIMITER

DEFAULT_SOURCE_PDF = (
    PROJECT_ROOT
    / "docs"
    / "references"
    / "emission_factor_validation"
    / "korea_ef_references"
    / "CAPSS_Manual_VII_2025.pdf"
)
DEFAULT_TARGET_FILE = NONPOWER_REFERENCE_DIR / "capss_vii_nonpower_scrape_targets.csv"
DEFAULT_OUTPUT_DIR = NONPOWER_INTERIM_DIR / "capss_vii_first_pass"
TABLE_PATTERN = re.compile(r"^<표\s+(\d+-\d+)>\s*(.+(?:배출계수|질량 함유율).*)$")


class CapssExtractionError(ValueError):
    """Raised when the source PDF or extraction target registry is invalid."""


def _split(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [item.strip() for item in str(value).split(DELIMITER) if item.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def extract_table_titles(text: str) -> list[tuple[str, str]]:
    """Return true table-title lines, excluding prose references to a table."""
    titles = []
    for line in text.splitlines():
        normalized = " ".join(line.split())
        match = TABLE_PATTERN.fullmatch(normalized)
        if match:
            title = re.sub(r"\s*\(계속\)\s*$", "", match.group(2)).strip()
            titles.append((match.group(1), title))
    return titles


def load_targets(
    target_file: Path = DEFAULT_TARGET_FILE,
    reference_dir: Path = NONPOWER_REFERENCE_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and validate page targets against the version-controlled inventory."""
    targets = pd.read_csv(target_file, dtype=str, keep_default_na=False)
    required = {
        "target_id",
        "scope",
        "pdf_page_start",
        "pdf_page_end",
        "inventory_ids",
        "notes",
    }
    missing = sorted(required - set(targets.columns))
    if missing:
        raise CapssExtractionError(f"Missing target columns: {missing}")
    if targets["target_id"].eq("").any() or not targets["target_id"].is_unique:
        raise CapssExtractionError("target_id must be nonempty and unique")

    for column in ("pdf_page_start", "pdf_page_end"):
        targets[column] = pd.to_numeric(targets[column], errors="raise").astype(int)
    invalid = targets["pdf_page_start"].lt(1) | targets["pdf_page_end"].lt(
        targets["pdf_page_start"]
    )
    if invalid.any():
        ids = targets.loc[invalid, "target_id"].tolist()
        raise CapssExtractionError(f"Invalid target page ranges: {ids}")

    inventory = pd.read_csv(
        reference_dir / "gcam_kaist_nonpower_sector_inventory.csv",
        dtype=str,
        keep_default_na=False,
    )
    inventory_ids = set(inventory["inventory_id"])
    referenced = {item for value in targets["inventory_ids"] for item in _split(value)}
    unknown = sorted(referenced - inventory_ids)
    if unknown:
        raise CapssExtractionError(f"Unknown target inventory IDs: {unknown}")
    return targets, inventory


def scrape_capss_vii(
    source_pdf: Path = DEFAULT_SOURCE_PDF,
    target_file: Path = DEFAULT_TARGET_FILE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, object]:
    """Extract target pages, table titles, coverage, checksums, and provenance."""
    if not source_pdf.is_file():
        raise CapssExtractionError(f"CAPSS VII source PDF not found: {source_pdf}")
    targets, inventory = load_targets(target_file)
    reader = PdfReader(str(source_pdf))
    page_count = len(reader.pages)
    if targets["pdf_page_end"].max() > page_count:
        raise CapssExtractionError(
            f"Target page exceeds {page_count}-page source PDF: "
            f"{int(targets['pdf_page_end'].max())}"
        )

    page_targets: dict[int, list[dict[str, str]]] = {}
    for row in targets.itertuples(index=False):
        for page_number in range(row.pdf_page_start, row.pdf_page_end + 1):
            page_targets.setdefault(page_number, []).append(
                {
                    "target_id": row.target_id,
                    "scope": row.scope,
                    "inventory_ids": row.inventory_ids,
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    pages_path = output_dir / "capss_vii_nonpower_pages.jsonl"
    table_rows: list[dict[str, object]] = []
    extracted_pages: dict[int, str] = {}
    with pages_path.open("w", encoding="utf-8") as stream:
        for page_number in sorted(page_targets):
            page = reader.pages[page_number - 1]
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:  # pragma: no cover - compatibility with older pypdf
                text = page.extract_text() or ""
            extracted_pages[page_number] = text
            target_ids = sorted({item["target_id"] for item in page_targets[page_number]})
            inventory_ids = sorted(
                {
                    inventory_id
                    for item in page_targets[page_number]
                    for inventory_id in _split(item["inventory_ids"])
                }
            )
            stream.write(
                json.dumps(
                    {
                        "source_id": "capss_handbook_vii",
                        "pdf_page": page_number,
                        "target_ids": target_ids,
                        "inventory_ids": inventory_ids,
                        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "text": text,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            for target_id in target_ids:
                for table_id, title in extract_table_titles(text):
                    table_rows.append(
                        {
                            "target_id": target_id,
                            "table_id": table_id,
                            "title": title,
                            "pdf_page_first": page_number,
                            "pdf_page_last": page_number,
                        }
                    )

    table_index = pd.DataFrame(
        table_rows,
        columns=("target_id", "table_id", "title", "pdf_page_first", "pdf_page_last"),
    )
    if not table_index.empty:
        table_index = (
            table_index.groupby(["target_id", "table_id", "title"], as_index=False)
            .agg(pdf_page_first=("pdf_page_first", "min"), pdf_page_last=("pdf_page_last", "max"))
            .sort_values(["pdf_page_first", "target_id", "table_id"], kind="stable")
        )
    table_index_path = output_dir / "capss_vii_nonpower_table_index.csv"
    table_index.to_csv(table_index_path, index=False, encoding="utf-8")

    target_table_counts = table_index["target_id"].value_counts().to_dict()
    target_by_inventory: dict[str, list[str]] = {}
    for row in targets.itertuples(index=False):
        for inventory_id in _split(row.inventory_ids):
            target_by_inventory.setdefault(inventory_id, []).append(row.target_id)
    coverage_rows = []
    for row in inventory.itertuples(index=False):
        target_ids = sorted(set(target_by_inventory.get(row.inventory_id, [])))
        coverage_rows.append(
            {
                "inventory_id": row.inventory_id,
                "priority": row.priority,
                "status": row.status,
                "required_pollutants": row.required_pollutants,
                "target_ids": DELIMITER.join(target_ids),
                "target_table_count": sum(target_table_counts.get(item, 0) for item in target_ids),
                "scrape_status": "target_extracted" if target_ids else "no_direct_target",
            }
        )
    coverage = pd.DataFrame(coverage_rows).sort_values("inventory_id", kind="stable")
    coverage_path = output_dir / "capss_vii_inventory_scrape_coverage.csv"
    coverage.to_csv(coverage_path, index=False, encoding="utf-8")

    metadata = {
        "source_id": "capss_handbook_vii",
        "source_pdf": _display_path(source_pdf),
        "source_pdf_sha256": _sha256(source_pdf),
        "source_pdf_pages": page_count,
        "target_registry": _display_path(target_file),
        "target_registry_sha256": _sha256(target_file),
        "target_count": int(len(targets)),
        "unique_pages_extracted": int(len(extracted_pages)),
        "pages_with_text": int(sum(bool(value.strip()) for value in extracted_pages.values())),
        "factor_or_speciation_tables_indexed": int(len(table_index)),
        "inventory_ids_targeted": int(sum(coverage["scrape_status"].eq("target_extracted"))),
        "inventory_ids_without_direct_target": coverage.loc[
            coverage["scrape_status"].eq("no_direct_target"), "inventory_id"
        ].tolist(),
        "scrape_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "outputs": {
            "page_text": pages_path.name,
            "table_index": table_index_path.name,
            "inventory_coverage": coverage_path.name,
        },
        "method_note": (
            "First-pass text extraction and table indexing only. Table rows are not production "
            "emission factors until normalized, checked against the PDF, and linked to legal "
            "inventory denominators."
        ),
    }
    (output_dir / "capss_vii_nonpower_scrape.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract inventory-targeted pages and table titles from CAPSS Handbook VII."
    )
    parser.add_argument("--source-pdf", type=Path, default=DEFAULT_SOURCE_PDF)
    parser.add_argument("--target-file", type=Path, default=DEFAULT_TARGET_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        metadata = scrape_capss_vii(args.source_pdf, args.target_file, args.output_dir)
    except CapssExtractionError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
