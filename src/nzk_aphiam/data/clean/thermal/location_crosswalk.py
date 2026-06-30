"""Fill plant location and commissioning-date columns from the documented crosswalk.

Plant coordinates and opening/closing dates cannot be derived from any
subsidiary's own API -- they come from a teammate-supplied roster
(`docs/references/province_level_power.xlsx`), matched by hand to each
KEPCO plant and recorded with evidence in
`docs/references/crosswalk/plant_location_dates.csv`. That file is the
source of truth here, including for the plants it deliberately leaves
blank: rows marked ``review`` (genuine identity ambiguity, e.g. an old
plant vs. a similarly-named new one under construction) or ``unmatched``
(not found in the roster at all) have empty coordinates and dates in the
crosswalk on purpose, so joining never asserts an unconfirmed location.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_CROSSWALK_PATH = (
    PROJECT_ROOT / "docs" / "references" / "crosswalk" / "plant_location_dates.csv"
)
LOCATION_COLUMNS = [
    "plant_latitude",
    "plant_longitude",
    "plant_opening_date",
    "plant_closing_date",
]
JOIN_KEY = ["subsidiary_company", "plant_name"]


def load_location_crosswalk(path: Path = DEFAULT_CROSSWALK_PATH) -> pd.DataFrame:
    """Load the documented plant location/date crosswalk."""
    crosswalk = pd.read_csv(path, encoding="utf-8-sig")
    crosswalk["plant_opening_date"] = pd.to_datetime(
        crosswalk["plant_opening_date"], errors="raise"
    )
    crosswalk["plant_closing_date"] = pd.to_datetime(
        crosswalk["plant_closing_date"], errors="raise"
    )
    return crosswalk[[*JOIN_KEY, *LOCATION_COLUMNS]]


def apply_location_crosswalk(
    cleaned: pd.DataFrame, crosswalk: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Return `cleaned` with plant_latitude/longitude/opening_date/closing_date filled in.

    Joins on (subsidiary_company, plant_name). Every plant present in
    `cleaned` must have a row in the crosswalk -- a missing plant means a
    scraper started reporting a plant the crosswalk has never seen, which
    should fail loudly rather than silently leave it unmatched.
    """
    crosswalk = crosswalk if crosswalk is not None else load_location_crosswalk()

    known_plants = cleaned[JOIN_KEY].drop_duplicates()
    missing = known_plants.merge(
        crosswalk[JOIN_KEY], on=JOIN_KEY, how="left", indicator=True
    ).query("_merge == 'left_only'")
    if not missing.empty:
        unresolved = list(missing[JOIN_KEY].itertuples(index=False, name=None))
        raise ValueError(
            "Plants present in cleaned data are missing from the location crosswalk "
            f"(docs/references/crosswalk/plant_location_dates.csv): {unresolved}. "
            "Add a row for each, even if its match_status is 'review' or 'unmatched'."
        )

    original_dtypes = cleaned.dtypes
    base = cleaned.drop(columns=LOCATION_COLUMNS)
    joined = base.merge(crosswalk, on=JOIN_KEY, how="left")

    # Merging against the crosswalk's plain object-dtype join-key columns
    # silently downgrades the caller's pandas "string"-dtype columns (e.g.
    # plant_name) to "object". Restore every untouched column to its
    # pre-merge dtype so this join is invisible to columns it isn't meant
    # to affect.
    for column in base.columns:
        joined[column] = joined[column].astype(original_dtypes[column])

    # A plain merge produces numpy float64/datetime64 columns regardless of
    # what dtype the caller's placeholder columns had. Enforce the schema's
    # nullable types explicitly so callers get a consistent result no matter
    # when in their own dtype-casting sequence they call this.
    joined["plant_latitude"] = joined["plant_latitude"].astype("Float64")
    joined["plant_longitude"] = joined["plant_longitude"].astype("Float64")
    joined["plant_opening_date"] = pd.to_datetime(joined["plant_opening_date"])
    joined["plant_closing_date"] = pd.to_datetime(joined["plant_closing_date"])

    return joined[cleaned.columns]
