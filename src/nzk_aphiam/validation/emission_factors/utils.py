"""Small IO and numeric helpers for emission-factor validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


def file_sha256(path: Path) -> str:
    """Return a deterministic SHA-256 checksum for a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_divide(numerator: float | pd.Series, denominator: float | pd.Series):
    """Divide while returning missing when the denominator is zero or missing."""
    denominator_series = (
        pd.Series(denominator) if not isinstance(denominator, pd.Series) else denominator
    )
    result = numerator / denominator_series.where(denominator_series.gt(0))
    return result


def percent_difference(project: pd.Series, reference: pd.Series) -> pd.Series:
    """Percent difference relative to reference, preserving missing zero denominators."""
    return 100 * (project - reference) / reference.where(reference.ne(0))


def symmetric_percent_difference(project: pd.Series, reference: pd.Series) -> pd.Series:
    """Symmetric percent difference using the mean absolute value as denominator."""
    denominator = (project.abs() + reference.abs()) / 2
    return 100 * (project - reference) / denominator.where(denominator.ne(0))
