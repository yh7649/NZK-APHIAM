"""Pinned Global InMAP executable and model-data installation."""

from __future__ import annotations

from hashlib import md5, sha256
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
from typing import Any
from urllib.request import Request, urlopen
from zipfile import ZipFile

import shapefile

WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


def file_checksum(path: Path, algorithm: str = "sha256") -> str:
    digest = sha256() if algorithm == "sha256" else md5()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    request = Request(url, headers={"User-Agent": "NZK-APHIAM/0.2 Global-InMAP installer"})
    if existing:
        request.add_header("Range", f"bytes={existing}-")
    mode = "ab" if existing else "wb"
    with urlopen(request, timeout=120) as response, partial.open(mode) as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    partial.replace(destination)


def _platform_asset(version: str) -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    system_name = {"darwin": "darwin", "linux": "linux", "windows": "windows"}.get(system)
    if system_name is None:
        raise RuntimeError(f"Unsupported InMAP platform: {platform.system()} {platform.machine()}")
    arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
    if system_name != "darwin" and arch == "arm64":
        raise RuntimeError("The pinned release has no official Linux/Windows ARM64 binary.")
    suffix = ".exe" if system_name == "windows" else ""
    return f"inmap-{version}-{system_name}-{arch}{suffix}"


def detect_executable(cache_path: Path, version: str) -> Path | None:
    """Find an explicit, cached, or PATH InMAP executable."""
    explicit = os.environ.get("INMAP_EXECUTABLE")
    candidates = [
        Path(explicit) if explicit else None,
        cache_path / "bin" / _platform_asset(version),
        Path(found) if (found := shutil.which("inmap")) else None,
    ]
    for candidate in candidates:
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def executable_version(executable: Path) -> str:
    result = subprocess.run(
        [str(executable), "version"], capture_output=True, text=True, check=False
    )
    return (result.stdout or result.stderr).strip()


def install_executable(cache_path: Path, version: str, *, force: bool = False) -> Path:
    asset = _platform_asset(version)
    destination = cache_path / "bin" / asset
    if force or not destination.exists():
        url = f"https://github.com/spatialmodel/inmap/releases/download/{version}/{asset}"
        _download(url, destination)
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return destination.resolve()


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            target = (destination / member.filename).resolve()
            if destination_root not in target.parents and target != destination_root:
                raise ValueError(f"Unsafe archive path: {member.filename}")
        zip_file.extractall(destination)


def resolve_model_files(data_root: Path) -> dict[str, Path]:
    regular = sorted(
        path for path in data_root.rglob("InMAPData_v1*.ncf") if "__MACOSX" not in path.parts
    )
    variable = sorted(data_root.rglob("global_inmap_004x003_v1*.gob"))
    population = sorted(
        path for path in data_root.rglob("Pop.ncf") if "__MACOSX" not in path.parts
    )
    if len(regular) != 1 or len(variable) != 1 or len(population) != 1:
        raise FileNotFoundError(
            "Expected one GlobalInMAPData, one global variable-grid file, and one "
            f"population NetCDF under {data_root}; found regular={regular}, "
            f"variable={variable}, population={population}."
        )
    return {
        "inmap_data": regular[0].resolve(),
        "variable_grid_data": variable[0].resolve(),
        "population_file": population[0].resolve(),
    }


