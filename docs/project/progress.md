# Research Progress

_As of 27 July 2026_

## 0a. Temporary KEPCO-only scenario fixtures

A deterministic proof-of-concept workflow now supplies two parallel three-scenario
thermal fixture families for 2025--2050 while the MACRO team scenarios are pending.
The original `no_nzk`, `nzk_low`, and `nzk_high` proportional-generation files are
retained. A separate `no_nzk_fleet_hold`, `nzk_low_unit_retirement`, and
`nzk_high_unit_retirement` family implements lumpy whole-unit exits: documented
closure dates take precedence, followed by oldest commissioning year, lowest
baseline utilization, highest NOx-plus-SOx intensity, and stable unit ID.

Both families treat the complete 2024 KEPCO calendar-year roster as a 2025 proxy,
keep non-thermal generation out of scope, carry plant coordinates, fuel, technology,
annual mass emissions, and stack parameters, and export the existing five-column
MACRO generation shape. The high cases reach zero thermal generation in 2050; the
low cases reach zero coal and oil-family generation while retaining LNG and biomass;
the no-NZK cases remain flat.

The rules, official Korean endpoint references, caveats, output schema, and commands
are documented in
[`docs/methods/kepco_poc_fleet_scenarios.md`](../methods/kepco_poc_fleet_scenarios.md).
These are explicitly test fixtures, not production scenario definitions or forecasts.

## 0b. Temporary non-power activity fixture

A reproducible GCAM-KAIST-shaped non-power activity fixture now supplies normalized
`2023 = 100` and `2025 = 100` indices for `no_nzk`, `nzk_low`, and `nzk_high`
through 2050. The rich output covers all 50 P1 inventory activities and preserves
conceptual technology/fuel labels, eventual physical units, profile assumptions,
boundary flags, and model-use status. A separate 44-pair CAPSS-aligned
sector/fuel view has the existing five-column activity schema and passes through
the aggregate intensity integrator without unmatched activity rows. Its 13
expected diagnostics are the fuel rows in the deliberately excluded aggregate
energy-industry combustion category.

The fishing-vessel/fisheries-energy overlap is retained but assigned to a single
emissions owner. Aggregate CAPSS energy-industry combustion is excluded because
it mixes power generation with non-power refining activity. These are synthetic
pipeline-test indices, not physical activity quantities, forecasts, or
GCAM-KAIST results. Commands, formulas, output schemas, and replacement rules are
documented in
[`docs/methods/gcam_kaist_nonpower_proxy.md`](../methods/gcam_kaist_nonpower_proxy.md).

## 0c. Combined point-plus-grid InMAP fixture

The proportional KEPCO power scenarios and GCAM-KAIST-shaped non-power activity
fixture now assemble into 18 Global InMAP scenario-year input bundles. Each bundle
contains an elevated KEPCO point shapefile, a COARDS NetCDF-3 non-power grid, a
harmonized power plus non-power mass ledger, and a relative-path manifest with
source checksums. Power generation is mass-balanced to KEPCO units and multiplied
by the 2024 complete-calendar generation-weighted KEPCO factors. TSP remains an
audit pollutant and is not relabeled as primary PM2.5.

The non-power factor catalog is audited during every build. Because it currently
has zero production-ready factors and links, the first pass uses the explicitly
selected CAPSS 2023 aggregate emissions-per-activity-index screening intensity.
Approved-factor mode fails closed. All non-power mass is temporarily distributed
over a four-cell national proxy grid; the routing diagnostic separately flags
facility-like rows as point-preferred and diffuse rows as awaiting sector-specific
spatial surrogates. National pollutant mass is preserved, but every manifest sets
`analytical_use_permitted=false`.

