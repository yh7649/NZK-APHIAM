"""Dependency-light SVG figures for emission-factor validation outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _scale(values: pd.Series, low: float, high: float, pixels_low: float, pixels_high: float):
    span = high - low if high != low else 1
    return pixels_low + (values - low) * (pixels_high - pixels_low) / span


def write_scatter_svg(comparisons: pd.DataFrame, output_path: Path) -> None:
    """Write project-vs-literature EF scatter with a one-to-one line."""
    data = comparisons.loc[
        comparisons["comparability_status"].eq("strict_same_year_comparable")
        & comparisons["analysis_variant"].eq("reported")
    ].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 900, 620
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="35" font-size="20" font-family="sans-serif">Project EF versus literature EF</text>',
    ]
    if data.empty:
        parts.append(
            '<text x="30" y="80" font-size="14" font-family="sans-serif">No strict comparable matches.</text>'
        )
    else:
        pollutants = ["NOx", "SOx", "TSP", "combined"]
        colors = {"NOx": "#1f77b4", "SOx": "#d62728", "TSP": "#2ca02c", "combined": "#444444"}
        max_value = float(
            data[["project_ef_kg_per_mwh", "reference_ef_kg_per_mwh"]].max().max() * 1.1
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
            xs = _scale(subset["reference_ef_kg_per_mwh"], 0, max_value, x0, x1)
            ys = _scale(subset["project_ef_kg_per_mwh"], 0, max_value, y0, y1)
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
        comparisons["comparability_status"].eq("strict_same_year_comparable")
        & comparisons["analysis_variant"].eq("reported")
    ].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1000, max(320, 34 * len(data) + 90)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="35" font-size="20" font-family="sans-serif">EF percent difference by plant and pollutant</text>',
    ]
    if not data.empty:
        bound = max(5.0, float(data["ef_percent_difference"].abs().max() * 1.1))
        x_mid = 520
        parts.append(f'<line x1="{x_mid}" y1="60" x2="{x_mid}" y2="{height - 30}" stroke="#888"/>')
        for i, row in enumerate(
            data.sort_values(["plant_name_en", "pollutant"]).to_dict("records")
        ):
            y = 80 + i * 30
            x = float(
                _scale(pd.Series([row["ef_percent_difference"]]), -bound, bound, 120, 920).iloc[0]
            )
            parts.append(
                f'<line x1="{x_mid}" y1="{y}" x2="{x:.1f}" y2="{y}" stroke="#3b6ea8" stroke-width="4"/>'
            )
            parts.append(f'<circle cx="{x:.1f}" cy="{y}" r="4" fill="#163d5c"/>')
            parts.append(
                f'<text x="30" y="{y + 4}" font-size="12" font-family="sans-serif">{row["plant_name_en"]} {row["pollutant"]}</text>'
            )
            parts.append(
                f'<text x="930" y="{y + 4}" font-size="12" font-family="sans-serif">{row["ef_percent_difference"]:.1f}%</text>'
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
