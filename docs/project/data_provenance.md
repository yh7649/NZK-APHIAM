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
