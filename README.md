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
make requirements-r
```

`make requirements-r` installs pinned CRAN package versions from
[`requirements/r.txt`](requirements/r.txt) and GitHub-only packages (currently
`augsynth`, pinned to a commit SHA since it has no CRAN release) from
[`requirements/r_github.txt`](requirements/r_github.txt) via the `remotes`
package. Run this before `make r-analysis` or any other R target.

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
written under `results/`. Data remains local under `data/` and is generally
ignored by Git; narrowly documented provider/external inputs that cannot be
regenerated are tracked directly. The RStudio project and analysis scripts are
tracked source files, so they are already present after cloning; `make
r-analysis` rebuilds the combined processed data before running the script.

Run every thermal subsidiary scraper sequentially with:

```bash
make scrape-thermal
```

This is a **networked** workflow: it contacts data.go.kr and subsidiary
websites and replaces reproducible raw outputs with a fresh download. Midland
is the exception for emissions: its directly supplied, checksum-verified
2024--2025 mass workbook is tracked as immutable raw data, while only its
monthly generation is refreshed from the public API. Its cleaner aggregates
provider-reported stack mass to the matching plant/technology subtotal before
the one-to-one generation join. The command stops if any scraper fails.
Individual subsidiary and dataset targets are available through `make help`.

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
make airkorea-monitor-workflow PYTHON_INTERPRETER=.venv/bin/python
```

See [`docs/datasets/airkorea_hourly_qc.md`](docs/datasets/airkorea_hourly_qc.md)
for the dataset schema and
[`docs/methods/airkorea_monitor_workflow.md`](docs/methods/airkorea_monitor_workflow.md)
for the staged commands, QC logic, EPA-style annual PM aggregation, and
optional InMAP bias-correction grid.

## CAPSS Emissions Inventory

Download Korea's CAPSS detailed emissions-statistics workbooks and parse them
without aggregating away the native 시군구 × 배출원소분류 × 연료 granularity:

```bash
make scrape-capss-emissions PYTHON_INTERPRETER=.venv/bin/python
make process-capss-emissions PYTHON_INTERPRETER=.venv/bin/python
make export-capss-power-fuel-technology PYTHON_INTERPRETER=.venv/bin/python
```

Raw XLSX files are written under `data/raw/capss/emissions_statistics/`.
Tidy long-form Parquet and metadata are written under
`data/interim/capss/emissions_statistics/`. See
[`docs/datasets/capss_emissions.md`](docs/datasets/capss_emissions.md) for
coverage caveats, pollutant/unit checks, taxonomy-change flags, and validation
source pages.

The power-sector export filters CAPSS to `에너지산업 연소` and the public/private
power-facility subcategories, then aggregates nationally by official CAPSS
combustion equipment, major/minor fuel, and pollutant. It writes canonical
2016--2023 tables under `data/processed/capss/` and a key validation table under
`results/tables/capss/`.

## Korean Non-Power Emissions Inventory

The version-controlled non-power framework maps conceptual GCAM-KAIST annual
activities to native CAPSS categories, canonical pollutants, official Korean
activity-source leads, and pollutant-specific legal EF denominators. It keeps
process, combustion, fugitive, and electricity-only boundaries explicit and
preserves unresolved research gaps rather than converting them to zero.

Validate the tracked registries and provisional factor evidence, or build their
canonical Parquet tables and diagnostics:

```bash
make validate-nonpower-sector-inventory PYTHON_INTERPRETER=.venv/bin/python
make validate-nonpower-emission-factors PYTHON_INTERPRETER=.venv/bin/python
make build-nonpower-emissions PYTHON_INTERPRETER=.venv/bin/python
make scrape-capss-vii-nonpower-efs PYTHON_INTERPRETER=.venv/bin/python
make scrape-capss-vii-nonpower-efs-verified PYTHON_INTERPRETER=.venv/bin/python
```

