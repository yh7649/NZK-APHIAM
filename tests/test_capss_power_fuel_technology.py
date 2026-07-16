from __future__ import annotations

import pandas as pd

from nzk_aphiam.data.process import capss_power_fuel_technology as capss_power


def sample_capss() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "year": 2021,
                "source_category_ko": "에너지산업 연소",
                "source_midcategory_ko": "공공발전시설",
                "source_subcategory_ko": "1,2,3종(보일러)",
                "fuel_category_ko": "유연탄",
                "fuel_type_ko": "유연탄",
                "pollutant": "NOx",
                "emissions_kg": 1000.0,
            },
            {
                "year": 2021,
                "source_category_ko": "에너지산업 연소",
                "source_midcategory_ko": "민간발전시설",
                "source_subcategory_ko": "1,2,3종(보일러)",
                "fuel_category_ko": "유연탄",
                "fuel_type_ko": "유연탄",
                "pollutant": "NOx",
                "emissions_kg": 2000.0,
            },
            {
                "year": 2021,
                "source_category_ko": "제조업 연소",
                "source_midcategory_ko": "기타",
                "source_subcategory_ko": "1,2,3종(보일러)",
                "fuel_category_ko": "유연탄",
                "fuel_type_ko": "유연탄",
                "pollutant": "NOx",
                "emissions_kg": 9999.0,
            },
            {
                "year": 2021,
                "source_category_ko": "에너지산업 연소",
                "source_midcategory_ko": "공공발전시설",
                "source_subcategory_ko": "가스터빈",
                "fuel_category_ko": "LNG",
                "fuel_type_ko": "LNG",
                "pollutant": "SOx",
                "emissions_kg": 500.0,
            },
        ]
    )


def source_metadata() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "year": 2021,
                "source_page_url": "https://example.test/page",
                "source_attachment_url": "https://example.test/file",
            }
        ]
    )


def test_power_sector_filter_excludes_non_power_categories() -> None:
    filtered = capss_power.filter_power_sector(sample_capss(), 2021, 2021)

    assert len(filtered) == 3
    assert set(filtered["source_midcategory_ko"]) == {"공공발전시설", "민간발전시설"}
    assert set(filtered["source_category_ko"]) == {"에너지산업 연소"}


def test_detailed_and_combined_aggregation_keep_public_private_separate_then_sum() -> None:
    filtered = capss_power.filter_power_sector(sample_capss(), 2021, 2021)
    detailed = capss_power.aggregate_detailed(filtered, source_metadata())
    combined = capss_power.aggregate_combined(detailed)

    public = detailed.loc[detailed["power_facility_class_ko"] == "공공발전시설", "emissions_kg"].sum()
    private = detailed.loc[detailed["power_facility_class_ko"] == "민간발전시설", "emissions_kg"].sum()
    assert public == 1500.0
    assert private == 2000.0
    coal_nox = combined.loc[
        (combined["fuel_major_ko"] == "유연탄") & (combined["pollutant"] == "NOx"),
        "emissions_kg",
    ].iloc[0]
    assert coal_nox == 3000.0
    assert sorted(combined["emissions_tonnes"].tolist()) == [0.5, 3.0]


def test_pollutant_pivot_uses_voc_column_name_and_preserves_pollutants_separately() -> None:
    combined = pd.DataFrame(
        [
            {
                "year": 2021,
                "technology_official_ko": "가스터빈",
                "technology_en": "Gas turbine",
                "fuel_major_ko": "LNG",
                "fuel_major_en": "LNG",
                "pollutant": "VOCs",
                "emissions_kg": 10.0,
                "emissions_tonnes": 0.01,
                "source_page_url": "u",
                "source_attachment_url": "a",
            },
            {
                "year": 2021,
                "technology_official_ko": "가스터빈",
                "technology_en": "Gas turbine",
                "fuel_major_ko": "LNG",
                "fuel_major_en": "LNG",
                "pollutant": "NOx",
                "emissions_kg": 20.0,
                "emissions_tonnes": 0.02,
                "source_page_url": "u",
                "source_attachment_url": "a",
            },
        ]
    )

    wide = capss_power.pivot_pollutants(
        combined, value_column="emissions_kg", suffix="_kg", include_source_url=True
    )

    assert wide.loc[0, "VOC_kg"] == 10.0
    assert wide.loc[0, "NOx_kg"] == 20.0
    assert wide.loc[0, "SOx_kg"] == 0.0


def test_korean_to_english_mapping_and_unexpected_label_diagnostics() -> None:
    filtered = capss_power.filter_power_sector(sample_capss(), 2021, 2021)
    filtered.loc[len(filtered)] = {
        "year": 2021,
        "source_category_ko": "에너지산업 연소",
        "source_midcategory_ko": "공공발전시설",
        "source_subcategory_ko": "가스터빈",
        "fuel_category_ko": "새연료",
        "fuel_type_ko": "새연료",
        "pollutant": "NOx",
        "emissions_kg": 1.0,
    }
    labeled = capss_power.add_labels(filtered)
    diagnostics = capss_power.unmapped_labels(filtered)

    assert "Boiler, Classes 1-3" in labeled["technology_en"].tolist()
    assert "Bituminous coal" in labeled["fuel_major_en"].tolist()
    assert "unmapped" in diagnostics["mapping_status"].tolist()


def test_reference_2021_totals_pass_with_requested_values() -> None:
    rows = []
    for (fuel, technology, pollutant), tonnes in capss_power.REFERENCE_2021_TONNES.items():
        rows.append(
            {
                "year": 2021,
                "technology_official_ko": technology,
                "technology_en": capss_power.TECHNOLOGY_EN[technology],
                "fuel_major_ko": fuel,
                "fuel_major_en": capss_power.FUEL_MAJOR_EN[fuel],
                "pollutant": pollutant,
                "emissions_kg": tonnes * 1000.0,
                "emissions_tonnes": tonnes,
                "source_page_url": "u",
                "source_attachment_url": "a",
            }
        )
    combined = pd.DataFrame(rows)
    detailed = combined.assign(
        power_facility_class_ko="공공발전시설",
        power_facility_class_en="Public power-generation facilities",
        fuel_minor_ko=combined["fuel_major_ko"],
    )
    power = pd.DataFrame(
        {
            "source_category_ko": ["에너지산업 연소"],
            "source_midcategory_ko": ["공공발전시설"],
        }
    )

    validation = capss_power.validate_outputs(
        power=power, detailed=detailed, combined=combined, start_year=2021, end_year=2021
    )

    assert validation.loc[
        validation["check"] == "reference_2021_all_requested_values", "passed"
    ].iloc[0]
