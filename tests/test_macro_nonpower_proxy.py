from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.config.paths import PROJECT_ROOT
from nzk_aphiam.data.process.macro.integrator import integrate_macro_inputs
from nzk_aphiam.data.process.macro.proxy_activity import (
    COMPATIBILITY_COLUMNS,
    _activity_index,
    build_capss_compatibility,
    build_detailed_activity,
    load_config,
)

CONFIG_PATH = PROJECT_ROOT / "configs" / "scenarios" / "gcam_kaist_nonpower_proxy_2025_2050.yaml"


def _config() -> dict[str, object]:
    return load_config(CONFIG_PATH)


def _capss_row(
    *,
    sector: str,
    fuel: str | None,
    emissions_kg: float,
    pollutant: str = "NOx",
) -> dict[str, object]:
    return {
        "year": 2023,
        "source_category": sector,
        "source_midcategory": f"{sector}_mid",
        "source_subcategory": f"{sector}_sub",
        "fuel_category": fuel,
        "fuel_type": fuel,
        "pollutant": pollutant,
        "emissions_kg": emissions_kg,
    }


def test_activity_index_anchors_2023_and_2025_then_reaches_endpoint() -> None:
    config = _config()

    assert (
        _activity_index(
            config,
            profile="road_passenger_ice",
            scenario="nzk_high",
            year=2023,
        )
        == 100.0
    )
    assert (
        _activity_index(
            config,
            profile="road_passenger_ice",
            scenario="nzk_high",
            year=2025,
        )
        == 100.0
    )
    assert (
        _activity_index(
            config,
            profile="road_passenger_ice",
            scenario="nzk_high",
            year=2035,
        )
        == 60.0
    )
    assert (
        _activity_index(
            config,
            profile="road_passenger_ice",
            scenario="nzk_high",
            year=2050,
        )
        == 0.0
    )


def test_detailed_proxy_covers_every_p1_mvp_activity_and_flags_fisheries_overlap() -> None:
    config = _config()
    inventory = pd.read_csv(config["inputs"]["inventory"])
    crosswalk = pd.read_csv(config["inputs"]["crosswalk"])

    detailed = build_detailed_activity(inventory, crosswalk, config)

    assert len(detailed) == 50 * 3 * 7
    assert detailed["inventory_id"].nunique() == 50
    assert detailed["scenario"].nunique() == 3
    assert detailed["year"].tolist().count(2023) == 50 * 3
    assert detailed.loc[detailed["year"].isin([2023, 2025]), "activity"].eq(100.0).all()
    assert detailed["activity"].ge(0).all()
    fisheries = detailed.loc[detailed["inventory_id"].eq("agr_fisheries_combustion")]
    assert not fisheries["include_in_emissions_model"].any()
    assert fisheries["double_counting_risk"].eq("high").all()
    fishing_vessels = detailed.loc[detailed["inventory_id"].eq("trn_shipping_fishing")]
    assert fishing_vessels["include_in_emissions_model"].all()


def test_capss_compatibility_has_exact_five_column_shape_and_excludes_power_mix() -> None:
    config = _config()
    capss = pd.DataFrame(
        [
            _capss_row(
                sector="도로이동오염원",
                fuel="경유",
                emissions_kg=1_000.0,
            ),
            _capss_row(
                sector="도로이동오염원",
                fuel="하이브리드",
                emissions_kg=200.0,
            ),
            _capss_row(
                sector="에너지산업 연소",
                fuel="유연탄",
                emissions_kg=2_000.0,
            ),
        ]
    )

    compatibility, audit = build_capss_compatibility(capss, config)

    assert compatibility.columns.tolist() == COMPATIBILITY_COLUMNS
    assert len(compatibility) == 2 * 3 * 7
    assert "에너지산업_연소" not in compatibility["sector"].unique()
    high_2050 = compatibility.loc[
        compatibility["scenario"].eq("nzk_high") & compatibility["year"].eq(2050)
    ]
    assert high_2050["activity"].eq(0.0).all()
    low_hybrid_2050 = audit.loc[
        audit["scenario"].eq("nzk_low") & audit["year"].eq(2050) & audit["fuel"].eq("하이브리드")
    ].iloc[0]
    assert low_hybrid_2050["activity"] == 60.0
    assert low_hybrid_2050["projection_profile"] == "road_passenger_hybrid"


def test_capss_compatibility_round_trips_through_macro_integrator(tmp_path: Path) -> None:
    config = _config()
    capss = pd.DataFrame(
        [
            _capss_row(
                sector="도로이동오염원",
                fuel="경유",
                emissions_kg=1_000.0,
            ),
            _capss_row(
                sector="농업",
                fuel=None,
                emissions_kg=300.0,
            ),
        ]
    )
    compatibility, _ = build_capss_compatibility(capss, config)
    activity_path = tmp_path / "activity.csv"
    capss_path = tmp_path / "capss.parquet"
    output_dir = tmp_path / "integration"
    compatibility.to_csv(activity_path, index=False)
    capss.to_parquet(capss_path, index=False)

    integrate_macro_inputs(
        gcam_path=activity_path,
        capss_path=capss_path,
        output_dir=output_dir,
        base_year=2023,
        scenario_columns=["scenario"],
        pollutants=["NOx"],
    )

    diagnostics = pd.read_csv(output_dir / "macro_input_diagnostics.csv")
    assert diagnostics.empty
    projected = pd.read_csv(output_dir / "macro_projected_emissions.csv")
    for scenario in config["scenarios"]:
        base = projected.loc[projected["scenario"].eq(scenario) & projected["year"].eq(2023)]
        assert base["projected_emissions_kg"].sum() == pytest.approx(1_300.0)
