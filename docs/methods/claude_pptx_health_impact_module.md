# Self-contained Claude PPTX prompt: health-impact assessment module

Copy everything below this line into Claude PPTX. Claude must not assume it can
open local files, inspect code, or retrieve missing context. All scientific,
implementation, and citation information required for the slides is included
here.

---

## Assignment

Create a coherent 13-slide, 16:9 presentation section explaining the
NZK-APHIAM health-impact assessment module. The section should be rigorous
enough for an academic or technical-policy audience while remaining
understandable to people who have not used BenMAP.

The communication job is:

> By the end, the audience should understand how modeled InMAP PM2.5
> concentrations become scenario-specific mortality estimates, why this is a
> BenMAP-equivalent calculation, how the six concentration-response
> specifications differ, and which inputs and caveats determine whether a
> result is analytically usable.

This is a methods section, not a results section. Do not invent or display
health-impact estimates. In particular, do not display a previously generated
28.74-death fixed-iteration diagnostic: it was non-converged, used a
superseded single-CRF adapter, and is not an analytical result.

Do not ask to open files or search for additional context. Use only the
technical specification and bibliography embedded in this prompt.

## What the module is

NZK-APHIAM estimates long-term PM2.5-attributable mortality after an air
quality simulation has been completed. InMAP produces PM2.5 concentration;
the health module combines that concentration with population, baseline
mortality, and an epidemiological concentration-response function (CRF).

The module is described as **BenMAP-style** or **BenMAP-equivalent** because it
implements the same attributable-fraction and population-health arithmetic
used in BenMAP-style policy analysis. It does **not** claim that BenMAP itself
was run. The calculation was implemented directly because this workflow has no
native BenMAP Korea configuration.

The module operates in four layers:

1. Aggregate each InMAP scenario to a South Korea population-weighted PM2.5
   concentration using InMAP `TotalPop`.
2. Combine each scenario concentration with age-specific projected population
   and endpoint-matched baseline mortality.
3. Apply each prespecified CRF to calculate attributable mortality for that
   scenario.
4. Subtract the policy-scenario total from the reference-scenario total to
   calculate avoided deaths.

The current implementation is national rather than district-level. The
geographic identifier in health model inputs is `KOR`. District exposure and
district decomposition await compatible district boundaries and population
allocation.

## Core calculation

### Log-linear CRFs

For scenario `s`, concentration `C_s`, counterfactual `C0`, and coefficient
`beta`:

```text
DeltaC_s = max(0, C_s - C0)

AF(C_s) = 1 - exp[-beta × DeltaC_s]
```

For age group `a`, annual baseline mortality rate `Y0_a`, and exposed
population `Pop_a`:

```text
D_s = sum over age groups a of:
      AF(C_s,a) × Y0_a × Pop_a
```

`AF` is dimensionless, `Y0` is deaths per person per year, and `Pop` is
persons, so `D_s` is deaths per year.

The policy comparison is:

```text
Avoided deaths = D_reference - D_policy
```

Positive avoided deaths mean the policy scenario has fewer deaths. Negative
avoided deaths mean the policy scenario has additional deaths.

### Critical nonlinearity rule

Calculate attributable mortality separately for each scenario and then
difference scenario totals:

```text
D_reference = burden(C_reference)
D_policy    = burden(C_policy)
Avoided     = D_reference - D_policy
```

Never calculate:

```text
burden(C_reference - C_policy)
```

The attributable-fraction function is nonlinear, so these operations are not
equivalent. This rule applies to both log-linear CRFs and GEMM.

### Mortality-rate conversion

The KOSIS mortality input is deaths per 100,000 people per year. Before the
health calculation:

```text
Y0_per_person = mortality_rate_per_100k / 100,000
```

The module rejects values that appear to have been passed in per-100,000 units
without conversion.

## Exact CRF registry

The six rows below are the complete recommended specification suite. They are
**alternative specifications**, not additive endpoints. Never sum or average
their mortality estimates.

