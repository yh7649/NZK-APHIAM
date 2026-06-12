from nzk_aphiam.data.scrape.thermal.eastwest_power import scraper


def test_enrichment_sources_are_logged() -> None:
    assert (
        scraper.FUEL_MAPPING_REFERENCE
        == "references/thermal/eastwest_power_energy_type_mapping.csv"
    )
    assert {source["url"] for source in scraper.ENRICHMENT_SOURCES} == {
        "https://www.ewp.co.kr/kor/download/ewp_open/environ_2011.pdf",
        "https://www.ewp.co.kr/kor/download/ewp_open/environ_2016.pdf",
    }
