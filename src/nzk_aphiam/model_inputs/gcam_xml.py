"""Stream GCAM scenario XML archives into portable APHIAM interface tables."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import BinaryIO, Iterator, Sequence
import xml.sax
from xml.sax.handler import feature_external_ges
import zipfile

import pandas as pd

from nzk_aphiam.config.paths import GCAM_NZK_APHIAM_DIR, GCAM_NZK_ARCHIVE, PROJECT_ROOT

SECTOR_TAGS = {
    "supplysector",
    "AgSupplySector",
    "pass-through-sector",
    "energy-final-demand",
}
SUBSECTOR_TAGS = {
    "subsector",
    "AgSupplySubsector",
    "tranSubsector",
    "nesting-subsector",
}
TECHNOLOGY_TAGS = {
    "technology",
    "AgProductionTechnology",
    "tranTechnology",
    "pass-through-technology",
    "UnmanagedLandTechnology",
    "intermittent-technology",
    "resource-reserve-technology",
}
VALUE_TAGS = {"physical-output", "demand-physical", "emissions"}
POLLUTANT_ALIASES = {
    "SO2_2": "SOx",
    "SO2_2_AWB": "SOx",
    "NOx": "NOx",
    "NOx_AGR": "NOx",
    "NOx_AWB": "NOx",
    "NH3": "NH3",
    "NH3_AGR": "NH3",
    "NH3_AWB": "NH3",
    "NMVOC": "VOCs",
    "NMVOC_AGR": "VOCs",
    "NMVOC_AWB": "VOCs",
    "BC": "BC",
    "BC_AWB": "BC",
    "OC": "OC",
    "OC_AWB": "OC",
    "CO": "CO",
    "CO_AWB": "CO",
}
DEFAULT_YEARS = (2021, 2025, 2030, 2035, 2040, 2045, 2050)
MAX_XML_BYTES = 12 * 1024**3

ACTIVITY_COLUMNS = [
    "scenario",
    "source_scenario",
    "region",
    "year",
    "record_type",
    "sector_type",
    "sector",
    "subsector_type",
    "subsector",
    "technology_type",
    "technology",
    "node_type",
    "node",
    "activity",
    "activity_unit",
]
EMISSIONS_COLUMNS = [
    "scenario",
    "source_scenario",
    "region",
    "year",
    "sector_type",
    "sector",
    "subsector_type",
    "subsector",
    "technology_type",
    "technology",
    "native_pollutant",
    "pollutant",
    "native_emissions",
    "native_emissions_unit",
    "emissions_kg",
]


class GcamXmlError(ValueError):
    """Raised when a GCAM XML handoff cannot be validated or extracted."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return path.name


@contextmanager
def open_gcam_xml(path: Path) -> Iterator[tuple[BinaryIO, str, int]]:
    """Open a plain XML file or a ZIP containing exactly one XML member."""
    if not path.is_file():
        raise FileNotFoundError(path)
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes and suffixes[-1] == ".xml":
        with path.open("rb") as stream:
            yield stream, path.name, path.stat().st_size
        return
    if not suffixes or suffixes[-1] != ".zip":
        raise GcamXmlError(f"{path} must be an XML file or a ZIP containing one XML file.")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise GcamXmlError(f"{path} is not a readable ZIP archive.") from error
    with archive:
        members = [
            item
            for item in archive.infolist()
            if not item.is_dir() and item.filename.lower().endswith(".xml")
        ]
        if len(members) != 1:
            raise GcamXmlError(
                f"{path} must contain exactly one XML member; found {[item.filename for item in members]}."
            )
        member = members[0]
        if member.file_size > MAX_XML_BYTES:
            raise GcamXmlError(
                f"{member.filename} is {member.file_size} bytes, above the {MAX_XML_BYTES}-byte safety limit."
            )
        with archive.open(member) as stream:
            yield stream, member.filename, member.file_size


def _nearest(stack: Sequence[tuple[str, dict[str, str]]], tags: set[str]) -> tuple[str, str]:
    return next(
        ((tag, attributes.get("name", "")) for tag, attributes in reversed(stack) if tag in tags),
        ("", ""),
    )


def _emissions_to_kg(value: float, unit: str) -> float | None:
    multiplier = {
        "Tg": 1_000_000_000.0,
        "Mt": 1_000_000_000.0,
        "Gg": 1_000_000.0,
        "kt": 1_000_000.0,
        "kg": 1.0,
    }.get(unit)
    return value * multiplier if multiplier is not None else None


