# Research Progress

_As of 22 July 2026_

## 0. Korean thermal-power replication MVP

An executable screening-level chain now links the local observed EPSIS 2021
thermal generation handoff to the single available 2030 MACRO pathway, allocates
generation to the canonical processed KEPCO thermal fleet plus explicit real-site
province coverage, applies the existing generation-weighted KEPCO EFs, generates
Global InMAP inputs, aggregates national exposure, and adapts real exposure to the
existing health model. The configuration, commands, assumptions, and limitations
are documented in [`docs/methods/peng_replication_mvp.md`](../methods/peng_replication_mvp.md).

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

An explicitly requested diagnostic health post-processing pass confirms the expected
sign. The MACRO inventory contains 50.14 thousand tonnes/year more NOx and 12.53
thousand tonnes/year more SOx than the observed inventory, and its POC concentration
is higher. Using 2030 projected Korean population age 30+, 2024 national age-specific
mortality rates held constant, and the Krewski central CRF gives **28.74 additional
annual deaths** under MACRO relative to observed 2021 (CRF-coefficient-only interval:
19.34--37.95). The scenario totals are 89.61 versus 60.88 attributable deaths. These
numbers inherit the fixed-iteration non-convergence, overstated thermal generation,
omitted primary PM2.5/NH3/VOC, stack and allocation imputations, national averaging,
and US-cohort CRF limitations. They are retained only as sign-and-plumbing diagnostics;
the normal `health_impacts.csv` remains absent and analytical use is prohibited.

## 1. Repo state (`yh7649/NZK-APHIAM`, main, 53 commits, v0.1.0 tagged)

Structure is a cookiecutter-data-science layout with Python (77%), R (19%), a bit of Stata. What's actually built:

**Implemented and tested:**
- **KEPCO thermal scrapers/cleaners** for all five subsidiaries (East-West, Western, Southern, South-East, and Midland); Midland now uses KOMIPO's checksum-verified direct 2024--2025 monthly mass workbook joined to its existing public monthly generation, with the superseded concentration/flow estimator archived; plus KHNP generation, combiner, auditor, handoff workbook export
- **CAPSS scraper + processor + power export** (`data/process/capss/processor.py`, `data/process/capss_power_fuel_technology.py`) — tidy long emissions, taxonomy-period flags, pollutant coverage metadata, 2016--2023 public/private power fuel × official CAPSS technology tables
- **Non-power inventory and EF evidence** (`data/process/nonpower_sector_inventory.py`, `data/process/nonpower_emission_factors.py`, `data/scrape/capss/nonpower_emission_factors.py`, `docs/references/nonpower_emissions/`) — 86 substantive activities; 161 native-CAPSS crosswalk rows; pollutant/source/denominator registries; 912 imported candidate EF records mapped into 2,067 inventory links covering 41 activities; and an official Handbook VII first-pass scrape covering 327 PDF pages, 83 direct-emission activities, and 125 factor/speciation tables. All 887 Handbook VI mirror transcriptions and all 25 literature rows remain `production_ready=false`; row-level VII normalization and review are pending
- **MACRO/GCAM integrator** (`data/process/macro/integrator.py`) — exactly the EF-derivation logic (CAPSS emissions ÷ GCAM activity → EF → × projected activity); the separate 2021 KEPCO-EF × MACRO-generation validation module is implemented but still requires the external MACRO generation file
- **AirKorea hourly QC pipeline** (2001–2025 finalized archives, station crosswalk, anomaly model, spatial validation)
- **KOSIS health/demographic panel** (monthly deaths by 시군구, cause deaths, population, age structure, projections, ~20 SDOH covariates)
- **Crosswalks**: plant location/dates, retirement dates, stack properties, technology mapping — all with evidence files
- **KEPCO external EF validation** permits percent-error statistics only for
  reviewed exact plant/unit/year comparisons, separates MOTIE fuel-fleet checks
  from plant validation, and exposes contextual/noncomparable literature gaps
  without automatic fuel-technology matching

**Archived as superseded:**

- **Midland concentration/flow mass estimator and per-site air-status scrapers**
  — retained for provenance after KOMIPO supplied direct monthly pollutant mass
- **KMA hourly weather** (ASOS, radiosonde, stability indices, Wind Profiler;
  mixing-height and inversion features) — retained for provenance, but no longer
  part of the annual Global InMAP design

