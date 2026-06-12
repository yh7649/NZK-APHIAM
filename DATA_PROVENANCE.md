# Data Provenance and Licensing

## Repository Scope

The MIT license in `LICENSE` applies to the software and documentation created
for this repository. It does not grant rights to third-party source data.

Raw and generated datasets under `data/` are intentionally ignored by Git.
Users reproduce them locally from the original providers using the repository's
scrapers, cleaners, and processing commands.

## Source Data

Current thermal-power sources include data.go.kr datasets and official power
subsidiary websites. Each scraper preserves source responses and writes
request metadata beside its raw outputs. Dataset names, source URLs, retrieval
parameters, and enrichment sources are documented in those metadata files and
in `README.md`.

Fuel classifications and other documented enrichments are recorded under
`references/thermal/`, including the evidence, source URL, and access date for
each mapping rule.

## Derived Data

Interim datasets retain source-specific values and units. The processed thermal
dataset combines the currently compatible monthly mass-emissions datasets,
standardizes pollutant mass to kilograms, and writes a variable dictionary
beside the output.

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