def ensure_unused_mortality_file(cache_path: Path) -> Path:
    """Create the polygon InMAP requires when no mortality output is requested.

    The Global InMAP v1.1.0 evaluation archive explicitly excludes mortality data.
    Health impacts are calculated downstream from KOSIS inputs, so the configuration
    supplies an empty mortality-column map and this zero-valued global polygon is only
    a loader compatibility input. Its values cannot enter any requested model output.
    """
    shape_path = cache_path / "support" / "unused_mortality_loader_input.shp"
    required = [shape_path, shape_path.with_suffix(".shx"), shape_path.with_suffix(".dbf")]
    if all(path.exists() for path in required):
        return shape_path.resolve()
    shape_path.parent.mkdir(parents=True, exist_ok=True)
    writer = shapefile.Writer(str(shape_path), shapeType=shapefile.POLYGON)
    writer.field("unused", "F", size=10, decimal=1)
    writer.poly(
        [
            [
                [-180.0, -89.999],
                [-180.0, 89.999],
                [180.0, 89.999],
                [180.0, -89.999],
                [-180.0, -89.999],
            ]
        ]
    )
    writer.record(0.0)
    writer.close()
    shape_path.with_suffix(".prj").write_text(WGS84_PRJ, encoding="ascii")
    return shape_path.resolve()


def install_model_data(
    cache_path: Path,
    *,
    filename: str,
    expected_md5: str,
    version: str,
    force: bool = False,
    skip_download: bool = False,
) -> dict[str, Path]:
    archive = cache_path / "downloads" / filename
    data_root = cache_path / "data" / version
    if not archive.exists():
        if skip_download:
            raise FileNotFoundError(
                f"Global InMAP archive is absent at {archive}; rerun without --skip-inmap-download."
            )
        url = f"https://zenodo.org/api/records/6189451/files/{filename}/content"
        _download(url, archive)
    actual_md5 = file_checksum(archive, "md5")
    if actual_md5 != expected_md5:
        raise ValueError(
            f"Global InMAP data checksum mismatch: expected {expected_md5}, got {actual_md5}."
        )
    if force or not data_root.exists():
        _safe_extract(archive, data_root)
    nested_archives = sorted(data_root.rglob("global_inmap_004x003_v1.1.0.zip"))
    if nested_archives and not list(data_root.rglob("global_inmap_004x003_v1*.gob")):
        _safe_extract(nested_archives[0], nested_archives[0].parent)
    return resolve_model_files(data_root)


def install_global_inmap(
    config: dict[str, Any], *, force: bool = False, skip_download: bool = False
) -> dict[str, Any]:
    """Install and record the official pinned executable and Global dataset."""
    inmap = config["inmap"]
    cache_path = Path(inmap["cache_path"])
    executable = detect_executable(cache_path, inmap["version"])
    if executable is None:
        if skip_download:
            raise FileNotFoundError("No InMAP executable found and download was disabled.")
        executable = install_executable(cache_path, inmap["version"], force=force)
    model = install_model_data(
        cache_path,
        filename=inmap["model_data_filename"],
        expected_md5=inmap["model_data_md5"],
        version=inmap["model_data_version"],
        force=force,
        skip_download=skip_download,
    )
    mortality_file = ensure_unused_mortality_file(cache_path)
    version_output = executable_version(executable)
    expected_version_output = inmap["expected_executable_version_output"]
    if version_output != expected_version_output:
        raise ValueError(
            f"Unexpected InMAP executable version output: expected "
            f"{expected_version_output!r}, got {version_output!r}."
        )
    manifest = {
        "executable": str(executable),
        "executable_asset": executable.name,
        "requested_version": inmap["version"],
        "executable_version_output": version_output,
        "expected_executable_version_output": expected_version_output,
        "source_commit": inmap["source_commit"],
        "version_output_note": (
            "The official v1.9.6 source tag retains the internal Version constant 1.9.0; "
            "release tag, asset name, source commit, and executable SHA-256 identify the binary."
        ),
        "executable_sha256": file_checksum(executable),
        "source_release": inmap["release_url"],
        "model_data_version": inmap["model_data_version"],
        "model_data_record": inmap["model_data_record"],
        "model_data_archive_md5": inmap["model_data_md5"],
        "mortality_rate_file": str(mortality_file),
        "mortality_rate_file_role": (
            "zero-valued loader compatibility polygon; mortality outputs disabled and "
            "health impacts calculated downstream from KOSIS data"
        ),
        **{key: str(value) for key, value in model.items()},
    }
    manifest_path = cache_path / "installation_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
