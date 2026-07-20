# Health-impact assessment (stage 5) and decomposition (stage 6)

This implements the Korean-equivalent of Huang & Peng (2025)'s BenMAP-CE
health-impact stage and their sequential decomposition, as `src/nzk_aphiam/health/`.
BenMAP has no Korea configuration, so the concentration-response function (CRF)
and attributable-deaths calculation are implemented by hand in `crf.py` and
`impact.py`; the decomposition is implemented in `decomposition.py`.

This module is deliberately self-contained: it takes PM2.5 concentrations,
population, and baseline mortality rates as arguments. It does not itself run,
call, or depend on InMAP. The thermal-power MVP now supplies a separate adapter
at `mvp/peng_replication/health_adapter.py`; see
[`peng_replication_mvp.md`](peng_replication_mvp.md). District exposure and
boundary harmonization remain unavailable.

## Concentration-response function

The primary CRF is Krewski et al. 2009 (HEI Research Report 140), the ACS
Extended Follow-up study, log-linear form -- the same estimate Huang & Peng
(2025) use as their main result (their Equation 2, citing this paper).

- **Hazard ratio**: 1.06 (95% CI 1.04-1.08) per 10 µg/m³ PM2.5, all-cause
  mortality, standard Cox model, PM2.5 (1979-1983 exposure metric), Table 3
  of the Investigators' Report (PDF page 29). This matches the task brief's
  expectation (HR near 1.06 per 10 µg/m³) with no material discrepancy.
- **β = ln(HR)/10 = 0.0058269 µg/m³⁻¹** (ci_low 0.0039221, ci_high 0.0076961).
- **Age restriction**: the ACS CPS-II cohort enrolled only persons "at least
  30 years of age" (Materials and Methods, Study Population, PDF page 20).
  `valid_age_min = 30`. `Pop` and `Y0` must both be restricted to age bands
  at or above 30; `impact.py` and `decomposition.py` raise rather than
  silently drop or include younger bands. KOSIS age bands align cleanly at
  30, so no band splitting is needed.
- All parameters are read from `docs/references/health/crf_parameters.csv`,
  not hardcoded; every numeric value there traces to a row in
  `crf_parameters_official_evidence.csv` with a source and page/table number.

### Sensitivity CRF: GEMM is deferred, not implemented

Huang & Peng (2025) also report a GEMM (Burnett et al. 2018) sensitivity run
(~200% higher attributable deaths than the Krewski log-linear function, "but
the relative differences across scenarios... remain similar"). GEMM is
**out of scope for this task** -- it is not implemented, and no stub or
placeholder row exists for it in `crf_parameters.csv`.

`crf.py` defines `ConcentrationResponseFunction` as a `Protocol` capturing
the interface any CRF must satisfy (`beta`, `ci_low`, `ci_high`,
`valid_age_min`, `counterfactual_ugm3`, `delta_pm`, `is_truncated`, `apply`).
`impact.py` and `decomposition.py` type-hint against this protocol, not the
concrete `LogLinearCRF` class, so a future `GEMM` implementation (its own
functional form, `T(z) = log(1+z/α)ω(z)`, fitted θ/α/μ/ν parameters from the
PNAS SI appendix -- not yet held in this repo) can be added as a new class in
`crf.py` without changing `impact.py` or `decomposition.py` at all.

## Counterfactual concentration

`counterfactual_ugm3` is a required parameter of every CRF with **no
default** -- `AF = 1 - exp(-β · max(0, pm25_ugm3 - counterfactual_ugm3))`.
Four candidate sources were evaluated (see
`crf_parameters_official_evidence.csv` for full evidence rows):

| Candidate | What it gives | Usable here? |
|---|---|---|
| Krewski (2009) Table 1, lowest measured PM2.5 (1979-1983), 0th percentile | **10.77 µg/m³** across the same 58-MSA sample that produced the Table 3 HR used for β | **Yes** -- fully documented, from the same underlying exposure data as our β |
| Orellano et al. (2024) WHO AQG update meta-analysis | Pooled RR only (1.095 per 10 µg/m³); the paper itself states no numeric TMREL/threshold -- it is the supporting systematic review for the 2021 WHO AQG, not the guideline document | No -- no number to extract; would need the actual WHO AQG 2021 guideline document, which is not held in this repo |
| GBD TMREL (2019/2021 rounds) | Reported in the general literature as a small range (commonly ~2.4-5.9 µg/m³ depending on GBD round), but no official GBD PM2.5 risk-factor appendix is held in `docs/references/literature/` | No -- not a locally sourced/traceable value; would need that document added first |
| CREA (2021) *HIA South Korea* | Korean HIA precedent, but uses **GBD 2019 (IHME)**'s integrated exposure-response function, not the Krewski log-linear form, and states no explicit numeric counterfactual/TMREL in the report text itself | No transferable number; establishes that the one Korean HIA precedent in this repo used a different (GBD-based) methodology, not Krewski's |

**Recommendation:** use the Krewski lowest-measured-level candidate,
**10.77 µg/m³**. It is the only candidate with a fully documented, in-repo
numeric value, and it comes from the same exposure data that produced the β
this module actually uses -- so the CRF is not extrapolated below the range
it was estimated over. This is implemented as the adopted
`counterfactual_ugm3` in `crf_parameters.csv`, but **it is a recommendation,
not a unilateral decision** -- it should be confirmed before being relied on
for any reported estimate.

Truncation (`pm25_ugm3 < counterfactual_ugm3`) is handled via
`max(0, pm25 - counterfactual)` and logged as a warning naming the
district-year, rather than silently zeroed, because it breaks the clean
scaling of the marginal estimand.

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

Output carries the central attributable-death estimate plus CI bounds
obtained by substituting `ci_low`/`ci_high` for β -- this is how Huang & Peng
propagate uncertainty, and it reflects uncertainty in the CRF coefficient
only, not in PM2.5, population, or baseline mortality inputs.

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

## Out of scope

InMAP, meteorology, emissions, downscaling, exposure aggregation to 시군구,
scenario definitions, boundary harmonization, GEMM, infant-mortality
endpoints, and the CAPSS 시군구 code join remain out of scope for this core
health module. The thermal MVP keeps those responsibilities in an upstream
adapter rather than duplicating the verified health equations here.