| ID | Model and role | Endpoint | Exposure metric | Ages | Central effect | 95% interval | Counterfactual |
|---|---|---|---|---:|---|---|---:|
| `peng_krewski_2009_all_cause` | Huang–Peng primary; log-linear | All-cause | Annual PM2.5 | 30+ | HR 1.06 per 10 µg/m³; beta 0.0058268908 per µg/m³ | HR 1.04–1.08; beta 0.0039220713–0.0076961041 | 0 µg/m³ |
| `gemm_2018_ncd_lri_with_china` | Huang–Peng nonlinear sensitivity | NCD+LRI | Annual PM2.5 | 25+ | Age-specific GEMM | Age-specific theta ± 1.96 SE | 2.4 µg/m³ |
| `byun_2024_korea_non_accidental` | Primary Korean-cohort sensitivity; log-linear | Non-accidental | Five-year moving-average PM2.5 | 30+ | HR 1.10 per 10; beta 0.0095310180 | HR 1.01–1.20; beta 0.0009950331–0.0182321557 | 0 µg/m³ |
| `kim_2020_korea_all_cause` | Lower Korean-cohort sensitivity; log-linear | All-cause | Long-term PM2.5 | 18+ source cohort; 20+ implemented | HR 1.034 per 10; beta 0.0033434784 | HR 1.027–1.041; beta 0.0026641927–0.0040181789 | 0 µg/m³ |
| `korea_guide_hoek_2013_policy` | Korean policy-HIA benchmark; log-linear | All-cause | Annual PM2.5 | 30+ analysis convention | beta 0.006015 | beta 0.00399032–0.00803968 | 0 µg/m³ |
| `lim_2020_korea_elderly_all_cause` | Elderly Korean-cohort sensitivity; log-linear | All-cause | 36-month moving-average PM2.5 | 65+ | HR 1.024 per 10; beta 0.0023716531 | HR 1.009–1.039; beta 0.0008959742–0.0038258708 | 0 µg/m³ |

Important interpretation:

- The Peng/Krewski primary transfers a US ACS cohort relationship to Korea.
- GEMM is global and nonlinear; it is not a Korean-derived CRF.
- Byun, Kim, and Lim are Korean cohort sensitivities.
- The Korea GUIDE/Hoek coefficient is a Korean policy-modeling precedent based
  on WHO HRAPIE/Hoek et al., not a Korea-derived cohort coefficient.
- Byun and Lim use multi-year moving-average exposure metrics. Applying them to
  annual scenario concentrations is a structural sensitivity, not an exact
  recreation of their exposure windows.
- Kim's cohort begins at age 18. The available Korean five-year bands cannot
  isolate ages 18–19, so the implementation conservatively starts with the
  complete 20–24 band rather than including the 15–19 band.
- The GUIDE row's age-30 minimum is a comparability convention, not a
  study-derived enrollment cutoff.

## Peng/Krewski primary in detail

The primary follows Huang and Peng's use of the Krewski et al. 2009 American
Cancer Society extended follow-up relationship:

```text
HR = 1.06 per 10 µg/m³ annual PM2.5
95% CI = 1.04 to 1.08

beta = ln(HR) / 10
     = ln(1.06) / 10
     = 0.0058268908 per µg/m³
```

The source cohort enrolled people age 30 and older.

The lowest PM2.5 concentration observed in the source cohort for the relevant
1979–1983 exposure metric was 10.77 µg/m³. The recommended Peng-replication
row nevertheless uses `C0 = 0` because Huang and Peng apply the coefficient to
modeled scenario concentration and do not instruct the analyst to subtract the
ACS minimum.

Therefore:

- `0 µg/m³` is the calculation counterfactual in the primary.
- `10.77 µg/m³` is the lower boundary of observed support in the source
  cohort.
- Results below 10.77 µg/m³ extrapolate beyond the source cohort's observed
  exposure range.
- Zero must not be described as a biologically proven no-risk threshold.

A legacy row that subtracts 10.77 µg/m³ is retained for reproducibility of old
runs but is not part of the recommended six-specification suite and should not
appear as a current method.

## GEMM in detail

The implemented model is Burnett et al. 2018's main Global Exposure Mortality
Model for noncommunicable diseases plus lower respiratory infections
(`NCD+LRI`), including the Chinese male cohort.

For PM2.5 concentration `C`:

```text
z = max(0, C - 2.4)

T(z) = log(1 + z/alpha) /
       [1 + exp(-(z - mu)/nu)]

RR_a(C) = exp[theta_a × T(z)]

AF_a(C) = 1 - 1/RR_a(C)
```

Shared parameters:

```text
alpha = 1.6
mu    = 15.5
nu    = 36.8
C0    = 2.4 µg/m³
```

Exact age-specific parameters:

| Age | theta | SE(theta) |
|---:|---:|---:|
| 25–29 | 0.1585 | 0.01477 |
| 30–34 | 0.1577 | 0.01470 |
| 35–39 | 0.1570 | 0.01463 |
| 40–44 | 0.1558 | 0.01450 |
| 45–49 | 0.1532 | 0.01425 |
| 50–54 | 0.1499 | 0.01394 |
| 55–59 | 0.1462 | 0.01361 |
| 60–64 | 0.1421 | 0.01325 |
| 65–69 | 0.1374 | 0.01284 |
| 70–74 | 0.1319 | 0.01234 |
| 75–79 | 0.1253 | 0.01174 |
| 80+ | 0.1141 | 0.01071 |

