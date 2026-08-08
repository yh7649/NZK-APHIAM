"""Build an EPSIS-to-ENV-INFO/CleanSYS thermal plant crosswalk."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha1, sha256
import html
import json
from pathlib import Path
import re
from typing import Any, Iterable

from nzk_aphiam.config.paths import (
    ANNUAL_PANEL_ARCHIVE_INTERIM_DIR,
    ANNUAL_PANEL_ARCHIVE_RAW_DIR,
    PROJECT_ROOT,
)

DEFAULT_EPSIS_DIR = ANNUAL_PANEL_ARCHIVE_RAW_DIR / "plant_rosters" / "epsis" / "annual"
DEFAULT_ENV_INFO_PATH = (
    ANNUAL_PANEL_ARCHIVE_RAW_DIR
    / "emissions"
    / "env_info"
    / "env_info_power_emissions_2015_2024.csv"
)
DEFAULT_CLEANSYS_PATH = (
    ANNUAL_PANEL_ARCHIVE_RAW_DIR / "emissions" / "cleansys" / "cleansys_annual_emissions_panel.csv"
)
DEFAULT_OUTPUT_DIR = ANNUAL_PANEL_ARCHIVE_INTERIM_DIR / "crosswalks" / "thermal"
DEFAULT_NAME_ALIASES_PATH = PROJECT_ROOT / "docs" / "references" / "crosswalk" / "name_aliases.csv"
DEFAULT_MANUAL_LINKS_PATH = (
    PROJECT_ROOT / "docs" / "references" / "crosswalk" / "manual_facility_links.csv"
)

THERMAL_TERMS = (
    "기력",
    "복합",
    "열병합",
    "내연",
    "석탄",
    "LNG",
    "유류",
    "부생",
    "바이오",
    "폐기물",
)
KHNP_CLEAN_GENERATION_TERMS = ("원자력", "수력", "양수")

LEGAL_TERMS = (
    "주식회사",
    "유한회사",
    "㈜",
    "(주)",
    "（주）",
    "본사",
    "군산사업부문",
)

COMPANY_CANONICAL: dict[str, str] = {}
PLANT_ALIASES: dict[str, str] = {}

MUNICIPALITY_PATTERN = re.compile(
    r"([가-힣]+(?:특별자치도|특별자치시|광역시|특별시|도))?\s*"
    r"([가-힣]+(?:시|군|구))"
)
UNIT_PATTERN = re.compile(
    r"(?:#\s*\d+(?:\s*[-~,]\s*\d+)*(?:\s*[-/]\s*\d+)?)|"
    r"(?:\d+(?:\s*[-~,]\s*\d+)*호기)|"
    r"(?:(?:GT|ST|C/C)(?:\s*#?\s*\d+)?)",
    re.IGNORECASE,
)
GENERIC_OPERATORS = {"", "-", "㈜", "(주)", "사업용", "전력㈜", "전력(주)", "에너지"}

PLANT_COLUMNS = [
    "epsis_plant_id",
    "epsis_plant_name",
    "epsis_operator",
    "epsis_operator_key",
    "epsis_plant_key",
    "epsis_location",
    "first_year",
    "last_year",
    "row_count",
    "unit_names",
    "fuels",
    "generation_types",
    "capacity_kw_latest",
    "multiple_fuels",
    "multiple_generation_types",
]

MATCH_COLUMNS = [
    *PLANT_COLUMNS,
    "env_info_record_id",
    "env_info_parent_record_id",
    "env_info_facility_name",
    "env_info_record_type",
    "env_info_first_year",
    "env_info_last_year",
    "env_info_score",
    "env_info_margin",
    "env_info_status",
    "env_info_boundary_flag",
    "cleansys_facility_code",
    "cleansys_business_registration_number",
    "cleansys_facility_name",
    "cleansys_address",
    "cleansys_first_year",
    "cleansys_last_year",
    "cleansys_score",
    "cleansys_margin",
    "cleansys_status",
    "overall_status",
]

CANDIDATE_COLUMNS = [
    "epsis_plant_id",
    "epsis_plant_name",
    "epsis_operator",
    "source",
    "candidate_rank",
    "candidate_id",
    "candidate_name",
    "candidate_parent_id",
    "candidate_record_type",
    "candidate_address",
    "score",
    "company_score",
    "plant_score",
    "location_score",
    "operator_exact",
    "plant_exact",
]

LINK_COLUMNS = [
    "epsis_plant_id",
    "epsis_plant_name",
    "epsis_operator",
    "source",
    "facility_id",
    "facility_name",
    "facility_parent_id",
    "facility_record_type",
    "facility_address",
    "facility_first_year",
    "facility_last_year",
    "link_status",
    "score",
    "boundary_flag",
    "link_note",
]


@dataclass(frozen=True)
class Facility:
    source: str
    identifier: str
    name: str
    aliases: tuple[str, ...]
    parent_id: str = ""
    parent_aliases: tuple[str, ...] = ()
    record_type: str = ""
    address: str = ""
    business_number: str = ""
    first_year: int = 0
    last_year: int = 0
    sibling_count: int = 0


def compact(value: str) -> str:
    value = html.unescape(value).lower()
    for term in LEGAL_TERMS:
        value = value.replace(term.lower(), "")
    return re.sub(r"[^0-9a-z가-힣]", "", value)


def normalize_company(value: str) -> str:
    key = compact(value)
    return COMPANY_CANONICAL.get(key, key)


def company_keys(value: str) -> set[str]:
    """Return plausible canonical operators embedded in a facility name."""
    raw = compact(value)
    keys = {COMPANY_CANONICAL.get(raw, raw)}
    for alias, canonical in COMPANY_CANONICAL.items():
        if len(alias) >= 3 and alias in raw:
            keys.add(canonical)
    return keys


def normalize_plant(value: str) -> str:
    value = value.replace("0천", "천")
    value = UNIT_PATTERN.sub("", value)
    value = re.sub(r"(?:복합|열병합|화력|천연가스|그린파워)$", "", value.strip())
    key = compact(value)
    return PLANT_ALIASES.get(key, key)


def municipality(value: str) -> str:
    match = MUNICIPALITY_PATTERN.search(value)
    return compact(match.group(2)) if match else ""


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if min(len(left), len(right)) >= 3 and (left in right or right in left):
        return 0.94
    return SequenceMatcher(None, left, right).ratio()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_name_aliases(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    company_aliases: dict[str, str] = {}
    plant_aliases: dict[str, str] = {}
    for row in read_csv(path):
        alias_type = row["alias_type"]
        target = company_aliases if alias_type == "company" else plant_aliases
        if alias_type not in {"company", "plant"}:
            raise RuntimeError(f"Unknown crosswalk alias type: {alias_type}")
        target[compact(row["alias"])] = compact(row["canonical"])
    return company_aliases, plant_aliases


def load_manual_links(
    path: Path,
) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str, str], tuple[str, ...]]]:
    preferred: dict[tuple[str, str, str], str] = {}
    historical: dict[tuple[str, str, str], list[str]] = {}
    for row in read_csv(path):
        key = (row["epsis_operator_key"], row["epsis_plant_key"], row["source"])
        if row["link_role"] == "preferred":
            if key in preferred:
                raise RuntimeError(f"Duplicate preferred manual facility link: {key}")
            preferred[key] = row["facility_id"]
        elif row["link_role"] == "historical":
            historical.setdefault(key, []).append(row["facility_id"])
        else:
            raise RuntimeError(f"Unknown manual facility link role: {row['link_role']}")
    return preferred, {key: tuple(values) for key, values in historical.items()}


COMPANY_CANONICAL, PLANT_ALIASES = load_name_aliases(DEFAULT_NAME_ALIASES_PATH)


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def is_thermal(row: dict[str, str]) -> bool:
    text = " ".join(
        row.get(column, "") for column in ("generation_source", "generation_type", "fuel")
    )
    return any(term in text for term in THERMAL_TERMS)


def is_khnp_clean_generation(row: dict[str, str]) -> bool:
    company = normalize_company(row.get("generation_company", ""))
    text = " ".join(
        row.get(column, "") for column in ("generation_source", "generation_type", "fuel")
    )
    return company == "한국수력원자력" and any(
        term in text for term in KHNP_CLEAN_GENERATION_TERMS
    )


def is_generic_operator(value: str) -> bool:
    stripped = value.strip()
    normalized = normalize_company(stripped)
    return (
        stripped in GENERIC_OPERATORS
        or normalized in {"", "사업용", "전력", "에너지"}
        or len(normalized) < 3
    )


def stable_id(*parts: str) -> str:
    digest = sha1("|".join(parts).encode()).hexdigest()[:12]
    return f"epsis_{digest}"


def build_epsis_plants(epsis_dir: Path) -> list[dict[str, Any]]:
    source_rows: list[dict[str, str]] = []
    for path in sorted(epsis_dir.glob("epsis_generator_roster_*.csv")):
        for row in read_csv(path):
            if not (is_thermal(row) or is_khnp_clean_generation(row)):
                continue
            row["_operator_key"] = normalize_company(row["generation_company"])
            row["_plant_key"] = normalize_plant(row["plant_name"])
            row["_municipality"] = municipality(row["location_or_main_product"])
            source_rows.append(row)

    known_operators: dict[tuple[str, str], list[str]] = {}
    for row in source_rows:
        if is_generic_operator(row["generation_company"]):
            continue
        known_operators.setdefault((row["_plant_key"], row["_municipality"]), []).append(
            row["_operator_key"]
        )

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in source_rows:
        operator_key = row["_operator_key"]
        plant_key = row["_plant_key"]
        if not plant_key:
            continue
        if is_generic_operator(row["generation_company"]):
            candidates = known_operators.get((plant_key, row["_municipality"]), [])
            if candidates:
                operator_key = max(set(candidates), key=candidates.count)
        grouped.setdefault((operator_key, plant_key), []).append(row)

    plants: list[dict[str, Any]] = []
    for (operator_key, plant_key), rows in grouped.items():
        rows.sort(key=lambda row: (int(row["year"]), row["plant_name"]))
        latest_year = max(int(row["year"]) for row in rows)
        latest_rows = [row for row in rows if int(row["year"]) == latest_year]
        names = sorted({row["plant_name"].strip() for row in rows if row["plant_name"].strip()})
        operators = sorted(
            {
                row["generation_company"].strip()
                for row in rows
                if not is_generic_operator(row["generation_company"])
            }
        )
        locations = sorted(
            {
                row["location_or_main_product"].strip()
                for row in rows
                if row["location_or_main_product"].strip()
            }
        )
        fuels = sorted({row["fuel"].strip() for row in rows if row["fuel"].strip()})
        generation_types = sorted(
            {row["generation_type"].strip() for row in rows if row["generation_type"].strip()}
        )
        capacities = [
            float(row["capacity_kw"]) for row in latest_rows if row["capacity_kw"] not in {"", "-"}
        ]
        display_name = min(names, key=lambda name: (len(name), name))
        display_operator = min(operators, key=lambda name: (len(name), name)) if operators else ""
        plants.append(
            {
                "epsis_plant_id": stable_id(operator_key, plant_key),
                "epsis_plant_name": display_name,
                "epsis_operator": display_operator,
                "epsis_operator_key": operator_key,
                "epsis_plant_key": plant_key,
                "epsis_location": max(locations, key=len) if locations else "",
                "first_year": min(int(row["year"]) for row in rows),
                "last_year": latest_year,
                "row_count": len(rows),
                "unit_names": " | ".join(names),
                "fuels": " | ".join(fuels),
                "generation_types": " | ".join(generation_types),
                "capacity_kw_latest": sum(capacities),
                "multiple_fuels": len(fuels) > 1,
                "multiple_generation_types": len(generation_types) > 1,
            }
        )
    return sorted(plants, key=lambda row: (row["epsis_operator_key"], row["epsis_plant_key"]))


def build_env_info_facilities(path: Path) -> list[Facility]:
    rows = read_csv(path)
    by_id: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_id.setdefault(row["record_id"], []).append(row)

    parent_names: dict[str, set[str]] = {}
    for record_rows in by_id.values():
        for row in record_rows:
            if row["record_id"] == row["parent_record_id"]:
                parent_names.setdefault(row["parent_record_id"], set()).add(row["facility_name"])

    sibling_counts: dict[str, int] = {}
    for identifier, record_rows in by_id.items():
        parent_id = record_rows[-1]["parent_record_id"]
        if identifier != parent_id:
            sibling_counts[parent_id] = sibling_counts.get(parent_id, 0) + 1

    facilities: list[Facility] = []
    for identifier, record_rows in by_id.items():
        aliases = tuple(sorted({row["facility_name"] for row in record_rows}))
        latest = max(record_rows, key=lambda row: int(row["year"]))
        parent_id = latest["parent_record_id"]
        facilities.append(
            Facility(
                source="env_info",
                identifier=identifier,
                name=latest["facility_name"],
                aliases=aliases,
                parent_id=parent_id,
                parent_aliases=tuple(sorted(parent_names.get(parent_id, set()))),
                record_type=latest["record_type"],
                first_year=min(int(row["year"]) for row in record_rows),
                last_year=max(int(row["year"]) for row in record_rows),
                sibling_count=sibling_counts.get(parent_id, 0),
            )
        )
    return facilities


def build_cleansys_facilities(path: Path) -> list[Facility]:
    by_id: dict[str, list[dict[str, str]]] = {}
    for row in read_csv(path):
        by_id.setdefault(row["facility_code"], []).append(row)

    facilities: list[Facility] = []
    for identifier, rows in by_id.items():
        aliases = tuple(sorted({row["facility_name"] for row in rows}))
        latest = max(rows, key=lambda row: int(row["year"]))
        facilities.append(
            Facility(
                source="cleansys",
                identifier=identifier,
                name=latest["facility_name"],
                aliases=aliases,
                address=latest["address"],
                business_number=latest["business_registration_number"],
                first_year=min(int(row["year"]) for row in rows),
                last_year=max(int(row["year"]) for row in rows),
            )
        )
    return facilities


def company_score(plant: dict[str, Any], facility: Facility) -> tuple[float, bool]:
    operator = plant["epsis_operator_key"]
    aliases = (*facility.aliases, *facility.parent_aliases)
    candidate_keys = {candidate_key for alias in aliases for candidate_key in company_keys(alias)}
    scores = [similarity(operator, candidate_key) for candidate_key in candidate_keys]
    score = max(scores, default=0.0)
    exact = operator in candidate_keys
    return score, exact


def plant_score(plant: dict[str, Any], facility: Facility) -> tuple[float, bool]:
    key = plant["epsis_plant_key"]
    scores = [similarity(key, normalize_plant(alias)) for alias in facility.aliases]
    score = max(scores, default=0.0)
    exact = any(
        key == normalize_plant(alias) or (len(key) >= 2 and key in normalize_plant(alias))
        for alias in facility.aliases
    )
    return score, exact


def score_candidate(plant: dict[str, Any], facility: Facility) -> dict[str, Any]:
    comp_score, operator_exact = company_score(plant, facility)
    p_score, p_exact = plant_score(plant, facility)
    plant_municipality = municipality(plant["epsis_location"])
    facility_municipality = municipality(facility.address)
    location_score = (
        1.0
        if plant_municipality
        and facility_municipality
        and plant_municipality == facility_municipality
        else 0.0
    )
    score = 0.5 * comp_score + 0.4 * p_score + 0.1 * location_score
    if operator_exact and p_exact:
        score = max(score, 0.98)
    elif p_exact and location_score and comp_score >= 0.55:
        score = max(score, 0.84)
    return {
        "facility": facility,
        "score": round(min(score, 1.0), 4),
        "company_score": round(comp_score, 4),
        "plant_score": round(p_score, 4),
        "location_score": location_score,
        "operator_exact": operator_exact,
        "plant_exact": p_exact,
    }


def rank_candidates(
    plant: dict[str, Any],
    facilities: list[Facility],
    limit: int = 5,
) -> list[dict[str, Any]]:
    candidates = [score_candidate(plant, facility) for facility in facilities]
    candidates.sort(
        key=lambda row: (
            row["score"],
            row["operator_exact"],
            row["plant_exact"],
            row["company_score"],
        ),
        reverse=True,
    )
    return candidates[:limit]


def classify_match(
    ranked: list[dict[str, Any]],
    operator_candidate_count: int,
) -> tuple[dict[str, Any] | None, float, str]:
    if not ranked:
        return None, 0.0, "unmatched"
    best = ranked[0]
    second_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
    margin = round(best["score"] - second_score, 4)
    if best["operator_exact"] and operator_candidate_count == 1:
        best = {**best, "score": max(best["score"], 0.9)}
        margin = round(best["score"] - second_score, 4)
    if best["score"] >= 0.84 and margin >= 0.06:
        status = "automatic"
    elif best["score"] >= 0.7 and margin >= 0.03:
        status = "probable"
    elif best["score"] >= 0.55:
        status = "review"
    else:
        status = "unmatched"
        return None, margin, status
    return best, margin, status


def apply_manual_override(
    plant: dict[str, Any],
    source: str,
    facilities_by_id: dict[str, Facility],
    manual_overrides: dict[tuple[str, str, str], str],
    match: dict[str, Any] | None,
    margin: float,
    status: str,
) -> tuple[dict[str, Any] | None, float, str]:
    identifier = manual_overrides.get(
        (plant["epsis_operator_key"], plant["epsis_plant_key"], source)
    )
    if not identifier:
        if plant["epsis_operator_key"] == "한국수력원자력":
            return None, margin, "unmatched"
        return match, margin, status
    manual_match = score_candidate(plant, facilities_by_id[identifier])
    manual_match["score"] = max(manual_match["score"], 0.95)
    return manual_match, 1.0, "manual"


def boundary_flag(match: dict[str, Any] | None) -> str:
    if not match:
        return ""
    facility: Facility = match["facility"]
    if (
        facility.source == "env_info"
        and facility.record_type == "대표사업장"
        and facility.sibling_count
        and not match["plant_exact"]
    ):
        return "possible_parent_aggregate"
    return ""


def link_row(
    plant: dict[str, Any],
    facility: Facility,
    status: str,
    score: float,
    flag: str,
    note: str,
) -> dict[str, Any]:
    return {
        "epsis_plant_id": plant["epsis_plant_id"],
        "epsis_plant_name": plant["epsis_plant_name"],
        "epsis_operator": plant["epsis_operator"],
        "source": facility.source,
        "facility_id": facility.identifier,
        "facility_name": facility.name,
        "facility_parent_id": facility.parent_id,
        "facility_record_type": facility.record_type,
        "facility_address": facility.address,
        "facility_first_year": facility.first_year,
        "facility_last_year": facility.last_year,
        "link_status": status,
        "score": score,
        "boundary_flag": flag,
        "link_note": note,
    }


def candidate_rows(
    plant: dict[str, Any],
    source: str,
    ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(ranked, start=1):
        facility: Facility = candidate["facility"]
        rows.append(
            {
                "epsis_plant_id": plant["epsis_plant_id"],
                "epsis_plant_name": plant["epsis_plant_name"],
                "epsis_operator": plant["epsis_operator"],
                "source": source,
                "candidate_rank": rank,
                "candidate_id": facility.identifier,
                "candidate_name": facility.name,
                "candidate_parent_id": facility.parent_id,
                "candidate_record_type": facility.record_type,
                "candidate_address": facility.address,
                "score": candidate["score"],
                "company_score": candidate["company_score"],
                "plant_score": candidate["plant_score"],
                "location_score": candidate["location_score"],
                "operator_exact": candidate["operator_exact"],
                "plant_exact": candidate["plant_exact"],
            }
        )
    return rows


def source_match_values(
    match: dict[str, Any] | None,
    margin: float,
    status: str,
    source: str,
) -> dict[str, Any]:
    if not match:
        prefix = "env_info" if source == "env_info" else "cleansys"
        result = {
            f"{prefix}_score": "",
            f"{prefix}_margin": margin,
            f"{prefix}_status": status,
        }
        if source == "env_info":
            result.update(
                {
                    "env_info_record_id": "",
                    "env_info_parent_record_id": "",
                    "env_info_facility_name": "",
                    "env_info_record_type": "",
                    "env_info_first_year": "",
                    "env_info_last_year": "",
                    "env_info_boundary_flag": "",
                }
            )
        else:
            result.update(
                {
                    "cleansys_facility_code": "",
                    "cleansys_business_registration_number": "",
                    "cleansys_facility_name": "",
                    "cleansys_address": "",
                    "cleansys_first_year": "",
                    "cleansys_last_year": "",
                }
            )
        return result

    facility: Facility = match["facility"]
    if source == "env_info":
        return {
            "env_info_record_id": facility.identifier,
            "env_info_parent_record_id": facility.parent_id,
            "env_info_facility_name": facility.name,
            "env_info_record_type": facility.record_type,
            "env_info_first_year": facility.first_year,
            "env_info_last_year": facility.last_year,
            "env_info_score": match["score"],
            "env_info_margin": margin,
            "env_info_status": status,
            "env_info_boundary_flag": boundary_flag(match),
        }
    return {
        "cleansys_facility_code": facility.identifier,
        "cleansys_business_registration_number": facility.business_number,
        "cleansys_facility_name": facility.name,
        "cleansys_address": facility.address,
        "cleansys_first_year": facility.first_year,
        "cleansys_last_year": facility.last_year,
        "cleansys_score": match["score"],
        "cleansys_margin": margin,
        "cleansys_status": status,
    }


def build_crosswalk(
    epsis_dir: Path,
    env_info_path: Path,
    cleansys_path: Path,
    output_dir: Path,
    name_aliases_path: Path = DEFAULT_NAME_ALIASES_PATH,
    manual_links_path: Path = DEFAULT_MANUAL_LINKS_PATH,
) -> list[dict[str, Any]]:
    global COMPANY_CANONICAL, PLANT_ALIASES
    COMPANY_CANONICAL, PLANT_ALIASES = load_name_aliases(name_aliases_path)
    manual_overrides, historical_links = load_manual_links(manual_links_path)
    plants = build_epsis_plants(epsis_dir)
    env_facilities = build_env_info_facilities(env_info_path)
    cleansys_facilities = build_cleansys_facilities(cleansys_path)
    env_by_id = {facility.identifier: facility for facility in env_facilities}
    clean_by_id = {facility.identifier: facility for facility in cleansys_facilities}

    crosswalk: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for plant in plants:
        env_ranked = rank_candidates(plant, env_facilities)
        clean_ranked = rank_candidates(plant, cleansys_facilities)
        candidates.extend(candidate_rows(plant, "env_info", env_ranked))
        candidates.extend(candidate_rows(plant, "cleansys", clean_ranked))

        env_exact_count = sum(company_score(plant, facility)[1] for facility in env_facilities)
        clean_exact_count = sum(
            company_score(plant, facility)[1] for facility in cleansys_facilities
        )
        env_match, env_margin, env_status = classify_match(env_ranked, env_exact_count)
        clean_match, clean_margin, clean_status = classify_match(clean_ranked, clean_exact_count)
        env_match, env_margin, env_status = apply_manual_override(
            plant,
            "env_info",
            env_by_id,
            manual_overrides,
            env_match,
            env_margin,
            env_status,
        )
        clean_match, clean_margin, clean_status = apply_manual_override(
            plant,
            "cleansys",
            clean_by_id,
            manual_overrides,
            clean_match,
            clean_margin,
            clean_status,
        )
        overall_status = (
            "manual"
            if "manual" in {env_status, clean_status}
            else "automatic"
            if "automatic" in {env_status, clean_status}
            else "probable"
            if "probable" in {env_status, clean_status}
            else "review"
            if "review" in {env_status, clean_status}
            else "unmatched"
        )
        crosswalk.append(
            {
                **plant,
                **source_match_values(env_match, env_margin, env_status, "env_info"),
                **source_match_values(clean_match, clean_margin, clean_status, "cleansys"),
                "overall_status": overall_status,
            }
        )
        for match, status in (
            (env_match, env_status),
            (clean_match, clean_status),
        ):
            if match and status in {"manual", "automatic", "probable"}:
                facility: Facility = match["facility"]
                links.append(
                    link_row(
                        plant,
                        facility,
                        status,
                        match["score"],
                        boundary_flag(match),
                        "preferred facility link",
                    )
                )

        for source, facilities_by_id in (
            ("env_info", env_by_id),
            ("cleansys", clean_by_id),
        ):
            extra_ids = historical_links.get(
                (plant["epsis_operator_key"], plant["epsis_plant_key"], source),
                (),
            )
            for identifier in extra_ids:
                links.append(
                    link_row(
                        plant,
                        facilities_by_id[identifier],
                        "manual_historical",
                        0.95,
                        "",
                        "additional source ID for the same physical plant",
                    )
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    plant_path = output_dir / "epsis_thermal_plants.csv"
    crosswalk_path = output_dir / "epsis_emissions_facility_crosswalk.csv"
    candidate_path = output_dir / "epsis_emissions_match_candidates.csv"
    link_path = output_dir / "epsis_emissions_facility_links.csv"
    write_csv(plant_path, PLANT_COLUMNS, plants)
    write_csv(
        crosswalk_path,
        MATCH_COLUMNS,
        crosswalk,
    )
    write_csv(
        candidate_path,
        CANDIDATE_COLUMNS,
        candidates,
    )
    unique_links = {
        (row["epsis_plant_id"], row["source"], row["facility_id"]): row for row in links
    }
    write_csv(
        link_path,
        LINK_COLUMNS,
        unique_links.values(),
    )
    metadata = {
        "dataset": "EPSIS thermal plant to emissions facility crosswalk",
        "method_version": 1,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_count": len(crosswalk),
        "status_counts": {
            status: sum(row["overall_status"] == status for row in crosswalk)
            for status in ("manual", "automatic", "probable", "review", "unmatched")
        },
        "accepted_link_count": len(unique_links),
        "outputs": {
            path.name: file_sha256(path)
            for path in (plant_path, crosswalk_path, candidate_path, link_path)
        },
        "source_record_counts": {
            "env_info": len(env_facilities),
            "cleansys": len(cleansys_facilities),
        },
        "inputs": {
            "epsis_annual_csvs": [
                {
                    "path": str(path.relative_to(PROJECT_ROOT)),
                    "sha256": file_sha256(path),
                }
                for path in sorted(epsis_dir.glob("epsis_generator_roster_*.csv"))
            ],
            "env_info": {
                "path": str(env_info_path.relative_to(PROJECT_ROOT)),
                "sha256": file_sha256(env_info_path),
            },
            "cleansys": {
                "path": str(cleansys_path.relative_to(PROJECT_ROOT)),
                "sha256": file_sha256(cleansys_path),
            },
            "name_aliases": {
                "path": str(name_aliases_path.relative_to(PROJECT_ROOT)),
                "sha256": file_sha256(name_aliases_path),
            },
            "manual_links": {
                "path": str(manual_links_path.relative_to(PROJECT_ROOT)),
                "sha256": file_sha256(manual_links_path),
            },
        },
        "method_notes": [
            "EPSIS unit/component rows are grouped by normalized operator and plant.",
            "Matches use operator, plant name, and municipality agreement.",
            "Automatic matches require a score margin over the next candidate.",
            "Candidate alternatives are retained for manual review.",
            "Representative ENV-INFO records with child sites are flagged when the plant name does not agree.",
            "A crosswalk match does not by itself prove equal emissions and generation boundaries.",
        ],
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return crosswalk


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epsis-dir", type=Path, default=DEFAULT_EPSIS_DIR)
    parser.add_argument("--env-info-path", type=Path, default=DEFAULT_ENV_INFO_PATH)
    parser.add_argument("--cleansys-path", type=Path, default=DEFAULT_CLEANSYS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--name-aliases", type=Path, default=DEFAULT_NAME_ALIASES_PATH)
    parser.add_argument("--manual-links", type=Path, default=DEFAULT_MANUAL_LINKS_PATH)
    args = parser.parse_args()
    rows = build_crosswalk(
        args.epsis_dir,
        args.env_info_path,
        args.cleansys_path,
        args.output_dir,
        args.name_aliases,
        args.manual_links,
    )
    print(f"Wrote {len(rows)} EPSIS thermal plant crosswalk records.")


if __name__ == "__main__":
    main()
