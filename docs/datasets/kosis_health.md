# KOSIS Public Health Baseline

## Overview

This collection provides the initial Korean district-level health baseline for
NZK-APHIAM. It contains mortality outcomes and population denominators from
three public KOSIS tables maintained by the National Data Office. Mortality is
reported by place of residence, not place of death.

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

The source mortality tables extend to 1997 and 1998 respectively. The current
project snapshot starts in 2001 to align with the AirKorea analysis window.
Although the population table advertises older annual history, its monthly API
series returns no data before 2011.

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
└── population/
    ├── population.csv
    └── raw/DT_1B040A3_<year>.json
```

The annual JSON files preserve the KOSIS responses. The CSV files are
deterministic normalized extracts. `metadata.json` is the machine-readable
provenance manifest and records retrieval time, coverage, row counts, relative
paths, reuse/download status, and SHA-256 checksums for every raw annual file
and normalized CSV.

Current normalized-file checksums:

| File | SHA-256 |
|---|---|
| `monthly_deaths/monthly_deaths.csv` | `f96974d5bd32484055e8c21b21aff4f56acf99e8c00dadf89aa5431f140228ad` |
| `cause_deaths/cause_deaths.csv` | `7e96cc7618fdaf8b1bc37348f1ee01e6ef0ee71f0a7f3d20b8b901455ffdf24c` |
| `population/population.csv` | `e3ccee16403d078465273465017855fe5a774b856f6580993995e3becebce0b8` |

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

Suppressed or missing KOSIS count markers are normalized to blank CSV cells,
not zero.

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
