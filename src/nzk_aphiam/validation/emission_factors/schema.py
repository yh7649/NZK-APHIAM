"""Shared constants for KEPCO emission-factor validation."""

from __future__ import annotations

from pathlib import Path

from nzk_aphiam.config.paths import DATA_DIR, PROJECT_ROOT

INPUT_PATH = DATA_DIR / "processed" / "kepco" / "kepco_monthly_generation_emissions.csv"
REFERENCE_DIR = PROJECT_ROOT / "docs" / "references" / "emission_factor_validation"
TABLE_OUTPUT_DIR = PROJECT_ROOT / "results" / "tables" / "kepco" / "emission_factor_validation"
FIGURE_OUTPUT_DIR = PROJECT_ROOT / "results" / "figures" / "kepco" / "emission_factor_validation"

POLLUTANT_COLUMNS = {"NOx": "nox", "SOx": "sox", "TSP": "dust_tsp"}
COMBINED_POLLUTANT = "combined"
COMBINED_SCOPE = "NOx+SOx+TSP"
SEVERE_AUDIT_SEVERITIES = {"critical"}

REFERENCE_FILES = {
    "benchmarks": "literature_benchmarks.csv",
    "crosswalk": "literature_plant_crosswalk.csv",
    "comparison_rules": "literature_comparison_rules.csv",
    "catalog": "literature_catalog.csv",
    "pdf_inventory": "literature_pdf_inventory.csv",
}

COMPARISON_CLASSES = {
    "A_exact_reproduction",
    "B_plant_pipeline_validation",
    "C_aggregate_consistency_check",
    "D_contextual_benchmark",
    "X_not_comparable",
}
DIRECT_VALIDATION_CLASSES = {"A_exact_reproduction", "B_plant_pipeline_validation"}
SMALL_EXTERNAL_EF_THRESHOLD = 1e-6

ANALYSIS_VARIANTS = {
    "reported": "All physically valid matched observations, retaining audit flags.",
    "audit_clean": "Reported variant excluding rows with severe audit errors.",
}


def reference_path(name: str, reference_dir: Path = REFERENCE_DIR) -> Path:
    """Return one tracked validation reference path."""
    return reference_dir / REFERENCE_FILES[name]
