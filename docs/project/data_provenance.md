# Data Provenance and Licensing

## Repository Scope

The MIT license in `LICENSE` applies to the software and documentation created
for this repository. It does not grant rights to third-party source data.

Raw and generated datasets under `data/` are intentionally ignored by Git.
Users reproduce them locally from the original providers using the repository's
scrapers, cleaners, and processing commands.

## Source Data

Current sources include data.go.kr datasets, official power subsidiary
websites, AirKorea, KPX EPSIS, and the Korea Environment Corporation CleanSYS website.
Each scraper preserves source responses and writes request metadata beside its
raw outputs. Dataset names, source URLs, retrieval parameters, and enrichment
sources are documented in those metadata files and in `README.md`.

The machine-readable source catalog is
[`docs/references/data_sources.csv`](../references/data_sources.csv). It records
the provider, dataset, coverage, granularity, units, public page, data
endpoint, access date, and important scope limitations.

CleanSYS annual records are facility-level totals for pollutants measured by
stack TMS instruments. They do not represent every emission source at a
facility and do not identify individual generating units.

AirKorea annual archives contain finalized hourly monitoring-station
observations. The downloader preserves the provider ZIPs and records their
checksums. AirKorea uses `-999` for observations invalidated by equipment or
communications problems; these values are source missing-value codes, not
pollution concentrations. A year marked with an asterisk on the source page is
based on monthly-report statistics and may change during annual finalization.

KMA meteorology is retrieved from the official KMA API Hub using a private
project-local credential. Surface ASOS timestamps are KST; radiosonde,
stability-analysis, and Wind Profiler timestamps are UTC. Raw KMA fields are
preserved in immutable annual snapshots with checksums and request counts.
Processed weather partitions convert surface times to UTC, apply physical
bounds, derive vector wind components, and estimate mixing height and surface
inversions from radiosonde potential-temperature profiles. These derived
upper-air values are labeled estimates and are not interpolated or represented
as directly observed KMA variables.

The public-health baseline preserves annual KOSIS API responses for monthly
all-cause mortality, annual cause-specific mortality, and monthly resident
population. Mortality geography follows the deceased person's residence.
National and province aggregates remain in the normalized files with explicit
geography-level labels. District codes and boundaries can change over time and
must be harmonized before longitudinal spatial analysis. Death counts should
be modeled as counts with population exposure or `log(population)` offsets,
rather than converted only to crude rates.

ENV-INFO records are verified annual environmental disclosures. The scraper
retains individual-site records where the public site exposes them and extracts
NOx, SOx, and TSP mass in metric tonnes. Its power-sector industry category
also contains gas, steam, water, and other utilities, so records must be
matched to EPSIS before they are treated as electricity generators.

Western Power's annual generator-performance and Taean daily-generation files
are cross-check sources, not automatic monthly gap fills. Annual totals are too
coarse to distribute across months. The available Taean daily file overlaps
the combined monthly source but does not supply any missing unit-month in that
overlap. Neither source contains monthly pollutant mass. Missing monthly values
therefore remain missing unless a future source matches the same reporting
boundary and month directly.

**The annual, non-KEPCO plant-level panel and its EPSIS/ENV-INFO/CleanSYS
crosswalk are paused indefinitely.** The project's active scope is the KEPCO
thermal subsidiary monthly panel (see
[`docs/datasets/kepco_monthly_generation_emissions.md`](../datasets/kepco_monthly_generation_emissions.md)).
The annual-panel matching and source integration were judged too messy for
current research needs relative to a fuel-type and emissions-only KEPCO scope.
The code is preserved, not deleted, under
`src/nzk_aphiam/archive/annual_panel/` (scrapers for EPSIS, ENV-INFO, and
CleanSYS under `scrape/`; the crosswalk builder and annual-panel pipeline
under `process/`), and remains runnable through the Makefile targets marked
`[PAUSED: annual non-KEPCO panel]` (`make help` lists them). Generated raw,
interim, and processed data for this effort are not committed to Git and were
removed from local disk; they are fully reproducible by rerunning those
targets.

The thermal crosswalk retains scored alternatives and distinguishes automatic,
manual, probable, review, and unmatched records. Historical ENV-INFO IDs can
appear as multiple dated links for one physical plant after ownership or
company-name changes. Crosswalk acceptance establishes identity, not equal
equipment boundaries between emissions and generation.

