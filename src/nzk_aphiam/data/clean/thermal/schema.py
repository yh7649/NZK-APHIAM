"""Shared output schema for thermal subsidiary cleaners."""

THERMAL_OUTPUT_COLUMNS = [
    "date",
    "plant_name",
    "plant_number",
    "plant_opening_date",
    "plant_closing_date",
    "plant_latitude",
    "plant_longitude",
    "subsidiary_company",
    "energy_type",
    "energy_generated_mwh",
    "energy_capacity_mw",
    "nox",
    "sox",
    "dust_tsp",
    "pollutant_measurement_basis",
    "nox_unit",
    "sox_unit",
    "dust_tsp_unit",
    "emissions_mass_unit",
    "oxygen",
    "oxygen_unit",
    "flue_gas_flow",
    "flue_gas_flow_unit",
    "temperature_celsius",
    "original_korean_plant_name",
    "original_korean_unit_name",
    "original_korean_note",
]

COMBINED_THERMAL_OUTPUT_COLUMNS = [
    "source_dataset",
    "observation_frequency",
    *THERMAL_OUTPUT_COLUMNS,
]
