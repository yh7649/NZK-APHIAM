from __future__ import annotations

import json
from pathlib import Path
import tomllib
from types import SimpleNamespace

import geopandas as gpd
import pytest
from scipy.io import netcdf_file
import shapefile
from shapely.geometry import Point, box

from nzk_aphiam.air_quality.inmap.emission_inputs import (
    select_supplemental_emissions,
    validate_coards_netcdf,
    validate_emissions_shapefile,
)
from nzk_aphiam.air_quality.inmap.exposure import (
    national_population_weighted_exposure,
    national_scenario_exposure,
)
from nzk_aphiam.air_quality.inmap.installation import install_global_inmap
from nzk_aphiam.air_quality.inmap.inventory import (
    generate_scenario_inputs,
    write_config,
    write_inventory,
)
from nzk_aphiam.air_quality.inmap.outputs import difference_outputs
from nzk_aphiam.air_quality.inmap.runner import run_scenario


def test_install_rejects_unexpected_executable_version(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "inmap-v1.9.6-darwin-arm64"
    executable.write_text("placeholder")
    executable.chmod(0o755)
    model_files = {
        "inmap_data": tmp_path / "InMAPData_v1.0.0.ncf",
        "variable_grid_data": tmp_path / "global_inmap_004x003_v1.1.0.gob",
        "population_file": tmp_path / "Pop.ncf",
    }
    for path in model_files.values():
        path.write_text("placeholder")
    mortality = tmp_path / "unused_mortality.shp"
    mortality.write_text("placeholder")
    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.installation.detect_executable",
        lambda *_: executable,
    )
    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.installation.install_model_data",
        lambda *_args, **_kwargs: model_files,
    )
    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.installation.ensure_unused_mortality_file",
        lambda *_: mortality,
    )
    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.installation.executable_version",
        lambda *_: "InMAP v0.0.0",
    )
    config = {
        "inmap": {
            "cache_path": tmp_path,
            "version": "v1.9.6",
            "expected_executable_version_output": "InMAP v1.9.0",
            "model_data_filename": "EvaluationData_v1.1.0.zip",
            "model_data_md5": "unused",
            "model_data_version": "v1.1.0",
            "source_commit": "7b665744065a447d2f2a64aa7124c043ef5b8b2e",
            "release_url": "https://github.com/spatialmodel/inmap/releases/tag/v1.9.6",
            "model_data_record": "https://doi.org/10.5281/zenodo.6189451",
        }
    }
    with pytest.raises(ValueError, match="Unexpected InMAP executable version"):
        install_global_inmap(config, skip_download=True)


def _inventory():
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "plant_id": "p1",
                "unit_id": "u1",
                "plant_name": "Plant 1",
                "longitude": 127.0,
                "latitude": 36.0,
                "voc_kg": 0.0,
                "nox_kg": 10.0,
                "nh3_kg": 0.0,
                "sox_kg": 5.0,
                "pm25_kg": 0.0,
                "stack_height_m": 100.0,
                "stack_diameter_m": 5.0,
                "stack_temperature_k": 373.15,
                "stack_velocity_m_s": 20.0,
                "pm25_treatment": "omitted",
                "nh3_treatment": "omitted",
                "voc_treatment": "omitted",
            }
        ]
    )


def test_inmap_input_schema_and_annual_units(tmp_path: Path) -> None:
    files = write_inventory(_inventory(), tmp_path / "input")
    reader = shapefile.Reader(str(files["shapefile"]))
    fields = [field.name for field in reader.fields]
    for required in ["VOC", "NOx", "NH3", "SOx", "PM2_5", "height", "diam", "temp", "velocity"]:
        assert required in fields
    schema = json.loads(files["schema"].read_text())
    assert schema["emission_units"] == "kg/year"
    assert schema["crs"] == "EPSG:4326"


