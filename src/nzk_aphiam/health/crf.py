"""Concentration-response functions (CRFs) for PM2.5 all-cause mortality.

A CRF converts a PM2.5 concentration into an attributable fraction (AF) via
``AF = 1 - exp(-beta * max(0, pm25_ugm3 - counterfactual_ugm3))``. The primary
CRF implemented here is the log-linear form from Krewski et al. 2009 (HEI
Research Report 140), as used by Huang & Peng (2025) Equation 2. Parameters
are read from ``docs/references/health/crf_parameters.csv`` rather than
hardcoded; every numeric value in that file traces to a row in
``crf_parameters_official_evidence.csv``.

GEMM (Burnett et al. 2018) is a deferred sensitivity CRF -- see
docs/methods/health_impact_assessment.md. It is intentionally not
implemented or stubbed here. ``ConcentrationResponseFunction`` documents the
interface any future CRF (GEMM included) must satisfy so that ``impact.py``
and ``decomposition.py`` never need to change to add one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

DEFAULT_CRF_PARAMETERS_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "references" / "health" / "crf_parameters.csv"
)
DEFAULT_CRF_ID = "krewski_2009_acs_extended"

REQUIRED_COLUMNS = (
    "crf_id",
    "label",
    "beta_per_ugm3",
    "beta_ci_low_per_ugm3",
    "beta_ci_high_per_ugm3",
    "valid_age_min",
    "lowest_measured_ugm3",
    "counterfactual_ugm3",
)


@runtime_checkable
class ConcentrationResponseFunction(Protocol):
    """Interface every CRF (log-linear today; GEMM as a future sensitivity CRF) must satisfy."""

    crf_id: str
    beta: float
    ci_low: float
    ci_high: float
    valid_age_min: int
    counterfactual_ugm3: float

    def delta_pm(self, pm25_ugm3: float | pd.Series) -> float | pd.Series:
        """Concentration above the counterfactual, truncated at zero."""
        ...

    def is_truncated(self, pm25_ugm3: float | pd.Series) -> bool | pd.Series:
        """Whether pm25_ugm3 fell below counterfactual_ugm3 (would go negative untruncated)."""
        ...

    def apply(self, pm25_ugm3: float | pd.Series, beta: float | None = None) -> float | pd.Series:
        """Attributable fraction AF = 1 - exp(-beta * delta_pm(pm25_ugm3))."""
        ...


@dataclass(frozen=True)
class LogLinearCRF:
    """Log-linear CRF: AF = 1 - exp(-beta * max(0, pm25_ugm3 - counterfactual_ugm3)).

    ``counterfactual_ugm3`` has no default -- every instantiation must supply a
    sourced value (see crf_parameters.csv / crf_parameters_official_evidence.csv).
    """

    crf_id: str
    label: str
    beta: float
    ci_low: float
    ci_high: float
    valid_age_min: int
    counterfactual_ugm3: float
    lowest_measured_ugm3: float

    def delta_pm(self, pm25_ugm3: float | pd.Series) -> float | pd.Series:
        return np.maximum(0.0, pm25_ugm3 - self.counterfactual_ugm3)

    def is_truncated(self, pm25_ugm3: float | pd.Series) -> bool | pd.Series:
        return pm25_ugm3 < self.counterfactual_ugm3

    def apply(self, pm25_ugm3: float | pd.Series, beta: float | None = None) -> float | pd.Series:
        beta_value = self.beta if beta is None else beta
        return 1.0 - np.exp(-beta_value * self.delta_pm(pm25_ugm3))


def load_crf(
    crf_id: str = DEFAULT_CRF_ID, path: Path = DEFAULT_CRF_PARAMETERS_PATH
) -> LogLinearCRF:
    """Load one CRF definition from ``crf_parameters.csv`` by ``crf_id``."""
    table = pd.read_csv(path)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in table.columns]
    if missing_columns:
        raise ValueError(f"{path} is missing required columns: {missing_columns}")

    matches = table.loc[table["crf_id"] == crf_id]
    if matches.empty:
        available = sorted(table["crf_id"].unique())
        raise KeyError(f"No CRF with crf_id={crf_id!r} in {path}. Available: {available}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate crf_id={crf_id!r} rows in {path}")

    record = matches.iloc[0]
    return LogLinearCRF(
        crf_id=str(record["crf_id"]),
        label=str(record["label"]),
        beta=float(record["beta_per_ugm3"]),
        ci_low=float(record["beta_ci_low_per_ugm3"]),
        ci_high=float(record["beta_ci_high_per_ugm3"]),
        valid_age_min=int(record["valid_age_min"]),
        counterfactual_ugm3=float(record["counterfactual_ugm3"]),
        lowest_measured_ugm3=float(record["lowest_measured_ugm3"]),
    )
