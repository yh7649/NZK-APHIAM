"""Out-of-fold expected-value models and robust residual anomaly flags."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder


@dataclass(frozen=True)
class ModelConfig:
    n_estimators: int = 200
    min_samples_leaf: int = 5
    max_features: float = 0.7
    random_state: int = 2026
    n_jobs: int = -1
    n_folds: int = 5
    mad_threshold: float = 6.0
    minimum_training_rows: int = 200
    max_training_rows: int | None = None


def _estimator(numeric: list[str], categorical: list[str], config: ModelConfig) -> Pipeline:
    preprocessor = ColumnTransformer(
        [
            ("numeric", SimpleImputer(strategy="median", keep_empty_features=True), numeric),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        (
                            "encode",
                            OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                        ),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )
    model = RandomForestRegressor(
        n_estimators=config.n_estimators,
        min_samples_leaf=config.min_samples_leaf,
        max_features=config.max_features,
        random_state=config.random_state,
        n_jobs=config.n_jobs,
    )
    return Pipeline([("features", preprocessor), ("model", model)])


def _time_blocks(datetimes: pd.Series, n_folds: int) -> list[np.ndarray]:
    ordered = np.array(sorted(pd.Series(datetimes.dropna().unique()).tolist()))
    return [block for block in np.array_split(ordered, n_folds) if len(block)]


def add_oof_predictions(
    data: pd.DataFrame,
    numeric_features: list[str],
    categorical_features: list[str],
    config: ModelConfig | None = None,
) -> pd.DataFrame:
    """Fit separate pollutant models, predicting each timestamp out of fold.

    Folds are blocks of timestamps (not random rows), preventing observations
    from the same hour from leaking between training and validation.
    """
    config = config or ModelConfig()
    result = data.copy()
    result["value_expected"] = np.nan
    result["model_residual"] = np.nan
    result["residual_robust_z"] = np.nan
    result["flag_ml"] = False

    invalid = result.get("flag_missing", False) | result.get("flag_impossible", False)
    for pollutant, frame in result.groupby("pollutant", sort=False, observed=True):
        eligible = frame.index[~invalid.loc[frame.index] & frame["value_raw"].notna()]
        if len(eligible) < config.minimum_training_rows:
            continue
        for fold, validation_times in enumerate(
            _time_blocks(result.loc[eligible, "datetime"], config.n_folds)
        ):
            validation = eligible[result.loc[eligible, "datetime"].isin(validation_times)]
            training = eligible.difference(validation, sort=False)
            if len(training) < config.minimum_training_rows or validation.empty:
                continue
            if config.max_training_rows and len(training) > config.max_training_rows:
                training = (
                    pd.Series(training, index=training)
                    .sample(
                        n=config.max_training_rows,
                        random_state=config.random_state + fold,
                    )
                    .index
                )
            estimator = _estimator(numeric_features, categorical_features, config)
            estimator.fit(result.loc[training], result.loc[training, "value_raw"])
            result.loc[validation, "value_expected"] = estimator.predict(result.loc[validation])

        indices = frame.index
        residual = result.loc[indices, "value_raw"] - result.loc[indices, "value_expected"]
        residual = pd.Series(
            residual.to_numpy(dtype=float, na_value=np.nan),
            index=residual.index,
            dtype=float,
        )
        result.loc[indices, "model_residual"] = residual.to_numpy()
        center = residual.median()
        mad = (residual - center).abs().median()
        scale = 1.4826 * mad
        if pd.notna(scale) and scale > 0:
            robust_z = (residual - center) / scale
            result.loc[indices, "residual_robust_z"] = robust_z.to_numpy()
            result.loc[indices, "flag_ml"] = (
                robust_z.abs().gt(config.mad_threshold).fillna(False).to_numpy()
            )
    return result
