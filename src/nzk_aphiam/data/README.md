# Thermal Data Pipeline

This document describes the source-specific scraping, cleaning, and processing
logic for the thermal power datasets. For installation, team onboarding,
citation, and the main analysis workflow, see the
[project README](../../../README.md).

## Common Commands

Run every thermal subsidiary scraper sequentially:

```bash
make scrape-thermal
```

This is a networked workflow that contacts data.go.kr and subsidiary websites.
Midland Power is included even though its current emissions API is not
sufficient for monthly emission-factor calculations. Individual subsidiary
and dataset targets are available through `make help`.

Rebuild every currently implemented cleaner:

```bash
make clean-thermal
```

Run the complete offline verification workflow using preserved raw files:

```bash
make verify-offline PYTHON_INTERPRETER=.venv/bin/python
```

Reproduce the annual facility-emission-factor inputs and plant crosswalk:

```bash
make reproduce-facility-crosswalk PYTHON_INTERPRETER=.venv/bin/python
```

This downloads EPSIS rosters and annual generation, CleanSYS emissions, and
ENV-INFO disclosures for 2015-2024 before rebuilding the crosswalk. To prove
that the normalized files can be regenerated without network access:

```bash
make verify-facility-crosswalk-offline PYTHON_INTERPRETER=.venv/bin/python
```

The offline command fails if any required raw response is absent. Override the
common period with `FACILITY_START_YEAR` and `FACILITY_END_YEAR`.

Build the final annual plant-level generation and emissions panel from the
preserved inputs:

```bash
make reproduce-annual-plant-panel-offline PYTHON_INTERPRETER=.venv/bin/python
```

This classifies and assigns EPSIS annual-generation rows, reconciles direct
subsidiary/CleanSYS/ENV-INFO emissions without adding overlapping sources, and
writes the plant-year panel under `data/archive/annual_plant/`.
Detailed rules and output definitions are in
[`docs/archive/annual_plant_panel_methods.md`](../../../docs/archive/annual_plant_panel_methods.md).

Download annual CleanSYS facility emissions:

```bash
make scrape-cleansys PYTHON_INTERPRETER=.venv/bin/python
```

The public annual series covers 2015 through the latest finalized reporting
year. Raw JSON responses and normalized CSV files are written to:

```text
data/interim/supporting/emissions/cleansys/raw/
```

Each facility row reports total, dust (TSP), SOx, NOx, HCl, HF, NH3, and CO
emissions in kilograms per year, plus the CleanSYS facility code, business
registration number, facility name, and address.

These are workplace/facility totals for TMS-monitored stacks, not individual
generator-unit totals. The business registration number groups sites belonging
to the same legal entity, while the facility name often identifies the plant
or operating division. Electricity-sector facilities can be linked to the
separate EPSIS generator roster using names and addresses, but emissions should
not be allocated to units without an additional documented stack-unit mapping.

## Shared Interim Schema

The subsidiary cleaners use a shared thermal schema containing the observation
date, English plant name, nullable unit number, subsidiary, energy type,
generation, capacity, pollutant measurements and units, and original Korean
source labels.

The processed monthly KEPCO dataset is the clean KEPCO subsidiary lane. It
adds `operator_category = kepco` before writing
`kepco_monthly_generation_emissions.csv`. The annual plant panel adds the same
concept as `operator_category`, using `kepco` for KEPCO and generation-company
operators and `private_or_other` for the broader reconstructed EPSIS/CleanSYS/
ENV-INFO records.

Nullable `plant_opening_date` and `plant_closing_date` columns are reserved for
documented plant metadata. Cleaners must not infer them from the first or last
observation in a source dataset.

Nullable `plant_latitude` and `plant_longitude` columns are also reserved for a
separate plant metadata dataset. Future coordinates should use WGS84 decimal
degrees (`EPSG:4326`) and consistently represent the plant site rather than
individual stacks or generating units.

## Western Power

Download and clean the preserved Western Power monthly source:

```bash
make scrape-western-power
make clean-western-power
```

The interim output is:

