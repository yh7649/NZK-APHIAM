"""Validate KEPCO EFs using observed EPSIS generation against CAPSS emissions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

import pandas as pd
import requests

from nzk_aphiam.config.paths import (
    PROCESSED_DIR,
    RESULTS_DIAGNOSTICS_DIR,
    RESULTS_TABLES_DIR,
)
from nzk_aphiam.integration.macro_kepco_validation import (
    DEFAULT_CAPSS_ACTUAL,
    DEFAULT_KEPCO_EF,
    compare_to_capss,
    prepare_kepco_ef,
)

EPSIS_GENERATION_URL = "https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGesGrid.do?menuId=060102"
DEFAULT_OUTPUT_DIR = PROCESSED_DIR / "epsis"
DEFAULT_RESULT_DIR = RESULTS_TABLES_DIR / "epsis"
DEFAULT_DIAGNOSTIC_DIR = RESULTS_DIAGNOSTICS_DIR / "epsis"

EPSIS_VALUE_COLUMNS = {
    "c5": ("기력", "무연탄"),
    "c6": ("기력", "유연탄"),
    "c7": ("기력", "중유"),
    "c8": ("기력", "LNG"),
    "c10": ("복합화력", "LNG"),
    "c11": ("복합화력", "유류"),
    "c16": ("내연력", None),
}

EPSIS_TO_VALIDATION = (
    {
        "epsis_row_label_ko": "유연탄",
        "epsis_column": "c6",
        "kepco_fuel": "coal",
        "kepco_technology": "conventional_steam_turbine",
        "capss_fuel_major_ko": "유연탄",
        "capss_technology_official_ko": "1,2,3종(보일러)",
        "mapping_status": "documented_proxy",
        "mapping_note": "EPSIS bituminous-coal steam generation mapped to CAPSS bituminous-coal boiler and KEPCO pooled coal steam EF.",
    },
    {
        "epsis_row_label_ko": "무연탄",
        "epsis_column": "c5",
        "kepco_fuel": "coal",
        "kepco_technology": "conventional_steam_turbine",
        "capss_fuel_major_ko": "무연탄",
        "capss_technology_official_ko": "1,2,3종(보일러)",
        "mapping_status": "documented_proxy",
        "mapping_note": "EPSIS anthracite steam generation mapped to CAPSS anthracite boiler; KEPCO handoff exposes pooled coal steam EF.",
    },
    {
        "epsis_row_label_ko": "LNG",
        "epsis_column": "c10",
        "kepco_fuel": "natural_gas",
        "kepco_technology": "combined_cycle_gas_turbine",
        "capss_fuel_major_ko": "LNG",
        "capss_technology_official_ko": "가스터빈",
        "mapping_status": "documented_proxy",
        "mapping_note": "EPSIS LNG combined-cycle generation mapped to CAPSS LNG gas-turbine equipment.",
    },
    {
        "epsis_row_label_ko": "LNG",
        "epsis_column": "c8",
        "kepco_fuel": "natural_gas",
        "kepco_technology": "conventional_steam_turbine",
        "capss_fuel_major_ko": "LNG",
        "capss_technology_official_ko": "1,2,3종(보일러)",
        "mapping_status": "unresolved",
        "mapping_note": "EPSIS LNG steam exists, but the current 2021 KEPCO handoff has no natural-gas conventional-steam EF.",
    },
    {
        "epsis_row_label_ko": "유류",
        "epsis_column": "c16",
        "kepco_fuel": "oil",
        "kepco_technology": "internal_combustion_engine",
        "capss_fuel_major_ko": "B-C유",
        "capss_technology_official_ko": "내연기관",
        "mapping_status": "unresolved",
        "mapping_note": "EPSIS reports oil internal-combustion generation only as broad oil; current KEPCO handoff has no oil internal-combustion EF.",
    },
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_epsis_generation_html(html: str) -> pd.DataFrame:
    """Parse embedded EPSIS annual generation grid rows from the page HTML."""
    starts = [
        (int(match.group(1)), match.start())
        for match in re.finditer(
            r'if\(\$\("#srchDate option:selected"\)\.val\(\)=="(\d{4})"\)\{', html
        )
    ]
    rows: list[dict[str, object]] = []
    for index, (year, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(html)
        block = html[start:end]
        if "gridData.push" not in block:
            continue
        row: dict[str, object] = {"year": year}
        for variable in ["idx", "genName", *[f"c{column}" for column in range(1, 21)]]:
            match = re.search(rf'{variable}\s*=\s*"(.*?)"\s*;', block, flags=re.DOTALL)
            row[variable] = match.group(1).strip() if match else None
        rows.append(row)
    if not rows:
        raise ValueError("Could not parse EPSIS generation grid rows from HTML.")
    data = pd.DataFrame(rows).rename(columns={"genName": "epsis_row_label_ko"})
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    for column in [f"c{index}" for index in range(1, 21)]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data


def fetch_epsis_generation(url: str = EPSIS_GENERATION_URL, timeout: int = 30) -> pd.DataFrame:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return parse_epsis_generation_html(response.text)


def build_observed_generation(
    epsis_grid: pd.DataFrame, year: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = epsis_grid.loc[epsis_grid["year"] == year].copy()
    if selected.empty:
        raise ValueError(f"EPSIS generation grid has no rows for {year}.")
    records = []
    diagnostics = []
    for mapping in EPSIS_TO_VALIDATION:
        row = selected.loc[selected["epsis_row_label_ko"] == mapping["epsis_row_label_ko"]]
        generation_form_ko, energy_source_column_ko = EPSIS_VALUE_COLUMNS[mapping["epsis_column"]]
        if row.empty:
            diagnostics.append({**mapping, "diagnostic": "missing_epsis_row"})
            continue
        generation_gwh = float(row.iloc[0][mapping["epsis_column"]])
        record = {
            "scenario": "observed_epsis",
            "year": year,
            "province": "national",
            "epsis_row_label_ko": mapping["epsis_row_label_ko"],
            "epsis_generation_form_ko": generation_form_ko,
            "epsis_energy_source_column_ko": energy_source_column_ko,
            "generation_original": generation_gwh,
            "generation_original_unit": "GWh",
            "generation_mwh": generation_gwh * 1000.0,
            **mapping,
        }
        records.append(record)
        if mapping["mapping_status"] != "documented_proxy":
            diagnostics.append({**record, "diagnostic": "not_in_primary_comparison"})
    observed = pd.DataFrame(records)
    return observed, pd.DataFrame(diagnostics)


def _read_capss_actual(path: Path, year: int) -> pd.DataFrame:
    capss = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    actual = capss.loc[capss["year"] == year].copy()
    actual = actual.rename(columns={"emissions_kg": "actual_capss_emissions_kg"})
    actual["actual_capss_emissions_tonnes"] = actual["actual_capss_emissions_kg"] / 1000.0
    return actual[
        [
            "year",
            "fuel_major_ko",
            "technology_official_ko",
            "pollutant",
            "actual_capss_emissions_kg",
            "actual_capss_emissions_tonnes",
        ]
    ]


def calculate_epsis_modeled(
    observed_generation: pd.DataFrame, kepco_ef: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    primary = observed_generation.loc[
        observed_generation["mapping_status"] == "documented_proxy"
    ].copy()
    modeled = primary.merge(kepco_ef, how="left", on=["kepco_fuel", "kepco_technology"])
    missing_ef = modeled.loc[
        modeled["emission_factor_kg_per_mwh"].isna(),
        [
            "epsis_row_label_ko",
            "epsis_generation_form_ko",
            "kepco_fuel",
            "kepco_technology",
            "capss_fuel_major_ko",
            "capss_technology_official_ko",
        ],
    ].drop_duplicates()
    modeled = modeled.dropna(subset=["emission_factor_kg_per_mwh"]).copy()
    modeled["macro_fuel"] = modeled["epsis_row_label_ko"]
    modeled["macro_technology"] = modeled["epsis_generation_form_ko"]
    modeled["modeled_emissions_kg"] = (
        modeled["generation_mwh"] * modeled["emission_factor_kg_per_mwh"]
    )
    modeled["modeled_emissions_tonnes"] = modeled["modeled_emissions_kg"] / 1000.0
    return modeled, missing_ef


def write_diagnostic_html_note(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<p>"
        + escape(
            "EPSIS observed generation is parsed from the embedded annual energy-source grid. "
            "The public page labels units as GWh and the page menu as 발전량 > 에너지원별."
        )
        + "</p>\n",
        encoding="utf-8",
    )


def run_validation(
    *,
    year: int,
    kepco_ef_path: Path,
    capss_actual_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    result_dir: Path = DEFAULT_RESULT_DIR,
    diagnostic_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
    epsis_url: str = EPSIS_GENERATION_URL,
) -> dict[str, object]:
    epsis_grid = fetch_epsis_generation(epsis_url)
    observed_generation, generation_diagnostics = build_observed_generation(epsis_grid, year)
    kepco_ef = prepare_kepco_ef(kepco_ef_path, year)
    modeled, missing_ef = calculate_epsis_modeled(observed_generation, kepco_ef)
    capss_actual = _read_capss_actual(capss_actual_path, year)
    comparison, missing_capss = compare_to_capss(modeled, capss_actual)

    output_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    epsis_grid.to_csv(output_dir / "epsis_energy_source_generation_grid.csv", index=False)
    observed_generation.to_csv(
        output_dir / f"epsis_observed_generation_for_validation_{year}.csv", index=False
    )
    modeled.to_csv(output_dir / f"epsis_{year}_kepco_ef_modeled_emissions.csv", index=False)
    comparison.to_csv(result_dir / f"epsis_{year}_kepco_ef_vs_capss_actual.csv", index=False)
    comparison.groupby("pollutant", as_index=False).agg(
        total_modeled_kg=("modeled_emissions_kg", "sum"),
        total_actual_kg=("actual_capss_emissions_kg", "sum"),
        total_absolute_error_kg=("absolute_error_kg", "sum"),
    ).to_csv(result_dir / f"epsis_{year}_kepco_ef_vs_capss_summary.csv", index=False)
    generation_diagnostics.to_csv(
        diagnostic_dir / f"epsis_{year}_unmodeled_generation_rows.csv", index=False
    )
    missing_ef.to_csv(diagnostic_dir / f"epsis_{year}_missing_kepco_ef.csv", index=False)
    missing_capss.to_csv(diagnostic_dir / f"epsis_{year}_missing_capss_actual.csv", index=False)
    write_diagnostic_html_note(diagnostic_dir / f"epsis_{year}_source_note.html")
    metadata = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "epsis_url": epsis_url,
        "epsis_unit": "GWh",
        "kepco_ef_path": str(kepco_ef_path),
        "capss_actual_path": str(capss_actual_path),
        "input_checksums": {
            "kepco_ef": _file_sha256(kepco_ef_path),
            "capss_actual": _file_sha256(capss_actual_path),
        },
        "row_counts": {
            "epsis_grid": int(len(epsis_grid)),
            "observed_generation_validation_rows": int(len(observed_generation)),
            "modeled": int(len(modeled)),
            "comparison": int(len(comparison)),
        },
    }
    (diagnostic_dir / f"epsis_{year}_validation_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2021)
    parser.add_argument("--kepco-ef", type=Path, default=DEFAULT_KEPCO_EF)
    parser.add_argument("--capss-actual", type=Path, default=DEFAULT_CAPSS_ACTUAL)
    parser.add_argument("--epsis-url", default=EPSIS_GENERATION_URL)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    metadata = run_validation(
        year=args.year,
        kepco_ef_path=args.kepco_ef,
        capss_actual_path=args.capss_actual,
        epsis_url=args.epsis_url,
    )
    print(json.dumps(metadata["row_counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
