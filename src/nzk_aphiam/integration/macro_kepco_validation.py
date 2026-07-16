"""Validate 2021 MACRO generation times KEPCO EFs against CAPSS power emissions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import sys

import pandas as pd

from nzk_aphiam.config.paths import MACRO_PROCESSED_DIR, PROJECT_ROOT

DEFAULT_KEPCO_EF = (
    PROJECT_ROOT
    / "results"
    / "tables"
    / "kepco"
    / "annual_handoff"
    / "kepco_annual_ef_distribution_long_by_fuel_technology.csv"
)
DEFAULT_CAPSS_ACTUAL = (
    PROJECT_ROOT / "data" / "processed" / "capss" / "power_fuel_technology_2016_2023.parquet"
)
DEFAULT_CROSSWALK = (
    PROJECT_ROOT / "docs" / "references" / "macro" / "macro_kepco_capss_power_crosswalk.csv"
)
DEFAULT_RESULT_DIR = PROJECT_ROOT / "results" / "tables" / "macro"
DEFAULT_DIAGNOSTIC_DIR = PROJECT_ROOT / "results" / "diagnostics" / "macro"
DEFAULT_FIGURE_DIR = PROJECT_ROOT / "results" / "figures" / "macro" / "validation_2021"

POLLUTANT_LABELS = {"nox": "NOx", "sox": "SOx", "dust_tsp": "TSP", "tsp": "TSP"}
ACCEPTED_MAPPING_STATUSES = {"exact", "documented_proxy"}
GENERATION_UNIT_FACTORS = {"MWh": 1.0, "GWh": 1000.0, "TWh": 1_000_000.0, "kWh": 0.001}
CROSSWALK_COLUMNS = (
    "macro_fuel",
    "macro_technology",
    "kepco_fuel",
    "kepco_technology",
    "capss_fuel_major_ko",
    "capss_technology_official_ko",
    "mapping_status",
    "mapping_note",
)


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    if path.suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported table format for {path}; use CSV, Excel, or Parquet.")


def _write_table(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        data.to_parquet(path, index=False)
    else:
        data.to_csv(path, index=False, encoding="utf-8")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _find_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {_norm(column).replace("_", " "): column for column in columns}
    for candidate in candidates:
        key = candidate.lower().replace("_", " ")
        if key in normalized:
            return normalized[key]
    for column in columns:
        key = _norm(column)
        if any(candidate.lower() in key for candidate in candidates):
            return column
    return None


def split_macro_type(value: object) -> tuple[str, str]:
    """Split MACRO combined labels such as ThermalPower{Coal} into fuel/technology."""
    text = "" if pd.isna(value) else str(value).strip()
    match = re.fullmatch(r"(?P<technology>[^{}]+)\{(?P<fuel>[^{}]+)\}", text)
    if match:
        return match.group("fuel").strip(), match.group("technology").strip()
    return text, text


def discover_macro_generation() -> Path:
    roots = [PROJECT_ROOT / "data" / stage / "macro" for stage in ("raw", "interim", "processed")]
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(
                path
                for path in root.rglob("*")
                if path.suffix.lower() in {".csv", ".parquet", ".xlsx", ".xls"}
            )
    for path in sorted(candidates):
        try:
            data = _read_table(path).head(20)
        except Exception:
            continue
        columns = list(data.columns)
        has_generation = _find_column(columns, ("generation_mwh", "generation", "mwh", "gwh"))
        has_year = _find_column(columns, ("year",))
        has_fuel = _find_column(columns, ("fuel", "type"))
        if has_generation and has_year and has_fuel:
            return path
    searched = ", ".join(str(root) for root in roots)
    raise FileNotFoundError(
        "Could not find a local MACRO generation table with year/fuel/generation columns. "
        f"Searched: {searched}. Supply --macro-generation explicitly."
    )


def prepare_kepco_ef(path: Path, year: int) -> pd.DataFrame:
    data = _read_table(path)
    if {"year", "fuel_type_clean", "technology", "pollutant", "ef_kg_per_mwh"}.issubset(
        data.columns
    ):
        ef = data.loc[data["year"] == year].copy()
        ef["pollutant"] = ef["pollutant"].map(
            lambda value: POLLUTANT_LABELS.get(_norm(value), value)
        )
        ef = ef.rename(
            columns={
                "year": "ef_year",
                "fuel_type_clean": "kepco_fuel",
                "technology": "kepco_technology",
                "ef_kg_per_mwh": "emission_factor_kg_per_mwh",
                "valid_generation_mwh": "generation_mwh_used_for_ef",
                "plant_count": "n_plants_or_units",
            }
        )
        ef["emissions_kg_used_for_ef"] = (
            ef["emission_factor_kg_per_mwh"] * ef["generation_mwh_used_for_ef"]
        )
        ef["coverage_flag"] = (
            ef["generation_mwh_used_for_ef"]
            .notna()
            .map({True: "reported_generation_weighted", False: "missing_generation_weight"})
        )
    else:
        rows: list[dict[str, object]] = []
        for _, row in data.loc[data["year"] == year].iterrows():
            for source, pollutant in [("nox", "NOx"), ("sox", "SOx"), ("dust_tsp", "TSP")]:
                field = f"{source}_ef_kg_per_mwh"
                if field not in data.columns or pd.isna(row.get(field)):
                    continue
                rows.append(
                    {
                        "ef_year": year,
                        "kepco_fuel": row["fuel_type_clean"],
                        "kepco_technology": row["technology"],
                        "pollutant": pollutant,
                        "emission_factor_kg_per_mwh": row[field],
                        "generation_mwh_used_for_ef": row.get(f"{source}_valid_generation_mwh"),
                        "emissions_kg_used_for_ef": row[field]
                        * row.get(f"{source}_valid_generation_mwh"),
                        "n_plants_or_units": row.get(f"{source}_plant_count"),
                        "coverage_flag": "reported_generation_weighted",
                    }
                )
        ef = pd.DataFrame(rows)
    if ef.empty:
        raise ValueError(f"{path} contains no KEPCO EF rows for {year}.")
    keep = [
        "ef_year",
        "kepco_fuel",
        "kepco_technology",
        "pollutant",
        "emission_factor_kg_per_mwh",
        "generation_mwh_used_for_ef",
        "emissions_kg_used_for_ef",
        "n_plants_or_units",
        "coverage_flag",
    ]
    ef = ef[keep].copy()
    ef["emission_factor_kg_per_mwh"] = pd.to_numeric(
        ef["emission_factor_kg_per_mwh"], errors="coerce"
    )
    return ef.dropna(subset=["emission_factor_kg_per_mwh"])


def detect_generation_unit(column: str, explicit_unit: str | None = None) -> str:
    if explicit_unit:
        if explicit_unit not in GENERATION_UNIT_FACTORS:
            raise ValueError(f"Unsupported generation unit {explicit_unit}.")
        return explicit_unit
    lowered = column.lower()
    for unit in ("MWh", "GWh", "TWh", "kWh"):
        if unit.lower() in lowered:
            return unit
    raise ValueError(
        f"Could not determine generation unit from column {column!r}; supply --generation-unit."
    )


def standardize_macro_generation(
    data: pd.DataFrame,
    *,
    source_file: Path,
    year: int,
    generation_unit: str | None = None,
) -> pd.DataFrame:
    columns = list(data.columns)
    year_col = _find_column(columns, ("year",))
    generation_col = _find_column(
        columns, ("generation_mwh", "generation_gwh", "generation", "mwh", "gwh")
    )
    fuel_col = _find_column(columns, ("macro_fuel", "fuel"))
    tech_col = _find_column(columns, ("macro_technology", "technology", "tech"))
    type_col = _find_column(columns, ("type",))
    province_col = _find_column(columns, ("province", "region", "sido"))
    scenario_col = _find_column(columns, ("scenario",))
    if not year_col or not generation_col:
        raise ValueError("MACRO generation data must include year and generation columns.")
    if not fuel_col and not type_col and not tech_col:
        raise ValueError(
            "MACRO generation data must include fuel, technology, or combined type for crosswalking."
        )

    unit = detect_generation_unit(generation_col, generation_unit)
    prepared = data.loc[pd.to_numeric(data[year_col], errors="coerce") == year].copy()
    prepared["scenario"] = (
        prepared[scenario_col].astype("string") if scenario_col else "historical_or_reference"
    )
    prepared["year"] = year
    prepared["province"] = prepared[province_col].astype("string") if province_col else pd.NA
    combined_col = type_col or tech_col
    prepared["macro_type"] = prepared[combined_col].astype("string") if combined_col else pd.NA
    if fuel_col:
        prepared["macro_fuel"] = prepared[fuel_col].astype("string")
    else:
        prepared["macro_fuel"] = prepared["macro_type"].map(
            lambda value: split_macro_type(value)[0]
        )
    if tech_col and fuel_col:
        prepared["macro_technology"] = prepared[tech_col].astype("string")
    elif type_col and tech_col:
        prepared["macro_technology"] = prepared[tech_col].astype("string")
    else:
        prepared["macro_technology"] = prepared["macro_type"].map(
            lambda value: split_macro_type(value)[1]
        )
    prepared["generation_original"] = pd.to_numeric(prepared[generation_col], errors="coerce")
    prepared["generation_original_unit"] = unit
    prepared["generation_mwh"] = prepared["generation_original"] * GENERATION_UNIT_FACTORS[unit]
    prepared["source_file"] = str(source_file)
    return prepared[
        [
            "scenario",
            "year",
            "province",
            "macro_fuel",
            "macro_technology",
            "macro_type",
            "generation_original",
            "generation_original_unit",
            "generation_mwh",
            "source_file",
        ]
    ]


def load_crosswalk(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    crosswalk = _read_table(path)
    missing = [column for column in CROSSWALK_COLUMNS if column not in crosswalk.columns]
    if missing:
        raise ValueError(f"crosswalk is missing required columns: {missing}")
    duplicate = crosswalk.duplicated(["macro_fuel", "macro_technology"], keep=False)
    duplicates = crosswalk.loc[duplicate, list(CROSSWALK_COLUMNS)].copy()
    usable = crosswalk.loc[
        crosswalk["mapping_status"].isin(ACCEPTED_MAPPING_STATUSES), list(CROSSWALK_COLUMNS)
    ].copy()
    return usable, duplicates


def calculate_modeled_emissions(
    macro_generation: pd.DataFrame, kepco_ef: pd.DataFrame, crosswalk: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mapped = macro_generation.merge(crosswalk, how="left", on=["macro_fuel", "macro_technology"])
    unmapped = mapped.loc[
        ~mapped["mapping_status"].isin(ACCEPTED_MAPPING_STATUSES), macro_generation.columns
    ].copy()
    primary = mapped.loc[mapped["mapping_status"].isin(ACCEPTED_MAPPING_STATUSES)].copy()
    modeled = primary.merge(kepco_ef, how="left", on=["kepco_fuel", "kepco_technology"])
    missing_ef = modeled.loc[
        modeled["emission_factor_kg_per_mwh"].isna(),
        [
            "macro_fuel",
            "macro_technology",
            "kepco_fuel",
            "kepco_technology",
            "capss_fuel_major_ko",
            "capss_technology_official_ko",
        ],
    ].drop_duplicates()
    modeled = modeled.dropna(subset=["emission_factor_kg_per_mwh"]).copy()
    modeled["modeled_emissions_kg"] = (
        modeled["generation_mwh"] * modeled["emission_factor_kg_per_mwh"]
    )
    modeled["modeled_emissions_tonnes"] = modeled["modeled_emissions_kg"] / 1000.0
    return modeled, unmapped, missing_ef


def load_capss_actual(path: Path, year: int) -> pd.DataFrame:
    capss = _read_table(path)
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


def compare_to_capss(
    modeled: pd.DataFrame, capss_actual: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    modeled_national = modeled.groupby(
        [
            "year",
            "macro_fuel",
            "macro_technology",
            "kepco_fuel",
            "kepco_technology",
            "capss_fuel_major_ko",
            "capss_technology_official_ko",
            "pollutant",
            "mapping_status",
            "mapping_note",
        ],
        dropna=False,
        as_index=False,
    ).agg(
        generation_mwh=("generation_mwh", "sum"),
        modeled_emissions_kg=("modeled_emissions_kg", "sum"),
        emission_factor_kg_per_mwh=("emission_factor_kg_per_mwh", "first"),
    )
    modeled_national["modeled_emissions_tonnes"] = (
        modeled_national["modeled_emissions_kg"] / 1000.0
    )
    comparison = modeled_national.merge(
        capss_actual,
        how="left",
        left_on=["year", "capss_fuel_major_ko", "capss_technology_official_ko", "pollutant"],
        right_on=["year", "fuel_major_ko", "technology_official_ko", "pollutant"],
    )
    missing_capss = comparison.loc[
        comparison["actual_capss_emissions_kg"].isna(),
        ["capss_fuel_major_ko", "capss_technology_official_ko", "pollutant"],
    ].drop_duplicates()
    comparison["actual_zero_flag"] = comparison["actual_capss_emissions_kg"].eq(0)
    comparison["signed_error_kg"] = (
        comparison["modeled_emissions_kg"] - comparison["actual_capss_emissions_kg"]
    )
    comparison["absolute_error_kg"] = comparison["signed_error_kg"].abs()
    comparison["percent_error"] = (
        100.0 * comparison["signed_error_kg"] / comparison["actual_capss_emissions_kg"]
    )
    comparison["modeled_to_actual_ratio"] = (
        comparison["modeled_emissions_kg"] / comparison["actual_capss_emissions_kg"]
    )
    comparison.loc[
        comparison["actual_zero_flag"] | comparison["actual_capss_emissions_kg"].isna(),
        ["percent_error", "modeled_to_actual_ratio"],
    ] = pd.NA
    comparison["fuel_standard"] = comparison["capss_fuel_major_ko"]
    comparison["technology_standard"] = comparison["capss_technology_official_ko"]
    columns = [
        "year",
        "fuel_standard",
        "technology_standard",
        "pollutant",
        "generation_mwh",
        "emission_factor_kg_per_mwh",
        "modeled_emissions_kg",
        "modeled_emissions_tonnes",
        "actual_capss_emissions_kg",
        "actual_capss_emissions_tonnes",
        "signed_error_kg",
        "absolute_error_kg",
        "percent_error",
        "modeled_to_actual_ratio",
        "actual_zero_flag",
        "mapping_status",
        "mapping_note",
    ]
    return comparison[columns], missing_capss


def build_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    summary = comparison.groupby("pollutant", dropna=False, as_index=False).agg(
        total_modeled_kg=("modeled_emissions_kg", "sum"),
        total_actual_kg=("actual_capss_emissions_kg", "sum"),
        total_absolute_error_kg=("absolute_error_kg", "sum"),
    )
    summary["total_signed_error_kg"] = summary["total_modeled_kg"] - summary["total_actual_kg"]
    summary["total_percent_error"] = (
        100.0 * summary["total_signed_error_kg"] / summary["total_actual_kg"]
    )
    summary.loc[summary["total_actual_kg"].eq(0), "total_percent_error"] = pd.NA
    return summary[
        [
            "pollutant",
            "total_modeled_kg",
            "total_actual_kg",
            "total_signed_error_kg",
            "total_absolute_error_kg",
            "total_percent_error",
        ]
    ]


def build_coverage(
    macro_generation: pd.DataFrame,
    modeled: pd.DataFrame,
    capss_actual: pd.DataFrame,
    comparison: pd.DataFrame,
) -> pd.DataFrame:
    total_generation = macro_generation["generation_mwh"].sum()
    matched_generation = (
        modeled[
            ["scenario", "year", "province", "macro_fuel", "macro_technology", "generation_mwh"]
        ]
        .drop_duplicates()["generation_mwh"]
        .sum()
    )
    rows = [
        {
            "metric": "matched_generation_share",
            "matched_value": matched_generation,
            "total_value": total_generation,
            "share": matched_generation / total_generation if total_generation else pd.NA,
        }
    ]
    for pollutant, actual in capss_actual.groupby("pollutant"):
        total = actual["actual_capss_emissions_kg"].sum()
        matched = comparison.loc[
            comparison["pollutant"] == pollutant, "actual_capss_emissions_kg"
        ].sum()
        rows.append(
            {
                "metric": f"matched_capss_emissions_share_{pollutant}",
                "matched_value": matched,
                "total_value": total,
                "share": matched / total if total else pd.NA,
            }
        )
    return pd.DataFrame(rows)


def make_figures(comparison: pd.DataFrame, coverage: pd.DataFrame, figure_dir: Path) -> list[str]:
    figure_dir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return make_svg_figures(comparison, coverage, figure_dir)

    paths: list[str] = []
    frame = comparison.copy()
    frame["fuel_technology"] = frame["fuel_standard"] + " / " + frame["technology_standard"]

    for pollutant, subset in frame.groupby("pollutant"):
        fig, ax = plt.subplots(figsize=(8, 4))
        plot = subset.set_index("fuel_technology")[
            ["modeled_emissions_tonnes", "actual_capss_emissions_tonnes"]
        ]
        plot.plot(kind="bar", ax=ax)
        ax.set_ylabel(f"{pollutant} tonnes")
        ax.set_xlabel("")
        fig.tight_layout()
        path = figure_dir / f"modeled_vs_capss_bars_{pollutant}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(str(path))

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(frame["actual_capss_emissions_tonnes"], frame["modeled_emissions_tonnes"])
    limit = max(
        frame["actual_capss_emissions_tonnes"].max(), frame["modeled_emissions_tonnes"].max()
    )
    ax.plot([0, limit], [0, limit], color="black", linewidth=1)
    ax.set_xlabel("CAPSS actual tonnes")
    ax.set_ylabel("Modeled tonnes")
    fig.tight_layout()
    path = figure_dir / "modeled_vs_actual_scatter.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(str(path))

    fig, ax = plt.subplots(figsize=(8, 4))
    frame.set_index("fuel_technology")["percent_error"].plot(kind="bar", ax=ax)
    ax.set_ylabel("Percent error")
    ax.set_xlabel("")
    fig.tight_layout()
    path = figure_dir / "percent_error_by_fuel_technology_pollutant.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(str(path))

    fig, ax = plt.subplots(figsize=(8, 4))
    coverage.set_index("metric")["share"].plot(kind="bar", ax=ax)
    ax.set_ylabel("Matched share")
    ax.set_ylim(0, 1)
    ax.set_xlabel("")
    fig.tight_layout()
    path = figure_dir / "validation_coverage.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(str(path))
    return paths


def _svg_bar_chart(
    data: pd.DataFrame,
    *,
    label_column: str,
    value_columns: list[str],
    title: str,
    ylabel: str,
    path: Path,
) -> str:
    width = 900
    height = 460
    margin_left = 90
    margin_top = 45
    plot_width = width - margin_left - 30
    plot_height = 280
    colors = ["#3568a8", "#c46a3a", "#4d8b57"]
    max_value = float(data[value_columns].max().max()) if not data.empty else 0.0
    max_value = max(max_value, 1.0)
    group_width = plot_width / max(len(data), 1)
    bar_width = group_width / (len(value_columns) + 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="16" font-family="Arial">{escape(title)}</text>',
        f'<text x="16" y="{margin_top + plot_height / 2}" transform="rotate(-90 16 {margin_top + plot_height / 2})" text-anchor="middle" font-size="12" font-family="Arial">{escape(ylabel)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{width - 30}" y2="{margin_top + plot_height}" stroke="#333"/>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#333"/>',
    ]
    for index, row in data.reset_index(drop=True).iterrows():
        for offset, column in enumerate(value_columns):
            value = float(row[column]) if pd.notna(row[column]) else 0.0
            bar_height = plot_height * value / max_value
            x = margin_left + index * group_width + offset * bar_width + bar_width * 0.5
            y = margin_top + plot_height - bar_height
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width * 0.85:.2f}" height="{bar_height:.2f}" fill="{colors[offset % len(colors)]}"/>'
            )
        label = escape(str(row[label_column]))
        x_label = margin_left + index * group_width + group_width / 2
        parts.append(
            f'<text x="{x_label:.2f}" y="{margin_top + plot_height + 18}" text-anchor="end" transform="rotate(-35 {x_label:.2f} {margin_top + plot_height + 18})" font-size="10" font-family="Arial">{label}</text>'
        )
    for offset, column in enumerate(value_columns):
        x = margin_left + offset * 170
        y = height - 28
        parts.append(
            f'<rect x="{x}" y="{y - 10}" width="12" height="12" fill="{colors[offset]}"/>'
        )
        parts.append(
            f'<text x="{x + 18}" y="{y}" font-size="11" font-family="Arial">{escape(column)}</text>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return str(path)


def _svg_scatter(data: pd.DataFrame, path: Path) -> str:
    width = 620
    height = 520
    margin = 70
    plot = width - 2 * margin
    max_value = max(
        float(data["actual_capss_emissions_tonnes"].max()),
        float(data["modeled_emissions_tonnes"].max()),
        1.0,
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="310" y="26" text-anchor="middle" font-size="16" font-family="Arial">Modeled versus CAPSS actual tonnes</text>',
        f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{margin}" stroke="#333" stroke-dasharray="4 4"/>',
        f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#333"/>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" stroke="#333"/>',
        '<text x="310" y="500" text-anchor="middle" font-size="12" font-family="Arial">CAPSS actual tonnes</text>',
        '<text x="18" y="260" transform="rotate(-90 18 260)" text-anchor="middle" font-size="12" font-family="Arial">Modeled tonnes</text>',
    ]
    for _, row in data.iterrows():
        x = margin + plot * float(row["actual_capss_emissions_tonnes"]) / max_value
        y = height - margin - plot * float(row["modeled_emissions_tonnes"]) / max_value
        label = escape(f"{row['fuel_standard']} {row['technology_standard']} {row['pollutant']}")
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#3568a8"><title>{label}</title></circle>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return str(path)


def make_svg_figures(
    comparison: pd.DataFrame, coverage: pd.DataFrame, figure_dir: Path
) -> list[str]:
    paths: list[str] = []
    frame = comparison.copy()
    frame["fuel_technology"] = frame["fuel_standard"] + " / " + frame["technology_standard"]
    for pollutant, subset in frame.groupby("pollutant"):
        paths.append(
            _svg_bar_chart(
                subset,
                label_column="fuel_technology",
                value_columns=["modeled_emissions_tonnes", "actual_capss_emissions_tonnes"],
                title=f"{pollutant}: modeled versus CAPSS actual",
                ylabel="Tonnes",
                path=figure_dir / f"modeled_vs_capss_bars_{pollutant}.svg",
            )
        )
    paths.append(_svg_scatter(frame, figure_dir / "modeled_vs_actual_scatter.svg"))
    percent = frame.copy()
    percent["label"] = percent["fuel_technology"] + " / " + percent["pollutant"]
    percent["percent_error_value"] = percent["percent_error"].abs()
    paths.append(
        _svg_bar_chart(
            percent,
            label_column="label",
            value_columns=["percent_error_value"],
            title="Absolute percent error by fuel-technology and pollutant",
            ylabel="Absolute percent error",
            path=figure_dir / "percent_error_by_fuel_technology_pollutant.svg",
        )
    )
    paths.append(
        _svg_bar_chart(
            coverage.rename(columns={"metric": "label", "share": "matched_share"}),
            label_column="label",
            value_columns=["matched_share"],
            title="Validation coverage",
            ylabel="Matched share",
            path=figure_dir / "validation_coverage.svg",
        )
    )
    return paths


def run_validation(
    *,
    year: int,
    kepco_ef_path: Path,
    macro_generation_path: Path | None,
    capss_actual_path: Path,
    crosswalk_path: Path,
    generation_unit: str | None = None,
    processed_dir: Path = MACRO_PROCESSED_DIR,
    result_dir: Path = DEFAULT_RESULT_DIR,
    diagnostic_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
    figure_dir: Path = DEFAULT_FIGURE_DIR,
) -> dict[str, object]:
    if macro_generation_path is None:
        macro_generation_path = discover_macro_generation()
    kepco_ef = prepare_kepco_ef(kepco_ef_path, year)
    macro_raw = _read_table(macro_generation_path)
    macro_generation = standardize_macro_generation(
        macro_raw, source_file=macro_generation_path, year=year, generation_unit=generation_unit
    )
    crosswalk, duplicate_crosswalk = load_crosswalk(crosswalk_path)
    modeled, unmapped_generation, missing_ef = calculate_modeled_emissions(
        macro_generation, kepco_ef, crosswalk
    )
    capss_actual = load_capss_actual(capss_actual_path, year)
    comparison, missing_capss = compare_to_capss(modeled, capss_actual)
    summary = build_summary(comparison)
    coverage = build_coverage(macro_generation, modeled, capss_actual, comparison)

    _write_table(
        modeled[
            [
                "scenario",
                "year",
                "province",
                "macro_fuel",
                "macro_technology",
                "kepco_fuel",
                "kepco_technology",
                "capss_fuel_major_ko",
                "capss_technology_official_ko",
                "pollutant",
                "generation_mwh",
                "emission_factor_kg_per_mwh",
                "modeled_emissions_kg",
                "modeled_emissions_tonnes",
                "mapping_status",
            ]
        ],
        processed_dir / "macro_2021_kepco_ef_modeled_emissions_by_province.csv",
    )
    _write_table(
        modeled,
        processed_dir / "macro_2021_kepco_ef_modeled_emissions_by_province.parquet",
    )
    _write_table(comparison, result_dir / "macro_2021_kepco_ef_vs_capss_actual.csv")
    _write_table(summary, result_dir / "macro_2021_kepco_ef_vs_capss_summary.csv")
    _write_table(unmapped_generation, diagnostic_dir / "macro_2021_unmapped_generation.csv")
    _write_table(missing_ef, diagnostic_dir / "macro_2021_missing_kepco_ef.csv")
    _write_table(missing_capss, diagnostic_dir / "macro_2021_missing_capss_actual.csv")
    _write_table(
        duplicate_crosswalk, diagnostic_dir / "macro_2021_duplicate_crosswalk_matches.csv"
    )
    _write_table(coverage, diagnostic_dir / "macro_2021_validation_coverage.csv")
    figures = make_figures(
        comparison.dropna(subset=["actual_capss_emissions_kg"]), coverage, figure_dir
    )

    metadata = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "input_files": {
            "kepco_ef": str(kepco_ef_path),
            "macro_generation": str(macro_generation_path),
            "capss_actual": str(capss_actual_path),
            "crosswalk": str(crosswalk_path),
        },
        "input_checksums": {
            "kepco_ef": _file_sha256(kepco_ef_path),
            "macro_generation": _file_sha256(macro_generation_path),
            "capss_actual": _file_sha256(capss_actual_path),
            "crosswalk": _file_sha256(crosswalk_path),
        },
        "selected_ef_field": "ef_kg_per_mwh",
        "ef_units": "kg/MWh",
        "generation_units": sorted(macro_generation["generation_original_unit"].dropna().unique()),
        "capss_source_year": year,
        "crosswalk_version": str(crosswalk_path),
        "excluded_categories": int(len(unmapped_generation)),
        "software_git_commit": None,
        "row_counts": {
            "macro_generation": int(len(macro_generation)),
            "modeled_province": int(len(modeled)),
            "comparison": int(len(comparison)),
        },
        "figures": figures,
    }
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    (diagnostic_dir / "macro_2021_validation_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2021)
    parser.add_argument("--kepco-ef", type=Path, default=DEFAULT_KEPCO_EF)
    parser.add_argument("--macro-generation", type=Path, default=None)
    parser.add_argument("--capss-actual", type=Path, default=DEFAULT_CAPSS_ACTUAL)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--generation-unit", choices=sorted(GENERATION_UNIT_FACTORS), default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    try:
        metadata = run_validation(
            year=args.year,
            kepco_ef_path=args.kepco_ef,
            macro_generation_path=args.macro_generation,
            capss_actual_path=args.capss_actual,
            crosswalk_path=args.crosswalk,
            generation_unit=args.generation_unit,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"macro_kepco_validation: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(metadata["row_counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
