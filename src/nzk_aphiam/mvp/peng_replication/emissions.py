"""Map canonical generation-weighted KEPCO EFs and construct emissions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

POLLUTANTS = {"NOx": "nox", "SOx": "sox"}


def _weighted_ef(rows: pd.DataFrame) -> tuple[float, float, float]:
    weights = pd.to_numeric(rows["valid_generation_mwh"], errors="coerce").fillna(0.0)
    factors = pd.to_numeric(rows["ef_kg_per_mwh"], errors="coerce")
    valid = factors.notna() & (weights > 0)
    if not valid.any():
        raise ValueError("A fallback EF group has no positive generation weights.")
    value = float(np.average(factors.loc[valid], weights=weights.loc[valid]))
    generation = float(weights.loc[valid].sum())
    support = float(pd.to_numeric(rows.loc[valid, "plant_count"], errors="coerce").sum())
    return value, generation, support


def prepare_ef_table(path: Path, *, year: int) -> pd.DataFrame:
    """Select the canonical annual handoff's generation-weighted central field."""
    ef = pd.read_csv(path)
    required = {
        "year",
        "fuel_type_clean",
        "technology",
        "pollutant",
        "ef_kg_per_mwh",
        "valid_generation_mwh",
        "plant_count",
        "start_date",
        "end_date",
    }
    missing = sorted(required - set(ef.columns))
    if missing:
        raise ValueError(f"{path} is missing canonical EF fields: {missing}")
    ef = ef.loc[pd.to_numeric(ef["year"]) == year].copy()
    ef = ef.loc[ef["pollutant"].isin(POLLUTANTS.values())].copy()
    if ef.empty:
        raise ValueError(f"{path} has no central NOx/SOx rows for {year}.")
    if ef["ef_kg_per_mwh"].isna().any():
        raise ValueError("Canonical EF rows contain missing ef_kg_per_mwh.")
    ef["ef_source_path"] = str(path)
    return ef


def _match_one_ef(
    ef: pd.DataFrame, *, fuel: str, technology: str, pollutant: str
) -> dict[str, object]:
    exact = ef.loc[
        ef["fuel_type_clean"].eq(fuel)
        & ef["technology"].eq(technology)
        & ef["pollutant"].eq(pollutant)
    ]
    if len(exact) == 1:
        row = exact.iloc[0]
        return {
            "ef_kg_per_mwh": float(row["ef_kg_per_mwh"]),
            "ef_mapping_level": "exact_fuel_technology",
            "ef_fallback": False,
            "ef_valid_generation_mwh": float(row["valid_generation_mwh"]),
            "ef_plant_count": float(row["plant_count"]),
            "ef_source_period": f"{row['start_date']} to {row['end_date']}",
        }
    within_fuel = ef.loc[ef["fuel_type_clean"].eq(fuel) & ef["pollutant"].eq(pollutant)]
    if not within_fuel.empty:
        value, generation, support = _weighted_ef(within_fuel)
        return {
            "ef_kg_per_mwh": value,
            "ef_mapping_level": "technology_aggregate_within_fuel",
            "ef_fallback": True,
            "ef_valid_generation_mwh": generation,
            "ef_plant_count": support,
            "ef_source_period": (
                f"{within_fuel['start_date'].min()} to {within_fuel['end_date'].max()}"
            ),
        }
    raise ValueError(
        f"No defensible generation-weighted EF for fuel={fuel!r}, "
        f"technology={technology!r}, pollutant={pollutant!r}."
    )