def test_scenario_exposure_emits_generic_health_concentration_and_scope(
    tmp_path: Path,
) -> None:
    boundary_path = tmp_path / "countries.shp"
    gpd.GeoDataFrame(
        {"ISO_A3": ["KOR"]},
        geometry=[box(126.0, 35.0, 129.0, 38.0)],
        crs="EPSG:4326",
    ).to_file(boundary_path)
    output = gpd.GeoDataFrame(
        {
            "TotalPM25": [10.0, 20.0, 100.0],
            "TotalPop": [1.0, 3.0, 10.0],
        },
        geometry=[
            box(126.1, 35.1, 126.9, 35.9),
            box(127.1, 36.1, 127.9, 36.9),
            box(130.0, 36.0, 131.0, 37.0),
        ],
        crs="EPSG:4326",
    )

    exposure = national_scenario_exposure(
        output,
        boundary_path,
        scenario="policy",
        year=2030,
        concentration_scope="all_source_total_ambient_pm25",
    )

    assert exposure.loc[0, "population_weighted_pm25_ugm3"] == pytest.approx(17.5)
    assert exposure.loc[0, "population_weighted_incremental_pm25_ugm3"] == pytest.approx(17.5)
    assert exposure.loc[0, "concentration_scope"] == "all_source_total_ambient_pm25"
    assert exposure.loc[0, "represented_population"] == pytest.approx(4.0)


def test_global_config_uses_global_files_and_kg_per_year(tmp_path: Path) -> None:
    config = write_config(
        scenario="test",
        year=2030,
        inventory_path=tmp_path / "emissions.shp",
        inmap_data=tmp_path / "InMAPData_v1.0.0.ncf",
        variable_grid_data=tmp_path / "global_inmap_004x003_v1.1.0.gob",
        population_file=tmp_path / "population" / "Pop.ncf",
        mortality_rate_file=tmp_path / "unused_mortality.shp",
        output_path=tmp_path / "output.shp",
        config_path=tmp_path / "config.toml",
    )
    text = config.read_text()
    assert "static = true" in text
    assert "NumIterations = 0" in text
    assert 'EmissionUnits = "kg/year"' in text
    assert "InMAPData_v1.0.0" in text
    assert 'GridProj = "+proj=longlat +units=degrees"' in text
    assert "VariableGridXo = -180.0" in text
    assert "Xnests = [140, 2, 2, 2, 2, 2, 2, 2]" in text
    assert 'CensusFile = "' in text and "population/Pop.ncf" in text
    assert 'CensusPopColumns = ["TotalPop"]' in text
    assert "[VarGrid.MortalityRateColumns]" in text
    assert 'PrimPM25 = "PrimaryPM25"' in text
    assert 'TotalPM25 = "PrimaryPM25 + pSO4 + pNO3 + pNH4 + SOA"' in text


def _polygon_emissions(path: Path, *, nox: float = 2.0) -> Path:
    frame = gpd.GeoDataFrame(
        {"NOx": [nox], "NH3": [1.0]},
        geometry=[box(126.0, 35.0, 127.0, 36.0)],
        crs="EPSG:4326",
    )
    frame.to_file(path)
    return path


def _coards_emissions(path: Path) -> Path:
    with netcdf_file(path, mode="w") as dataset:
        dataset.createDimension("lat", 2)
        dataset.createDimension("lon", 2)
        latitude = dataset.createVariable("lat", "f", ("lat",))
        longitude = dataset.createVariable("lon", "f", ("lon",))
        nox = dataset.createVariable("NOx", "f", ("lat", "lon"))
        latitude[:] = [35.0, 36.0]
        longitude[:] = [126.0, 127.0]
        nox[:] = [[1.0, 2.0], [3.0, 4.0]]
    return path


def test_mixed_shapefile_and_coards_inputs_are_selected_and_configured(
    tmp_path: Path,
) -> None:
    polygon = _polygon_emissions(tmp_path / "traffic.shp")
    coards = _coards_emissions(tmp_path / "agriculture.nc")
    assert validate_emissions_shapefile(polygon)["geometry_types"] == ["Polygon"]
    assert validate_coards_netcdf(coards)["grid_shape"] == [2, 2]

    selected = select_supplemental_emissions(
        [
            {
                "id": "traffic_grid",
                "sector": "transport",
                "format": "shapefile",
                "path": polygon,
                "units": "kg/year",
                "scenarios": ["policy"],
                "years": [2030],
            },
            {
                "id": "agriculture_grid",
                "sector": "agriculture",
                "format": "coards",
                "path": coards,
                "units": "kg",
                "scenarios": "*",
                "years": [2030],
            },
        ],
        scenario="policy",
        year=2030,
        shapefile_units="kg/year",
    )
    assert [item["id"] for item in selected] == ["traffic_grid", "agriculture_grid"]

    config = write_config(
        scenario="policy",
        year=2030,
        inventory_path=tmp_path / "power.shp",
        inmap_data=tmp_path / "InMAPData_v1.0.0.ncf",
        variable_grid_data=tmp_path / "global_inmap_004x003_v1.1.0.gob",
        population_file=tmp_path / "population" / "Pop.ncf",
        mortality_rate_file=tmp_path / "unused_mortality.shp",
        output_path=tmp_path / "output.shp",
        config_path=tmp_path / "config.toml",
        supplemental_inputs=selected,
    )
    text = config.read_text()
    assert str(polygon.resolve()) in text
    assert "[aep.InventoryConfig.COARDSFiles]" in text
    assert '"agriculture" = [' in text
    assert str(coards.resolve()) in text
    assert "COARDSYear = 2030" in text
    assert 'InputUnits = "kg"' in text
    parsed = tomllib.loads(text)
    assert len(parsed["EmissionsShapefiles"]) == 2
    assert parsed["aep"]["InventoryConfig"]["COARDSFiles"]["agriculture"] == [
        str(coards.resolve())
    ]


