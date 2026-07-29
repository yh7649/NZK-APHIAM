# Archived Midland concentration/flow pipeline

## Status

This pipeline was superseded on 22 July 2026. Korea Midland Power (KOMIPO)
supplied monthly NOx, SOx, and TSP mass in kilograms for January 2024 through
December 2025, so the active pipeline no longer estimates Midland mass from
concentration and flue-gas flow.

The old code was retained for research provenance under:

```text
src/nzk_aphiam/archive/kepco_midland_concentration/
```

It includes the former aggregate monthly-emissions scraper, facility-specific
air-status scrapers, and mass-estimation cleaner. It is not called by active
Makefile targets or by the KEPCO combiner.

## Why it was replaced

The public monthly emissions endpoint contained concentration summaries but no
flue-gas flow. Separate facility-status sources exposed both fields only for a
subset of plants, requiring approximate molecular-weight conversions and
leaving Boryeong, Seoul, and Shin-Boryeong without usable mass estimates. The
direct provider workbook reports mass itself and covers all seven workbook
sites, so it is authoritative for its 2024--2025 coverage window.

## Archived execution

Archived commands must be invoked explicitly and write generated data beneath
ignored `data/archive/` directories:

```bash
PYTHONPATH=src python -m nzk_aphiam.archive.kepco_midland_concentration.scrape emissions --overwrite
PYTHONPATH=src python -m nzk_aphiam.archive.kepco_midland_concentration.scrape facility-status --overwrite
PYTHONPATH=src python -m nzk_aphiam.archive.kepco_midland_concentration.cleaner
```

These commands require the same historical API credentials and endpoint access
as the former active modules. Their output must not be mixed with direct
provider-reported mass without an explicit, documented analytical decision.

## Active replacement

The active cleaner reads the checksum-verified provider workbook under
`data/raw/kepco_subsidiaries/midland_power/provider_responses/`, aggregates its
stack/outlet rows to the matching KOMIPO generation subtotals, and joins the
existing public monthly-generation file one-to-one. See
[`src/nzk_aphiam/data/README.md`](../../src/nzk_aphiam/data/README.md#midland-power).
