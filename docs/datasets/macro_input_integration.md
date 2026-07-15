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