The build writes ignored outputs under `data/processed/nonpower_emissions/`
and `results/diagnostics/nonpower_emissions/`. The scrape writes ignored page
text, raw table cells, a normalized 2025 Handbook VII factor-candidate table,
candidate inventory links, extraction issues, and coverage under
`data/interim/nonpower_emissions/`. The verified target additionally requires
the preserved PDF to be byte-identical to the current official download. All
imported and scraped factors remain candidate evidence: none is enabled for
production emissions, and the VI rows still require an official VII row-level
diff. See
[`docs/datasets/nonpower_sector_inventory.md`](docs/datasets/nonpower_sector_inventory.md)
for schemas, validation, known gaps, and the migration from the current
aggregate MACRO/CAPSS base-year intensity method.

## MACRO/GCAM-KAIST Activity Integration

MACRO and GCAM-KAIST files are mutable inter-model scenario inputs, not
datasets. They live in named bundles under `model_inputs/scenarios/`.
Add a team handoff through the schema-checking ingestion command:

```bash
make ingest-model-input \
  MODEL_INPUT_SOURCE=~/Downloads/gcam_kaist_sector_fuel_activity.csv \
  MODEL_INPUT_KIND=activity \
  MODEL_INPUT_SOURCE_MODEL=gcam_kaist \
  MODEL_INPUT_SCENARIO=team_handoff
```

This validates the file has the columns the downstream step needs, copies it
under `model_inputs/scenarios/<bundle>/upstream/<model>/`, and writes a metadata
sidecar recording who supplied it and its checksum. Use
`MODEL_INPUT_KIND=generation` and `MODEL_INPUT_SOURCE_MODEL=macro` for a MACRO
generation handoff.

The active team-supplied `CORE_9_NZ` XML is preserved as a DVC-tracked ZIP.
Build its South Korea activity, native-emissions validation, approved-factor,
and spatial-readiness interfaces directly from the compressed XML with:

```bash
make build-gcam-nzk-interface PYTHON_INTERPRETER=.venv/bin/python
```

The paired scenario configuration holds the NZK non-power pathway fixed and
compares `nzk_with_power_plant_nzk` with
`nzk_without_power_plant_nzk`. The final InMAP assembly is deliberately blocked
until denominator-compatible Korean non-power factors and reviewed
point/grid coordinates are production-ready. See
[`docs/methods/gcam_kaist_native_nzk_interface.md`](docs/methods/gcam_kaist_native_nzk_interface.md).

To run the explicitly non-analytical maximum-coverage proof of concept with
native NZK non-power activity and all three simulated power pathways:

```bash
make inmap-gcam-nzk-poc PYTHON_INTERPRETER=.venv/bin/python
```

This builds and runs 18 fixed-iteration jobs: three power pathways for six
years. The POC retains all 42 listed native non-power selectors as 25 APHIAM
activities, assigns all five InMAP pollutants through a documented ranked EF
fallback, and allocates emissions with 2021 CAPSS administrative shares placed
at matching AirKorea monitor centroids. It never changes factor approval flags.
The assumed activity conversions, CAPSS-calibrated and global fallback EFs, and
proxy coordinates make it unsuitable for policy, exposure, or health
inference.

After the jobs finish, run the Korea exposure, BenMAP-equivalent health, and
presentation stages with:

```bash
make inmap-gcam-nzk-poc-health PYTHON_INTERPRETER=.venv/bin/python
```

This produces slide-ready maps and charts under
`results/figures/inmap/gcam_nzk_three_power_poc_2025_2050/`, GIF and MP4
animations under `results/videos/inmap/gcam_nzk_three_power_poc_2025_2050/`,
and health/component tables under
`results/tables/inmap/gcam_nzk_three_power_poc_2025_2050/`. The animations show
annual steady-state fields and an illustrative PM2.5 component build-up, not a
time-resolved plume. For a future clean run, use
`make inmap-gcam-nzk-poc-with-health` to execute InMAP and these downstream
stages in one command.

To isolate the thermal-power signal from the shared GCAM non-power inventory,
run the 2050 current-thermal-versus-complete-shutdown diagnostic with:

