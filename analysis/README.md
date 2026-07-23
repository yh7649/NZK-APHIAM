# Analysis

Dataset merging, schema validation, and unit standardization are handled in
Python by `make combine-kepco`. R and Stata are reserved for analysis only.

## R

`kepco/kepco_monthly_analysis.R` is the main RStudio workspace. It loads and
validates the combined monthly dataset, applies variable labels, creates kg/MWh
emission-factor columns, and provides helpers for saving tables, figures, and
model objects under `results/`.

`kepco/ef_eligibility.R` defines the shared pollutant-month eligibility rules
for the operational-primary, low-load-inclusive, and conservative-quality EF
specifications. Run `make test-kepco-ef-r` for its deterministic smoke tests.
`kepco/query_ef_cohort.R` applies those rules to user-selected time periods,
pollutants, fuels, technologies, provinces, and output groupings; run it with
`--help` to see the command-line interface and examples.

Shared path helpers live in `R/paths.R` — source it at the top of any R script.

## Descriptive plant-to-air-quality GWR

`gwr/plant_air_quality_gwr.R` compares global OLS with descriptive annual GWR
using 25/50/100 km distance-decayed KEPCO emissions indices. The exposure
kernel and adaptive bisquare GWR observation kernel are distinct. The indices
are not concentrations and the associations are not causal. See
`gwr/README.md`; run `make test-gwr-r` and `make gwr-plant-air-quality`.

Open `NZK-APHIAM.Rproj` and work through `kepco/kepco_monthly_analysis.R`
interactively, or run the complete setup from the terminal with:

```bash
make r-analysis
```

## Stata

Panel regressions, health impact models, DiD event studies, and
publication-ready tables are handled in Stata. Shell `.do` files live alongside
their R counterparts in `kepco/`.

Shared path helpers live in `stata/paths.do` — source it at the top of every
do file. It sets `$project_root`, `$kepco_processed_root`, `$results_root`, and
related globals. It detects the project root automatically (via the
`NZK_APHIAM_ROOT` env var or by walking up from cwd); no manual edits needed.

To run a do file from the terminal:

```bash
stata -b do analysis/kepco/kepco_panel.do
```

Or open interactively from within Stata after `cd`-ing to the project root.
