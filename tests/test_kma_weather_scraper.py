from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.data.scrape.weather.kma import scraper
from nzk_aphiam.data.scrape.weather.kma.schemas import ASOS_COLUMNS


def test_parse_text_response_skips_kma_markers_and_preserves_source_strings() -> None:
    values = [str(index) for index in range(len(ASOS_COLUMNS))]
    text = "#START7777\n" + " ".join(values) + "\n#7777END\n"

    result = scraper.parse_text_response(text, ASOS_COLUMNS)

    assert result.shape == (1, len(ASOS_COLUMNS))
    assert result.loc[0, "TM"] == "0"
    assert result.loc[0, "RN_JUN"] == str(ASOS_COLUMNS.index("RN_JUN"))


def test_parse_text_response_rejects_schema_drift() -> None:
    with pytest.raises(scraper.KmaApiError, match="schema mismatch"):
        scraper.parse_text_response("202401010000 108", ASOS_COLUMNS)


def test_request_estimate_keeps_one_core_year_below_daily_limit() -> None:
    assert scraper.estimate_requests("core", 2001, 2001, 1) == 757
    assert scraper.estimate_requests("profiler", 2001, 2001, 1) == 8760


def test_save_snapshot_is_atomic_and_requires_overwrite_for_revision(tmp_path: Path) -> None:
    path = tmp_path / "surface.source.2001.csv"
    original = pd.DataFrame({"TM": ["200101010000"], "STN": ["108"]})
    revised = pd.DataFrame({"TM": ["200101010100"], "STN": ["108"]})

    assert scraper.save_snapshot(original, path, overwrite=False) == "new"
    assert scraper.save_snapshot(revised, path, overwrite=False) == "reused"
    assert pd.read_csv(path, dtype=str).loc[0, "TM"] == "200101010000"
    assert scraper.save_snapshot(revised, path, overwrite=True) == "revised"
    assert not path.with_suffix(".csv.part").exists()


class ForbiddenResponse:
    status_code = 403
    text = '{"result":{"status":403,"message":"activation required"}}'

    def json(self) -> dict:
        return {"result": {"status": 403, "message": "activation required"}}


class ForbiddenSession:
    def get(self, endpoint: str, params: dict[str, str], timeout: int) -> ForbiddenResponse:
        return ForbiddenResponse()


def test_api_error_does_not_leak_authentication_key() -> None:
    secret = "do-not-print-this-key"
    with pytest.raises(scraper.KmaApiError, match="activation required") as error:
        scraper.request_text(  # type: ignore[arg-type]
            ForbiddenSession(), "https://example.test", {}, secret, timeout=10
        )

    assert secret not in str(error.value)


class ProfilerClient:
    def get(self, endpoint: str, params: dict[str, str]) -> str:
        return "202301010000 47100 100 90 2 -2 0 0 0"


def test_profiler_year_uses_configured_interval_and_documented_schema() -> None:
    result, requests_used = scraper._fetch_profiler_year(  # type: ignore[arg-type]
        ProfilerClient(), 2023, interval_hours=24
    )

    assert requests_used == 365
    assert len(result) == 365
    assert list(result.columns) == scraper.PROFILER_COLUMNS