```text
data/interim/western_power/western_power_monthly_generation_emissions.csv
```

The cleaner retains every source row and never converts a blank pollutant or
generation value to zero. Western Power reports pollutant mass in metric
tonnes and does not report temperature.

Western's `호기` field mixes physical generating units with combined-cycle
blocks and plant-level rows. The cleaner therefore adds a stable
`reporting_unit_id`, classifies `observation_level`, and does not treat every
numeric label as a physical unit number. It also assigns conservative
`row_status` and `row_status_basis` values. Rows before a reporting boundary's
first observed activity and rows explicitly marked retired (`폐지`) are
`inactive_placeholder`; other entirely blank rows remain `unknown_status`.
`pollutant_data_pattern` records which pollutant fields are actually present,
including the common `nox_only` pattern at gas facilities.
`reporting_start_date` is deliberately the first month with reported activity,
not an inferred commissioning date. `reporting_end_date` is populated only
when the source explicitly gives a retirement date; `reporting_window_basis`
records that distinction.

The raw source does not include fuel type. The cleaner enriches `energy_type`
from official Korea Western Power plant and operating-history pages. Mapping
rules, effective dates, evidence, and source URLs are recorded in
[`docs/references/thermal/western_power_energy_type_mapping.csv`](../../../docs/references/thermal/western_power_energy_type_mapping.csv).

Pyeongtaek steam units are classified as `oil_and_natural_gas` through February
2020 and `natural_gas` from March 2020, following the documented start of
full-LNG operation on February 27, 2020.

Two additional official Western datasets were evaluated as possible gap
patches. The annual generator-performance file is too coarse for monthly
imputation. The daily generation file covers Taean units 1–10 from 2019 through
2023; aggregating it produced 563 overlapping unit-months and no values for a
blank month in the monthly source. It is therefore validation evidence, not an
imputation input. CleanSYS and ENV-INFO are annual facility-level emissions
sources and are likewise retained for validation/crosswalking rather than
distributed into missing unit-months.

## East-West Power

Download and clean the East-West Power monthly source:

```bash
make scrape-eastwest-power
make clean-eastwest-power
```

The interim output is:

```text
data/interim/eastwest_power/eastwest_power_monthly_generation_emissions.csv
```

The cleaner preserves every monthly source row. Fuel mappings and their
official sources are recorded in
[`docs/references/thermal/eastwest_power_energy_type_mapping.csv`](../../../docs/references/thermal/eastwest_power_energy_type_mapping.csv).
The scraper also writes the enrichment source URLs into its raw JSON and
metadata outputs.

Unlike Western, East-West's `호기` field is always a clean numeric unit
number, so `observation_level` is always `generating_unit` and
`reporting_unit_id` is built directly from the plant name and unit number.
The source has no retirement-note column, so `reporting_end_date` is always
blank and `row_status`/`row_status_basis` can only detect rows before a
unit's first reported activity (`inactive_placeholder`), not explicit
retirements.

## Southern Power

Southern Power requires the shared data.go.kr API key and these endpoint
settings in `.env`:

```dotenv
DATA_GO_KR_API_KEY=...
SOUTHERN_POWER_EMISSIONS_API_URL=https://api.odcloud.kr/api/15099713/v1/uddi:e7ea7bfd-d0c4-4cb6-afea-95fa7821cb51
SOUTHERN_POWER_GENERATION_API_URL=http://apis.data.go.kr/B552520/GenInfo/getDataService
```

Download and clean both sources:

```bash
make scrape-southern-power
make clean-southern-power
```

Raw responses, CSV extracts, and redacted request metadata are saved under:

```text
data/raw/southern_power/
```

The interim output is:

```text
data/interim/southern_power/southern_power_monthly_generation_emissions.csv
```

Southern reports emissions in kilograms, which are retained without
conversion. Daily gross generation is summed by month and converted from kWh to
MWh. Fuel and source-granularity rules are recorded in
[`docs/references/thermal/southern_power_energy_type_mapping.csv`](../../../docs/references/thermal/southern_power_energy_type_mapping.csv).