The command, schemas, safeguards, outputs, and replacement path are documented in
[`docs/methods/inmap_combined_inventory.md`](../methods/inmap_combined_inventory.md).
All 18 strict and fixed-iteration TOMLs can now be generated from the bundle and
the pinned local installation. Cache-aware targets run sequentially or with
bounded scenario-level parallelism and resume completed identical jobs. The
parallel runner partitions detected CPU cores across workers and records its
limits in the summary; two workers are the documented ceiling for the current
38.7 GB development machine. A separate 50-iteration, two-worker target runs the
complete InMAP-to-health plumbing proof under `poc_50_iterations/` without
overwriting the 200-iteration work; fixed-count accuracy remains unquantified
until it is benchmarked against automatic convergence. Output validation
requires all requested PM2.5 components and `TotalPop`. A real-binary
one-iteration `no_nzk` 2025 smoke job accepted the mixed point/COARDS inputs and
wrote a valid 273,739-cell output; it is execution evidence only, not a modeled
concentration.

The combined-run post-processor now filters every output to Korean cells,
calculates national population-weighted PM2.5, and feeds the 18 scenario-year
concentrations through the existing BenMAP-style multi-CRF health adapter. It
writes primary scenario mortality, all-CRF sensitivities, and same-year avoided
deaths versus `no_nzk`. The fixed-iteration pathway is filename- and row-labeled
as non-converged. KOSIS age-specific population is exact through 2040 for the
five-year scenarios; 2045 and 2050 explicitly hold the latest 2042 projection.
The latest 2024 national age-specific mortality rates are held constant.
The same one-command health workflow now produces three presentation figures and
four concise CSV tables: InMAP PM2.5 trajectories and reductions, primary
scenario mortality, avoided mortality relative to `no_nzk`, and an endpoint-year
air-quality/health summary. The report manifest preserves the diagnostic status
and source health manifest; reporting does not promote fixed-iteration results
to analytical estimates.

## 0. Korean thermal-power replication MVP

An executable screening-level chain now links the local observed EPSIS 2021
thermal generation handoff to the single available 2030 MACRO pathway, allocates
generation to the canonical processed KEPCO thermal fleet plus explicit real-site
province coverage, applies the existing generation-weighted KEPCO EFs, generates
Global InMAP inputs, optionally combines scenario-scoped non-power point/polygon or
COARDS NetCDF-3 gridded inventories, aggregates national exposure, and adapts real
exposure to the existing health model. The configuration, commands, assumptions, and
limitations are documented in
[`docs/methods/peng_replication_mvp.md`](../methods/peng_replication_mvp.md).
A slide-production brief for explaining the model, mixed emissions inputs,
Korea-specific bias correction, and pipeline integration is available in
[`docs/methods/claude_pptx_inmap_module.md`](../methods/claude_pptx_inmap_module.md).

Because the MACRO file has no scenario field and contains only one pathway, the
comparison is labeled `historical_to_scenario`; no reference pathway was invented.
Primary PM2.5, NH3, and VOC are omitted from the central inventory rather than
assigned undocumented factors. Global InMAP v1.9.6 and official model data v1.1.0
are pinned in the workflow; run-specific execution state and any external blocker
are recorded under ignored `results/mvp/peng_replication/`.

The team has selected Global InMAP's annual-resolution pathway, including its
packaged global meteorology and built-in bias correction. The separate hourly KMA
weather pipeline is therefore superseded and has been moved to
`src/nzk_aphiam/archive/kma_weather/`; its history and optional manual commands are
documented in [`docs/archive/kma_weather.md`](../archive/kma_weather.md).

The official binary and dataset installed successfully. A strict static-grid attempt
advanced to about 4.1 simulated days over 1.79 cumulative solver hours, but the slowest
global mass check was still about 2.7%, above the official 0.1% convergence criterion.
It was terminated without a concentration output; InMAP v1.9.6 has no solver checkpoint,
so the strict analytical run still needs a fresh uninterrupted execution.

A separate, explicitly non-converged 200-iteration real-binary proof of concept has now
completed both inventories end to end. Each run wrote 273,739 Global InMAP cells in
about 4.8 minutes. The differencing/exposure path selected 1,104 South Korean cells and
represented 49.76 million people. Its diagnostic population-weighted incremental PM2.5
values were 0.024857 µg/m³ for observed 2021 and 0.036591 µg/m³ for the 2030 MACRO
pathway, or -0.011734 µg/m³ under the documented historical-minus-future sign. These
early-time values are plumbing evidence only, not analytical estimates. The workflow
marks them non-converged and prohibits the normal health stage.

