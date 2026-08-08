from pathlib import Path

# NZK-APHIAM project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Core directories
DATA_DIR = PROJECT_ROOT / "data"
SRC_DIR = PROJECT_ROOT / "src"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_DIAGNOSTICS_DIR = RESULTS_DIR / "diagnostics"
RESULTS_FIGURES_DIR = RESULTS_DIR / "figures"
RESULTS_MODELS_DIR = RESULTS_DIR / "models"
RESULTS_OBJECTS_DIR = RESULTS_DIR / "objects"
RESULTS_RUNS_DIR = RESULTS_DIR / "runs"
RESULTS_TABLES_DIR = RESULTS_DIR / "tables"

# Mutable inter-model handoffs and APHIAM-ready scenario interfaces.
MODEL_INPUTS_DIR = PROJECT_ROOT / "model_inputs"
MODEL_SCENARIO_INPUTS_DIR = MODEL_INPUTS_DIR / "scenarios"
TEAM_HANDOFF_MODEL_INPUTS_DIR = MODEL_SCENARIO_INPUTS_DIR / "team_handoff"
TEAM_HANDOFF_GCAM_INPUTS_DIR = TEAM_HANDOFF_MODEL_INPUTS_DIR / "upstream" / "gcam_kaist"
TEAM_HANDOFF_APHIAM_DIR = TEAM_HANDOFF_MODEL_INPUTS_DIR / "aphiam"
GCAM_NZK_ARCHIVE = (
    TEAM_HANDOFF_GCAM_INPUTS_DIR / "nzk" / "CORE_9_NZ_2026-8-7T12_32_50+09_00.xml.zip"
)
GCAM_NZK_APHIAM_DIR = TEAM_HANDOFF_APHIAM_DIR / "gcam_kaist" / "nzk"
PENG_REPLICATION_MODEL_INPUTS_DIR = MODEL_SCENARIO_INPUTS_DIR / "peng_replication_mvp"
PENG_REPLICATION_MACRO_INPUTS_DIR = PENG_REPLICATION_MODEL_INPUTS_DIR / "upstream" / "macro"
NONPOWER_PROXY_MODEL_INPUTS_DIR = MODEL_SCENARIO_INPUTS_DIR / "nonpower_proxy_2025_2050" / "aphiam"

# Archived datasets
ARCHIVE_DIR = DATA_DIR / "archive"

ARCHIVE_RAW_DIR = ARCHIVE_DIR / "raw"
ARCHIVE_INTERIM_DIR = ARCHIVE_DIR / "interim"
ARCHIVE_PROCESSED_DIR = ARCHIVE_DIR / "processed"
ANNUAL_PANEL_ARCHIVE_RAW_DIR = ARCHIVE_RAW_DIR / "annual_panel"
ANNUAL_PANEL_ARCHIVE_INTERIM_DIR = ARCHIVE_INTERIM_DIR / "annual_panel"
ANNUAL_PANEL_ARCHIVE_PROCESSED_DIR = ARCHIVE_PROCESSED_DIR / "annual_panel"

# CleanSYS TMS (archived project)
CLEANSYS_DIR = ARCHIVE_RAW_DIR / "cleansys_tms"

# Three-stage pipeline roots: raw (scraper output), interim (cleaner
# output), processed (auditor/merger output). Each active domain (kepco today;
# airkorea/health as they're added) gets its own subdirectory under
# each stage, e.g. data/raw/kepco_subsidiaries/eastwest_power, data/processed/kepco.
THERMAL_RAW_DIR = DATA_DIR / "raw"
THERMAL_INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
KEPCO_PROCESSED_DIR = PROCESSED_DIR / "kepco"
THERMAL_PROCESSED_DIR = KEPCO_PROCESSED_DIR
KEPCO_EMISSION_FACTORS_DIR = KEPCO_PROCESSED_DIR / "emission_factors"

# Archived KMA hourly meteorology. The active annual Global InMAP workflow uses
# its packaged meteorology and built-in bias correction instead.
KMA_WEATHER_ARCHIVE_RAW_DIR = ARCHIVE_RAW_DIR / "weather" / "kma"
KMA_WEATHER_ARCHIVE_PROCESSED_DIR = ARCHIVE_PROCESSED_DIR / "weather" / "kma"

# AirKorea station registry and year-specific station-location crosswalk.
AIRKOREA_RAW_DIR = DATA_DIR / "raw" / "airkorea"
AIRKOREA_STATION_RAW_DIR = AIRKOREA_RAW_DIR / "stations"
AIRKOREA_INTERIM_DIR = DATA_DIR / "interim" / "air_quality"
AIRKOREA_PROCESSED_DIR = PROCESSED_DIR / "air_quality"

# KOSIS source responses remain raw; deterministic normalized tables are
# separate interim products.
KOSIS_RAW_DIR = DATA_DIR / "raw" / "health" / "kosis"
KOSIS_INTERIM_DIR = DATA_DIR / "interim" / "health" / "kosis"

# CAPSS national air pollutant emissions inventory workbooks and normalized
# long-form emissions tables.
CAPSS_RAW_DIR = DATA_DIR / "raw" / "capss"
CAPSS_INTERIM_DIR = DATA_DIR / "interim" / "capss"

# Third-party datasets that this repo cannot reproduce by scraping or
# transformation. Inter-model scenario handoffs belong under MODEL_INPUTS_DIR.
# Unlike data/raw/, this directory is not gitignored: the files placed here
# are the only copy and must be tracked directly in Git.
EXTERNAL_DIR = DATA_DIR / "external"

# Derived MACRO validation products remain processed data. Mutable upstream
# handoffs and APHIAM scenario interfaces live under MODEL_INPUTS_DIR.
MACRO_PROCESSED_DIR = PROCESSED_DIR / "macro"

# Version-controlled non-power inventory inputs and reproducible local outputs.
NONPOWER_REFERENCE_DIR = PROJECT_ROOT / "docs" / "references" / "nonpower_emissions"
NONPOWER_PROCESSED_DIR = PROCESSED_DIR / "nonpower_emissions"
NONPOWER_INTERIM_DIR = DATA_DIR / "interim" / "nonpower_emissions"
NONPOWER_DIAGNOSTIC_DIR = RESULTS_DIAGNOSTICS_DIR / "nonpower_emissions"
