#################################################################################
# GLOBALS                                                                       #
#################################################################################

PROJECT_NAME = NZK-APHIAM
PYTHON_VERSION = 3.11
PYTHON_INTERPRETER = python
DVC ?= dvc
EVENT ?= example_event
ASCM_INPUT ?= data/interim/synthetic_control/$(EVENT)_hourly.csv
ASCM_HOURLY ?= data/interim/synthetic_control/$(EVENT)_hourly_normalized.csv

#################################################################################
# COMMANDS                                                                      #
#################################################################################


## Install Python dependencies
.PHONY: requirements
requirements:
	$(PYTHON_INTERPRETER) -m pip install -U pip
	$(PYTHON_INTERPRETER) -m pip install -r requirements/python.txt
	

## Install R analysis dependencies
.PHONY: requirements-r
requirements-r:
	Rscript -e 'options(repos = c(CRAN = "https://cloud.r-project.org")); pkgs <- readLines("requirements/r.txt", warn = FALSE); pkgs <- pkgs[nzchar(pkgs)]; missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]; if (length(missing)) install.packages(missing)'


## Install Python and R dependencies
.PHONY: requirements-all
requirements-all: requirements requirements-r


## Normalize hourly monitor pollution with rmweather
.PHONY: ascm-normalize
ascm-normalize:
	Rscript analysis/synthetic_control/normalize_weather.R $(ASCM_INPUT) $(ASCM_HOURLY)


## Screen donors and build the weekly synthetic-control panel
.PHONY: ascm-panel
ascm-panel:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.modeling.synthetic_control --config configs/plant_events/$(EVENT).yml --hourly $(ASCM_HOURLY)


## Fit ridge-augmented synthetic control (one pollutant per event panel)
.PHONY: ascm-estimate
ascm-estimate:
	Rscript analysis/synthetic_control/run_augsynth.R data/processed/synthetic_control/$(EVENT)_weekly.csv results/models/synthetic_control/$(EVENT)



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


## Download Southern Power's independent hourly generation cross-check
.PHONY: scrape-southern-power-hourly-generation
scrape-southern-power-hourly-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power hourly-generation


## Download Southern Power's annual unit/plant generation validation file
.PHONY: scrape-southern-power-annual-generation
scrape-southern-power-annual-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power annual-generation


## Download Southern Power emissions and generation data
.PHONY: scrape-southern-power
scrape-southern-power:
	$(MAKE) scrape-southern-power-emissions
	$(MAKE) scrape-southern-power-generation
	$(MAKE) scrape-southern-power-hourly-generation
	$(MAKE) scrape-southern-power-annual-generation


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


## Build KEPCO subsidiaries and KHNP monthly generation and capacity panel (no emissions)
.PHONY: build-generation-panel
build-generation-panel:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.clean.thermal.generation_panel


## Download KHNP rolling daily generation data and retain monthly source snapshots
.PHONY: scrape-khnp-generation
scrape-khnp-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.khnp --overwrite


## Download CAPSS detailed annual emissions statistics workbooks
.PHONY: scrape-capss-emissions
scrape-capss-emissions:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.capss


## Parse CAPSS detailed emissions workbooks into tidy long-form Parquet
.PHONY: process-capss-emissions
process-capss-emissions:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.capss


## Download and parse CAPSS detailed annual emissions statistics
.PHONY: build-capss-emissions
build-capss-emissions: scrape-capss-emissions process-capss-emissions


MACRO_ACTIVITY ?= data/raw/macro/gcam_kaist_sector_fuel_activity.csv
MACRO_MAPPING ?=
MACRO_BASE_YEAR ?=
MACRO_SCENARIO_COLUMNS ?= scenario
MACRO_POLLUTANTS ?= SOx,NOx,NH3,VOCs,PM2.5