An explicitly requested, now-superseded single-CRF diagnostic health post-processing
pass confirmed the expected sign. The MACRO inventory contains 50.14 thousand tonnes/year more NOx and 12.53
thousand tonnes/year more SOx than the observed inventory, and its POC concentration
is higher. Using 2030 projected Korean population age 30+, 2024 national age-specific
mortality rates held constant, and the Krewski central CRF gives **28.74 additional
annual deaths** under MACRO relative to observed 2021 (CRF-coefficient-only interval:
19.34--37.95). The scenario totals are 89.61 versus 60.88 attributable deaths. These
numbers inherit the fixed-iteration non-convergence, overstated thermal generation,
omitted primary PM2.5/NH3/VOC, stack and allocation imputations, national averaging,
and US-cohort CRF limitations. They are retained only as sign-and-plumbing diagnostics;
the normal `health_impacts.csv` remains absent and analytical use is prohibited.
That historical diagnostic used the legacy counterfactual-plus-source-contribution
adapter and is not comparable to a current suite run.

The health adapter now evaluates six prespecified CRFs from each pair of national
InMAP scenario concentrations: Huang–Peng/Krewski primary, Burnett GEMM NCD+LRI,
Byun non-accidental, Kim all-cause, Korean GUIDE/Hoek policy benchmark, and Lim
elderly all-cause. It supports either direct total-ambient scenario concentration or
a sourced background plus InMAP contribution, applies study-specific age
restrictions, normalizes difference intervals, and emits per-specification inputs,
scenario totals, impacts, and status. Endpoint matching is strict. Current KOSIS
data activate the four all-cause rows; Byun and GEMM remain machine-readably blocked
until separate age-specific non-accidental and NCD+LRI mortality inputs are supplied.

## 1. Repo state (`yh7649/NZK-APHIAM`, main, 53 commits, v0.1.0 tagged)

Structure is a cookiecutter-data-science layout with Python (77%), R (19%), a bit of Stata. What's actually built:

**Implemented and tested:**
- **KEPCO thermal scrapers/cleaners** for all five subsidiaries (East-West, Western, Southern, South-East, and Midland); Midland now uses KOMIPO's checksum-verified direct 2024--2025 monthly mass workbook joined to its existing public monthly generation, with the superseded concentration/flow estimator archived; plus KHNP generation, combiner, auditor, explicit pollutant-month EF eligibility, on-demand cohort EF queries, operational/low-load/conservative annual sensitivities, and handoff workbook export
- **CAPSS scraper + processor + power export** (`data/process/capss/processor.py`, `data/process/capss_power_fuel_technology.py`) — tidy long emissions, taxonomy-period flags, pollutant coverage metadata, 2016--2023 public/private power fuel × official CAPSS technology tables
- **Non-power inventory and EF evidence** (`data/process/nonpower_sector_inventory.py`, `data/process/nonpower_emission_factors.py`, `data/scrape/capss/nonpower_emission_factors.py`, `docs/references/nonpower_emissions/`) — inventory v0.2.0 contains 89 substantive activities, 181 native-CAPSS crosswalk rows, 608 pollutant-specific denominators, and separate supplemental boundaries for commercial cooking aerosol, charcoal kilns, and road tire/brake wear. The tracked collection retains 912 imported candidates mapped into 2,067 links over 41 activities. The verified official Handbook VII scrape covers 327 PDF pages and 86 direct-emission activities, indexes 123 true factor/speciation tables, reconstructs 129 table occurrences, and emits 3,250 standard-column factor candidates. Of those, 2,994 have aligned labels, 3,144 have resolved units, and 2,720 map conservatively into 4,196 candidate links over 54 activities. All imported and scraped rows remain `production_ready=false`; formula-heavy table parsers, row review, VI-to-VII diffing, and annual weighting remain
- **MACRO/GCAM integrator** (`data/process/macro/integrator.py`) — exactly the EF-derivation logic (CAPSS emissions ÷ GCAM activity → EF → × projected activity); the separate 2021 KEPCO-EF × MACRO-generation validation module is implemented but still requires the external MACRO generation file
- **AirKorea hourly QC pipeline** (2001–2025 finalized archives, station crosswalk, anomaly model, spatial validation)
- **KOSIS health/demographic panel** (monthly deaths by 시군구, cause deaths, population, age structure, projections, ~20 SDOH covariates)
- **Crosswalks**: plant location/dates, retirement dates, stack properties, technology mapping — all with evidence files
- **KEPCO external EF validation** permits percent-error statistics only for
  reviewed exact plant/unit/year comparisons, separates MOTIE fuel-fleet checks
  from plant validation, and exposes contextual/noncomparable literature gaps
  without automatic fuel-technology matching
