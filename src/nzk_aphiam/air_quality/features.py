"""Feature engineering that only uses information available at each hour."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_temporal_and_lag_features(
    data: pd.DataFrame, lags: tuple[int, ...] = (1, 2, 24, 48, 168)
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Create calendar cycles and within-monitor pollutant lags."""
    result = data.sort_values(["pollutant", "monitor_id", "datetime"], kind="stable").copy()
    dt = result["datetime"]
    result["hour_sin"] = np.sin(2 * np.pi * dt.dt.hour / 24)
    result["hour_cos"] = np.cos(2 * np.pi * dt.dt.hour / 24)
    result["weekday_sin"] = np.sin(2 * np.pi * dt.dt.dayofweek / 7)
    result["weekday_cos"] = np.cos(2 * np.pi * dt.dt.dayofweek / 7)
    result["month_sin"] = np.sin(2 * np.pi * (dt.dt.month - 1) / 12)
    result["month_cos"] = np.cos(2 * np.pi * (dt.dt.month - 1) / 12)
    numeric = ["hour_sin", "hour_cos", "weekday_sin", "weekday_cos", "month_sin", "month_cos"]
    clean_values = result["value_raw"].mask(result["flag_missing"] | result["flag_impossible"])
    groups = clean_values.groupby(
        [result["pollutant"], result["monitor_id"]], sort=False, observed=True
    )
    for lag in lags:
        column = f"lag_{lag}h"
        result[column] = groups.shift(lag)
        numeric.append(column)

    for optional in ("latitude", "longitude", "temperature", "humidity", "wind_speed", "pressure"):
        if optional in result.columns:
            numeric.append(optional)
    return result.sort_index(), numeric, ["monitor_id"]
