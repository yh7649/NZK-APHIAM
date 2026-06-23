from nzk_aphiam.data.scrape.thermal.western_power import scraper


def test_fuel_mapping_sources_are_logged() -> None:
    assert (
        scraper.FUEL_MAPPING_REFERENCE
        == "docs/references/thermal/western_power_energy_type_mapping.csv"
    )
    assert {source["url"] for source in scraper.FUEL_MAPPING_SOURCES} == {
        "https://www.iwest.co.kr/iwest/559/subview.do",
        "https://www.iwest.co.kr/iwest/800/subview.do",
        "https://www.iwest.co.kr/iwest/925/subview.do",
        "https://www.iwest.co.kr/iwest/560/subview.do",
        "https://www.iwest.co.kr/iwest/561/subview.do",
        "https://www.iwest.co.kr/iwest/562/subview.do",
        "https://www.iwest.co.kr/iwest/1052/subview.do",
    }
