"""Build donor decisions and an ASCM-ready weekly panel."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .config import load_event_config
from .exposure import add_exposure_features
from .panel import build_weekly_panel, select_donors


def read_table(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--hourly", type=Path, required=True, help="Weather-normalized hourly CSV/Parquet"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/processed/synthetic_control")
    )
    args = parser.parse_args()
    config = load_event_config(args.config)
    hourly = read_table(args.hourly)
    if not {"plant_monitor_distance_km", "target_exposure"}.issubset(hourly.columns):
        hourly = add_exposure_features(hourly, config.plant_latitude, config.plant_longitude)
    decisions = select_donors(hourly, config)
    panel = build_weekly_panel(hourly, decisions, config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(args.output_dir / f"{config.event_id}_donors.csv", index=False)
    panel.to_csv(args.output_dir / f"{config.event_id}_weekly.csv", index=False)


if __name__ == "__main__":
    main()
