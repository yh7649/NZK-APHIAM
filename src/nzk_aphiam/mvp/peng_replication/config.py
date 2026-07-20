"""Configuration loading for the Peng replication MVP."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from nzk_aphiam.config.paths import PROJECT_ROOT

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "scenarios" / "peng_replication_mvp.yaml"


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