class _GcamHandler(xml.sax.ContentHandler):
    def __init__(
        self,
        *,
        region: str,
        scenario_label: str,
        years: set[int] | None,
        collect_rows: bool,
    ) -> None:
        super().__init__()
        self.target_region = region
        self.scenario_label = scenario_label
        self.years = years
        self.collect_rows = collect_rows
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.text_stack: list[list[str] | None] = []
        self.in_target_region = False
        self.source_scenario = ""
        self.scenario_date = ""
        self.model_version = ""
        self.model_years: list[int] = []
        self.regions: list[str] = []
        self.activity_rows: list[dict[str, object]] = []
        self.emissions_rows: list[dict[str, object]] = []
        self.tag_counts: Counter[str] = Counter()

    def startElement(self, name: str, attrs: xml.sax.xmlreader.AttributesImpl) -> None:
        attributes = dict(attrs)
        self.stack.append((name, attributes))
        self.text_stack.append(
            [] if name in {*VALUE_TAGS, "model-version", "model-year"} else None
        )
        if name == "scenario":
            self.source_scenario = attributes.get("name", "")
            self.scenario_date = attributes.get("date", "")
        if name == "region":
            region = attributes.get("name", "")
            self.regions.append(region)
            self.in_target_region = region == self.target_region
        if self.in_target_region:
            self.tag_counts[name] += 1

    def characters(self, content: str) -> None:
        if self.text_stack and self.text_stack[-1] is not None:
            self.text_stack[-1].append(content)

    def endElement(self, name: str) -> None:
        text_parts = self.text_stack[-1]
        text = "".join(text_parts).strip() if text_parts is not None else ""
        if name == "model-version":
            self.model_version = text
        elif name == "model-year" and text:
            self.model_years.append(int(text))
        elif self.collect_rows and self.in_target_region and name in VALUE_TAGS:
            self._collect_value(name, text)
        if name == "region" and self.in_target_region:
            self.in_target_region = False
        self.stack.pop()
        self.text_stack.pop()

    def _collect_value(self, name: str, text: str) -> None:
        attributes = self.stack[-1][1]
        raw_year = attributes.get("vintage") or attributes.get("year")
        if not raw_year:
            return
        year = int(raw_year)
        if self.years is not None and year not in self.years:
            return
        try:
            value = float(text)
        except ValueError as error:
            raise GcamXmlError(f"Non-numeric {name} value {text!r} for year {year}.") from error
        if not math.isfinite(value):
            raise GcamXmlError(f"Non-finite {name} value {text!r} for year {year}.")
        ancestors = self.stack[:-1]
        sector_type, sector = _nearest(ancestors, SECTOR_TAGS)
        subsector_type, subsector = _nearest(ancestors, SUBSECTOR_TAGS)
        technology_type, technology = _nearest(ancestors, TECHNOLOGY_TAGS)
        parent_type, parent_attributes = ancestors[-1] if ancestors else ("", {})
        common = {
            "scenario": self.scenario_label,
            "source_scenario": self.source_scenario,
            "region": self.target_region,
            "year": year,
            "sector_type": sector_type,
            "sector": sector,
            "subsector_type": subsector_type,
            "subsector": subsector,
            "technology_type": technology_type,
            "technology": technology,
        }
        if name in {"physical-output", "demand-physical"}:
            self.activity_rows.append(
                {
                    **common,
                    "record_type": "output" if name == "physical-output" else "input",
                    "node_type": parent_type,
                    "node": parent_attributes.get("name", ""),
                    "activity": value,
                    "activity_unit": attributes.get("unit", ""),
                }
            )
            return
        native_pollutant = next(
            (
                ancestor_attributes.get("name", "")
                for tag, ancestor_attributes in reversed(ancestors)
                if tag in {"Non-CO2", "CO2"}
            ),
            "",
        )
        unit = attributes.get("unit", "")
        mass_kg = _emissions_to_kg(value, unit)
        self.emissions_rows.append(
            {
                **common,
                "native_pollutant": native_pollutant,
                "pollutant": POLLUTANT_ALIASES.get(native_pollutant, native_pollutant),
                "native_emissions": value,
                "native_emissions_unit": unit,
                "emissions_kg": mass_kg,
            }
        )


def _parse(
    path: Path,
    *,
    region: str,
    scenario_label: str,
    years: set[int] | None,
    collect_rows: bool,
) -> tuple[_GcamHandler, str, int]:
    handler = _GcamHandler(
        region=region,
        scenario_label=scenario_label,
        years=years,
        collect_rows=collect_rows,
    )
    parser = xml.sax.make_parser()
    try:
        parser.setFeature(feature_external_ges, False)
    except (xml.sax.SAXNotRecognizedException, xml.sax.SAXNotSupportedException):
        pass
    parser.setContentHandler(handler)
    try:
        with open_gcam_xml(path) as (stream, member_name, member_size):
            parser.parse(stream)
    except xml.sax.SAXParseException as error:
        raise GcamXmlError(
            f"{path} contains incomplete or invalid XML at line {error.getLineNumber()}, "
            f"column {error.getColumnNumber()}: {error.getMessage()}"
        ) from error
    if not handler.source_scenario:
        raise GcamXmlError(f"{path} does not contain a named GCAM scenario root.")
    if region not in handler.regions:
        raise GcamXmlError(
            f"{path} does not contain region {region!r}; available regions: {handler.regions}"
        )
    return handler, member_name, member_size


