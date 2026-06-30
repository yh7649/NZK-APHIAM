from nzk_aphiam.archive.annual_panel.process.crosswalk.builder import (
    Facility,
    normalize_company,
    normalize_plant,
    score_candidate,
)


def test_normalize_company_aliases() -> None:
    assert normalize_company("GS EPS㈜") == "지에스이피에스"
    assert normalize_company("남부발전(주)") == "한국남부발전"
    assert normalize_company("지역난방 공사") == "한국지역난방공사"


def test_normalize_plant_groups_components() -> None:
    assert normalize_plant("당진#4 GT") == "당진"
    assert normalize_plant("동탄열병합 #2 ST") == "동탄"
    assert normalize_plant("강릉안인#1") == "강릉"


def test_operator_and_plant_agreement_is_high_confidence() -> None:
    plant = {
        "epsis_operator_key": "지에스이피에스",
        "epsis_plant_key": "당진",
        "epsis_location": "충남 당진시 송악읍",
    }
    facility = Facility(
        source="cleansys",
        identifier="170707",
        name="지에스이피에스㈜[GS EPS㈜]",
        aliases=("지에스이피에스㈜[GS EPS㈜]",),
        address="충청남도 당진시 송악읍 부곡공단로 241",
    )
    result = score_candidate(plant, facility)
    assert result["operator_exact"] is True
    assert result["plant_exact"] is False
    assert result["location_score"] == 1.0
    assert result["score"] >= 0.6


def test_plant_and_operator_agreement_scores_near_one() -> None:
    plant = {
        "epsis_operator_key": "한국남부발전",
        "epsis_plant_key": "하동",
        "epsis_location": "경남 하동군 금성면",
    }
    facility = Facility(
        source="cleansys",
        identifier="130401",
        name="한국남부발전㈜ 하동빛드림본부",
        aliases=("한국남부발전㈜ 하동빛드림본부",),
        address="경상남도 하동군 금성면 경제산업로 509",
    )
    result = score_candidate(plant, facility)
    assert result["operator_exact"] is True
    assert result["plant_exact"] is True
    assert result["score"] >= 0.9