- **Mixed-sector Global InMAP inputs** accept validated scenario/year-scoped
  point, line, or polygon shapefiles and COARDS NetCDF-3 grids alongside the
  generated elevated power inventory. Run manifests and cache keys cover every
  supplemental input and shapefile component.

**Archived as superseded:**

- **Midland concentration/flow mass estimator and per-site air-status scrapers**
  — retained for provenance after KOMIPO supplied direct monthly pollutant mass
- **KMA hourly weather** (ASOS, radiosonde, stability indices, Wind Profiler;
  mixing-height and inversion features) — retained for provenance, but no longer
  part of the annual Global InMAP design

**Notably absent or still limited:**
- **Global InMAP is integrated and the real-binary POC is complete**, including
  the mixed point/grid input interface. An economy-wide point-plus-grid software
  fixture is now generated, but no real non-power spatial inventory has yet been
  connected; analytical exposure and health results still require sector-specific
  spatialization and simulations that meet strict automatic convergence.
- **The health-impact suite is implemented and tested** (`src/nzk_aphiam/health/`
  and the Peng adapter), including all six CRFs, GEMM, endpoint blocking, age
  restrictions, and both InMAP concentration modes; current source-only exposure
  and missing non-all-cause denominators still limit analytical use.
- **No downscaling module.** CAPSS tidy output has **no 시군구 code** — the workbook doesn't ship one, and no admin-code crosswalk is joined yet.
- **No production-ready non-power EF table yet.** A standardized official
  Handbook VII candidate table and inventory-link table now exist, but
  formula-heavy road/aviation/nonstandard tables, human row review, and annual
  technology/fleet/control shares still need implementation.
- **No team-supplied production scenario definitions.** KEPCO-only proportional
  and whole-unit-retirement proof-of-concept fixtures exist for pipeline testing,
  but both must be replaced by the paired MACRO reference and policy pathways.
- **No `METHODOLOGY.md`** — it's not in the tree.

**Drift worth flagging:** a large empirical branch has grown — `analysis/gwr/`
(descriptive plant-emissions→monitor GWR), `analysis/synthetic_control/`, and Stata
panel `.do` files. It remains a standalone descriptive/causal exercise, not wired
to Global InMAP. The synthetic-control pilot can still accept externally joined
meteorology, but its former KMA acquisition dependency is now archived. Worth
deciding explicitly whether this branch is the validation stage or a separate paper.

Also: `stack_properties.csv` is sourced from **CREA's 2021 South Korea HIA Appendix 2**, not KEPCO directly — coal plants matched (Dangjin, Donghae, Samcheonpo, Yeongheung, Hadong, etc.), with at least one unmatched (Yeongdong unit 2). Zero LNG/CCGT rows.

---

## 2. Huang & Peng (2025) methodology, step by step

**Stage 0 — Scenarios (3, run 2015→2030 in 5-yr steps):** Baseline (sociodemographic change + BAU pollution control, no climate policy); Existing Climate Policies (IRA/BIL + state RPS/EV); All-In (federal + state + city/business, hits −52% GHG vs 2005).

**Stage 1 — Energy & emissions:** GCAM-USA-CGS (fork of GCAM-USA 6.0), 50 states + DC, market-equilibrium IAM. Updated with NREL ATB 2022 renewable costs and EPA non-CO₂ MAC curves. **Outputs CO₂ *and* criteria pollutants natively** (SO₂, NOₓ, NH₃, VOC, primary PM2.5, BC, OC) for power/industry/building/transport at state level; land-use/ag at national level.