Some emissions rows are more detailed than the generation records. The cleaner
aggregates Samcheok A/B stack rows to generating units and combined-cycle
components to plant level where a steam turbine is shared. Generation remains
null where the generation API has no safely matching record; it is not
fabricated or forward-filled.

Southern also exposes an independent hourly generation API and an annual
plant/unit generation file. Run `make scrape-southern-power-hourly-generation`
and `make scrape-southern-power-annual-generation` to acquire them. The cleaner
uses hourly generation only as a fallback when the primary daily source is
missing, retains both values when they overlap, and records their percent
difference and reconciliation status. The hourly service requires separate
data.go.kr approval.

Monthly output records the physical reporting boundary, contributing component
count, minimum reported source days across those components, calendar days
expected, and a `complete`, `partial`, or `missing` coverage flag. The annual
file is not used to impute months; it produces
`southern_power_annual_generation_validation.csv` at plant-year level.

Unresolved emissions codes and the requested stack-to-generator crosswalk are
listed in `docs/references/thermal/southern_power_unresolved_data_request.md`.

## EPSIS Generator Rosters

KPX EPSIS provides two complementary generator-level sources:

```bash
make scrape-epsis-annual
make scrape-epsis-generation
make scrape-epsis-snapshots
```

Annual generator-detail rosters cover 2012 through 2024. The scraper preserves
the raw EPSIS grid response and writes a faithful UTF-8 CSV under:

```text
data/interim/supporting/plant_rosters/epsis/raw/annual/
```

The generator-change board contains irregular dated snapshots beginning on
December 31, 2012. Each original ZIP contains provider-generated CSV and XLSX
files. ZIPs are preserved without extraction under:

```text
data/interim/supporting/plant_rosters/epsis/raw/snapshots/
```

The snapshot command writes a complete board manifest with source attachment
URLs and local checksums. Use `snapshots --index-only` to refresh only the
manifest, or `snapshots --limit N` to download the newest N archives while
testing. Existing files are reused unless `--overwrite` is passed.

EPSIS also publishes annual capacity and generation records from 2002 through
2024 under:

```text
data/interim/supporting/plant_rosters/epsis/raw/annual_generation/
```

These records include reported capacity, gross generation, station use, net
generation, maximum and average output, load factor, utilization rate, fuel,
and company. They are not uniformly generating-unit records. The source mixes
individual unit labels, whole plants, multi-unit combined-cycle and hydro
plants, company/technology totals, and portfolio aggregates. EPSIS's English
table labels the identifying column `Plant`, despite the Korean menu being
named `발전기별` ("by generator").

EPSIS also notes that some small non-KEPCO and renewable facilities are
omitted, and that reported capacity may not reflect facility improvements.
Keep this separate from the rosters and preserve `source_record_name` without
assuming plant or unit granularity.

## Private Generator Emissions

Download annual ENV-INFO disclosures for individual and representative
power-sector sites:

```bash
make scrape-env-info
```

The scraper preserves compressed public detail pages and writes yearly CSVs
plus a combined 2015-2024 panel under:

```text
data/interim/supporting/emissions/env_info/raw/
```

The normalized fields include facility name and annual NOx, SOx, and TSP in
metric tonnes. ENV-INFO's industry category also includes non-generating
utilities, so match facilities to EPSIS before calculating emission factors.
Each year contains a detail-page checksum manifest, and the combined panel has
metadata linking it to the yearly metadata files.

## Thermal Plant Crosswalk

Build the EPSIS thermal plant dimension and link it to ENV-INFO and CleanSYS:

```bash
make build-thermal-crosswalk
```

Outputs under `data/interim/supporting/crosswalks/thermal/` include:

- `epsis_thermal_plants.csv`: normalized EPSIS plant entities.
- `epsis_emissions_facility_crosswalk.csv`: preferred source matches.
- `epsis_emissions_facility_links.csv`: accepted long-form links, including
  historical source IDs after ownership changes.
- `epsis_emissions_match_candidates.csv`: ranked alternatives for review.

