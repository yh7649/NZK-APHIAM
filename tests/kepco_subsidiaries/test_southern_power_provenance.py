from nzk_aphiam.data.scrape.thermal.southern_power import provenance


def test_all_southern_fuel_sources_are_logged() -> None:
    assert (
        provenance.FUEL_MAPPING_REFERENCE
        == "docs/references/thermal/southern_power_fuel_type_mapping.csv"
    )
    assert len(provenance.ENRICHMENT_SOURCES) == 9
    assert all(source["url"].startswith("https://") for source in provenance.ENRICHMENT_SOURCES)
