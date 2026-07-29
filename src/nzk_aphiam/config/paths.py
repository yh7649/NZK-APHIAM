from pathlib import Path

# NZK-APHIAM project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Core directories
DATA_DIR = PROJECT_ROOT / "data"
SRC_DIR = PROJECT_ROOT / "src"

# Archived datasets
ARCHIVE_DIR = DATA_DIR / "archive"

ARCHIVE_RAW_DIR = ARCHIVE_DIR / "raw"
ARCHIVE_INTERIM_DIR = ARCHIVE_DIR / "interim"
ARCHIVE_PROCESSED_DIR = ARCHIVE_DIR / "processed"

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

# Archived KMA hourly meteorology. The active annual Global InMAP workflow uses
# its packaged meteorology and built-in bias correction instead.
KMA_WEATHER_ARCHIVE_RAW_DIR = ARCHIVE_RAW_DIR / "weather" / "kma"
KMA_WEATHER_ARCHIVE_PROCESSED_DIR = ARCHIVE_PROCESSED_DIR / "weather" / "kma"

# AirKorea station registry and year-specific station-location crosswalk.
AIRKOREA_RAW_DIR = DATA_DIR / "raw" / "airkorea"
AIRKOREA_STATION_RAW_DIR = AIRKOREA_RAW_DIR / "stations"
AIRKOREA_INTERIM_DIR = DATA_DIR / "interim" / "air_quality"

# CAPSS national air pollutant emissions inventory workbooks and normalized
# long-form emissions tables.
CAPSS_RAW_DIR = DATA_DIR / "raw" / "capss"
CAPSS_INTERIM_DIR = DATA_DIR / "interim" / "capss"

# Third-party model/dataset deliverables that this repo cannot reproduce by
# scraping or transformation (e.g. team-supplied GCAM-KAIST/MACRO tables).
# Unlike data/raw/, this directory is not gitignored: the files placed here
# are the only copy and must be tracked directly in Git.
EXTERNAL_DIR = DATA_DIR / "external"

# MACRO/GCAM-KAIST integration products built from externally supplied
# activity tables and CAPSS historical emissions intensities.
MACRO_EXTERNAL_DIR = EXTERNAL_DIR / "macro"
MACRO_PROCESSED_DIR = PROCESSED_DIR / "macro"

# Version-controlled non-power inventory inputs and reproducible local outputs.
NONPOWER_REFERENCE_DIR = PROJECT_ROOT / "docs" / "references" / "nonpower_emissions"
NONPOWER_PROCESSED_DIR = PROCESSED_DIR / "nonpower_emissions"
NONPOWER_INTERIM_DIR = DATA_DIR / "interim" / "nonpower_emissions"
NONPOWER_DIAGNOSTIC_DIR = PROJECT_ROOT / "results" / "diagnostics" / "nonpower_emissions"
