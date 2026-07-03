from pathlib import Path

import pandas as pd

from nzk_aphiam.data.clean.thermal.generation_panel.panel import build_khnp_generation
from nzk_aphiam.data.scrape.thermal.khnp import generation_scraper


def test_parse_and_extract_khnp_response() -> None:
    root = generation_scraper.parse_response(
        b"""<response><header><resultCode>00</resultCode><resultMsg>OK</resultMsg></header>
        <body><items><item><genCd>7012</genCd><genNm>\xea\xb3\xa0\xeb\xa6\xac#2</genNm>
        <resourceType>\xec\x9b\x90\xec\x9e\x90\xeb\xa0\xa5</resourceType><tradeDt>20260630</tradeDt>
        <qt_1h>640000</qt_1h></item></items></body></response>"""
    )
    assert generation_scraper.extract_rows(root) == [
        {
            "genCd": "7012",
            "genNm": "고리#2",
            "resourceType": "원자력",
            "tradeDt": "20260630",
            "qt_1h": "640000",
        }
    ]


def test_merge_with_collected_history_replaces_overlap(tmp_path: Path) -> None:
    combined = tmp_path / "khnp_daily_generation.csv"
    pd.DataFrame(
        [{"tradeDt": "20260629", "genCd": "1", "qt_1h": "10"}]
    ).to_csv(combined, index=False, encoding="utf-8-sig")
    fresh = pd.DataFrame(
        [
            {"tradeDt": "20260629", "genCd": "1", "qt_1h": "11"},
            {"tradeDt": "20260630", "genCd": "1", "qt_1h": "12"},
        ],
        dtype="string",
    )
    merged = generation_scraper.merge_with_collected_history(fresh, combined)
    assert merged[["tradeDt", "qt_1h"]].to_dict("records") == [
        {"tradeDt": "20260629", "qt_1h": "11"},
        {"tradeDt": "20260630", "qt_1h": "12"},
    ]


def test_build_khnp_generation_aggregates_daily_kwh_to_monthly_mwh(tmp_path: Path) -> None:
    path = tmp_path / "khnp.csv"
    pd.DataFrame(
        [
            {
                "tradeDt": "20260629", "genCd": "7012", "genNm": "고리#2",
                "resourceType": "원자력", "qt_1h": "1000", "qt_2h": "2000",
            },
            {
                "tradeDt": "20260630", "genCd": "7012", "genNm": "고리#2",
                "resourceType": "원자력", "qt_1h": "3000", "qt_2h": "4000",
            },
        ]
    ).to_csv(path, index=False, encoding="utf-8-sig")

    result = build_khnp_generation(path)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["date"] == pd.Timestamp("2026-06-01")
    assert row["subsidiary_company"] == "Korea Hydro & Nuclear Power"
    assert row["plant_name"] == "Kori"
    assert row["plant_number"] == 2
    assert row["reporting_unit_id"] == "khnp:7012"
    assert row["fuel_type"] == "nuclear"
    assert row["energy_generated_mwh"] == 10.0
    assert pd.isna(row["energy_capacity_mw"])
