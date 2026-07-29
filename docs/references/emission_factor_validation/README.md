# KEPCO Emission-Factor Validation References

This directory contains the tracked reference data used by the offline KEPCO
emission-factor validation workflow:

- `literature_catalog.csv` inventories the sources.
- `literature_benchmarks.csv` preserves transcribed numeric values in long form.
- `literature_plant_crosswalk.csv` records reviewed project-to-literature plant
  and unit boundaries. Production code does not fuzzy-match boundaries.
- `literature_comparison_rules.csv` explicitly authorizes each quantitative
  comparison or records why it is contextual/noncomparable. A shared fuel or
  technology label is never a matching rule.
- `literature_pdf_inventory.csv` records each local PDF and checksum.
- `korea_ef_references/` stores the reviewed PDFs. Runtime validation is offline.

The project annual factor remains:

```text
EF = sum(matched monthly pollutant mass kg) / sum(matched monthly generation MWh)
```

Missing emissions are not zero, and annual factors are never arithmetic means of
monthly ratios. A paper-specific annualization can be reproduced only as a
separate source-method diagnostic.

> Direct Korean literature providing realized, pollutant-specific kg/MWh emission factors by fuel, technology and year is limited. Therefore, the workflow distinguishes exact plant-level validation from aggregate checks, methodological precedents and noncomparable engineering factors.

Sparse direct literature is itself a result. `literature_coverage_matrix.csv`
exposes the gap; the workflow does not weaken plant, unit, year, fuel,
technology, pollutant, mass-boundary, generation-denominator, temporal-coverage,
or normalization criteria to manufacture comparisons.

## Comparison classes

- `A_exact_reproduction`: same plant, units, year, pollutant, reporting boundary,
  denominator, and complete temporal coverage.
- `B_plant_pipeline_validation`: same plant/unit boundary and year, with
  emissions or generation from an external pipeline.
- `C_aggregate_consistency_check`: compatible year/fuel fleet aggregation, but
  not an exact plant comparison.
- `D_contextual_benchmark`: relevant context without a sufficient direct match.
- `X_not_comparable`: incompatible units, normalization, pollutant definition,
  or scope.

Only A and B are labeled **Plant-level external validation**. C is labeled
**Aggregate consistency check**. D and X receive no ordinary percent error and
are labeled **Methodological precedent**, **Engineering/contextual benchmark**,
or **Not directly comparable** as appropriate. PM2.5 remains PM2.5 and is never
matched to TSP.

The source benchmark type remains separate from the comparison class:
`direct_output_ef`, `derivable_output_ef`, `input_based_ef`,
`supporting_measurement`, and `secondary_report` describe what a source reports,
not whether a project match is valid.

## Source-specific treatment

Lee et al. (2025), `doi:10.5572/KOSAE.2025.41.6.976`, is the primary class B
source. Table 1 provides 2022 generation and NOx, SOx, and TSP mass for exact
coal plant groups. Lee uses annual CleanSYS emissions and EPSIS generation; the
project uses its KEPCO monthly pipeline, so this is external pipeline validation,
not identical-data replication. Generation and pollutant mass are reconciled
before EF. A pollutant with incomplete expected unit-month coverage is moved to
class D with `comparison_status=excluded_coverage_mismatch`, and its ordinary
percent difference is suppressed. Dangjin remains the regression fixture showing
that formula and unit conversions agree when the inputs align.

KEEI Table 3-17 can be evaluated only against its exact plant/unit group, 2016
year, and combined `NOx+SOx+TSP` definition. It never matches an individual
pollutant or generic fuel-technology group. Unresolved combined-cycle unit IDs
and insufficient historical fuel detail are explicit exclusions.

MOTIE's 2019 clarification provides 2017 national coal and LNG fleet averages.
The workflow constructs at most one ratio-of-sums KEPCO value per year, fuel,
pollutant, and analysis variant across all technologies. It does not repeat coal
against steam and IGCC or LNG against CHP and combined cycle. These class C rows
have `operator_coverage=kepco_subsidiaries_only` and are not national validation.

Seo, Kim, and Jeon (2019), `doi:10.7849/ksnre.2019.9.15.3.085`, reports HFO and
bio-heavy-oil results for two anonymous 75 MW oil-steam units. It is class D
**Methodological precedent** only. A future quantitative match requires the exact
plant, exact unit, 2015--2017 observations, effective-dated fuel classification,
and matching paper annualization method.

CAPSS Manual VII and Yu et al. (2021), `doi:10.5572/ajae.2021.104`, are class X
fuel-input references. They remain engineering and independent field-measurement
context but are not converted to kg/MWh without separately documented heating
value, heat rate, fuel composition, and control-efficiency assumptions.

The Solutions for Our Climate biomass report is secondary evidence. It is class
D unless an exact plant, unit boundary, year, and pollutant are documented and
reviewed.

Historical matching uses dated fuel and technology values on project unit-month
observations. If a literature year has multiple or missing classifications for a
reviewed unit boundary, the match is excluded with
`historical_fuel_mapping_unresolved`; HFO, bio-heavy oil, diesel, and mixed-fuel
units are never silently pooled.

## Generated tables

`make validate-kepco-emission-factors` replaces superseded outputs with:

- `direct_validation_comparisons.csv` (A/B only);
- `aggregate_consistency_checks.csv` (C only);
- `contextual_literature_benchmarks.csv` (D, no ordinary percent difference);
- `rejected_or_noncomparable_comparisons.csv` (machine-readable reasons);
- `plant_input_reconciliation.csv` (Lee generation and mass before EF); and
- `literature_coverage_matrix.csv` (fuel × technology × year × pollutant ×
  comparison class).

Kim et al. (2025), `doi:10.1016/j.scitotenv.2025.179430`, remains cataloged as
supporting independent SO2 measurement evidence; no annual kg/MWh value is
invented from the abstract-only source.
