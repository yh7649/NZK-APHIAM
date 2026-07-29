"""Scrape inventory-linked non-power emission factors from the official CAPSS VII PDF."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
from typing import Any

import pandas as pd
import pdfplumber
from pypdf import PdfReader
import requests

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
OFFICIAL_SOURCE_PAGE = "https://air.go.kr/article/view.do?articleId=491&boardId=8&currentPageNo=1"
OFFICIAL_SOURCE_PDF_URL = "https://air.go.kr/file/download.do?fileId=699"
DEFAULT_TARGET_FILE = NONPOWER_REFERENCE_DIR / "capss_vii_nonpower_scrape_targets.csv"
DEFAULT_OUTPUT_DIR = NONPOWER_INTERIM_DIR / "capss_vii_first_pass"
TABLE_PATTERN = re.compile(r"^<표\s+(\d+-\d+)>\s*(.+(?:배출계수|질량 함유율).*)$")
PROSE_TABLE_REFERENCE_PATTERN = re.compile(r"^(?:은|는|이|가|을|를|의|과|와|에서|에는)\s")
UNIT_LINE_PATTERN = re.compile(r"(?:단위|배출계수 단위)\s*[:：]\s*(.+)")
POLLUTANT_ORDER = ("PM2.5", "SOx", "NOx", "VOCs", "NH3", "CO", "TSP", "PM10")
MISSING_FACTOR_MARKERS = {"", "-", "‐", "–", "—", "―"}
RAW_TABLE_FILE = "capss_vii_nonpower_raw_tables.jsonl"
CANDIDATE_FILE = "capss_vii_nonpower_factor_candidates.csv"
LINK_FILE = "capss_vii_nonpower_inventory_factor_links.csv"
EXTRACTION_ISSUE_FILE = "capss_vii_nonpower_extraction_issues.csv"


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
            if PROSE_TABLE_REFERENCE_PATTERN.match(title):
                continue
            titles.append((match.group(1), title))
    return titles


def verify_official_source(
    source_pdf: Path,
    source_url: str = OFFICIAL_SOURCE_PDF_URL,
    timeout: float = 120,
) -> dict[str, object]:
    """Verify that the preserved source PDF is byte-identical to the official download."""
    if not source_pdf.is_file():
        raise CapssExtractionError(f"CAPSS VII source PDF not found: {source_pdf}")
    try:
        response = requests.get(source_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise CapssExtractionError(
            f"Could not retrieve the official CAPSS VII PDF from {source_url}: {error}"
        ) from error
    if not response.content.startswith(b"%PDF"):
        raise CapssExtractionError(
            f"Official CAPSS VII response was not a PDF: {response.headers.get('content-type')}"
        )
    remote_sha256 = hashlib.sha256(response.content).hexdigest()
    local_sha256 = _sha256(source_pdf)
    if remote_sha256 != local_sha256:
        raise CapssExtractionError(
            "The preserved CAPSS VII PDF differs from the current official download: "
            f"local={local_sha256}, official={remote_sha256}"
        )
    return {
        "official_source_page": OFFICIAL_SOURCE_PAGE,
        "official_source_pdf_url": source_url,
        "official_source_verified": True,
        "official_source_bytes": len(response.content),
        "official_source_sha256": remote_sha256,
    }


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


def _normalize_pollutant(value: object) -> str:
    text = re.sub(r"[\s.\-‐–—―_]", "", str(value or "")).upper()
    if text.startswith("PM25"):
        return "PM2.5"
    if text.startswith("PM10"):
        return "PM10"
    if text.startswith("SOX"):
        return "SOx"
    if text.startswith("NOX"):
        return "NOx"
    if text.startswith("VOC"):
        return "VOCs"
    if text.startswith("NH") and text.endswith("3"):
        return "NH3"
    if text == "CO" or text.startswith("CO("):
        return "CO"
    if text.startswith("TSP"):
        return "TSP"
    return ""


def _compact_cell(value: object) -> str:
    return " ".join(str(value or "").split())


def _cell_lines(value: object) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _split_factor_cell(value: object) -> list[str]:
    """Split a vertically stacked factor cell while retaining multi-line formulas."""
    raw_lines = _cell_lines(value)
    combined: list[str] = []
    for line in raw_lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if combined and (
            combined[-1].rstrip().endswith(("+", "×", "*", "/"))
            or normalized.startswith(("+", "×", "*", "/"))
        ):
            combined[-1] = f"{combined[-1]} {normalized}"
        else:
            combined.append(normalized)
    return combined


def _split_source_labels(value: object) -> list[str]:
    lines = []
    for line in _cell_lines(value):
        if "단위" in line or re.fullmatch(r"\([^)]*(?:㎏|kg|g)/[^)]*\)", line):
            continue
        if lines and line.startswith("(") and line.endswith(")"):
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    return lines


def _align_source_labels(labels: list[str], count: int) -> tuple[list[str], bool]:
    if len(labels) == count:
        return labels, True
    if count == 1 and labels:
        return [" ".join(labels)], True
    if len(labels) == count + 1 and labels[0] in {"비민수용", "민수용"}:
        return [f"{labels[0]} {labels[1]}", *labels[2:]], True
    if len(labels) == count + 1 and "돼지" in labels:
        reduced = labels.copy()
        reduced.remove("돼지")
        return reduced, len(reduced) == count
    return labels, False


def _strip_factor_footnote(value: str) -> str:
    normalized = (
        value.replace("−", "-")
        .replace("‐", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("―", "-")
        .strip()
    )
    if normalized in MISSING_FACTOR_MARKERS:
        return ""
    # CAPSS uses superscript a-h source markers, which extract as a trailing letter.
    return re.sub(r"(?<=[0-9S)])([a-h])$", "", normalized)


def _factor_fields(value: str) -> tuple[str, str]:
    normalized = _strip_factor_footnote(value)
    if not normalized:
        return "", ""
    numeric = normalized.replace(",", "")
    if re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)", numeric):
        return numeric, ""
    return "", normalized


def _unit_lines(page: Any, table_bbox: tuple[float, float, float, float]) -> list[str]:
    top = max(0.0, table_bbox[1] - 65.0)
    bottom = min(page.height, table_bbox[3])
    text = page.crop((0.0, top, page.width, bottom)).extract_text() or ""
    lines = []
    for line in text.splitlines():
        compact = " ".join(line.replace("\x00", "·").split())
        if "단위" in compact:
            lines.append(compact)
    return list(dict.fromkeys(lines))


def _normalize_unit(source_unit_text: str, source_label: str) -> tuple[str, str]:
    """Return a conservative normalized denominator and its resolution status."""
    text = (
        f"{source_unit_text} {source_label}".replace("㎏", "kg")
        .replace("㎘", "kL")
        .replace("㎥", "m3")
        .replace("톤", "ton")
        .replace("천m3", "thousand m3")
    )
    compact = re.sub(r"\s+", " ", text)
    lower = compact.lower()
    # Mixed stationary-combustion tables state three units in one note.
    if "석탄" in compact and "유류" in compact:
        solid_markers = ("무연탄", "유연탄", "석탄", "SRF", "BIO-SRF", "목재", "코크스")
        gas_markers = (
            "LNG",
            "도시가스",
            "공정부생가스",
            "정제가스",
            "매립가스",
            "소화가스",
            "BFG",
            "COG",
            "LDG",
        )
        if any(marker in source_label for marker in solid_markers):
            return "kg/tonne-fuel", "resolved_from_material"
        if any(marker in source_label for marker in gas_markers):
            return "kg/thousand-m3-fuel", "resolved_from_material"
        return "kg/kL-fuel", "resolved_from_material"
    if re.search(r"\b(?:g|kg)\s*/\s*km\b", lower):
        return ("g/vehicle-km" if re.search(r"\bg\s*/\s*km\b", lower) else "kg/vehicle-km"), (
            "resolved"
        )
    if re.search(r"\bg\s*/\s*kwh\b", lower):
        return "g/kWh", "resolved"
    if re.search(r"\bkg(?:-pollutant)?\s*/\s*lto\b", lower):
        return "kg/LTO", "resolved"
    if re.search(r"\bg(?:-pollutant)?\s*/\s*(?:대[·.]?)?lto\b", lower):
        return "g/equipment-LTO", "resolved"
    if re.search(r"\bkg\s*/\s*(?:kg|㎏)\b", lower):
        return "kg/kg-material", "resolved"
    if re.search(r"\bg\s*/\s*(?:ton|tonne)\b", lower):
        return "g/tonne", "resolved"
    if re.search(r"\bkg\s*/\s*(?:ton|tonne)\b", lower):
        return "kg/tonne", "resolved"
    if re.search(r"\bkg\s*/\s*kl\b", lower):
        return "kg/kL", "resolved"
    if re.search(r"\bkg\s*/\s*(?:l|ℓ|litre)\b", lower):
        return "kg/litre", "resolved"
    if re.search(r"\bkg\s*/\s*(?:thousand\s*)?m3\b", lower):
        return (
            "kg/thousand-m3" if "thousand" in lower or "천" in compact else "kg/m3"
        ), "resolved"
    if re.search(r"\bg\s*/\s*kg\b", lower):
        return "g/kg-material", "resolved"
    if re.search(r"\bkg\s*/\s*(?:head|animal|마리|두)\b", lower):
        return "kg/animal-year", "resolved"
    if re.search(r"\bkg\s*/\s*(?:ha|헥타르)\b", lower):
        return "kg/hectare", "resolved"
    if re.search(r"\bkg\s*/\s*(?:m2|㎡)\s*[·.]?\s*month\b", lower):
        return "kg/m2-month", "resolved"
    if re.search(r"\bkg\s*/\s*(?:종사자\s*수|worker)\s*[·.]?\s*yr\b", lower):
        return "kg/worker-year", "resolved"
    if re.search(r"\bkg\s*/\s*(?:업소\s*수|facility)\s*[·.]?\s*yr\b", lower):
        return "kg/facility-year", "resolved"
    if re.search(r"\bkg\s*/\s*(?:인|person)\s*[·.]?\s*yr\b", lower):
        return "kg/person-year", "resolved"
    return "", "unresolved"


def _table_matrix(page: Any, table: Any) -> list[list[str | None]]:
    """Extract a bordered table and recover the usually unbordered final pollutant column."""
    left, top, _, bottom = table.bbox
    verticals = sorted(
        {
            round(edge["x0"], 2)
            for edge in page.edges
            if edge["orientation"] == "v"
            and edge["top"] <= top + 30
            and edge["bottom"] >= bottom - 1
        }
    )
    verticals = sorted({round(left, 2), *verticals})
    widths = [
        right - current for current, right in zip(verticals, verticals[1:]) if right - current > 10
    ]
    if len(verticals) < 2 or not widths:
        return table.extract()
    right = verticals[-1] + statistics.median(widths[-4:])
    if right > page.width:
        right = page.width
    settings = {
        "vertical_strategy": "explicit",
        "explicit_vertical_lines": [*verticals, right],
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "intersection_tolerance": 3,
        "text_tolerance": 3,
    }
    cropped = page.crop((verticals[0], top, right, bottom))
    return cropped.extract_table(settings) or table.extract()


def _title_hits(page: Any, table_id: str) -> list[dict[str, Any]]:
    return page.search(rf"<표\s*{re.escape(table_id)}>")


def _associate_table(page: Any, table_id: str) -> tuple[Any | None, str]:
    tables = page.find_tables()
    candidates = []
    for hit in _title_hits(page, table_id):
        for table_index, table in enumerate(tables):
            distance = table.bbox[1] - hit["bottom"]
            if -5 <= distance <= 160:
                candidates.append((abs(distance), table_index, table))
    if not candidates:
        return None, "no_table_below_title"
    _, _, table = min(candidates, key=lambda item: (item[0], item[1]))
    return table, "extracted"


def _factor_header(matrix: list[list[object]]) -> tuple[int, dict[int, str]] | None:
    best: tuple[int, dict[int, str]] | None = None
    for row_index, row in enumerate(matrix):
        headers = {
            column_index: pollutant
            for column_index, value in enumerate(row)
            if (pollutant := _normalize_pollutant(value))
        }
        if len(headers) >= 2 and (best is None or len(headers) > len(best[1])):
            best = row_index, headers
    return best


def _factor_count(factor_cells: list[object]) -> int:
    counts = [
        len(_split_factor_cell(value)) for value in factor_cells if _split_factor_cell(value)
    ]
    if not counts:
        return 0
    frequencies = Counter(counts)
    return max(frequencies, key=lambda count: (frequencies[count], count))


def _normalized_candidates(
    *,
    target_id: str,
    table_id: str,
    title: str,
    pdf_page: int,
    inventory_ids: str,
    matrix: list[list[object]],
    source_unit_text: str,
) -> list[dict[str, object]]:
    header = _factor_header(matrix)
    if header is None:
        return []
    header_index, pollutant_columns = header
    first_factor_column = min(pollutant_columns)
    candidates: list[dict[str, object]] = []
    for source_row_number, row in enumerate(matrix[header_index + 1 :], start=1):
        padded = [*row, *([""] * (max(pollutant_columns) + 1 - len(row)))]
        count = _factor_count([padded[index] for index in pollutant_columns])
        if not count:
            continue
        label_cell = padded[first_factor_column - 1] if first_factor_column else ""
        labels, aligned = _align_source_labels(_split_source_labels(label_cell), count)
        source_category = " / ".join(
            _compact_cell(value) for value in padded[: first_factor_column - 1] if value
        )
        for column_index, pollutant in pollutant_columns.items():
            factors = _split_factor_cell(padded[column_index])
            if len(factors) != count:
                continue
            for ordinal, raw_factor in enumerate(factors, start=1):
                ef_value, ef_expression = _factor_fields(raw_factor)
                if not ef_value and not ef_expression:
                    continue
                source_label = (
                    labels[ordinal - 1]
                    if aligned
                    else f"{_compact_cell(label_cell)} [row {ordinal} of {count}]"
                )
                unit_label = source_label
                compact_label_cell = _compact_cell(label_cell)
                if re.search(r"(?:㎏|kg|g)\s*/", compact_label_cell):
                    unit_label = f"{unit_label} {compact_label_cell}"
                unit, unit_status = _normalize_unit(source_unit_text, unit_label)
                if not aligned and unit_status == "resolved_from_material":
                    unit, unit_status = "", "unresolved"
                candidates.append(
                    {
                        "target_id": target_id,
                        "table_id": table_id,
                        "title": title,
                        "pdf_page": pdf_page,
                        "source_row_number": source_row_number,
                        "source_value_ordinal": ordinal,
                        "target_inventory_ids": inventory_ids,
                        "source_category": source_category,
                        "source_label": source_label,
                        "pollutant": pollutant,
                        "ef_value": ef_value,
                        "ef_expression": ef_expression,
                        "raw_factor": raw_factor,
                        "unit": unit,
                        "unit_status": unit_status,
                        "source_unit_text": source_unit_text,
                        "alignment_status": (
                            "aligned" if aligned else "unresolved_source_label_alignment"
                        ),
                        "review_status": "official_vii_machine_extracted",
                        "production_ready": "false",
                    }
                )
    return candidates


def _match_text(value: object) -> str:
    normalized = str(value or "").replace("소고기", "쇠고기")
    return re.sub(r"[\s,·․‧()\-_/]", "", normalized).lower()


def _candidate_inventory_match(
    row: object,
    crosswalk: pd.DataFrame,
) -> tuple[str, str]:
    """Map a scraped row to the strongest matching native CAPSS crosswalk target(s)."""
    search_text = _match_text(f"{row.title} {row.source_category} {row.source_label}")
    target_ids = set(_split(row.target_inventory_ids))
    scored: dict[str, int] = {}
    for crosswalk_row in crosswalk.itertuples(index=False):
        if crosswalk_row.inventory_id not in target_ids:
            continue
        if crosswalk_row.match_status in {"excluded", "not_applicable"}:
            continue
        if (
            row.table_id == "13-15"
            and crosswalk_row.inventory_id == "bld_residential_cooking"
            and _match_text(crosswalk_row.capss_minor_category) not in search_text
        ):
            continue
        score = 0
        matched_below_major = False
        for field, weight in (
            ("capss_major_category", 1),
            ("capss_intermediate_category", 3),
            ("capss_minor_category", 5),
            ("capss_detail_category", 6),
        ):
            term = _match_text(getattr(crosswalk_row, field))
            if term and len(term) >= 2 and term in search_text:
                score += weight
                if field != "capss_major_category":
                    matched_below_major = True
        if matched_below_major:
            scored[crosswalk_row.inventory_id] = max(
                scored.get(crosswalk_row.inventory_id, 0),
                score,
            )
    if scored:
        maximum = max(scored.values())
        inventory_ids = sorted(
            inventory_id for inventory_id, score in scored.items() if score == maximum
        )
        return DELIMITER.join(inventory_ids), "capss_crosswalk_text_match"
    if len(target_ids) == 1:
        return next(iter(target_ids)), "single_target_scope"
    return "", "unresolved"


def _extract_tables_and_candidates(
    source_pdf: Path,
    table_index: pd.DataFrame,
    targets: pd.DataFrame,
    reference_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    target_inventory = targets.set_index("target_id")["inventory_ids"].to_dict()
    raw_path = output_dir / RAW_TABLE_FILE
    raw_count = 0
    candidates: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    with pdfplumber.open(source_pdf) as pdf, raw_path.open("w", encoding="utf-8") as stream:
        for row in table_index.itertuples(index=False):
            for pdf_page in range(int(row.pdf_page_first), int(row.pdf_page_last) + 1):
                page = pdf.pages[pdf_page - 1]
                table, status = _associate_table(page, row.table_id)
                if table is None:
                    issues.append(
                        {
                            "target_id": row.target_id,
                            "table_id": row.table_id,
                            "pdf_page": pdf_page,
                            "code": status,
                            "message": "No bordered PDF table was found below the indexed title.",
                        }
                    )
                    continue
                matrix = _table_matrix(page, table)
                unit_lines = _unit_lines(page, table.bbox)
                source_unit_text = " | ".join(unit_lines)
                inventory_ids = target_inventory[row.target_id]
                stream.write(
                    json.dumps(
                        {
                            "source_id": "capss_handbook_vii",
                            "target_id": row.target_id,
                            "table_id": row.table_id,
                            "title": row.title,
                            "pdf_page": pdf_page,
                            "inventory_ids": _split(inventory_ids),
                            "source_unit_text": source_unit_text,
                            "table_bbox": [round(value, 2) for value in table.bbox],
                            "cells": matrix,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
                raw_count += 1
                candidates.extend(
                    _normalized_candidates(
                        target_id=row.target_id,
                        table_id=row.table_id,
                        title=row.title,
                        pdf_page=pdf_page,
                        inventory_ids=inventory_ids,
                        matrix=matrix,
                        source_unit_text=source_unit_text,
                    )
                )

    candidate_columns = (
        "candidate_id",
        "source_id",
        "target_id",
        "table_id",
        "title",
        "pdf_page",
        "source_row_number",
        "source_value_ordinal",
        "target_inventory_ids",
        "inventory_ids",
        "inventory_match_status",
        "source_category",
        "source_label",
        "pollutant",
        "ef_value",
        "ef_expression",
        "raw_factor",
        "unit",
        "unit_status",
        "source_unit_text",
        "alignment_status",
        "review_status",
        "production_ready",
    )
    candidate_frame = pd.DataFrame(candidates)
    if candidate_frame.empty:
        candidate_frame = pd.DataFrame(columns=candidate_columns)
    else:
        candidate_frame.insert(
            0,
            "candidate_id",
            [f"CAPSSVII{number:06d}" for number in range(1, len(candidate_frame) + 1)],
        )
        candidate_frame.insert(1, "source_id", "capss_handbook_vii")
        crosswalk = pd.read_csv(
            reference_dir / "gcam_capss_nonpower_crosswalk.csv",
            dtype=str,
            keep_default_na=False,
        )
        matches = [
            _candidate_inventory_match(row, crosswalk)
            for row in candidate_frame.itertuples(index=False)
        ]
        candidate_frame.insert(
            candidate_frame.columns.get_loc("target_inventory_ids") + 1,
            "inventory_ids",
            [item[0] for item in matches],
        )
        candidate_frame.insert(
            candidate_frame.columns.get_loc("inventory_ids") + 1,
            "inventory_match_status",
            [item[1] for item in matches],
        )
        candidate_frame = candidate_frame.loc[:, candidate_columns]
    candidate_frame.to_csv(output_dir / CANDIDATE_FILE, index=False, encoding="utf-8")

    denominators = pd.read_csv(
        reference_dir / "nonpower_ef_denominator_registry.csv",
        dtype=str,
        keep_default_na=False,
    )
    link_rows = []
    for candidate in candidate_frame.itertuples(index=False):
        for inventory_id in _split(candidate.inventory_ids):
            matches = denominators.loc[
                denominators["inventory_id"].eq(inventory_id)
                & denominators["pollutant"].eq(candidate.pollutant)
            ]
            denominator_ids = DELIMITER.join(sorted(matches["denominator_id"].tolist()))
            link_rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "inventory_id": inventory_id,
                    "pollutant": candidate.pollutant,
                    "table_id": candidate.table_id,
                    "pdf_page": candidate.pdf_page,
                    "denominator_ids": denominator_ids,
                    "denominator_match_status": (
                        "candidate_denominator" if denominator_ids else "missing_denominator"
                    ),
                    "unit": candidate.unit,
                    "unit_status": candidate.unit_status,
                    "alignment_status": candidate.alignment_status,
                    "review_status": candidate.review_status,
                    "production_ready": candidate.production_ready,
                }
            )
    links = pd.DataFrame(
        link_rows,
        columns=(
            "candidate_id",
            "inventory_id",
            "pollutant",
            "table_id",
            "pdf_page",
            "denominator_ids",
            "denominator_match_status",
            "unit",
            "unit_status",
            "alignment_status",
            "review_status",
            "production_ready",
        ),
    )
    links.to_csv(output_dir / LINK_FILE, index=False, encoding="utf-8")
    issue_frame = pd.DataFrame(
        issues,
        columns=("target_id", "table_id", "pdf_page", "code", "message"),
    )
    issue_frame.to_csv(output_dir / EXTRACTION_ISSUE_FILE, index=False, encoding="utf-8")
    return {
        "raw_table_occurrences_extracted": raw_count,
        "normalized_factor_candidates": int(len(candidate_frame)),
        "candidate_pollutant_counts": {
            key: int(value)
            for key, value in candidate_frame["pollutant"].value_counts().sort_index().items()
        },
        "aligned_factor_candidates": int(candidate_frame["alignment_status"].eq("aligned").sum()),
        "unit_resolved_factor_candidates": int(
            candidate_frame["unit_status"].ne("unresolved").sum()
        ),
        "inventory_factor_link_rows": int(len(links)),
        "inventory_ids_with_factor_candidates": int(links["inventory_id"].nunique()),
        "factor_candidates_with_inventory_match": int(
            candidate_frame["inventory_ids"].ne("").sum()
        ),
        "table_extraction_issue_count": int(len(issue_frame)),
        "candidate_outputs": {
            "raw_tables": raw_path.name,
            "factor_candidates": CANDIDATE_FILE,
            "inventory_factor_links": LINK_FILE,
            "extraction_issues": EXTRACTION_ISSUE_FILE,
        },
    }


def scrape_capss_vii(
    source_pdf: Path = DEFAULT_SOURCE_PDF,
    target_file: Path = DEFAULT_TARGET_FILE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    reference_dir: Path = NONPOWER_REFERENCE_DIR,
    *,
    verify_source: bool = False,
    official_source_url: str = OFFICIAL_SOURCE_PDF_URL,
) -> dict[str, object]:
    """Extract target pages, raw tables, normalized candidates, links, and provenance."""
    if not source_pdf.is_file():
        raise CapssExtractionError(f"CAPSS VII source PDF not found: {source_pdf}")
    targets, inventory = load_targets(target_file, reference_dir)
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

    extraction_summary = _extract_tables_and_candidates(
        source_pdf,
        table_index,
        targets,
        reference_dir,
        output_dir,
    )
    links = pd.read_csv(output_dir / LINK_FILE, dtype=str, keep_default_na=False)
    target_table_counts = table_index["target_id"].value_counts().to_dict()
    candidate_counts = (
        links.groupby("inventory_id")["candidate_id"].nunique().to_dict()
        if not links.empty
        else {}
    )
    candidate_pollutants = (
        links.groupby("inventory_id")["pollutant"]
        .agg(lambda values: DELIMITER.join(sorted(set(values))))
        .to_dict()
        if not links.empty
        else {}
    )
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
                "factor_candidate_count": candidate_counts.get(row.inventory_id, 0),
                "factor_candidate_pollutants": candidate_pollutants.get(row.inventory_id, ""),
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
        **extraction_summary,
        "outputs": {
            "page_text": pages_path.name,
            "table_index": table_index_path.name,
            "inventory_coverage": coverage_path.name,
            **extraction_summary["candidate_outputs"],
        },
        "method_note": (
            "Every indexed bordered table is preserved as raw cells. Standard pollutant-column "
            "tables are normalized into inventory-linked factor candidates. Candidates remain "
            "production_ready=false until source labels, units, controls, and model denominators "
            "are independently reviewed; missing factors are never interpreted as zero."
        ),
    }
    metadata.pop("candidate_outputs")
    if verify_source:
        metadata.update(verify_official_source(source_pdf, official_source_url))
    else:
        metadata.update(
            {
                "official_source_page": OFFICIAL_SOURCE_PAGE,
                "official_source_pdf_url": official_source_url,
                "official_source_verified": False,
            }
        )
    (output_dir / "capss_vii_nonpower_scrape.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape inventory-linked non-power emission-factor tables from CAPSS Handbook VII."
        )
    )
    parser.add_argument("--source-pdf", type=Path, default=DEFAULT_SOURCE_PDF)
    parser.add_argument("--target-file", type=Path, default=DEFAULT_TARGET_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reference-dir", type=Path, default=NONPOWER_REFERENCE_DIR)
    parser.add_argument(
        "--verify-official-source",
        action="store_true",
        help="Download the official PDF and require its SHA-256 to match the preserved source.",
    )
    parser.add_argument("--official-source-url", default=OFFICIAL_SOURCE_PDF_URL)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        metadata = scrape_capss_vii(
            args.source_pdf,
            args.target_file,
            args.output_dir,
            args.reference_dir,
            verify_source=args.verify_official_source,
            official_source_url=args.official_source_url,
        )
    except CapssExtractionError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
