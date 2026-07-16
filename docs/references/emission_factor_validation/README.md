# KEPCO Emission-Factor Validation References

This directory contains the small tracked reference tables used by the offline
KEPCO plant emission-factor validation workflow:

- `literature_catalog.csv` records each source and whether it is a direct
  `kg/MWh` comparator.
- `literature_benchmarks.csv` stores transcribed numeric benchmark values in
  long format.
- `literature_plant_crosswalk.csv` records the reviewed project-to-literature
  plant and unit boundaries. The production workflow does not fuzzy match.

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

Yu et al. (2021), `doi:10.5572/ajae.2021.104`, and Kim et al. (2025),
`doi:10.1016/j.scitotenv.2025.179430`, are cataloged as supporting measurement
context, but they are not direct annual `kg/MWh` comparators.
