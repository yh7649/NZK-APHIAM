"""Configuration loading for the Peng replication MVP."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from nzk_aphiam.config.paths import PROJECT_ROOT

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "scenarios" / "peng_replication_mvp.yaml"
HEALTH_CONCENTRATION_MODES = {
    "direct_scenario_concentration",
    "background_plus_inmap_contribution",
}


def _validate_health_config(config: dict[str, Any]) -> None:
    health = config.get("health")
    if not isinstance(health, dict):
        raise ValueError("health must be a mapping.")
    crf_ids = health.get("crf_ids")
    if (
        not isinstance(crf_ids, list)
        or not crf_ids
        or not all(isinstance(crf_id, str) and crf_id for crf_id in crf_ids)
    ):
        raise ValueError("health.crf_ids must be a non-empty list of CRF identifiers.")
    if len(crf_ids) != len(set(crf_ids)):
        raise ValueError("health.crf_ids must not contain duplicates.")

    mortality_inputs = health.get("mortality_inputs")
    if not isinstance(mortality_inputs, dict) or not mortality_inputs:
        raise ValueError("health.mortality_inputs must be a non-empty endpoint-to-input mapping.")
    unknown_input_keys = sorted(
        input_key
        for input_key in mortality_inputs.values()
        if input_key is not None and input_key not in config.get("inputs", {})
    )
    if unknown_input_keys:
        raise ValueError(
            f"health.mortality_inputs references undefined inputs: {unknown_input_keys}."
        )

    mode = health.get("concentration_mode")
    if mode not in HEALTH_CONCENTRATION_MODES:
        raise ValueError(
            "health.concentration_mode must be one of "
            f"{sorted(HEALTH_CONCENTRATION_MODES)}; got {mode!r}."
        )
    if mode == "background_plus_inmap_contribution" and health.get("background_pm25_ugm3") is None:
        raise ValueError(
            "health.background_pm25_ugm3 is required when concentration_mode is "
            "'background_plus_inmap_contribution'."
        )
    for key in ("concentration_column", "exposure_scope"):
        if not isinstance(health.get(key), str) or not health[key].strip():
            raise ValueError(f"health.{key} must be a non-empty string.")
    if not isinstance(health.get("analytical_use_permitted"), bool):
        raise ValueError("health.analytical_use_permitted must be true or false.")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load the YAML configuration and resolve repository-relative paths."""
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")
    config = deepcopy(config)
    config["config_path"] = path.resolve()
    config["project_root"] = PROJECT_ROOT
    for section in ("inputs",):
        for key, value in config.get(section, {}).items():
            if isinstance(value, str):
                candidate = Path(str(value))
                config[section][key] = (
                    candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
                )
    cache = Path(config["inmap"]["cache_path"])
    config["inmap"]["cache_path"] = cache if cache.is_absolute() else PROJECT_ROOT / cache
    supplemental = config["inmap"].get("supplemental_emissions", [])
    if not isinstance(supplemental, list):
        raise ValueError("inmap.supplemental_emissions must be a list.")
    for item in supplemental:
        if not isinstance(item, dict):
            raise ValueError("Each inmap.supplemental_emissions entry must be a mapping.")
        if isinstance(item.get("path"), str):
            candidate = Path(item["path"])
            item["path"] = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
    _validate_health_config(config)
    return config


def serializable_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON/YAML-safe copy with paths relative to the project when possible."""

    def convert(value: Any) -> Any:
        if isinstance(value, Path):
            try:
                return str(value.relative_to(PROJECT_ROOT))
            except ValueError:
                return str(value)
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return convert(config)
