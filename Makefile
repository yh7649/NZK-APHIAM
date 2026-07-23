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
test: test-kepco-ef-r
	$(PYTHON_INTERPRETER) -m pytest tests


## Run deterministic tests for KEPCO monthly EF eligibility rules
.PHONY: test-kepco-ef-r
test-kepco-ef-r:
	Rscript analysis/kepco/test_ef_eligibility.R
	Rscript analysis/kepco/test_ef_cohort_query.R


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


## Export CAPSS power-sector fuel x official technology emissions tables
.PHONY: export-capss-power-fuel-technology
export-capss-power-fuel-technology: process-capss-emissions
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.capss_power_fuel_technology \
		--start-year 2016 \
		--end-year 2023


## Download and parse CAPSS detailed annual emissions statistics
.PHONY: build-capss-emissions
build-capss-emissions: scrape-capss-emissions process-capss-emissions export-capss-power-fuel-technology


## Validate the tracked non-power sector inventory without generating outputs
.PHONY: validate-nonpower-sector-inventory
validate-nonpower-sector-inventory:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.nonpower_sector_inventory --validate-only


## Validate and export the canonical non-power sector inventory and diagnostics
.PHONY: build-nonpower-sector-inventory
build-nonpower-sector-inventory:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.nonpower_sector_inventory


## Validate tracked non-power emission-factor evidence without generating outputs
.PHONY: validate-nonpower-emission-factors
validate-nonpower-emission-factors:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.nonpower_emission_factors --validate-only


## Export provisional non-power factors, inventory links, and coverage diagnostics
.PHONY: build-nonpower-emission-factors
build-nonpower-emission-factors:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.nonpower_emission_factors


## Extract inventory-targeted pages and factor-table titles from official CAPSS VII
.PHONY: scrape-capss-vii-nonpower-efs
scrape-capss-vii-nonpower-efs:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.capss.nonpower_emission_factors


## Build the non-power inventory and provisional factor-evidence products
.PHONY: build-nonpower-emissions
build-nonpower-emissions: build-nonpower-sector-inventory build-nonpower-emission-factors


MACRO_ACTIVITY ?= data/external/macro/gcam_kaist_sector_fuel_activity.csv
MACRO_MAPPING ?=
MACRO_BASE_YEAR ?=
MACRO_SCENARIO_COLUMNS ?= scenario
MACRO_POLLUTANTS ?= SOx,NOx,NH3,VOCs,PM2.5
MACRO_GENERATION ?=
KEPCO_EF ?= results/tables/kepco/annual_handoff/kepco_annual_ef_distribution_long_by_fuel_technology.csv
CAPSS_POWER_ACTUAL ?= data/processed/capss/power_fuel_technology_2016_2023.parquet
MACRO_KEPCO_CAPSS_CROSSWALK ?= docs/references/macro/macro_kepco_capss_power_crosswalk.csv
MACRO_INGEST_SOURCE ?=
MACRO_INGEST_KIND ?= activity
MACRO_INGEST_DEST_NAME ?=
MACRO_INGEST_CONTRIBUTOR ?=
MACRO_INGEST_NOTE ?=
PENG_MVP_CONFIG ?= configs/scenarios/peng_replication_mvp.yaml
PENG_MVP_ARGS ?=
PENG_MVP_POC_ITERATIONS ?= 200


## Place a team-supplied MACRO/GCAM-KAIST file under data/external/macro/ with provenance
.PHONY: ingest-macro-external
ingest-macro-external:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.external.ingest_macro \
		$(if $(MACRO_INGEST_SOURCE),--source $(MACRO_INGEST_SOURCE),) \
		--kind $(MACRO_INGEST_KIND) \
		$(if $(MACRO_INGEST_DEST_NAME),--dest-name $(MACRO_INGEST_DEST_NAME),) \
		$(if $(MACRO_INGEST_CONTRIBUTOR),--contributor "$(MACRO_INGEST_CONTRIBUTOR)",) \
		$(if $(MACRO_INGEST_NOTE),--note "$(MACRO_INGEST_NOTE)",)


## Build the double-clickable macOS app for adding a MACRO generation file (no terminal needed afterward)
.PHONY: build-macro-generation-dropper
build-macro-generation-dropper:
	osacompile -o "tools/macos/Add MACRO Generation File.app" tools/macos/add_macro_generation_file.applescript
	@echo "Built tools/macos/Add MACRO Generation File.app"
	@echo "Drag it to the Desktop or Dock, then drop a MACRO generation file onto it any time."


## Integrate GCAM-KAIST/MACRO sector-fuel activity with CAPSS emission intensities
.PHONY: integrate-macro-inputs
integrate-macro-inputs:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.macro \
		--gcam-activity $(MACRO_ACTIVITY) \
		$(if $(MACRO_MAPPING),--mapping $(MACRO_MAPPING),) \
		$(if $(MACRO_BASE_YEAR),--base-year $(MACRO_BASE_YEAR),) \
		--scenario-columns $(MACRO_SCENARIO_COLUMNS) \
		--pollutants $(MACRO_POLLUTANTS)


