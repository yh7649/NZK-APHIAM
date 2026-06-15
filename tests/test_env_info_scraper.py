from pathlib import Path

import pytest

from nzk_aphiam.data.scrape.env_info.scraper import (
    columnar_json_to_rows,
    parse_emissions_detail,
    scrape_year,
)


def test_columnar_json_to_rows() -> None:
    assert columnar_json_to_rows({"name": ["a", "b"], "year": [2024, 2024]}) == [
        {"name": "a", "year": 2024},
        {"name": "b", "year": 2024},
    ]


def test_parse_emissions_detail() -> None:
    html = """
    <td id="printCompNm">Private Power Plant</td>
    <div id="inquiry14">
    <th>질소산화물(Nox)</th><td class="last">804.366 ton</td>
    <th>황산화물(SOX)</th><td class="last">133.95 ton</td>
    <th>먼지(TSP)</th><td class="last">6.834 ton</td>
    <!-- //의무 14. 대기오염물질 배출량 -->
    """
    assert parse_emissions_detail(html) == {
        "facility_name": "Private Power Plant",
        "nox_tonnes": 804.366,
        "sox_tonnes": 133.95,
        "tsp_tonnes": 6.834,
    }


def test_parse_emissions_detail_allows_missing_values() -> None:
    html = """
    <td id="printCompNm">Plant</td>
    <span>질소산화물(Nox)</span><td>999 ton</td>
    """
    assert parse_emissions_detail(html) == {
        "facility_name": "Plant",
        "nox_tonnes": None,
        "sox_tonnes": None,
        "tsp_tonnes": None,
    }


def test_offline_rebuild_requires_preserved_index(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing index"):
        scrape_year(tmp_path, 2024, offline=True)
