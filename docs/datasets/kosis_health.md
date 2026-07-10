# KOSIS Public Health And Demographic Baseline

## Overview

This collection provides the Korean district-level health and demographic
baseline for NZK-APHIAM. It contains mortality outcomes, population
denominators, and health-relevant demographic and socioeconomic covariates from
public KOSIS tables. Mortality is reported by place of residence, not place of
death.

The local snapshot was retrieved on 2026-07-01 (UTC) and covers 2001–2024,
except for monthly population, which begins in 2011. Counts are retained as
counts; for count models, use `log(population)` as an offset rather than
converting the source data permanently to rates.

## Dataset inventory

| Dataset | KOSIS table | Frequency | Local coverage | Rows | Grain |
|---|---|---:|---:|---:|---|
| Monthly all-cause deaths | `DT_1B82A01` | Monthly | 2001–2024 | 89,892 | geography × month × selected sex category |
| Cause-specific deaths | `DT_1B34E13` | Annual | 2001–2024 | 386,672 | geography × year × cause × selected sex category |
| Resident population | `DT_1B040A3` | Monthly | 2011–2024 | 47,661 | geography × month × selected sex category |
| Resident population by age | `DT_1B04006` | Annual | 2008–2024 | 245,310 | geography × year × sex × five-year age band |
| All-cause mortality by age | `DT_1B80A18` | Annual | 2001–2024 | 383,265 | geography × year × sex × five-year age band |
| Projected population by age | `DT_1BPB002E` | Annual | 2022–2042 | 236,691 | geography × year × sex × five-year age band |
| Aged population indicators | `DT_1YL20631` | Monthly | monthly API available from 2008 | 150,966 | geography × month × indicator |
| Sex-ratio indicators | `DT_1YL20701` | Monthly | monthly API available from 2008 | 150,966 | geography × month × indicator |
| Foreign-resident composition | `TX_11025_A001_A` | Annual | available from 2015 | 86,402 | geography × year × resident category × sex |
| Fiscal independence | `DT_1YL20921` | Annual | available from 2003 | 8,079 | geography × year × indicator |
| Elderly one-person households | `DT_1YL12701` | Annual | continuous annual API series from 2015 | 7,380 | geography × year × indicator |
| Registered disability | `DT_11761_N009` | Annual | available from 2019 | 14,436 | geography × year × disability severity × sex |
| Health-insurance applied population | `DT_1YL202114E` | Annual | available from 2004 | 39,081 | geography × year × insurance category |
| One-person households | `DT_1YL21161` | Annual | continuous annual API series from 2015 | 7,419 | geography × year × indicator |
| One-person households by age and sex | `DT_1PL1502` | Annual | available from 2015 | 155,808 | geography × year × age group × sex |
| Internal migration counts | `DT_1B26001_A01` | Monthly | available from 2001 in local panel | 604,976 | geography × month × migration measure |
| Old housing indicators | `DT_1YL202004` | Annual | available from 2015 | 7,384 | geography × year × indicator |
| Vacant housing indicators | `DT_1YL202005` | Annual | available from 2015 | 7,380 | geography × year × indicator |
| Long-term-care facilities | `DT_35006_N021` | Annual | available from 2010 | 83,964 | geography × year × facility type × measure |
| NHIS regional coverage, institutions, workforce, premiums | `TX_35003_A018` etc. | Annual | mostly 2006 onward | 254,539 | regional table × geography × year × category × measure |

The source mortality tables extend to 1997 and 1998 respectively. The current
project snapshot starts in 2001 to align with the AirKorea analysis window.
Although the population table advertises older annual history, its monthly API
series returns no data before 2011.

The age-stratified resident population table `DT_1B04006` publishes single-year
ages. The collector pulls those single-year rows and bins them to `0-4`,
`5-9`, ..., `80+`. KOSIS district population projections in `DT_1BPB002E`
currently end in 2042, so they do not support a district-level 2050+ horizon.

## Files