def construct_emissions(
    allocations: pd.DataFrame,
    ef: pd.DataFrame,
    *,
    ef_source_path: Path,
    ef_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate plant emissions and retain pollutant-specific EF provenance."""
    rows: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for record in allocations.to_dict("records"):
        output = dict(record)
        physical_fuel = str(record["fuel"])
        requested_fuel = str(record.get("requested_fuel", physical_fuel))
        ef_fuel = (
            requested_fuel
            if physical_fuel == "oil_and_natural_gas" or record.get("synthetic_fuel_assignment")
            else physical_fuel
        )
        for label, pollutant in POLLUTANTS.items():
            match = _match_one_ef(
                ef,
                fuel=ef_fuel,
                technology=str(record["technology"]),
                pollutant=pollutant,
            )
            prefix = label.lower()
            output[f"{prefix}_kg"] = float(record["generation_mwh"]) * float(
                match["ef_kg_per_mwh"]
            )
            output[f"{prefix}_ef_kg_per_mwh"] = match["ef_kg_per_mwh"]
            output[f"{prefix}_ef_mapping_level"] = match["ef_mapping_level"]
            output[f"{prefix}_ef_fallback"] = match["ef_fallback"]
            diagnostics.append(
                {
                    "scenario": record["scenario"],
                    "year": record["year"],
                    "plant_id": record["plant_id"],
                    "unit_id": record["unit_id"],
                    "fuel": record["fuel"],
                    "ef_fuel": ef_fuel,
                    "technology": record["technology"],
                    "pollutant": label,
                    "ef_kg_per_mwh": match["ef_kg_per_mwh"],
                    "ef_unit": "kg/MWh",
                    "ef_source_path": str(ef_source_path),
                    "ef_source_year": ef_year,
                    **match,
                }
            )
        output["pm25_kg"] = 0.0
        output["nh3_kg"] = 0.0
        output["voc_kg"] = 0.0
        output["pm25_treatment"] = "omitted_no_documented_tsp_to_primary_pm25_conversion"
        output["nh3_treatment"] = "omitted_no_documented_factor"
        output["voc_treatment"] = "omitted_no_documented_factor"
        output["ef_source_path"] = str(ef_source_path)
        output["ef_source_year"] = ef_year
        output["ef_unit"] = "kg/MWh"
        rows.append(output)
    emissions = pd.DataFrame(rows)
    for pollutant in ("nox_kg", "sox_kg"):
        expected = emissions["generation_mwh"] * emissions[f"{pollutant[:-3]}_ef_kg_per_mwh"]
        if not np.allclose(emissions[pollutant], expected, rtol=0.0, atol=1e-8):
            raise AssertionError(f"{pollutant} does not equal generation times EF.")
    return emissions, pd.DataFrame(diagnostics)


def summarize_emissions(emissions: pd.DataFrame) -> pd.DataFrame:
    """Return tidy totals at scenario/year/province/fuel/technology level."""
    identifiers = ["scenario", "year", "province", "fuel", "technology"]
    mass_columns = ["nox_kg", "sox_kg", "pm25_kg", "nh3_kg", "voc_kg"]
    summary = emissions.groupby(identifiers, as_index=False)[
        ["generation_mwh", *mass_columns]
    ].sum()
    return summary.sort_values(identifiers).reset_index(drop=True)


def difference_totals(
    emissions: pd.DataFrame, *, reference_scenario: str, policy_scenario: str
) -> pd.DataFrame:
    """National reference-minus-policy totals; positive is an emissions reduction."""
    columns = ["generation_mwh", "nox_kg", "sox_kg", "pm25_kg", "nh3_kg", "voc_kg"]
    totals = emissions.groupby("scenario")[columns].sum()
    missing = {reference_scenario, policy_scenario} - set(totals.index)
    if missing:
        raise ValueError(f"Cannot difference missing scenarios: {sorted(missing)}")
    difference = totals.loc[reference_scenario] - totals.loc[policy_scenario]
    result = difference.rename(lambda name: f"{name}_reduction").to_frame().T
    result.insert(0, "reference_scenario", reference_scenario)
    result.insert(1, "policy_scenario", policy_scenario)
    result.insert(2, "sign_convention", "reference_minus_policy_positive_is_reduction")
    return result
