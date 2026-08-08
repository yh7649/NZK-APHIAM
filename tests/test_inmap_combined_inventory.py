from __future__ import annotations

import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pandas as pd
import pytest
from scipy.io import netcdf_file

from nzk_aphiam.air_quality.inmap.combined_inventory import (
    audit_nonpower_factor_catalog,
    build_harmonized_ledger,
    build_nonpower_point_inventory,
    build_power_emissions,
    prepare_nonpower_emissions,
    spatialize_nonpower_with_geometry,
    spatialize_nonpower_with_monitor_surrogates,
    write_coards_inventory,
    write_coordinate_coards_inventory,
)
from nzk_aphiam.air_quality.inmap.combined_runner import (
    load_run_jobs,
    prepare_run_instructions,
    run_all,
)
from nzk_aphiam.air_quality.inmap.inventory import write_inventory
from nzk_aphiam.air_quality.inmap.runner import run_scenario
from nzk_aphiam.mvp.peng_replication.scenarios import normalize_macro_scenarios


def _factor_tables(*, production_ready: str = "false") -> tuple[pd.DataFrame, pd.DataFrame]:
    factors = pd.DataFrame(
        [
            {
                "record_id": "EF1",
                "production_ready": production_ready,
                "review_status": "candidate",
                "pollutant": "NOx",
                "unit": "kg/ton-fuel",
            }
        ]
    )
    links = pd.DataFrame(
        [
            {
                "record_id": "EF1",
                "inventory_id": "activity_1",
                "production_ready": production_ready,
                "match_status": "exact",
            }
        ]
    )
    return factors, links


def test_nonpower_factor_catalog_blocks_unapproved_production_mode() -> None:
    factors, links = _factor_tables()
    audit = audit_nonpower_factor_catalog(
        factors,
        links,
        emissions_mode="capss_base_intensity_screening",
    )
    assert audit["production_ready_factor_rows"] == 0
    candidate_audit = audit_nonpower_factor_catalog(
        factors,
        links,
        emissions_mode="candidate_factor_screening",
    )
    assert candidate_audit["production_ready_factor_rows"] == 0
    with pytest.raises(ValueError, match="requires production-ready"):
        audit_nonpower_factor_catalog(
            factors,
            links,
            emissions_mode="approved_factor_inventory",
        )


def test_macro_combined_technology_label_is_split(tmp_path: Path) -> None:
    path = tmp_path / "macro_power.csv"
    pd.DataFrame(
        [
            {
                "Scenario": "policy",
                "Year": 2030,
                "Province": "CNA",
                "Technology": "ThermalPower{Coal}",
                "Generation_TWh": 1.5,
            }
        ]
    ).to_csv(path, index=False)
    normalized = normalize_macro_scenarios(
        path,
        scenario_label="unused",
        province_crosswalk={"CNA": "Chungcheongnam-do"},
        fuel_crosswalk={"Coal": "coal"},
        technology_crosswalk={"ThermalPower": {"Coal": "conventional_steam_turbine"}},
    )
    assert normalized.loc[0, "macro_fuel"] == "Coal"
    assert normalized.loc[0, "macro_technology"] == "ThermalPower"
    assert normalized.loc[0, "generation_mwh"] == pytest.approx(1_500_000.0)


def _fleet() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "plant_id": "plant-1",
                "plant_name": "Plant 1",
                "unit_id": "unit-1",
                "province": "Chungcheongnam-do",
                "fuel": "coal",
                "technology": "conventional_steam_turbine",
                "capacity_mw": 100.0,
                "commissioning_year": 2000,
                "retirement_year": pd.NA,
                "longitude": 126.5,
                "latitude": 36.5,
                "stack_height_m": 100.0,
                "stack_diameter_m": 5.0,
                "stack_temperature_k": 373.15,
                "stack_velocity_m_s": 20.0,
                "nox_ef_kg_per_mwh": 0.1,
                "sox_ef_kg_per_mwh": 0.2,
                "dust_tsp_ef_kg_per_mwh": 0.03,
                "nox_ef_mapping_level": "test_exact",
                "sox_ef_mapping_level": "test_exact",
                "dust_tsp_ef_mapping_level": "test_exact",
            }
        ]
    )