```text
data/raw/health/kosis/
├── metadata.json
├── monthly_deaths/
│   ├── monthly_deaths.csv
│   └── raw/DT_1B82A01_<year>.json
├── cause_deaths/
│   ├── cause_deaths.csv
│   └── raw/DT_1B34E13_<year>.json
├── population/
│   ├── population.csv
│   └── raw/DT_1B040A3_<year>.json
├── age_population/
│   ├── age_population.csv
│   └── raw/DT_1B04006_<year>.json
├── age_mortality/
│   ├── age_mortality.csv
│   └── raw/DT_1B80A18_<year>.json
├── population_projection_age/
│   ├── population_projection_age.csv
│   └── raw/DT_1BPB002E_<year>.json
├── aging/
│   ├── aging.csv
│   └── raw/DT_1YL20631_<year>.json
├── sex_ratio/
│   ├── sex_ratio.csv
│   └── raw/DT_1YL20701_<year>.json
├── foreign_residents/
│   ├── foreign_residents.csv
│   └── raw/TX_11025_A001_A_<year>.json
├── fiscal_independence/
│   ├── fiscal_independence.csv
│   └── raw/DT_1YL20921_<year>.json
└── elderly_living_alone/
    ├── elderly_living_alone.csv
    └── raw/DT_1YL12701_<year>.json
```

The annual JSON files preserve the KOSIS responses. The CSV files are
deterministic normalized extracts. `metadata.json` is the machine-readable
provenance manifest and records retrieval time, coverage, row counts, relative
paths, reuse/download status, and SHA-256 checksums for every raw annual file
and normalized CSV.

Full default scrapes write `metadata.json`. Targeted commands such as
`make scrape-demographics` and `make scrape-social-determinants` write
`metadata_selected_<hash>.json` in the same directory so selected-run
provenance does not overwrite full-baseline provenance.

Current normalized-file checksums:

| File | SHA-256 |
|---|---|
| `monthly_deaths/monthly_deaths.csv` | `f96974d5bd32484055e8c21b21aff4f56acf99e8c00dadf89aa5431f140228ad` |
| `cause_deaths/cause_deaths.csv` | `7e96cc7618fdaf8b1bc37348f1ee01e6ef0ee71f0a7f3d20b8b901455ffdf24c` |
| `population/population.csv` | `e3ccee16403d078465273465017855fe5a774b856f6580993995e3becebce0b8` |
| `age_population/age_population.csv` | `5b443285172939fb7db1db884c4d96fd8a347fb8b99fa9ef9650c9b532dd9612` |
| `age_mortality/age_mortality.csv` | `7f7fc038faedb6aa561f9c9e8b007931d7f246afec45bf5756af74a9a576709d` |
| `population_projection_age/population_projection_age.csv` | `0d9a21c2645b5f21323d461e010041cb4be037d4f8dfb36634014aa15f1ed3f0` |

## Data dictionary

Fields shared by all three normalized files:

| Field | Description |
|---|---|
| `district_code` | KOSIS published administrative-area code; read as text to preserve leading zeros. |
| `district_name` | Korean administrative-area name published by KOSIS. |
| `geography_level` | Project label: `national`, `province`, `district`, or `district_equivalent`. |
| `year` | Four-digit reference year. |
| `sex_code` | KOSIS sex-category code, retained as text. |
| `sex` | Korean sex-category label; the current pull selects the total (`계`) category. |
| `unit` | KOSIS unit label; `명` means persons. |

Dataset-specific fields:

| File | Field | Description |
|---|---|---|
| Monthly deaths | `month` | Calendar month, 1–12. |
| Monthly deaths | `deaths_all` | All-cause death count. |
| Cause deaths | `cause_code` | KOSIS 50-cause-group code, retained as text. |
| Cause deaths | `cause_name` | Korean cause-group label. |
| Cause deaths | `deaths` | Death count for the cause group. |
| Population | `month` | Calendar month, 1–12. |
| Population | `population` | Resident population count. |
| Age population | `age_band` | Project-standard five-year age band: `0-4`, `5-9`, ..., `80+`. |
| Age population | `population` | Resident population count after summing KOSIS single-year ages into the age band. |
| Age mortality | `age_band` | Project-standard five-year age band: `0-4`, `5-9`, ..., `80+`. |
| Age mortality | `deaths` | All-cause death count. |
| Age mortality | `mortality_rate_per_100k` | All-cause death rate per 100,000. The `0-4` and `80+` rates are recomputed from KOSIS sub-band deaths and rates. |
| Population projection by age | `age_band` | Project-standard five-year age band: `0-4`, `5-9`, ..., `80+`. |
| Population projection by age | `population_projected` | Projected resident population count after summing KOSIS 80+ sub-bands. |
| Indicator files | `indicator_code` | KOSIS item code. |
| Indicator files | `indicator` | KOSIS item label with HTML breaks removed. |
| Indicator files | `value` | Numeric KOSIS value; counts and percentages are both retained as published. |
| Foreign residents | `resident_category_code` | KOSIS foreign-resident category code. |
| Foreign residents | `resident_category` | KOSIS foreign-resident category label. |
| Foreign residents | `measure_code` | KOSIS measure code. |
| Foreign residents | `measure` | KOSIS measure label. |
| Foreign residents | `population` | Foreign-resident count. |
| Classified indicator files | `source_table_id` | KOSIS source table ID. |
| Classified indicator files | `source_table_name` | KOSIS source table title. |
| Classified indicator files | `area_code` | Published area code; provider-specific NHIS regional codes are retained as published. |
| Classified indicator files | `area_name` | Published area name. |
| Classified indicator files | `category1_code`, `category2_code`, `category3_code` | Published category codes. |
| Classified indicator files | `category1`, `category2`, `category3` | Published category labels. |
| Classified indicator files | `measure_code` | KOSIS item/measure code. |
| Classified indicator files | `measure` | KOSIS item/measure label. |
| Classified indicator files | `value` | Numeric value retained in published units. |