The GEMM lower and upper calculations substitute:

```text
theta_lower,a = theta_a - 1.96 × SE(theta_a)
theta_upper,a = theta_a + 1.96 × SE(theta_a)
```

GEMM must use age-specific **NCD+LRI baseline mortality**. Generic
non-accidental mortality is broader than NCD+LRI and must not be substituted.
All-cause mortality must not be substituted either.

## Population, mortality, and endpoint rules

The default analysis years are:

- Projected population year: 2030
- Latest compatible observed baseline mortality year: 2024
- Mortality assumption: hold the 2024 age-specific national rates constant in
  the 2030 health calculation

Population is the all-sex KOSIS province-level projection aggregated to the
national level by five-year age band.

Baseline mortality is the all-sex KOSIS national age-specific rate. It is
currently available for all-cause mortality in five-year age bands:

```text
0–4, 5–9, 10–14, 15–19, 20–24, 25–29, 30–34, 35–39,
40–44, 45–49, 50–54, 55–59, 60–64, 65–69, 70–74,
75–79, 80+
```

Each CRF requests one exact endpoint:

```text
All-cause:
  Peng/Krewski, Kim, Korea GUIDE/Hoek, Lim

Non-accidental:
  Byun

NCD+LRI:
  GEMM
```

Current default input status:

| Endpoint input | Status | Consequence |
|---|---|---|
| Age-specific all-cause mortality | Available | Four all-cause CRFs can run |
| Age-specific non-accidental mortality | Not configured | Byun is blocked |
| Age-specific NCD+LRI mortality | Not configured | GEMM is blocked |

Missing endpoint data do not stop compatible CRFs. Instead, the affected
specification receives a machine-readable blocked status. All-cause mortality
is never silently substituted for another endpoint. Non-all-cause mortality
files must identify their endpoint explicitly.

After applying a CRF's age minimum, projected population and baseline mortality
must have matching age bands. Duplicate, missing, or misaligned denominator
rows block the affected specification.

## InMAP concentration interpretation

The health adapter accepts one national population-weighted PM2.5 value for
each scenario and supports two modes.

### Mode 1: direct scenario concentration

```text
mode = direct_scenario_concentration
C_health,s = C_InMAP,s
```

Use this only when the InMAP scenario output represents total ambient PM2.5
concentration for that scenario.

### Mode 2: background plus source contribution

```text
mode = background_plus_inmap_contribution
C_health,s = C_background,s + C_InMAP_contribution,s
```

The background can be common across scenarios or scenario-specific, but it
must be finite, non-negative, defensible, and documented.

The current thermal-power-only InMAP inventory represents an incremental
Korean thermal-power PM2.5 source contribution, not total ambient PM2.5.
Consequently:

- It is valid for testing signs, schema, and pipeline plumbing.
- It is not by itself a reportable total-ambient health exposure.
- The default configuration labels its scope as
  `incremental_korean_thermal_power_pm25_not_total_ambient`.
- The default configuration sets `analytical_use_permitted = false`.

A reportable health run needs either:

1. a converged all-source InMAP concentration for every scenario; or
2. a converged source-contribution result plus a sourced background.

Convergence alone is not sufficient. Concentration scope, scenario design, and
mortality endpoint must also support the claimed interpretation.

## Input and output behavior

For every runnable CRF, model inputs carry:

- national geography code (`KOR`)
- target population year
- scenario
- age band
- health-model PM2.5 concentration
- baseline mortality rate per person
- population
- original InMAP exposure year
- mortality endpoint
- CRF ID
- exposure mode
- exposure scope
- analytical-use flag

The pipeline writes:

| Output | Meaning |
|---|---|
| `national_scenario_exposures.csv` | Population-weighted InMAP concentration, scope, represented population, and cell count by scenario |
| `health_model_inputs.csv` | Age-specific concentration, population, mortality, endpoint, and CRF inputs |
| `health_scenario_totals.csv` | Attributable mortality by CRF and scenario |
| `health_impacts.csv` | Reference-minus-policy avoided deaths and CRF-only lower and upper values |
| `health_specification_status.csv` | Complete or blocked status and reason for every requested CRF |

Outputs preserve CRF ID, CRF label, model type, endpoint, specification role,
concentration mode, exposure scope, mortality year, population year,
mortality-rate assumption, sign convention, and analytical-use status.

The report must list every CRF separately. It must never sum alternative CRF
estimates.

## Validation and status behavior

