"""Global InMAP point-source and supplemental-emissions configuration generation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd
import shapefile

from nzk_aphiam.air_quality.inmap.emission_inputs import (
    emission_dependency_files,
    select_supplemental_emissions,
)

SHAPEFILE_FIELDS = {
    "VOC": "voc_kg",
    "NOx": "nox_kg",
    "NH3": "nh3_kg",
    "SOx": "sox_kg",
    "PM2_5": "pm25_kg",
    "height": "stack_height_m",
    "diam": "stack_diameter_m",
    "temp": "stack_temperature_k",
    "velocity": "stack_velocity_m_s",
}
WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


def _safe_label(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value)).strip("_")


def _toml_string(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_inventory_schema(inventory: pd.DataFrame) -> None:
    required = {"plant_id", "unit_id", "longitude", "latitude", *SHAPEFILE_FIELDS.values()}
    missing = sorted(required - set(inventory.columns))
    if missing:
        raise ValueError(f"InMAP inventory is missing fields: {missing}")
    if inventory[list(SHAPEFILE_FIELDS.values())].isna().any().any():
        raise ValueError("InMAP emissions or stack fields may not be missing.")
    if (inventory[["voc_kg", "nox_kg", "nh3_kg", "sox_kg", "pm25_kg"]] < 0).any().any():
        raise ValueError("InMAP emissions must be non-negative annual totals.")
    if (
        not inventory["latitude"].between(33.0, 39.0).all()
        or not inventory["longitude"].between(124.0, 132.0).all()
    ):
        raise ValueError("A plant coordinate lies outside the Korean coordinate envelope.")


def write_inventory(inventory: pd.DataFrame, directory: Path) -> dict[str, Path]:
    """Write shapefile, full-name Parquet, schema JSON, and ID lookup."""
    validate_inventory_schema(inventory)
    directory.mkdir(parents=True, exist_ok=True)
    shape_path = directory / "emissions.shp"
    writer = shapefile.Writer(str(shape_path), shapeType=shapefile.POINT)
    writer.autoBalance = 1
    for field in SHAPEFILE_FIELDS:
        writer.field(field, "F", size=20, decimal=8)
    writer.field("plant_id", "C", size=80)
    writer.field("unit_id", "C", size=100)
    for row in inventory.itertuples(index=False):
        data = row._asdict()
        writer.point(float(data["longitude"]), float(data["latitude"]))
        writer.record(
            *[float(data[source]) for source in SHAPEFILE_FIELDS.values()],
            str(data["plant_id"]),
            str(data["unit_id"]),
        )
    writer.close()
    shape_path.with_suffix(".prj").write_text(WGS84_PRJ, encoding="ascii")
    parquet_path = directory / "emissions_full_schema.parquet"
    inventory.to_parquet(parquet_path, index=False)
    lookup_path = directory / "plant_id_lookup.csv"
    inventory[["plant_id", "unit_id", "plant_name"]].drop_duplicates().to_csv(
        lookup_path, index=False
    )
    schema_path = directory / "schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "geometry": "Point",
                "crs": "EPSG:4326",
                "emission_units": "kg/year",
                "shapefile_fields": SHAPEFILE_FIELDS,
                "stack_units": {"height": "m", "diam": "m", "temp": "K", "velocity": "m/s"},
                "row_count": len(inventory),
                "omitted_pollutants": {
                    "PM2_5": inventory["pm25_treatment"].drop_duplicates().tolist(),
                    "NH3": inventory["nh3_treatment"].drop_duplicates().tolist(),
                    "VOC": inventory["voc_treatment"].drop_duplicates().tolist(),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "shapefile": shape_path,
        "parquet": parquet_path,
        "lookup": lookup_path,
        "schema": schema_path,
    }


def write_config(
    *,
    scenario: str,
    year: int,
    inventory_path: Path,
    inmap_data: Path,
    variable_grid_data: Path,
    population_file: Path,
    mortality_rate_file: Path,
    output_path: Path,
    config_path: Path,
    num_iterations: int = 0,
    supplemental_inputs: Sequence[Mapping[str, Any]] = (),
    emission_units: str = "kg/year",
) -> Path:
    """Write a Global InMAP v1.9.6 config for mixed point and grid emissions."""
    if num_iterations < 0:
        raise ValueError("InMAP num_iterations must be zero or positive.")
    shapefiles = [Path(inventory_path)]
    coards = []
    for item in supplemental_inputs:
        if item["format"] == "shapefile":
            if item["units"] != emission_units:
                raise ValueError("All InMAP shapefiles in one run must use the same units.")
            shapefiles.append(Path(item["path"]))
        elif item["format"] == "coards":
            coards.append(item)
        else:
            raise ValueError(f"Unsupported supplemental InMAP format: {item['format']}")

    shapefile_values = ",\n  ".join(_toml_string(path) for path in shapefiles)
    coards_content = ""
    if coards:
        coards_units = {str(item["units"]) for item in coards}
        coards_years = {int(item["coards_year"]) for item in coards}
        if len(coards_units) != 1 or len(coards_years) != 1:
            raise ValueError("COARDS inputs in one InMAP run must share units and year.")
        by_sector: defaultdict[str, list[Path]] = defaultdict(list)
        for item in coards:
            by_sector[str(item["sector"])].append(Path(item["path"]))
        sector_lines = []
        for sector, paths in sorted(by_sector.items()):
            values = ", ".join(_toml_string(path) for path in sorted(paths))
            sector_lines.append(f"{_toml_string(sector)} = [{values}]")
        coards_content = f"""
