"""Build the coal stack-properties reference crosswalk from CREA Appendix 2."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from io import BytesIO
import re
from typing import ClassVar

import pandas as pd
from pypdf import PdfReader
import requests

from nzk_aphiam.config.paths import PROJECT_ROOT

SOURCE_URL = (
    "https://energyandcleanair.org/wp/wp-content/uploads/2021/04/HIA_South-Korea_April-2021.pdf"
)
SOURCE_TITLE = "HIA South Korea: Time for a Check Up"
PUBLICATION_DATE = "2021-04-01"
DEFAULT_REFERENCE_PATH = (
    PROJECT_ROOT / "docs" / "references" / "crosswalk" / "stack_properties.csv"
)
DEFAULT_UNIT_MAP_PATH = PROJECT_ROOT / "docs" / "references" / "crosswalk" / "stack_unit_map.csv"
DEFAULT_EVIDENCE_PATH = (
    PROJECT_ROOT / "docs" / "references" / "crosswalk" / "stack_properties_official_evidence.csv"
)

REFERENCE_COLUMNS = [
    "subsidiary_company",
    "plant_name",
    "stack_id",
    "reporting_unit_id",
    "stack_height_m",
    "stack_diameter_m",
    "exit_temp_c",
    "flue_gas_velocity_m_s",
    "stack_latitude",
    "stack_longitude",
    "match_status",
    "evidence_id",
]
UNIT_MAP_COLUMNS = ["stack_id", "reporting_unit_id"]
EVIDENCE_COLUMNS = [
    "evidence_id",
    "source_title",
    "source_url",
    "publication_date",
    "accessed_date",
    "evidence",
]

SOURCE_PLANTS = [
    "Samcheok Blue Powerpower",
    "Samcheok GreenPower",
    "Gangneung Anin",
    "Shin Boryeong",
    "Shin Seocheon",
    "Goseong Hi",
    "Samcheonpo",
    "Yeongheung",
    "Bukpyeong",
    "Boryeong",
    "Dangjin",
    "Donghae",
    "Hadong",
    "Honam",
    "Taean",
    "Yeosu",
]
ROW_PATTERN = re.compile(
    rf"(?P<label>(?:{'|'.join(re.escape(name) for name in SOURCE_PLANTS)})(?:\s+Unit\s+\d+)?)"
    r"\s+(?P<body>.*?)(?=(?:"
    + "|".join(re.escape(name) for name in SOURCE_PLANTS)
    + r")(?:\s+Unit\s+\d+)?\s+|\Z)",
    re.DOTALL,
)
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class SourceStackRow:
    """One source-table row after PDF text extraction."""

    source_plant: str
    unit_number: int | None
    stack_latitude: float
    stack_longitude: float
    stack_height_m: float
    stack_diameter_m: float
    exit_temp_c: float
    flue_gas_velocity_m_s: float


@dataclass(frozen=True)
class CanonicalMapping:
    """Map one CREA source plant label to this project's KEPCO coal identities."""

    subsidiary_company: str
    plant_name: str
    reporting_unit_prefix: str | None
    reporting_unit_suffix: str = ""
    unit_required: bool = True

    CREATION_NOTE: ClassVar[str] = (
        "These mappings are limited to KEPCO coal plants present in the processed panel."
    )

    def reporting_unit_id(self, unit_number: int | None) -> str:
        if self.reporting_unit_prefix is None:
            return ""
        if unit_number is None:
            return self.reporting_unit_prefix if not self.unit_required else ""
        return f"{self.reporting_unit_prefix}{unit_number}{self.reporting_unit_suffix}"


SOURCE_MAPPING = {
    "Dangjin": CanonicalMapping("Korea East-West Power", "Dangjin", "eastwest_power:Dangjin:"),
    "Donghae": CanonicalMapping("Korea East-West Power", "Donghae", "eastwest_power:Donghae:"),
    "Honam": CanonicalMapping("Korea East-West Power", "Honam", "eastwest_power:Honam:"),
    "Shin Seocheon": CanonicalMapping(
        "Korea Midland Power",
        "Seocheon",
        "midland_power:신서천화력",
        unit_required=False,
    ),
    "Samcheonpo": CanonicalMapping(
        "Korea South-East Power", "Samcheonpo", "southeast_power:삼천포:"
    ),
    "Yeongheung": CanonicalMapping(
        "Korea South-East Power", "Yeongheung", "southeast_power:영흥:"
    ),
    "Yeosu": CanonicalMapping("Korea South-East Power", "Yeosu", "southeast_power:여수:"),
    "Hadong": CanonicalMapping("Korea Southern Power", "Hadong", None),
    "Samcheok GreenPower": CanonicalMapping("Korea Southern Power", "Samcheok", None),
    "Taean": CanonicalMapping("Korea Western Power", "Taean", "western_power:Taean:", "호기"),
}

