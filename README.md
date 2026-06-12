# Net-Zero Korea: Air Pollution and Health IAM

<a target="_blank" href="https://cookiecutter-data-science.drivendata.org/">
    <img src="https://img.shields.io/badge/CCDS-Project%20template-328F97?logo=cookiecutter" />
</a>

Integrated Assessment Model for Air Pollution and Health Impact of Korea's National Decarbonization

## Authorship and Citation

Yehyun Hong is the project creator, primary author, and maintainer. Yehyun is a
Princeton University Operations Research and Financial Engineering student in
the Class of 2028 and a research assistant for Net Zero Korea, a joint
Princeton University-KAIST collaboration. OpenAI Codex was used for coding and
documentation assistance under human direction and review; responsibility for
the research and released work remains with the human author.

If you use this repository, cite it using [`CITATION.cff`](CITATION.cff).
GitHub will expose this through its **Cite this repository** interface. See
[`AUTHORS.md`](AUTHORS.md) for contribution credit,
[`DATA_PROVENANCE.md`](DATA_PROVENANCE.md) for source-data and licensing
guidance, and [`RELEASING.md`](RELEASING.md) for tagged releases and Zenodo DOI
archiving.

## New Team Member Setup

These instructions assume macOS and Homebrew. Clone the repository, open a
terminal in the project directory, and install Python if it is not already
available:

```bash
brew install python
```

Create a project-specific virtual environment and install the Python
dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
make requirements PYTHON_INTERPRETER=.venv/bin/python
```

Create the local environment file:

```bash
cp .env.example .env
```

Add a valid data.go.kr API key to `DATA_GO_KR_API_KEY` in `.env`. Keep `.env`
private; it is ignored by Git.

Download the three monthly datasets currently used in the combined analysis:

```bash
make scrape-eastwest-power PYTHON_INTERPRETER=.venv/bin/python
make scrape-western-power PYTHON_INTERPRETER=.venv/bin/python
make scrape-southern-power PYTHON_INTERPRETER=.venv/bin/python
```

Clean and combine them:

```bash
make clean-eastwest-power PYTHON_INTERPRETER=.venv/bin/python
make clean-western-power PYTHON_INTERPRETER=.venv/bin/python
make clean-southern-power PYTHON_INTERPRETER=.venv/bin/python
make combine-thermal PYTHON_INTERPRETER=.venv/bin/python
```

Install R and RStudio if needed:

```bash
brew install r
brew install --cask rstudio
```

Open `NZK-APHIAM.Rproj` in RStudio and use
`analysis/manual_analysis.R` as the main analysis workspace. The project file
and R script are tracked in Git and do not need to be generated. From the
terminal, the same analysis setup can be checked with:

```bash
make r-analysis PYTHON_INTERPRETER=.venv/bin/python
```

## RStudio Analysis

Open `NZK-APHIAM.Rproj` in RStudio to work from the project root.

Python combines and standardizes the monthly East-West, Western, and Southern
datasets. R only loads the resulting processed dataset for analysis:

```bash
make r-analysis
```

The R entry point is `analysis/manual_analysis.R`, with shared path helpers
under `analysis/R/`. Generated figures, tables, analysis objects, and models are
written under `results/`. Data remains local under `data/` and is ignored by
Git. The RStudio project and analysis scripts are tracked source files, so they
are already present after cloning; `make r-analysis` rebuilds the combined
processed data before running the script.

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

## Combined Monthly Thermal Dataset

Combine the three interim datasets that currently report monthly pollutant
mass and generation:

```bash
make combine-thermal
```

This combines East-West, Western, and Southern Power into
`data/power_generation/thermal/processed/thermal_power_generation_emissions.csv`.
All input schemas are checked before concatenation. Generation remains in MWh,
capacity remains in MW, and NOx, SOx, and dust mass are standardized to
kilograms. East-West and Western values are converted from metric tonnes by
multiplying by 1,000; Southern values are already kilograms.

The processed monthly mass dataset omits oxygen, flue-gas flow, and temperature
fields because they are empty across all three included sources. Those fields
remain available in source-specific interim datasets where they are reported.

The same command writes
`thermal_power_generation_emissions_metadata.csv` beside the data. It contains
ordered `varname` and `label` fields for every column, with units included in
quantitative variable labels. The R analysis loader checks that this dictionary
matches the dataset and attaches the labels to the imported columns.

South-East is intentionally excluded because it reports daily concentrations
with undocumented concentration units rather than monthly pollutant mass.
Midland is excluded until the requested monthly raw emissions data are
available.

Load the combined data and calculate pollutant emission factors in R with:

```bash
make r-analysis
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

Clean the downloaded daily measurements with:

```bash
make clean-southeast-power
```

The output is written to
`data/power_generation/thermal/interim/southeast_power/southeast_power_daily_air_pollutant_measurements.csv`.
It preserves every plant-unit-day row and retains the reported NOX, SOX, dust,
oxygen, flue-gas flow, and temperature values. The export does not state the
pollutant concentration units or flue-gas-flow unit, so those unit fields are
marked `not_reported`. `emissions_mass_unit`, generation, capacity, and fuel
type remain null. Concentrations are not converted to mass because the source
does not document enough unit and operating-duration information for a
defensible conversion.

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
├── CITATION.cff       <- Machine-readable software citation
├── AUTHORS.md         <- Human authorship and AI-assistance disclosure
├── DATA_PROVENANCE.md <- Source-data, licensing, and reproducibility guidance
├── RELEASING.md       <- Versioning, GitHub release, and Zenodo instructions
├── LICENSE            <- MIT license for repository software and documentation
├── Makefile           <- Reproducible scrape, clean, combine, test, and analysis commands
├── analysis           <- Main R analysis workspace and shared R helpers
├── data               <- Local raw, interim, and processed data; ignored by Git
├── references         <- Documented mappings, evidence, and source references
├── results
│   ├── figures        <- Saved plots and graphics
│   ├── tables         <- Saved analysis tables
│   ├── objects        <- Serialized analysis objects
│   └── models         <- Trained and serialized models
├── src/nzk_aphiam     <- Python package for scraping, cleaning, and processing
└── tests              <- Python test suite
```