[aep]
SrgSpecSMOKE = ""
GridRef = []

[aep.InventoryConfig]
InputUnits = {_toml_string(next(iter(coards_units)))}
COARDSYear = {next(iter(coards_years))}

[aep.InventoryConfig.COARDSFiles]
{chr(10).join(sector_lines)}

[aep.SpatialConfig]
InputSR = "+proj=longlat"
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# Generated for {_safe_label(scenario)} {year}; Global InMAP only.
static = true
NumIterations = {num_iterations}
InMAPData = {_toml_string(inmap_data)}
VariableGridData = {_toml_string(variable_grid_data)}
EmissionsShapefiles = [
  {shapefile_values}
]
EmissionUnits = {_toml_string(emission_units)}
OutputFile = {_toml_string(output_path)}
LogFile = {_toml_string(output_path.with_suffix(".model.log"))}
{coards_content}

[OutputVariables]
PrimPM25 = "PrimaryPM25"
pSO4 = "pSO4"
pNO3 = "pNO3"
pNH4 = "pNH4"
SOA = "SOA"
TotalPM25 = "PrimaryPM25 + pSO4 + pNO3 + pNH4 + SOA"
TotalPop = "TotalPop"

[VarGrid]
# These domain parameters are pinned to the official Global InMAP v1.1.0
# sampleConfig.toml. They are required even when loading the prebuilt .gob grid.
VariableGridXo = -180.0
VariableGridYo = -90.0
VariableGridDx = 2.5
VariableGridDy = 2.0
Xnests = [140, 2, 2, 2, 2, 2, 2, 2]
Ynests = [84, 2, 2, 2, 2, 2, 2, 2]
HiResLayers = 8
GridProj = "+proj=longlat +units=degrees"
PopDensityThreshold = 55000000.0
PopThreshold = 100000.0
PopConcThreshold = 0.000000001
CensusFile = {_toml_string(population_file)}
CensusPopColumns = ["TotalPop"]
PopGridColumn = "TotalPop"
MortalityRateFile = {_toml_string(mortality_rate_file)}

# Deliberately empty: mortality is not a requested InMAP output. The official
# Global InMAP v1.1.0 evaluation archive does not distribute mortality data;
# health impacts are calculated downstream from KOSIS mortality inputs.
[VarGrid.MortalityRateColumns]
"""
    config_path.write_text(content, encoding="utf-8")
    return config_path


def generate_scenario_inputs(
    emissions: pd.DataFrame,
    run_dir: Path,
    installation: dict[str, Any],
    *,
    num_iterations: int = 0,
    supplemental_emissions: Sequence[Mapping[str, Any]] | None = None,
    emission_units: str = "kg/year",
) -> list[dict[str, Any]]:
    """Generate mixed point/grid input configurations per scenario-year."""
    generated: list[dict[str, Any]] = []
    for (scenario, year), group in emissions.groupby(["scenario", "year"], sort=True):
        scenario = str(scenario)
        year = int(year)
        label = f"{_safe_label(scenario)}_{year}"
        input_dir = run_dir / "inmap" / "inputs" / label
        files = write_inventory(group.reset_index(drop=True), input_dir)
        supplemental = select_supplemental_emissions(
            supplemental_emissions,
            scenario=scenario,
            year=year,
            shapefile_units=emission_units,
        )
        output_path = run_dir / "inmap" / "outputs" / label / "concentrations.shp"
        config_path = run_dir / "inmap" / "configs" / f"{label}.toml"
        write_config(
            scenario=scenario,
            year=year,
            inventory_path=files["shapefile"].resolve(),
            inmap_data=Path(installation["inmap_data"]),
            variable_grid_data=Path(installation["variable_grid_data"]),
            population_file=Path(installation["population_file"]),
            mortality_rate_file=Path(installation["mortality_rate_file"]),
            output_path=output_path.resolve(),
            config_path=config_path,
            num_iterations=num_iterations,
            supplemental_inputs=supplemental,
            emission_units=emission_units,
        )
        emission_paths = [
            files["shapefile"].resolve(),
            *(Path(item["path"]) for item in supplemental),
        ]
        dependencies = emission_dependency_files(emission_paths)
        manifest_path = input_dir / "emission_inputs.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "scenario": scenario,
                    "year": year,
                    "shapefile_units": emission_units,
                    "inputs": [
                        {
                            "id": "generated_power",
                            "sector": "power",
                            "format": "shapefile",
                            "path": str(files["shapefile"].resolve()),
                            "units": emission_units,
                            "geometry_types": ["Point"],
                            "elevated": True,
                        },
                        *[
                            {
                                key: str(value) if isinstance(value, Path) else value
                                for key, value in item.items()
                            }
                            for item in supplemental
                        ],
                    ],
                    "dependency_sha256": {str(path): _sha256(path) for path in dependencies},
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        generated.append(
            {
                "scenario": scenario,
                "year": year,
                "label": label,
                "config": config_path,
                "output": output_path,
                "num_iterations": num_iterations,
                "emission_files": emission_paths,
                "emission_inputs": json.loads(manifest_path.read_text(encoding="utf-8"))["inputs"],
                "input_manifest": manifest_path,
                **files,
            }
        )
    return generated
