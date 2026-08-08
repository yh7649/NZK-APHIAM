"""Deterministic quality-control rules for hourly pollutant observations."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DEFAULT_BOUNDS: dict[str, tuple[float, float]] = {
    "SO2": (0.0, 2.0),
    "CO": (0.0, 50.0),
    "O3": (0.0, 2.0),
    "NO2": (0.0, 2.0),
    "PM10": (0.0, 2000.0),
    "PM25": (0.0, 1000.0),
}


@dataclass(frozen=True)
class RuleConfig:
    """Thresholds for transparent, non-statistical flags."""

    bounds: dict[str, tuple[float, float]] = field(default_factory=lambda: DEFAULT_BOUNDS.copy())
    missing_sentinels: tuple[float, ...] = (-999.0, -9999.0)
    flatline_hours: int = 12
    jump_multiplier: float = 10.0
    jump_minimum: dict[str, float] = field(
        default_factory=lambda: {
            "SO2": 0.1,
            "CO": 5.0,
            "O3": 0.15,
            "NO2": 0.15,
            "PM10": 300.0,
            "PM25": 200.0,
        }
    )


def _flatline_mask(values: pd.Series, minimum_run: int) -> pd.Series:
    valid = values.notna()
    runs = values.ne(values.shift()) | ~valid
    run_id = runs.cumsum()
    sizes = values.groupby(run_id, sort=False).transform("size")
    return valid & sizes.ge(minimum_run)


def apply_rule_flags(data: pd.DataFrame, config: RuleConfig | None = None) -> pd.DataFrame:
    """Return a copy with individual rule flags and a pipe-delimited summary.

    Required columns are ``monitor_id``, ``datetime``, ``pollutant`` and
    ``value_raw``. Rows are never removed and ``value_raw`` is never modified.
    """
    config = config or RuleConfig()
    required = {"monitor_id", "datetime", "pollutant", "value_raw"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"Rule QC is missing required columns: {sorted(missing)}")

    result = data.copy()
    result["value_raw"] = pd.to_numeric(result["value_raw"], errors="coerce")
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    sentinel = result["value_raw"].isin(config.missing_sentinels)
    result["flag_missing"] = sentinel | result["value_raw"].isna() | result["datetime"].isna()

    lower = result["pollutant"].map({k: v[0] for k, v in config.bounds.items()})
    upper = result["pollutant"].map({k: v[1] for k, v in config.bounds.items()})
    result["flag_impossible"] = (
        result["value_raw"].lt(lower) | result["value_raw"].gt(upper)
    ).fillna(False)

    result = result.sort_values(["pollutant", "monitor_id", "datetime"], kind="stable")
    groups = result.groupby(["pollutant", "monitor_id"], sort=False, observed=True)
    result["flag_flatline"] = (
        groups["value_raw"]
        .transform(lambda values: _flatline_mask(values, config.flatline_hours))
        .fillna(False)
    )
    difference = groups["value_raw"].diff().abs()
    typical = groups["value_raw"].transform(
        lambda values: values.diff().abs().rolling(24 * 30, min_periods=24).median()
    )
    minimum = result["pollutant"].map(config.jump_minimum).fillna(np.inf)
    result["flag_jump"] = (
        difference.gt(minimum) & difference.gt(typical * config.jump_multiplier)
    ).fillna(False)

    names = {
        "flag_missing": "missing",
        "flag_impossible": "impossible",
        "flag_flatline": "flatline",
        "flag_jump": "jump",
    }
    summary = pd.Series("", index=result.index, dtype="string")
    for column, label in names.items():
        addition = pd.Series("", index=result.index, dtype="string")
        addition.loc[result[column].fillna(False).astype(bool)] = label
        summary = summary.str.cat(addition, sep="|").str.strip("|")
    result["flag_rule"] = summary
    return result.sort_index()
