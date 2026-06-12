from pathlib import Path

# NZK-APHIAM project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Core directories
DATA_DIR = PROJECT_ROOT / "data"
SRC_DIR = PROJECT_ROOT / "src"

# Legacy datasets
LEGACY_DIR = DATA_DIR / "legacy"

LEGACY_RAW_DIR = LEGACY_DIR / "raw"
LEGACY_INTERIM_DIR = LEGACY_DIR / "interim"
LEGACY_PROCESSED_DIR = LEGACY_DIR / "processed"

# CleanSYS (archived project)
CLEANSYS_DIR = LEGACY_RAW_DIR / "cleansys_tms"

# KEPCO thermal subsidiary project
THERMAL_DIR = DATA_DIR / "power_generation" / "thermal"

THERMAL_RAW_DIR = THERMAL_DIR / "raw"
THERMAL_INTERIM_DIR = THERMAL_DIR / "interim"
THERMAL_PROCESSED_DIR = THERMAL_DIR / "processed"
