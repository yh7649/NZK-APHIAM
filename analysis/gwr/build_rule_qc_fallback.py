"""Build a memory-bounded rule-QC monthly sensitivity input.

This is not the canonical ML/spatial QC product. It only removes observations
flagged missing or impossible by the repository's configured deterministic rules.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nzk_aphiam.air_quality.pipeline import (
    AirQualityQCPipeline,
    monthly_aggregates,
    read_airkorea_zip,
)
from nzk_aphiam.air_quality.qc_rules import apply_rule_flags


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/airkorea/hourly_finalized"))
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/processed/air_quality/air_quality_monthly_rule_qc.parquet"),
    )
    args = parser.parse_args()
    archive = args.input_dir / f"airkorea_hourly_finalized_{args.year}.zip"
    if not archive.exists():
        parser.error(f"Missing archive: {archive}")
    config = AirQualityQCPipeline.from_yaml()
    monthly_parts: list[pd.DataFrame] = []
    for pollutant in ("NO2", "SO2", "PM10", "PM25"):
        checkpoint = args.output.with_name(f"{args.output.stem}_{pollutant.lower()}.parquet")
        if checkpoint.exists():
            monthly_parts.append(pd.read_parquet(checkpoint))
            print(f"Reusing {checkpoint}")
            continue
        try:
            hourly = read_airkorea_zip(archive, {pollutant})
        except ValueError as error:
            if "No XLSX workbooks found" in str(error):
                print(f"Skipping {pollutant}: unavailable in {archive.name}")
                continue
            raise
        checked = apply_rule_flags(hourly, config.rule_config)
        checked["value_analysis"] = checked["value_raw"].mask(
            checked["flag_missing"] | checked["flag_impossible"]
        )
        _, monthly = monthly_aggregates(checked)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        monthly.to_parquet(checkpoint, index=False)
        monthly_parts.append(monthly)
    result = pd.concat(monthly_parts, ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(args.output, index=False)
    print(f"Wrote {len(result):,} rule-QC monitor-months to {args.output}")


if __name__ == "__main__":
    main()