def test_supplemental_scope_and_invalid_emissions_are_rejected(tmp_path: Path) -> None:
    polygon = _polygon_emissions(tmp_path / "traffic.shp", nox=-1.0)
    with pytest.raises(ValueError, match="non-negative"):
        select_supplemental_emissions(
            [
                {
                    "id": "traffic",
                    "format": "shapefile",
                    "path": polygon,
                    "scenarios": ["policy"],
                }
            ],
            scenario="policy",
            year=2030,
            shapefile_units="kg/year",
        )
    assert (
        select_supplemental_emissions(
            [
                {
                    "id": "traffic",
                    "format": "shapefile",
                    "path": polygon,
                    "scenarios": ["reference"],
                }
            ],
            scenario="policy",
            year=2030,
            shapefile_units="kg/year",
        )
        == []
    )
    valid = _polygon_emissions(tmp_path / "valid.shp")
    with pytest.raises(ValueError, match="counted twice"):
        select_supplemental_emissions(
            [
                {"id": "traffic", "format": "shapefile", "path": valid},
                {"id": "industry", "format": "shapefile", "path": valid},
            ],
            scenario="policy",
            year=2030,
            shapefile_units="kg/year",
        )


def test_generate_scenario_inputs_records_all_emission_dependencies(tmp_path: Path) -> None:
    emissions = _inventory().assign(scenario="policy", year=2030)
    polygon = _polygon_emissions(tmp_path / "factory.shp")
    jobs = generate_scenario_inputs(
        emissions,
        tmp_path / "run",
        {
            "inmap_data": tmp_path / "InMAPData_v1.0.0.ncf",
            "variable_grid_data": tmp_path / "global_inmap_004x003_v1.1.0.gob",
            "population_file": tmp_path / "population" / "Pop.ncf",
            "mortality_rate_file": tmp_path / "unused_mortality.shp",
        },
        supplemental_emissions=[
            {
                "id": "factories",
                "sector": "industry",
                "format": "shapefile",
                "path": polygon,
            }
        ],
    )
    assert len(jobs) == 1
    assert len(jobs[0]["emission_files"]) == 2
    manifest = json.loads(jobs[0]["input_manifest"].read_text())
    assert [item["id"] for item in manifest["inputs"]] == ["generated_power", "factories"]
    assert all(len(checksum) == 64 for checksum in manifest["dependency_sha256"].values())


def test_fixed_iteration_config_is_explicitly_requested(tmp_path: Path) -> None:
    config = write_config(
        scenario="poc",
        year=2030,
        inventory_path=tmp_path / "emissions.shp",
        inmap_data=tmp_path / "InMAPData_v1.0.0.ncf",
        variable_grid_data=tmp_path / "global_inmap_004x003_v1.1.0.gob",
        population_file=tmp_path / "population" / "Pop.ncf",
        mortality_rate_file=tmp_path / "unused_mortality.shp",
        output_path=tmp_path / "output.shp",
        config_path=tmp_path / "config.toml",
        num_iterations=200,
    )
    assert "NumIterations = 200" in config.read_text()


