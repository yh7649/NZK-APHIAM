#################################################################################
# GLOBALS                                                                       #
#################################################################################

PROJECT_NAME = NZK-APHIAM
PYTHON_VERSION = 3.14.5
PYTHON_INTERPRETER = python

#################################################################################
# COMMANDS                                                                      #
#################################################################################


## Install Python dependencies
.PHONY: requirements
requirements:
	$(PYTHON_INTERPRETER) -m pip install -U pip
	$(PYTHON_INTERPRETER) -m pip install -r requirements.txt
	



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


## Download raw thermal data for all five power subsidiaries
.PHONY: scrape-thermal
scrape-thermal:
	$(MAKE) scrape-eastwest-power
	$(MAKE) scrape-western-power
	$(MAKE) scrape-southern-power
	$(MAKE) scrape-southeast-power
	$(MAKE) scrape-midland-power


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


## Verify code and rebuild implemented interim datasets without network access
.PHONY: verify-offline
verify-offline:
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) check-scraper-cli
	$(MAKE) clean-thermal
	$(MAKE) combine-thermal


## Run the main manual analysis workspace
.PHONY: r-analysis
r-analysis:
	Rscript analysis/manual_analysis.R


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
