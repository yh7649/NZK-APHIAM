# Korean non-power emissions inventory references

## Purpose

These tracked CSVs define the sector taxonomy, activity denominators, source
leads, pollutant names, GCAM–CAPSS relationships, and provisional factor
evidence needed to calculate Korean direct non-power air-pollutant emissions.
Inventory version `0.2.0` and factor collection version `1.0.0` form a
populated research framework, not a production-ready emission-factor database.
Version 0.2.0 adds separate supplemental boundaries for commercial
meat-grilling aerosol and charcoal kilns, preventing food aerosol from being
silently assigned to commercial fuel-energy cooking. It also separates road
tire/brake wear from tailpipe emissions and paved-road resuspension.

The intended future calculation is:

```text
annual GCAM-KAIST activity
× raw technology/fuel/process emission factor
× annual technology, route, fleet, and control weights
= annual direct emissions
```

## Files

- `gcam_kaist_nonpower_sector_inventory.csv`: one row per distinct modeled or
  supplemental activity boundary.
- `gcam_capss_nonpower_crosswalk.csv`: one-to-many links to the native 2023
  CAPSS major/intermediate/minor taxonomy, including unresolved links.
- `nonpower_ef_denominator_registry.csv`: pollutant-specific legal activity–EF
  joins. It contains units and weighting requirements, not EF values.
- `nonpower_source_registry.csv`: official Korean activity/EF sources and
  Korean measured-emissions literature leads with access limitations.
- `pollutant_registry.csv`: canonical CAPSS pollutant names and aliases.
- `nonpower_emission_factors.csv`: 912 imported, mass-normalized candidate
  factors in long form, including numeric values, formulas, and ranges.
- `nonpower_ef_inventory_mapping_rules.csv`: explicit rules expanding every
  factor row to candidate inventory activities without inventing a one-to-one
  match.
- `capss_vii_review_map.csv`: official Handbook VII table targets for each
  source-table label in the supplied v1 collection.
- `capss_vii_nonpower_scrape_targets.csv`: inventory-linked official VII PDF
  page ranges used by the table extractor.
- `non_mass_normalized_evidence.csv`: six concentration, qualitative, or
  source-lead records that cannot be represented as mass-normalized factors.
- `nonpower_ef_collection_gaps.csv`: 11 explicit extraction and access gaps
  linked to affected inventory IDs.

Pipe (`|`) is the deterministic delimiter for list-valued fields such as
`required_pollutants`, aliases, compatible units, and source IDs.

## Imported collection and production gate

The user-supplied collection was adopted as evidence, not as an authoritative
default. Of its 912 factor rows, 887 were transcribed from CAPSS Handbook VI
(2023) through a secondary mirror. Handbook VII (2025) is the current official
methodology, so those rows are labeled
`superseded_pending_capss_vii_diff`. The remaining 25 rows are Korean
measurement-study candidates. Every row has `production_ready=false`.

The original review workbook and sector-coverage CSV are derived views and are
not duplicated in Git; the integrated build regenerates sector coverage under
`results/diagnostics/nonpower_emissions/`. The standalone uploaded scripts are
also superseded by
the package modules: the supplied builder depended on an unavailable notebook
session, while its useful validation, source-mapping, PDF-extraction, and build
behavior is now covered by repository code and tests.

Run the integrated workflow with:

```bash
make validate-nonpower-emission-factors
make scrape-capss-vii-nonpower-efs
make scrape-capss-vii-nonpower-efs-verified
make build-nonpower-emissions
```

The official VII extractor reads the locally preserved 412-page PDF, extracts
327 unique inventory-targeted pages, indexes 123 true factor or particulate-
speciation tables, and reconstructs 129 table occurrences including
continuations. The verified run confirmed that the local PDF is byte-identical
to the current official download (SHA-256
`fd84b21d6b0e54408e376ca027948a0355c65546d50a15b46ee0da1e08b7ed37`).

All reconstructed table cells are retained in
`capss_vii_nonpower_raw_tables.jsonl`. Standard pollutant-column tables produce
3,250 long-form factor candidates: 2,994 have aligned source labels and 3,144
have resolved physical units. Conservative native-CAPSS text matching links
2,720 candidates into 4,196 candidate links covering 54 inventory activities;
broad chapter membership alone is not accepted as a link. Formula-heavy road
appendices and other nonstandard tables remain available as raw cells pending
dedicated parsers. Every scraped candidate is
`production_ready=false`.

Generated page text, raw cells, normalized candidates, links, extraction
issues, coverage, and metadata live under
`data/interim/nonpower_emissions/capss_vii_first_pass/` and remain ignored by
Git. The target registry covers 86 direct-emission inventory activities.
Electric passenger/freight rail and electrolytic hydrogen intentionally have
no direct non-power target.

## Relationship to GCAM-KAIST and MACRO/NZK-APHIAM