The implementation rejects or blocks:

- missing required columns
- negative, missing, or non-finite PM2.5 concentration
- negative population
- missing, negative, non-finite, or greater-than-100,000 mortality rates per
  100,000
- baseline mortality accidentally supplied in per-100,000 units to a function
  expecting per-person units
- age bands below or above the CRF's valid range
- duplicate mortality age bands
- population and mortality age-band mismatches
- non-all-cause mortality files without an explicit matching endpoint
- an unknown concentration mode
- background-plus-contribution mode without valid background concentration
- a scenario exposure table with anything other than one row per requested
  scenario

Examples of specification statuses include:

```text
complete
blocked_missing_endpoint_mortality
blocked_missing_mortality_file
blocked_invalid_mortality_input
```

A blocked row is an input-availability or compatibility result, not a software
failure.

## Uncertainty interpretation

For log-linear CRFs, lower and upper mortality estimates substitute the lower
and upper beta coefficients.

For GEMM, lower and upper estimates substitute age-specific
`theta ± 1.96 × SE(theta)`.

These intervals reflect **CRF parameter uncertainty only**. They do not include:

- emissions uncertainty
- emission-factor uncertainty
- InMAP model or convergence uncertainty
- background-concentration uncertainty
- exposure aggregation uncertainty
- population uncertainty
- baseline mortality uncertainty
- scenario uncertainty
- endpoint choice
- structural differences between log-linear and GEMM functions

Do not label the interval as a complete uncertainty interval.

## Non-negotiable statements for the deck

Preserve all of the following:

1. This is a transparent BenMAP-style or BenMAP-equivalent calculation.
   BenMAP itself is not run.
2. Calculate attributable mortality for every scenario first, then difference
   scenario totals.
3. The six CRFs are alternatives. Never add or average their results.
4. Match each CRF to its exact endpoint and age range.
5. NCD+LRI, non-accidental, and all-cause mortality are not interchangeable.
6. The primary's zero counterfactual is a scenario-total modeling convention,
   not a proven zero-risk threshold.
7. The ACS 10.77 µg/m³ value is an observed-support boundary, not the primary
   counterfactual.
8. Korean-cohort sensitivities increase local relevance but differ in endpoint,
   age, and exposure window.
9. The thermal-only InMAP output is a source contribution and defaults to
   non-analytical use.
10. CRF intervals are not complete model uncertainty intervals.

## Embedded source bibliography

Use the source IDs below in speaker notes. All links are direct links to the
original publication or official source; do not cite search-results pages.

**S1 — Huang and Peng replication target**

Huang, X., Peng, W., Zhao, A., Ou, Y., Kennedy, S., Iyer, G., McJeon, H.,
Cui, R., and Hultman, N. (2025). “Substantial air quality and health
co-benefits from combined federal and subnational climate actions in the
United States.” *One Earth*, 8, 101232.
`https://doi.org/10.1016/j.oneear.2025.101232`

Supports: BenMAP-style health equations, Krewski primary, scenario-specific
health calculation, GEMM sensitivity, and sequential health decomposition.

**S2 — Krewski primary CRF**

Krewski, D., Jerrett, M., Burnett, R. T., et al. (2009). *Extended Follow-Up
and Spatial Analysis of the American Cancer Society Study Linking Particulate
Air Pollution and Mortality*. HEI Research Report 140.
`https://www.healtheffects.org/node/442`

Direct report PDF:
`https://www.healtheffects.org/system/files/Krewski140.pdf`

Supports: all-cause HR 1.06 (1.04–1.08) per 10 µg/m³, age 30+ cohort
restriction, and 10.77 µg/m³ lowest observed concentration for the relevant
exposure metric.

**S3 — GEMM**

Burnett, R., Chen, H., Szyszkowicz, M., et al. (2018). “Global estimates of
mortality associated with long-term exposure to outdoor fine particulate
matter.” *Proceedings of the National Academy of Sciences*, 115,
9592–9597.
`https://doi.org/10.1073/pnas.1803222115`

Supports: GEMM functional form, 2.4 µg/m³ counterfactual, age-specific
NCD+LRI model, and SI Table S2 parameters.

**S4 — Byun Korean non-accidental mortality CRF**

Byun, G., Kim, S., Choi, Y., et al. (2024). “Long-term exposure to PM2.5 and
mortality in a national cohort in South Korea: effect modification by
community deprivation, medical infrastructure, and greenness.” *BMC Public
Health*, 24.
`https://doi.org/10.1186/s12889-024-18752-y`

Supports: non-accidental HR 1.10 (1.01–1.20) per 10 µg/m³, five-year
moving-average exposure, and age 30+ cohort.