def _generation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": "policy",
                "year": 2030,
                "province": "Chungcheongnam-do",
                "fuel": "coal",
                "technology": "conventional_steam_turbine",
                "generation_mwh": 1_000.0,
            }
        ]
    )


def test_power_generation_times_kepco_ef_and_keeps_tsp_out_of_pm25() -> None:
    power, diagnostics = build_power_emissions(
        _generation(),
        _fleet(),
        fuel_compatibility={"coal": ["coal"]},
        tolerance_mwh=0.001,
        ef_source="test.csv",
        ef_year=2024,
    )
    assert diagnostics.loc[0, "mass_balance_error_mwh"] == pytest.approx(0.0)
    assert power.loc[0, "nox_kg"] == pytest.approx(100.0)
    assert power.loc[0, "sox_kg"] == pytest.approx(200.0)
    assert power.loc[0, "dust_tsp_kg"] == pytest.approx(30.0)
    assert power.loc[0, "pm25_kg"] == 0.0
    assert "omitted" in power.loc[0, "pm25_treatment"]


def _nonpower_config() -> dict:
    return {
        "years": [2030],
        "scenario_pairs": {
            "policy": {
                "power": "policy",
                "nonpower": "gcam_policy",
            }
        },
        "nonpower": {"emissions_mode": "capss_base_intensity_screening"},
    }


def _projected_nonpower() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": "gcam_policy",
                "year": 2030,
                "sector": "생산공정",
                "fuel": "missing",
                "pollutant": "NOx",
                "activity": 80.0,
                "emission_factor_kg_per_activity": 10.0,
                "projected_emissions_kg": 800.0,
            },
            {
                "scenario": "gcam_policy",
                "year": 2030,
                "sector": "농업",
                "fuel": "missing",
                "pollutant": "NH3",
                "activity": 90.0,
                "emission_factor_kg_per_activity": 20.0,
                "projected_emissions_kg": 1_800.0,
            },
        ]
    )


def test_grid_writer_and_harmonized_ledger_preserve_mass(tmp_path: Path) -> None:
    factors, links = _factor_tables()
    factor_audit = audit_nonpower_factor_catalog(
        factors,
        links,
        emissions_mode="capss_base_intensity_screening",
    )
    nonpower = prepare_nonpower_emissions(
        _projected_nonpower(),
        _nonpower_config(),
        factor_audit=factor_audit,
    )
    path = tmp_path / "nonpower.nc"
    details = write_coards_inventory(
        nonpower,
        path,
        grid_config={
            "status": "test_proxy",
            "latitudes": [35.0, 37.0],
            "longitudes": [126.0, 128.0],
            "weights": [[0.1, 0.2], [0.3, 0.4]],
        },
    )
    assert details["totals_kg"]["NOx"] == pytest.approx(800.0)
    assert details["totals_kg"]["NH3"] == pytest.approx(1_800.0)
    with netcdf_file(path, mode="r", mmap=False) as dataset:
        assert float(dataset.variables["NOx"][:].sum()) == pytest.approx(800.0)
        assert float(dataset.variables["NH3"][:].sum()) == pytest.approx(1_800.0)

    power, _ = build_power_emissions(
        _generation(),
        _fleet(),
        fuel_compatibility={"coal": ["coal"]},
        tolerance_mwh=0.001,
        ef_source="test.csv",
        ef_year=2024,
    )
    ledger = build_harmonized_ledger(power, nonpower)
    totals = ledger.groupby(["source_family", "pollutant"])["emissions_kg"].sum()
    assert totals.loc[("power", "NOx")] == pytest.approx(100.0)
    assert totals.loc[("nonpower", "NOx")] == pytest.approx(800.0)
    process = ledger.loc[
        ledger["source_id"].eq("생산공정::missing"), "spatialization_status"
    ].iloc[0]
    assert process.startswith("downgraded_to_proxy_grid")


