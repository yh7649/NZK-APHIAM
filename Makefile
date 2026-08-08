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
	

## Install R analysis dependencies (pinned CRAN versions + GitHub-only packages)
.PHONY: requirements-r
requirements-r:
	Rscript requirements/install_r.R


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


## Scrape official CAPSS VII pages, raw table cells, normalized candidates, and inventory links
.PHONY: scrape-capss-vii-nonpower-efs
scrape-capss-vii-nonpower-efs:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.capss.nonpower_emission_factors


## Verify the preserved handbook against the current official download, then scrape it
.PHONY: scrape-capss-vii-nonpower-efs-verified
scrape-capss-vii-nonpower-efs-verified:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.capss.nonpower_emission_factors \
		--verify-official-source


## Scrape CAPSS VII and build the tracked non-power inventory and factor-evidence products
.PHONY: build-nonpower-emissions
build-nonpower-emissions: scrape-capss-vii-nonpower-efs build-nonpower-sector-inventory build-nonpower-emission-factors


MODEL_INPUT_SCENARIO ?= team_handoff
MODEL_INPUT_SOURCE_MODEL ?= macro
MACRO_ACTIVITY ?= model_inputs/scenarios/$(MODEL_INPUT_SCENARIO)/upstream/gcam_kaist/gcam_kaist_sector_fuel_activity.csv
MACRO_APHIAM_INPUT_DIR ?= model_inputs/scenarios/$(MODEL_INPUT_SCENARIO)/aphiam
MACRO_MAPPING ?=
MACRO_BASE_YEAR ?=
MACRO_SCENARIO_COLUMNS ?= scenario
MACRO_POLLUTANTS ?= SOx,NOx,NH3,VOCs,PM2.5
MACRO_GENERATION ?= model_inputs/scenarios/peng_replication_mvp/upstream/macro/generation_by_province_long.csv
KEPCO_EF ?= data/processed/kepco/emission_factors/kepco_annual_ef_distribution_long_by_fuel_technology.csv
CAPSS_POWER_ACTUAL ?= data/processed/capss/power_fuel_technology_2016_2023.parquet
MACRO_KEPCO_CAPSS_CROSSWALK ?= docs/references/macro/macro_kepco_capss_power_crosswalk.csv
MODEL_INPUT_SOURCE ?=
MODEL_INPUT_KIND ?= activity
MODEL_INPUT_DEST_NAME ?=
MODEL_INPUT_CONTRIBUTOR ?=
MODEL_INPUT_NOTE ?=
MODEL_INPUT_FORCE ?=
MODEL_INPUT_UPSTREAM_SCENARIO ?=
GCAM_XML_SOURCE ?= model_inputs/scenarios/team_handoff/upstream/gcam_kaist/nzk/CORE_9_NZ_2026-8-7T12_32_50+09_00.xml.zip
GCAM_XML_UPSTREAM_SCENARIO ?= nzk
GCAM_XML_SCENARIO_LABEL ?= nzk
GCAM_XML_YEARS ?= 2021,2025,2030,2035,2040,2045,2050
GCAM_NZK_APHIAM_OUTPUT ?= model_inputs/scenarios/team_handoff/aphiam/gcam_kaist/nzk
MACRO_NONPOWER_PROXY_CONFIG ?= configs/scenarios/gcam_kaist_nonpower_proxy_2025_2050.yaml
MACRO_NONPOWER_PROXY_OUTPUT ?= model_inputs/scenarios/nonpower_proxy_2025_2050/aphiam
MACRO_NONPOWER_PROXY_CAPSS ?= data/interim/capss/emissions_statistics/capss_emissions_tidy.parquet
INMAP_COMBINED_CONFIG ?= configs/scenarios/inmap_combined_proxy_2025_2050.yaml
INMAP_COMBINED_OUTPUT ?= data/processed/inmap/combined_proxy_2025_2050
INMAP_INSTALLATION_MANIFEST ?= .cache/inmap/installation_manifest.json
INMAP_COMBINED_RUN_ROOT ?= results/runs/inmap/combined_proxy_2025_2050
INMAP_COMBINED_POC_ITERATIONS ?= 200
INMAP_COMBINED_FAST_POC_ITERATIONS ?= 50
INMAP_COMBINED_PARALLEL_WORKERS ?= 2
INMAP_COMBINED_HEALTH_CONFIG ?= configs/scenarios/peng_replication_mvp.yaml
INMAP_COMBINED_FIGURE_ROOT ?= results/figures/inmap/combined_proxy_2025_2050
INMAP_COMBINED_TABLE_ROOT ?= results/tables/inmap/combined_proxy_2025_2050
INMAP_GCAM_NZK_CONFIG ?= configs/scenarios/gcam_nzk_power_toggle_2025_2050.yaml
INMAP_GCAM_NZK_OUTPUT ?= data/processed/inmap/gcam_nzk_power_toggle_2025_2050
INMAP_GCAM_NZK_POC_CONFIG ?= configs/scenarios/gcam_nzk_three_power_poc_2025_2050.yaml
INMAP_GCAM_NZK_POC_OUTPUT ?= data/processed/inmap/gcam_nzk_three_power_poc_2025_2050
INMAP_GCAM_NZK_POC_RUN_ROOT ?= results/runs/inmap/gcam_nzk_three_power_poc_2025_2050
INMAP_GCAM_NZK_POC_ITERATIONS ?= 50
INMAP_GCAM_NZK_POC_WORKERS ?= 2
INMAP_GCAM_NZK_POC_HEALTH_CONFIG ?= configs/scenarios/peng_replication_mvp.yaml
INMAP_GCAM_NZK_POC_FIGURE_ROOT ?= results/figures/inmap/gcam_nzk_three_power_poc_2025_2050
INMAP_GCAM_NZK_POC_TABLE_ROOT ?= results/tables/inmap/gcam_nzk_three_power_poc_2025_2050
INMAP_GCAM_NZK_POC_VIDEO_ROOT ?= results/videos/inmap/gcam_nzk_three_power_poc_2025_2050
INMAP_GCAM_NZK_POWER_ONLY_YEAR ?= 2050
INMAP_GCAM_NZK_POWER_ONLY_RUN_DIR ?= $(INMAP_GCAM_NZK_POC_RUN_ROOT)/power_only_poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations
INMAP_GCAM_NZK_POWER_ONLY_FIGURE_DIR ?= $(INMAP_GCAM_NZK_POC_FIGURE_ROOT)/power_only_poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations
INMAP_GCAM_NZK_POWER_ONLY_TABLE_DIR ?= $(INMAP_GCAM_NZK_POC_TABLE_ROOT)/power_only_poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations
GCAM_XML_REFERENCE_SOURCE ?= model_inputs/scenarios/team_handoff/upstream/gcam_kaist/reference/gcam9_ref.xml.zip
GCAM_XML_REFERENCE_SCENARIO_LABEL ?= reference
GCAM_REFERENCE_APHIAM_OUTPUT ?= model_inputs/scenarios/team_handoff/aphiam/gcam_kaist/reference
GCAM_REFERENCE_VS_NZK_NONPOWER_MERGED ?= model_inputs/scenarios/team_handoff/aphiam/gcam_kaist/reference_vs_nzk/maximum_coverage_poc_projected_emissions.csv
INMAP_REFVSNZK_CONFIG ?= configs/scenarios/gcam_reference_vs_nzk_poc_2025_2050.yaml
INMAP_REFVSNZK_OUTPUT ?= data/processed/inmap/gcam_reference_vs_nzk_poc_2025_2050
INMAP_REFVSNZK_RUN_ROOT ?= results/runs/inmap/gcam_reference_vs_nzk_poc_2025_2050
INMAP_REFVSNZK_ITERATIONS ?= 20
INMAP_REFVSNZK_WORKERS ?= 2
INMAP_REFVSNZK_HEALTH_CONFIG ?= configs/scenarios/peng_replication_mvp.yaml
INMAP_REFVSNZK_FIGURE_ROOT ?= results/figures/inmap/gcam_reference_vs_nzk_poc_2025_2050
INMAP_REFVSNZK_TABLE_ROOT ?= results/tables/inmap/gcam_reference_vs_nzk_poc_2025_2050
PENG_MVP_CONFIG ?= configs/scenarios/peng_replication_mvp.yaml
PENG_MVP_ARGS ?=
PENG_MVP_POC_ITERATIONS ?= 200
KEPCO_POC_SCENARIO_CONFIG ?= configs/scenarios/kepco_poc_fleet_scenarios.yaml
KEPCO_POC_SCENARIO_OUTPUT ?= data/processed/kepco/scenarios/poc_2025_2050
KEPCO_POC_SCENARIO_FIGURES ?= results/figures/kepco/poc_scenarios
KEPCO_POC_RETIREMENT_CONFIG ?= configs/scenarios/kepco_poc_fleet_retirement_scenarios.yaml
KEPCO_POC_RETIREMENT_OUTPUT ?= data/processed/kepco/scenarios/poc_2025_2050_unit_retirement
KEPCO_POC_RETIREMENT_FIGURES ?= results/figures/kepco/poc_scenarios_unit_retirement