**S5 — Kim Korean all-cause mortality CRF**

Kim, H., et al. (2020). “Long-term fine particulate matter exposure and
cardiovascular mortality in the general population: a nationwide cohort
study.” *Journal of Cardiology*, 75, 549–558.
`https://doi.org/10.1016/j.jjcc.2019.11.004`

Article page:
`https://www.journal-of-cardiology.com/article/S0914-5087(19)30344-2/fulltext`

Supports: all-cause mortality increase of 3.4% (2.7%–4.1%) per 10 µg/m³,
adult cohort, and stronger evidence above approximately 18 µg/m³.

**S6 — Lim Korean elderly CRF**

Lim, Y.-H., et al. (2020). “Long-term exposure to moderate fine particulate
matter concentrations and cause-specific mortality in an ageing society.”
*International Journal of Epidemiology*, 49, 1792–1802.
`https://doi.org/10.1093/ije/dyaa146`

Article page:
`https://academic.oup.com/ije/article/49/6/1792/5933274`

Supports: all-cause HR 1.024 (1.009–1.039) per 10 µg/m³, 36-month
moving-average exposure, age 65+ Korean cohort, and Korean HIA precedent using
population and mortality data.

**S7 — Korean GUIDE policy-HIA benchmark**

Kim, J., Jang, Y., Hu, H., et al. (2025). “Analysis of Health Impacts from
Future Air Quality Changes Considering the Aging Population in Korea.”
*Atmosphere*, 16, 41.
`https://doi.org/10.3390/atmos16010041`

Supports: Korean GUIDE/CMAQ/BenMAP policy-HIA precedent and beta 0.006015 for
long-term adult PM2.5 mortality based on WHO HRAPIE/Hoek.

**S8 — KOSIS age-specific mortality**

Korean Statistical Information Service, table `DT_1B80A18`, all-cause deaths
and mortality rates by age, sex, and geography.
`https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1B80A18`

Supports: Korean age-specific baseline all-cause mortality rates.

**S9 — KOSIS population projections**

Korean Statistical Information Service, table `DT_1BPB002E`, population
projections by age.
`https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPB002E`

Supports: target-year Korean age-specific projected population.

**S10 — Project implementation**

NZK-APHIAM health-impact module, July 2026 implementation specification,
including the equations, exact parameter registry, endpoint guards, InMAP
adapter behavior, outputs, validation rules, and current input status embedded
in this prompt.

Use S10 for claims about how this particular software pipeline operates. Pair
S10 with S1–S9 when the claim also originates in external literature or
official data.

## Visual and writing direction

- If this section is inserted into an existing deck, inherit its master,
  typography, palette, footer, and page-number treatment.
- If no deck is supplied, use a restrained academic style: warm white
  background, deep navy text, teal for the primary pathway, muted violet for
  sensitivity specifications, and amber only for caveats or blocked inputs.
- Use at least 35 pt for slide titles, 24 pt for subheads, and 16 pt for body
  text. Keep every title on one line.
- Use takeaway titles that state the slide's conclusion.
- Prefer one dominant composition per slide. Avoid dashboards, card grids,
  decorative icons, and generic medical stock photography.
- Use native PowerPoint shapes for the pipeline and endpoint diagrams. Put
  connectors behind nodes and keep connector directions consistent.
- Typeset equations as real editable equation text where possible. Do not use
  screenshots of equations.
- Use µg/m³ consistently. Define every abbreviation on first use:
  concentration-response function (CRF), attributable fraction (AF), baseline
  mortality rate (Y0), and noncommunicable diseases plus lower respiratory
  infections (NCD+LRI).
- Add a `[Sources]` block in the speaker notes of every slide. Use the embedded
  source IDs and direct links above. Do not put long citations in visible slide
  copy.

## Slide-by-slide specification

### Slide 1 — Health impacts are calculated from modeled exposure, not emissions alone

**Narrative job:** Open the section and establish what the module contributes.

**Visible content:**

- Section label: `Health-impact assessment`
- Subtitle: `From InMAP PM2.5 concentration to attributable mortality`
- One sentence: `A transparent Korea-specific implementation of the mortality
  calculation used in BenMAP-style policy analysis`

**Visual:** A restrained left-to-right visual:
`InMAP concentration → exposed population → mortality impact`.
Keep this as a simple section divider, not a detailed process diagram.

**Speaker notes:** Explain that emissions are upstream inputs; health effects
are calculated only after atmospheric transport, chemistry, exposure
aggregation, population, baseline mortality, and a CRF are combined.

**Sources:** S10.