UNMATCHED_ROWS = [
    {
        "subsidiary_company": "Korea Midland Power",
        "plant_name": "Boryeong",
        "stack_id": "korea_midland_power_boryeong_unmatched",
        "reporting_unit_id": "midland_power:보령기력",
        "stack_height_m": "",
        "stack_diameter_m": "",
        "exit_temp_c": "",
        "flue_gas_velocity_m_s": "",
        "stack_latitude": "",
        "stack_longitude": "",
        "match_status": "unmatched",
        "evidence_id": "crea_hia_south_korea_2021_appendix_2",
    },
    {
        "subsidiary_company": "Korea Midland Power",
        "plant_name": "Shin-Boryeong",
        "stack_id": "korea_midland_power_shin_boryeong_unmatched",
        "reporting_unit_id": "midland_power:신보령기력",
        "stack_height_m": "",
        "stack_diameter_m": "",
        "exit_temp_c": "",
        "flue_gas_velocity_m_s": "",
        "stack_latitude": "",
        "stack_longitude": "",
        "match_status": "unmatched",
        "evidence_id": "crea_hia_south_korea_2021_appendix_2",
    },
    {
        "subsidiary_company": "Korea South-East Power",
        "plant_name": "Yeongdong",
        "stack_id": "korea_south_east_power_yeongdong_unmatched",
        "reporting_unit_id": "southeast_power:영동:2",
        "stack_height_m": "",
        "stack_diameter_m": "",
        "exit_temp_c": "",
        "flue_gas_velocity_m_s": "",
        "stack_latitude": "",
        "stack_longitude": "",
        "match_status": "unmatched",
        "evidence_id": "crea_hia_south_korea_2021_appendix_2",
    },
]


def download_source_pdf(source_url: str = SOURCE_URL) -> bytes:
    """Download the CREA report PDF."""
    response = requests.get(source_url, timeout=120)
    response.raise_for_status()
    return response.content


def extract_source_stack_rows(pdf_bytes: bytes) -> list[SourceStackRow]:
    """Extract stack-property rows from Appendix 2 of the CREA report."""
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(reader.pages[index].extract_text() or "" for index in range(26, 29))
    rows: list[SourceStackRow] = []
    for match in ROW_PATTERN.finditer(text):
        label = " ".join(match.group("label").split())
        numbers = [float(value) for value in NUMBER_PATTERN.findall(match.group("body"))[:10]]
        if len(numbers) < 6:
            continue
        unit_match = re.search(r"\bUnit\s+(\d+)\b", label)
        source_plant = re.sub(r"\s+Unit\s+\d+\b", "", label).strip()
        rows.append(
            SourceStackRow(
                source_plant=source_plant,
                unit_number=int(unit_match.group(1)) if unit_match else None,
                stack_latitude=numbers[0],
                stack_longitude=numbers[1],
                stack_height_m=numbers[2],
                stack_diameter_m=numbers[3],
                exit_temp_c=numbers[4],
                flue_gas_velocity_m_s=numbers[5],
            )
        )
    return rows


def _stack_id(
    subsidiary_company: str,
    plant_name: str,
    rows: list[dict[str, object]],
) -> str:
    units = [
        str(row["reporting_unit_id"]).rsplit(":", maxsplit=1)[-1].removesuffix("호기")
        for row in rows
        if row["reporting_unit_id"]
    ]
    if not units:
        unit_labels = [str(row["source_unit_number"]) for row in rows if row["source_unit_number"]]
        units = unit_labels
    units = [unit for unit in units if unit.isascii()]
    unit_part = "_".join(units) if units else "plant"
    company_part = subsidiary_company.lower().replace(" ", "_").replace("-", "_")
    plant_part = plant_name.lower().replace(" ", "_").replace("-", "_")
    return f"{company_part}_{plant_part}_stack_{unit_part}"