```bash
make inmap-gcam-nzk-power-only-poc-with-health \
  PYTHON_INTERPRETER=.venv/bin/python
```

This prepares only two jobs, excludes the non-power COARDS file from both
InMAP configurations, and then writes explicitly power-only exposure,
mortality, figures, and tables. It remains a 50-iteration proof of concept and
does not repair the omitted power-sector primary PM2.5, NH3, or VOC emissions.

The explicitly synthetic 2023--2050 activity-index fixture remains available
only for software smoke tests:

```bash
make build-macro-nonpower-proxy PYTHON_INTERPRETER=.venv/bin/python
make validate-macro-nonpower-proxy PYTHON_INTERPRETER=.venv/bin/python
```

The fixture uses the existing `no_nzk`, `nzk_low`, and `nzk_high` scenario names,
keeps 50 P1 activities in the rich table, and labels every output as a
pipeline-test proxy rather than GCAM-KAIST model output. See
[`docs/methods/gcam_kaist_nonpower_proxy.md`](docs/methods/gcam_kaist_nonpower_proxy.md).

Build the paired point-plus-grid Global InMAP input bundle with:

```bash
make build-inmap-combined-inputs PYTHON_INTERPRETER=.venv/bin/python
```

For each scenario and five-year snapshot, this writes an elevated KEPCO power
shapefile, a COARDS NetCDF-3 non-power grid, a combined long-form emissions
ledger, and a binding manifest. The first-pass grid and CAPSS aggregate-intensity
factors are explicitly screening proxies; all manifests prohibit analytical use.
See
[`docs/methods/inmap_combined_inventory.md`](docs/methods/inmap_combined_inventory.md).

Once the pinned InMAP installation is present, generate all instruction files or
run all 18 jobs sequentially and resumably with:

```bash
make inmap-combined-prepare PYTHON_INTERPRETER=.venv/bin/python
make inmap-combined-run PYTHON_INTERPRETER=.venv/bin/python
```

Use `make inmap-combined-poc` for the faster, explicitly non-converged
200-iteration plumbing test.

To resume an already prepared POC with two scenario-years running concurrently,
use:

```bash
make inmap-combined-poc-parallel PYTHON_INTERPRETER=.venv/bin/python
```

The runner divides the detected CPU cores between the workers and reuses
completed checksum-matched jobs. Do not run the sequential and parallel commands
at the same time.

For the quickest end-to-end plumbing proof, run a separate 50-iteration,
two-worker POC through mortality and presentation-ready result reporting with:

```bash
make inmap-combined-fast-poc-with-health PYTHON_INTERPRETER=.venv/bin/python
```

This writes under `poc_50_iterations/` and does not overwrite the 200-iteration
outputs. It is an execution diagnostic, not a converged estimate.

After all POC jobs finish, produce Korean exposure, explicitly diagnostic
BenMAP-style mortality totals, figures, and CSV tables for every scenario-year
with:

```bash
make inmap-combined-poc-health PYTHON_INTERPRETER=.venv/bin/python
```

Use `make inmap-combined-poc-with-health` to run both stages together on a
future invocation. See the method document for output files, interpretation,
and the 2042 population-projection hold used for 2045 and 2050.

If the health outputs already exist, rebuild only the figures and summary tables
with:

```bash
make inmap-combined-poc-report \
  PYTHON_INTERPRETER=.venv/bin/python \
  INMAP_COMBINED_POC_ITERATIONS=50
```

The 50-iteration figures go to
`results/figures/inmap/combined_proxy_2025_2050/poc_50_iterations/`, and their
CSV counterparts go to
`results/tables/inmap/combined_proxy_2025_2050/poc_50_iterations/`. All POC
outputs remain explicitly non-converged diagnostics and are not suitable for
effect-size inference.

## Korean Thermal-Power Replication MVP

The screening-level Huang–Peng replication chain now connects observed EPSIS
generation and the local MACRO pathway to physical thermal sites, the existing
generation-weighted KEPCO emission factors, Global InMAP, national exposure,
and the existing health-impact model. The current local comparison is explicitly
`historical_to_scenario`; it is not presented as a causal net-zero policy benefit.