### Slide 2 — We reproduce BenMAP's mortality arithmetic without claiming to run BenMAP

**Narrative job:** Explain the relationship between BenMAP and the module.

**Visible content:** Use a clean two-column comparison.

Left, `BenMAP-style structure`:

- Air-quality change or scenario concentration
- Population and baseline incidence
- Epidemiological concentration-response function
- Attributable cases and scenario differences

Right, `NZK-APHIAM implementation`:

- National Korean InMAP exposure adapter
- KOSIS population and mortality inputs
- Evidence-linked six-CRF registry
- Open calculations with auditable intermediate tables

Bottom line:

> The epidemiological arithmetic is equivalent; the geographic configuration,
> inputs, and implementation are Korean and project-specific.

**Visual:** The comparison is the visual. Do not use a BenMAP screenshot.

**Speaker notes:** State that BenMAP itself is not run. Explain that the direct
implementation makes concentration scope, endpoint matching, age restrictions,
and alternative CRFs explicit.

**Sources:** S1 and S10.

### Slide 3 — The pipeline converts InMAP concentration into mortality in six auditable steps

**Narrative job:** Show the complete calculation map before introducing
equations.

**Visible content:** One horizontal flow:

1. `Scenario emissions`
2. `InMAP PM2.5`
3. `Population-weighted exposure`
4. `Age-specific Pop × Y0`
5. `CRF → attributable fraction`
6. `Scenario mortality → difference`

Under steps 3–5, add:

- `InMAP TotalPop weights`
- `KOSIS population and mortality`
- `Primary + five sensitivities`

**Visual:** Native PowerPoint flow diagram. Use teal for the primary flow,
gray for data inputs, and violet only at the CRF step to signal multiple
specifications.

**Speaker notes:** Explain that InMAP produces concentration, not deaths.
Every runnable CRF receives the same scenario exposure but its own endpoint
and age restriction.

**Sources:** S8, S9, and S10.

### Slide 4 — Exposure, baseline risk, and population jointly determine attributable mortality

**Narrative job:** Introduce the equations and define every term.

**Visible content:** Make these equations the largest objects:

```text
AF(C_s) = 1 - exp[-beta × max(0, C_s - C0)]

D_s = sum_a [AF(C_s,a) × Y0_a × Pop_a]
```

Definitions:

- `C_s`: scenario PM2.5 concentration
- `C0`: CRF counterfactual
- `beta`: concentration-response coefficient
- `Y0_a`: annual baseline mortality rate for age group `a`
- `Pop_a`: exposed population for age group `a`

Unit check:

```text
dimensionless AF × deaths/person/year × persons = deaths/year
```

**Visual:** Equation-led slide with definitions aligned under the associated
symbols.

**Speaker notes:** Explain the KOSIS per-100,000 to per-person conversion and
the role of age-specific denominators.

**Sources:** S1, S8, S9, and S10.

### Slide 5 — We calculate each scenario first—and only then take the difference

**Narrative job:** Prevent the most consequential implementation error.

**Visible content:** Two parallel lanes:

```text
Reference concentration → AF_reference → D_reference
Policy concentration    → AF_policy    → D_policy

Avoided deaths = D_reference - D_policy
```

Prominent warning:

> Do not calculate `AF(C_reference - C_policy)`.

Explanation:

> The attributable-fraction function is nonlinear, so the two operations are
> not equivalent.

**Visual:** Two converging lanes ending in one subtraction. Do not invent a
numerical example.

**Speaker notes:** Define the sign convention. State that the same
scenario-first rule applies to GEMM.

**Sources:** S1 and S10.

### Slide 6 — The Peng primary uses Krewski's log-linear all-cause relationship

**Narrative job:** Explain where the primary comes from and how it is
parameterized.

**Visible content:**

- Source: Krewski et al. 2009, ACS extended follow-up
- Endpoint: all-cause mortality
- Population: age 30+
- HR: `1.06` per 10 µg/m³
- 95% CI: `1.04–1.08`
- `beta = ln(1.06)/10 = 0.0058269 per µg/m³`
- Primary counterfactual: `C0 = 0`
- Observed-support lower bound: `10.77 µg/m³`

Bottom caveat:

> Below 10.77 µg/m³, the coefficient is extrapolated beyond the lowest
> exposure observed in the source cohort.

**Visual:** A simple log-linear modeled response curve. Show 10.77 µg/m³ as a
vertical dashed support boundary. Label the curve `specified model—not
observed Korean data`.

**Speaker notes:** Explain the HR-to-beta conversion and why zero is used in
the Huang–Peng replication. Explicitly say zero is not a proven no-risk
threshold.