def build_crosswalk_tables(
    rows: list[SourceStackRow],
    *,
    accessed_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return stack reference, stack-unit map, and evidence tables."""
    mapped_rows: list[dict[str, object]] = []
    for row in rows:
        mapping = SOURCE_MAPPING.get(row.source_plant)
        if mapping is None:
            continue
        if mapping.unit_required and row.unit_number is None:
            raise ValueError(f"Source row requires a unit number: {row.source_plant}")
        mapped_rows.append(
            {
                "subsidiary_company": mapping.subsidiary_company,
                "plant_name": mapping.plant_name,
                "reporting_unit_id": mapping.reporting_unit_id(row.unit_number),
                "stack_height_m": row.stack_height_m,
                "stack_diameter_m": row.stack_diameter_m,
                "exit_temp_c": row.exit_temp_c,
                "flue_gas_velocity_m_s": row.flue_gas_velocity_m_s,
                "stack_latitude": row.stack_latitude,
                "stack_longitude": row.stack_longitude,
                "source_unit_number": row.unit_number,
            }
        )

    grouped: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in mapped_rows:
        key = (
            row["subsidiary_company"],
            row["plant_name"],
            row["stack_height_m"],
            row["stack_diameter_m"],
            row["exit_temp_c"],
            row["flue_gas_velocity_m_s"],
            row["stack_latitude"],
            row["stack_longitude"],
        )
        grouped[key].append(row)

    reference_rows: list[dict[str, object]] = []
    unit_map_rows: list[dict[str, str]] = []
    for source_rows in grouped.values():
        source_rows = sorted(
            source_rows,
            key=lambda item: (
                str(item["subsidiary_company"]),
                str(item["plant_name"]),
                int(item["source_unit_number"] or 0),
            ),
        )
        first = source_rows[0]
        stack_id = _stack_id(
            str(first["subsidiary_company"]),
            str(first["plant_name"]),
            source_rows,
        )
        reporting_unit_ids = [str(row["reporting_unit_id"]) for row in source_rows]
        known_reporting_unit_ids = [value for value in reporting_unit_ids if value]
        reference_rows.append(
            {
                "subsidiary_company": first["subsidiary_company"],
                "plant_name": first["plant_name"],
                "stack_id": stack_id,
                "reporting_unit_id": known_reporting_unit_ids[0]
                if len(known_reporting_unit_ids) == 1 and len(source_rows) == 1
                else "",
                "stack_height_m": first["stack_height_m"],
                "stack_diameter_m": first["stack_diameter_m"],
                "exit_temp_c": first["exit_temp_c"],
                "flue_gas_velocity_m_s": first["flue_gas_velocity_m_s"],
                "stack_latitude": first["stack_latitude"],
                "stack_longitude": first["stack_longitude"],
                "match_status": "matched",
                "evidence_id": "crea_hia_south_korea_2021_appendix_2",
            }
        )
        for reporting_unit_id in known_reporting_unit_ids:
            unit_map_rows.append({"stack_id": stack_id, "reporting_unit_id": reporting_unit_id})

    reference_rows.extend(UNMATCHED_ROWS)
    reference = pd.DataFrame(reference_rows, columns=REFERENCE_COLUMNS).sort_values(
        ["subsidiary_company", "plant_name", "stack_id"]
    )
    unit_map = pd.DataFrame(unit_map_rows, columns=UNIT_MAP_COLUMNS).sort_values(
        ["stack_id", "reporting_unit_id"]
    )
    evidence = pd.DataFrame(
        [
            {
                "evidence_id": "crea_hia_south_korea_2021_appendix_2",
                "source_title": SOURCE_TITLE,
                "source_url": SOURCE_URL,
                "publication_date": PUBLICATION_DATE,
                "accessed_date": accessed_date.isoformat(),
                "evidence": (
                    "Appendix 2 Table A2 reports unit-level coordinates, stack height, "
                    "diameter, exit temperature, and flue gas velocity used as CALPUFF "
                    "model inputs for South Korean coal-fired power plants. KEPCO coal "
                    "plants present in this project are matched by source plant name and "
                    "unit number. Boryeong and Shin-Boryeong remain explicitly "
                    "unmatched pending review of source stack units against their new "
                    "provider aggregate boundaries; Yeongdong is unmatched because the "
                    "appendix does not include a Yeongdong row."
                ),
            }
        ],
        columns=EVIDENCE_COLUMNS,
    )
    return reference, unit_map, evidence


def write_crosswalk_tables(
    *,
    reference_path: str | None = None,
    unit_map_path: str | None = None,
    evidence_path: str | None = None,
    accessed_date: date | None = None,
) -> None:
    """Download, extract, and write the standalone stack crosswalk tables."""
    reference, unit_map, evidence = build_crosswalk_tables(
        extract_source_stack_rows(download_source_pdf()),
        accessed_date=accessed_date or date.today(),
    )
    reference.to_csv(reference_path or DEFAULT_REFERENCE_PATH, index=False)
    unit_map.to_csv(unit_map_path or DEFAULT_UNIT_MAP_PATH, index=False)
    evidence.to_csv(evidence_path or DEFAULT_EVIDENCE_PATH, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-path")
    parser.add_argument("--unit-map-path")
    parser.add_argument("--evidence-path")
    parser.add_argument(
        "--accessed-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Access date in YYYY-MM-DD form.",
    )
    args = parser.parse_args()
    write_crosswalk_tables(
        reference_path=args.reference_path,
        unit_map_path=args.unit_map_path,
        evidence_path=args.evidence_path,
        accessed_date=args.accessed_date,
    )


if __name__ == "__main__":
    main()