Run the resumable workflow with:

```bash
make peng-mvp PYTHON_INTERPRETER=.venv/bin/python
```

For a faster real-binary plumbing proof that writes diagnostic, explicitly
non-converged exposure output and never runs health impacts, use:

```bash
make peng-mvp-poc PYTHON_INTERPRETER=.venv/bin/python
```

The first 200-iteration dual-scenario POC completed on 20 July 2026. Its values
are retained only as execution diagnostics; strict-convergence exposure and health
results remain pending.

To confirm health-module plumbing and sign using those non-converged values, without
creating a normal analytical health output, run:

```bash
make peng-mvp-poc-health-diagnostic PYTHON_INTERPRETER=.venv/bin/python
```

See [`docs/methods/peng_replication_mvp.md`](docs/methods/peng_replication_mvp.md)
for inputs, assumptions, safeguards, component commands, and interpretation.

Teammates who prefer not to use the terminal can build
`tools/macos/Add MACRO Generation File.app` once with
`make build-macro-generation-dropper`, then just drag a MACRO generation file
onto it. See [`tools/macos/README.md`](tools/macos/README.md).

The legacy five-column workflow combines sector-by-fuel activity with CAPSS
base-year pollutant intensities. It remains a screening/compatibility path,
separate from the native XML interface:

```bash
make integrate-macro-inputs \
  MODEL_INPUT_SCENARIO=team_handoff \
  MACRO_ACTIVITY=model_inputs/scenarios/team_handoff/upstream/gcam_kaist/gcam_kaist_sector_fuel_activity.csv \
  MACRO_MAPPING=docs/references/macro/gcam_capss_sector_fuel_mapping.csv \
  MACRO_BASE_YEAR=2023
```

Projected emissions, emission factors, diagnostics, and metadata are written
to the bundle's `aphiam/` interface. See
[`docs/datasets/macro_input_integration.md`](docs/datasets/macro_input_integration.md).

For the separate 2021 historical validation of MACRO generation multiplied by
KEPCO-derived EFs against CAPSS actual power-sector emissions, run:

```bash
make validate-macro-2021-kepco-ef \
  MACRO_GENERATION=model_inputs/scenarios/<bundle>/upstream/macro/<generation-file>.csv
```

This workflow requires the team-supplied MACRO generation file; it does
not substitute CAPSS-derived EFs when that file is absent.

## Atmospheric Dispersion

The active air-quality pathway uses annual Global InMAP with the model's
packaged global meteorology and built-in bias correction. Hourly KMA weather is
therefore outside the current research design and is not an input to the Global
InMAP workflow. The InMAP adapter can combine the generated elevated power inventory
with scenario-scoped point/line/polygon shapefiles and COARDS NetCDF-3 gridded
inventories for transport, agriculture, industry, and other sectors; see
[`docs/methods/peng_replication_mvp.md`](docs/methods/peng_replication_mvp.md).
The reproducible economy-wide fixture assembler is documented separately in
[`docs/methods/inmap_combined_inventory.md`](docs/methods/inmap_combined_inventory.md).

The former KMA ASOS, radiosonde, stability-index, and Wind Profiler pipeline is
preserved under `src/nzk_aphiam/archive/kma_weather/` for provenance and possible
future reuse. Its active Makefile targets and data-package entry points were
removed. See [`docs/archive/kma_weather.md`](docs/archive/kma_weather.md) for the
archived scope, storage locations, and explicit restoration commands.

## Public Health And Demographic Baseline

The public Korean health panel uses KOSIS tables for outcomes, denominators,
and district-level covariates:

- monthly all-cause deaths by residence 시군구;
- annual deaths by 시군구 and 50 cause groups;
- monthly resident population denominators;
- monthly age-structure and sex-ratio indicators;
- annual foreign-resident composition by category and sex; and
- annual socioeconomic, housing, migration, insurance, disability, household,
  and healthcare-access proxies.

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
annual JSON responses and provenance metadata are written under
`data/raw/health/kosis/`; deterministic normalized CSVs are written under
`data/interim/health/kosis/`. Aggregate national and provincial rows
are retained and labeled so boundary harmonization can be handled explicitly
before the DiD/GWR panel is constructed.