## Validate 2021 MACRO generation times KEPCO EFs against CAPSS actual power emissions
.PHONY: validate-macro-2021-kepco-ef
validate-macro-2021-kepco-ef: export-capss-power-fuel-technology
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.integration.macro_kepco_validation \
		--year 2021 \
		--kepco-ef $(KEPCO_EF) \
		$(if $(MACRO_GENERATION),--macro-generation $(MACRO_GENERATION),) \
		--capss-actual $(CAPSS_POWER_ACTUAL) \
		--crosswalk $(MACRO_KEPCO_CAPSS_CROSSWALK)


## Validate 2021 observed EPSIS generation times KEPCO EFs against CAPSS actual power emissions
.PHONY: validate-epsis-2021-kepco-ef
validate-epsis-2021-kepco-ef: export-capss-power-fuel-technology
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.integration.epsis_kepco_capss_validation \
		--year 2021 \
		--kepco-ef $(KEPCO_EF) \
		--capss-actual $(CAPSS_POWER_ACTUAL)


## Audit all local inputs for the Korean thermal-power replication MVP
.PHONY: peng-mvp-audit
peng-mvp-audit:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage audit $(PENG_MVP_ARGS)


## Build fleet allocation, emissions, stack diagnostics, and InMAP point inputs
.PHONY: peng-mvp-inventory
peng-mvp-inventory:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage inventory $(PENG_MVP_ARGS)


## Install the pinned official InMAP binary and Global InMAP data in the ignored cache
.PHONY: peng-mvp-install-inmap
peng-mvp-install-inmap:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage install $(PENG_MVP_ARGS)


## Run both Global InMAP inventories with resumable input/version caching
.PHONY: peng-mvp-run-inmap
peng-mvp-run-inmap:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage run $(PENG_MVP_ARGS)


## Difference real Global InMAP outputs and aggregate South Korean exposure
.PHONY: peng-mvp-exposure
peng-mvp-exposure:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage exposure --resume $(PENG_MVP_ARGS)


## Pass real exposure through the existing verified health-impact API
.PHONY: peng-mvp-health
peng-mvp-health:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage health --resume $(PENG_MVP_ARGS)


## Execute the resumable end-to-end Korean thermal-power replication MVP
.PHONY: peng-mvp
peng-mvp:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage all --resume $(PENG_MVP_ARGS)


## Run a real-binary, fixed-iteration InMAP diagnostic; health output is prohibited
.PHONY: peng-mvp-poc
peng-mvp-poc:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage all --resume \
		--inmap-poc-iterations $(PENG_MVP_POC_ITERATIONS) $(PENG_MVP_ARGS)


## Opt in to a separately labeled, non-inferential health diagnostic from the InMAP POC
.PHONY: peng-mvp-poc-health-diagnostic
peng-mvp-poc-health-diagnostic:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage all --resume \
		--inmap-poc-iterations $(PENG_MVP_POC_ITERATIONS) \
		--write-diagnostic-poc-health $(PENG_MVP_ARGS)


## Run synthetic unit/integration tests for the replication MVP only
.PHONY: test-peng-mvp
test-peng-mvp:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m pytest \
		tests/test_peng_mvp.py tests/test_inmap_integration.py


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


## Validate KEPCO plant emission factors against tracked external literature tables
.PHONY: validate-kepco-emission-factors
validate-kepco-emission-factors:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.validation.emission_factors


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


## Download Midland Power generation data
.PHONY: scrape-midland-power-generation
scrape-midland-power-generation:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power --overwrite


## Download Midland Power generation data (reported mass is a tracked provider workbook)
.PHONY: scrape-midland-power
scrape-midland-power:
	$(MAKE) scrape-midland-power-generation


## Join Midland Power's directly reported monthly mass to monthly generation
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


HEALTH_IMPACT_INPUT ?= data/processed/health/health_impact_input.csv
HEALTH_IMPACT_OUTPUT ?= results/tables/health/attributable_deaths.csv
HEALTH_IMPACT_CRF_ID ?= krewski_2009_acs_extended
HEALTH_IMPACT_MODE ?= totals
HEALTH_IMPACT_BASELINE_SCENARIO ?=
HEALTH_IMPACT_COMPARISON_SCENARIO ?=


## Compute PM2.5-attributable deaths from a tidy scenario CSV (see docs/methods/health_impact_assessment.md)
.PHONY: health-impact
health-impact:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health \
		--input $(HEALTH_IMPACT_INPUT) \
		--output $(HEALTH_IMPACT_OUTPUT) \
		--crf-id $(HEALTH_IMPACT_CRF_ID) \
		--mode $(HEALTH_IMPACT_MODE) \
		$(if $(HEALTH_IMPACT_BASELINE_SCENARIO),--baseline-scenario $(HEALTH_IMPACT_BASELINE_SCENARIO),) \
		$(if $(HEALTH_IMPACT_COMPARISON_SCENARIO),--comparison-scenario $(HEALTH_IMPACT_COMPARISON_SCENARIO),)


## Run health-impact assessment tests only (CRF, attributable deaths, decomposition)
.PHONY: test-health
test-health:
	$(PYTHON_INTERPRETER) -m pytest tests/test_health_crf.py tests/test_health_impact.py tests/test_health_decomposition.py


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
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.thermal.midland_power --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.archive.annual_panel.scrape.epsis --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.airkorea --help
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.health.kosis --help
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
