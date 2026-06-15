# Annual Plant Generation and Emissions Method

## Objective

The pipeline produces one canonical row per Korean thermal plant and year,
where public source coverage permits, with annual gross generation, selected
NOx/SOx/TSP mass, source provenance, emission factors, and review flags.

Run the complete preserved-raw workflow with:

```bash
make reproduce-annual-plant-panel-offline PYTHON_INTERPRETER=.venv/bin/python
```

Outputs are written under `data/power_generation/annual_plant/`.

## Generation

The EPSIS annual roster defines canonical plant IDs and operating-year bounds.
Every EPSIS annual-generation row is retained in
`epsis_generation_row_audit.csv` and classified as `unit`, `plant_total`,
`company_total`, `fuel_total`, `regional_total`, `other_aggregate`, or
`unresolved`.

Assignment is deliberately conservative:

1. Apply documented rules from
   `references/annual_panel/generation_overrides.csv`.
2. Match the normalized plant label within the roster-valid year.
3. Use company identity to disambiguate duplicate plant names.
4. Permit a unique high-scoring fuzzy match only above the documented
   threshold and margin.
5. Leave all other rows unresolved.

For a plant-year, one explicit plant total is preferred. If there is no plant
total, valid unit rows are summed. Plant totals and component units are never
added together. Multiple plant totals are excluded for review.

Both gross and net generation are retained. The final panel uses gross
generation because it is the consistently populated EPSIS measure across the
study period. Emission factors therefore have a gross-generation denominator.

## Emissions

All candidates are standardized to kilograms:

- Direct subsidiary observations are already standardized to kilograms by the
  monthly thermal pipeline and are summed annually.
- CleanSYS reports kilograms per facility-year.
- ENV-INFO tonnes are multiplied by 1,000.

Direct subsidiary plant mappings are documented in
`references/annual_panel/direct_company_plant_links.csv`. CleanSYS and ENV-INFO
use the versioned EPSIS facility crosswalk.

The selection hierarchy is:

1. Direct subsidiary plant-level mass.
2. A unique, confidently matched CleanSYS facility.
3. A unique, confidently matched ENV-INFO individual site.

Sources are alternatives and are never added together. ENV-INFO representative
records, many-to-many facilities, probable links, and overlapping facility
sets remain in the candidate table but are not eligible for automatic
selection. A configurable relative disagreement threshold defaults to 50%.

## Validation

The processor rejects duplicate plant-year generation rows, duplicate selected
plant-year-pollutant rows, mixed unit and plant-total contributions, and
negative selected values. It retains but flags:

- extreme emission factors;
- more than fivefold year-to-year generation or emissions changes;
- source disagreements above the configured threshold;
- records outside roster operating years;
- ambiguous facility mappings.

EPSIS does not provide safely comparable thermal company totals in these
annual-generation extracts. Company-total exceedance validation therefore
records zero available comparisons instead of treating fuel or portfolio
aggregates as company benchmarks.

## Output Files

- `epsis_annual_plant_generation.csv`: accepted plant-year generation.
- `epsis_generation_row_audit.csv`: classification and disposition of every
  EPSIS annual-generation row.
- `epsis_generation_review.csv`: unresolved and low-confidence rows.
- `annual_emissions_candidates.csv`: every standardized source candidate.
- `annual_emissions_comparison.csv`: side-by-side source values and selection.
- `annual_plant_generation_emissions.csv`: final plant-year panel and factors.
- `metadata.json`: checksums, thresholds, counts, coverage, and validations.