**Stage 2 — Downscaling to 12×12 km:** Proportional. Sum NEI 2017 hourly → annual per grid cell → grid share of state total = downscaling factor, held constant 2015–2030. FINN 2017 for fire (held at baseline). Canada/Mexico frozen at 2017 NEI/FINN. Ag primary PM2.5 derived as (BC + OC×1.8)×1.1. Sensitivity: hybrid NEI (power, 12 km) + NEMO (building/transport/industrial non-point, 1 km).

**Stage 3 — Air quality:** InMAP. Variable resolution 1–48 km, 29 vertical layers, ~30 m ground layer. Steady-state reaction-advection-diffusion; WRF-Chem 2005 meteorology preprocessed for >50,000 cells. Simulates primary PM2.5 + secondary (SO₄²⁻, NO₃⁻, NH₄⁺).

**Stage 4 — Exposure:** County-level. InMAP grid < county → population-weighted average across grids; grid > county → same value to all counties inside.

**Stage 5 — Health:** BenMAP-CE v1.5.8, 3,108 counties. `ΔY = (1 − e^(−β·ΔPM)) · Y₀ · Pop`. Krewski et al. 2009 (ACS) log-linear β, constant across years. Y₀ from CDC WONDER (2015) + BenMAP projections (2020–2030). Pop from Census 2010 blocks + Hauer/SEDAC ARIMA SSP-controlled county projections. GEMM as sensitivity (~200% higher).

**Stage 6 — Decomposition:** Sequential factor attribution (population growth → aging → baseline mortality → exposure), exposure split into BAU-control vs climate-policy parts.

**Stage 7 — Sensitivities:** imperfect enforcement (80% realization), stricter pollution control (EF −20%), SSP1/SSP3 mortality rates, isolated state policies (EV vs coal phaseout in CA/TX/PA), cross-state transport (VA held at baseline while 5 neighbors decarbonize), SVI equity split.

---

## 3. Replication table