**Sources:** S1, S2, and S10.

### Slide 7 — Six prespecified CRFs test transferability and functional-form uncertainty

**Narrative job:** Present the full suite and the purpose of each
specification.

**Visible content:** Use one readable table:

| Specification | Role | Endpoint | Ages | Effect |
|---|---|---|---:|---|
| Peng/Krewski 2009 | Primary | All-cause | 30+ | HR 1.06 per 10 |
| Burnett GEMM 2018 | Nonlinear Peng sensitivity | NCD+LRI | 25+ | Age-specific nonlinear |
| Byun 2024 | Primary Korean sensitivity | Non-accidental | 30+ | HR 1.10 per 10 |
| Kim 2020 | Lower Korean sensitivity | All-cause | 20+ implemented | HR 1.034 per 10 |
| Korea GUIDE/Hoek | Policy benchmark | All-cause | 30+ convention | beta 0.006015 |
| Lim 2020 | Elderly Korean sensitivity | All-cause | 65+ | HR 1.024 per 10 |

Below the table:

> These are alternative answers to the same policy question—not additive
> health endpoints.

**Visual:** The table is the visual. Highlight the primary row in teal and use
subtle violet accents for sensitivities.

**Speaker notes:** Explain that not every row is a Korean-derived coefficient.
Mention Kim's age-band implementation and the GUIDE comparability convention.

**Sources:** S1–S7 and S10.

### Slide 8 — GEMM adds nonlinear, age-specific risk above 2.4 µg/m³

**Narrative job:** Explain how GEMM differs mathematically and
epidemiologically from the primary.

**Visible content:**

```text
z = max(0, C - 2.4)

T(z) = log(1 + z/1.6) /
       [1 + exp(-(z - 15.5)/36.8)]

RR_a = exp[theta_a × T(z)]
AF_a = 1 - 1/RR_a
```

Add:

- `theta varies across 12 age groups from 25–29 through 80+`
- `uncertainty uses theta ± 1.96 × SE(theta)`
- `endpoint = NCD+LRI`

**Visual:** If an accurate plot can be computed, show one illustrative GEMM
relative-risk curve using the 60–64 parameters:
`theta = 0.1421`, `SE = 0.01325`, across 0–40 µg/m³. Label it `Model shape
computed from published parameters—not observed outcome data`. Mark
2.4 µg/m³. If the plot cannot be computed accurately, omit it and use the
equation plus a clean age-parameter strip. Never invent curve values.

Do not put Krewski and GEMM on a single unlabeled axis because their endpoints
and age structures differ.

**Speaker notes:** Explain why NCD+LRI baseline mortality is essential and why
generic non-accidental mortality is not an acceptable denominator.

**Sources:** S3 and S10.

### Slide 9 — Korean evidence improves relevance but does not yield one universally “best” coefficient

**Narrative job:** Explain what is gained and what remains structurally
different across the Korean evidence.

**Visible content:** Use a horizontal evidence spectrum, not a ranking:

- `Byun 2024`: nationwide NHIS-NSC; non-accidental; five-year moving average;
  age 30+
- `Kim 2020`: nationwide NHIS cohort; all-cause; adult cohort; stronger
  evidence above approximately 18 µg/m³
- `Lim 2020`: Korean elderly cohort; all-cause; 36-month moving average;
  age 65+
- `Korea GUIDE`: Korean policy-HIA precedent; not a Korean-derived cohort
  coefficient

Bottom takeaway:

> Different endpoints, ages, exposure windows, and study designs prevent a
> simple coefficient ranking.

**Visual:** Four aligned evidence markers from `Korean policy precedent` to
`Korean cohort evidence`. Avoid four boxed cards.

**Speaker notes:** State that applying moving-average cohort coefficients to
annual scenario concentrations is a structural sensitivity. Explain that the
approximately 18 µg/m³ Kim finding is not encoded as a biological threshold.

**Sources:** S4–S7 and S10.

### Slide 10 — Endpoint and age matching are enforced, not assumed

**Narrative job:** Show why mortality denominators are part of the
specification.

**Visible content:** Three endpoint lanes:

```text
All-cause Y0       → Peng/Krewski, Kim, GUIDE, Lim
Non-accidental Y0  → Byun
NCD+LRI Y0         → GEMM
```

Show current status:

- All-cause age-specific input: `available`
- Non-accidental age-specific input: `not configured`
- NCD+LRI age-specific input: `not configured`

Add:

> Missing or mismatched endpoint inputs block only the affected
> specification; compatible specifications continue.

**Visual:** Three parallel lanes with amber stop symbols at the missing
non-accidental and NCD+LRI inputs.