## Add a mutable MACRO/GCAM-KAIST handoff to a named model-input scenario bundle
.PHONY: ingest-model-input
ingest-model-input:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.model_inputs.ingest_macro \
		$(if $(MODEL_INPUT_SOURCE),--source $(MODEL_INPUT_SOURCE),) \
		--kind $(MODEL_INPUT_KIND) \
		--scenario-bundle $(MODEL_INPUT_SCENARIO) \
		--source-model $(MODEL_INPUT_SOURCE_MODEL) \
		$(if $(MODEL_INPUT_DEST_NAME),--dest-name $(MODEL_INPUT_DEST_NAME),) \
		$(if $(MODEL_INPUT_CONTRIBUTOR),--contributor "$(MODEL_INPUT_CONTRIBUTOR)",) \
		$(if $(MODEL_INPUT_NOTE),--note "$(MODEL_INPUT_NOTE)",) \
		$(if $(MODEL_INPUT_UPSTREAM_SCENARIO),--upstream-scenario $(MODEL_INPUT_UPSTREAM_SCENARIO),) \
		$(if $(MODEL_INPUT_FORCE),--force,)


## Validate and ingest a GCAM XML/ZIP handoff under its upstream scenario directory
.PHONY: ingest-gcam-xml
ingest-gcam-xml:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.model_inputs.ingest_macro \
		$(if $(MODEL_INPUT_SOURCE),--source $(MODEL_INPUT_SOURCE),) \
		--kind gcam_xml_archive \
		--scenario-bundle $(MODEL_INPUT_SCENARIO) \
		--source-model gcam_kaist \
		--upstream-scenario $(GCAM_XML_UPSTREAM_SCENARIO) \
		$(if $(MODEL_INPUT_DEST_NAME),--dest-name $(MODEL_INPUT_DEST_NAME),) \
		$(if $(MODEL_INPUT_CONTRIBUTOR),--contributor "$(MODEL_INPUT_CONTRIBUTOR)",) \
		$(if $(MODEL_INPUT_NOTE),--note "$(MODEL_INPUT_NOTE)",) \
		$(if $(MODEL_INPUT_FORCE),--force,)


