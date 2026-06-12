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

Run every thermal subsidiary scraper sequentially with:

```bash
make scrape-thermal
```

This is a **networked** workflow: it contacts data.go.kr and subsidiary
websites and replaces the reproducible raw outputs with a fresh download.
Midland Power is included even though its emissions data is not currently
sufficient for monthly emission-factor calculations. The command stops if any
scraper fails. Individual subsidiary and dataset targets are available through
`make help`.

For a fully local check using preserved raw files, run:

```bash
make verify-offline PYTHON_INTERPRETER=.venv/bin/python
```

This performs formatting and lint checks, runs the complete Python test suite,
checks every scraper command-line entry point with `--help`, and rebuilds all
currently implemented interim datasets. It does not access the internet.

## Western Power Cleaner

Clean the preserved Western Power monthly source without modifying the raw
files:

```bash
make clean-western-power
```

The output is written to
`data/power_generation/thermal/interim/western_power/western_power_monthly_generation_emissions.csv`.
It retains every source row and uses the shared thermal schema: monthly date,
English plant name, nullable unit number, subsidiary, energy type, generation,
capacity, pollutant mass with an explicit unit column, nullable temperature,
and the original Korean plant/unit labels and note. Western Power reports
pollutant mass in metric tonnes and does not report temperature.

The shared interim schema includes nullable `plant_opening_date` and
`plant_closing_date` columns. They are intentionally blank at present. These
reserved fields must only be populated from documented sources; cleaners must
not infer them from the first or last observation in a raw dataset.

Nullable `plant_latitude` and `plant_longitude` columns are also reserved for
the plant metadata dataset being collected separately. They are intentionally
blank for now. Future coordinates should use WGS84 decimal degrees
(`EPSG:4326`), with latitude in `plant_latitude` and longitude in
`plant_longitude`. Coordinates should represent the plant site consistently,
not individual stacks or generating units, unless that convention is changed
and documented for every subsidiary.

The raw Western Power file does not include fuel type. The cleaner enriches
`energy_type` from official Korea Western Power plant and operating-history
pages. The rule for each plant/unit, its effective dates, evidence, and source
URL are recorded in
[`references/thermal/western_power_energy_type_mapping.csv`](references/thermal/western_power_energy_type_mapping.csv).
Pyeongtaek steam units are classified as `oil_and_natural_gas` through
February 2020 and `natural_gas` from March 2020, following the documented start
of full-LNG operation on February 27, 2020.

## East-West Power Cleaner

Run `make clean-eastwest-power` to create
`data/power_generation/thermal/interim/eastwest_power/eastwest_power_monthly_generation_emissions.csv`.
The cleaner preserves every monthly source row and uses the shared thermal
schema. Fuel mappings and their official sources are recorded in
[`references/thermal/eastwest_power_energy_type_mapping.csv`](references/thermal/eastwest_power_energy_type_mapping.csv).
The East-West scraper also writes those enrichment source URLs into its raw
JSON and metadata outputs.

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

Clean and combine Southern's monthly emissions with monthly sums of its daily
generation:

```bash
make clean-southern-power
```

The output is written to
`data/power_generation/thermal/interim/southern_power/southern_power_monthly_generation_emissions.csv`.
Southern reports emissions in kilograms, which are retained without
conversion and identified by `emissions_mass_unit`. Daily gross generation is
summed and converted from kWh to MWh. Explicit fuel and source-granularity
rules are recorded in
[`references/thermal/southern_power_energy_type_mapping.csv`](references/thermal/southern_power_energy_type_mapping.csv)
and their official URLs are logged by both Southern scrapers.

Some Southern emissions rows are more detailed than generation records. The
cleaner aggregates Samcheok A/B stack rows to generating units and aggregates
combined-cycle components to plant level where a steam turbine is shared.
Generation is left null where the generation API has no safely matching
record; it is never fabricated or forward-filled.

Rebuild every cleaner currently implemented with:

```bash
make clean-thermal
```

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

## Midland Power Data

Midland Power exposes monthly generation and air-pollutant emissions through
data.go.kr XML APIs. They use the same `DATA_GO_KR_API_KEY` configured above:

```bash
PYTHONPATH=src python -m nzk_aphiam.data.scrape.thermal.midland_power generation
PYTHONPATH=src python -m nzk_aphiam.data.scrape.thermal.midland_power emissions
```

The commands retain source field names and values, save the XML responses plus
CSV extracts and redacted metadata under
`data/power_generation/thermal/raw/midland_power/`, and refuse to replace
existing outputs unless `--overwrite` is explicitly provided.

The API URLs default to the documented endpoints. Optional environment
overrides are `MIDLAND_POWER_GENERATION_API_URL` and
`MIDLAND_POWER_EMISSIONS_API_URL`.

The verified June 12, 2026 pull contains 4,424 generation records from January
2012 through May 2026 and 853 emissions records for five thermal plants.
The emissions API returns no records for December 2019, December 2020, or July
2023; the scraper preserves those source gaps rather than filling them.

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