def test_one_nonpower_nzk_path_can_pair_with_two_power_cases() -> None:
    factors, links = _factor_tables()
    factor_audit = audit_nonpower_factor_catalog(
        factors,
        links,
        emissions_mode="capss_base_intensity_screening",
    )
    config = _nonpower_config()
    config["scenario_pairs"] = {
        "nzk_with_power_plant_nzk": {
            "power": "power_nzk",
            "nonpower": "gcam_policy",
        },
        "nzk_without_power_plant_nzk": {
            "power": "power_no_nzk",
            "nonpower": "gcam_policy",
        },
    }
    selected = prepare_nonpower_emissions(
        _projected_nonpower(),
        config,
        factor_audit=factor_audit,
    )
    assert set(selected["scenario"]) == {
        "nzk_with_power_plant_nzk",
        "nzk_without_power_plant_nzk",
    }
    assert selected["source_scenario"].eq("gcam_policy").all()
    assert len(selected) == 2 * len(_projected_nonpower())


def test_reviewed_nonpower_geometry_writes_point_and_grid_inputs(
    tmp_path: Path,
) -> None:
    emissions = pd.DataFrame(
        [
            {
                "scenario": "nzk",
                "year": 2030,
                "inventory_id": "industry",
                "sector": "industry",
                "fuel": "coal",
                "pollutant": "NOx",
                "activity": 10.0,
                "projected_emissions_kg": 100.0,
                "inmap_field": "NOx",
                "geometry_type": "Pending",
                "preferred_geometry": "Pending",
                "spatialization_status": "pending_reviewed_coordinate_join",
                "activity_unit": "tonne product",
                "emission_factor_kg_per_activity": 10.0,
                "emission_factor_unit": "kg/ton-product",
                "factor_method": "approved_nonpower_factor_inventory",
            },
            {
                "scenario": "nzk",
                "year": 2030,
                "inventory_id": "agriculture",
                "sector": "agriculture",
                "fuel": "none",
                "pollutant": "NH3",
                "activity": 20.0,
                "projected_emissions_kg": 200.0,
                "inmap_field": "NH3",
                "geometry_type": "Pending",
                "preferred_geometry": "Pending",
                "spatialization_status": "pending_reviewed_coordinate_join",
                "activity_unit": "kg nitrogen applied",
                "emission_factor_kg_per_activity": 10.0,
                "emission_factor_unit": "kg/kg-N",
                "factor_method": "approved_nonpower_factor_inventory",
            },
        ]
    )
    geometry = pd.DataFrame(
        [
            {
                "spatial_id": "facility-1",
                "inventory_id": "industry",
                "geometry_type": "Point",
                "latitude": 36.0,
                "longitude": 127.0,
                "weight": 1.0,
                "stack_height_m": 100.0,
                "stack_diameter_m": 5.0,
                "stack_temperature_k": 373.15,
                "stack_velocity_m_s": 20.0,
                "status": "production_ready",
                "source_id": "facility_source",
            },
            {
                "spatial_id": "grid-1",
                "inventory_id": "agriculture",
                "geometry_type": "Grid",
                "latitude": 35.0,
                "longitude": 126.0,
                "weight": 0.25,
                "stack_height_m": "",
                "stack_diameter_m": "",
                "stack_temperature_k": "",
                "stack_velocity_m_s": "",
                "status": "production_ready",
                "source_id": "grid_source",
            },
            {
                "spatial_id": "grid-2",
                "inventory_id": "agriculture",
                "geometry_type": "Grid",
                "latitude": 37.0,
                "longitude": 128.0,
                "weight": 0.75,
                "stack_height_m": "",
                "stack_diameter_m": "",
                "stack_temperature_k": "",
                "stack_velocity_m_s": "",
                "status": "production_ready",
                "source_id": "grid_source",
            },
        ]
    )
    allocated = spatialize_nonpower_with_geometry(emissions, geometry)
    totals = allocated.groupby("pollutant")["projected_emissions_kg"].sum()
    assert totals["NOx"] == pytest.approx(100.0)
    assert totals["NH3"] == pytest.approx(200.0)

    point = build_nonpower_point_inventory(
        allocated.loc[allocated["geometry_type"].eq("Point")]
    )
    assert point.loc[0, "nox_kg"] == pytest.approx(100.0)
    assert point.loc[0, "nh3_kg"] == pytest.approx(0.0)

    grid_path = tmp_path / "reviewed.nc"
    details = write_coordinate_coards_inventory(
        allocated.loc[allocated["geometry_type"].eq("Grid")],
        grid_path,
    )
    assert details["totals_kg"]["NH3"] == pytest.approx(200.0)