def test_fixed_iteration_run_state_prohibits_analytical_use(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "inmap"
    executable.write_text("placeholder")
    config = tmp_path / "config.toml"
    config.write_text("NumIterations = 200\n")
    shapefile = tmp_path / "input" / "emissions.shp"
    shapefile.parent.mkdir()
    shapefile.write_text("placeholder")
    output = tmp_path / "output" / "concentrations.shp"

    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.runner.executable_version",
        lambda _: "InMAP 1.9.6",
    )

    observed_environment = {}

    def complete_run(*_args, **kwargs):
        observed_environment.update(kwargs["env"])
        output.write_text("placeholder")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("nzk_aphiam.air_quality.inmap.runner.subprocess.run", complete_run)
    state = run_scenario(
        executable,
        {
            "scenario": "poc",
            "year": 2030,
            "config": config,
            "shapefile": shapefile,
            "output": output,
            "num_iterations": 200,
        },
        max_threads=7,
    )
    assert state["status"] == "complete"
    assert state["solver_mode"] == "fixed_iterations_poc"
    assert state["inmap_max_threads"] == 7
    assert observed_environment["GOMAXPROCS"] == "7"
    assert not state["converged"]
    assert not state["analytical_use_permitted"]


def test_run_cache_tracks_every_emissions_file(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "inmap"
    executable.write_text("placeholder")
    config = tmp_path / "config.toml"
    config.write_text("NumIterations = 0\n")
    shapefile = tmp_path / "power.shp"
    shapefile.write_text("power")
    supplemental = tmp_path / "traffic.nc"
    supplemental.write_text("first")
    output = tmp_path / "output" / "concentrations.shp"
    calls = 0

    monkeypatch.setattr(
        "nzk_aphiam.air_quality.inmap.runner.executable_version",
        lambda _: "InMAP 1.9.6",
    )

    def complete_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        output.write_text(f"run {calls}")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("nzk_aphiam.air_quality.inmap.runner.subprocess.run", complete_run)
    job = {
        "scenario": "policy",
        "year": 2030,
        "config": config,
        "shapefile": shapefile,
        "emission_files": [shapefile, supplemental],
        "output": output,
    }
    first = run_scenario(executable, job)
    cached = run_scenario(executable, job)
    supplemental.write_text("second")
    changed = run_scenario(executable, job)
    assert not first["cache_hit"]
    assert cached["cache_hit"]
    assert not changed["cache_hit"]
    assert calls == 2


def _output(path: Path, total: tuple[float, float]) -> None:
    frame = gpd.GeoDataFrame(
        {
            "PrimPM25": [0.0, 0.0],
            "pSO4": [value * 0.5 for value in total],
            "pNO3": [value * 0.5 for value in total],
            "pNH4": [0.0, 0.0],
            "SOA": [0.0, 0.0],
            "TotalPM25": list(total),
            "TotalPop": [100.0, 300.0],
        },
        geometry=[box(126.0, 35.0, 127.0, 36.0), box(127.0, 35.0, 128.0, 36.0)],
        crs="EPSG:4326",
    )
    frame.to_file(path)


def test_concentration_sign_and_population_weighting(tmp_path: Path) -> None:
    reference = tmp_path / "reference.shp"
    policy = tmp_path / "policy.shp"
    _output(reference, (3.0, 5.0))
    _output(policy, (1.0, 1.0))
    difference = difference_outputs(reference, policy, tmp_path / "difference.gpkg")
    assert difference["delta_TotalPM25"].tolist() == [2.0, 4.0]
    boundary = gpd.GeoDataFrame(
        {"ISO_A3": ["KOR"], "name": ["synthetic Korea"]},
        geometry=[box(125.0, 34.0, 129.0, 37.0)],
        crs="EPSG:4326",
    )
    boundary_path = tmp_path / "boundary.gpkg"
    boundary.to_file(boundary_path)
    exposure, _ = national_population_weighted_exposure(difference, boundary_path)
    assert exposure.loc[0, "population_weighted_delta_pm25_ugm3"] == 3.5
    assert exposure.loc[0, "sign_convention"] == "reference_minus_policy_positive_is_cleaner"


def test_national_filter_excludes_foreign_cell(tmp_path: Path) -> None:
    difference = gpd.GeoDataFrame(
        {"delta_TotalPM25": [1.0, 100.0], "TotalPop": [100.0, 10_000.0]},
        geometry=[Point(127.0, 36.0), Point(120.0, 36.0)],
        crs="EPSG:4326",
    )
    boundary = gpd.GeoDataFrame(
        {"ISO_A3": ["KOR"]}, geometry=[box(125.0, 34.0, 129.0, 38.0)], crs="EPSG:4326"
    )
    boundary_path = tmp_path / "boundary.gpkg"
    boundary.to_file(boundary_path)
    exposure, selected = national_population_weighted_exposure(difference, boundary_path)
    assert len(selected) == 1
    assert exposure.loc[0, "population_weighted_delta_pm25_ugm3"] == 1.0
