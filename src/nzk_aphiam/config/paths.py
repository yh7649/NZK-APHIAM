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
# output), processed (auditor/merger output). Each domain (kepco today;
# airkorea/health/weather as they're added) gets its own subdirectory under
# each stage, e.g. data/raw/kepco_subsidiaries/eastwest_power, data/processed/kepco.
THERMAL_RAW_DIR = DATA_DIR / "raw"
THERMAL_INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
KEPCO_PROCESSED_DIR = PROCESSED_DIR / "kepco"
THERMAL_PROCESSED_DIR = KEPCO_PROCESSED_DIR

# KMA meteorology: official API responses, normalized observation tables,
# and analysis-ready dispersion features.
WEATHER_RAW_DIR = DATA_DIR / "raw" / "weather" / "kma"
WEATHER_INTERIM_DIR = DATA_DIR / "interim" / "weather" / "kma"
WEATHER_PROCESSED_DIR = PROCESSED_DIR / "weather" / "kma"

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
