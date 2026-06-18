#################################################################################
# GLOBALS                                                                       #
#################################################################################

PROJECT_NAME = NZK-APHIAM
PYTHON_VERSION = 3.11
PYTHON_INTERPRETER = python

#################################################################################
# COMMANDS                                                                      #
#################################################################################


## Install Python dependencies
.PHONY: requirements
requirements:
	$(PYTHON_INTERPRETER) -m pip install -U pip
	$(PYTHON_INTERPRETER) -m pip install -r requirements.txt
	

## Install R analysis dependencies
.PHONY: requirements-r
requirements-r:
	Rscript -e 'options(repos = c(CRAN = "https://cloud.r-project.org")); pkgs <- readLines("requirements-r.txt", warn = FALSE); pkgs <- pkgs[nzchar(pkgs)]; missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]; if (length(missing)) install.packages(missing)'


## Install Python and R dependencies
.PHONY: requirements-all
requirements-all: requirements requirements-r



## Delete all compiled Python files
.PHONY: clean
clean:
	find . -type f -name "*.py[co]" -delete
	find . -type d -name "__pycache__" -delete


## Lint using ruff (use `make format` to do formatting)
.PHONY: lint
lint:
	$(PYTHON_INTERPRETER) -m ruff format --check
	$(PYTHON_INTERPRETER) -m ruff check

## Format source code with ruff
.PHONY: format
format:
	$(PYTHON_INTERPRETER) -m ruff check --fix
	$(PYTHON_INTERPRETER) -m ruff format



## Run tests
.PHONY: test
test:
	$(PYTHON_INTERPRETER) -m pytest tests


## Download East-West Power raw data
.PHONY: scrape-eastwest-power
scrape-eastwest-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.eastwest_power


## Clean East-West Power monthly generation and emissions data
.PHONY: clean-eastwest-power
clean-eastwest-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.clean.thermal.eastwest_power


## Download Western Power raw data
.PHONY: scrape-western-power
scrape-western-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.western_power


## Clean Western Power monthly generation and emissions data
.PHONY: clean-western-power
clean-western-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.clean.thermal.western_power


## Download Southern Power emissions data
.PHONY: scrape-southern-power-emissions
scrape-southern-power-emissions:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power emissions


## Download Southern Power generation data
.PHONY: scrape-southern-power-generation
scrape-southern-power-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power generation


## Download Southern Power emissions and generation data
.PHONY: scrape-southern-power
scrape-southern-power:
	$(MAKE) scrape-southern-power-emissions
	$(MAKE) scrape-southern-power-generation


## Clean Southern Power monthly generation and emissions data
.PHONY: clean-southern-power
clean-southern-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.clean.thermal.southern_power


## Clean all implemented thermal subsidiary datasets
.PHONY: clean-thermal
clean-thermal:
	$(MAKE) clean-western-power
	$(MAKE) clean-eastwest-power
	$(MAKE) clean-southern-power
	$(MAKE) clean-southeast-power
	$(MAKE) clean-midland-power


## Combine East-West, Western, and Southern monthly data with pollutant mass in kilograms
.PHONY: combine-thermal
combine-thermal:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.thermal


## Download fresh South-East Power raw data
.PHONY: scrape-southeast-power
scrape-southeast-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southeast_power


## Clean South-East Power daily pollutant measurements
.PHONY: clean-southeast-power
clean-southeast-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.clean.thermal.southeast_power


## Download Midland Power emissions data
.PHONY: scrape-midland-power-emissions
scrape-midland-power-emissions:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power emissions --overwrite


## Download Midland Power generation data
.PHONY: scrape-midland-power-generation
scrape-midland-power-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power generation --overwrite


## Download Midland Power emissions and generation data
.PHONY: scrape-midland-power
scrape-midland-power:
	$(MAKE) scrape-midland-power-emissions
	$(MAKE) scrape-midland-power-generation
	$(MAKE) scrape-midland-power-facility-status


## Download Midland Power facility air-status data
.PHONY: scrape-midland-power-facility-status
scrape-midland-power-facility-status:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power facility-status --overwrite


## Download individual Midland Power facility air-status datasets
.PHONY: scrape-midland-power-boryeong scrape-midland-power-seoul scrape-midland-power-seocheon scrape-midland-power-sejong scrape-midland-power-shin-boryeong scrape-midland-power-jeju scrape-midland-power-incheon
scrape-midland-power-boryeong:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power.boryeong --overwrite

scrape-midland-power-seoul:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power.seoul --overwrite

scrape-midland-power-seocheon:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power.seocheon --overwrite

scrape-midland-power-sejong:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power.sejong --overwrite

scrape-midland-power-shin-boryeong:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power.shin_boryeong --overwrite

scrape-midland-power-jeju:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power.jeju --overwrite

scrape-midland-power-incheon:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power.incheon --overwrite


## Clean Midland Power facility air-status data
.PHONY: clean-midland-power
clean-midland-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.clean.thermal.midland_power