## Validate the GCAM NZK archive and report its scenario, years, regions, and model version
.PHONY: inspect-gcam-nzk
inspect-gcam-nzk:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.model_inputs.gcam_xml \
		--source $(GCAM_XML_SOURCE) \
		--inspect-only


## Extract the large GCAM NZK XML directly from ZIP into APHIAM activity and native-emissions tables
.PHONY: extract-gcam-nzk
extract-gcam-nzk:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.model_inputs.gcam_xml \
		--source $(GCAM_XML_SOURCE) \
		--output-dir $(GCAM_NZK_APHIAM_OUTPUT) \
		--scenario-label $(GCAM_XML_SCENARIO_LABEL) \
		--years $(GCAM_XML_YEARS)


## Map GCAM NZK activity and build approved, candidate, and maximum-coverage POC interfaces
.PHONY: build-gcam-nzk-nonpower-interface
build-gcam-nzk-nonpower-interface: extract-gcam-nzk build-nonpower-emission-factors build-gcam-nzk-spatial-interface
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.nonpower_native \
		--output-dir $(GCAM_NZK_APHIAM_OUTPUT)


## Build CAPSS administrative spatial weights and audit missing InMAP coordinate geometry
.PHONY: build-gcam-nzk-spatial-interface
build-gcam-nzk-spatial-interface:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.nonpower_spatial \
		--output-dir $(GCAM_NZK_APHIAM_OUTPUT)


## Build the complete fail-closed GCAM NZK activity, factor, and spatial interface
.PHONY: build-gcam-nzk-interface
build-gcam-nzk-interface: build-gcam-nzk-nonpower-interface build-gcam-nzk-spatial-interface


## Track a large GCAM XML archive with DVC after ingestion
.PHONY: track-gcam-xml
track-gcam-xml:
	$(DVC) add $(GCAM_XML_SOURCE)
	@echo "Commit the generated .dvc pointer and local .gitignore; run dvc push after configuring a remote."


## Attempt the NZK power-plant on/off InMAP bundle; fails closed until factors and geometry are ready
.PHONY: build-inmap-gcam-nzk-toggle
build-inmap-gcam-nzk-toggle: build-gcam-nzk-interface
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_inventory \
		--config $(INMAP_GCAM_NZK_CONFIG) \
		--output-dir $(INMAP_GCAM_NZK_OUTPUT)


## Build the three-power-pathway GCAM NZK maximum-coverage POC input bundle
.PHONY: build-inmap-gcam-nzk-poc-inputs
build-inmap-gcam-nzk-poc-inputs: build-gcam-nzk-nonpower-interface kepco-poc-scenarios
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_inventory \
		--config $(INMAP_GCAM_NZK_POC_CONFIG) \
		--output-dir $(INMAP_GCAM_NZK_POC_OUTPUT)


