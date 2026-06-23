# Analysis

`kepco/kepco_monthly_analysis.R` is the main RStudio analysis workspace. It loads and
validates the combined monthly dataset, applies variable labels, creates kg/MWh
emission-factor columns, defines output paths, and provides helpers for saving
tables, figures, R objects, and models under `results/`.

Shared path helpers live in `R/`. Dataset merging, schema validation, and unit
standardization are handled in Python by `make combine-kepco`; R is reserved
for analysis.

Open `NZK-APHIAM.Rproj` and work through `kepco/kepco_monthly_analysis.R`
interactively, or run the complete setup from the terminal with:

```bash
make r-analysis
```