Use `manual`, `automatic`, and `probable` links for downstream joins.
`review` and `unmatched` records are not accepted links. A matched name still
does not prove that generation and emissions cover identical equipment, so
retain the boundary and mixed-fuel flags when calculating emission factors.

All aliases and human-reviewed links are data rather than hidden code:

- [`docs/references/crosswalk/name_aliases.csv`](../../../docs/references/crosswalk/name_aliases.csv)
  records each company/plant normalization, evidence, URL, and access date.
- [`docs/references/crosswalk/manual_facility_links.csv`](../../../docs/references/crosswalk/manual_facility_links.csv)
  records preferred and historical facility IDs with row-level evidence.
- [`docs/references/data_sources.csv`](../../../docs/references/data_sources.csv)
  is the project source inventory for the datasets used by these workflows.

Crosswalk `metadata.json` records the SHA-256 checksum of every EPSIS annual
input, both emissions panels, both reference tables, and the method version.

## Processed Monthly Datasets

Combine the interim datasets that currently report compatible monthly
pollutant mass:

```bash
make combine-kepco
```

The preferred outputs are one file per subsidiary:

```text
data/processed/kepco/subsidiaries/<source>_monthly_generation_emissions.csv
```

Field completeness for each product is recorded in:

```text
data/processed/kepco/subsidiaries/subsidiary_coverage.csv
```

Use this table to distinguish full generation-and-emissions panels from
emissions-only sources. Missing values are preserved rather than imputed. A
combined backward-compatible output is also written to:

```text
data/processed/kepco/kepco_monthly_generation_emissions.csv
```

The dataset description is:

```text
docs/datasets/kepco_monthly_generation_emissions.md
```

The command processes East-West, Western, Southern, South-East, and Midland
Power independently before producing the combined file. It
checks every input schema before concatenation, retains generation in MWh and
capacity in MW where available, and standardizes NOx, SOx, and dust mass to
kilograms. East-West and Western values are multiplied by 1,000 to convert
metric tonnes to kilograms; Southern and South-East values are already in
kilograms.

Oxygen, flue-gas flow, and temperature are omitted from this processed monthly
mass dataset because they are empty across the included mass sources. They
remain in source-specific interim datasets where reported.

The command also writes
`kepco_monthly_generation_emissions_metadata.csv` beside the processed data.
It contains ordered `varname` and `label` fields for every column, including
units in quantitative labels.

Midland facility-status rows are included where the source reports stack
pollutant concentrations and flue-gas flow.

## Audit Stage

`combine-kepco` audits every subsidiary's freshly standardized data before
merging it into the final combined file, so the combined output is always
analysis-ready -- there is no separate step to remember to run afterward:

```bash
make combine-kepco
```

or, to also re-clean every subsidiary from raw data first:

```bash
make reproduce-kepco-monthly
```

The auditor (`src/nzk_aphiam/data/audit/thermal/auditor.py`) generalizes a
unit-resolution audit originally written for East-West Power only so it now
runs identically across all five subsidiaries' processed files. It checks
for duplicate unit-months, negative values, nameplate violations, zero
generation/pollutants where the row is not already an `inactive_placeholder`,
and unit-specific outlier mass and emission-factor thresholds
(`Q3 + 3 * IQR`, requiring at least 12 valid unit-months).

It never drops or imputes a row. It rewrites each subsidiary's processed CSV
and the final combined CSV with `audit_severity` (the worst flag raised, or missing) and
`audit_issue_codes` (every issue code, joined with `;`), and writes
long-format flag detail and summary tables to
`results/tables/<subsidiary>/audit/`. To re-run just the audit stage without
recombining (e.g. after changing a threshold but not the data), use
`make audit-kepco`.

## South-East Power

South-East Power publishes daily air-pollutant measurements through a signed
CSV export form:

```bash
make scrape-southeast-power
make scrape-southeast-power-generation
make clean-southeast-power
```

The scraper downloads calendar-year chunks, preserves each original CP949
response, writes a combined UTF-8 CSV, and records request metadata under:

```text
data/raw/southeast_power/
```

