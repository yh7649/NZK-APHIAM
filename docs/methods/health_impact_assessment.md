# Health-impact assessment (stage 5) and decomposition (stage 6)

This is the Korean equivalent of Huang & Peng (2025)'s BenMAP-CE
health-impact stage and sequential decomposition. BenMAP has no Korea
configuration, so `src/nzk_aphiam/health/` implements the same attributable
fraction and population-health arithmetic directly. This is a BenMAP-equivalent
calculation, not a claim that BenMAP itself was run.

The core module accepts PM2.5 concentration, population, and endpoint-matched
baseline mortality tables. The Peng MVP adapter at
`src/nzk_aphiam/mvp/peng_replication/health_adapter.py` converts national
population-weighted InMAP scenario outputs into those inputs, runs the complete
prespecified CRF suite, and records each specification as complete or blocked.
See [`peng_replication_mvp.md`](peng_replication_mvp.md).

For a slide-production brief that explains this module, see
[`claude_pptx_health_impact_module.md`](claude_pptx_health_impact_module.md).

## Concentration-response function

The primary remains the same Krewski et al. (2009) ACS Extended Follow-up
log-linear estimate used by Huang & Peng. Its HR is 1.06 (95% CI 1.04–1.08)
per 10 µg/m³ annual PM2.5 for all-cause mortality, giving
`beta = ln(HR)/10 = 0.0058269` per µg/m³. The ACS cohort enrolled people age
30+, so both population and mortality denominators begin at 30.

The complete suite is:

| Registry ID | Model and role | Mortality endpoint | Ages | Main parameter |
|---|---|---:|---:|---|
| `peng_krewski_2009_all_cause` | Huang–Peng primary, log-linear | all-cause | 30+ | HR 1.06 (1.04–1.08) per 10 µg/m³ |
| `gemm_2018_ncd_lri_with_china` | Huang–Peng nonlinear sensitivity | NCD+LRI | 25+ | Burnett SI Table S2 age-specific θ; `α=1.6`, `μ=15.5`, `ν=36.8` |
| `byun_2024_korea_non_accidental` | primary Korea-cohort sensitivity | non-accidental | 30+ | HR 1.10 (1.01–1.20) per 10 µg/m³ |
| `kim_2020_korea_all_cause` | lower Korea-cohort sensitivity | all-cause | 18+ | HR 1.034 (1.027–1.041) per 10 µg/m³ |
| `korea_guide_hoek_2013_policy` | Korean policy-HIA benchmark | all-cause | 30+ convention | β 0.006015 (0.00399032–0.00803968) |
| `lim_2020_korea_elderly_all_cause` | elderly Korea-cohort sensitivity | all-cause | 65+ | HR 1.024 (1.009–1.039) per 10 µg/m³ |

Kim's source cohort starts at age 18. Because the KOSIS input uses five-year
bands, the implementation starts with the complete 20–24 band rather than
including ages 15–17. The GUIDE row's age-30 minimum is an explicit
comparability convention, not a source-cohort enrollment rule. Byun and Lim
use multi-year moving-average exposure metrics, so applying their coefficients
to annual InMAP scenarios is a structural sensitivity, not an exact replication
of their lagged exposure construction.

All registry metadata and log-linear coefficients are in
`docs/references/health/crf_parameters.csv`. GEMM's twelve age-specific rows
are in `gemm_ncd_lri_parameters.csv`. Evidence is split between the original
`crf_parameters_official_evidence.csv` and the additive
`crf_specification_evidence.csv`.

### GEMM implementation

The Burnett et al. (2018) main NCD+LRI model including the Chinese male cohort
is implemented exactly as:

```text
z = max(0, PM2.5 - 2.4)
T(z) = log(1 + z/α) / (1 + exp(-(z-μ)/ν))
RR = exp(θ_age × T(z))
AF = 1 - 1/RR
```

The twelve θ values cover 25–29 through 75–79 and 80+. Its interval substitutes
`θ ± 1.96 × SE(θ)` and therefore represents GEMM parameter uncertainty only.
GEMM requires age-specific NCD+LRI baseline mortality. Generic
non-accidental or all-cause rates are not accepted as substitutes.

## Counterfactual concentration and InMAP interpretation

The Peng primary uses `counterfactual_ugm3 = 0`: Huang & Peng's equations use
the modeled scenario concentration as ΔPM and do not subtract the ACS sample
minimum. The registry retains 10.77 µg/m³ as the lowest concentration observed
in the Krewski cohort, so results below that support boundary are explicitly
extrapolations. The old 10.77-cutoff row remains under
`krewski_2009_acs_extended` for reproducibility but is not in the recommended
suite.

The Korea-derived log-linear sensitivities also use zero as an unthresholded
scenario-total convention, because their papers do not supply transferable
numeric no-effect thresholds. This choice must not be interpreted as evidence
of a biological zero-risk threshold.

The adapter supports two explicit exposure modes:

- `direct_scenario_concentration`: the InMAP column is already each scenario's
  total ambient PM2.5 concentration.
- `background_plus_inmap_contribution`: add a sourced scenario-specific or
  common ambient background to an InMAP source contribution.

The current thermal-only inventory yields a power-sector source contribution,
not total ambient PM2.5. It can test signs and plumbing, but a reportable Peng
run requires an all-source InMAP scenario or a defensible background. The
`exposure_scope` column and run manifest preserve this distinction. The default
configuration also sets `health.analytical_use_permitted: false`; changing that
flag is an explicit assertion that exposure scope, convergence, mortality
endpoints, and scenario design are fit for the intended analysis.