GCAM-KAIST supplies annual scenario activity. The corresponding non-power
activity/taxonomy file is a restricted team deliverable and is not currently
present in `data/external/macro/`. Therefore, version `0.2.0` keeps the requested
conceptual activity in `conceptual_activity`, labels the `gcam_*` fields
`conceptual_pending_model_file`, and does not claim that those labels are
model-native. Once the file is supplied through `make ingest-macro-external`,
the model-native labels should be inspected and inserted without changing the
inventory schema.

The existing MACRO integrator derives a fallback base-year intensity from
aggregate CAPSS emissions divided by GCAM sector/fuel activity. That code is
unchanged. This inventory is the migration path to source-appropriate,
technology-specific factors. The legacy four-column mapping file at
`docs/references/macro/gcam_capss_sector_fuel_mapping.csv` is intentionally
header-only until native GCAM labels exist; passing it to the current integrator
preserves rows as unmapped rather than inventing a mapping.

## Direct-emissions boundary

The framework includes direct on-site combustion, mobile combustion, process,
and fugitive emissions. Purchased electricity never receives a direct
non-power factor. Electric passenger/freight rail and electrolytic hydrogen are
marked `electricity_only=true`, have `direct_emissions_scope=none_on_site`, and
use `not_applicable` crosswalk rows. Their upstream electricity emissions stay
in the power module. Process and combustion rows are separate where activity
permits, notably for steel, cement, chemicals, refining, and hydrogen.

Missing factors are never interpreted as zero. The inventory uses the explicit
research statuses `available`, `partially_available`, `proxy_required`,
`restricted_source`, `not_yet_researched`, `not_applicable`, and `excluded`.

## Raw versus annual effective factors

A raw factor belongs to a measured or documented technology and denominator,
for example `g NOx/vehicle-km`, `kg PM2.5/tonne EAF steel`, or
`kg NH3/animal-year`. An annual effective factor is derived from raw factors and
annual fleet, model-year, speed, route, fuel, process, and pollution-control
shares. It must not be manually entered as if it were a raw measurement. The
denominator registry flags temporal, technology, and control weighting needed
for that derivation.

## Sector inclusion and supplemental sources

The inventory covers industry, transport, buildings, agriculture and land,
waste, and non-power energy conversion. Sources important to air quality but
without a defensible energy-consuming GCAM cluster use
`gcam_cluster=air_quality_supplemental` and carry an explicit future scenario
driver. Solvents, construction and road dust, fuel-distribution losses, open
biomass burning, commercial cooking aerosol, and charcoal kilns are never
silently assigned to unrelated GCAM activity.

Rows are prioritized as follows:

- `P1`: MVP activity with a source lead, unit, EF basis, denominator, and CAPSS
  crosswalk or explicit unresolved record.
- `P2`: important extension requiring finer activity or mapping work.
- `P3`: retained lower-priority or highly uncertain research gap.

## Source hierarchy

1. Tier 1 official Korean sources: CAPSS/NIER, KESIS/KEEI, KOSIS,
   ministries, official portals, and official industry statistics.
2. Tier 2 Korean measured-emissions literature with physical denominators,
   measurement periods, technologies, controls, sample sizes, and methods.
3. Tier 3 international factors only when Korean factors are unavailable, with
   an explicit proxy rationale.

The source registry contains real provider or bibliographic URLs. A public
program record does not imply that the underlying dataset is public. The MOF
ship-factor program is therefore marked `restricted_source` pending access to
the factor records.

## Crosswalk match statuses

- `exact`: CAPSS major, intermediate, and minor categories and the modeled
  activity boundary align one-to-one. Similar wording alone is insufficient.
- `documented_proxy`: a defensible translation requires explicit allocation or
  technology weights.
- `aggregate_proxy`: the available CAPSS category pools incompatible modeled
  activities or vice versa.
- `unresolved`: a mapping question remains open and is retained in diagnostics.
- `excluded`: the source is outside this inventory boundary.
- `not_applicable`: no direct non-power emissions belong to the activity.

`double_counting_risk` and `boundary_note` identify overlapping process and
combustion sources, fishing vessels/fisheries energy, wastewater types, road
dust/tailpipe activity, fuel storage/distribution, and crop/open biomass
burning.

## Versioning

The semantic inventory version is stored in every inventory row and build
metadata, not only in filenames:

- patch: documentation or source-metadata correction;
- minor: new sectors, sources, denominators, or crosswalks;
- major: schema or modeling-boundary change.

Build metadata records schema and inventory versions, a reproducible input-keyed
build timestamp, Git commit when available, and SHA-256 checksums for all five
tracked inputs. Canonical tables are sorted by stable ID before export.

## Known gaps and next steps

The largest gaps are confirmed model-native GCAM-KAIST labels, chemical and
refinery flaring activity, cement grinding/fugitive dust, pulp recovery and
lime kilns, port and forestry machinery, aviation cruise allocation, route-
specific hydrogen process mappings, and public access to detailed ship-factor
data. Aggregate proxy rows also need physical annual allocation weights.

The next implementation task is: **write dedicated parsers for the formula-heavy
road, aviation-ground-equipment, and other nonstandard tables; then review
source labels, controls, units, and inventory denominators before approving any
rows for production.** Annual effective factors still belong downstream of
fleet, technology, route, and control weighting.
