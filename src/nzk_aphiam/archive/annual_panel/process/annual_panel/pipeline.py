"""Build annual plant-level generation, emissions, and emission factors."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

from nzk_aphiam.archive.annual_panel.process.crosswalk.builder import (
    company_keys,
    normalize_company,
    normalize_plant,
    similarity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[6]
SUPPORTING_DATA_DIR = PROJECT_ROOT / "data" / "interim" / "supporting"
DEFAULT_GENERATION_DIR = (
    SUPPORTING_DATA_DIR / "plant_rosters" / "epsis" / "raw" / "annual_generation"
)
DEFAULT_ROSTER_DIR = SUPPORTING_DATA_DIR / "plant_rosters" / "epsis" / "raw" / "annual"
DEFAULT_PLANTS_PATH = SUPPORTING_DATA_DIR / "crosswalks" / "thermal" / "epsis_thermal_plants.csv"
DEFAULT_LINKS_PATH = (
    SUPPORTING_DATA_DIR / "crosswalks" / "thermal" / "epsis_emissions_facility_links.csv"
)
DEFAULT_CLEANSYS_PATH = (
    SUPPORTING_DATA_DIR / "emissions" / "cleansys" / "raw" / "cleansys_annual_emissions_panel.csv"
)
DEFAULT_ENV_INFO_PATH = (
    SUPPORTING_DATA_DIR
    / "emissions"
    / "env_info"
    / "raw"
    / "env_info_power_emissions_2015_2024.csv"
)
DEFAULT_DIRECT_PATH = (
    PROJECT_ROOT / "data" / "kepco" / "processed" / "kepco_monthly_generation_emissions.csv"
)
DEFAULT_GENERATION_OVERRIDES = (
    PROJECT_ROOT / "docs" / "references" / "archive" / "annual_panel" / "generation_overrides.csv"
)
DEFAULT_DIRECT_LINKS = (
    PROJECT_ROOT
    / "docs"
    / "references"
    / "archive"
    / "annual_panel"
    / "direct_company_plant_links.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "archive" / "annual_plant"

POLLUTANTS = ("nox", "sox", "tsp")
THERMAL_TERMS = (
    "기력",
    "복합",
    "집단",
    "내연",
    "석탄",
    "LNG",
    "가스",
    "유류",
    "중유",
    "경유",
    "부생가스",
    "폐기물",
)
KHNP_CLEAN_GENERATION_TERMS = ("원자력", "수력", "양수")
UNIT_PATTERN = re.compile(r"(?:#\s*\d+)|(?:\d+\s*호기)|(?:\b(?:GT|ST)\s*#?\s*\d+)", re.I)
PLANT_TOTAL_PATTERN = re.compile(r"(?:C/C|열병합|복합)$", re.I)
FUEL_TOTAL_LABELS = {
    "태양광",
    "풍력",
    "바이오매스",
    "연료전지",
    "부생가스",
    "폐기물에너지",
    "신재생(기타)",
}
GENERIC_COMPANIES = {
    "",
    "기타사",
    "기타",
    "한전 및 자회사",
    "한전자회사",
    "한전",
}
KEPCO_OPERATOR_KEYS = {
    normalize_company(value)
    for value in (
        "한국전력",
        "한전",
        "한국남동발전",
        "남동발전",
        "한국남부발전",
        "남부발전",
        "남부발전㈜",
        "남부발전(주)",
        "코스포",
        "한국동서발전",
        "동서발전",
        "한국서부발전",
        "서부발전",
        "서부발전㈜",
        "한국중부발전",
        "중부발전",
        "중부발전㈜",
        "한국수력원자력",
        "한수원",
    )
}

GENERATION_AUDIT_COLUMNS = [
    "source_file",
    "source_row_id",
    "year",
    "original_label",
    "company",
    "fuel",
    "gross_generation",
    "net_generation",
    "row_class",
    "assigned_plant_id",
    "assignment_method",
    "included_in_plant_total",
    "exclusion_reason",
    "confidence",
    "notes",
]

GENERATION_COLUMNS = [
    "year",
    "plant_id",
    "canonical_plant_name",
    "company",
    "operator_category",
    "fuel",
    "generation_mwh",
    "gross_generation_mwh",
    "net_generation_mwh",
    "generation_measure",
    "generation_assignment_method",
    "generation_source",
    "source_row_count",
    "classification_confidence",
    "review_required",
    "notes",
]

EMISSIONS_CANDIDATE_COLUMNS = [
    "year",
    "plant_id",
    "pollutant",
    "source",
    "source_facility_id",
    "source_facility_name",
    "emissions_kg",
    "match_confidence",
    "record_scope",
    "review_required",
    "notes",
]

EMISSIONS_COMPARISON_COLUMNS = [
    "year",
    "plant_id",
    "pollutant",
    "direct_company_kg",
    "cleansys_kg",
    "env_info_kg",
    "selected_emissions_kg",
    "selected_source",
    "selection_rule",
    "difference_abs_kg",
    "difference_pct",
    "review_required",
    "notes",
]

FINAL_COLUMNS = [
    "year",
    "plant_id",
    "plant",
    "company",
    "operator_category",
    "fuel",
    "generation_mwh",
    "nox_kg",
    "sox_kg",
    "tsp_kg",
    "nox_kg_per_mwh",
    "sox_kg_per_mwh",
    "tsp_kg_per_mwh",
    "generation_source",
    "nox_source",
    "sox_source",
    "tsp_source",
    "generation_confidence",
    "emissions_confidence",
    "review_required",
    "validation_flags",
]

FUEL_VALIDATION_COLUMNS = [
    "year",
    "plant_id",
    "plant",
    "company",
    "panel_fuel",
    "roster_fuel",
    "panel_fuel_normalized",
    "roster_fuel_normalized",
    "validation_status",
    "source",
    "notes",
]

FUEL_ALIASES = {
    "LNG": "natural_gas",
    "가스": "natural_gas",
    "천연가스": "natural_gas",
    "유연탄": "bituminous_coal",
    "역청탄": "bituminous_coal",
    "석탄": "bituminous_coal",
    "무연탄": "anthracite",
    "중유": "heavy_oil",
    "B-C": "heavy_oil",
    "BC": "heavy_oil",
    "LSWR": "heavy_oil",
    "유류": "heavy_oil",
    "경유": "diesel",
    "LPG*": "lpg",
    "LPG": "lpg",
    "바이오중유": "bio_heavy_oil",
    "바이오": "bio",
    "원자력": "nuclear",
    "농축U": "nuclear",
    "천연U": "nuclear",
    "수력": "hydro",
    "일반수력": "hydro",
    "소수력": "small_hydro",
    "양수": "pumped_hydro",
    "기타": "other",
    "-": "missing",
}


@dataclass(frozen=True)
class Plant:
    identifier: str
    name: str
    operator: str
    operator_key: str
    plant_key: str
    first_year: int
    last_year: int
    fuels: str


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    if cleaned in {"", "-", "nan", "None"}:
        return None
    parsed = float(cleaned)
    return parsed if math.isfinite(parsed) else None


def operator_category(company: str) -> str:
    """Classify EPSIS operators into the current KEPCO/non-KEPCO split."""
    return "kepco" if normalize_company(company) in KEPCO_OPERATOR_KEYS else "private_or_other"


def is_thermal_generation_row(row: dict[str, str]) -> bool:
    text = " ".join(
        row.get(column, "") for column in ("generation_source", "fuel_group", "fuel_detail")
    )
    return any(term.lower() in text.lower() for term in THERMAL_TERMS)


def is_khnp_clean_generation_row(row: dict[str, str]) -> bool:
    text = " ".join(
        row.get(column, "") for column in ("generation_source", "fuel_group", "fuel_detail")
    )
    return normalize_company(row.get("company", "")) == "한국수력원자력" and any(
        term in text for term in KHNP_CLEAN_GENERATION_TERMS
    )


def is_generation_row_in_scope(row: dict[str, str]) -> bool:
    return is_thermal_generation_row(row) or is_khnp_clean_generation_row(row)


def classify_generation_row(row: dict[str, str]) -> tuple[str, str]:
    """Classify one EPSIS annual-generation row without assigning it."""
    label = row["source_record_name"].strip()
    if label.startswith("[PPA]"):
        return "company_total", "PPA portfolio aggregate"
    if label.startswith("기타 ") or label == "기타":
        return "other_aggregate", "provider residual aggregate"
    if label in FUEL_TOTAL_LABELS:
        return "fuel_total", "fuel/technology aggregate label"
    if label.endswith("계"):
        if any(term in label for term in ("양수", "발전소")):
            return "plant_total", "explicit plant total suffix"
        return "other_aggregate", "provider total label"
    if UNIT_PATTERN.search(label):
        return "unit", "explicit unit designator"
    if PLANT_TOTAL_PATTERN.search(label) or "열병합" in label:
        return "plant_total", "explicit plant-level technology label"
    if row.get("company", "") in {"한전 및 자회사", "기타사"} and label in FUEL_TOTAL_LABELS:
        return "fuel_total", "company-category fuel total"
    if is_thermal_generation_row(row):
        return "plant_total", "thermal label without a unit designator"
    if is_khnp_clean_generation_row(row):
        return "plant_total", "KHNP nuclear/hydro plant label"
    return "unresolved", "not a thermal plant row"


def load_plants(path: Path) -> list[Plant]:
    return [
        Plant(
            identifier=row["epsis_plant_id"],
            name=row["epsis_plant_name"],
            operator=row["epsis_operator"],
            operator_key=row["epsis_operator_key"],
            plant_key=row["epsis_plant_key"],
            first_year=int(row["first_year"]),
            last_year=int(row["last_year"]),
            fuels=row["fuels"],
        )
        for row in read_csv(path)
    ]


def fuel_tokens(value: str) -> set[str]:
    return {token.strip() for token in value.split("|") if token.strip()}


def normalized_fuel_tokens(value: str) -> set[str]:
    return {
        FUEL_ALIASES.get(token, token)
        for token in fuel_tokens(value)
        if FUEL_ALIASES.get(token, token) != "missing"
    }


def validation_status(panel_fuel: str, roster_fuel: str) -> tuple[str, str]:
    panel_raw = fuel_tokens(panel_fuel)
    roster_raw = fuel_tokens(roster_fuel)
    panel_normalized = normalized_fuel_tokens(panel_fuel)
    roster_normalized = normalized_fuel_tokens(roster_fuel)
    if not roster_raw or roster_raw == {"-"}:
        return "no_roster_fuel", "EPSIS roster has no usable fuel value for this plant-year"
    if panel_raw == roster_raw:
        return "exact_match", ""
    if panel_normalized == roster_normalized:
        return "alias_match", "Fuel labels differ but map to the same normalized fuel class"
    if panel_normalized and roster_normalized and panel_normalized <= roster_normalized:
        return "panel_subset_of_roster", "Panel fuel is covered by the broader roster fuel set"
    if panel_normalized and roster_normalized and roster_normalized <= panel_normalized:
        return "roster_subset_of_panel", "Roster fuel is covered by the broader panel fuel set"
    if panel_normalized & roster_normalized:
        return "partial_overlap", "Panel and roster fuel sets share at least one fuel class"
    return "mismatch", "Panel fuel does not match the external EPSIS roster fuel class"


def find_roster_plant(row: dict[str, str], plants: list[Plant]) -> Plant | None:
    year = int(row["year"])
    plant_key = normalize_plant(row["plant_name"])
    operator_key = normalize_company(row["generation_company"])
    active = [
        plant
        for plant in plants
        if plant.first_year <= year <= plant.last_year and plant.plant_key == plant_key
    ]
    exact = [plant for plant in active if plant.operator_key == operator_key]
    if len(exact) == 1:
        return exact[0]
    if len(active) == 1:
        return active[0]
    return None


def build_roster_fuels_by_plant_year(
    roster_dir: Path,
    plants: list[Plant],
) -> dict[tuple[int, str], set[str]]:
    fuels_by_key: dict[tuple[int, str], set[str]] = {}
    for path in sorted(roster_dir.glob("epsis_generator_roster_*.csv")):
        if path.name.endswith("_raw.js"):
            continue
        for row in read_csv(path):
            if not (is_thermal_roster_row(row) or is_khnp_clean_roster_row(row)):
                continue
            plant = find_roster_plant(row, plants)
            if plant is None:
                continue
            fuels_by_key.setdefault((int(row["year"]), plant.identifier), set()).update(
                fuel_tokens(row["fuel"])
            )
    return fuels_by_key


def is_thermal_roster_row(row: dict[str, str]) -> bool:
    text = " ".join(
        row.get(column, "") for column in ("generation_source", "generation_type", "fuel")
    )
    return any(term.lower() in text.lower() for term in THERMAL_TERMS)


def is_khnp_clean_roster_row(row: dict[str, str]) -> bool:
    text = " ".join(
        row.get(column, "") for column in ("generation_source", "generation_type", "fuel")
    )
    return normalize_company(row.get("generation_company", "")) == "한국수력원자력" and any(
        term in text for term in KHNP_CLEAN_GENERATION_TERMS
    )


def validate_fuels_against_roster(
    final: list[dict[str, Any]],
    roster_dir: Path,
    plants: list[Plant],
) -> list[dict[str, Any]]:
    roster_fuels = build_roster_fuels_by_plant_year(roster_dir, plants)
    rows: list[dict[str, Any]] = []
    for row in final:
        key = (int(row["year"]), row["plant_id"])
        roster_fuel = " | ".join(sorted(roster_fuels.get(key, set())))
        status, notes = validation_status(str(row["fuel"]), roster_fuel)
        rows.append(
            {
                "year": row["year"],
                "plant_id": row["plant_id"],
                "plant": row["plant"],
                "company": row["company"],
                "panel_fuel": row["fuel"],
                "roster_fuel": roster_fuel,
                "panel_fuel_normalized": " | ".join(sorted(normalized_fuel_tokens(row["fuel"]))),
                "roster_fuel_normalized": " | ".join(sorted(normalized_fuel_tokens(roster_fuel))),
                "validation_status": status,
                "source": "KPX EPSIS annual generator roster",
                "notes": notes,
            }
        )
    return rows


def load_generation_overrides(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    result: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in read_csv(path):
        result[(row["year"], row["source_label"], row["company"])] = row
    return result


def find_override(
    row: dict[str, str],
    overrides: dict[tuple[str, str, str], dict[str, str]],
) -> dict[str, str] | None:
    exact = (row["year"], row["source_record_name"], row["company"])
    all_years = ("", row["source_record_name"], row["company"])
    return overrides.get(exact) or overrides.get(all_years)


def assign_generation_row(
    row: dict[str, str],
    row_class: str,
    plants: list[Plant],
    overrides: dict[tuple[str, str, str], dict[str, str]],
) -> tuple[str, str, str, str]:
    """Return plant ID, method, confidence, and notes."""
    override = find_override(row, overrides)
    if override:
        if override["action"] == "exclude":
            return "", "manual_exclusion", "high", override["notes"]
        plant = next(
            (plant for plant in plants if plant.identifier == override["plant_id"]),
            None,
        )
        if plant is None:
            raise RuntimeError(f"Unknown generation override plant ID: {override['plant_id']}")
        year = int(row["year"])
        if not plant.first_year <= year <= plant.last_year:
            return "", "manual_override_outside_roster_years", "low", override["notes"]
        return plant.identifier, "manual_override", "high", override["notes"]

    if row_class not in {"unit", "plant_total"}:
        return "", "not_assignable", "high", ""

    year = int(row["year"])
    key = normalize_plant(row["source_record_name"])
    active = [plant for plant in plants if plant.first_year <= year <= plant.last_year]
    exact = [plant for plant in active if plant.plant_key == key]
    company = normalize_company(row["company"])
    company_is_generic = row["company"] in GENERIC_COMPANIES or company in GENERIC_COMPANIES
    if len(exact) > 1 and not company_is_generic:
        company_exact = [plant for plant in exact if plant.operator_key == company]
        if len(company_exact) == 1:
            return company_exact[0].identifier, "exact_plant_and_company", "high", ""
    if len(exact) == 1:
        return exact[0].identifier, "exact_plant_key", "high", ""

    scored: list[tuple[float, Plant]] = []
    for plant in active:
        plant_score = similarity(key, plant.plant_key)
        if plant_score < 0.72:
            continue
        company_score = (
            0.0
            if company_is_generic
            else max(
                [similarity(company, candidate) for candidate in company_keys(plant.operator)]
                + [similarity(company, plant.operator_key)]
            )
        )
        score = plant_score if company_is_generic else 0.7 * plant_score + 0.3 * company_score
        scored.append((score, plant))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored:
        margin = scored[0][0] - (scored[1][0] if len(scored) > 1 else 0.0)
        threshold = 0.9 if company_is_generic else 0.84
        if scored[0][0] >= threshold and margin >= 0.08:
            return scored[0][1].identifier, "fuzzy_unique", "medium", ""
    return "", "unresolved", "low", "No unique year-valid roster plant match"


def build_generation(
    generation_dir: Path,
    plants_path: Path,
    overrides_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    plants = load_plants(plants_path)
    plants_by_id = {plant.identifier: plant for plant in plants}
    overrides = load_generation_overrides(overrides_path)
    audits: list[dict[str, Any]] = []
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}

    for path in sorted(generation_dir.glob("epsis_generator_generation_*.csv")):
        for index, row in enumerate(read_csv(path), start=1):
            row_class, class_note = classify_generation_row(row)
            plant_id, method, confidence, assignment_note = assign_generation_row(
                row, row_class, plants, overrides
            )
            gross = number(row["gross_generation_mwh"])
            net = number(row["net_generation_mwh"])
            exclusion = ""
            if not is_generation_row_in_scope(row):
                exclusion = "out_of_scope_generation_type"
                plant_id = ""
            elif row_class not in {"unit", "plant_total"}:
                exclusion = row_class
            elif not plant_id:
                exclusion = "unresolved_plant_assignment"
            elif gross is None or gross < 0:
                exclusion = "missing_or_negative_gross_generation"

            audit = {
                "source_file": path.name,
                "source_row_id": f"{path.stem}:{index}",
                "year": row["year"],
                "original_label": row["source_record_name"],
                "company": row["company"],
                "fuel": row["fuel_detail"],
                "gross_generation": "" if gross is None else gross,
                "net_generation": "" if net is None else net,
                "row_class": row_class,
                "assigned_plant_id": plant_id,
                "assignment_method": method,
                "included_in_plant_total": False,
                "exclusion_reason": exclusion,
                "confidence": confidence,
                "notes": "; ".join(note for note in (class_note, assignment_note) if note),
                "_row": row,
                "_audit_index": len(audits),
            }
            audits.append(audit)
            if plant_id and not exclusion:
                grouped.setdefault((int(row["year"]), plant_id), []).append(audit)

    generation_rows: list[dict[str, Any]] = []
    for (year, plant_id), rows in sorted(grouped.items()):
        plant_totals = [row for row in rows if row["row_class"] == "plant_total"]
        units = [row for row in rows if row["row_class"] == "unit"]
        notes: list[str] = []
        review = False
        if len(plant_totals) == 1:
            selected = plant_totals
            method = "explicit_plant_total"
            if units:
                notes.append("Unit rows excluded because an explicit plant total is available")
        elif not plant_totals and units:
            selected = units
            method = "sum_generating_units"
        elif len(plant_totals) > 1:
            labels = {row["original_label"] for row in plant_totals}
            fuels = {row["fuel"] for row in plant_totals}
            if len(labels) == 1 and len(fuels) == len(plant_totals):
                selected = plant_totals
                method = "sum_fuel_partitioned_plant_totals"
                notes.append("Provider split one explicit plant total across distinct fuels")
            else:
                selected = []
                method = "ambiguous_multiple_plant_totals"
                review = True
                notes.append("Multiple plant-total rows prevent deterministic selection")
        else:
            selected = []
            method = "no_usable_rows"
            review = True

        for row in selected:
            audits[row["_audit_index"]]["included_in_plant_total"] = True
        for row in rows:
            if row not in selected and not row["exclusion_reason"]:
                audits[row["_audit_index"]]["exclusion_reason"] = (
                    "component_excluded_for_explicit_plant_total"
                    if plant_totals and units
                    else "ambiguous_duplicate_plant_total"
                )

        if not selected:
            continue
        gross_values = [float(row["gross_generation"]) for row in selected]
        net_values = [
            float(row["net_generation"]) for row in selected if row["net_generation"] != ""
        ]
        source_rows = [row["_row"] for row in selected]
        confidence = "high" if all(row["confidence"] == "high" for row in selected) else "medium"
        generation_rows.append(
            {
                "year": year,
                "plant_id": plant_id,
                "canonical_plant_name": plants_by_id[plant_id].name,
                "company": plants_by_id[plant_id].operator,
                "operator_category": operator_category(plants_by_id[plant_id].operator),
                "fuel": " | ".join(sorted({row["fuel_detail"] for row in source_rows})),
                "generation_mwh": sum(gross_values),
                "gross_generation_mwh": sum(gross_values),
                "net_generation_mwh": sum(net_values) if len(net_values) == len(selected) else "",
                "generation_measure": "gross_generation_mwh",
                "generation_assignment_method": method,
                "generation_source": "KPX EPSIS annual generation",
                "source_row_count": len(selected),
                "classification_confidence": confidence,
                "review_required": review or confidence != "high",
                "notes": "; ".join(notes),
            }
        )

    clean_audits = [{key: row[key] for key in GENERATION_AUDIT_COLUMNS} for row in audits]
    review_rows = [
        row
        for row in clean_audits
        if row["confidence"] == "low"
        or row["row_class"] == "unresolved"
        or row["exclusion_reason"]
        in {
            "unresolved_plant_assignment",
            "ambiguous_duplicate_plant_total",
        }
    ]
    return generation_rows, clean_audits, review_rows


def confidence_from_status(status: str) -> str:
    return {
        "manual": "high",
        "manual_historical": "high",
        "automatic": "high",
        "probable": "medium",
    }.get(status, "low")


def build_direct_candidates(
    path: Path,
    links_path: Path,
    plants: dict[str, Plant],
    start_year: int,
    end_year: int,
) -> list[dict[str, Any]]:
    links = {
        (row["source_dataset"], row["source_plant_name"]): row for row in read_csv(links_path)
    }
    grouped: dict[tuple[int, str, str], list[float]] = {}
    names: dict[tuple[int, str, str], str] = {}
    for row in read_csv(path):
        year = int(row["date"][:4])
        if not start_year <= year <= end_year:
            continue
        link = links.get((row["source_dataset"], row["plant_name"]))
        if not link:
            continue
        plant_id = link["plant_id"]
        if (
            plant_id not in plants
            or not plants[plant_id].first_year <= year <= plants[plant_id].last_year
        ):
            continue
        for source_column, pollutant in (
            ("nox", "nox"),
            ("sox", "sox"),
            ("dust_tsp", "tsp"),
        ):
            value = number(row[source_column])
            if value is None:
                continue
            key = (year, plant_id, pollutant)
            grouped.setdefault(key, []).append(value)
            names[key] = row["plant_name"]

    return [
        {
            "year": year,
            "plant_id": plant_id,
            "pollutant": pollutant,
            "source": "direct_company",
            "source_facility_id": "",
            "source_facility_name": names[(year, plant_id, pollutant)],
            "emissions_kg": sum(values),
            "match_confidence": "high",
            "record_scope": "direct_plant",
            "review_required": False,
            "notes": "Annual sum of source monthly plant/unit pollutant-mass rows",
        }
        for (year, plant_id, pollutant), values in sorted(grouped.items())
    ]


def build_facility_candidates(
    links_path: Path,
    cleansys_path: Path,
    env_info_path: Path,
) -> list[dict[str, Any]]:
    links = read_csv(links_path)
    mapping_counts: dict[tuple[str, str], int] = {}
    for link in links:
        key = (link["source"], link["facility_id"])
        mapping_counts[key] = mapping_counts.get(key, 0) + 1

    clean_rows: dict[str, list[dict[str, str]]] = {}
    for row in read_csv(cleansys_path):
        clean_rows.setdefault(row["facility_code"], []).append(row)
    env_rows: dict[str, list[dict[str, str]]] = {}
    for row in read_csv(env_info_path):
        env_rows.setdefault(row["record_id"], []).append(row)

    candidates: list[dict[str, Any]] = []
    for link in links:
        source = link["source"]
        facility_id = link["facility_id"]
        many_to_many = mapping_counts[(source, facility_id)] > 1
        rows = (
            clean_rows.get(facility_id, [])
            if source == "cleansys"
            else env_rows.get(facility_id, [])
        )
        if not rows:
            raise RuntimeError(
                f"Crosswalk facility ID is absent from {source} input: {facility_id}"
            )
        for row in rows:
            if source == "cleansys":
                values = {
                    "nox": number(row["nox_kg"]),
                    "sox": number(row["sox_kg"]),
                    "tsp": number(row["tsp_kg"]),
                }
                scope = "individual_facility"
                facility_name = row["facility_name"]
            else:
                values = {
                    "nox": (
                        None
                        if number(row["nox_tonnes"]) is None
                        else number(row["nox_tonnes"]) * 1000
                    ),
                    "sox": (
                        None
                        if number(row["sox_tonnes"]) is None
                        else number(row["sox_tonnes"]) * 1000
                    ),
                    "tsp": (
                        None
                        if number(row["tsp_tonnes"]) is None
                        else number(row["tsp_tonnes"]) * 1000
                    ),
                }
                scope = (
                    "individual_site" if row["record_type"] == "사업장" else "representative_site"
                )
                facility_name = row["facility_name"]
            for pollutant, value in values.items():
                if value is None:
                    continue
                reasons: list[str] = []
                if many_to_many:
                    reasons.append("facility_maps_to_multiple_plants")
                if source == "env_info" and scope != "individual_site":
                    reasons.append("representative_or_parent_scope")
                if link["boundary_flag"]:
                    reasons.append(link["boundary_flag"])
                confidence = confidence_from_status(link["link_status"])
                if confidence == "medium":
                    reasons.append("probable_crosswalk")
                candidates.append(
                    {
                        "year": int(row["year"]),
                        "plant_id": link["epsis_plant_id"],
                        "pollutant": pollutant,
                        "source": source,
                        "source_facility_id": facility_id,
                        "source_facility_name": facility_name,
                        "emissions_kg": value,
                        "match_confidence": confidence,
                        "record_scope": scope,
                        "review_required": bool(reasons),
                        "notes": "; ".join(reasons),
                    }
                )
    return candidates


def collapse_source_candidates(
    candidates: list[dict[str, Any]],
) -> tuple[dict[tuple[int, str, str, str], float], set[tuple[int, str, str, str]]]:
    grouped: dict[tuple[int, str, str, str], list[dict[str, Any]]] = {}
    for row in candidates:
        key = (row["year"], row["plant_id"], row["pollutant"], row["source"])
        grouped.setdefault(key, []).append(row)
    values: dict[tuple[int, str, str, str], float] = {}
    rejected: set[tuple[int, str, str, str]] = set()
    for key, rows in grouped.items():
        valid = [row for row in rows if not row["review_required"]]
        facility_ids = {row["source_facility_id"] for row in valid}
        if len(valid) == 1 or (key[3] == "direct_company" and valid):
            values[key] = sum(float(row["emissions_kg"]) for row in valid)
        elif valid and len(facility_ids) == 1:
            values[key] = sum(float(row["emissions_kg"]) for row in valid)
        elif valid:
            rejected.add(key)
    return values, rejected


def reconcile_emissions(
    candidates: list[dict[str, Any]],
    disagreement_threshold: float,
) -> list[dict[str, Any]]:
    values, rejected = collapse_source_candidates(candidates)
    keys = sorted({key[:3] for key in values} | {key[:3] for key in rejected})
    rows: list[dict[str, Any]] = []
    for year, plant_id, pollutant in keys:
        source_values = {
            source: values.get((year, plant_id, pollutant, source))
            for source in ("direct_company", "cleansys", "env_info")
        }
        selected_source = next(
            (
                source
                for source in ("direct_company", "cleansys", "env_info")
                if source_values[source] is not None
            ),
            "",
        )
        selected = source_values.get(selected_source) if selected_source else None
        available = [value for value in source_values.values() if value is not None]
        difference_abs = max(available) - min(available) if len(available) >= 2 else None
        difference_pct = (
            difference_abs / max(available)
            if difference_abs is not None and max(available) > 0
            else None
        )
        review = bool(
            any((year, plant_id, pollutant, source) in rejected for source in source_values)
            or (difference_pct is not None and difference_pct > disagreement_threshold)
        )
        notes: list[str] = []
        if difference_pct is not None and difference_pct > disagreement_threshold:
            notes.append("large_source_disagreement")
        if any((year, plant_id, pollutant, source) in rejected for source in source_values):
            notes.append("overlapping_or_ambiguous_source_facilities")
        rows.append(
            {
                "year": year,
                "plant_id": plant_id,
                "pollutant": pollutant,
                "direct_company_kg": (
                    ""
                    if source_values["direct_company"] is None
                    else source_values["direct_company"]
                ),
                "cleansys_kg": (
                    "" if source_values["cleansys"] is None else source_values["cleansys"]
                ),
                "env_info_kg": (
                    "" if source_values["env_info"] is None else source_values["env_info"]
                ),
                "selected_emissions_kg": "" if selected is None else selected,
                "selected_source": selected_source,
                "selection_rule": (
                    "direct_company>cleansys>env_info_individual_site"
                    if selected_source
                    else "no_eligible_source"
                ),
                "difference_abs_kg": "" if difference_abs is None else difference_abs,
                "difference_pct": "" if difference_pct is None else difference_pct,
                "review_required": review,
                "notes": "; ".join(notes),
            }
        )
    return rows


def factor(value: float | None, generation: float | None) -> float | str:
    if value is None or generation is None or generation <= 0:
        return ""
    return value / generation


def build_final_panel(
    generation: list[dict[str, Any]],
    emissions: list[dict[str, Any]],
    plants: dict[str, Plant],
    extreme_thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    generation_by_key = {(row["year"], row["plant_id"]): row for row in generation}
    emissions_by_key = {(row["year"], row["plant_id"], row["pollutant"]): row for row in emissions}
    keys = sorted(set(generation_by_key) | {(row["year"], row["plant_id"]) for row in emissions})
    result: list[dict[str, Any]] = []
    previous_generation: dict[str, tuple[int, float]] = {}
    previous_emissions: dict[tuple[str, str], tuple[int, float]] = {}
    for year, plant_id in keys:
        generation_row = generation_by_key.get((year, plant_id))
        generation_value = float(generation_row["generation_mwh"]) if generation_row else None
        pollutant_values: dict[str, float | None] = {}
        pollutant_sources: dict[str, str] = {}
        emission_reviews: list[bool] = []
        flags: list[str] = []
        for pollutant in POLLUTANTS:
            row = emissions_by_key.get((year, plant_id, pollutant))
            pollutant_values[pollutant] = (
                float(row["selected_emissions_kg"])
                if row and row["selected_emissions_kg"] != ""
                else None
            )
            pollutant_sources[pollutant] = row["selected_source"] if row else ""
            emission_reviews.append(bool(row and row["review_required"]))
            ef = factor(pollutant_values[pollutant], generation_value)
            if ef != "" and float(ef) > extreme_thresholds[pollutant]:
                flags.append(f"extreme_{pollutant}_factor")
            value = pollutant_values[pollutant]
            previous_pollutant = previous_emissions.get((plant_id, pollutant))
            if previous_pollutant and value is not None and previous_pollutant[1] > 0:
                ratio = value / previous_pollutant[1]
                if ratio > 5 or ratio < 0.2:
                    flags.append(f"large_year_to_year_{pollutant}_change")
            if value is not None:
                previous_emissions[(plant_id, pollutant)] = (year, value)
        plant = plants[plant_id]
        if not plant.first_year <= year <= plant.last_year:
            flags.append("outside_roster_operating_years")
        if generation_value is not None and generation_value < 0:
            flags.append("negative_generation")
        if any(value is not None and value < 0 for value in pollutant_values.values()):
            flags.append("negative_emissions")
        previous = previous_generation.get(plant_id)
        if previous and generation_value is not None and previous[1] > 0:
            ratio = generation_value / previous[1]
            if ratio > 5 or ratio < 0.2:
                flags.append("large_year_to_year_generation_change")
        if generation_value is not None:
            previous_generation[plant_id] = (year, generation_value)
        row = {
            "year": year,
            "plant_id": plant_id,
            "plant": plant.name,
            "company": plant.operator,
            "operator_category": operator_category(plant.operator),
            "fuel": generation_row["fuel"] if generation_row else plant.fuels,
            "generation_mwh": "" if generation_value is None else generation_value,
            "nox_kg": ("" if pollutant_values["nox"] is None else pollutant_values["nox"]),
            "sox_kg": ("" if pollutant_values["sox"] is None else pollutant_values["sox"]),
            "tsp_kg": ("" if pollutant_values["tsp"] is None else pollutant_values["tsp"]),
            "nox_kg_per_mwh": factor(pollutant_values["nox"], generation_value),
            "sox_kg_per_mwh": factor(pollutant_values["sox"], generation_value),
            "tsp_kg_per_mwh": factor(pollutant_values["tsp"], generation_value),
            "generation_source": generation_row["generation_source"] if generation_row else "",
            "nox_source": pollutant_sources["nox"],
            "sox_source": pollutant_sources["sox"],
            "tsp_source": pollutant_sources["tsp"],
            "generation_confidence": (
                generation_row["classification_confidence"] if generation_row else ""
            ),
            "emissions_confidence": (
                "review"
                if any(emission_reviews)
                else "high"
                if any(pollutant_sources.values())
                else ""
            ),
            "review_required": bool(
                flags
                or any(emission_reviews)
                or (generation_row and generation_row["review_required"])
            ),
            "validation_flags": "; ".join(sorted(set(flags))),
        }
        result.append(row)
    return result


def validate_outputs(
    generation: list[dict[str, Any]],
    generation_audit: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    emissions: list[dict[str, Any]],
    final: list[dict[str, Any]],
) -> dict[str, int]:
    generation_keys = [(row["year"], row["plant_id"]) for row in generation]
    emissions_keys = [(row["year"], row["plant_id"], row["pollutant"]) for row in emissions]
    final_keys = [(row["year"], row["plant_id"]) for row in final]
    included_classes: dict[tuple[str, str], set[str]] = {}
    for row in generation_audit:
        if row["included_in_plant_total"]:
            included_classes.setdefault(
                (str(row["year"]), str(row["assigned_plant_id"])), set()
            ).add(str(row["row_class"]))
    checks = {
        "duplicate_generation_keys": len(generation_keys) - len(set(generation_keys)),
        "duplicate_selected_emissions_keys": len(emissions_keys) - len(set(emissions_keys)),
        "duplicate_final_keys": len(final_keys) - len(set(final_keys)),
        "negative_generation_rows": sum(float(row["generation_mwh"]) < 0 for row in generation),
        "negative_selected_emissions_rows": sum(
            row["selected_emissions_kg"] != "" and float(row["selected_emissions_kg"]) < 0
            for row in emissions
        ),
        "mixed_unit_and_plant_total_contributions": sum(
            classes == {"unit", "plant_total"} for classes in included_classes.values()
        ),
        "ambiguous_facility_candidate_rows": sum(
            "facility_maps_to_multiple_plants" in str(row["notes"]) for row in candidates
        ),
        "company_aggregate_comparisons": 0,
        "company_aggregate_exceedances": 0,
    }
    fatal_checks = {
        key: value
        for key, value in checks.items()
        if key
        not in {
            "ambiguous_facility_candidate_rows",
            "company_aggregate_comparisons",
            "company_aggregate_exceedances",
        }
        and value
    }
    if fatal_checks:
        raise RuntimeError(f"Annual panel validation failed: {checks}")
    return checks


def build_annual_panel(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    disagreement_threshold: float = 0.5,
    extreme_nox_kg_per_mwh: float = 100.0,
    extreme_sox_kg_per_mwh: float = 100.0,
    extreme_tsp_kg_per_mwh: float = 20.0,
) -> dict[str, Any]:
    plants_list = load_plants(DEFAULT_PLANTS_PATH)
    plants = {plant.identifier: plant for plant in plants_list}
    generation, generation_audit, generation_review = build_generation(
        DEFAULT_GENERATION_DIR,
        DEFAULT_PLANTS_PATH,
        DEFAULT_GENERATION_OVERRIDES,
    )
    direct = build_direct_candidates(
        DEFAULT_DIRECT_PATH,
        DEFAULT_DIRECT_LINKS,
        plants,
        2015,
        2024,
    )
    facility = build_facility_candidates(
        DEFAULT_LINKS_PATH,
        DEFAULT_CLEANSYS_PATH,
        DEFAULT_ENV_INFO_PATH,
    )
    candidates = sorted(
        [*direct, *facility],
        key=lambda row: (
            row["year"],
            row["plant_id"],
            row["pollutant"],
            row["source"],
            row["source_facility_id"],
        ),
    )
    emissions = reconcile_emissions(candidates, disagreement_threshold)
    final = build_final_panel(
        generation,
        emissions,
        plants,
        {
            "nox": extreme_nox_kg_per_mwh,
            "sox": extreme_sox_kg_per_mwh,
            "tsp": extreme_tsp_kg_per_mwh,
        },
    )
    fuel_validation = validate_fuels_against_roster(final, DEFAULT_ROSTER_DIR, plants_list)
    checks = validate_outputs(generation, generation_audit, candidates, emissions, final)

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "generation": output_dir / "epsis_annual_plant_generation.csv",
        "generation_audit": output_dir / "epsis_generation_row_audit.csv",
        "generation_review": output_dir / "epsis_generation_review.csv",
        "emissions_candidates": output_dir / "annual_emissions_candidates.csv",
        "emissions_comparison": output_dir / "annual_emissions_comparison.csv",
        "final": output_dir / "annual_plant_generation_emissions.csv",
        "fuel_validation": output_dir / "annual_fuel_validation.csv",
    }
    write_csv(paths["generation"], GENERATION_COLUMNS, generation)
    write_csv(paths["generation_audit"], GENERATION_AUDIT_COLUMNS, generation_audit)
    write_csv(paths["generation_review"], GENERATION_AUDIT_COLUMNS, generation_review)
    write_csv(paths["emissions_candidates"], EMISSIONS_CANDIDATE_COLUMNS, candidates)
    write_csv(paths["emissions_comparison"], EMISSIONS_COMPARISON_COLUMNS, emissions)
    write_csv(paths["final"], FINAL_COLUMNS, final)
    write_csv(paths["fuel_validation"], FUEL_VALIDATION_COLUMNS, fuel_validation)

    metadata = {
        "dataset": "Korean annual thermal plant generation and air emissions",
        "method_version": 2,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "generation_measure": "gross_generation_mwh",
        "source_precedence": ["direct_company", "cleansys", "env_info_individual_site"],
        "disagreement_threshold": disagreement_threshold,
        "extreme_factor_thresholds_kg_per_mwh": {
            "nox": extreme_nox_kg_per_mwh,
            "sox": extreme_sox_kg_per_mwh,
            "tsp": extreme_tsp_kg_per_mwh,
        },
        "counts": {
            "generation_rows": len(generation),
            "generation_audit_rows": len(generation_audit),
            "generation_review_rows": len(generation_review),
            "emissions_candidate_rows": len(candidates),
            "emissions_comparison_rows": len(emissions),
            "final_rows": len(final),
            "final_review_rows": sum(bool(row["review_required"]) for row in final),
            "fuel_validation_rows": len(fuel_validation),
        },
        "coverage": {
            "generation_by_year": {
                str(year): sum(row["year"] == year for row in generation)
                for year in sorted({row["year"] for row in generation})
            },
            "generation_by_company": {
                company: sum(row["company"] == company for row in generation)
                for company in sorted({row["company"] for row in generation})
            },
            "generation_by_operator_category": {
                category: sum(row["operator_category"] == category for row in generation)
                for category in sorted({row["operator_category"] for row in generation})
            },
            "generation_by_fuel": {
                fuel: sum(row["fuel"] == fuel for row in generation)
                for fuel in sorted({row["fuel"] for row in generation})
            },
            "selected_emissions_by_pollutant": {
                pollutant: sum(
                    row["pollutant"] == pollutant and row["selected_emissions_kg"] != ""
                    for row in emissions
                )
                for pollutant in POLLUTANTS
            },
            "selected_emissions_by_source": {
                source: sum(row["selected_source"] == source for row in emissions)
                for source in ("direct_company", "cleansys", "env_info")
            },
            "final_rows_by_operator_category": {
                category: sum(row["operator_category"] == category for row in final)
                for category in sorted({row["operator_category"] for row in final})
            },
            "fuel_validation_by_status": {
                status: sum(row["validation_status"] == status for row in fuel_validation)
                for status in sorted({row["validation_status"] for row in fuel_validation})
            },
        },
        "validation": checks,
        "inputs": {
            str(path.relative_to(PROJECT_ROOT)): file_sha256(path)
            for path in (
                DEFAULT_PLANTS_PATH,
                DEFAULT_LINKS_PATH,
                DEFAULT_CLEANSYS_PATH,
                DEFAULT_ENV_INFO_PATH,
                DEFAULT_DIRECT_PATH,
                DEFAULT_GENERATION_OVERRIDES,
                DEFAULT_DIRECT_LINKS,
            )
        },
        "outputs": {path.name: file_sha256(path) for path in paths.values()},
        "scope_notes": [
            "Gross generation is selected because it is consistently populated across EPSIS.",
            "Explicit plant totals take precedence over component unit rows.",
            "CleanSYS and ENV-INFO values are alternatives and are never added together.",
            "Representative ENV-INFO records and many-to-many facilities are retained as candidates but not selected.",
            "Outliers are flagged and retained.",
            (
                "No EPSIS thermal company-total rows could be safely paired with the "
                "plant assignments, so company-aggregate exceedance validation reports "
                "zero available comparisons rather than inventing a benchmark."
            ),
        ],
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(generation)} annual plant-generation rows")
    print(f"Wrote {len(emissions)} plant-year-pollutant comparisons")
    print(f"Wrote {len(final)} final plant-year rows")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--disagreement-threshold", type=float, default=0.5)
    parser.add_argument("--extreme-nox-kg-per-mwh", type=float, default=100.0)
    parser.add_argument("--extreme-sox-kg-per-mwh", type=float, default=100.0)
    parser.add_argument("--extreme-tsp-kg-per-mwh", type=float, default=20.0)
    args = parser.parse_args()
    build_annual_panel(
        output_dir=args.output_dir,
        disagreement_threshold=args.disagreement_threshold,
        extreme_nox_kg_per_mwh=args.extreme_nox_kg_per_mwh,
        extreme_sox_kg_per_mwh=args.extreme_sox_kg_per_mwh,
        extreme_tsp_kg_per_mwh=args.extreme_tsp_kg_per_mwh,
    )


if __name__ == "__main__":
    main()
