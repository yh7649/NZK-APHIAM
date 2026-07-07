# KEPCO Monthly Generation and Emissions Dataset

This document describes the processed monthly KEPCO subsidiary generation and
emissions dataset. This is the preferred dataset for near-term analysis. Work
on the annual plant-level panel is paused indefinitely because its plant
matching and annual source integration are too messy for the current research
needs, and the project's scope is narrowed to KEPCO thermal subsidiaries. The
annual panel's code is preserved under `src/nzk_aphiam/archive/annual_panel/`;
see [`docs/project/data_provenance.md`](../project/data_provenance.md) for
details and the still-runnable (but `[PAUSED]`-marked) Makefile targets.

The active dataset uses KEPCO-wide naming rather than "thermal" naming. The
included monthly emissions sources are mostly thermal subsidiaries, but the
research object is the KEPCO monthly generation-and-emissions panel. The KEPCO
nuclear subsidiary is not included because we did not find compatible monthly
pollutant mass emissions for it.

The preferred processed datasets are:

- `data/processed/kepco/subsidiaries/eastwest_power_monthly_generation_emissions.csv`
- `data/processed/kepco/subsidiaries/western_power_monthly_generation_emissions.csv`
- `data/processed/kepco/subsidiaries/southern_power_monthly_generation_emissions.csv`
- `data/processed/kepco/subsidiaries/southeast_power_monthly_generation_emissions.csv`
- `data/processed/kepco/subsidiaries/midland_power_monthly_generation_emissions.csv`
- `data/processed/kepco/subsidiaries/subsidiary_coverage.csv`

These keep the common schema and kilogram standardization while making each
source's usable fields and time coverage explicit. The coverage table reports
non-missing counts and percentages for generation, capacity, fuel type, and
each pollutant. Missing source values are not imputed.

The combined dataset remains available for backward compatibility:

- `data/processed/kepco/kepco_monthly_generation_emissions.csv`

The column metadata file is:

- `data/processed/kepco/kepco_monthly_generation_emissions_metadata.csv`

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
- `{fuel_type_counts}`: row counts by cleaned `fuel_type`
- `{nonmissing_value_counts}`: non-missing counts for generation, capacity,
  NOx, SOx, and dust/TSP

A local current-values file is written automatically by `make combine-kepco`
(and refreshed by `make audit-kepco`) beside the processed data at:

- `data/processed/kepco/README.md`

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

The schema is intentionally wide (43 base columns, or 45 after auditing) because
most of it is provenance and reliability metadata needed to merge five
incompatible government sources defensibly, not redundant data. If you only
need the dataset for fuel-type or emission-factor analysis, the columns
below are grouped by how often you actually need them:

- **Core measures** (almost every analysis needs these): `date`,
  `plant_name`, `plant_number`, `subsidiary_company`, `fuel_type`,
  `energy_generated_mwh`, `energy_capacity_mw`, `nox`, `sox`, `dust_tsp`.
- **Identity columns** (needed when joining or deduplicating at the
  unit/reporting level): `source_dataset`, `reporting_unit_id`,
  `original_korean_unit_name`.