## Integrate GCAM-KAIST/MACRO sector-fuel activity with CAPSS emission intensities
.PHONY: integrate-macro-inputs
integrate-macro-inputs:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.macro \
		--gcam-activity $(MACRO_ACTIVITY) \
		$(if $(MACRO_MAPPING),--mapping $(MACRO_MAPPING),) \
		$(if $(MACRO_BASE_YEAR),--base-year $(MACRO_BASE_YEAR),) \
		--scenario-columns $(MACRO_SCENARIO_COLUMNS) \
		--pollutants $(MACRO_POLLUTANTS)


## Build, audit, and merge per-subsidiary KEPCO monthly datasets (pollutant mass in kilograms)
.PHONY: combine-kepco
combine-kepco:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.thermal


## Backward-compatible alias for the combined KEPCO monthly dataset
.PHONY: combine-thermal
combine-thermal: combine-kepco


## Fit descriptive plant-emissions to AirKorea spatial associations (requires existing AirKorea QC products)
.PHONY: gwr-plant-air-quality
gwr-plant-air-quality: combine-kepco
	Rscript analysis/gwr/plant_air_quality_gwr.R


## Run deterministic smoke tests for the descriptive GWR helpers
.PHONY: test-gwr-r
test-gwr-r:
	Rscript analysis/gwr/test_gwr_helpers.R


## Map annual AirKorea monitor means with fuel-coded KEPCO plants
.PHONY: map-gwr-plant-air-quality
map-gwr-plant-air-quality:
	Rscript analysis/gwr/map_air_quality_and_plants.R


## Re-audit already-combined KEPCO subsidiary datasets without recombining (e.g. after changing audit thresholds)
.PHONY: audit-kepco
audit-kepco:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.audit.thermal


## Clean, standardize, audit, and merge every implemented KEPCO thermal subsidiary dataset
.PHONY: reproduce-kepco-monthly
reproduce-kepco-monthly: clean-thermal combine-kepco


## Download fresh South-East Power raw data
.PHONY: scrape-southeast-power
scrape-southeast-power:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southeast_power
	$(MAKE) scrape-southeast-power-generation-fresh

.PHONY: scrape-southeast-power-generation-fresh
scrape-southeast-power-generation-fresh:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southeast_power.generation_scraper

.PHONY: scrape-southeast-power-generation
scrape-southeast-power-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southeast_power.generation_scraper --reuse-existing-source


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


## Version this run's KEPCO raw snapshots with DVC (local only; configure a
## remote with `dvc remote add` before `dvc push` can share them with a teammate)
.PHONY: track-kepco-snapshots
track-kepco-snapshots:
	$(DVC) add \
		data/raw/kepco_subsidiaries/eastwest_power \
		data/raw/kepco_subsidiaries/western_power \
		data/raw/kepco_subsidiaries/southern_power \
		data/raw/kepco_subsidiaries/southeast_power \
		data/raw/kepco_subsidiaries/midland_power
	@echo "Snapshots staged for git (review with 'git status', then commit)."
	@echo "Run 'dvc push' once a remote is configured to share them."


## [PAUSED: annual non-KEPCO panel] Download EPSIS annual generator rosters
.PHONY: scrape-epsis-annual
scrape-epsis-annual:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis annual


## [PAUSED: annual non-KEPCO panel] Download EPSIS dated generator roster snapshots
.PHONY: scrape-epsis-snapshots
scrape-epsis-snapshots:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis snapshots


## [PAUSED: annual non-KEPCO panel] Download EPSIS annual mixed-granularity capacity and generation
.PHONY: scrape-epsis-generation
scrape-epsis-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis annual-generation


## [PAUSED: annual non-KEPCO panel] Download all EPSIS annual and dated generator rosters
.PHONY: scrape-epsis
scrape-epsis:
	$(MAKE) scrape-epsis-annual
	$(MAKE) scrape-epsis-generation
	$(MAKE) scrape-epsis-snapshots


## [PAUSED: annual non-KEPCO panel] Download CleanSYS annual facility-level air pollutant emissions
.PHONY: scrape-cleansys
scrape-cleansys:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.cleansys


