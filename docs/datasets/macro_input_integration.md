# MACRO input integration

This pipeline combines externally supplied GCAM-KAIST/MACRO activity with
historical CAPSS emissions to create projected non-power emissions inputs.
GCAM-KAIST is treated as an activity model, not an emissions model: it supplies
sector-by-fuel activity, while CAPSS supplies the base-year pollutant intensity.

Run:

```bash
make integrate-macro-inputs \
  MACRO_ACTIVITY=data/raw/macro/gcam_kaist_sector_fuel_activity.csv \
  MACRO_MAPPING=docs/references/macro/gcam_capss_sector_fuel_mapping.csv \
  MACRO_BASE_YEAR=2023
```

The default GCAM activity file is:

- `data/raw/macro/gcam_kaist_sector_fuel_activity.csv`

Expected activity columns are:

```text
scenario, year, sector, fuel, activity
```

Use CLI options directly if the supplied file uses different names:

```bash
PYTHONPATH=src python -m nzk_aphiam.data.process.macro \
  --gcam-activity path/to/activity.csv \
  --year-column year \
  --sector-column sector \
  --fuel-column fuel \
  --activity-column activity \
  --scenario-columns scenario
```

The optional mapping file must contain:

```text
gcam_sector,gcam_fuel,capss_sector,capss_fuel
```

Values are normalized with the same label logic used for CAPSS, so Korean source
labels such as `도로이동오염원` and already-normalized keys such as
`도로이동오염원` both work. If no mapping is supplied, GCAM sector/fuel labels are
passed through as CAPSS keys; this is mainly useful for tests or hand-aligned
inputs.

Outputs are written under:

- `data/processed/macro/macro_projected_emissions.csv`
- `data/processed/macro/macro_capss_emission_factors.csv`
- `data/processed/macro/macro_input_diagnostics.csv`
- `data/processed/macro/macro_input_integration.metadata.json`

The method is:

1. aggregate CAPSS base-year emissions by selected sector/fuel/pollutant;
2. aggregate GCAM-KAIST base-year activity by scenario and sector/fuel;
3. calculate `emission_factor_kg_per_activity`;
4. multiply every projected activity row by that emission factor.

Review `macro_input_diagnostics.csv` before using the output. It flags GCAM
activity without CAPSS emissions, CAPSS emissions without matching base-year
GCAM activity, and missing or zero base-year activity denominators.

Default pollutants are `SOx`, `NOx`, `NH3`, `VOCs`, and `PM2.5`. Override with
`--pollutants` or `MACRO_POLLUTANTS` when building broader inventories.

## 2021 KEPCO EF back-cast validation

The historical validation workflow is separate from the generic MACRO/CAPSS
intensity integrator. It tests:

```text
KEPCO-derived 2021 emission factor
× MACRO-reported 2021 generation
= modeled 2021 pollutant emissions
```

and compares the modeled values with the CAPSS public-plus-private national
power-sector actuals by aligned fuel, official CAPSS technology, and pollutant.
It uses the generation-weighted KEPCO EF field `ef_kg_per_mwh`; it does not use
plant-level arithmetic means and does not calculate EFs from CAPSS.

Run after supplying the MACRO generation file:

```bash
make validate-macro-2021-kepco-ef \
  MACRO_GENERATION=data/raw/macro/<team-supplied-generation-file>.csv
```

or directly:

```bash
PYTHONPATH=src python -m nzk_aphiam.integration.macro_kepco_validation \
  --year 2021 \
  --kepco-ef results/tables/kepco/annual_handoff/kepco_annual_ef_distribution_long_by_fuel_technology.csv \
  --macro-generation data/raw/macro/<team-supplied-generation-file>.csv \
  --capss-actual data/processed/capss/power_fuel_technology_2016_2023.parquet \
  --crosswalk docs/references/macro/macro_kepco_capss_power_crosswalk.csv
```

The crosswalk is version controlled at:

- `docs/references/macro/macro_kepco_capss_power_crosswalk.csv`

Only rows marked `exact` or `documented_proxy` enter the primary comparison.
Rows marked `unresolved` or `excluded` are preserved in diagnostics. This is
important because MACRO generation technologies, KEPCO plant technologies, and
CAPSS combustion-equipment categories are not identical ontologies.

Outputs are:

- `data/processed/macro/macro_2021_kepco_ef_modeled_emissions_by_province.csv`
- `data/processed/macro/macro_2021_kepco_ef_modeled_emissions_by_province.parquet`
- `results/tables/macro/macro_2021_kepco_ef_vs_capss_actual.csv`
- `results/tables/macro/macro_2021_kepco_ef_vs_capss_summary.csv`
- `results/diagnostics/macro/macro_2021_unmapped_generation.csv`
- `results/diagnostics/macro/macro_2021_missing_kepco_ef.csv`
- `results/diagnostics/macro/macro_2021_missing_capss_actual.csv`
- `results/diagnostics/macro/macro_2021_duplicate_crosswalk_matches.csv`
- `results/diagnostics/macro/macro_2021_validation_coverage.csv`
- `results/diagnostics/macro/macro_2021_validation_metadata.json`
- `results/figures/macro/validation_2021/`

Interpret discrepancies as uncalibrated validation evidence. At minimum, review
EF transfer error, classification mismatch, generation mismatch, and inventory-
method mismatch before considering any EF calibration.
