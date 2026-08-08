# MACRO input integration

This pipeline combines team-supplied GCAM-KAIST/MACRO activity with
historical CAPSS emissions to create projected non-power emissions inputs.
GCAM-KAIST is treated as an activity model, not an emissions model: it supplies
sector-by-fuel activity, while CAPSS supplies the base-year pollutant intensity.

## Placing the team-supplied file

GCAM-KAIST/MACRO activity and generation tables are mutable inter-model
scenario inputs, not datasets. They live in named bundles under
`model_inputs/scenarios/`. The upstream files can change when the team supplies
a revision; APHIAM-ready interfaces are rebuilt under the same bundle's
`aphiam/` directory.

Rather than copying the file in by hand, ingest it so the correct location,
schema check, and provenance record all happen in one step:

```bash
make ingest-model-input \
  MODEL_INPUT_SOURCE=~/Downloads/gcam_kaist_sector_fuel_activity.csv \
  MODEL_INPUT_KIND=activity \
  MODEL_INPUT_SOURCE_MODEL=gcam_kaist \
  MODEL_INPUT_SCENARIO=team_handoff \
  MODEL_INPUT_CONTRIBUTOR="GCAM-KAIST team" \
  MODEL_INPUT_NOTE="2026-07 baseline scenario"
```

Use `MODEL_INPUT_KIND=generation` and `MODEL_INPUT_SOURCE_MODEL=macro` for the
2021 KEPCO EF validation's
generation file instead. The command validates that the file has the columns
the downstream step needs (failing fast with the actual column names
otherwise), copies it into
`model_inputs/scenarios/<bundle>/upstream/<model>/`, and writes a
`<name>.metadata.json` sidecar recording the original filename, ingestion
timestamp, contributor, note, bundle, source model, SHA-256, and detected
columns. It then prints the exact follow-up `make` command to run. See
[`src/nzk_aphiam/model_inputs/ingest_macro.py`](../../src/nzk_aphiam/model_inputs/ingest_macro.py).

If the team revises a handoff without changing its filename, rerun the command
with `MODEL_INPUT_FORCE=1`. This makes the mutable update explicit; review the
Git diff and rebuild the bundle's `aphiam/` interface afterward.

## Synthetic non-power pipeline fixture

The native NZK activity deliverable is now available through the separate
native XML interface. Retain this explicitly synthetic activity-index fixture
only for legacy integrator and software smoke tests:

```bash
make build-macro-nonpower-proxy PYTHON_INTERPRETER=.venv/bin/python
make validate-macro-nonpower-proxy PYTHON_INTERPRETER=.venv/bin/python
```

The primary five-column APHIAM input is written to:

- `model_inputs/scenarios/nonpower_proxy_2025_2050/aphiam/gcam_kaist_sector_fuel_activity_proxy_2023_2050.csv`

It is CAPSS-category aligned for smoke testing, uses `2023 = 100` and `2025 = 100`
normalized activity indices, and supplies the existing `no_nzk`, `nzk_low`, and
`nzk_high` scenario names through 2050. A separate rich table retains the 50 P1
inventory activities, conceptual technology labels, reference physical units,
profile assignments, endpoint assumptions, double-counting flags, and model-use
status.

This fixture is a reproducible APHIAM interface, not a team GCAM-KAIST
handoff. It must never be described as a model run or forecast. Method, files,
assumptions, and safeguards are in
[`gcam_kaist_nonpower_proxy.md`](../methods/gcam_kaist_nonpower_proxy.md).

To combine the resulting screening emissions with the matching MACRO-shaped
KEPCO power fixture as Global InMAP point and grid inputs, run
`make build-inmap-combined-inputs`. See
[`inmap_combined_inventory.md`](../methods/inmap_combined_inventory.md).

## Running the integration

Run:

```bash
make integrate-macro-inputs \
  MODEL_INPUT_SCENARIO=team_handoff \
  MACRO_ACTIVITY=model_inputs/scenarios/team_handoff/upstream/gcam_kaist/gcam_kaist_sector_fuel_activity.csv \
  MACRO_MAPPING=docs/references/macro/gcam_capss_sector_fuel_mapping.csv \
  MACRO_BASE_YEAR=2023
```

The default GCAM activity file is:

- `model_inputs/scenarios/team_handoff/upstream/gcam_kaist/gcam_kaist_sector_fuel_activity.csv`

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

The tracked legacy mapping is currently header-only because the team-supplied
non-power GCAM-KAIST taxonomy is not present; it deliberately makes no guessed
native mappings. The populated one-to-many research crosswalk and legal EF
denominators are documented in
[`nonpower_sector_inventory.md`](nonpower_sector_inventory.md). That framework
will eventually augment or replace the aggregate intensity method below, but
does not change this integrator in inventory version `0.2.0`.

APHIAM-ready outputs are written under:

- `model_inputs/scenarios/team_handoff/aphiam/macro_projected_emissions.csv`
- `model_inputs/scenarios/team_handoff/aphiam/macro_capss_emission_factors.csv`
- `model_inputs/scenarios/team_handoff/aphiam/macro_input_diagnostics.csv`
- `model_inputs/scenarios/team_handoff/aphiam/macro_input_integration.metadata.json`

The method is:

1. aggregate CAPSS base-year emissions by selected sector/fuel/pollutant;
2. aggregate GCAM-KAIST base-year activity by scenario and sector/fuel;
3. calculate `emission_factor_kg_per_activity`;
4. multiply every projected activity row by that emission factor.

This is a clearly labeled fallback/validation intensity rather than the primary
future EF database. It assumes one sector, one fuel, one base-year intensity,
and one direct mapping, so it cannot yet represent separate process and
combustion sources or annual technology/fleet/control weighting.

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

Run after supplying the MACRO generation file (see "Placing the team-supplied
file" above):

```bash
make validate-macro-2021-kepco-ef \
  MACRO_GENERATION=model_inputs/scenarios/<bundle>/upstream/macro/<generation-file>.csv
```

or directly:

```bash
PYTHONPATH=src python -m nzk_aphiam.integration.macro_kepco_validation \
  --year 2021 \
  --kepco-ef data/processed/kepco/emission_factors/kepco_annual_ef_distribution_long_by_fuel_technology.csv \
  --macro-generation model_inputs/scenarios/<bundle>/upstream/macro/<generation-file>.csv \
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
