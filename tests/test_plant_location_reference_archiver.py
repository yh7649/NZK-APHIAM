import pandas as pd

from nzk_aphiam.data.scrape.references.plant_location_dates import (
    DEFAULT_EVIDENCE_PATH,
    _extension,
    _fetch_url,
    _source_inventory,
)


def test_osm_citation_is_archived_through_full_geometry_api() -> None:
    assert _fetch_url("https://www.openstreetmap.org/way/640000730") == (
        "https://api.openstreetmap.org/api/0.6/way/640000730/full.json"
    )


def test_non_osm_source_url_is_preserved() -> None:
    url = "https://example.com/operator/page"
    assert _fetch_url(url) == url


def test_content_type_controls_archive_extension() -> None:
    assert _extension("application/json; charset=utf-8", "https://example.com") == ".json"
    assert _extension("text/html;charset=UTF-8", "https://example.com") == ".html"
    assert _extension("application/octet-stream", "https://example.com/report.pdf") == ".pdf"


def test_real_evidence_inventory_covers_every_documented_row() -> None:
    evidence = pd.read_csv(DEFAULT_EVIDENCE_PATH)
    inventory = _source_inventory(evidence)
    assert len(evidence) == 18
    assert len(inventory) == 38
    documented_plants = {plant for source in inventory.values() for plant in source["plants"]}
    assert len(documented_plants) == 18
