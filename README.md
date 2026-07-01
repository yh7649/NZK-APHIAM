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
[`docs/project/authors.md`](docs/project/authors.md) for contribution credit,
[`docs/project/data_provenance.md`](docs/project/data_provenance.md) for source-data and licensing
guidance, and [`docs/project/releasing.md`](docs/project/releasing.md) for tagged
releases and Zenodo DOI archiving.

## New Team Member Setup

The project requires Python 3.11 or newer, Make, R, and optionally RStudio.
Install the platform prerequisites first.

### macOS

```bash
brew install python
brew install r
brew install --cask rstudio
```

### Ubuntu or Debian Linux

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip make r-base
```

Install [RStudio Desktop](https://posit.co/download/rstudio-desktop/) separately
from its official Linux installer if a GUI is desired. The R analysis can also
be run from the terminal with `Rscript`.

### Windows

The Makefile uses Unix shell syntax. The recommended Windows setup is
[Windows Subsystem for Linux (WSL2)](https://learn.microsoft.com/windows/wsl/install)
with Ubuntu. Install WSL from an administrator PowerShell window:

```powershell
wsl --install
```

Restart if prompted, open the Ubuntu terminal, and follow the Ubuntu/Debian
commands above. Run all `make` commands inside WSL.
[RStudio Desktop](https://posit.co/download/rstudio-desktop/) may be installed
on Windows for interactive analysis, or R can be run directly inside WSL.

Native Windows PowerShell is not currently a supported Make workflow because
commands such as `PYTHONPATH=src` and `.venv/bin/python` use POSIX conventions.

### Shared Project Setup

Clone the repository, open a terminal in its root directory, and create a
project-specific virtual environment:

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
make combine-kepco PYTHON_INTERPRETER=.venv/bin/python
```

Open `NZK-APHIAM.Rproj` in RStudio and use
`analysis/kepco/kepco_monthly_analysis.R` as the main analysis workspace. The project file
and R script are tracked in Git and do not need to be generated. From the
terminal, the same analysis setup can be checked with:

```bash
make r-analysis PYTHON_INTERPRETER=.venv/bin/python
```

## RStudio Analysis

The descriptive plant-emissions to monitor-air-quality baseline is implemented
in `analysis/gwr/plant_air_quality_gwr.R`. Once the upstream monthly AirKorea
QC Parquet and station-year crosswalk exist, run `make test-gwr-r` and
`make gwr-plant-air-quality`. It estimates non-causal annual spatial
associations with separate emissions-distance and adaptive GWR kernels. See
`analysis/gwr/README.md` for the 25/50/100 km sensitivity design, outputs, and
limitations.

Open `NZK-APHIAM.Rproj` in RStudio to work from the project root.

Python combines and standardizes the monthly East-West, Western, and Southern
datasets. R only loads the resulting processed dataset for analysis:

```bash
make r-analysis
```

The R entry point is `analysis/kepco/kepco_monthly_analysis.R`, with shared path helpers
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
Midland Power includes both the original monthly APIs and facility-status
datasets that can derive approximate pollutant mass where stack flow is
reported. Its cleaner aggregates the derived unit/turbine emissions to the
matching plant/technology subtotal before joining monthly generation, so the
same generation total is never repeated across components. The command stops
if any scraper fails. Individual subsidiary,
facility, and dataset targets are available through `make help`.

Each subsidiary's raw output is written as immutable per-year snapshot files
plus a combined file in the shape cleaners expect, so re-running a scraper
after a source adds new months only changes the newest year, not the whole
history. To version a fresh pull locally with DVC (no remote required):

```bash
make track-kepco-snapshots
```

