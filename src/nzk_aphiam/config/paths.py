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

# KEPCO subsidiary source files and final processed dataset
KEPCO_DIR = DATA_DIR / "kepco"
KEPCO_PROCESSED_DIR = KEPCO_DIR / "processed"

THERMAL_RAW_DIR = DATA_DIR / "raw"
THERMAL_INTERIM_DIR = DATA_DIR / "interim"
THERMAL_PROCESSED_DIR = KEPCO_PROCESSED_DIR
