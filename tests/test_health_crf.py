from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.health import crf as crf_module
from nzk_aphiam.health.crf import LogLinearCRF, load_crf


def test_default_crf_parameters_file_matches_krewski_2009_table3() -> None:
    """Guards the sourced Krewski et al. 2009 Table 3 values against accidental drift."""
    crf = load_crf()
    assert crf.crf_id == "krewski_2009_acs_extended"
    assert crf.valid_age_min == 30
    assert crf.counterfactual_ugm3 == pytest.approx(10.77)
    assert crf.lowest_measured_ugm3 == pytest.approx(10.77)
    assert crf.beta == pytest.approx(math.log(1.06) / 10, rel=1e-6)
    assert crf.ci_low == pytest.approx(math.log(1.04) / 10, rel=1e-6)
    assert crf.ci_high == pytest.approx(math.log(1.08) / 10, rel=1e-6)


def test_apply_matches_manual_attributable_fraction_above_counterfactual() -> None:
    crf = LogLinearCRF(
        crf_id="test_crf",
        label="test",
        beta=0.01,
        ci_low=0.005,
        ci_high=0.02,
        valid_age_min=30,
        counterfactual_ugm3=10.0,
        lowest_measured_ugm3=10.0,
    )
    pm25 = 25.0
    expected_af = 1 - math.exp(-0.01 * (25.0 - 10.0))
    assert crf.apply(pm25) == pytest.approx(expected_af)


def test_apply_truncates_at_zero_below_counterfactual() -> None:
    crf = LogLinearCRF(
        crf_id="test_crf",
        label="test",
        beta=0.01,
        ci_low=0.005,
        ci_high=0.02,
        valid_age_min=30,
        counterfactual_ugm3=10.0,
        lowest_measured_ugm3=10.0,
    )
    assert crf.apply(5.0) == pytest.approx(0.0)
    assert crf.delta_pm(5.0) == pytest.approx(0.0)
    assert crf.is_truncated(5.0)
    assert not crf.is_truncated(15.0)


def test_apply_accepts_explicit_beta_override_for_ci_propagation() -> None:
    crf = LogLinearCRF(
        crf_id="test_crf",
        label="test",
        beta=0.01,
        ci_low=0.005,
        ci_high=0.02,
        valid_age_min=30,
        counterfactual_ugm3=10.0,
        lowest_measured_ugm3=10.0,
    )
    af_central = crf.apply(30.0)
    af_ci_low = crf.apply(30.0, beta=crf.ci_low)
    af_ci_high = crf.apply(30.0, beta=crf.ci_high)
    assert af_ci_low < af_central < af_ci_high


def _write_crf_csv(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _base_row(**overrides: object) -> dict[str, object]:
    row = {
        "crf_id": "synthetic_crf",
        "label": "synthetic",
        "beta_per_ugm3": 0.01,
        "beta_ci_low_per_ugm3": 0.005,
        "beta_ci_high_per_ugm3": 0.02,
        "valid_age_min": 30,
        "lowest_measured_ugm3": 5.0,
        "counterfactual_ugm3": 5.0,
    }
    row.update(overrides)
    return row


def test_load_crf_raises_for_unknown_crf_id(tmp_path: Path) -> None:
    path = tmp_path / "crf_parameters.csv"
    _write_crf_csv(path, [_base_row()])
    with pytest.raises(KeyError):
        load_crf("does_not_exist", path)


def test_load_crf_raises_for_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "crf_parameters.csv"
    frame = pd.DataFrame([_base_row()]).drop(columns=["counterfactual_ugm3"])
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        load_crf("synthetic_crf", path)


def test_load_crf_raises_for_duplicate_crf_id(tmp_path: Path) -> None:
    path = tmp_path / "crf_parameters.csv"
    _write_crf_csv(path, [_base_row(), _base_row()])
    with pytest.raises(ValueError):
        load_crf("synthetic_crf", path)


def test_load_crf_reads_synthetic_row(tmp_path: Path) -> None:
    path = tmp_path / "crf_parameters.csv"
    _write_crf_csv(path, [_base_row(crf_id="synthetic_crf")])
    crf = load_crf("synthetic_crf", path)
    assert crf.beta == pytest.approx(0.01)
    assert crf.valid_age_min == 30
    assert crf.counterfactual_ugm3 == pytest.approx(5.0)


def test_concentration_response_function_protocol_isinstance_check() -> None:
    crf = LogLinearCRF(
        crf_id="test_crf",
        label="test",
        beta=0.01,
        ci_low=0.005,
        ci_high=0.02,
        valid_age_min=30,
        counterfactual_ugm3=10.0,
        lowest_measured_ugm3=10.0,
    )
    assert isinstance(crf, crf_module.ConcentrationResponseFunction)
