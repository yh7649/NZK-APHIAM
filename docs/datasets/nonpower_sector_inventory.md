# Non-power sector inventory

## Scope

This dataset is the version-controlled framework for joining annual
GCAM-KAIST non-power activity to Korean CAPSS emission-factor categories. It
contains taxonomy, source leads, pollutant aliases, legal EF denominators,
crosswalk decisions, and a provisional first-pass emission-factor evidence
collection. It does **not** contain production-ready factors or calculated
emissions.

Method and boundary details are in the discoverable reference guide:
[`docs/references/nonpower_emissions/README.md`](../references/nonpower_emissions/README.md).

## Inputs

All build inputs are tracked CSVs under
`docs/references/nonpower_emissions/`:

- `gcam_kaist_nonpower_sector_inventory.csv`
- `gcam_capss_nonpower_crosswalk.csv`
- `nonpower_ef_denominator_registry.csv`
- `nonpower_source_registry.csv`
- `pollutant_registry.csv`
- `nonpower_emission_factors.csv`
- `nonpower_ef_inventory_mapping_rules.csv`
- `capss_vii_review_map.csv`
- `capss_vii_nonpower_scrape_targets.csv`
- `non_mass_normalized_evidence.csv`
- `nonpower_ef_collection_gaps.csv`

The inventory's `gcam_*` labels are provisional conceptual labels because the
team-supplied non-power GCAM-KAIST activity file is not currently present.
`conceptual_activity` and `gcam_label_status` keep that limitation
machine-readable.

## Commands

Validate only the tracked inputs:

```bash
make validate-nonpower-sector-inventory
make validate-nonpower-emission-factors
```

Validate and export canonical data plus diagnostics:

```bash
make build-nonpower-emissions
make scrape-capss-vii-nonpower-efs
```

The equivalent module interface is:

```bash
PYTHONPATH=src python -m nzk_aphiam.data.process.nonpower_sector_inventory
PYTHONPATH=src python -m nzk_aphiam.data.process.nonpower_emission_factors
PYTHONPATH=src python -m nzk_aphiam.data.scrape.capss.nonpower_emission_factors
```

Structural errors return a nonzero exit code. A deliberately unresolved
research mapping creates a warning and diagnostic row, not a build failure.

## Outputs

Canonical ID-sorted Parquet files are written to
`data/processed/nonpower_emissions/`:

- `gcam_kaist_nonpower_sector_inventory.parquet`
- `gcam_capss_nonpower_crosswalk.parquet`
- `nonpower_ef_denominator_registry.parquet`
- `nonpower_source_registry.parquet`
- `pollutant_registry.parquet`
- `nonpower_sector_inventory.metadata.json`
- `nonpower_emission_factors.parquet`
- `nonpower_emission_factor_inventory_links.parquet`
- `non_mass_normalized_evidence.parquet`
- `nonpower_emission_factors.metadata.json`

Metadata records inventory/schema versions, the Git commit when available,
input checksums, a reproducible input-keyed timestamp, output filenames, and
row counts. Generated data remains ignored by Git.

Human-readable diagnostics are written to
`results/diagnostics/nonpower_emissions/`:

- `inventory_validation_summary.json`
- `inventory_validation_issues.csv`
- `unresolved_crosswalks.csv`
- `missing_activity_sources.csv`
- `missing_ef_denominators.csv`
- `direct_emissions_boundary_issues.csv`
- `ef_collection_validation_summary.json`
- `ef_collection_validation_issues.csv`
- `nonpower_ef_inventory_coverage.csv`
- `nonpower_ef_inventory_gaps.csv`
- `nonpower_ef_sector_coverage.csv`
- `nonpower_ef_collection_gaps.csv`

Generated diagnostics remain ignored by Git. Review unresolved mappings and
double-counting risks before downstream use.

## Validation

The processor checks required columns, enums and booleans; stable unique IDs;
cross-file inventory/source keys; pollutant aliases and canonical pollutants;
P1 activity/source/denominator/crosswalk coverage; duplicate or contradictory
crosswalk targets; electricity-only direct-emissions boundaries; legal
activity/EF unit joins; and aggregate mappings incorrectly labeled `exact`.

The factor-evidence validator additionally checks factor modes and ranges,
canonical pollutants, source foreign keys, version/review state, the production
block on superseded CAPSS VI factors, exactly one mapping rule per evidence row,
candidate inventory IDs, official-VII review targets, and registered
pollutant-specific denominators. The current 912 factor records expand to 2,067
candidate links across 41 inventory activities. Missing candidate denominators
remain warnings and diagnostics, never zeros.

Tests also prove that unresolved mappings remain nonfatal, every required
output is generated, ID ordering is stable, and two builds from identical
inputs are byte-identical.

## Relationship to `macro_input_integration.md`

The existing [MACRO input integration](macro_input_integration.md) is preserved
as a provisional fallback and validation workflow. It currently:

1. accepts one GCAM sector and one fuel key per activity row;
2. optionally applies a one-to-one four-column sector/fuel mapping;
3. aggregates CAPSS emissions to one selected sector/fuel level;
4. divides one base-year CAPSS total by one base-year activity total; and
5. applies that aggregate intensity to projected activity.

Those assumptions cannot represent process versus combustion sources,
technology/fleet/control weighting, source-specific physical denominators, or
one GCAM activity mapping to several CAPSS components. The new inventory does
not replace that code yet. It adds stable compatibility fields and documents a
migration path:

1. ingest and inspect the native GCAM-KAIST non-power taxonomy;
2. replace provisional `gcam_*` labels while retaining stable `inventory_id`;
3. extract raw factors into tables keyed by `inventory_id`, pollutant,
   denominator, technology, fuel, control status, and source;
4. build annual effective factors from explicit scenario shares; and
5. join effective factors to annual activity, while retaining the old CAPSS
   aggregate intensity only as a labeled fallback/validation result.

The header-only legacy file
`docs/references/macro/gcam_capss_sector_fuel_mapping.csv` keeps the current
documented command runnable without asserting nonexistent native mappings.

## Current limitations

No production emissions calculation should use these files alone. All 887
imported CAPSS Handbook VI rows were transcribed from a secondary mirror and
are marked `superseded_pending_capss_vii_diff`; all 25 Korean literature rows
remain validation candidates. `production_ready=false` for all 912 rows.

The official 412-page Handbook VII PDF is locally checksum-verified. The first
inventory-driven scrape extracts 327 unique PDF pages for 83 activities and
indexes 125 factor or particulate-speciation tables. Its page text, index,
coverage, and metadata are generated under
`data/interim/nonpower_emissions/capss_vii_first_pass/` and ignored by Git.
The only activities without a direct target are electric passenger rail,
electric freight rail, and electrolytic hydrogen because their upstream power
emissions are outside this non-power boundary.

Remaining requirements include native GCAM label confirmation, Handbook VII
row normalization and review, activity-unit conversion parameters,
technology/fleet/control shares, restricted ship-factor access, and resolution
of the gaps listed in the reference README. Missing or unresolved factors are
not zero.

The recommended next task is: **normalize and independently verify the indexed
Handbook VII tables, then approve only unit-compatible rows for production.**
