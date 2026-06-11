# Analysis

RStudio-facing analysis code lives here.

- `R/`: Shared R helpers used by notebooks and analysis scripts.
- `render.R`: Renders the current Western Power notebook from the command line.
- `setup.R`: Installs the notebook dependencies.
- `../notebooks/r/`: R Markdown notebooks for exploratory analysis.

Data files are intentionally not tracked by Git. Notebooks should read from `data/`
when the relevant local scrape has been run.
