from __future__ import annotations

import numpy as np
import pandas as pd

from nzk_aphiam.air_quality.anomaly_model import ModelConfig
from nzk_aphiam.air_quality.pipeline import (
    AirQualityQCPipeline,
    monthly_aggregates,
    standardize_airkorea_frame,
)
from nzk_aphiam.air_quality.qc_rules import RuleConfig, apply_rule_flags


def test_standardize_airkorea_frame_preserves_raw_values() -> None:
    wide = pd.DataFrame(
        {
            "측정소코드": [111],
            "측정소명": ["종로"],
            "측정일시": [2024010101],
            "SO2": [0.01],
            "PM2.5": [-999],
        }
    )
    long = standardize_airkorea_frame(wide)
    assert set(long["pollutant"]) == {"SO2", "PM25"}
    assert long.set_index("pollutant").at["PM25", "value_raw"] == -999
    assert long["datetime"].notna().all()


def test_rules_flag_sentinel_impossible_flatline_and_jump() -> None:
    times = pd.date_range("2024-01-01", periods=30, freq="h")
    values = [10.0] * 12 + [20.0] * 16 + [2001.0, -999.0]
    data = pd.DataFrame(
        {"monitor_id": "A", "datetime": times, "pollutant": "PM10", "value_raw": values}
    )
    result = apply_rule_flags(data, RuleConfig(flatline_hours=12, jump_multiplier=2.0))
    assert result["flag_flatline"].iloc[:12].all()
    assert result.loc[28, "flag_impossible"]
    assert result.loc[29, "flag_missing"]
    assert result.loc[29, "value_raw"] == -999


def test_pipeline_produces_auditable_output_and_monthly_pairs() -> None:
    rng = np.random.default_rng(4)
    times = pd.date_range("2024-01-01", periods=120, freq="h")
    rows = []
    for station, latitude, longitude in [("A", 37.50, 127.00), ("B", 37.51, 127.01)]:
        for i, timestamp in enumerate(times):
            rows.append(
                {
                    "monitor_id": station,
                    "datetime": timestamp,
                    "pollutant": "PM10",
                    "value_raw": 30 + 8 * np.sin(i / 24) + rng.normal(),
                    "latitude": latitude,
                    "longitude": longitude,
                }
            )
    data = pd.DataFrame(rows)
    pipeline = AirQualityQCPipeline(
        model_config=ModelConfig(n_estimators=10, n_folds=3, minimum_training_rows=100, n_jobs=1)
    )
    result = pipeline.run(data)
    assert {
        "value_raw",
        "value_expected",
        "model_residual",
        "flag_ml",
        "qc_status",
        "value_analysis",
    }.issubset(result)
    assert len(result) == len(data)
    raw, qc = monthly_aggregates(result)
    assert len(raw) == len(qc) == 2
