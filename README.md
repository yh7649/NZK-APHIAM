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
make combine-thermal PYTHON_INTERPRETER=.venv/bin/python
```

Open `NZK-APHIAM.Rproj` in RStudio and use
`analysis/kepco/manual_analysis.R` as the main analysis workspace. The project file
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

The R entry point is `analysis/kepco/manual_analysis.R`, with shared path helpers
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

## Thermal Data Documentation

Detailed source-specific documentation for Western, East-West, Southern,
South-East, and Midland Power, along with the shared schema and combined
dataset rules, lives in
[`src/nzk_aphiam/data/README.md`](src/nzk_aphiam/data/README.md).

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
