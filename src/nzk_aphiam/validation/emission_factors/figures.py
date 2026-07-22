"""Dependency-light SVG figures for emission-factor validation outputs."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from xml.sax.saxutils import escape

import pandas as pd


def _scale(values: pd.Series, low: float, high: float, pixels_low: float, pixels_high: float):
    span = high - low if high != low else 1
    return pixels_low + (values - low) * (pixels_high - pixels_low) / span


def write_scatter_svg(comparisons: pd.DataFrame, output_path: Path) -> None:
    """Write A/B project-vs-external EF scatter with a one-to-one line."""
    data = comparisons.loc[
        comparisons["comparison_class"].isin(
            ["A_exact_reproduction", "B_plant_pipeline_validation"]
        )
        & comparisons["analysis_variant"].eq("reported")
    ].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 900, 620
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="35" font-size="20" font-family="sans-serif">Plant-level external validation</text>',
    ]
    if data.empty:
        parts.append(
            '<text x="30" y="80" font-size="14" font-family="sans-serif">No strict comparable matches.</text>'
        )
    else:
        pollutants = ["NOx", "SOx", "TSP", "combined"]
        colors = {"NOx": "#1f77b4", "SOx": "#d62728", "TSP": "#2ca02c", "combined": "#444444"}
        max_value = float(
            data[["kepco_ef_kg_per_mwh", "external_ef_kg_per_mwh"]].max().max() * 1.1
        )
        x0, y0, x1, y1 = 80, 540, 820, 80
        parts.extend(
            [
                f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="#999" stroke-dasharray="4 4"/>',
                f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#222"/>',
                f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#222"/>',
                f'<text x="{(x0 + x1) / 2 - 80}" y="590" font-size="13" font-family="sans-serif">Reference kg/MWh</text>',
                '<text x="15" y="330" font-size="13" font-family="sans-serif" transform="rotate(-90 15,330)">Project kg/MWh</text>',
            ]
        )
        for pollutant in pollutants:
            subset = data.loc[data["pollutant"].eq(pollutant)]
            if subset.empty:
                continue
            xs = _scale(subset["external_ef_kg_per_mwh"], 0, max_value, x0, x1)
            ys = _scale(subset["kepco_ef_kg_per_mwh"], 0, max_value, y0, y1)
            for (_, row), x, y in zip(subset.iterrows(), xs, ys, strict=True):
                label = f"{row['plant_name_en']} {pollutant}"
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{colors[pollutant]}"><title>{label}</title></circle>'
                )
        for i, pollutant in enumerate(pollutants):
            parts.append(
                f'<text x="690" y="{115 + i * 20}" fill="{colors[pollutant]}" font-size="13" font-family="sans-serif">{pollutant}</text>'
            )
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def write_percent_difference_svg(comparisons: pd.DataFrame, output_path: Path) -> None:
    """Write a simple percent-difference strip chart."""
    data = comparisons.loc[
        comparisons["comparison_class"].isin(
            ["A_exact_reproduction", "B_plant_pipeline_validation"]
        )
        & comparisons["analysis_variant"].eq("reported")
    ].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1000, max(320, 34 * len(data) + 90)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="35" font-size="20" font-family="sans-serif">Plant-level external validation: EF percent difference</text>',
    ]
    if not data.empty:
        bound = max(5.0, float(data["percent_difference"].abs().max() * 1.1))
        x_mid = 520
        parts.append(f'<line x1="{x_mid}" y1="60" x2="{x_mid}" y2="{height - 30}" stroke="#888"/>')
        for i, row in enumerate(
            data.sort_values(["plant_name_en", "pollutant"]).to_dict("records")
        ):
            y = 80 + i * 30
            x = float(
                _scale(pd.Series([row["percent_difference"]]), -bound, bound, 120, 920).iloc[0]
            )
            parts.append(
                f'<line x1="{x_mid}" y1="{y}" x2="{x:.1f}" y2="{y}" stroke="#3b6ea8" stroke-width="4"/>'
            )
            parts.append(f'<circle cx="{x:.1f}" cy="{y}" r="4" fill="#163d5c"/>')
            parts.append(
                f'<text x="30" y="{y + 4}" font-size="12" font-family="sans-serif">{row["plant_name_en"]} {row["pollutant"]}</text>'
            )
            parts.append(
                f'<text x="930" y="{y + 4}" font-size="12" font-family="sans-serif">{row["percent_difference"]:.1f}%</text>'
            )
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def write_timeseries_svg(
    project_annual: pd.DataFrame, literature: pd.DataFrame, output_path: Path
) -> None:
    """Write project annual EF time series with literature benchmark points."""
    data = project_annual.loc[
        project_annual["analysis_variant"].eq("reported")
        & project_annual["pollutant"].isin(["NOx", "SOx", "TSP"])
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1000, 620
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="35" font-size="20" font-family="sans-serif">Project annual EF time series with literature points</text>',
    ]
    if not data.empty:
        years = sorted(data["year"].dropna().unique())
        max_value = float(
            max(data["ef_kg_per_mwh"].max(), literature["reference_ef_kg_per_mwh"].max()) * 1.1
        )
        x0, y0, x1, y1 = 70, 540, 930, 80
        parts.extend(
            [
                f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#222"/>',
                f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#222"/>',
            ]
        )
        colors = {"NOx": "#1f77b4", "SOx": "#d62728", "TSP": "#2ca02c"}
        for pollutant, subset in data.groupby("pollutant"):
            yearly = subset.groupby("year", as_index=False).agg(ef=("ef_kg_per_mwh", "mean"))
            points = []
            xs = _scale(yearly["year"], min(years), max(years), x0, x1)
            ys = _scale(yearly["ef"], 0, max_value, y0, y1)
            for x, y in zip(xs, ys, strict=True):
                points.append(f"{x:.1f},{y:.1f}")
            if points:
                parts.append(
                    f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[pollutant]}" stroke-width="2"/>'
                )
        lee = literature.loc[
            literature["reference_id"].eq("lee_2025_kosae") & literature["pollutant"].isin(colors)
        ]
        for row in lee.to_dict("records"):
            x = float(
                _scale(pd.Series([row["data_year"]]), min(years), max(years), x0, x1).iloc[0]
            )
            y = float(
                _scale(pd.Series([row["reference_ef_kg_per_mwh"]]), 0, max_value, y0, y1).iloc[0]
            )
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{colors[row["pollutant"]]}"/>'
            )
        for i, pollutant in enumerate(colors):
            parts.append(
                f'<text x="820" y="{105 + i * 20}" fill="{colors[pollutant]}" font-size="13" font-family="sans-serif">{pollutant}</text>'
            )
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def write_comparison_table_images(
    readable_comparison: pd.DataFrame,
    readable_comparison_wide: pd.DataFrame,
    output_dir: Path,
) -> None:
    """Write styled SVG and PNG table images for the readable EF comparisons."""
    output_dir.mkdir(parents=True, exist_ok=True)
    tidy = _format_tidy_table(readable_comparison)
    wide = _format_wide_table(readable_comparison_wide)
    for name, table, title in [
        (
            "plant_level_external_validation_table",
            tidy,
            "Plant-level external validation: inputs and EFs",
        ),
        (
            "plant_level_external_validation_ef_table",
            wide,
            "Plant-level external validation: EF comparison by plant",
        ),
    ]:
        svg_path = output_dir / f"{name}.svg"
        png_path = output_dir / f"{name}.png"
        _write_table_svg(table, title, svg_path)
        _convert_svg_to_png(svg_path, png_path)


def write_literature_ranges_svg(literature: pd.DataFrame, output_path: Path) -> None:
    """Write contextual literature values without a validation line."""
    data = literature.loc[
        literature["normalization_basis"].eq("output_generation_kg_per_mwh")
        & literature["reference_ef_kg_per_mwh"].notna()
        & ~literature["pollutant"].isin(["PM2.5", "PM10"])
    ].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1100, max(320, 30 * len(data) + 90)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="34" font-size="20" font-family="Arial, Helvetica, sans-serif" font-weight="700">Literature context (not direct validation)</text>',
    ]
    if not data.empty:
        max_value = float(data["reference_ef_kg_per_mwh"].max() * 1.1)
        x0, x1 = 460, 1040
        for i, row in enumerate(
            data.sort_values(["fuel_type", "technology", "data_year", "pollutant"]).to_dict(
                "records"
            )
        ):
            y = 70 + i * 28
            x = float(
                _scale(pd.Series([row["reference_ef_kg_per_mwh"]]), 0, max_value, x0, x1).iloc[0]
            )
            label = f"{row['reference_id']} | {row['data_year']} | {row['fuel_type']} | {row['pollutant']}"
            parts.append(
                f'<text x="24" y="{y + 4}" font-size="11" font-family="Arial, Helvetica, sans-serif" fill="#1f2933">{escape(label[:72])}</text>'
            )
            parts.append(
                f'<line x1="{x0}" y1="{y}" x2="{x:.1f}" y2="{y}" stroke="#8aa7c7" stroke-width="5"/>'
            )
            parts.append(f'<circle cx="{x:.1f}" cy="{y}" r="4" fill="#20384f"/>')
            parts.append(
                f'<text x="{x + 8:.1f}" y="{y + 4}" font-size="11" font-family="Arial, Helvetica, sans-serif" fill="#1f2933">{row["reference_ef_kg_per_mwh"]:.3f}</text>'
            )
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def write_fuel_technology_trends_svg(
    project_fuel_technology: pd.DataFrame,
    literature: pd.DataFrame,
    output_path: Path,
) -> None:
    """Write KEPCO annual fuel-technology trends with literature points overlaid."""
    project = project_fuel_technology.loc[
        project_fuel_technology["analysis_variant"].eq("reported")
        & project_fuel_technology["pollutant"].isin(["NOx", "SOx", "TSP"])
    ].copy()
    lit = literature.loc[
        literature["normalization_basis"].eq("output_generation_kg_per_mwh")
        & literature["reference_ef_kg_per_mwh"].notna()
        & literature["pollutant"].isin(["NOx", "SOx", "TSP"])
    ].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1100, 650
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="34" font-size="20" font-family="Arial, Helvetica, sans-serif" font-weight="700">KEPCO fuel-technology EF trends with literature points</text>',
    ]
    if not project.empty:
        years = sorted(project["year"].dropna().unique())
        max_value = float(
            max(project["ef_kg_per_mwh"].max(), lit["reference_ef_kg_per_mwh"].max()) * 1.1
        )
        x0, y0, x1, y1 = 70, 570, 1030, 80
        parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#222"/>')
        parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#222"/>')
        colors = {"NOx": "#1f77b4", "SOx": "#d62728", "TSP": "#2ca02c"}
        for pollutant, subset in project.groupby("pollutant"):
            yearly = subset.groupby("year", as_index=False).agg(ef=("ef_kg_per_mwh", "mean"))
            xs = _scale(yearly["year"], min(years), max(years), x0, x1)
            ys = _scale(yearly["ef"], 0, max_value, y0, y1)
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
            if points:
                parts.append(
                    f'<polyline points="{points}" fill="none" stroke="{colors[pollutant]}" stroke-width="2"/>'
                )
        for row in lit.to_dict("records"):
            if pd.isna(row.get("data_year")) or row["data_year"] == "":
                continue
            x = float(
                _scale(pd.Series([float(row["data_year"])]), min(years), max(years), x0, x1).iloc[
                    0
                ]
            )
            y = float(
                _scale(pd.Series([row["reference_ef_kg_per_mwh"]]), 0, max_value, y0, y1).iloc[0]
            )
            color = colors.get(row["pollutant"], "#444")
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" opacity="0.7"><title>{escape(str(row["reference_id"]))}</title></circle>'
            )
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def write_source_coverage_matrix_svg(coverage: pd.DataFrame, output_path: Path) -> None:
    """Write a compact source coverage matrix SVG."""
    data = coverage.copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = data.head(80).to_dict("records")
    cell = 18
    left = 360
    top = 70
    classes = list(dict.fromkeys(data["comparison_class"].astype(str)))
    combo_series = (
        data["data_year"].fillna("unknown_year").astype(str)
        + " | "
        + data["fuel_type"].fillna("unknown_fuel").astype(str)
        + " | "
        + data["technology"].fillna("unknown_technology").astype(str)
        + " | "
        + data["pollutant"].fillna("unknown_pollutant").astype(str)
    )
    combos = [str(combo) for combo in dict.fromkeys(combo_series)][:80]
    width = left + cell * len(classes) + 80
    height = top + cell * len(combos) + 80
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="34" font-size="20" font-family="Arial, Helvetica, sans-serif" font-weight="700">Literature source coverage matrix</text>',
    ]
    for j, comparison_class in enumerate(classes):
        x = left + j * cell + 12
        parts.append(
            f'<text x="{x}" y="62" font-size="9" font-family="Arial, Helvetica, sans-serif" transform="rotate(-45 {x},62)">{escape(comparison_class)}</text>'
        )
    present = {
        (
            f"{row['data_year']} | {row['fuel_type']} | {row['technology']} | {row['pollutant']}",
            str(row["comparison_class"]),
        )
        for row in rows
    }
    for i, combo in enumerate(combos):
        y = top + i * cell
        parts.append(
            f'<text x="24" y="{y + 13}" font-size="10" font-family="Arial, Helvetica, sans-serif">{escape(str(combo)[:55])}</text>'
        )
        for j, comparison_class in enumerate(classes):
            x = left + j * cell
            fill = "#20384f" if (combo, comparison_class) in present else "#eef2f6"
            parts.append(
                f'<rect x="{x}" y="{y}" width="14" height="14" fill="{fill}" stroke="#d9e1ea"/>'
            )
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def _format_tidy_table(data: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "plant",
        "pollutant",
        "external_generation_mwh",
        "kepco_generation_mwh",
        "external_pollutant_mass_kg",
        "kepco_pollutant_mass_kg",
        "external_ef_kg_per_mwh",
        "kepco_ef_kg_per_mwh",
        "percent_difference",
        "coverage_fraction",
    ]
    if data.empty:
        return pd.DataFrame(columns=["Plant", "Pollutant", "External EF", "KEPCO EF"])
    table = data[columns].copy()
    for column in [
        "external_generation_mwh",
        "kepco_generation_mwh",
        "external_pollutant_mass_kg",
        "kepco_pollutant_mass_kg",
    ]:
        table[column] = table[column].map(lambda value: f"{value:,.0f}")
    for column in ["external_ef_kg_per_mwh", "kepco_ef_kg_per_mwh"]:
        table[column] = table[column].map(lambda value: f"{value:.6f}")
    table["percent_difference"] = table["percent_difference"].map(
        lambda value: f"{value:.2f}%" if pd.notna(value) else "flagged"
    )
    table["coverage_fraction"] = table["coverage_fraction"].map(lambda value: f"{value:.0%}")
    return table.rename(
        columns={
            "plant": "Plant",
            "pollutant": "Pollutant",
            "external_generation_mwh": "External gen.",
            "kepco_generation_mwh": "KEPCO gen.",
            "external_pollutant_mass_kg": "External mass",
            "kepco_pollutant_mass_kg": "KEPCO mass",
            "external_ef_kg_per_mwh": "External EF",
            "kepco_ef_kg_per_mwh": "KEPCO EF",
            "percent_difference": "EF difference",
            "coverage_fraction": "Coverage",
        }
    )


def _format_wide_table(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    table = data.copy()
    table = table.drop(columns=["reference_id", "year"], errors="ignore")
    table = table.rename(columns={"plant": "Plant"})
    for column in table.columns:
        if column == "Plant":
            continue
        if column.endswith("percent_difference"):
            table[column] = pd.to_numeric(table[column], errors="coerce").map(
                lambda value: f"{value:.2f}%" if pd.notna(value) else ""
            )
        else:
            table[column] = pd.to_numeric(table[column], errors="coerce").map(
                lambda value: f"{value:.6f}" if pd.notna(value) else ""
            )
    return table


def _write_table_svg(data: pd.DataFrame, title: str, output_path: Path) -> None:
    columns = list(data.columns)
    rows = data.fillna("").astype(str).to_dict("records")
    char_width = 7
    padding_x = 12
    title_height = 58
    header_height = 42
    row_height = 30
    min_widths = {"Plant": 130, "Pollutant": 88}
    widths = []
    for column in columns:
        max_len = max([len(str(column)), *[len(str(row[column])) for row in rows]], default=0)
        widths.append(max(min_widths.get(column, 86), max_len * char_width + 2 * padding_x))
    table_width = sum(widths) + 2
    title_width = len(title) * 12 + 28
    subtitle_width = 650
    width = max(table_width, title_width, subtitle_width)
    height = title_height + header_height + row_height * max(len(rows), 1) + 2
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="14" y="28" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#17202a">{escape(title)}</text>',
        '<text x="14" y="48" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="#5f6b7a">Generation and pollutant mass are reconciled before EF; EF units are kg/MWh.</text>',
    ]
    x = 1
    y = title_height
    for column, column_width in zip(columns, widths, strict=True):
        parts.append(
            f'<rect x="{x}" y="{y}" width="{column_width}" height="{header_height}" fill="#20384f"/>'
        )
        parts.append(
            f'<text x="{x + padding_x}" y="{y + 26}" font-family="Arial, Helvetica, sans-serif" font-size="12" font-weight="700" fill="#ffffff">{escape(column)}</text>'
        )
        x += column_width
    for row_index, row in enumerate(rows):
        y = title_height + header_height + row_index * row_height
        fill = "#f7f9fc" if row_index % 2 == 0 else "#ffffff"
        x = 1
        for column, column_width in zip(columns, widths, strict=True):
            parts.append(
                f'<rect x="{x}" y="{y}" width="{column_width}" height="{row_height}" fill="{fill}" stroke="#d9e1ea" stroke-width="1"/>'
            )
            color = _table_text_color(column, row[column])
            anchor = "start" if column in {"Plant", "Pollutant"} else "end"
            text_x = x + padding_x if anchor == "start" else x + column_width - padding_x
            parts.append(
                f'<text x="{text_x}" y="{y + 20}" text-anchor="{anchor}" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="{color}">{escape(row[column])}</text>'
            )
            x += column_width
    if not rows:
        parts.append(
            f'<text x="14" y="{title_height + header_height + 22}" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#5f6b7a">No comparable rows.</text>'
        )
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def _table_text_color(column: str, value: str) -> str:
    if not column.endswith("error") and column != "Error":
        return "#1f2933"
    try:
        number = float(value.replace("%", ""))
    except ValueError:
        return "#1f2933"
    if number > 0:
        return "#9b2c2c"
    if number < 0:
        return "#1f5f99"
    return "#1f2933"


def _convert_svg_to_png(svg_path: Path, png_path: Path) -> None:
    command = shutil.which("magick") or shutil.which("convert")
    if command is None:
        return
    if Path(command).name == "magick":
        args = [command, "-background", "white", "-density", "180", str(svg_path), str(png_path)]
    else:
        args = [command, "-background", "white", "-density", "180", str(svg_path), str(png_path)]
    subprocess.run(args, check=True)
