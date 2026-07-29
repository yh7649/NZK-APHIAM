from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from nzk_aphiam.health import crf as crf_module
from nzk_aphiam.health.crf import GEMMNCDLRICRF, LogLinearCRF, load_crf
from nzk_aphiam.mvp.peng_replication.health_adapter import RECOMMENDED_CRF_IDS


def test_default_crf_matches_peng_replication_specification() -> None:
    """Peng uses the Krewski coefficient on the scenario concentration itself."""
    crf = load_crf()
    assert crf.crf_id == "peng_krewski_2009_all_cause"
    assert crf.valid_age_min == 30
    assert crf.counterfactual_ugm3 == pytest.approx(0.0)
    assert crf.lowest_measured_ugm3 == pytest.approx(10.77)
    assert crf.beta == pytest.approx(math.log(1.06) / 10, rel=1e-6)
    assert crf.ci_low == pytest.approx(math.log(1.04) / 10, rel=1e-6)
    assert crf.ci_high == pytest.approx(math.log(1.08) / 10, rel=1e-6)


def test_legacy_krewski_cutoff_remains_reproducible() -> None:
    crf = load_crf("krewski_2009_acs_extended")
    assert crf.counterfactual_ugm3 == pytest.approx(10.77)
    assert crf.specification_role == "legacy_not_in_recommended_suite"


def test_every_recommended_specification_loads() -> None:
    loaded = [load_crf(crf_id) for crf_id in RECOMMENDED_CRF_IDS]
    assert [crf.crf_id for crf in loaded] == list(RECOMMENDED_CRF_IDS)
    assert {crf.endpoint for crf in loaded} == {
        "all_cause",
        "non_accidental",
        "ncd_lri",
    }


def test_active_registry_is_exactly_the_recommended_suite_and_evidence_resolves() -> None:
    registry_path = crf_module.DEFAULT_CRF_PARAMETERS_PATH
    registry = pd.read_csv(registry_path)
    assert set(registry.loc[registry["status"].eq("active"), "crf_id"]) == set(
        RECOMMENDED_CRF_IDS
    )

    evidence = pd.concat(
        [
            pd.read_csv(registry_path.parent / "crf_parameters_official_evidence.csv"),
            pd.read_csv(registry_path.parent / "crf_specification_evidence.csv"),
        ],
        ignore_index=True,
    )
    evidence_ids = set(evidence["evidence_id"])
    for column in registry.columns[registry.columns.str.startswith("evidence_id_")]:
        referenced = set(registry[column].dropna())
        assert referenced <= evidence_ids


def test_gemm_matches_burnett_equation_for_age_band() -> None:
    crf = load_crf("gemm_2018_ncd_lri_with_china")
    assert isinstance(crf, GEMMNCDLRICRF)
    concentration = 20.0
    z = concentration - 2.4
    transform = math.log1p(z / 1.6) / (1 + math.exp(-(z - 15.5) / 36.8))
    expected = 1 - math.exp(-0.1577 * transform)
    assert crf.apply(concentration, age_band="30-34") == pytest.approx(expected)


def test_gemm_uncertainty_bounds_and_counterfactual() -> None:
    crf = load_crf("gemm_2018_ncd_lri_with_china")
    lower = crf.apply(20.0, age_band="65-69", estimate="lower")
    central = crf.apply(20.0, age_band="65-69")
    upper = crf.apply(20.0, age_band="65-69", estimate="upper")
    assert lower < central < upper
    assert crf.apply(2.0, age_band="65-69") == pytest.approx(0.0)


def test_gemm_rejects_age_bands_that_do_not_match_parameter_table() -> None:
    crf = load_crf("gemm_2018_ncd_lri_with_china")
    with pytest.raises(ValueError, match="five-year age bands"):
        crf.apply(20.0, age_band="30+")


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