See [`docs/project/data_provenance.md`](docs/project/data_provenance.md#raw-snapshot-versioning)
for how this works and how to add a remote later.

Official webpages and OpenStreetMap geometry supporting the plant location/date
crosswalk have their own offline archive. Refresh and track it locally with:

```bash
make archive-plant-location-references PYTHON_INTERPRETER=.venv/bin/python
make track-plant-location-references DVC=.venv/bin/dvc
```

The second command updates a small Git-tracked `.dvc` pointer. Once a shared
DVC remote is configured, `dvc push` publishes the archived source bodies and
`dvc pull` restores them for a teammate without access to the original sites.

For a fully local check using preserved raw files, run:

```bash
make verify-offline PYTHON_INTERPRETER=.venv/bin/python
```

This performs formatting and lint checks, runs the complete Python test suite,
checks every scraper command-line entry point with `--help`, and rebuilds all
currently implemented interim datasets. It does not access the internet.

## AirKorea Hourly Monitor Data

Download the official finalized hourly monitoring-station archives (2001
through the latest year advertised by AirKorea):

```bash
make scrape-airkorea PYTHON_INTERPRETER=.venv/bin/python
```

For a smaller inclusive range, for example the years around a policy event:

```bash
make scrape-airkorea AIRKOREA_START_YEAR=2015 AIRKOREA_END_YEAR=2022
```

Annual ZIP files and a checksum manifest are written under
`data/raw/airkorea/hourly_finalized/`. Existing complete archives are reused,
interrupted `.part` files are resumed when the server supports byte ranges,
and invalid or incomplete ZIPs are rejected. No data.go.kr API key is needed:
the downloader uses AirKorea's public finalized-data archive rather than the
recent, provisional real-time API.

Run the QC pipeline over the downloaded archives with:

```bash
python -m nzk_aphiam.air_quality --years 2021 2022
```

See [`docs/datasets/airkorea_hourly_qc.md`](docs/datasets/airkorea_hourly_qc.md)
for the QC methodology, station-crosswalk logic, coverage, and output schema.

## KMA Weather and Dispersion Features

Create a KMA API Hub account, activate the ASOS, radiosonde, radiosonde
stability-analysis, Wind Profiler, and upper-air station-information APIs, and
add the issued key to `.env`:

```dotenv
KMA_API_HUB_KEY=...
```

Download the core 2001–2024 observations. These include ASOS surface weather,
station history, twice-daily radiosonde profiles, and KMA stability indices:

```bash
make scrape-kma-weather PYTHON_INTERPRETER=.venv/bin/python
```

Wind Profiler is intentionally separate because hourly nationwide retrieval
requires about 8,760 requests per year. Its Make target downloads one year by
default; change the explicit year variables to retrieve another batch:

```bash
make scrape-kma-profiler KMA_PROFILER_START_YEAR=2015 KMA_PROFILER_END_YEAR=2015
```

Normalize timestamps and units and derive sounding-time mixing-height and
surface-inversion features with:

```bash
make process-kma-weather PYTHON_INTERPRETER=.venv/bin/python
```

Raw and processed files remain partitioned by calendar year under
`data/raw/weather/kma/` and `data/processed/weather/kma/`. No observations are
interpolated or imputed. See
[`docs/datasets/kma_weather.md`](docs/datasets/kma_weather.md) for variable,
coverage, request-budget, and methodological details.

## Public Health Baseline

The initial public Korean health panel uses three KOSIS tables:

- monthly all-cause deaths by residence 시군구;
- annual deaths by 시군구 and 50 cause groups; and
- monthly resident population denominators.

Request a free KOSIS OpenAPI key and add it to `.env`:

```dotenv
KOSIS_API_KEY=...
```

Then download the 2001–2024 baseline aligned with the finalized AirKorea
series:

```bash
make scrape-health PYTHON_INTERPRETER=.venv/bin/python
```

Override `HEALTH_START_YEAR` and `HEALTH_END_YEAR` for a narrower panel. Raw
annual JSON responses, normalized CSVs, checksums, and provenance metadata are
written under `data/raw/health/kosis/`. Aggregate national and provincial rows
are retained and labeled so boundary harmonization can be handled explicitly
before the DiD/GWR panel is constructed.

## KEPCO Data Documentation

Detailed source-specific documentation for Western, East-West, Southern,
South-East, and Midland Power, along with the shared schema and combined
dataset rules, lives in
[`src/nzk_aphiam/data/README.md`](src/nzk_aphiam/data/README.md).

## Project Organization

```
├── CITATION.cff       <- Machine-readable software citation
├── docs/project       <- Authorship, provenance, and release documentation
├── docs/references    <- Documented mappings, evidence, and source references
├── LICENSE            <- MIT license for repository software and documentation
├── Makefile           <- Reproducible scrape, clean, combine, test, and analysis commands
├── requirements       <- Python and R dependency lists
├── configs            <- Event and pipeline YAML configuration files
├── analysis           <- Main R analysis workspace and shared R helpers
├── data               <- Local raw, interim, and processed data; ignored by Git
├── results
│   ├── figures        <- Saved plots and graphics
│   ├── tables         <- Saved analysis tables
│   ├── objects        <- Serialized analysis objects
│   └── models         <- Trained and serialized models
├── src/nzk_aphiam     <- Python package for scraping, cleaning, and processing
└── tests              <- Python test suite
```
