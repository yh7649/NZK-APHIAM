# KEPCO Emission-Factor Validation References

This directory contains the small tracked reference tables used by the offline
KEPCO plant emission-factor validation workflow:

- `literature_catalog.csv` records each source and whether it is a direct
  `kg/MWh` comparator.
- `literature_benchmarks.csv` stores transcribed numeric benchmark values in
  long format.
- `literature_plant_crosswalk.csv` records the reviewed project-to-literature
  plant and unit boundaries. The production workflow does not fuzzy match.
- `literature_pdf_inventory.csv` records every local Korean EF reference PDF,
  its SHA-256 checksum, extraction status, source class, and comparator role.
- `korea_ef_references/` stores the reviewed PDFs. The validation workflow runs
  offline from the CSV transcriptions and does not download or parse PDFs at
  runtime.

The project KEPCO factors are calculated from the same monthly source lane as:

```text
EF = sum(matched monthly pollutant mass kg) / sum(matched monthly generation MWh)
```

Missing emissions are not treated as zero, and annual factors are never
arithmetic means of monthly ratios.

## Literature Classes

The reference data distinguish:

- `direct_output_ef`: the source directly reports kg/MWh.
- `derivable_output_ef`: the source reports emissions and generation, allowing
  kg/MWh to be recalculated.
- `input_based_ef`: the source reports fuel-input factors such as kg/tonne coal
  or kg/kL oil. These are not direct KEPCO kg/MWh comparators.
- `supporting_measurement`: the source validates measurement credibility but
  not annual kg/MWh factors.
- `secondary_report`: the source reproduces company, government-submission, or
  another study's values.

PM2.5 is stored as PM2.5 and is not matched to TSP.

## Priority Methodological Precedent

Seo, Kim, and Jeon (2019), `doi:10.7849/ksnre.2019.9.15.3.085`, is the closest
methodological precedent now tracked here. Table 3 reports annual kg/MWh values
for HFO and bio-heavy-oil generation in 2015, 2016, and 2017 for SOx, NOx, TSP,
and PM2.5. The paper uses CleanSYS monthly emissions and monthly generation for
two anonymized 75 MW oil power units, excluding months with replacement
measurements or fuel-switching operations. Because the plant identity and exact
generation technology are anonymized, the table is treated as a fuel-technology
methodological benchmark rather than a forced plant-level match; technology is
recorded as `unspecified_oil_thermal`.

The main numeric benchmark is Lee et al. (2025),
`doi:10.5572/KOSAE.2025.41.6.976`. Table 1 reports 2022 annual generation and
NOx, SOx, and TSP emissions for Korean coal plant complexes. The source table
reports emissions in tonnes; the CSV stores them as kilograms and the pipeline
recalculates the emission factors from mass divided by generation.

The Lee comparison is an external data-pipeline validation because it uses
published CleanSYS TMS annual emissions and EPSIS annual generation. It is not
a fully independent measurement benchmark.

The KEEI Table 3-17 values are historical 2016 combined `NOx+SOx+TSP` factors
from an external report using company-origin data. They are retained as
historical benchmarks only and are never compared to individual pollutants or
treated as same-year validation for 2022.

MOTIE's 2019 clarification provides 2017 national coal and LNG kg/MWh factors.
These are useful national fuel-level checks but are not plant or unit matches.

CAPSS Manual VII and Yu et al. (2021), `doi:10.5572/ajae.2021.104`, are
fuel-input references. They remain supporting engineering and field-measurement
benchmarks and are not converted to kg/MWh without documented heat rate,
heating value, sulfur content, and control-efficiency assumptions.

The Solutions for Our Climate biomass report is secondary evidence based on
company/National Assembly submissions. It is cataloged with provenance, but not
used as a strict validation observation.

Kim et al. (2025), `doi:10.1016/j.scitotenv.2025.179430`, is cataloged as
supporting independent SO2 measurement evidence where available, but no annual
kg/MWh values are invented from the abstract-only source.