**Notably absent or still limited:**
- **Global InMAP is integrated and the real-binary POC is complete**, but analytical exposure and health results still require both simulations to meet strict automatic convergence.
- **The health-impact function is implemented and tested** (`src/nzk_aphiam/health/`); district exposure and boundary harmonization remain unavailable.
- **No downscaling module.** CAPSS tidy output has **no 시군구 code** — the workbook doesn't ship one, and no admin-code crosswalk is joined yet.
- **No standardized non-power EF value table yet.** The sector/source/denominator
  framework is complete, but CAPSS Handbook VII factors and annual
  technology/fleet/control shares still need extraction and implementation.
- **No scenario definitions** (no baseline/policy scenario configs).
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
| 0 | Scenario design | 3 scenarios (Baseline / Existing / All-In), 2015→2030 | Net Zero Korea MACRO pathway pairs + a no-policy baseline; **must define an explicit baseline** — the marginal estimand requires it | **No.** No scenario configs anywhere |
| 1 | Energy/activity model | GCAM-USA-CGS, state-level | MACRO (MacroEnergy.jl) + gcam-kaist7 | Integrator and populated non-power conceptual taxonomy exist; **the native activity CSV itself is an external input, not in repo**, so model labels remain provisional |
| 2 | Criteria pollutant emissions | **Native GCAM-USA output** | **Not native** — technology/fuel/process EF × annual GCAM activity, with aggregate CAPSS intensity retained only as fallback/validation | **Framework partial.** The 86-row inventory, 589 legal pollutant-denominator joins, 161 CAPSS links, 912 provisional EF rows, and official-VII page/table scrape are implemented; VII row normalization, approval, and annual weighting remain |
| 3 | Base-year emissions inventory | NEI 2017 (12 km gridded, point sources w/ stack params) | CAPSS | Scraper + tidy processor **yes**; **but no facility coordinates** — CAPSS board exposes no point-source download (flagged in docs as a separate SEMS task) |
| 4 | Spatial downscaling factors | Grid share of state total from NEI, held constant | 시군구 share of national/sido total from CAPSS, held constant | **No.** Blocked: `sub_district_code` is null; needs an admin-code crosswalk |
| 5 | Fire/land-use emissions | FINN 2017, held at baseline | Korean equivalent, or explicit exclusion | **No** — and worth documenting as a scope exclusion |
| 6 | Transboundary/exogenous emissions | Canada+Mexico frozen at NEI 2017 | **China/NE Asia** — far more consequential for Korea than CA/MX are for the US | **No.** This is a real gap, not a formality |
| 7 | Point-source stack parameters | NEI vertical profile | Height, diameter, exit temp, velocity per stack | **Partial.** Coal from CREA 2021 App. 2 (not KEPCO); ≥1 unmatched; **zero LNG/CCGT rows** |
| 8 | Meteorology preprocessing | WRF-Chem 2005 field, prebaked into InMAP | Global InMAP's packaged global meteorology and built-in bias correction; no separate hourly Korean preprocessing in the active design | **Selected and integrated.** The superseded KMA hourly pipeline is archived and is not an InMAP input |
| 9 | Air quality model | InMAP (primary + secondary PM2.5) | **Same** — InMAP / Global InMAP | **MVP integrated; real-binary POC complete.** Pinned installer, input writer, runner, cache, output validation, and differencing work end to end. The fixed-iteration POC is diagnostic; strict converged runs remain pending |
| 10 | AQ model evaluation | InMAP vs WRF-Chem vs 2017 obs (Fig. S13) | InMAP vs AirKorea monitors — **this is your stated core contribution** | **Infrastructure yes, evaluation no.** AirKorea QC + crosswalk are built and are the right inputs |
| 11 | Exposure aggregation | Pop-weighted grid→county | Pop-weighted grid→시군구 | **National MVP integrated and exercised.** The POC selected 1,104 Korean cells and Global InMAP `TotalPop` represented 49.76 million people; the resulting concentrations remain diagnostic until strict convergence. District exposure still needs compatible boundaries/allocation |
| 12 | Health impact function | BenMAP-CE 1.5.8, `ΔY=(1−e^(−β·ΔPM))·Y₀·Pop` | Hand-implemented equivalent (BenMAP has no Korea config) | **Yes.** Verified `health/` module plus a thermal-MVP adapter. An opt-in non-converged POC pass gives 28.74 additional annual deaths under MACRO, retained only as a diagnostic; analytical health output still requires converged exposure |
| 13 | CRF (β) | Krewski 2009 ACS log-linear | Same, or a Korea/Asia cohort; GEMM as sensitivity | **Krewski implemented and tested** from evidence-linked parameters; GEMM remains deferred |
| 14 | Baseline mortality Y₀ | CDC WONDER + BenMAP projections | KOSIS district deaths (`DT_1B82A01`), age-specific (`DT_1B80A18`) | **Yes**, scraped 2001–2024 |
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
