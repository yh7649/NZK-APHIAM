from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from nzk_aphiam.health.combined_inmap import PRIMARY_CRF_ID
from nzk_aphiam.health.combined_report import (
    build_report_tables,
    write_combined_report,
)


def _report_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    concentrations = {
        "no_nzk": {2030: 1.0, 2050: 1.2},
        "nzk_low": {2030: 0.9, 2050: 0.6},
        "nzk_high": {2030: 0.8, 2050: 0.3},
    }
    exposure_rows = []
    mortality_rows = []
    for scenario, by_year in concentrations.items():
        for year, concentration in by_year.items():
            exposure_rows.append(
                {
                    "scenario": scenario,
                    "year": year,
                    "population_weighted_pm25_ugm3": concentration,
                    "result_status": "nonconverged_poc_diagnostic_not_for_inference",
                    "analytical_use_permitted": False,
                }
            )
            deaths = concentration * 100
            mortality_rows.append(
                {
                    "crf_id": PRIMARY_CRF_ID,
                    "scenario": scenario,
                    "year": year,
                    "attributable_deaths": deaths,
                    "attributable_deaths_ci_low": deaths * 0.8,
                    "attributable_deaths_ci_high": deaths * 1.2,
                    "population_year": year,
                    "mortality_year": 2024,
                    "result_status": "nonconverged_poc_diagnostic_not_for_inference",
                    "analytical_use_permitted": False,
                }
            )
    comparison_rows = []
    for policy in ("nzk_low", "nzk_high"):
        for year in (2030, 2050):
            avoided = (
                concentrations["no_nzk"][year] - concentrations[policy][year]
            ) * 100
            comparison_rows.append(
                {
                    "crf_id": PRIMARY_CRF_ID,
                    "reference_scenario": "no_nzk",
                    "policy_scenario": policy,
                    "year": year,
                    "avoided_deaths": avoided,
                    "avoided_deaths_ci_low": avoided * 0.8,
                    "avoided_deaths_ci_high": avoided * 1.2,
                }
            )
    return (
        pd.DataFrame(exposure_rows),
        pd.DataFrame(mortality_rows),
        pd.DataFrame(comparison_rows),
    )


def test_report_tables_calculate_reductions_and_headline_year() -> None:
    exposures, mortality, comparisons = _report_inputs()
    tables = build_report_tables(exposures, mortality, comparisons)

    inmap = tables["inmap_scenario_results"]
    low_2050 = inmap.loc[
        inmap["scenario"].eq("nzk_low") & inmap["year"].eq(2050)
    ].iloc[0]
    assert low_2050["pm25_reduction_vs_no_nzk_ugm3"] == 0.6
    assert low_2050["pm25_reduction_vs_no_nzk_percent"] == 50.0
    assert len(tables["benmap_avoided_mortality"]) == 4
    assert len(tables["headline_results_2050"]) == 2


def test_combined_report_writes_tables_figures_and_manifest(tmp_path: Path) -> None:
    exposures, mortality, comparisons = _report_inputs()
    health_dir = tmp_path / "health"
    health_dir.mkdir()
    exposures.to_csv(health_dir / "exposures.csv", index=False)
    mortality.to_csv(health_dir / "mortality.csv", index=False)
    comparisons.to_csv(health_dir / "comparisons.csv", index=False)
    (health_dir / "health_postprocess_manifest.json").write_text(
        json.dumps(
            {
                "inmap_num_iterations": 50,
                "result_status": "nonconverged_poc_diagnostic_not_for_inference",
                "outputs": {
                    "exposures": "exposures.csv",
                    "primary_totals": "mortality.csv",
                    "comparisons": "comparisons.csv",
                },
            }
        ),
        encoding="utf-8",
    )

    manifest_path = write_combined_report(
        health_dir,
        tmp_path / "figures",
        tmp_path / "tables",
    )

    manifest = json.loads(manifest_path.read_text())
    assert not manifest["analytical_use_permitted"]
    assert len(manifest["figures"]) == 3
    assert len(manifest["tables"]) == 4
    for path in [*manifest["figures"].values(), *manifest["tables"].values()]:
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0
