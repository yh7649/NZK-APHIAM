# Net-Zero Korea: Air Pollution and Health IAM

<a target="_blank" href="https://cookiecutter-data-science.drivendata.org/">
    <img src="https://img.shields.io/badge/CCDS-Project%20template-328F97?logo=cookiecutter" />
</a>

Integrated Assessment Model for Air Pollution and Health Impact of Korea's National Decarbonization

## RStudio Analysis

Open `NZK-APHIAM.Rproj` in RStudio to work from the project root.

R analysis files are organized as:

```text
analysis/
├── R/            <- Shared R helper functions
└── setup.R       <- Installs packages required by the notebooks

notebooks/r/      <- R Markdown analysis notebooks
```

Install the notebook dependencies with:

```bash
make r-requirements
```

The first notebook checks the locally scraped Western Power dataset:

```text
notebooks/r/01-western-power-raw-check.Rmd
```

Data remains local under `data/` and is ignored by Git.

## Southern Power Data

Add your data.go.kr API key to `.env`:

```dotenv
DATA_GO_KR_API_KEY=...
SOUTHERN_POWER_EMISSIONS_API_URL=https://api.odcloud.kr/api/15099713/v1/uddi:e7ea7bfd-d0c4-4cb6-afea-95fa7821cb51
SOUTHERN_POWER_GENERATION_API_URL=http://apis.data.go.kr/B552520/GenInfo/getDataService
```

Download the complete emissions or daily generation datasets:

```bash
PYTHONPATH=src python -m nzk_aphiam.data.scrape.thermal.southern_power emissions
PYTHONPATH=src python -m nzk_aphiam.data.scrape.thermal.southern_power generation
```

Raw source responses, CSV extracts, and redacted request metadata are saved under
`data/power_generation/thermal/raw/southern_power/`.

## South-East Power Data

South-East Power publishes its daily air-pollutant data through a signed CSV
export form on its website rather than a data.go.kr API:

```bash
PYTHONPATH=src python -m nzk_aphiam.data.scrape.thermal.southeast_power
```

The command downloads calendar-year chunks, preserves each original CP949
response, writes one combined UTF-8 CSV for analysis, and saves request metadata under
`data/power_generation/thermal/raw/southeast_power/`.

Resume an interrupted run from preserved yearly source files with
`--reuse-existing-source`.

Although data.go.kr advertises history from 2015, the provider's daily export
currently begins on July 16, 2020. The requested and actual coverage dates are
both recorded in metadata.

## Project Organization

```
├── LICENSE            <- Open-source license if one is chosen
├── Makefile           <- Makefile with convenience commands like `make data` or `make train`
├── README.md          <- The top-level README for developers using this project.
├── data
│   ├── external       <- Data from third party sources.
│   ├── interim        <- Intermediate data that has been transformed.
│   ├── processed      <- The final, canonical data sets for modeling.
│   └── raw            <- The original, immutable data dump.
│
├── docs               <- A default mkdocs project; see www.mkdocs.org for details
│
├── models             <- Trained and serialized models, model predictions, or model summaries
│
├── notebooks          <- Jupyter notebooks. Naming convention is a number (for ordering),
│                         the creator's initials, and a short `-` delimited description, e.g.
│                         `1.0-jqp-initial-data-exploration`.
│
├── pyproject.toml     <- Project configuration file with package metadata for 
│                         net_zero_korea:_air_pollution_and_health_iam and configuration for tools like black
│
├── references         <- Data dictionaries, manuals, and all other explanatory materials.
│
├── reports            <- Generated analysis as HTML, PDF, LaTeX, etc.
│   └── figures        <- Generated graphics and figures to be used in reporting
│
├── requirements.txt   <- The requirements file for reproducing the analysis environment, e.g.
│                         generated with `pip freeze > requirements.txt`
│
├── setup.cfg          <- Configuration file for flake8
│
└── net_zero_korea:_air_pollution_and_health_iam   <- Source code for use in this project.
    │
    ├── __init__.py             <- Makes net_zero_korea:_air_pollution_and_health_iam a Python module
    │
    ├── config.py               <- Store useful variables and configuration
    │
    ├── dataset.py              <- Scripts to download or generate data
    │
    ├── features.py             <- Code to create features for modeling
    │
    ├── modeling                
    │   ├── __init__.py 
    │   ├── predict.py          <- Code to run model inference with trained models          
    │   └── train.py            <- Code to train models
    │
    └── plots.py                <- Code to create visualizations
```

--------
