# KEPCO Monthly Generation and Emissions Dataset

This document describes the processed monthly KEPCO subsidiary generation and
emissions dataset. This is the preferred dataset for near-term analysis. Work
on the annual plant-level panel is paused because its plant matching and annual
source integration are too messy for the current research needs.

The active dataset uses KEPCO-wide naming rather than "thermal" naming. The
included monthly emissions sources are mostly thermal subsidiaries, but the
research object is the KEPCO monthly generation-and-emissions panel. The KEPCO
nuclear subsidiary is not included because we did not find compatible monthly
pollutant mass emissions for it.

The preferred processed datasets are:

- `data/kepco/processed/subsidiaries/eastwest_power_monthly_generation_emissions.csv`
- `data/kepco/processed/subsidiaries/western_power_monthly_generation_emissions.csv`
- `data/kepco/processed/subsidiaries/southern_power_monthly_generation_emissions.csv`
- `data/kepco/processed/subsidiaries/southeast_power_monthly_generation_emissions.csv`
- `data/kepco/processed/subsidiaries/midland_power_monthly_generation_emissions.csv`
- `data/kepco/processed/subsidiaries/subsidiary_coverage.csv`

These keep the common schema and kilogram standardization while making each
source's usable fields and time coverage explicit. The coverage table reports
non-missing counts and percentages for generation, capacity, fuel type, and
each pollutant. Missing source values are not imputed.

The combined dataset remains available for backward compatibility:

- `data/kepco/processed/kepco_monthly_generation_emissions.csv`

The column metadata file is:

- `data/kepco/processed/kepco_monthly_generation_emissions_metadata.csv`

## Current Coverage

Coverage values are defined by the generated outputs after a team member runs
the scripts. They are intentionally not hard-coded here because adding Midland
or refreshing source websites can change them.

Current-value variables:

- `{monthly_rows}`: rows in `kepco_monthly_generation_emissions.csv`
- `{monthly_start_date}`: first monthly observation date
- `{monthly_end_date}`: last monthly observation date
- `{plant_count}`: distinct `plant_name` values
- `{unit_reporting_identities}`: distinct source-reported unit/reporting
  identities
- `{numeric_unit_identities}`: distinct clean numeric unit identities
- `{source_dataset_counts}`: row counts by `source_dataset`
- `{subsidiary_company_counts}`: row counts by `subsidiary_company`
- `{energy_type_counts}`: row counts by cleaned `energy_type`
- `{nonmissing_value_counts}`: non-missing counts for generation, capacity,
  NOx, SOx, and dust/TSP

A local current-values file may be kept beside the processed data at:

- `data/kepco/processed/README.md`

## Unit of Observation

Each row is a monthly observation for a KEPCO subsidiary plant, unit, or
source-reported generating identity. The dataset is closer to unit resolution
than the annual plant panel because it preserves:

- `plant_name`
- `plant_number`
- `original_korean_unit_name`
- `source_dataset`

`unit/reporting identities` are counted using:

```text
source_dataset + plant_name + plant_number + original_korean_unit_name
```

This is the broadest fine-resolution identity. It preserves source-reported
unit labels even when they are not clean numeric unit numbers.

`numeric unit identities` are counted only when `plant_number` is populated:

```text
source_dataset + plant_name + plant_number
```

In plain terms, numeric unit identities are cleaner numbered units.
Unit/reporting identities are the finest identities available from the source,
including combined-cycle blocks, paired units, text unit labels, and rows where
the source does not provide a clean numeric unit.

## Fuel Categories

The monthly dataset uses cleaned fuel categories that preserve source detail
without forcing rows into broad mentor technology bins.

- `coal`: coal-fired generation rows.
- `natural_gas`: rows reported as gas/LNG only.
- `oil`: petroleum-derived oil fuel rows without gas/LNG.
- `oil_and_natural_gas`: mixed oil plus gas/LNG rows.
- `bio_oil_and_diesel`: rows involving bio-heavy-oil and diesel-type fuels.
- `unknown`: rows where the source fuel/energy type is missing or cannot be
  assigned confidently.