Fuel classifications and other documented enrichments are recorded under
`docs/references/thermal/`, including the evidence, source URL, and access date for
each mapping rule.

Crosswalk aliases and manual links are recorded under `docs/references/crosswalk/`.
Every manual facility ID includes its role, evidence, source URL, and access
date. The builder reads these files directly; changing a decision therefore
changes a tracked input and its checksum rather than changing an undocumented
constant in Python.

Plant coordinates and commissioning/retirement dates begin with a project
teammate's secondary roster, preserved as received at
`docs/references/province_level_power.xlsx` (provenance and known
limitations documented beside it in
`docs/references/province_level_power_README.md`). Because it is a
teammate-compiled secondary dataset rather than an official source, it is
used as supporting evidence: each KEPCO plant was matched to it by hand, and
that matching is recorded with evidence in
`docs/references/crosswalk/plant_location_dates.csv`. Missing locations and
ambiguous identities were then resolved against official operator plant pages.
Coordinates use the centroid of each mapped OpenStreetMap plant footprint;
the operator address, operator URL, coordinate method, OpenStreetMap element,
and date evidence are recorded row by row in
`docs/references/crosswalk/plant_location_dates_official_evidence.csv`.
Cleaners join against the main crosswalk file, not either source directly.

## Derived Data

Interim datasets retain source-specific values and units. The processed KEPCO
monthly dataset combines the currently compatible monthly mass-emissions
datasets, standardizes pollutant mass to kilograms, and writes a variable
dictionary beside the output.

Derived outputs remain subject to the terms, attribution requirements, and
reuse restrictions of their underlying source datasets. Before redistributing
data or publishing an archive, review each provider's current license and terms
of use.

## Reproducibility

Use the commands documented in `README.md` to retrieve source data and rebuild
the derived datasets. Do not manually edit raw files. For a publication or
release, record the software version, retrieval date, source metadata, and any
provider-specific license in the accompanying methods or data-availability
statement.

### Raw snapshot versioning

The five KEPCO subsidiary scrapers (East-West, Western, Southern, South-East,
Midland) write their raw CSV output as immutable per-period snapshots
(`{dataset}.source.{period}.csv`, one file per calendar year) plus a combined
file in the same row shape every downstream cleaner already expects
(`{dataset}.csv`). This is implemented once, in
`src/nzk_aphiam/data/scrape/common/period_snapshot.py`, and used by every
subsidiary scraper rather than each one writing its own single ever-growing
file. A period file is only rewritten when its content actually changes; an
unchanged period produces no new file. If a source revises historic data
(not just appends new months), the scraper prints an explicit warning naming
the period and a sample of the changed rows, and records the same detail in
that scrape's `*.metadata.json` under `period_snapshots`, so a silent
correction never passes for a normal monthly update.

This is what makes [DVC](https://dvc.org) viable for archiving raw snapshots:
since each period is its own file, re-running a scraper after a source
appends new months only changes (and only re-stores) the newest period, not
the entire historic record. Track a fresh pull with:

```bash
make track-kepco-snapshots
```

This runs `dvc add` over each subsidiary's raw directory and stages the
resulting small pointer files for git; it does not push anywhere; no DVC
remote is configured yet. `git status` shows what changed before you commit,
and `dvc push` becomes available once a remote (Google Drive, S3-compatible
storage, etc.) is configured with `dvc remote add`.

A live scrape failing partway through never overwrites prior data: every
scraper only calls `save_period_snapshots()` after a fetch has fully
succeeded, so an interrupted or failed run leaves the previous successful
snapshot exactly as it was. There is deliberately no separate "fall back to
cache" code path; the safety property falls out of write order rather than
needing its own logic to maintain.

For the facility-level emission-factor inputs and crosswalk:

```bash
make reproduce-facility-crosswalk
make verify-facility-crosswalk-offline
```

The first command contacts providers. The second performs no network requests
and fails when preserved raw material is incomplete. Raw and generated data are
ignored by Git, so reproducibility is computational rather than archival:
providers can revise historical pages. Preserve the raw directories and their
checksum metadata with any published analysis snapshot.
