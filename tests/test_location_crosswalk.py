import pandas as pd
import pytest

from nzk_aphiam.data.clean.thermal.location_crosswalk import (
    apply_location_crosswalk,
    load_location_crosswalk,
)

CROSSWALK = pd.DataFrame(
    {
        "subsidiary_company": ["Korea East-West Power", "Korea East-West Power"],
        "plant_name": ["Dangjin", "Honam"],
        "plant_latitude": [37.057, None],
        "plant_longitude": [126.509, None],
        "plant_opening_date": [pd.Timestamp("1999-06-01"), pd.NaT],
        "plant_closing_date": [pd.NaT, pd.NaT],
    }
)


def _cleaned_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "subsidiary_company": pd.array(
                ["Korea East-West Power", "Korea East-West Power"], dtype="string"
            ),
            "plant_name": pd.array(["Dangjin", "Honam"], dtype="string"),
            "plant_latitude": pd.array([None, None], dtype="Float64"),
            "plant_longitude": pd.array([None, None], dtype="Float64"),
            "plant_opening_date": pd.to_datetime([None, None]),
            "plant_closing_date": pd.to_datetime([None, None]),
            "value": [1, 2],
        }
    )


def test_matched_plant_gets_location_filled_in() -> None:
    result = apply_location_crosswalk(_cleaned_rows(), CROSSWALK)
    dangjin = result.loc[result["plant_name"] == "Dangjin"].iloc[0]
    assert dangjin["plant_latitude"] == 37.057
    assert dangjin["plant_longitude"] == 126.509
    assert dangjin["plant_opening_date"] == pd.Timestamp("1999-06-01")


def test_review_status_plant_stays_blank_rather_than_guessed() -> None:
    result = apply_location_crosswalk(_cleaned_rows(), CROSSWALK)
    honam = result.loc[result["plant_name"] == "Honam"].iloc[0]
    assert pd.isna(honam["plant_latitude"])
    assert pd.isna(honam["plant_longitude"])
    assert pd.isna(honam["plant_opening_date"])


def test_result_dtypes_match_the_schema_regardless_of_caller_input_dtype() -> None:
    result = apply_location_crosswalk(_cleaned_rows(), CROSSWALK)
    assert result["plant_latitude"].dtype == "Float64"
    assert result["plant_longitude"].dtype == "Float64"
    assert pd.api.types.is_datetime64_any_dtype(result["plant_opening_date"])
    assert pd.api.types.is_datetime64_any_dtype(result["plant_closing_date"])


def test_join_key_columns_keep_their_original_dtype() -> None:
    # A bare merge against the crosswalk's plain object-dtype columns would
    # silently downgrade these from pandas' "string" dtype to "object".
    result = apply_location_crosswalk(_cleaned_rows(), CROSSWALK)
    assert result["plant_name"].dtype == "string"
    assert result["subsidiary_company"].dtype == "string"


def test_other_columns_and_row_count_are_preserved() -> None:
    cleaned = _cleaned_rows()
    result = apply_location_crosswalk(cleaned, CROSSWALK)
    assert len(result) == len(cleaned)
    assert list(result.columns) == list(cleaned.columns)
    assert result["value"].tolist() == [1, 2]


def test_plant_missing_from_crosswalk_raises() -> None:
    cleaned = _cleaned_rows()
    cleaned.loc[0, "plant_name"] = "Unknown Plant"
    with pytest.raises(ValueError, match="missing from the location crosswalk"):
        apply_location_crosswalk(cleaned, CROSSWALK)


def test_real_crosswalk_file_loads_and_parses_dates() -> None:
    crosswalk = load_location_crosswalk()
    assert {"subsidiary_company", "plant_name", "plant_latitude", "plant_longitude"}.issubset(
        crosswalk.columns
    )
    assert len(crosswalk) == 29
    assert pd.api.types.is_datetime64_any_dtype(crosswalk["plant_opening_date"])


def test_real_crosswalk_has_location_and_opening_date_for_every_plant() -> None:
    crosswalk = load_location_crosswalk()
    assert (
        crosswalk[["plant_latitude", "plant_longitude", "plant_opening_date"]].notna().all().all()
    )


def test_official_review_corrections_are_preserved() -> None:
    crosswalk = load_location_crosswalk().set_index(["subsidiary_company", "plant_name"])
    assert crosswalk.loc[
        ("Korea South-East Power", "Bundang"), "plant_opening_date"
    ] == pd.Timestamp("1993-09-01")
    assert crosswalk.loc[
        ("Korea Southern Power", "Namjeju Steam"), "plant_opening_date"
    ] == pd.Timestamp("2007-03-01")
    assert crosswalk.loc[
        ("Korea Southern Power", "Shinsejong"), "plant_opening_date"
    ] == pd.Timestamp("2024-06-30")

    # These adjacent Incheon plants have often been conflated, but belong to
    # different operators and have distinct mapped plant footprints.
    shin_incheon = crosswalk.loc[("Korea Southern Power", "Shin-Incheon")]
    seoincheon = crosswalk.loc[("Korea Western Power", "Seoincheon")]
    assert shin_incheon["plant_longitude"] != seoincheon["plant_longitude"]