**Speaker notes:** Explain that non-all-cause inputs must explicitly identify
their endpoint. Population and mortality bands must align after age filtering.
Blocked specifications are data-status outcomes, not software failures.

**Sources:** S8 and S10.

### Slide 11 — InMAP concentration scope determines whether a health result is interpretable

**Narrative job:** Separate total ambient concentration from a source
contribution.

**Visible content:** Compare the two modes.

Mode 1:

```text
direct_scenario_concentration
C_health,s = C_InMAP,s
```

Use only when InMAP represents total ambient PM2.5.

Mode 2:

```text
background_plus_inmap_contribution
C_health,s = C_background,s + C_InMAP contribution,s
```

Use when InMAP represents a modeled source or sector and a defensible
background is available.

Prominent current-state statement:

> The thermal-only inventory is a source contribution; its default health run
> is a pipeline test with `analytical_use_permitted = false`.

**Visual:** Two equations with a small source-scope illustration:
`all sources` versus `background + thermal contribution`.

**Speaker notes:** Explain why background affects nonlinear burden
calculations. State that convergence is necessary but not sufficient.

**Sources:** S10.

### Slide 12 — Outputs keep specifications, uncertainty, and scientific status separate

**Narrative job:** Make the module auditable and show what downstream users
receive.

**Visible content:** Use this mapping:

| Output | Purpose |
|---|---|
| `national_scenario_exposures.csv` | InMAP concentration and scope by scenario |
| `health_model_inputs.csv` | Age-specific population, Y0, concentration, endpoint, and CRF |
| `health_scenario_totals.csv` | Attributable mortality by scenario and CRF |
| `health_impacts.csv` | Reference-minus-policy avoided deaths and CRF interval |
| `health_specification_status.csv` | Complete or blocked status and reason |

Rules:

- `Report each CRF separately—never sum across specifications.`
- `CRF intervals are not complete model uncertainty intervals.`

**Visual:** A vertical sequence from model inputs to results and status. Avoid
a dashboard treatment.

**Speaker notes:** Explain the sign convention and list the metadata preserved
in outputs. Describe the excluded uncertainty sources.

**Sources:** S10.

### Slide 13 — The module is complete; analytical results depend on valid exposure and mortality inputs

**Narrative job:** Close by distinguishing implemented capability from
remaining empirical inputs.

**Visible content:** Two columns.

`Implemented and tested`:

- BenMAP-equivalent attributable-mortality arithmetic
- Six prespecified CRFs, including age-specific GEMM
- CRF-only lower and upper estimates
- Endpoint and age validation
- Direct and background-added concentration modes
- Per-specification status and analytical-use flags

`Required for reportable estimates`:

- Strictly converged InMAP scenario outputs
- Total ambient concentration or sourced background
- Paired, policy-relevant reference and policy scenarios
- Age-specific non-accidental mortality for Byun
- Age-specific NCD+LRI mortality for GEMM

Closing statement:

> The software can test every specification; scientific interpretation is
> permitted only when exposure and mortality inputs support the claim.

**Visual:** A balanced implemented-versus-required composition. Do not end on
a generic thank-you slide.

**Speaker notes:** State that four all-cause specifications can currently run
with the available KOSIS denominator, while Byun and GEMM remain blocked by
their missing endpoint-specific denominators.

**Sources:** S8–S10.

## Required speaker-note format

At the end of each slide's notes, add:

```text
[Sources]
- [S#] Author or organization, title, year, direct DOI or URL
- [S10] NZK-APHIAM implementation specification supplied in the prompt
```

Include only the sources actually used on that slide. Every external equation,
parameter, cohort characteristic, and methodological claim needs a source.

## Final quality-control checklist

Before delivering the PPTX:

- Confirm all six CRF names, roles, endpoints, ages, HRs, intervals, beta
  values, exposure metrics, and counterfactuals against the embedded registry.
- Confirm all twelve GEMM theta and SE values against the embedded table.
- Confirm equations use scenario concentration and avoided deaths are
  calculated by differencing scenario totals.
- Confirm no slide adds or averages alternative CRF results.
- Confirm GEMM is paired only with NCD+LRI mortality.
- Confirm the source-only thermal InMAP configuration is labeled
  non-analytical.
- Confirm 10.77 µg/m³ is labeled as the Krewski observed-support minimum, not
  the primary counterfactual.
- Confirm zero is not described as a biologically proven threshold.
- Confirm uncertainty is described as CRF-only.
- Confirm every slide has a `[Sources]` block in speaker notes.
- Render every slide and inspect it at full size for clipping, overlap,
  equation legibility, title wrapping, and source-note completeness.
