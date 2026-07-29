"""Observed-first stack parameter resolution with explicit provenance."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PARAMETERS = {
    "stack_height_m": "stack_height_m",
    "stack_diameter_m": "stack_diameter_m",
    "stack_temperature_k": "exit_temp_c",
    "stack_velocity_m_s": "flue_gas_velocity_m_s",
}


def _convert_temperature(value: float) -> float:
    return value + 273.15


def impute_stack_parameters(
    fleet: pd.DataFrame, stack_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach stack values using unit, plant, fuel-tech, fuel, and thermal medians."""
    stack = pd.read_csv(stack_path)
    observed = stack.loc[stack["match_status"].eq("matched")].copy()
    for source_column in PARAMETERS.values():
        observed[source_column] = pd.to_numeric(observed[source_column], errors="coerce")
    unit = observed.dropna(subset=["reporting_unit_id"]).drop_duplicates(
        "reporting_unit_id", keep="first"
    )
    plant = (
        observed.groupby(["subsidiary_company", "plant_name"], as_index=False)[
            list(PARAMETERS.values())
        ]
        .median(numeric_only=True)
        .reset_index(drop=True)
    )
    resolved = fleet.copy()
    unit_columns = {source: f"unit_{source}" for source in PARAMETERS.values()}
    resolved = resolved.merge(
        unit[["reporting_unit_id", *PARAMETERS.values()]].rename(
            columns={"reporting_unit_id": "unit_id", **unit_columns}
        ),
        on="unit_id",
        how="left",
        validate="one_to_one",
    )
    plant_columns = {source: f"plant_{source}" for source in PARAMETERS.values()}
    resolved = resolved.merge(
        plant.rename(columns=plant_columns),
        on=["subsidiary_company", "plant_name"],
        how="left",
        validate="many_to_one",
    )
    observed_with_fleet = observed.merge(
        fleet[["subsidiary_company", "plant_name", "fuel", "technology"]].drop_duplicates(),
        on=["subsidiary_company", "plant_name"],
        how="left",
    )
    fuel_technology_medians = observed_with_fleet.groupby(["fuel", "technology"])[
        list(PARAMETERS.values())
    ].median(numeric_only=True)
    fuel_medians = observed_with_fleet.groupby("fuel")[list(PARAMETERS.values())].median(
        numeric_only=True
    )
    all_medians = observed[list(PARAMETERS.values())].median(numeric_only=True)

    for target, source in PARAMETERS.items():
        values: list[float] = []
        provenance: list[str] = []
        for _, row in resolved.iterrows():
            candidates = [
                (row.get(f"unit_{source}"), "unit_observed"),
                (row.get(f"plant_{source}"), "plant_observed"),
            ]
            key = (row["fuel"], row["technology"])
            if key in fuel_technology_medians.index:
                candidates.append(
                    (fuel_technology_medians.loc[key, source], "fuel_technology_median")
                )
            if row["fuel"] in fuel_medians.index:
                candidates.append((fuel_medians.loc[row["fuel"], source], "fuel_median"))
            candidates.append((all_medians.get(source), "all_thermal_median"))
            selected_value = float("nan")
            selected_source = "unavailable"
            for value, label in candidates:
                if pd.notna(value):
                    selected_value = float(value)
                    selected_source = label
                    break
            if source == "exit_temp_c" and pd.notna(selected_value):
                selected_value = _convert_temperature(selected_value)
            values.append(selected_value)
            provenance.append(selected_source)
        resolved[target] = values
        resolved[f"{target}_provenance"] = provenance
    drop = [
        *[f"unit_{source}" for source in PARAMETERS.values()],
        *[f"plant_{source}" for source in PARAMETERS.values()],
    ]
    resolved = resolved.drop(columns=drop)
    if resolved[list(PARAMETERS)].isna().any().any():
        missing = resolved.loc[
            resolved[list(PARAMETERS)].isna().any(axis=1), ["unit_id", *PARAMETERS]
        ]
        raise ValueError(f"Stack imputation could not resolve all required parameters:\n{missing}")
    diagnostics = resolved[
        [
            "plant_id",
            "unit_id",
            "plant_name",
            "fuel",
            "technology",
            *PARAMETERS,
            *[f"{target}_provenance" for target in PARAMETERS],
        ]
    ].copy()
    diagnostics["all_stack_values_observed"] = (
        diagnostics[[f"{target}_provenance" for target in PARAMETERS]]
        .eq("unit_observed")
        .all(axis=1)
    )
    return resolved, diagnostics