def test_monitor_surrogate_spatialization_preserves_mass() -> None:
    emissions = pd.DataFrame(
        [
            {
                "scenario": "nzk",
                "year": 2030,
                "inventory_id": "industry",
                "sector": "industry",
                "fuel": "aggregate",
                "pollutant": "NOx",
                "activity": 10.0,
                "projected_emissions_kg": 100.0,
                "inmap_field": "NOx",
                "preferred_geometry": "Pending",
                "spatialization_status": "pending",
            }
        ]
    )
    surrogates = pd.DataFrame(
        [
            {
                "inventory_id": "industry",
                "pollutant": "NOx",
                "latitude": latitude,
                "longitude": longitude,
                "weight": weight,
                "coordinate_method": "test_monitor_centroid",
                "spatialization_status": "maximum_coverage_poc_monitor_proxy",
            }
            for latitude, longitude, weight in [
                (35.0, 126.0, 0.25),
                (37.0, 128.0, 0.75),
            ]
        ]
    )
    allocated = spatialize_nonpower_with_monitor_surrogates(emissions, surrogates)
    assert allocated["projected_emissions_kg"].sum() == pytest.approx(100.0)
    assert sorted(allocated["projected_emissions_kg"]) == pytest.approx([25.0, 75.0])
    assert set(allocated["geometry_type"]) == {"Grid"}
    assert set(allocated["spatialization_status"]) == {
        "maximum_coverage_poc_monitor_proxy"
    }


