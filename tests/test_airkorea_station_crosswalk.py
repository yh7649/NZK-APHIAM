from __future__ import annotations

import pandas as pd
import pytest

from nzk_aphiam.air_quality.station_crosswalk import (
    add_station_coordinates,
    build_station_crosswalk,
)


def test_unmatched_station_does_not_drop_registry_coordinate_columns():
    hourly = pd.DataFrame(
        {
            "monitor_id": ["historic-only"],
            "datetime": pd.to_datetime(["2010-01-01 01:00"]),
            "station_name": ["없는측정소"],
            "address": ["과거주소"],
        }
    )
    registry = pd.DataFrame(
        {
            "station_name": ["현재측정소"],
            "address": ["현재주소"],
            "latitude": [37.0],
            "longitude": [127.0],
        }
    )

    crosswalk = build_station_crosswalk(hourly, registry)

    assert crosswalk.loc[0, "coordinate_match_method"] == "unmatched"
    assert crosswalk.loc[0, "coordinate_match_confidence"] == "unresolved"
from nzk_aphiam.data.scrape.airkorea import stations


class JsonResponse:
    status_code = 200

    def json(self) -> dict[str, object]:
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                "body": {
                    "totalCount": 1,
                    "items": [
                        {
                            "stationName": "중구",
                            "addr": "서울 중구 덕수궁길 15",
                            "year": "1995",
                            "mangName": "도시대기",
                            "item": "SO2,CO,O3,NO2,PM10,PM25",
                            "dmX": "37.564",
                            "dmY": "126.975",
                        }
                    ],
                },
            }
        }


class JsonSession:
    def get(self, endpoint: str, params: dict[str, object], timeout: int) -> JsonResponse:
        assert "serviceKey" in params
        return JsonResponse()


def test_fetch_registry_maps_documented_wgs84_fields() -> None:
    result = stations.fetch_registry("secret", session=JsonSession())  # type: ignore[arg-type]
    assert result.loc[0, "latitude"] == pytest.approx(37.564)
    assert result.loc[0, "longitude"] == pytest.approx(126.975)
    assert result.loc[0, "station_name"] == "중구"


def _hourly() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "monitor_id": ["111121", "111122"],
            "datetime": pd.to_datetime(["2022-01-01 01:00", "2005-01-01 01:00"]),
            "station_name": ["중구", "이동측정소"],
            "address": ["서울 중구 덕수궁길 15", "서울 종로구 옛주소 1"],
            "pollutant": ["PM10", "PM10"],
            "value_raw": [30.0, 40.0],
        }
    )


def _registry() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_name": ["중구", "이동측정소"],
            "address": ["서울 중구 덕수궁길 15", "서울 종로구 새주소 2"],
            "latitude": [37.564, 37.58],
            "longitude": [126.975, 127.0],
        }
    )


def test_crosswalk_matches_exact_address_but_rejects_relocation_guess() -> None:
    result = build_station_crosswalk(_hourly(), _registry()).set_index("monitor_id")
    assert result.at["111121", "coordinate_match_confidence"] == "high"
    assert result.at["111121", "latitude"] == pytest.approx(37.564)
    assert result.at["111122", "coordinate_match_method"] == "name_only_with_address_change"
    assert pd.isna(result.at["111122", "latitude"])


def test_annual_report_override_has_priority_and_merge_preserves_rows() -> None:
    historical = pd.DataFrame(
        {"monitor_id": ["111122"], "year": [2005], "latitude": [37.57], "longitude": [126.99]}
    )
    crosswalk = build_station_crosswalk(_hourly(), _registry(), historical)
    moved = crosswalk.set_index("monitor_id").loc["111122"]
    assert moved["coordinate_match_method"] == "annual_report_station_code"
    enriched = add_station_coordinates(_hourly(), crosswalk)
    assert len(enriched) == 2
    assert enriched.loc[enriched["monitor_id"] == "111122", "latitude"].iloc[0] == pytest.approx(
        37.57
    )