AIRKOREA_START_YEAR ?= 2001
AIRKOREA_END_YEAR ?=


## Download finalized hourly monitor-level air quality archives from AirKorea
.PHONY: scrape-airkorea
scrape-airkorea:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.airkorea --start-year $(AIRKOREA_START_YEAR) $(if $(AIRKOREA_END_YEAR),--end-year $(AIRKOREA_END_YEAR),)


KMA_START_YEAR ?= 2001
KMA_END_YEAR ?= 2024
KMA_PROFILER_START_YEAR ?= 2004
KMA_PROFILER_END_YEAR ?= 2004


## Download core KMA surface, station, radiosonde, and stability observations
.PHONY: scrape-kma-weather
scrape-kma-weather:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.weather.kma core --start-year $(KMA_START_YEAR) --end-year $(KMA_END_YEAR)


## Download high-volume hourly KMA Wind Profiler data (one year by default)
.PHONY: scrape-kma-profiler
scrape-kma-profiler:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.weather.kma profiler --start-year $(KMA_PROFILER_START_YEAR) --end-year $(KMA_PROFILER_END_YEAR)


## Normalize KMA observations and derive mixing-height/inversion features
.PHONY: process-kma-weather
process-kma-weather:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.weather.kma --start-year $(KMA_START_YEAR) --end-year $(KMA_END_YEAR)


## Version KMA annual raw snapshots with local DVC
.PHONY: track-kma-snapshots
track-kma-snapshots:
	$(DVC) add data/raw/weather/kma
	@echo "KMA snapshots staged for git (review with 'git status', then commit)."


## Archive official plant-location/date evidence for offline reproducibility
.PHONY: archive-plant-location-references
archive-plant-location-references:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.references.plant_location_dates


## Store the archived reference snapshot in the local DVC cache
.PHONY: track-plant-location-references
track-plant-location-references:
	$(DVC) add data/raw/references/plant_location_dates
	@echo "Reference archive stored in the local DVC cache."
	@echo "Commit data/raw/references/plant_location_dates.dvc; run dvc push after adding a remote."


HEALTH_START_YEAR ?= 2001
HEALTH_END_YEAR ?= 2024


## Download KOSIS district health, population, and demographic baseline data
.PHONY: scrape-health
scrape-health:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.health.kosis --start-year $(HEALTH_START_YEAR) --end-year $(HEALTH_END_YEAR)


## Download only KOSIS district demographic and socioeconomic covariates
.PHONY: scrape-demographics
scrape-demographics:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.health.kosis aging sex-ratio foreign-residents fiscal-independence elderly-living-alone --start-year $(HEALTH_START_YEAR) --end-year $(HEALTH_END_YEAR)


## Download additional KOSIS/NHIS social determinants and healthcare-access covariates
.PHONY: scrape-social-determinants
scrape-social-determinants:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.health.kosis registered-disability health-insurance-population one-person-households one-person-households-age-sex migration old-housing vacant-housing longterm-care-facilities medical-coverage-seoul-incheon-gyeonggi-gangwon medical-coverage-daejeon-sejong-chungcheong medical-coverage-gwangju-jeolla-jeju medical-coverage-busan-daegu-ulsan-gyeongsang medical-institutions-seoul-incheon-gyeonggi-gangwon medical-institutions-daejeon-sejong-chungcheong medical-institutions-gwangju-jeolla-jeju medical-institutions-busan-daegu-ulsan-gyeongsang medical-workforce-seoul-incheon-gyeonggi-gangwon medical-workforce-daejeon-sejong-chungcheong medical-workforce-gwangju-jeolla-jeju medical-workforce-busan-daegu-ulsan-gyeongsang insurance-premiums-seoul-incheon-gyeonggi-gangwon insurance-premiums-daejeon-sejong-chungcheong insurance-premiums-gwangju-jeolla-jeju insurance-premiums-busan-daegu-ulsan-gyeongsang --start-year $(HEALTH_START_YEAR) --end-year $(HEALTH_END_YEAR)