The mixed and specific oil categories are separated because they can have
different emissions behavior. In particular, `oil_and_natural_gas` should not
be treated as pure natural gas, and `bio_oil_and_diesel` should not be silently
collapsed into generic fossil oil.

## Column Tiers

The schema is intentionally wide (41 base columns, or 43 after auditing) because
most of it is provenance and reliability metadata needed to merge five
incompatible government sources defensibly, not redundant data. If you only
need the dataset for fuel-type or emission-factor analysis, the columns
below are grouped by how often you actually need them:

- **Core measures** (almost every analysis needs these): `date`,
  `plant_name`, `plant_number`, `subsidiary_company`, `energy_type`,
  `energy_generated_mwh`, `energy_capacity_mw`, `nox`, `sox`, `dust_tsp`.
- **Identity columns** (needed when joining or deduplicating at the
  unit/reporting level): `source_dataset`, `reporting_unit_id`,
  `original_korean_unit_name`.
- **Provenance and reliability metadata** (needed when deciding whether to
  trust or exclude a row, but not for typical aggregation): `row_status`,
  `row_status_basis`, `observation_level`, `component_count`,
  `generation_source`, `generation_coverage_status`,
  `generation_days_reported`, `generation_days_expected`,
  `alternate_energy_generated_mwh`, `generation_difference_pct`,
  `generation_reconciliation_status`, `pollutant_data_pattern`,
  `reporting_start_date`, `reporting_end_date`, `reporting_window_basis`.
  After running `make audit-kepco`, the combined and subsidiary processed files
  also carry `audit_severity` and `audit_issue_codes` from this tier; see
  [Audit Stage](#audit-stage) below.
- **Units and encoding** (constant or near-constant within a column;
  consult once, then ignore): `pollutant_measurement_basis`, `nox_unit`,
  `sox_unit`, `dust_tsp_unit`, `emissions_mass_unit`, `operator_category`,
  `observation_frequency`.
- **Source-language reference** (useful for tracing a row back to the
  original filing, rarely used in analysis): `original_korean_plant_name`,
  `original_korean_note`.
- **Largely unpopulated today** (kept for schema stability if a source ever
  supplies them): `plant_opening_date`, `plant_closing_date`,
  `plant_latitude`, `plant_longitude`.

## Main Columns

- `source_dataset`: source interim dataset identifier.
- `operator_category`: operator category; currently `kepco`.
- `observation_frequency`: observation frequency; currently `monthly`.
- `date`: observation month, stored as the first day of the month.
- `plant_name`: English plant name.
- `plant_number`: source-reported generating unit number where available.
- `plant_opening_date`: plant opening date.
- `plant_closing_date`: plant closing date.
- `plant_latitude`: plant latitude in WGS84 decimal degrees.
- `plant_longitude`: plant longitude in WGS84 decimal degrees.
- `subsidiary_company`: KEPCO subsidiary company name.
- `energy_type`: cleaned primary energy or fuel type.
- `energy_generated_mwh`: monthly electricity generation in MWh.
- `energy_capacity_mw`: installed generating capacity in MW.
- `reporting_unit_id`: stable source reporting-boundary identifier. Western
  IDs preserve the full source `호기` label, preventing Pyeongtaek steam and
  combined-cycle rows with the same extracted number from colliding.
- `reporting_start_date`: first month with reported generation or pollutant
  activity. This is an observed-data boundary, not a commissioning date.
- `reporting_end_date`: source-documented retirement date where available.
- `reporting_window_basis`: evidence used for the reporting window.
- `observation_level`: physical reporting boundary where audited, including
  `generating_unit`, `gas_turbine`, `generation_block`, `plant`, and
  `unresolved`.
- `component_count`: source generation components aggregated to the row.
- `generation_source`: primary daily source, hourly fallback, or missing.
- `generation_days_reported`: minimum distinct source days across contributing
  components.
- `generation_days_expected`: calendar days in the month.
- `generation_coverage_status`: source-appropriate generation availability;
  Western uses `reported` or `missing`, while daily-derived sources may use
  `complete`, `partial`, or `missing`.
- `alternate_energy_generated_mwh`: independent Southern hourly-source monthly
  total when available.
- `generation_difference_pct`: absolute difference between Southern generation
  sources as a percentage of the larger value.
- `generation_reconciliation_status`: overlap comparison or fallback status.
- `row_status`: evidence-based row status: `active_reported`, `active_partial`,
  `inactive_placeholder`, or `unknown_status` where assigned.
- `row_status_basis`: evidence used for `row_status`.
- `nox`: monthly nitrogen oxides emissions in kilograms.
- `sox`: monthly sulfur oxides emissions in kilograms.
- `dust_tsp`: monthly total suspended particulate emissions in kilograms.
- `pollutant_data_pattern`: pollutant fields present on the source row, such as
  `nox_sox_dust`, `nox_only`, or `none`.
- `pollutant_measurement_basis`: pollutant measurement basis; currently `mass`.
- `nox_unit`, `sox_unit`, `dust_tsp_unit`: pollutant-specific canonical units.
- `emissions_mass_unit`: common pollutant mass unit; currently `kilograms`.
- `original_korean_plant_name`: original Korean plant name.
- `original_korean_unit_name`: original Korean generating unit name.
- `original_korean_note`: original Korean source note.

## Source Logic

The processed monthly dataset combines compatible KEPCO subsidiary generation
and pollutant-mass sources. It retains generation in MWh, capacity in MW, and
standardizes NOx, SOx, and dust/TSP emissions to kilograms.

The combined sources are generated from the source datasets included by the
current pipeline. The source list and row counts should be read from
`{source_dataset_counts}` after regeneration.

Current source families include KEPCO subsidiary data from East-West, Western,
Southern, South-East, and Midland Power where compatible monthly mass data are
available.

Southern Power is assembled from separate emissions and generation systems.
Its combined-cycle observations remain at plant level when the shared emissions
boundary cannot be mapped defensibly to individual turbine components. Missing
daily generation may be filled only from Southern's independent hourly API;
annual totals are validation evidence and are never distributed across months.

East-West and Western source values are converted from metric tonnes to
kilograms by multiplying by `1,000`. Southern and South-East values are already
reported in kilograms. Midland contributes facility-status rows where usable
mass-related information is available in the processed pipeline.

Oxygen, flue-gas flow, and temperature are not included in this processed
monthly mass dataset because they are not consistently populated across the
combined mass sources. Those variables remain in source-specific interim data
where available.

Western rows mix unit, combined-cycle block, and plant reporting boundaries.
The cleaner preserves those boundaries rather than assuming that a missing
unit number means a single-unit plant. It retains source blanks as missing and
flags pre-activity or explicitly retired placeholders so analyses can exclude
them without deleting source history. Gas-facility rows often report NOx but
not SOx or dust; pollutant-specific analyses should use each pollutant's own
nonmissing sample instead of requiring all three.

Subsidiary coverage outputs retain total `rows`, add `analysis_rows` and
`inactive_placeholder_rows`, and calculate field-coverage percentages over
`analysis_rows`. Thus source history remains reproducible without allowing
known pre-operation or retired placeholders to depress analytical coverage.

Official Western annual generation is too coarse to repair monthly gaps. Its
daily generation file covers only Taean units 1–10 for 2019–2023; 563 monthly
aggregates overlapped the monthly file, 98.6% agreed within 1%, and none filled
a blank monthly generation value. CleanSYS and ENV-INFO emissions are annual
and facility-level. These sources are useful validation evidence, but none
supports defensible monthly unit-level pollutant imputation.

## Audit Stage

After `combine-kepco` builds the per-subsidiary processed files, a separate
auditor checks each one for outliers and reporting anomalies:

```bash
python -m nzk_aphiam.data.audit.thermal
```

or:

```bash
make audit-kepco
```

or, to clean, combine, and audit in one step:

```bash
make reproduce-kepco-monthly
```

The auditor is implemented in
`src/nzk_aphiam/data/audit/thermal/auditor.py` and runs the same checks
(duplicate unit-months, negative values, nameplate violations, zero
generation, zero pollutants alongside positive generation, and unit-specific
outlier mass/emission-factor thresholds) across all five subsidiaries,
generalized from a unit-resolution audit originally written for East-West
Power only.

It is deliberately non-destructive: it never drops or imputes a row. Instead
it rewrites each subsidiary's processed CSV and the final combined CSV with two additional
columns, `audit_severity` (the worst flag raised against the row, or missing
if none) and `audit_issue_codes` (every issue code raised, joined with
`;`), so analysts choose what to exclude with full provenance for the
decision. Rows already explained by `row_status == "inactive_placeholder"`
are not re-flagged for zero generation.

Long-format detail per subsidiary — every flagged row with its value,
threshold, and explanation, plus summary tables — is written to
`results/tables/{subsidiary}/audit/`. Re-running `combine-kepco` after
`audit-kepco` rebuilds the subsidiary files from interim data and removes
the audit columns from both subsidiary and combined files; re-run
`audit-kepco` afterward to restore them. The audit stage also extends the
combined variable metadata with labels for both audit columns.

## Analysis Outputs

The current R analysis is:

- `analysis/kepco/kepco_monthly_analysis.R`

Key generated monthly fuel-analysis tables include:

- `results/tables/kepco/kepco_pollutant_summary_by_fuel.csv`
- `results/tables/kepco/kepco_ef_coverage_by_plant_fuel.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_generation_mwh.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_sox_ef.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_nox_ef.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_dust_tsp_ef.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_sox_emissions_kg.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_nox_emissions_kg.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_dust_tsp_emissions_kg.csv`

Raw generation and raw emissions plots are generated by fuel type with a
6-month moving average. Emission-factor plots are also generated by fuel type
with a 6-month moving average.

## Regeneration

From the project root, regenerate the monthly KEPCO processed dataset with:

```bash
python -m nzk_aphiam.data.process.thermal
```

or:

```bash
make combine-kepco
```

Then audit it (see [Audit Stage](#audit-stage)) with `make audit-kepco`, or
run clean, combine, and audit together with `make reproduce-kepco-monthly`.

Then rerun the R analysis with:

```bash
Rscript analysis/kepco/kepco_monthly_analysis.R
```

For a quick local summary:

```bash
python - <<'PY'
import csv
from collections import Counter

path = "data/kepco/processed/kepco_monthly_generation_emissions.csv"
with open(path, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

unit_reporting = {
    (
        row["source_dataset"],
        row["plant_name"],
        row["plant_number"],
        row["original_korean_unit_name"],
    )
    for row in rows
}
numeric_units = {
    (row["source_dataset"], row["plant_name"], row["plant_number"])
    for row in rows
    if row["plant_number"]
}

print("rows:", len(rows))
print("date range:", min(row["date"] for row in rows), "to", max(row["date"] for row in rows))
print("plants:", len({row["plant_name"] for row in rows}))
print("unit/reporting identities:", len(unit_reporting))
print("numeric unit identities:", len(numeric_units))
print("source datasets:", Counter(row["source_dataset"] for row in rows))
print("subsidiaries:", Counter(row["subsidiary_company"] for row in rows))
print("energy types:", Counter(row["energy_type"] or "unknown" for row in rows))
for col in ["energy_generated_mwh", "energy_capacity_mw", "nox", "sox", "dust_tsp"]:
    print(f"{col} non-missing:", sum(bool(row[col]) for row in rows))
PY
```

## Notes

For the foreseeable future, analysis should prioritize this monthly KEPCO
dataset rather than the annual plant-level panel. The monthly panel is more
directly tied to KEPCO subsidiary source data, preserves finer source-reported
unit/reporting identities, and avoids the heavier matching assumptions needed
for the annual plant-level "frankenstein" panel.