Suppressed or missing KOSIS count markers, including `*` and `X`, are
normalized to blank CSV cells, not zero.

## Geography and analytical cautions

- National and province aggregates are deliberately retained. Filter on
  `geography_level` before constructing a district panel to avoid double
  counting.
- Published codes and boundaries change over time. Harmonize geography before
  longitudinal joins or spatial modeling; equal-looking names are not enough.
- Sejong is labeled `district_equivalent` by the collector.
- Monthly mortality is all-cause. Public district-level cause-specific
  mortality in this collection is annual, so it cannot support monthly
  cause-specific inference.
- The collector found an all-cause district × sex × five-year-age mortality
  table (`DT_1B80A18`). It did not find a public KOSIS table that jointly
  publishes cause × district × age; using national or province age-cause
  structures for districts would be a methodological approximation that should
  be documented separately.
- District-level KOSIS population projections by age (`DT_1BPB002E`) cover
  2022–2042. A 2050+ aging decomposition would need another projection source
  or an explicitly documented extrapolation.
- KOSIS does not publish race in the US Census sense. The foreign-resident
  composition table is an aggregate nationality/migration-status proxy, not a
  race measure.
- Fiscal independence is a local-government finance proxy. It is useful for
  socioeconomic adjustment but is not household income, wealth, or deprivation.
- NHIS regional medical coverage, provider, workforce, and premium tables are
  split by broad Korean regions in KOSIS. They should be appended before
  analysis and may use provider-specific area codes rather than the mortality
  table's administrative codes.
- One-person household, elderly-living-alone, and housing indicators have
  sparse census-style early years, but the collector uses their continuous
  annual API series for the default panel.
- Population coverage begins ten years later than mortality coverage. A
  population-offset analysis therefore starts in 2011 unless another
  documented denominator source is added.
- The files contain aggregate statistics and no person-level records, but
  users should still follow the source terms and applicable disclosure rules.

## Reproduction

Request a free KOSIS OpenAPI key and place it in the untracked `.env` file:

```dotenv
KOSIS_API_KEY=...
```

From the project root, run:

```bash
make scrape-health PYTHON_INTERPRETER=.venv/bin/python
```

To collect only the demographic and socioeconomic covariates:

```bash
make scrape-demographics PYTHON_INTERPRETER=.venv/bin/python
```

To collect the additional social determinants and healthcare-access covariates:

```bash
make scrape-social-determinants PYTHON_INTERPRETER=.venv/bin/python
```

Change `HEALTH_START_YEAR` and `HEALTH_END_YEAR` to request another range. The
collector reuses existing annual JSON snapshots unless `--overwrite` is passed
directly to the Python entry point:

```bash
PYTHONPATH=src .venv/bin/python -m nzk_aphiam.data.scrape.health.kosis \
  --start-year 2001 --end-year 2024
```

## Source and provenance

- Provider: National Data Office KOSIS
- API: `https://kosis.kr/openapi/Param/statisticsParameterData.do`
- KOSIS OpenAPI information: `https://kosis.kr/openapi/`
- Source catalog and access dates: `docs/references/data_sources.csv`
- Machine-readable snapshot metadata: `data/raw/health/kosis/metadata.json`

Raw data are not committed to Git. Share or archive the data together with
`metadata.json` so checksums and year-level provenance remain attached.