## Download raw thermal data for all five power subsidiaries
.PHONY: scrape-thermal
scrape-thermal:
	$(MAKE) scrape-eastwest-power
	$(MAKE) scrape-western-power
	$(MAKE) scrape-southern-power
	$(MAKE) scrape-southeast-power
	$(MAKE) scrape-midland-power


## Download EPSIS annual generator rosters
.PHONY: scrape-epsis-annual
scrape-epsis-annual:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis annual


## Download EPSIS dated generator roster snapshots
.PHONY: scrape-epsis-snapshots
scrape-epsis-snapshots:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis snapshots


## Download EPSIS annual mixed-granularity capacity and generation
.PHONY: scrape-epsis-generation
scrape-epsis-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis annual-generation


## Download all EPSIS annual and dated generator rosters
.PHONY: scrape-epsis
scrape-epsis:
	$(MAKE) scrape-epsis-annual
	$(MAKE) scrape-epsis-generation
	$(MAKE) scrape-epsis-snapshots


## Download CleanSYS annual facility-level air pollutant emissions
.PHONY: scrape-cleansys
scrape-cleansys:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.cleansys


## Download ENV-INFO annual power-sector facility air pollutant emissions
.PHONY: scrape-env-info
scrape-env-info:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.env_info --start-year 2015 --end-year 2024


FACILITY_START_YEAR ?= 2015
FACILITY_END_YEAR ?= 2024


## Download the EPSIS, CleanSYS, and ENV-INFO inputs used for facility emission factors
.PHONY: scrape-facility-ef-inputs
scrape-facility-ef-inputs:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis annual --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis annual-generation --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.cleansys --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.env_info --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)


## Rebuild normalized facility-EF inputs strictly from preserved raw files
.PHONY: rebuild-facility-ef-inputs-offline
rebuild-facility-ef-inputs-offline:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis --offline annual --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis --offline annual-generation --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.cleansys --offline --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.env_info --offline --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)


## Build the EPSIS to ENV-INFO and CleanSYS thermal facility crosswalk
.PHONY: build-thermal-crosswalk
build-thermal-crosswalk:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.crosswalk


## Download all facility-EF inputs and build the documented crosswalk
.PHONY: reproduce-facility-crosswalk
reproduce-facility-crosswalk: scrape-facility-ef-inputs build-thermal-crosswalk


## Rebuild facility-EF inputs and crosswalk without contacting providers
.PHONY: verify-facility-crosswalk-offline
verify-facility-crosswalk-offline: rebuild-facility-ef-inputs-offline build-thermal-crosswalk


## Build annual plant generation, reconcile emissions, and calculate emission factors
.PHONY: build-annual-plant-panel
build-annual-plant-panel:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.annual_panel


## Rebuild all annual facility inputs, crosswalks, and the final plant-year panel offline
.PHONY: reproduce-annual-plant-panel-offline
reproduce-annual-plant-panel-offline: verify-facility-crosswalk-offline combine-thermal build-annual-plant-panel


## Check every thermal scraper command without network access
.PHONY: check-scraper-cli
check-scraper-cli:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.eastwest_power --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.western_power --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power emissions --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power generation --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southeast_power --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power emissions --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power generation --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.epsis --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.cleansys --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.env_info --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.crosswalk --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.annual_panel --help


## Verify code and rebuild implemented interim datasets without network access
.PHONY: verify-offline
verify-offline:
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) check-scraper-cli
	$(MAKE) clean-thermal
	$(MAKE) combine-thermal
	$(MAKE) r-analysis


## Build the combined data and run the main manual R analysis workspace
.PHONY: r-analysis
r-analysis: combine-thermal
	Rscript analysis/kepco/manual_analysis.R


## Set up Python interpreter environment
.PHONY: create_environment
create_environment:
	@bash -c "if [ ! -z `which virtualenvwrapper.sh` ]; then source `which virtualenvwrapper.sh`; mkvirtualenv $(PROJECT_NAME) --python=$(PYTHON_INTERPRETER); else mkvirtualenv.bat $(PROJECT_NAME) --python=$(PYTHON_INTERPRETER); fi"
	@echo ">>> New virtualenv created. Activate with:\nworkon $(PROJECT_NAME)"
	



#################################################################################
# PROJECT RULES                                                                 #
#################################################################################


## Make dataset
.PHONY: data
data: requirements
	$(PYTHON_INTERPRETER) net_zero_korea:_air_pollution_and_health_iam/dataset.py


#################################################################################
# Self Documenting Commands                                                     #
#################################################################################

.DEFAULT_GOAL := help

define PRINT_HELP_PYSCRIPT
import re, sys; \
lines = '\n'.join([line for line in sys.stdin]); \
matches = re.findall(r'\n## (.*)\n[\s\S]+?\n([a-zA-Z_-]+):', lines); \
print('Available rules:\n'); \
print('\n'.join(['{:40}{}'.format(*reversed(match)) for match in matches]))
endef
export PRINT_HELP_PYSCRIPT

help:
	@$(PYTHON_INTERPRETER) -c "${PRINT_HELP_PYSCRIPT}" < $(MAKEFILE_LIST)
