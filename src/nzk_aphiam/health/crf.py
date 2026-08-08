"""Concentration-response functions (CRFs) for long-term PM2.5 mortality.

The registry in ``docs/references/health/crf_parameters.csv`` contains the
log-linear Peng/Krewski primary specification and the prespecified Korean
sensitivities. The nonlinear, age-specific GEMM NCD+LRI parameters are stored
separately in ``gemm_ncd_lri_parameters.csv`` because one parameter row is
required for every five-year age band.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from nzk_aphiam.config.paths import PROJECT_ROOT

_REFERENCE_DIR = PROJECT_ROOT / "docs" / "references" / "health"
DEFAULT_CRF_PARAMETERS_PATH = _REFERENCE_DIR / "crf_parameters.csv"
DEFAULT_GEMM_PARAMETERS_PATH = _REFERENCE_DIR / "gemm_ncd_lri_parameters.csv"
DEFAULT_CRF_ID = "peng_krewski_2009_all_cause"

REQUIRED_BASE_COLUMNS = (
    "crf_id",
    "label",
    "valid_age_min",
    "counterfactual_ugm3",
)
REQUIRED_LOG_LINEAR_COLUMNS = (
    "beta_per_ugm3",
    "beta_ci_low_per_ugm3",
    "beta_ci_high_per_ugm3",
)
REQUIRED_GEMM_COLUMNS = (
    "parameter_set",
    "age_band",
    "theta",
    "theta_se",
    "alpha",
    "mu",
    "nu",
    "counterfactual_ugm3",
)
ESTIMATES = ("central", "lower", "upper")


@runtime_checkable
class ConcentrationResponseFunction(Protocol):
    """Interface shared by log-linear and nonlinear concentration-response functions."""

    crf_id: str
    label: str
    model_type: str
    endpoint: str
    specification_role: str
    valid_age_min: int
    valid_age_max: int | None
    counterfactual_ugm3: float

    def delta_pm(self, pm25_ugm3: float | pd.Series) -> float | pd.Series:
        """Concentration above the counterfactual, truncated at zero."""
        ...

    def is_truncated(self, pm25_ugm3: float | pd.Series) -> bool | pd.Series:
        """Whether concentration is below the CRF counterfactual."""
        ...

    def apply(
        self,
        pm25_ugm3: float | pd.Series,
        *,
        age_band: object | pd.Series | None = None,
        estimate: str = "central",
    ) -> float | pd.Series:
        """Return the population-attributable fraction."""
        ...


def _validate_estimate(estimate: str) -> None:
    if estimate not in ESTIMATES:
        raise ValueError(f"estimate must be one of {ESTIMATES}; got {estimate!r}.")


def _optional_text(record: pd.Series, column: str, default: str) -> str:
    value = record.get(column, default)
    return default if pd.isna(value) or str(value).strip() == "" else str(value)


def _optional_int(record: pd.Series, column: str) -> int | None:
    value = record.get(column)
    return None if value is None or pd.isna(value) else int(value)


@dataclass(frozen=True)
class LogLinearCRF:
    """Log-linear CRF with an explicit counterfactual concentration."""

    crf_id: str
    label: str
    beta: float
    ci_low: float
    ci_high: float
    valid_age_min: int
    counterfactual_ugm3: float
    lowest_measured_ugm3: float
    endpoint: str = "all_cause"
    valid_age_max: int | None = None
    specification_role: str = "unspecified"
    model_type: str = "log_linear"

    def delta_pm(self, pm25_ugm3: float | pd.Series) -> float | pd.Series:
        return np.maximum(0.0, pm25_ugm3 - self.counterfactual_ugm3)

    def is_truncated(self, pm25_ugm3: float | pd.Series) -> bool | pd.Series:
        return pm25_ugm3 < self.counterfactual_ugm3

    def apply(
        self,
        pm25_ugm3: float | pd.Series,
        beta: float | None = None,
        *,
        age_band: object | pd.Series | None = None,
        estimate: str = "central",
    ) -> float | pd.Series:
        """Return ``1-exp(-beta*delta_pm)``.

        ``beta`` remains as a backward-compatible explicit override. New code
        should select ``estimate`` so the same interface works for GEMM.
        """
        del age_band
        _validate_estimate(estimate)
        if beta is not None and estimate != "central":
            raise ValueError("Use either beta= or estimate=, not both.")
        coefficient = {
            "central": self.beta,
            "lower": self.ci_low,
            "upper": self.ci_high,
        }[estimate]
        if beta is not None:
            coefficient = beta
        return 1.0 - np.exp(-coefficient * self.delta_pm(pm25_ugm3))


def _gemm_parameter_age_band(value: object) -> str:
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)(?:-(\d+)|\+)", text)
    if not match:
        raise ValueError(
            f"GEMM requires five-year age bands from 25-29 through 75-79 and 80+; got {value!r}."
        )
    lower = int(match.group(1))
    upper = match.group(2)
    if lower >= 80 and upper is None:
        return "80+"
    if lower < 25 or lower > 75 or lower % 5 != 0 or int(upper or -1) != lower + 4:
        raise ValueError(
            f"GEMM requires five-year age bands from 25-29 through 75-79 and 80+; got {value!r}."
        )
    return f"{lower}-{lower + 4}"


@dataclass(frozen=True)
class GEMMNCDLRICRF:
    """Burnett et al. (2018) age-specific GEMM for NCD+LRI mortality.

    ``RR(z)=exp(theta*T(z))`` and the attributable fraction is ``1-1/RR``.
    The lower and upper estimates use ``theta +/- 1.96*SE(theta)`` as specified
    by the paper's algebraic approximation to the ensemble uncertainty.
    """

    crf_id: str
    label: str
    parameters: pd.DataFrame
    valid_age_min: int = 25
    counterfactual_ugm3: float = 2.4
    endpoint: str = "ncd_lri"
    valid_age_max: int | None = None
    specification_role: str = "peng_sensitivity"
    model_type: str = "gemm_ncd_lri"

    def delta_pm(self, pm25_ugm3: float | pd.Series) -> float | pd.Series:
        return np.maximum(0.0, pm25_ugm3 - self.counterfactual_ugm3)

    def is_truncated(self, pm25_ugm3: float | pd.Series) -> bool | pd.Series:
        return pm25_ugm3 < self.counterfactual_ugm3

    def apply(
        self,
        pm25_ugm3: float | pd.Series,
        *,
        age_band: object | pd.Series | None = None,
        estimate: str = "central",
    ) -> float | pd.Series:
        _validate_estimate(estimate)
        if age_band is None:
            raise ValueError("GEMM requires age_band for every concentration.")

        scalar_input = not isinstance(pm25_ugm3, pd.Series)
        concentrations = (
            pd.Series([float(pm25_ugm3)])
            if scalar_input
            else pd.to_numeric(pm25_ugm3, errors="raise").astype(float)
        )
        if isinstance(age_band, pd.Series):
            ages = age_band.reindex(concentrations.index)
        else:
            ages = pd.Series([age_band] * len(concentrations), index=concentrations.index)
        keys = ages.map(_gemm_parameter_age_band)
        indexed = self.parameters.set_index("age_band")
        missing = sorted(set(keys) - set(indexed.index))
        if missing:
            raise ValueError(f"GEMM parameter rows are missing age bands: {missing}")
        matched = indexed.loc[keys].reset_index(drop=True)

        theta = matched["theta"].to_numpy(dtype=float)
        if estimate == "lower":
            theta = theta - 1.96 * matched["theta_se"].to_numpy(dtype=float)
        elif estimate == "upper":
            theta = theta + 1.96 * matched["theta_se"].to_numpy(dtype=float)
        if (theta < 0).any():
            raise ValueError("GEMM theta uncertainty bound became negative.")

        z = np.maximum(0.0, concentrations.to_numpy() - self.counterfactual_ugm3)
        transform = np.log1p(z / matched["alpha"].to_numpy(dtype=float)) / (
            1.0
            + np.exp(
                -(z - matched["mu"].to_numpy(dtype=float)) / matched["nu"].to_numpy(dtype=float)
            )
        )
        attributable_fraction = 1.0 - np.exp(-theta * transform)
        if scalar_input:
            return float(attributable_fraction[0])
        return pd.Series(attributable_fraction, index=concentrations.index)


def _load_gemm_parameters(parameter_set: str, path: Path) -> pd.DataFrame:
    table = pd.read_csv(path)
    missing_columns = [column for column in REQUIRED_GEMM_COLUMNS if column not in table.columns]
    if missing_columns:
        raise ValueError(f"{path} is missing required GEMM columns: {missing_columns}")
    parameters = table.loc[table["parameter_set"].eq(parameter_set)].copy()
    if parameters.empty:
        available = sorted(table["parameter_set"].dropna().unique())
        raise KeyError(
            f"No GEMM parameter_set={parameter_set!r} in {path}. Available: {available}"
        )
    if parameters["age_band"].duplicated().any():
        duplicates = sorted(parameters.loc[parameters["age_band"].duplicated(), "age_band"])
        raise ValueError(f"Duplicate GEMM age bands for {parameter_set!r}: {duplicates}")
    counterfactuals = parameters["counterfactual_ugm3"].dropna().unique()
    if len(counterfactuals) != 1:
        raise ValueError(f"GEMM parameter set {parameter_set!r} has inconsistent counterfactuals.")
    return parameters.reset_index(drop=True)


def load_crf(
    crf_id: str = DEFAULT_CRF_ID,
    path: Path = DEFAULT_CRF_PARAMETERS_PATH,
    gemm_parameters_path: Path = DEFAULT_GEMM_PARAMETERS_PATH,
) -> ConcentrationResponseFunction:
    """Load one CRF definition from the specification registry."""
    table = pd.read_csv(path)
    missing_columns = [column for column in REQUIRED_BASE_COLUMNS if column not in table.columns]
    if missing_columns:
        raise ValueError(f"{path} is missing required columns: {missing_columns}")

    matches = table.loc[table["crf_id"] == crf_id]
    if matches.empty:
        available = sorted(table["crf_id"].unique())
        raise KeyError(f"No CRF with crf_id={crf_id!r} in {path}. Available: {available}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate crf_id={crf_id!r} rows in {path}")

    record = matches.iloc[0]
    model_type = _optional_text(record, "model_type", "log_linear")
    endpoint = _optional_text(record, "endpoint", _optional_text(record, "cause", "all_cause"))
    role = _optional_text(record, "specification_role", "unspecified")
    valid_age_max = _optional_int(record, "valid_age_max")
    counterfactual = float(record["counterfactual_ugm3"])

    if model_type == "gemm_ncd_lri":
        parameter_set = _optional_text(record, "parameter_set", "gemm_ncd_lri_with_chinese_cohort")
        parameters = _load_gemm_parameters(parameter_set, gemm_parameters_path)
        parameter_counterfactual = float(parameters["counterfactual_ugm3"].iloc[0])
        if not np.isclose(counterfactual, parameter_counterfactual):
            raise ValueError(
                f"{crf_id!r} counterfactual {counterfactual} does not match "
                f"{parameter_set!r} counterfactual {parameter_counterfactual}."
            )
        return GEMMNCDLRICRF(
            crf_id=str(record["crf_id"]),
            label=str(record["label"]),
            parameters=parameters,
            valid_age_min=int(record["valid_age_min"]),
            counterfactual_ugm3=counterfactual,
            endpoint=endpoint,
            valid_age_max=valid_age_max,
            specification_role=role,
        )

    if model_type != "log_linear":
        raise ValueError(f"Unsupported model_type={model_type!r} for crf_id={crf_id!r}.")
    missing_log_columns = [
        column for column in REQUIRED_LOG_LINEAR_COLUMNS if column not in table.columns
    ]
    if missing_log_columns:
        raise ValueError(f"{path} is missing required log-linear columns: {missing_log_columns}")
    for column in REQUIRED_LOG_LINEAR_COLUMNS:
        if pd.isna(record[column]):
            raise ValueError(f"{crf_id!r} has no value for required column {column!r}.")

    lowest_measured = record.get("lowest_measured_ugm3", counterfactual)
    if pd.isna(lowest_measured):
        lowest_measured = counterfactual
    return LogLinearCRF(
        crf_id=str(record["crf_id"]),
        label=str(record["label"]),
        beta=float(record["beta_per_ugm3"]),
        ci_low=float(record["beta_ci_low_per_ugm3"]),
        ci_high=float(record["beta_ci_high_per_ugm3"]),
        valid_age_min=int(record["valid_age_min"]),
        counterfactual_ugm3=counterfactual,
        lowest_measured_ugm3=float(lowest_measured),
        endpoint=endpoint,
        valid_age_max=valid_age_max,
        specification_role=role,
    )
