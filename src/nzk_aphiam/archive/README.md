# Archived Pipelines

Code in this package is retained for research provenance or possible explicit
reuse. It is not part of the repository's active pipeline.

## Midland concentration/flow estimator

`kepco_midland_concentration/` contains the former Midland monthly-emissions
API scraper, per-site facility-status scrapers, and concentration/flow mass
estimator. They were superseded on 22 July 2026 when KOMIPO supplied direct
monthly pollutant mass for 2024--2025. The archive remains runnable only by
explicit module path and writes to ignored `data/archive/` locations. See
[`docs/archive/kepco_midland_concentration.md`](../../../docs/archive/kepco_midland_concentration.md).

## KMA Hourly Weather

`kma_weather/` contains the superseded KMA ASOS, radiosonde,
stability-analysis, station-history, and Wind Profiler collector and processor.
The team archived it on 22 July 2026 after selecting annual Global InMAP with
packaged global meteorology and built-in bias correction. It is no longer
reachable through active Makefile targets. See
[`docs/archive/kma_weather.md`](../../../docs/archive/kma_weather.md) for its
scope and explicit module commands.

## CleanSYS TMS Scripts

This folder contains archived CleanSYS TMS scripts that convert raw downloaded
API responses into analysis-ready CSV files. They are retained for reference
and are not part of the active KEPCO monthly workflow.

**Not to be confused with** `nzk_aphiam.archive.annual_panel.scrape.cleansys`
(the `[PAUSED: annual non-KEPCO panel]` scraper used by `make scrape-cleansys`,
documented in [`src/nzk_aphiam/data/README.md`](../data/README.md)). That module
downloads annual facility-level CleanSYS emissions for the paused non-KEPCO
plant panel. This folder's `cleansys_tms_*` scripts are an older, unrelated,
real-time TMS stack-measurement pipeline that predates that effort and is not
reachable through any current Makefile target.

The basic workflow is:

```text
raw API response → cleaning script → processed CSV
```

Raw data should not be edited manually. The cleaning scripts read from
`data/archive/raw/` and write cleaned outputs to `data/archive/interim/`.

Generated CSV files are not committed to Git by default because `data/` is ignored in `.gitignore`.

## CleanSYS TMS

The CleanSYS TMS scripts process real-time stack emissions measurement data downloaded from the data.go.kr CleanSYS API.

Source scraper:

```bash
python -m nzk_aphiam.archive.cleansys_tms_scraper
```

Optional filters:

```bash
python -m nzk_aphiam.archive.cleansys_tms_scraper \
    --area-nm 충남 \
    --fact-manage-nm 태안
```

Raw output location:

```text
data/archive/raw/cleansys_tms/
```

## Wide cleaner

The wide cleaner creates the main cleaned data product.

Run:

```bash
python -m nzk_aphiam.archive.cleansys_tms_wide
```

Output:

```text
data/archive/interim/cleansys_tms/cleansys_tms_wide.csv
```

Unit of observation:

```text
facility/stack at measurement time
```

In other words, each row represents one facility stack at one timestamp.

Key identifying columns:

```text
mesure_dt
area_nm
fact_manage_nm
stack_code
source_file
```

Pollutant columns are stored in wide format. For each pollutant, the cleaner creates:

```text
{pollutant}_value_raw
{pollutant}_value
{pollutant}_status
{pollutant}_limit_raw
{pollutant}_limit
```

Example pollutants:

```text
nox
sox
tsp
co
nh3
hf
hcl
```

Example columns:

```text
nox_value_raw
nox_value
nox_status
nox_limit_raw
nox_limit
```

The wide file is the canonical cleaned dataset because the natural unit of observation is a stack/facility at a measurement time, with pollutant measurements as variables.

## Long cleaner

The long cleaner creates a pollutant-level version of the same data.

Run:

```bash
python -m nzk_aphiam.archive.cleansys_tms_long
```

Output:

```text
data/archive/interim/cleansys_tms/cleansys_tms_long.csv
```

Unit of observation:

```text
facility/stack/measurement time/pollutant
```

Each row represents one pollutant measurement for one facility stack at one timestamp.

Key columns:

```text
mesure_dt
area_nm
fact_manage_nm
stack_code
pollutant
measure_value_raw
measure_value
measure_status
limit_raw
limit
source_file
```

The long file is useful for pollutant-level plots, groupby summaries, regressions, and model inputs where pollutant is treated as a variable.

## Handling nonnumeric measurement values

Some CleanSYS measurement fields contain status strings instead of numeric values.

Example:

```text
측정자료확인중(가동중지)
```

The cleaners preserve this information instead of discarding it.

The raw string is stored in:

```text
*_value_raw
```

The numeric value, if available, is stored in:

```text
*_value
```

The interpreted status is stored in:

```text
*_status
```

For example, `측정자료확인중(가동중지)` is currently coded as:

```text
shutdown
```

This allows downstream analysis to distinguish between true missing values, shutdown periods, and valid numeric measurements.

## Encoding

CSV files are saved with:

```text
utf-8-sig
```

This helps Korean text display correctly when opening the CSV files in Excel.

## Notes

* Do not manually edit files in `data/archive/raw/`.
* Do not commit `.env` or API keys.
* Do not commit large raw or processed data files unless there is a specific reason.
* Commit the scraper and cleaning scripts, not the generated data.
* The wide file should be treated as the main cleaned data product.
* The long file should be treated as a derived analysis-friendly version.