See [`docs/datasets/kosis_health.md`](docs/datasets/kosis_health.md) for the
table inventory, schemas, and source-specific limitations.

To refresh only the demographic covariates, run:

```bash
make scrape-demographics PYTHON_INTERPRETER=.venv/bin/python
```

To add the broader social-determinants scrape:

```bash
make scrape-social-determinants PYTHON_INTERPRETER=.venv/bin/python
```

## Health-Impact Assessment

The CRF, attributable-deaths, and decomposition functions in
`src/nzk_aphiam/health/` implement the
`ΔY = (1 − e^(−β·ΔPM)) · Y₀ · Pop` estimator (Krewski et al. 2009 by
default) independent of any specific exposure pipeline. Given a tidy
scenario CSV of PM2.5 exposure by population group, compute
PM2.5-attributable deaths with:

```bash
make health-impact PYTHON_INTERPRETER=.venv/bin/python
```

See [`docs/methods/health_impact_assessment.md`](docs/methods/health_impact_assessment.md)
for the input schema, CRF parameters, decomposition method, and
interpretation caveats.

## KEPCO Data Documentation

Detailed source-specific documentation for Western, East-West, Southern,
South-East, and Midland Power, along with the shared schema and combined
dataset rules, lives in
[`src/nzk_aphiam/data/README.md`](src/nzk_aphiam/data/README.md).

The empirical synthetic-control branch is documented in
[`docs/methods/synthetic_control.md`](docs/methods/synthetic_control.md).
Current implementation status and the Huang & Peng replication gap analysis
are maintained in [`docs/project/progress.md`](docs/project/progress.md).

## Project Organization

The authoritative placement rules are in
[`docs/project/data_layout.md`](docs/project/data_layout.md).

```
├── CITATION.cff       <- Machine-readable software citation
├── pyproject.toml     <- Python package metadata, dependencies, and ruff config
├── NZK-APHIAM.Rproj   <- RStudio project file
├── docs/project       <- Authorship, provenance, and release documentation
├── docs/datasets      <- Per-dataset schema, coverage, and QC documentation
├── docs/methods       <- Documented analysis methodologies
├── docs/references    <- Documented mappings, evidence, and source references
├── docs/archive       <- Documentation for paused/superseded work
├── LICENSE            <- MIT license for repository software and documentation
├── Makefile           <- Reproducible scrape, clean, combine, test, and analysis commands
├── requirements       <- Python and R dependency lists
├── configs            <- Event and pipeline YAML configuration files
├── analysis           <- Main R analysis workspace and shared R helpers
├── model_inputs       <- Mutable inter-model handoffs and APHIAM scenario interfaces
├── data               <- Local data; mostly ignored, with documented tracked exceptions
│   ├── raw            <- Preserved provider responses and source snapshots
│   ├── external       <- Non-model third-party primary datasets; tracked directly in Git
│   ├── interim        <- Source-specific normalized and cleaned products
│   ├── processed      <- Canonical analysis-ready data and reusable parameters
│   └── archive        <- Raw/interim/processed data for archived pipelines
├── .dvc               <- Local DVC cache/config for versioning raw-data snapshots
├── results
│   ├── figures        <- Saved plots and graphics
│   ├── tables         <- Saved analysis tables
│   ├── objects        <- Serialized analysis objects
│   ├── models         <- Trained and serialized statistical models
│   ├── runs           <- Simulation configs, logs, manifests, and outputs
│   └── diagnostics    <- Validation and machine-readable QC reports
├── src/nzk_aphiam     <- Python package for scraping, cleaning, and processing
├── tools              <- Non-terminal helper tools (e.g. macOS drag-and-drop apps)
└── tests              <- Python test suite
```
