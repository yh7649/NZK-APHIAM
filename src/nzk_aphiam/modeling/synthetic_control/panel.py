"""Donor screening and weekly panel construction."""

from __future__ import annotations

import pandas as pd

from .config import EventConfig


def _require(data: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(data))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def select_donors(hourly: pd.DataFrame, config: EventConfig) -> pd.DataFrame:
    """Create a monitor-level decision table; never silently pass all controls through."""
    _require(
        hourly,
        {"datetime", "monitor_id", "pollutant", "plant_monitor_distance_km", "target_exposure"},
        "Donor input",
    )
    data = hourly.copy()
    data["datetime"] = pd.to_datetime(data["datetime"])
    data["monitor_id"] = data["monitor_id"].astype(str)
    data = data.loc[data["pollutant"].str.upper().isin(config.pollutants)]
    pre = data.loc[data["datetime"].dt.date.between(config.pre_start, config.pre_end)]
    rows: list[dict[str, object]] = []
    treated_types = set()
    if "monitor_type" in pre:
        treated_types = set(
            pre.loc[pre["monitor_id"].isin(config.treated_monitor_ids), "monitor_type"].dropna()
        )
    expected_hours = max(1, int((config.pre_end - config.pre_start).days + 1) * 24)
    for monitor_id, group in pre.groupby("monitor_id", observed=True):
        reasons = []
        distance = float(group["plant_monitor_distance_km"].median())
        exposure = float(group["target_exposure"].mean())
        observed_fraction = group["datetime"].nunique() / expected_hours
        pre_weeks = group["datetime"].dt.to_period("W-SUN").nunique()
        is_treated = monitor_id in config.treated_monitor_ids
        if is_treated and distance > config.maximum_treated_distance_km:
            reasons.append("treated_monitor_too_far")
        if not is_treated and distance < config.minimum_donor_distance_km:
            reasons.append("too_close_to_target")
        if not is_treated and exposure > config.maximum_donor_exposure:
            reasons.append("target_exposure")
        if observed_fraction < 1 - config.maximum_missing_pre_fraction:
            reasons.append("insufficient_pre_coverage")
        if pre_weeks < config.minimum_pre_weeks:
            reasons.append("insufficient_pre_weeks")
        if (
            not is_treated
            and config.same_monitor_type
            and treated_types
            and "monitor_type" in group
        ):
            if not set(group["monitor_type"].dropna()).intersection(treated_types):
                reasons.append("monitor_type_mismatch")
        rows.append(
            {
                "event_id": config.event_id,
                "monitor_id": monitor_id,
                "role": "treated" if is_treated else "donor",
                "eligible": not reasons,
                "exclusion_reason": ";".join(reasons),
                "distance_km": distance,
                "target_exposure_pre": exposure,
                "pre_observed_fraction": observed_fraction,
                "pre_weeks": pre_weeks,
            }
        )
    return pd.DataFrame(rows).sort_values(["role", "monitor_id"], kind="stable")


def build_weekly_panel(
    hourly: pd.DataFrame, decisions: pd.DataFrame, config: EventConfig
) -> pd.DataFrame:
    """Aggregate eligible normalized observations to complete-enough Monday weeks."""
    _require(
        hourly,
        {"datetime", "monitor_id", "pollutant", "concentration", "normalized_concentration"},
        "Weekly input",
    )
    eligible = set(decisions.loc[decisions["eligible"], "monitor_id"].astype(str))
    data = hourly.copy()
    data["datetime"] = pd.to_datetime(data["datetime"])
    data["monitor_id"] = data["monitor_id"].astype(str)
    start, end = (
        pd.Timestamp(config.pre_start),
        pd.Timestamp(config.post_end) + pd.Timedelta(days=1),
    )
    data = data.loc[
        data["monitor_id"].isin(eligible)
        & data["pollutant"].str.upper().isin(config.pollutants)
        & data["datetime"].ge(start)
        & data["datetime"].lt(end)
    ].copy()
    data["week"] = data["datetime"].dt.to_period("W-SUN").dt.start_time
    weekly = (
        data.groupby(["monitor_id", "pollutant", "week"], observed=True)
        .agg(
            normalized_concentration=("normalized_concentration", "mean"),
            observed_concentration=("concentration", "mean"),
            hours_available=("concentration", "count"),
        )
        .reset_index()
    )
    weekly = weekly.loc[weekly["hours_available"] >= config.minimum_weekly_hours].copy()
    intervention = pd.Timestamp(config.intervention_week)
    weekly["event_id"] = config.event_id
    weekly["treated"] = weekly["monitor_id"].isin(config.treated_monitor_ids).astype(int)
    weekly["post"] = weekly["week"].ge(intervention).astype(int)
    all_weeks = sorted(weekly["week"].unique())
    index = {week: position + 1 for position, week in enumerate(all_weeks)}
    weekly["week_index"] = weekly["week"].map(index).astype(int)
    return weekly.sort_values(["pollutant", "monitor_id", "week"], kind="stable")