- **Provenance and reliability metadata** (needed when deciding whether to
  trust or exclude a row, but not for typical aggregation): `row_status`,
  `row_status_basis`, `observation_level`, `component_count`,
  `generation_source`, `generation_coverage_status`,
  `generation_days_reported`, `generation_days_expected`,
  `generation_reconciliation_status`, `pollutant_data_pattern`,
  `reporting_start_date`, `reporting_end_date`, `reporting_window_basis`.
  The combined and subsidiary processed files also carry `audit_severity`
  and `audit_issue_codes` from this tier, populated automatically by
  `combine-kepco`; see [Audit Stage](#audit-stage) below.
- **Units and encoding** (constant or near-constant within a column;
  consult once, then ignore): `pollutant_measurement_basis`, `nox_unit`,
  `sox_unit`, `dust_tsp_unit`, `emissions_mass_unit`, `operator_category`,
  `observation_frequency`.
- **Source-language reference** (useful for tracing a row back to the
  original filing, rarely used in analysis): `original_korean_plant_name`,
  `original_korean_note`.
- **Plant location and dates** (location and opening metadata come from
  `docs/references/crosswalk/plant_location_dates.csv`; actual and planned
  unit retirements come from `plant_retirement_dates.csv`, with reviewed
  evidence files beside both references): `plant_opening_date`,
  `plant_closing_date`, `plant_closing_date_status`, `plant_latitude`,
  `plant_longitude`.
  The coordinate-derived administrative fields are `plant_province` and
  `plant_district`; their reviewed plant mapping is stored in
  `docs/references/crosswalk/plant_geography.csv`.

## Main Columns

- `source_dataset`: source interim dataset identifier.
- `operator_category`: operator category; currently `kepco`.
- `observation_frequency`: observation frequency; currently `monthly`.
- `date`: observation month, stored as the first day of the month.
- `plant_name`: English plant name.
- `plant_number`: source-reported generating unit number where available.
- `plant_opening_date`: plant opening date.
- `plant_closing_date`: plant closing date.
- `plant_closing_date_status`: whether `plant_closing_date` is an observed
  `actual` closure or an officially published `planned` closure. Plans that
  specify only a calendar year are encoded as December 31 of that year; this
  is an explicit end-of-year convention, not an asserted exact shutdown day.
- `plant_latitude`: plant latitude in WGS84 decimal degrees.
- `plant_longitude`: plant longitude in WGS84 decimal degrees.
- `plant_province`: current English province or metropolitan-city name.
- `plant_district`: current English city, county, or autonomous-district name.
- `subsidiary_company`: KEPCO subsidiary company name.
- `fuel_type`: cleaned primary energy or fuel type.
- `technology`: generation technology at the row's reporting boundary. Current
  values distinguish `combined_cycle_gas_turbine` (NGCC),
  `conventional_steam_turbine`, `cogeneration_chp`,
  `internal_combustion_engine`, and
  `integrated_gasification_combined_cycle` (IGCC). No current KEPCO row is an
  open-cycle NGCT or CCS unit. Technology evidence is recorded in
  `docs/references/thermal/kepco_technology_mapping.csv` and checked against
  `docs/references/province_level_power.xlsx` where that roster has coverage.
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

South-East Power pollutant mass is derived from daily concentration and stack
flow, then aggregated to the matching unit before joining KOEN's monthly
unit-level generation and capacity. Samcheonpo A/B stack components are joined
to their numbered generator only after aggregation; Bundang units 1--8 map to
CG1--CG8, and Yeosu's unlabeled second stack maps to generator 2. This avoids
repeating one generator's MWh across multiple emissions stacks.

East-West and Western source values are converted from metric tonnes to
kilograms by multiplying by `1,000`. Southern and South-East values are already
reported in kilograms. For Midland, the Incheon, Jeju, Sejong, and Seocheon
facility-status sources contain pollutant concentrations and stack flow. The
cleaner derives approximate row-level pollutant mass, aggregates component
turbines/units to the monthly plant/technology boundary reported by Midland's
generation API, and joins generation and capacity at that boundary. This
supports emission-factor analysis without duplicating a plant subtotal across
its component turbines. Boryeong, Seoul, and Shin-Boryeong remain raw-only
because their facility endpoints expose TMS instrument diagnostics rather than
the pollutant-concentration and stack-flow fields required for mass derivation.

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

Each subsidiary cleaner fills `plant_latitude`, `plant_longitude`,
`plant_opening_date`, and `plant_closing_date` by joining on
(`subsidiary_company`, `plant_name`) against
`docs/references/crosswalk/plant_location_dates.csv`, a hand-built crosswalk
against a teammate-supplied plant roster
(`docs/references/province_level_power.xlsx`), official operator plant pages,
and mapped OpenStreetMap plant footprints. The associated
`plant_location_dates_official_evidence.csv` records the official address and
URL, coordinate method and map element, and opening-date evidence for every
plant added during the official-source review. The join fails loudly if a
cleaner ever produces a plant the crosswalk has no row for at all.

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

`combine-kepco` audits every subsidiary's freshly standardized data *before*
merging it into the final combined file, so the file at the canonical output
path is never in an unaudited state, even momentarily:

```bash
make combine-kepco
```

The auditor is implemented in
`src/nzk_aphiam/data/audit/thermal/auditor.py` and runs the same checks
(duplicate unit-months, negative values, nameplate violations, zero
generation, zero pollutants alongside positive generation, unit-specific
outlier mass/emission-factor thresholds, and a recent-vs-baseline level-shift
check) across all five subsidiaries, generalized from a unit-resolution audit
originally written for East-West Power only.

The level-shift check (`recent_shift_high_*`/`recent_shift_low_*`) exists
because the full-history outlier thresholds have a blind spot: if a unit's
reporting shifts to a sustained new level (not a one-off spike), enough
months eventually accumulate at the new level to pull the unit's own
historical Q1/Q3 toward it, and the threshold stops catching the very rows
it was meant to catch. This check instead computes each unit's threshold
only from data before its most recent 12 months, so a sustained shift in
that window is judged against unaffected history. It requires 24 months of
pre-window history per unit, and computes quantiles on a log scale so the
low-side fence stays meaningful for strictly positive, right-skewed
pollutant data instead of clipping to zero. It is `warning` severity, not
`critical`, because a detected shift can be a genuine operational change
(e.g. an SCR/FGD retrofit cutting an emission factor) as easily as a
reporting problem -- the check flags "statistically different from this
unit's own history," not "wrong."

It is deliberately non-destructive: it never drops or imputes a row. Instead
it rewrites each subsidiary's processed CSV and the final combined CSV with two additional
columns, `audit_severity` (the worst flag raised against the row, or missing
if none) and `audit_issue_codes` (every issue code raised, joined with
`;`), so analysts choose what to exclude with full provenance for the
decision. Rows already explained by `row_status == "inactive_placeholder"`
are not re-flagged for zero generation.

Long-format detail per subsidiary — every flagged row with its value,
threshold, and explanation, plus summary tables — is written to
`results/tables/{subsidiary}/audit/`.

To re-run just the audit stage without recombining (for example, after
changing an audit threshold but not the underlying data), use:

```bash
make audit-kepco
```

This rebuilds the combined file by re-auditing whatever is currently in the
per-subsidiary processed files; run `combine-kepco` first if you also need
to refresh those from interim data. The audit stage extends the combined
variable metadata with labels for both audit columns either way.

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

From the project root, regenerate the monthly KEPCO processed dataset
(cleaned, location-enriched, audited, and merged in one step) with:

```bash
python -m nzk_aphiam.data.process.thermal
```

or:

```bash
make combine-kepco
```

or, to also re-clean every subsidiary from raw data first:

```bash
make reproduce-kepco-monthly
```

See [Audit Stage](#audit-stage) if you only need to re-run the audit step
on its own.

Then rerun the R analysis with:

```bash
Rscript analysis/kepco/kepco_monthly_analysis.R
```

For a quick local summary, read the local current-values file that
`combine-kepco`/`audit-kepco` regenerate automatically:

```bash
cat data/processed/kepco/README.md
```

## Notes

For the foreseeable future, analysis should prioritize this monthly KEPCO
dataset rather than the annual plant-level panel. The monthly panel is more
directly tied to KEPCO subsidiary source data, preserves finer source-reported
unit/reporting identities, and avoids the heavier matching assumptions needed
for the annual plant-level "frankenstein" panel.