def test_prepare_combined_run_instructions_writes_runnable_toml(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    job_dir = bundle / "policy" / "2030"
    point = _fleet().assign(
        scenario="policy",
        year=2030,
        voc_kg=0.0,
        nox_kg=100.0,
        nh3_kg=0.0,
        sox_kg=200.0,
        pm25_kg=0.0,
        pm25_treatment="omitted",
        nh3_treatment="omitted",
        voc_treatment="omitted",
    )
    point_files = write_inventory(point, job_dir / "power_point")
    grid_path = job_dir / "nonpower_grid" / "emissions.nc"
    write_coards_inventory(
        _projected_nonpower(),
        grid_path,
        grid_config={
            "status": "test_proxy",
            "latitudes": [35.0, 37.0],
            "longitudes": [126.0, 128.0],
            "weights": [[0.25, 0.25], [0.25, 0.25]],
        },
    )
    input_manifest = {
        "scenario": "policy",
        "year": 2030,
        "analytical_use_permitted": False,
        "inputs": [
            {
                "id": "power",
                "sector": "power",
                "format": "shapefile",
                "path": "power_point/emissions.shp",
                "units": "kg/year",
            },
            {
                "id": "nonpower",
                "sector": "nonpower",
                "format": "coards",
                "path": "nonpower_grid/emissions.nc",
                "units": "kg",
                "coards_year": 2030,
            },
        ],
    }
    (job_dir / "emission_inputs.json").write_text(json.dumps(input_manifest))
    root_manifest = {
        "analytical_use_permitted": False,
        "jobs": [
            {
                "scenario": "policy",
                "year": 2030,
                "manifest": "policy/2030/emission_inputs.json",
            }
        ],
    }
    (bundle / "combined_inmap_input_manifest.json").write_text(json.dumps(root_manifest))

    executable = tmp_path / "inmap"
    executable.write_text("binary")
    executable.chmod(0o755)
    installation_files = {}
    for key, name in {
        "inmap_data": "InMAPData.ncf",
        "variable_grid_data": "grid.gob",
        "population_file": "Pop.ncf",
        "mortality_rate_file": "mortality.shp",
    }.items():
        path = tmp_path / name
        path.write_text("placeholder")
        installation_files[key] = str(path)
    installation_path = tmp_path / "installation.json"
    installation_path.write_text(json.dumps({"executable": str(executable), **installation_files}))

    run_dir = tmp_path / "run"
    jobs_path = prepare_run_instructions(
        bundle,
        installation_path,
        run_dir,
        num_iterations=200,
    )
    instructions = json.loads(jobs_path.read_text())
    assert instructions["job_count"] == 1
    assert instructions["solver_mode"] == "fixed_iterations_poc"
    assert not instructions["analytical_use_permitted"]
    config = (run_dir / "configs" / "policy_2030.toml").read_text()
    assert "NumIterations = 200" in config
    assert "[aep.InventoryConfig.COARDSFiles]" in config
    _, jobs, _ = load_run_jobs(jobs_path)
    assert jobs[0]["emission_files"] == [
        point_files["shapefile"].resolve(),
        grid_path.resolve(),
    ]
    assert not jobs[0]["analytical_use_permitted"]

    power_only_dir = tmp_path / "power_only_run"
    power_only_jobs_path = prepare_run_instructions(
        bundle,
        installation_path,
        power_only_dir,
        num_iterations=50,
        power_only=True,
        scenarios=["policy"],
        years=[2030],
    )
    power_only_manifest = json.loads(power_only_jobs_path.read_text())
    assert power_only_manifest["job_count"] == 1
    assert power_only_manifest["emissions_scope"] == "thermal_power_only"
    assert power_only_manifest["selected_scenarios"] == ["policy"]
    assert power_only_manifest["selected_years"] == [2030]
    power_only_config = (power_only_dir / "configs" / "policy_2030.toml").read_text()
    assert "NumIterations = 50" in power_only_config
    assert "[aep.InventoryConfig.COARDSFiles]" not in power_only_config
    _, power_only_jobs, _ = load_run_jobs(power_only_jobs_path)
    assert power_only_jobs[0]["emission_files"] == [
        point_files["shapefile"].resolve()
    ]


def test_strict_solver_does_not_override_screening_input_status(
    tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "inmap"
    executable.write_text("binary")
    executable.chmod(0o755)
    config = tmp_path / "config.toml"
    config.write_text("NumIterations = 0\n")
    shapefile = tmp_path / "emissions.shp"
    shapefile.write_text("input")
    output = tmp_path / "output" / "concentrations.shp"

    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.runner.executable_version",
        lambda _: "InMAP v1.9.0",
    )

    def complete_run(*_args, **_kwargs):
        output.write_text("result")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("nzk_aphiam.air_quality.inmap.runner.subprocess.run", complete_run)
    state = run_scenario(
        executable,
        {
            "scenario": "policy",
            "year": 2030,
            "config": config,
            "output": output,
            "shapefile": shapefile,
            "num_iterations": 0,
            "analytical_use_permitted": False,
        },
    )
    assert state["converged"]
    assert not state["input_analytical_use_permitted"]
    assert not state["analytical_use_permitted"]


def test_combined_runner_bounds_parallel_jobs_and_partitions_cpu_threads(
    tmp_path: Path, monkeypatch
) -> None:
    jobs = [
        {
            "scenario": "no_nzk",
            "year": 2025,
            "output": tmp_path / "no_nzk.shp",
            "analytical_use_permitted": False,
        },
        {
            "scenario": "nzk_low",
            "year": 2025,
            "output": tmp_path / "nzk_low.shp",
            "analytical_use_permitted": False,
        },
    ]
    manifest = {"solver_mode": "fixed_iterations_poc", "num_iterations": 200}
    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.combined_runner.load_run_jobs",
        lambda _path: (tmp_path / "inmap", jobs, manifest),
    )
    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.combined_runner.os.cpu_count",
        lambda: 14,
    )
    overlap = Barrier(2)
    observed_threads = []

    def complete_job(_executable, job, **kwargs):
        observed_threads.append(kwargs["max_threads"])
        overlap.wait(timeout=2)
        return {
            "scenario": job["scenario"],
            "year": job["year"],
            "converged": False,
        }

    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.combined_runner.run_scenario",
        complete_job,
    )
    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.combined_runner.read_output",
        lambda _path: [1, 2],
    )

    summary_path = run_all(tmp_path / "run_jobs.json", max_workers=2)

    summary = json.loads(summary_path.read_text())
    assert observed_threads == [7, 7]
    assert summary["max_workers"] == 2
    assert summary["threads_per_job"] == 7
    assert summary["completed_jobs"] == 2
    assert summary["all_complete"]