## Endpoint safety

Each CRF requests one exact endpoint: `all_cause`, `non_accidental`, or
`ncd_lri`. The canonical KOSIS table supplies age-specific all-cause mortality.
The default configuration leaves the other two paths null, so the Byun and
GEMM rows receive machine-readable blocked statuses while all compatible
specifications still run. Non-all-cause inputs must include a
`mortality_endpoint` column matching the requested endpoint. No cross-endpoint
fallback occurs.

## Attributable deaths

`impact.py` implements Equations 2-4:

- Attributable fraction: `AF = 1 - exp(-β · ΔPM)`
- Attributable deaths: `ΔY = AF · Y0 · Pop`, summed over district `c` and age
  band `a`

Two distinct functions, matching two distinct uses:

1. `compute_attributable_deaths` -- total attributable deaths in a single
   scenario-year (Equations 3-4).
2. `compute_marginal_attributable_deaths` -- the marginal difference between
   two scenarios, which is **the estimand this project actually cares
   about**. It is computed by differencing two calls to (1), never by
   substituting a concentration difference into the AF formula: AF is
   non-linear in PM2.5, so `total(pm25_b) - total(pm25_a) != apply(pm25_b -
   pm25_a)`. `tests/test_health_impact.py::test_marginal_deaths_is_not_af_of_concentration_difference`
   exists specifically so this is not "simplified" away later.

Output carries the central attributable-death estimate plus CRF-only bounds.
Log-linear specifications substitute the lower and upper β; GEMM substitutes
the age-specific `θ ± 1.96 × SE(θ)`. Neither interval includes uncertainty in
PM2.5, population, baseline mortality, background concentration, or model
structure.

Inputs are validated loudly: negative concentrations, mortality rates above 1
(the KOSIS-per-100,000 trap), and age bands below `valid_age_min` all raise
rather than get silently coerced.

## Decomposition

`decomposition.py` implements Equations 3-7 and the "Decomposition analysis"
Methods subsection: population growth → aging → baseline mortality rate →
exposure, with exposure split into a BAU-pollution-control component and a
climate-policy component.

**Reading note on Equation 5.** As transcribed in the paper, Equation 5

```
A = 2015 Mortality × (2030 Pop_{c,a} / 2015 Pop_{c,a})
```

subscripts the population ratio by district `c` and age band `a`. Read
literally, that ratio already carries the full end-year age structure into
`A`, which would force the paper's own next term, "population aging effect =
(B - A)", to be identically zero -- not a meaningful decomposition. This
module instead reads Equation 5 as scaling base-year mortality by the
**aggregate** population ratio (summed over all `c, a`), holding age
composition, `Y0`, and exposure fixed at base-year values:

```
A = mortality_base_year × (Σ Pop_end / Σ Pop_base)
B = Σ_{c,a} Y0_base_{c,a} × Pop_end_{c,a} × AF(PM_base_{c,a})
C = Σ_{c,a} Y0_end_{c,a}  × Pop_end_{c,a} × AF(PM_base_{c,a})
```

`B` then introduces the true end-year age-specific population, so `B - A`
isolates the aging effect; `C` introduces the end-year baseline mortality
rate, so `C - B` isolates that effect; the BAU and climate-policy exposure
effects follow by introducing each scenario's end-year PM2.5 last. **This is
an interpretive judgment about an ambiguous equation, not a verbatim
transcription** -- flagged here and in `crf_parameters_official_evidence.csv`
(`huang_peng_2025_eq5_7_decomposition`).

By construction the five effects telescope exactly:

```
population_growth_effect + population_aging_effect + baseline_mortality_rate_effect
    + exposure_bau_effect + exposure_climate_policy_effect
  = mortality_end_year_policy - mortality_base_year
```

`tests/test_health_decomposition.py::test_telescoping_invariant_holds_exactly`
checks this to floating-point tolerance; it is the structural test that fails
loudly if any stage is misassembled.

**Order-dependence.** Sequential decomposition is order-dependent: because
each factor is introduced holding the others fixed, a different sequence
(e.g. exposure before aging) would split the same total change differently.
The order fixed here (population growth → aging → baseline mortality rate →
exposure) matches the reference study and should not be changed without
re-deriving what each effect means.

**Age restriction interacts with the decomposition.** Because the CRF is
age-restricted at `valid_age_min` (30 for Krewski), the population growth
factor here is growth of the **restricted (30+) population**, and the aging
factor is the composition shift **within** that restricted population --
not an all-ages reading of Equations 5-7. Given Korea's demographic profile
(a much older and faster-aging population than the US case Huang & Peng
study), this is a meaningful departure from an all-ages decomposition, not a
technicality.

## Outputs and remaining scope

The Peng MVP writes:

- `national_scenario_exposures.csv`: population-weighted InMAP concentration
  and concentration scope by scenario;
- `health_model_inputs.csv`: age-specific denominator and concentration rows
  for every runnable CRF;
- `health_scenario_totals.csv`: attributable mortality by CRF and scenario;
- `health_impacts.csv`: reference-minus-policy avoided mortality and CRF-only
  interval by specification; and
- `health_specification_status.csv`: complete or blocked status and reason for
  every requested CRF.

The core health module still leaves InMAP execution, meteorology, emissions,
and boundary harmonization upstream. District exposure and district
decomposition remain unavailable until compatible district boundaries and
population allocation are connected. Infant mortality and morbidity endpoints
are not implemented.
