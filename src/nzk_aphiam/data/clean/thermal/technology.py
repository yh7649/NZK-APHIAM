"""Documented technology classification for KEPCO thermal reporting units."""

from __future__ import annotations

import pandas as pd

CONVENTIONAL_STEAM_PLANTS = {
    "Dangjin",
    "Donghae",
    "Honam",
    "Hadong",
    "Namjeju Steam",
    "Samcheok",
    "Samcheonpo",
    "Shin-Boryeong",
    "Yeongdong",
    "Yeongheung",
    "Yeosu",
    "Seocheon",
}
CHP_PLANTS = {"Bundang", "Gimpo", "Ilsan", "Sejong", "Shinsejong"}
CCGT_PLANTS = {
    "Andong",
    "Busan",
    "Gunsan",
    "Hallim",
    "Incheon",
    "Namjeju Combined",
    "Seoul",
    "Shin-Incheon",
    "Seoincheon",
    "Yeongwol",
}


def classify_technology(row: pd.Series) -> str:
    """Classify one already-standardized row at its reporting boundary."""
    plant = row["plant_name"]
    reporting_id = str(row.get("reporting_unit_id", ""))

    if plant in CONVENTIONAL_STEAM_PLANTS:
        return "conventional_steam_turbine"
    if plant in CHP_PLANTS:
        return "cogeneration_chp"
    if plant in CCGT_PLANTS:
        return "combined_cycle_gas_turbine"
    if plant == "Boryeong":
        if reporting_id.endswith(":보령기력"):
            return "conventional_steam_turbine"
        if reporting_id.endswith(":보령복합"):
            return "combined_cycle_gas_turbine"
        raise ValueError(f"Unknown Boryeong reporting boundary: {reporting_id!r}")
    if plant == "Ulsan":
        return (
            "conventional_steam_turbine"
            if int(row["plant_number"]) <= 6
            else "combined_cycle_gas_turbine"
        )
    if plant == "Jeju":
        if reporting_id.endswith(":제주내연"):
            return "internal_combustion_engine"
        if reporting_id.endswith(":제주기력"):
            return "conventional_steam_turbine"
        if reporting_id.endswith(":제주복합"):
            return "combined_cycle_gas_turbine"
    if plant == "Pyeongtaek":
        return (
            "conventional_steam_turbine"
            if ":기력 " in reporting_id
            else "combined_cycle_gas_turbine"
        )
    if plant == "Taean":
        return (
            "integrated_gasification_combined_cycle"
            if reporting_id.endswith(":IGCC")
            else "conventional_steam_turbine"
        )
    raise ValueError(f"No technology mapping for {reporting_id!r} ({plant!r})")


def apply_technology_mapping(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach a non-missing technology label before subsidiary outputs merge."""
    result = frame.copy()
    result["technology"] = result.apply(classify_technology, axis=1).astype("string")
    return result
