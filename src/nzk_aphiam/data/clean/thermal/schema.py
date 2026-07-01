"""Shared output schema for thermal subsidiary cleaners."""

THERMAL_OUTPUT_COLUMNS = [
    "date",
    "plant_name",
    "plant_number",
    "plant_opening_date",
    "plant_closing_date",
    "plant_latitude",
    "plant_longitude",
    "plant_province",
    "plant_district",
    "subsidiary_company",
    "energy_type",
    "energy_generated_mwh",
    "energy_capacity_mw",
    "reporting_unit_id",
    "reporting_start_date",
    "reporting_end_date",
    "reporting_window_basis",
    "observation_level",
    "component_count",
    "generation_source",
    "generation_days_reported",
    "generation_days_expected",
    "generation_coverage_status",
    "alternate_energy_generated_mwh",
    "generation_difference_pct",
    "generation_reconciliation_status",
    "row_status",
    "row_status_basis",
    "nox",
    "sox",
    "dust_tsp",
    "pollutant_data_pattern",
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

COMBINED_THERMAL_EXCLUDED_COLUMNS = {
    "oxygen",
    "oxygen_unit",
    "flue_gas_flow",
    "flue_gas_flow_unit",
    "temperature_celsius",
}

COMBINED_THERMAL_OUTPUT_COLUMNS = [
    "source_dataset",
    "operator_category",
    "observation_frequency",
    *[
        column
        for column in THERMAL_OUTPUT_COLUMNS
        if column not in COMBINED_THERMAL_EXCLUDED_COLUMNS
    ],
]