Use `--reuse-existing-source` on the Python scraper command to resume from
preserved yearly files. Although data.go.kr advertises history from 2015, the
provider export currently begins on July 16, 2020.

The interim output is:

```text
data/interim/southeast_power/southeast_power_monthly_derived_emissions.csv
```

It converts reported daily concentrations and flow to inferred daily mass, then
aggregates to month/unit rows in the shared thermal schema. The derivation uses
the provider's confirmed formulas:

```text
SOx kg  = SOx ppm * flow Sm3 * 64 / (22.4 * 1,000,000) * 288
NOx kg  = NOx ppm * flow Sm3 * 46 / (22.4 * 1,000,000) * 288
Dust kg = dust mg/Sm3 * flow Sm3 / 1,000,000 * 288
```

KOEN clarified in June 2026 that the reported daily concentration, flow, and
calculated mass values are daily averages of 288 five-minute readings, so the
`288` multiplier approximates daily totals from those daily averages. KOEN also
confirmed that SOx uses an SO2 molecular weight of `64`, NOx uses an NO2
molecular weight of `46`, reported concentrations are already corrected to 6%
standard oxygen, and numeric units combine A/B stack labels (for example,
Samcheonpo 3 = 3A + 3B). Dust concentration rows above `30 mg/Sm3` are excluded
from dust mass because they match invalid/non-operating measurement patterns
and otherwise overstate KOEN annual dust mass by about threefold.

Monthly unit-level generation is sourced from KOEN's public generation export,
which is also registered as data.go.kr OpenAPI dataset `15120379`. The scraper
preserves yearly source CSV responses and writes the combined normalized file:

```text
data/raw/southeast_power/southeast_power_monthly_generation.csv
```

The cleaner crosswalks Bundang emissions units 1--8 to generation units
CG1--CG8, maps Yeosu's unlabeled `-` stack to unit 2, combines Samcheonpo A/B
stack labels at numbered-unit level, and joins generation only after emissions
have been aggregated to that boundary.

## Midland Power

Midland Power exposes monthly generation and air-pollutant measurements through
data.go.kr XML APIs, plus facility-specific air-status datasets through
odcloud file-backed APIs:

```bash
make scrape-midland-power
make clean-midland-power
```

The commands retain source field names and values, save XML responses, CSV
extracts, and redacted metadata under:

```text
data/raw/midland_power/
```

They refuse to replace existing outputs unless `--overwrite` is explicitly
provided. Optional endpoint overrides are
`MIDLAND_POWER_GENERATION_API_URL` and `MIDLAND_POWER_EMISSIONS_API_URL`.

The verified June 12, 2026 pull contains 4,424 generation records from January
2012 through May 2026 and 853 emissions records for five thermal plants. The
emissions API returns no records for December 2019, December 2020, or July
2023; the scraper preserves those source gaps.

The monthly emissions API returns pollutant standards and average concentration
values, but not flue-gas flow, so it is not used for mass derivation. The newer
facility-status APIs are saved under:

```text
data/raw/midland_power/facilities/
```

Each facility has its own subdirectory, and the scraper also writes:

```text
data/raw/midland_power/facilities/midland_power_facility_air_status.csv
```

The cleaner reads that merged raw file and writes:

```text
data/interim/midland_power/midland_power_monthly_derived_emissions.csv
```

For Seocheon, Sejong, Jeju, and Incheon, the facility-status APIs report
pollutant concentrations and stack `유량`, so the cleaner derives row-level mass
and sums to month/unit rows:

```text
SOx kg  = SOx ppm * flow Sm3 * 64 / (22.4 * 1,000,000)
NOx kg  = NOx ppm * flow Sm3 * 46 / (22.4 * 1,000,000)
Dust kg = dust mg/Sm3 * flow Sm3 / 1,000,000
```

Boryeong, Seoul, and Shin-Boryeong are retained as raw facility datasets, but
they expose TMS diagnostic/calibration fields rather than stack pollutant
concentrations plus stack flow, so the cleaner excludes them from mass
derivation. Generation, capacity, and fuel type remain null in the derived
facility-status output.