def inspect_gcam_source(path: Path, *, region: str = "South Korea") -> dict[str, object]:
    """Validate a GCAM XML source and return its structural metadata."""
    handler, member_name, member_size = _parse(
        path,
        region=region,
        scenario_label="inspection",
        years=None,
        collect_rows=False,
    )
    return {
        "source_scenario": handler.source_scenario,
        "scenario_date": handler.scenario_date,
        "model_version": handler.model_version,
        "model_years": handler.model_years,
        "regions": handler.regions,
        "target_region": region,
        "xml_member": member_name,
        "xml_uncompressed_size_bytes": member_size,
        "target_region_tag_counts": dict(sorted(handler.tag_counts.items())),
    }


def extract_gcam_source(
    path: Path,
    *,
    output_dir: Path,
    region: str = "South Korea",
    scenario_label: str = "nzk",
    years: Sequence[int] = DEFAULT_YEARS,
) -> dict[str, object]:
    """Extract activity and native-emissions tables without materializing the XML."""
    selected_years = {int(year) for year in years}
    handler, member_name, member_size = _parse(
        path,
        region=region,
        scenario_label=scenario_label,
        years=selected_years,
        collect_rows=True,
    )
    activity = pd.DataFrame(handler.activity_rows, columns=ACTIVITY_COLUMNS)
    emissions = pd.DataFrame(handler.emissions_rows, columns=EMISSIONS_COLUMNS)
    if activity.empty:
        raise GcamXmlError(
            f"No activity rows were extracted for {region} and years {sorted(years)}."
        )
    activity = activity.sort_values(
        [
            "scenario",
            "year",
            "sector_type",
            "sector",
            "subsector",
            "technology",
            "record_type",
            "node",
        ],
        kind="stable",
    ).reset_index(drop=True)
    emissions = emissions.sort_values(
        [
            "scenario",
            "year",
            "sector_type",
            "sector",
            "subsector",
            "technology",
            "native_pollutant",
        ],
        kind="stable",
    ).reset_index(drop=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"gcam_kaist_{scenario_label}"
    paths = {
        "activity_parquet": output_dir / f"{prefix}_activity.parquet",
        "activity_csv": output_dir / f"{prefix}_activity.csv",
        "native_emissions_parquet": output_dir / f"{prefix}_native_emissions.parquet",
        "native_emissions_csv": output_dir / f"{prefix}_native_emissions.csv",
        "metadata": output_dir / f"{prefix}_extraction.metadata.json",
    }
    activity.to_parquet(paths["activity_parquet"], index=False)
    activity.to_csv(paths["activity_csv"], index=False)
    emissions.to_parquet(paths["native_emissions_parquet"], index=False)
    emissions.to_csv(paths["native_emissions_csv"], index=False)

    metadata: dict[str, object] = {
        "dataset": "GCAM-KAIST scenario XML interface",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": _portable_path(path),
        "source_sha256": _sha256(path),
        "source_scenario": handler.source_scenario,
        "scenario_label": scenario_label,
        "scenario_date": handler.scenario_date,
        "model_version": handler.model_version,
        "model_years": handler.model_years,
        "selected_years": sorted(selected_years),
        "regions": handler.regions,
        "target_region": region,
        "xml_member": member_name,
        "xml_uncompressed_size_bytes": member_size,
        "activity_rows": int(len(activity)),
        "native_emissions_rows": int(len(emissions)),
        "native_pollutants": sorted(emissions["native_pollutant"].dropna().unique()),
        "outputs": {key: path.name for key, path in paths.items() if key != "metadata"},
        "analytical_use_permitted": False,
        "limitations": [
            "Native GCAM emissions are a validation lane, not approved Korean activity-times-EF emissions.",
            "The XML contains national South Korea results but no subnational coordinates.",
            "Primary PM2.5 is not inferred from BC and OC.",
        ],
    }
    paths["metadata"].write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def _parse_years(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=GCAM_NZK_ARCHIVE)
    parser.add_argument("--output-dir", type=Path, default=GCAM_NZK_APHIAM_DIR)
    parser.add_argument("--region", default="South Korea")
    parser.add_argument("--scenario-label", default="nzk")
    parser.add_argument(
        "--years",
        type=_parse_years,
        default=list(DEFAULT_YEARS),
        help="Comma-separated model years.",
    )
    parser.add_argument("--inspect-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.inspect_only:
        result = inspect_gcam_source(args.source, region=args.region)
    else:
        result = extract_gcam_source(
            args.source,
            output_dir=args.output_dir,
            region=args.region,
            scenario_label=args.scenario_label,
            years=args.years,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
