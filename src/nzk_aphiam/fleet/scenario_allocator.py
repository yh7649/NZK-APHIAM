"""Allocate province/fuel/technology scenario generation to physical thermal sites."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

import numpy as np
import pandas as pd

GROUP_COLUMNS = ["scenario", "year", "province", "fuel", "technology"]
FLEET_REQUIRED_COLUMNS = {
    "plant_id",
    "plant_name",
    "unit_id",
    "province",
    "fuel",
    "technology",
    "capacity_mw",
    "commissioning_year",
    "retirement_year",
}


def _validate_inputs(generation: pd.DataFrame, fleet: pd.DataFrame) -> None:
    missing_generation = [
        column for column in [*GROUP_COLUMNS, "generation_mwh"] if column not in generation
    ]
    if missing_generation:
        raise ValueError(f"Generation input is missing columns: {missing_generation}")
    missing_fleet = sorted(FLEET_REQUIRED_COLUMNS - set(fleet.columns))
    if missing_fleet:
        raise ValueError(f"Fleet input is missing columns: {missing_fleet}")
    if generation["generation_mwh"].isna().any() or (generation["generation_mwh"] < 0).any():
        raise ValueError("generation_mwh must be non-missing and non-negative.")


def eligible_fleet(fleet: pd.DataFrame, year: int) -> pd.DataFrame:
    """Return units commissioned by and not retired before ``year``."""
    commissioned = fleet["commissioning_year"].isna() | (fleet["commissioning_year"] <= year)
    active = fleet["retirement_year"].isna() | (fleet["retirement_year"] >= year)
    return fleet.loc[commissioned & active].copy()


def _compatible_fuels(
    requested_fuel: str, fuel_compatibility: Mapping[str, Sequence[str]]
) -> set[str]:
    return set(fuel_compatibility.get(requested_fuel, [requested_fuel]))


def _select_candidates(
    fleet: pd.DataFrame,
    *,
    year: int,
    province: str,
    fuel: str,
    technology: str,
    fuel_compatibility: Mapping[str, Sequence[str]],
) -> tuple[pd.DataFrame, str, bool, bool]:
    active = eligible_fleet(fleet, year)
    within_province = (
        active if province == "national" else active.loc[active["province"] == province]
    )
    compatible_fuels = _compatible_fuels(fuel, fuel_compatibility)
    same_fuel = within_province.loc[within_province["fuel"].isin(compatible_fuels)]
    exact = same_fuel.loc[same_fuel["technology"] == technology]
    if not exact.empty:
        return exact, "exact_fuel_technology", False, False
    if not same_fuel.empty:
        return same_fuel, "technology_aggregate_within_fuel", True, False
    if not within_province.empty:
        return within_province, "same_province_synthetic_technology", True, True
    return within_province, "unmatched", True, True


def _allocation_weights(candidates: pd.DataFrame) -> tuple[pd.Series, str]:
    capacity = pd.to_numeric(candidates["capacity_mw"], errors="coerce").fillna(0.0)
    if capacity.sum() > 0:
        return capacity / capacity.sum(), "capacity"
    historical = pd.to_numeric(
        candidates.get("recent_historical_generation_mwh", pd.Series(0.0, index=candidates.index)),
        errors="coerce",
    ).fillna(0.0)
    if historical.sum() > 0:
        return historical / historical.sum(), "recent_historical_generation"
    return pd.Series(1.0 / len(candidates), index=candidates.index), "equal"


def allocate_generation(
    generation: pd.DataFrame,
    fleet: pd.DataFrame,
    *,
    fuel_compatibility: Mapping[str, Sequence[str]],
    tolerance_mwh: float = 0.001,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Allocate every generation group without dropping mass.

    Exact matches use province, compatible fuel, technology, and operating-year
    eligibility. If exact technology is unavailable, all compatible technologies
    in the same fuel are used. The final in-province fallback uses any documented
    thermal site and explicitly marks both synthetic technology and fuel assignment.
    """
    _validate_inputs(generation, fleet)
    rows: list[pd.DataFrame] = []
    diagnostics: list[dict[str, object]] = []
    grouped = generation.groupby(GROUP_COLUMNS, dropna=False, sort=True, as_index=False)
    for group_key, group in grouped:
        scenario, year, province, fuel, technology = group_key
        requested = float(group["generation_mwh"].sum())
        candidates, match_level, synthetic_technology, synthetic_fuel = _select_candidates(
            fleet,
            year=int(year),
            province=str(province),
            fuel=str(fuel),
            technology=str(technology),
            fuel_compatibility=fuel_compatibility,
        )
        if requested == 0:
            diagnostics.append(
                {
                    **dict(zip(GROUP_COLUMNS, group_key, strict=True)),
                    "requested_generation_mwh": 0.0,
                    "allocated_generation_mwh": 0.0,
                    "mass_balance_error_mwh": 0.0,
                    "candidate_count": len(candidates),
                    "match_level": match_level,
                    "allocation_weight_basis": "zero_generation",
                    "status": "zero_generation",
                }
            )
            continue
        if candidates.empty:
            diagnostics.append(
                {
                    **dict(zip(GROUP_COLUMNS, group_key, strict=True)),
                    "requested_generation_mwh": requested,
                    "allocated_generation_mwh": 0.0,
                    "mass_balance_error_mwh": -requested,
                    "candidate_count": 0,
                    "match_level": "unmatched",
                    "allocation_weight_basis": "unavailable",
                    "status": "unmatched_error",
                }
            )
            continue
        weights, weight_basis = _allocation_weights(candidates)
        allocated = candidates.copy()
        allocated["scenario"] = scenario
        allocated["year"] = int(year)
        allocated["requested_province"] = province
        allocated["requested_fuel"] = fuel
        allocated["requested_technology"] = technology
        allocated["generation_mwh"] = weights.to_numpy() * requested
        residual = requested - float(allocated["generation_mwh"].sum())
        allocated.iloc[-1, allocated.columns.get_loc("generation_mwh")] += residual
        allocated["allocation_share"] = allocated["generation_mwh"] / requested
        allocated["allocation_rule"] = f"{weight_basis}:{match_level}"
        allocated["allocation_assumption"] = "existing_site_allocation"
        allocated["synthetic_technology_assignment"] = synthetic_technology
        allocated["synthetic_fuel_assignment"] = synthetic_fuel
        allocated["synthetic_site_flag"] = allocated.get(
            "synthetic_site_flag", pd.Series(False, index=allocated.index)
        ).fillna(False)
        capacity = pd.to_numeric(allocated["capacity_mw"], errors="coerce")
        allocated["implied_capacity_factor"] = allocated["generation_mwh"] / (capacity * 8760.0)
        rows.append(allocated)
        total = float(allocated["generation_mwh"].sum())
        capacity_factors = allocated["implied_capacity_factor"].to_numpy()
        max_capacity_factor = (
            float(np.nanmax(capacity_factors))
            if np.isfinite(capacity_factors).any()
            else float("nan")
        )
        diagnostics.append(
            {
                **dict(zip(GROUP_COLUMNS, group_key, strict=True)),
                "requested_generation_mwh": requested,
                "allocated_generation_mwh": total,
                "mass_balance_error_mwh": total - requested,
                "candidate_count": len(candidates),
                "match_level": match_level,
                "allocation_weight_basis": weight_basis,
                "status": "allocated",
                "synthetic_technology_assignment": synthetic_technology,
                "synthetic_fuel_assignment": synthetic_fuel,
                "max_allocation_share": float(weights.max()),
                "max_implied_capacity_factor": max_capacity_factor,
            }
        )
    diagnostic_frame = pd.DataFrame(diagnostics)
    unmatched = diagnostic_frame.loc[diagnostic_frame["status"] == "unmatched_error"]
    if not unmatched.empty:
        labels = unmatched[GROUP_COLUMNS + ["requested_generation_mwh"]].to_dict("records")
        raise ValueError(f"No compatible thermal site for generation groups: {labels}")
    allocations = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not diagnostic_frame.empty:
        errors = diagnostic_frame["mass_balance_error_mwh"].abs()
        if (errors > tolerance_mwh).any():
            bad = diagnostic_frame.loc[
                errors > tolerance_mwh, GROUP_COLUMNS + ["mass_balance_error_mwh"]
            ]
            raise AssertionError(f"Generation mass balance failed:\n{bad}")
    if not allocations.empty and not np.isfinite(allocations["generation_mwh"]).all():
        raise AssertionError("Allocation produced non-finite generation values.")
    if not allocations.empty and not math.isclose(
        allocations["generation_mwh"].sum(),
        generation["generation_mwh"].sum(),
        abs_tol=tolerance_mwh,
    ):
        raise AssertionError("Overall generation mass balance failed.")
    return allocations, diagnostic_frame
