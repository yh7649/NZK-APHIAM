# Data Provenance and Licensing

## Repository Scope

The MIT license in `LICENSE` applies to the software and documentation created
for this repository. It does not grant rights to third-party source data.

Raw and generated datasets under `data/` are intentionally ignored by Git.
Users reproduce them locally from the original providers using the repository's
scrapers, cleaners, and processing commands.

## Source Data

Current sources include data.go.kr datasets, official power subsidiary
websites, KPX EPSIS, and the Korea Environment Corporation CleanSYS website.
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

ENV-INFO records are verified annual environmental disclosures. The scraper
retains individual-site records where the public site exposes them and extracts
NOx, SOx, and TSP mass in metric tonnes. Its power-sector industry category
also contains gas, steam, water, and other utilities, so records must be
matched to EPSIS before they are treated as electricity generators.

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
