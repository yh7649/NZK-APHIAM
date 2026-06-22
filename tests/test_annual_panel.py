from nzk_aphiam.data.process.annual_panel.pipeline import (
    classify_generation_row,
    collapse_source_candidates,
    factor,
    operator_category,
    reconcile_emissions,
    validation_status,
)


def generation_row(label: str, source: str = "기력", fuel: str = "유연탄") -> dict[str, str]:
    return {
        "source_record_name": label,
        "generation_source": source,
        "fuel_group": source,
        "fuel_detail": fuel,
        "company": "남부",
    }


def test_generation_classification_distinguishes_units_and_plant_totals() -> None:
    assert classify_generation_row(generation_row("하동#1"))[0] == "unit"
    assert classify_generation_row(generation_row("부산C/C", "복합", "LNG"))[0] == "plant_total"
    assert classify_generation_row(generation_row("위례열병합", "집단", "LNG"))[0] == (
        "plant_total"
    )


def test_generation_classification_excludes_aggregates() -> None:
    assert classify_generation_row(generation_row("[PPA] 한수원"))[0] == "company_total"
    assert classify_generation_row(generation_row("기타 상용자가(LNG)"))[0] == ("other_aggregate")
    assert classify_generation_row(generation_row("태양광", "신재생", "태양광"))[0] == (
        "fuel_total"
    )


def test_source_candidate_collapse_rejects_multiple_facilities() -> None:
    base = {
        "year": 2024,
        "plant_id": "plant",
        "pollutant": "nox",
        "source": "cleansys",
        "emissions_kg": 10.0,
        "review_required": False,
    }
    candidates = [
        {**base, "source_facility_id": "a"},
        {**base, "source_facility_id": "b"},
    ]
    values, rejected = collapse_source_candidates(candidates)
    key = (2024, "plant", "nox", "cleansys")
    assert key not in values
    assert key in rejected


def test_reconciliation_uses_precedence_and_flags_disagreement() -> None:
    candidates = [
        {
            "year": 2024,
            "plant_id": "plant",
            "pollutant": "nox",
            "source": source,
            "source_facility_id": source,
            "emissions_kg": value,
            "review_required": False,
        }
        for source, value in (
            ("direct_company", 100.0),
            ("cleansys", 40.0),
            ("env_info", 30.0),
        )
    ]
    row = reconcile_emissions(candidates, disagreement_threshold=0.5)[0]
    assert row["selected_source"] == "direct_company"
    assert row["selected_emissions_kg"] == 100.0
    assert row["review_required"] is True


def test_emission_factor_requires_positive_generation() -> None:
    assert factor(100.0, 50.0) == 2.0
    assert factor(100.0, 0.0) == ""
    assert factor(100.0, None) == ""


def test_operator_category_identifies_kepco_variants() -> None:
    assert operator_category("남부발전㈜") == "kepco"
    assert operator_category("한국전력") == "kepco"
    assert operator_category("GS EPS") == "private_or_other"


def test_fuel_validation_accepts_known_aliases() -> None:
    assert validation_status("가스", "LNG")[0] == "alias_match"
    assert validation_status("석탄 | 유연탄", "유연탄")[0] == "alias_match"


def test_fuel_validation_flags_mismatch_and_missing_roster() -> None:
    assert validation_status("LNG", "유연탄")[0] == "mismatch"
    assert validation_status("LNG", "")[0] == "no_roster_fuel"