| # | Step | Peng et al. (US) | Korean equivalent required | In repo? |
|---|---|---|---|---|
| 0 | Scenario design | 3 scenarios (Baseline / Existing / All-In), 2015→2030 | Net Zero Korea MACRO pathway pairs + a no-policy baseline; **must define an explicit baseline** — the marginal estimand requires it | **POC only.** Separate proportional and whole-unit-retirement KEPCO fixture families exist; paired production MACRO pathways are still pending |
| 1 | Energy/activity model | GCAM-USA-CGS, state-level | MACRO (MacroEnergy.jl) + gcam-kaist7 | Integrator and populated non-power conceptual taxonomy exist; **the native activity CSV itself is an external input, not in repo**, so model labels remain provisional |
| 2 | Criteria pollutant emissions | **Native GCAM-USA output** | **Not native** — technology/fuel/process EF × annual GCAM activity, with aggregate CAPSS intensity retained only as fallback/validation | **Framework partial.** The 89-row inventory, 608 legal pollutant-denominator joins, 181 CAPSS links, 912 imported provisional EF rows, and 3,250 official-VII machine-normalized candidates are implemented; nonstandard formula parsing, row approval, and annual weighting remain |
| 3 | Base-year emissions inventory | NEI 2017 (12 km gridded, point sources w/ stack params) | CAPSS | Scraper + tidy processor **yes**; **but no facility coordinates** — CAPSS board exposes no point-source download (flagged in docs as a separate SEMS task) |
| 4 | Spatial downscaling factors | Grid share of state total from NEI, held constant | 시군구 share of national/sido total from CAPSS, held constant | **No.** Blocked: `sub_district_code` is null; needs an admin-code crosswalk |
| 5 | Fire/land-use emissions | FINN 2017, held at baseline | Korean equivalent, or explicit exclusion | **No** — and worth documenting as a scope exclusion |
| 6 | Transboundary/exogenous emissions | Canada+Mexico frozen at NEI 2017 | **China/NE Asia** — far more consequential for Korea than CA/MX are for the US | **No.** This is a real gap, not a formality |
| 7 | Point-source stack parameters | NEI vertical profile | Height, diameter, exit temp, velocity per stack | **Partial.** Coal from CREA 2021 App. 2 (not KEPCO); ≥1 unmatched; **zero LNG/CCGT rows** |
| 8 | Meteorology preprocessing | WRF-Chem 2005 field, prebaked into InMAP | Global InMAP's packaged global meteorology and built-in bias correction; no separate hourly Korean preprocessing in the active design | **Selected and integrated.** The superseded KMA hourly pipeline is archived and is not an InMAP input |
| 9 | Air quality model | InMAP (primary + secondary PM2.5) | **Same** — InMAP / Global InMAP | **MVP integrated; real-binary POC complete.** Pinned installer, mixed point/polygon/COARDS-grid input writer, scenario scoping, all-input cache, output validation, and differencing work end to end. No real non-power spatial file is connected yet. The fixed-iteration POC is diagnostic; strict converged runs remain pending |
| 10 | AQ model evaluation | InMAP vs WRF-Chem vs 2017 obs (Fig. S13) | InMAP vs AirKorea monitors — **this is your stated core contribution** | **Infrastructure yes, evaluation no.** AirKorea QC + crosswalk are built and are the right inputs |
| 11 | Exposure aggregation | Pop-weighted grid→county | Pop-weighted grid→시군구 | **National MVP integrated and exercised.** The POC selected 1,104 Korean cells and Global InMAP `TotalPop` represented 49.76 million people; the resulting concentrations remain diagnostic until strict convergence. District exposure still needs compatible boundaries/allocation |
| 12 | Health impact function | BenMAP-CE 1.5.8, `ΔY=(1−e^(−β·ΔPM))·Y₀·Pop` | Hand-implemented equivalent (BenMAP has no Korea config) | **Yes.** Verified core plus a multi-specification InMAP adapter. The historical 28.74-death POC was produced by the superseded single-CRF adapter and remains a non-converged sign diagnostic; analytical health output requires converged, correctly scoped exposure |
| 13 | CRF (β) | Krewski 2009 ACS log-linear | Same, or a Korea/Asia cohort; GEMM as sensitivity | **Full suite implemented and tested.** Huang–Peng/Krewski primary, age-specific GEMM, Byun, Kim, Korean GUIDE/Hoek, and Lim elderly are evidence-linked and prespecified |
| 14 | Baseline mortality Y₀ | CDC WONDER + BenMAP projections | KOSIS district deaths (`DT_1B82A01`), age-specific (`DT_1B80A18`) | **All-cause yes**, scraped 2001–2024. Age-specific non-accidental and NCD+LRI denominators are not present, so those exact specifications block rather than substitute all-cause |
| 15 | Population + age structure | Census blocks + Hauer/SEDAC SSP ARIMA to 2100 | KOSIS `DT_1B040A3`, `DT_1B04006` | **Yes** |
| 16 | Population **projections** | SSP-controlled county projections through 2030 | KOSIS `DT_1BPB002E` — **ends 2042, not 2050** | **Yes but insufficient.** Your horizon is 2050; needs an extension method |
| 17 | Boundary harmonization | (not needed — stable counties) | 시군구 boundary changes over time — **US has no analogue** | Flagged in docs, not resolved |
| 18 | Decomposition analysis | Sequential 4-factor + exposure split | Same | **Core function implemented and tested; not run in the national thermal MVP** |
| 19 | Sensitivities | Enforcement, EF −20%, SSP1/3, isolated policy, cross-state transport, SVI | Same, minus SVI (use KOSIS SDOH covariates) | Covariates scraped; no sensitivity framework |
| 20 | Cross-boundary transport test | VA held at baseline, 5 neighbors decarbonized | Sido-level analogue + the China question | **No** |

**The short version:** the thermal-power MVP now bridges the former middle gap at
national scale, with explicit existing-site allocation and Global InMAP. A proper
paired reference-policy MACRO deliverable, exhaustive national plant/stack evidence,
district exposure, non-power factor normalization/emissions, foreign emissions, and the broader sensitivity
framework remain substantive gaps; the CAPSS 시군구 code gap still blocks economy-wide
district downscaling.