## [PAUSED: annual non-KEPCO panel] Download ENV-INFO annual power-sector facility air pollutant emissions
.PHONY: scrape-env-info
scrape-env-info:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.env_info --start-year 2015 --end-year 2024


FACILITY_START_YEAR ?= 2015
FACILITY_END_YEAR ?= 2024


## [PAUSED: annual non-KEPCO panel] Download the EPSIS, CleanSYS, and ENV-INFO inputs used for facility emission factors
.PHONY: scrape-facility-ef-inputs
scrape-facility-ef-inputs:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis annual --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis annual-generation --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.cleansys --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.env_info --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)


## [PAUSED: annual non-KEPCO panel] Rebuild normalized facility-EF inputs strictly from preserved raw files
.PHONY: rebuild-facility-ef-inputs-offline
rebuild-facility-ef-inputs-offline:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis --offline annual --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis --offline annual-generation --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.cleansys --offline --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.env_info --offline --start-year $(FACILITY_START_YEAR) --end-year $(FACILITY_END_YEAR)


## [PAUSED: annual non-KEPCO panel] Build the EPSIS to ENV-INFO and CleanSYS thermal facility crosswalk
.PHONY: build-thermal-crosswalk
build-thermal-crosswalk:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.process.crosswalk


## [PAUSED: annual non-KEPCO panel] Download all facility-EF inputs and build the documented crosswalk
.PHONY: reproduce-facility-crosswalk
reproduce-facility-crosswalk: scrape-facility-ef-inputs build-thermal-crosswalk


## [PAUSED: annual non-KEPCO panel] Rebuild facility-EF inputs and crosswalk without contacting providers
.PHONY: verify-facility-crosswalk-offline
verify-facility-crosswalk-offline: rebuild-facility-ef-inputs-offline build-thermal-crosswalk


## [PAUSED: annual non-KEPCO panel] Build annual plant generation, reconcile emissions, and calculate emission factors
.PHONY: build-annual-plant-panel
build-annual-plant-panel:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.process.annual_panel


## [PAUSED: annual non-KEPCO panel] Rebuild all annual facility inputs, crosswalks, and the final plant-year panel offline
.PHONY: reproduce-annual-plant-panel-offline
reproduce-annual-plant-panel-offline: verify-facility-crosswalk-offline combine-kepco build-annual-plant-panel


## Check every thermal scraper command without network access
.PHONY: check-scraper-cli
check-scraper-cli:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.eastwest_power --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.khnp --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.western_power --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power emissions --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power generation --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power hourly-generation --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southern_power annual-generation --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southeast_power --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.southeast_power.generation_scraper --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power emissions --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power generation --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.airkorea --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.health.kosis --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.weather.kma --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.weather.kma --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.cleansys --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.env_info --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.process.crosswalk --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.process.annual_panel --help


## Verify code and rebuild implemented interim datasets without network access
.PHONY: verify-offline
verify-offline:
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) check-scraper-cli
	$(MAKE) clean-thermal
	$(MAKE) combine-kepco
	$(MAKE) r-analysis


## Build the combined data and run the main manual R analysis workspace
.PHONY: r-analysis
r-analysis: combine-kepco
	Rscript analysis/kepco/kepco_monthly_analysis.R


## Set up Python interpreter environment
.PHONY: create_environment
create_environment:
	@bash -c "if [ ! -z `which virtualenvwrapper.sh` ]; then source `which virtualenvwrapper.sh`; mkvirtualenv $(PROJECT_NAME) --python=$(PYTHON_INTERPRETER); else mkvirtualenv.bat $(PROJECT_NAME) --python=$(PYTHON_INTERPRETER); fi"
	@echo ">>> New virtualenv created. Activate with:\nworkon $(PROJECT_NAME)"
	



#################################################################################
# PROJECT RULES                                                                 #
#################################################################################


## Build the full KEPCO monthly dataset
.PHONY: data
data: reproduce-kepco-monthly


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