## Prepare fixed-iteration InMAP jobs for the three-power-pathway GCAM NZK POC
.PHONY: inmap-gcam-nzk-poc-prepare
inmap-gcam-nzk-poc-prepare: build-inmap-gcam-nzk-poc-inputs
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner prepare \
		--bundle-dir $(INMAP_GCAM_NZK_POC_OUTPUT) \
		--installation-manifest $(INMAP_INSTALLATION_MANIFEST) \
		--run-dir $(INMAP_GCAM_NZK_POC_RUN_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations \
		--num-iterations $(INMAP_GCAM_NZK_POC_ITERATIONS)


## Build and run all 18 GCAM NZK plus simulated-power proof-of-concept jobs
.PHONY: inmap-gcam-nzk-poc
inmap-gcam-nzk-poc: inmap-gcam-nzk-poc-prepare
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner run \
			--job-manifest $(INMAP_GCAM_NZK_POC_RUN_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations/run_jobs.json \
			--max-workers $(INMAP_GCAM_NZK_POC_WORKERS)


## Run BenMAP-equivalent health diagnostics and make presentation figures, GIFs, and MP4s
.PHONY: inmap-gcam-nzk-poc-health
inmap-gcam-nzk-poc-health:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_inmap \
		--job-manifest $(INMAP_GCAM_NZK_POC_RUN_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations/run_jobs.json \
		--config $(INMAP_GCAM_NZK_POC_HEALTH_CONFIG) \
		--output-dir $(INMAP_GCAM_NZK_POC_RUN_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations/health \
		--allow-nonconverged-diagnostic \
		--reference-scenario nzk_nonpower_no_nzk_power
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_report \
		--health-dir $(INMAP_GCAM_NZK_POC_RUN_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations/health \
		--figure-dir $(INMAP_GCAM_NZK_POC_FIGURE_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations \
		--table-dir $(INMAP_GCAM_NZK_POC_TABLE_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.gcam_nzk_presentation \
		--job-manifest $(INMAP_GCAM_NZK_POC_RUN_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations/run_jobs.json \
		--config $(INMAP_GCAM_NZK_POC_HEALTH_CONFIG) \
		--figure-dir $(INMAP_GCAM_NZK_POC_FIGURE_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations \
		--video-dir $(INMAP_GCAM_NZK_POC_VIDEO_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations \
		--table-dir $(INMAP_GCAM_NZK_POC_TABLE_ROOT)/poc_$(INMAP_GCAM_NZK_POC_ITERATIONS)_iterations


## Run the GCAM-NZK POC, BenMAP-equivalent diagnostics, and presentation package
.PHONY: inmap-gcam-nzk-poc-with-health
inmap-gcam-nzk-poc-with-health: inmap-gcam-nzk-poc inmap-gcam-nzk-poc-health


## Prepare two power-only 2050 jobs: current thermal pathway versus complete shutdown
.PHONY: inmap-gcam-nzk-power-only-poc-prepare
inmap-gcam-nzk-power-only-poc-prepare:
	@test -f $(INMAP_GCAM_NZK_POC_OUTPUT)/combined_inmap_input_manifest.json || \
		{ echo "Missing GCAM-NZK POC inputs; run make build-inmap-gcam-nzk-poc-inputs first."; exit 1; }
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner prepare \
		--bundle-dir $(INMAP_GCAM_NZK_POC_OUTPUT) \
		--installation-manifest $(INMAP_INSTALLATION_MANIFEST) \
		--run-dir $(INMAP_GCAM_NZK_POWER_ONLY_RUN_DIR) \
		--num-iterations $(INMAP_GCAM_NZK_POC_ITERATIONS) \
		--power-only \
		--scenario nzk_nonpower_no_nzk_power \
		--scenario nzk_nonpower_high_nzk_power \
		--year $(INMAP_GCAM_NZK_POWER_ONLY_YEAR)


## Run the two-job thermal-power-only InMAP shutdown diagnostic
.PHONY: inmap-gcam-nzk-power-only-poc
inmap-gcam-nzk-power-only-poc: inmap-gcam-nzk-power-only-poc-prepare
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner run \
		--job-manifest $(INMAP_GCAM_NZK_POWER_ONLY_RUN_DIR)/run_jobs.json \
		--max-workers $(INMAP_GCAM_NZK_POC_WORKERS)


## Calculate power-only mortality and write diagnostic figures and tables
.PHONY: inmap-gcam-nzk-power-only-poc-health
inmap-gcam-nzk-power-only-poc-health: inmap-gcam-nzk-power-only-poc
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_inmap \
		--job-manifest $(INMAP_GCAM_NZK_POWER_ONLY_RUN_DIR)/run_jobs.json \
		--config $(INMAP_GCAM_NZK_POC_HEALTH_CONFIG) \
		--output-dir $(INMAP_GCAM_NZK_POWER_ONLY_RUN_DIR)/health \
		--allow-nonconverged-diagnostic \
		--reference-scenario nzk_nonpower_no_nzk_power
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_report \
		--health-dir $(INMAP_GCAM_NZK_POWER_ONLY_RUN_DIR)/health \
		--figure-dir $(INMAP_GCAM_NZK_POWER_ONLY_FIGURE_DIR) \
		--table-dir $(INMAP_GCAM_NZK_POWER_ONLY_TABLE_DIR)


## Run the 2050 thermal-power-only shutdown diagnostic through health in one command
.PHONY: inmap-gcam-nzk-power-only-poc-with-health
inmap-gcam-nzk-power-only-poc-with-health: inmap-gcam-nzk-power-only-poc-health


## Validate the GCAM Reference archive and report its scenario, years, regions, and model version
.PHONY: inspect-gcam-reference
inspect-gcam-reference:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.model_inputs.gcam_xml \
		--source $(GCAM_XML_REFERENCE_SOURCE) \
		--inspect-only


## Extract the large GCAM Reference XML directly from ZIP into APHIAM activity and native-emissions tables
.PHONY: extract-gcam-reference
extract-gcam-reference:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.model_inputs.gcam_xml \
		--source $(GCAM_XML_REFERENCE_SOURCE) \
		--output-dir $(GCAM_REFERENCE_APHIAM_OUTPUT) \
		--scenario-label $(GCAM_XML_REFERENCE_SCENARIO_LABEL) \
		--years $(GCAM_XML_YEARS)


## Map GCAM Reference activity through the same maximum-coverage POC ladder used for NZK
.PHONY: build-gcam-reference-nonpower-interface
build-gcam-reference-nonpower-interface: extract-gcam-reference build-nonpower-emission-factors
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.nonpower_native \
		--activity $(GCAM_REFERENCE_APHIAM_OUTPUT)/gcam_kaist_reference_activity.parquet \
		--native-emissions $(GCAM_REFERENCE_APHIAM_OUTPUT)/gcam_kaist_reference_native_emissions.parquet \
		--output-dir $(GCAM_REFERENCE_APHIAM_OUTPUT) \
		--capss-admin-weights $(GCAM_NZK_APHIAM_OUTPUT)/capss_2021_admin_surrogate_weights.parquet


## Merge the independently-mapped Reference and NZK non-power projections into one file
## (checks for both interfaces instead of rebuilding them, since each rebuild re-parses a
## 2GB+ GCAM XML archive from scratch; run the two build-* targets above first if missing)
.PHONY: merge-gcam-reference-vs-nzk-nonpower
merge-gcam-reference-vs-nzk-nonpower:
	@test -f $(GCAM_REFERENCE_APHIAM_OUTPUT)/maximum_coverage_poc_projected_emissions.csv || \
		{ echo "Missing GCAM Reference non-power interface; run make build-gcam-reference-nonpower-interface first."; exit 1; }
	@test -f $(GCAM_NZK_APHIAM_OUTPUT)/maximum_coverage_poc_projected_emissions.csv || \
		{ echo "Missing GCAM NZK non-power interface; run make build-gcam-nzk-nonpower-interface first."; exit 1; }
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.merge_nonpower_scenarios \
		--input $(GCAM_REFERENCE_APHIAM_OUTPUT)/maximum_coverage_poc_projected_emissions.csv \
		--input $(GCAM_NZK_APHIAM_OUTPUT)/maximum_coverage_poc_projected_emissions.csv \
		--output $(GCAM_REFERENCE_VS_NZK_NONPOWER_MERGED)


## Build the no_nzk+Reference vs nzk_high+NZK InMAP input bundle (2 scenario-years by default)
## (checks for the merged non-power file and KEPCO fixture instead of rebuilding them; run
## make merge-gcam-reference-vs-nzk-nonpower / make kepco-poc-scenarios first if missing)
.PHONY: build-inmap-reference-vs-nzk-poc-inputs
build-inmap-reference-vs-nzk-poc-inputs:
	@test -f $(GCAM_REFERENCE_VS_NZK_NONPOWER_MERGED) || \
		{ echo "Missing merged reference-vs-NZK non-power projections; run make merge-gcam-reference-vs-nzk-nonpower first."; exit 1; }
	@test -f $(KEPCO_POC_SCENARIO_OUTPUT)/macro_generation_scenarios_2025_2050.csv || \
		{ echo "Missing KEPCO POC power scenarios; run make kepco-poc-scenarios first."; exit 1; }
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_inventory \
		--config $(INMAP_REFVSNZK_CONFIG) \
		--output-dir $(INMAP_REFVSNZK_OUTPUT)


## Prepare the fixed-iteration InMAP jobs for the reference-vs-NZK comparison
.PHONY: inmap-reference-vs-nzk-poc-prepare
inmap-reference-vs-nzk-poc-prepare: build-inmap-reference-vs-nzk-poc-inputs
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner prepare \
		--bundle-dir $(INMAP_REFVSNZK_OUTPUT) \
		--installation-manifest $(INMAP_INSTALLATION_MANIFEST) \
		--run-dir $(INMAP_REFVSNZK_RUN_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations \
		--num-iterations $(INMAP_REFVSNZK_ITERATIONS)


## Run the no_nzk+Reference vs nzk_high+NZK InMAP jobs
.PHONY: inmap-reference-vs-nzk-poc
inmap-reference-vs-nzk-poc: inmap-reference-vs-nzk-poc-prepare
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner run \
		--job-manifest $(INMAP_REFVSNZK_RUN_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations/run_jobs.json \
		--max-workers $(INMAP_REFVSNZK_WORKERS)


## Calculate diagnostic mortality and write the PM2.5/mortality figures, tables, and Korea maps
.PHONY: inmap-reference-vs-nzk-poc-health
inmap-reference-vs-nzk-poc-health: inmap-reference-vs-nzk-poc
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_inmap \
		--job-manifest $(INMAP_REFVSNZK_RUN_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations/run_jobs.json \
		--config $(INMAP_REFVSNZK_HEALTH_CONFIG) \
		--output-dir $(INMAP_REFVSNZK_RUN_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations/health \
		--allow-nonconverged-diagnostic \
		--reference-scenario no_nzk
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_report \
		--health-dir $(INMAP_REFVSNZK_RUN_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations/health \
		--figure-dir $(INMAP_REFVSNZK_FIGURE_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations \
		--table-dir $(INMAP_REFVSNZK_TABLE_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.scenario_pm25_maps \
		--job-manifest $(INMAP_REFVSNZK_RUN_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations/run_jobs.json \
		--config $(INMAP_REFVSNZK_HEALTH_CONFIG) \
		--figure-dir $(INMAP_REFVSNZK_FIGURE_ROOT)/poc_$(INMAP_REFVSNZK_ITERATIONS)_iterations \
		--reference-scenario no_nzk


## Run the reference-vs-NZK POC end to end: inputs, InMAP, health, figures, and tables
.PHONY: inmap-reference-vs-nzk-poc-with-health
inmap-reference-vs-nzk-poc-with-health: inmap-reference-vs-nzk-poc-health


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
		--output-dir $(MACRO_APHIAM_INPUT_DIR) \
		--scenario-columns $(MACRO_SCENARIO_COLUMNS) \
		--pollutants $(MACRO_POLLUTANTS)


## Build a synthetic GCAM-KAIST-shaped non-power activity fixture for pipeline testing
.PHONY: build-macro-nonpower-proxy
build-macro-nonpower-proxy:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.macro.proxy_activity \
		--config $(MACRO_NONPOWER_PROXY_CONFIG) \
		--output-dir $(MACRO_NONPOWER_PROXY_OUTPUT)


## Smoke-test the synthetic non-power fixture through the CAPSS intensity integrator
.PHONY: validate-macro-nonpower-proxy
validate-macro-nonpower-proxy: build-macro-nonpower-proxy
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.process.macro \
		--gcam-activity $(MACRO_NONPOWER_PROXY_OUTPUT)/gcam_kaist_sector_fuel_activity_proxy_2023_2050.csv \
		--capss-emissions $(MACRO_NONPOWER_PROXY_CAPSS) \
		--output-dir $(MACRO_NONPOWER_PROXY_OUTPUT)/integration \
		--base-year 2023 \
		--scenario-columns scenario \
		--pollutants $(MACRO_POLLUTANTS)


## Build point-plus-grid InMAP inputs from the paired power and non-power fixtures
.PHONY: build-inmap-combined-inputs
build-inmap-combined-inputs: kepco-poc-scenarios validate-macro-nonpower-proxy build-nonpower-emission-factors
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_inventory \
		--config $(INMAP_COMBINED_CONFIG) \
		--output-dir $(INMAP_COMBINED_OUTPUT)


## Write strict-convergence TOMLs for every combined scenario-year
.PHONY: inmap-combined-prepare
inmap-combined-prepare: build-inmap-combined-inputs
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner prepare \
		--bundle-dir $(INMAP_COMBINED_OUTPUT) \
		--installation-manifest $(INMAP_INSTALLATION_MANIFEST) \
		--run-dir $(INMAP_COMBINED_RUN_ROOT)/strict \
		--num-iterations 0


## Run all strict-convergence combined scenarios sequentially and resumably
.PHONY: inmap-combined-run
inmap-combined-run: inmap-combined-prepare
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner run \
		--job-manifest $(INMAP_COMBINED_RUN_ROOT)/strict/run_jobs.json


## Resume prepared strict jobs with bounded scenario-level parallelism
.PHONY: inmap-combined-run-parallel
inmap-combined-run-parallel:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner run \
		--job-manifest $(INMAP_COMBINED_RUN_ROOT)/strict/run_jobs.json \
		--max-workers $(INMAP_COMBINED_PARALLEL_WORKERS)


## Write fixed-iteration proof-of-concept TOMLs for every combined scenario-year
.PHONY: inmap-combined-poc-prepare
inmap-combined-poc-prepare: build-inmap-combined-inputs
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner prepare \
		--bundle-dir $(INMAP_COMBINED_OUTPUT) \
		--installation-manifest $(INMAP_INSTALLATION_MANIFEST) \
		--run-dir $(INMAP_COMBINED_RUN_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations \
		--num-iterations $(INMAP_COMBINED_POC_ITERATIONS)


## Run all combined scenarios as a quick non-analytical plumbing proof
.PHONY: inmap-combined-poc
inmap-combined-poc: inmap-combined-poc-prepare
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner run \
		--job-manifest $(INMAP_COMBINED_RUN_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations/run_jobs.json


## Resume the prepared POC with bounded scenario-level parallelism
.PHONY: inmap-combined-poc-parallel
inmap-combined-poc-parallel:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.inmap.combined_runner run \
		--job-manifest $(INMAP_COMBINED_RUN_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations/run_jobs.json \
		--max-workers $(INMAP_COMBINED_PARALLEL_WORKERS)


## Post-process completed strict combined runs into screening mortality outputs
.PHONY: inmap-combined-health
inmap-combined-health:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_inmap \
		--job-manifest $(INMAP_COMBINED_RUN_ROOT)/strict/run_jobs.json \
		--config $(INMAP_COMBINED_HEALTH_CONFIG) \
		--output-dir $(INMAP_COMBINED_RUN_ROOT)/strict/health
	$(MAKE) inmap-combined-report \
		PYTHON_INTERPRETER=$(PYTHON_INTERPRETER)


## Post-process completed POC runs into explicitly non-converged mortality diagnostics
.PHONY: inmap-combined-poc-health
inmap-combined-poc-health:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_inmap \
		--job-manifest $(INMAP_COMBINED_RUN_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations/run_jobs.json \
		--config $(INMAP_COMBINED_HEALTH_CONFIG) \
		--output-dir $(INMAP_COMBINED_RUN_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations/health \
		--allow-nonconverged-diagnostic
	$(MAKE) inmap-combined-poc-report \
		PYTHON_INTERPRETER=$(PYTHON_INTERPRETER) \
		INMAP_COMBINED_POC_ITERATIONS=$(INMAP_COMBINED_POC_ITERATIONS)


## Create presentation-ready tables and figures from completed strict health outputs
.PHONY: inmap-combined-report
inmap-combined-report:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_report \
		--health-dir $(INMAP_COMBINED_RUN_ROOT)/strict/health \
		--figure-dir $(INMAP_COMBINED_FIGURE_ROOT)/strict \
		--table-dir $(INMAP_COMBINED_TABLE_ROOT)/strict


## Create presentation-ready tables and figures from completed POC health outputs
.PHONY: inmap-combined-poc-report
inmap-combined-poc-report:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.health.combined_report \
		--health-dir $(INMAP_COMBINED_RUN_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations/health \
		--figure-dir $(INMAP_COMBINED_FIGURE_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations \
		--table-dir $(INMAP_COMBINED_TABLE_ROOT)/poc_$(INMAP_COMBINED_POC_ITERATIONS)_iterations


## Run all POC scenarios, then calculate the labeled mortality diagnostics
.PHONY: inmap-combined-poc-with-health
inmap-combined-poc-with-health: inmap-combined-poc inmap-combined-poc-health


## Resume POC jobs in parallel, then calculate mortality diagnostics
.PHONY: inmap-combined-poc-parallel-with-health
inmap-combined-poc-parallel-with-health: inmap-combined-poc-parallel inmap-combined-poc-health


## Prepare and run a separate 50-iteration parallel POC, then calculate mortality
.PHONY: inmap-combined-fast-poc
inmap-combined-fast-poc:
	$(MAKE) inmap-combined-poc-prepare \
		PYTHON_INTERPRETER=$(PYTHON_INTERPRETER) \
		INMAP_COMBINED_POC_ITERATIONS=$(INMAP_COMBINED_FAST_POC_ITERATIONS)
	$(MAKE) inmap-combined-poc-parallel \
		PYTHON_INTERPRETER=$(PYTHON_INTERPRETER) \
		INMAP_COMBINED_POC_ITERATIONS=$(INMAP_COMBINED_FAST_POC_ITERATIONS)


.PHONY: inmap-combined-fast-poc-with-health
inmap-combined-fast-poc-with-health: inmap-combined-fast-poc
	$(MAKE) inmap-combined-poc-health \
		PYTHON_INTERPRETER=$(PYTHON_INTERPRETER) \
		INMAP_COMBINED_POC_ITERATIONS=$(INMAP_COMBINED_FAST_POC_ITERATIONS)


## Validate 2021 MACRO generation times KEPCO EFs against CAPSS actual power emissions
.PHONY: validate-macro-2021-kepco-ef
validate-macro-2021-kepco-ef: build-kepco-emission-factors export-capss-power-fuel-technology
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.integration.macro_kepco_validation \
		--year 2021 \
		--kepco-ef $(KEPCO_EF) \
		$(if $(MACRO_GENERATION),--macro-generation $(MACRO_GENERATION),) \
		--capss-actual $(CAPSS_POWER_ACTUAL) \
		--crosswalk $(MACRO_KEPCO_CAPSS_CROSSWALK)


## Validate 2021 observed EPSIS generation times KEPCO EFs against CAPSS actual power emissions
.PHONY: validate-epsis-2021-kepco-ef
validate-epsis-2021-kepco-ef: build-kepco-emission-factors export-capss-power-fuel-technology
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.integration.epsis_kepco_capss_validation \
		--year 2021 \
		--kepco-ef $(KEPCO_EF) \
		--capss-actual $(CAPSS_POWER_ACTUAL)


## Audit all local inputs for the Korean thermal-power replication MVP
.PHONY: peng-mvp-audit
peng-mvp-audit: build-kepco-emission-factors
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage audit $(PENG_MVP_ARGS)


## Build lightweight KEPCO-only 2025--2050 thermal fleet scenarios for pipeline testing
.PHONY: kepco-poc-scenarios
kepco-poc-scenarios:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.fleet.poc_scenarios \
		--config $(KEPCO_POC_SCENARIO_CONFIG) \
		--output-dir $(KEPCO_POC_SCENARIO_OUTPUT) \
		--figure-dir $(KEPCO_POC_SCENARIO_FIGURES)


## Build separate whole-unit KEPCO retirement scenarios; preserve the proportional fixtures
.PHONY: kepco-poc-retirement-scenarios
kepco-poc-retirement-scenarios:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.fleet.poc_scenarios \
		--config $(KEPCO_POC_RETIREMENT_CONFIG) \
		--output-dir $(KEPCO_POC_RETIREMENT_OUTPUT) \
		--figure-dir $(KEPCO_POC_RETIREMENT_FIGURES)


## Build fleet allocation, emissions, stack diagnostics, and InMAP point inputs
.PHONY: peng-mvp-inventory
peng-mvp-inventory: build-kepco-emission-factors
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


## Evaluate the full CRF specification suite from completed InMAP scenario exposure
.PHONY: peng-mvp-health
peng-mvp-health:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage health --resume $(PENG_MVP_ARGS)


## Execute the resumable end-to-end Korean thermal-power replication MVP
.PHONY: peng-mvp
peng-mvp: build-kepco-emission-factors
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage all --resume $(PENG_MVP_ARGS)


## Run a real-binary, fixed-iteration InMAP diagnostic; health output is prohibited
.PHONY: peng-mvp-poc
peng-mvp-poc: build-kepco-emission-factors
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.mvp.peng_replication \
		--config $(PENG_MVP_CONFIG) --stage all --resume \
		--inmap-poc-iterations $(PENG_MVP_POC_ITERATIONS) $(PENG_MVP_ARGS)


## Opt in to a separately labeled, non-inferential health diagnostic from the InMAP POC
.PHONY: peng-mvp-poc-health-diagnostic
peng-mvp-poc-health-diagnostic: build-kepco-emission-factors
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
		data/raw/kepco_subsidiaries/midland_power/generation
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
AIRKOREA_WORKFLOW_ARGS ?=
AIRKOREA_INMAP_GRID ?=
AIRKOREA_GRID_YEAR ?=


## Download finalized hourly monitor-level air quality archives from AirKorea
.PHONY: scrape-airkorea
scrape-airkorea:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.data.scrape.airkorea --start-year $(AIRKOREA_START_YEAR) $(if $(AIRKOREA_END_YEAR),--end-year $(AIRKOREA_END_YEAR),)


## Standardize/merge AirKorea workbooks into row-preserving Parquet and build the coordinate crosswalk
.PHONY: airkorea-canonicalize
airkorea-canonicalize:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.monitor_workflow canonicalize $(AIRKOREA_WORKFLOW_ARGS)


## Apply rule flags, out-of-fold random-forest QC, and spatial confirmation to canonical AirKorea data
.PHONY: airkorea-clean
airkorea-clean:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.monitor_workflow clean $(AIRKOREA_WORKFLOW_ARGS)


## Build canonical monthly data and EPA-style annual AirKorea PM monitor means
.PHONY: airkorea-aggregate
airkorea-aggregate:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.monitor_workflow aggregate $(AIRKOREA_WORKFLOW_ARGS)


## Run the complete resumable AirKorea monitor workflow, with optional InMAP bias grid
.PHONY: airkorea-monitor-workflow
airkorea-monitor-workflow:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.monitor_workflow all \
		$(AIRKOREA_WORKFLOW_ARGS) \
		$(if $(AIRKOREA_INMAP_GRID),--inmap-grid "$(AIRKOREA_INMAP_GRID)",) \
		$(if $(AIRKOREA_GRID_YEAR),--grid-year $(AIRKOREA_GRID_YEAR),)


## Interpolate annual AirKorea-minus-InMAP monitor residuals to an InMAP grid
.PHONY: airkorea-inmap-bias-grid
airkorea-inmap-bias-grid:
	PYTHONPATH=src $(PYTHON_INTERPRETER) -m nzk_aphiam.air_quality.monitor_workflow grid \
		--inmap-grid "$(AIRKOREA_INMAP_GRID)" \
		--grid-year $(AIRKOREA_GRID_YEAR)


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


## Run health-impact tests (CRFs, InMAP adapter, attributable deaths, decomposition)
.PHONY: test-health
test-health:
	$(PYTHON_INTERPRETER) -m pytest tests/test_health_crf.py tests/test_health_impact.py tests/test_health_decomposition.py tests/test_health_specifications.py


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


## Materialize the canonical KEPCO annual emission-factor dataset under data/processed
.PHONY: build-kepco-emission-factors
build-kepco-emission-factors: r-analysis


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

help:
	@$(PYTHON_INTERPRETER) tools/make_help.py $(firstword $(MAKEFILE_LIST))
