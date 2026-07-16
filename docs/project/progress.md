# Research Progress

_As of 16 July 2026_

## 1. Repo state (`yh7649/NZK-APHIAM`, main, 53 commits, v0.1.0 tagged)

Structure is a cookiecutter-data-science layout with Python (77%), R (19%), a bit of Stata. What's actually built:

**Implemented and tested:**
- **KEPCO thermal scrapers/cleaners** for all five subsidiaries (East-West, Western, Southern, South-East, Midland incl. per-site scrapers), plus KHNP generation, combiner, auditor, handoff workbook export
- **CAPSS scraper + processor + power export** (`data/process/capss/processor.py`, `data/process/capss_power_fuel_technology.py`) — tidy long emissions, taxonomy-period flags, pollutant coverage metadata, 2016--2023 public/private power fuel × official CAPSS technology tables
- **MACRO/GCAM integrator** (`data/process/macro/integrator.py`) — exactly the EF-derivation logic (CAPSS emissions ÷ GCAM activity → EF → × projected activity); the separate 2021 KEPCO-EF × MACRO-generation validation module is implemented but still requires the external MACRO generation file
- **AirKorea hourly QC pipeline** (2001–2025 finalized archives, station crosswalk, anomaly model, spatial validation)
- **KMA weather** (ASOS, radiosonde, stability indices, wind profiler; mixing height + inversion features)
- **KOSIS health/demographic panel** (monthly deaths by 시군구, cause deaths, population, age structure, projections, ~20 SDOH covariates)
- **Crosswalks**: plant location/dates, retirement dates, stack properties, technology mapping — all with evidence files

**Notably absent:**
- **No InMAP anywhere.** No module, no config, no docs.
- **No health-impact function code.** Krewski 2009, Burnett 2018 (GEMM), WHO AQG 2024 PDFs sit in `docs/references/literature/`, but nothing implements Equation 2.
- **No downscaling module.** CAPSS tidy output has **no 시군구 code** — the workbook doesn't ship one, and no admin-code crosswalk is joined yet.
- **No scenario definitions** (no baseline/policy scenario configs).
- **No `METHODOLOGY.md`** — it's not in the tree.

**Drift worth flagging:** a large empirical branch has grown — `analysis/gwr/` (descriptive plant-emissions→monitor GWR), `analysis/synthetic_control/`, Stata panel `.do` files. Reading it charitably, this is the validation layer (AirKorea + KMA are exactly what you'd need to validate a transport model), but right now it's a standalone descriptive/causal exercise, not wired to any dispersion model. Worth deciding explicitly whether it's the validation stage or a separate paper.

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
| 1 | Energy/activity model | GCAM-USA-CGS, state-level | MACRO (MacroEnergy.jl) + gcam-kaist7 | Integrator exists; **the activity CSV itself is an external input, not in repo**. Non-power scope still TBC with MACRO team |
| 2 | Criteria pollutant emissions | **Native GCAM-USA output** | **Not native** — must derive EFs = CAPSS sector emissions ÷ gcam-kaist7 activity | **Yes**, `process/macro/integrator.py` + diagnostics. The single biggest structural deviation |
| 3 | Base-year emissions inventory | NEI 2017 (12 km gridded, point sources w/ stack params) | CAPSS | Scraper + tidy processor **yes**; **but no facility coordinates** — CAPSS board exposes no point-source download (flagged in docs as a separate SEMS task) |
| 4 | Spatial downscaling factors | Grid share of state total from NEI, held constant | 시군구 share of national/sido total from CAPSS, held constant | **No.** Blocked: `sub_district_code` is null; needs an admin-code crosswalk |
| 5 | Fire/land-use emissions | FINN 2017, held at baseline | Korean equivalent, or explicit exclusion | **No** — and worth documenting as a scope exclusion |
| 6 | Transboundary/exogenous emissions | Canada+Mexico frozen at NEI 2017 | **China/NE Asia** — far more consequential for Korea than CA/MX are for the US | **No.** This is a real gap, not a formality |
| 7 | Point-source stack parameters | NEI vertical profile | Height, diameter, exit temp, velocity per stack | **Partial.** Coal from CREA 2021 App. 2 (not KEPCO); ≥1 unmatched; **zero LNG/CCGT rows** |
| 8 | Meteorology preprocessing | WRF-Chem 2005 field, prebaked into InMAP | Korean met field for InMAP variable grid — Global InMAP ships coarse global met | **No InMAP work.** KMA scrapers exist but feed the GWR branch, not a dispersion model |
| 9 | Air quality model | InMAP (primary + secondary PM2.5) | **Same** — InMAP / Global InMAP | **No.** Nothing in `src/` |
| 10 | AQ model evaluation | InMAP vs WRF-Chem vs 2017 obs (Fig. S13) | InMAP vs AirKorea monitors — **this is your stated core contribution** | **Infrastructure yes, evaluation no.** AirKorea QC + crosswalk are built and are the right inputs |
| 11 | Exposure aggregation | Pop-weighted grid→county | Pop-weighted grid→시군구 | **No.** Needs 시군구 boundaries + gridded population |
| 12 | Health impact function | BenMAP-CE 1.5.8, `ΔY=(1−e^(−β·ΔPM))·Y₀·Pop` | Hand-implemented equivalent (BenMAP has no Korea config) | **No code.** Only PDFs in `docs/references/literature/` |
| 13 | CRF (β) | Krewski 2009 ACS log-linear | Same, or a Korea/Asia cohort; GEMM as sensitivity | Papers collected (Krewski, Burnett GEMM, WHO 2024). Not implemented |
| 14 | Baseline mortality Y₀ | CDC WONDER + BenMAP projections | KOSIS district deaths (`DT_1B82A01`), age-specific (`DT_1B80A18`) | **Yes**, scraped 2001–2024 |
| 15 | Population + age structure | Census blocks + Hauer/SEDAC SSP ARIMA to 2100 | KOSIS `DT_1B040A3`, `DT_1B04006` | **Yes** |
| 16 | Population **projections** | SSP-controlled county projections through 2030 | KOSIS `DT_1BPB002E` — **ends 2042, not 2050** | **Yes but insufficient.** Your horizon is 2050; needs an extension method |
| 17 | Boundary harmonization | (not needed — stable counties) | 시군구 boundary changes over time — **US has no analogue** | Flagged in docs, not resolved |
| 18 | Decomposition analysis | Sequential 4-factor + exposure split | Same | **No** |
| 19 | Sensitivities | Enforcement, EF −20%, SSP1/3, isolated policy, cross-state transport, SVI | Same, minus SVI (use KOSIS SDOH covariates) | Covariates scraped; no sensitivity framework |
| 20 | Cross-boundary transport test | VA held at baseline, 5 neighbors decarbonized | Sido-level analogue + the China question | **No** |

**The short version:** stages 0, 3(spatial), 4, 8–13, 18–20 are unbuilt. Everything in the repo today is stage 1–2 inputs and the health *denominators*. The pipeline has strong front and back ends and an empty middle — InMAP is the load-bearing missing piece, and the 시군구 code gap in CAPSS is the near-term blocker that quietly stops stages 4 and 11 too.
