# Paste-ready Claude PPTX prompt: Global InMAP module

Copy everything below this sentence into Claude PPTX. The prompt is
self-contained; Claude does not need access to the NZK-APHIAM repository.

---

## Operating constraint

Create the slides using only the information in this prompt.

- Do not attempt to open repository files, local paths, attachments, or links.
- Do not browse for additional facts.
- Do not ask for missing project documentation.
- Do not invent data, results, maps, numerical estimates, or implementation
  status.
- The citations below are supplied so they can be placed in speaker notes;
  accessing the cited sources is not required.
- If a factual detail is not supplied below, omit it or label it `to be
  finalized by the project team`.

## Assignment

Create a coherent 9-slide, 16:9 presentation section that:

1. introduces the Intervention Model for Air Pollution (InMAP);
2. explains why the project uses Global InMAP;
3. explains how point and gridded emissions represent plant and non-plant
   sources;
4. explains the Korea-specific PM2.5 bias correction now under development;
5. shows where InMAP sits within the full NZK-APHIAM research pipeline; and
6. distinguishes completed infrastructure from work still in progress.

The audience is academic and technical-policy researchers who understand
emissions and fine particulate matter but may not know reduced-complexity
air-quality models.

The communication job is:

> By the end, the audience should understand that Global InMAP is the
> atmospheric bridge between spatially resolved energy-scenario emissions and
> population exposure in NZK-APHIAM; that it combines stack-resolved plant
> sources with gridded or feature-based non-plant sources; and that a
> Korea-specific, grid-cell-level additive correction is being developed to
> align historical absolute PM2.5 concentrations with observations without
> overwriting InMAP's modeled scenario differences.

This is a methods-and-workflow section, not a results section. Do not show
concentration, exposure, mortality, or avoided-death estimates. A
fixed-iteration proof of concept has tested the plumbing, but its values are
not analytical results and must not appear in the slides.

## Self-contained project context

### What the project is doing

NZK-APHIAM studies how Korean energy-transition scenarios affect air-pollutant
emissions, annual PM2.5 exposure, and health.

The intended end-to-end pipeline is:

```text
Energy scenarios
→ plant and non-plant activity
→ pollutant emissions
→ spatial point and gridded inventories
→ Global InMAP
→ Korea-specific PM2.5 bias correction
→ population-weighted exposure
→ health-impact calculations
```

The main upstream data roles are:

- KEPCO data describe the Korean thermal-power fleet, generation, and observed
  pollutant emissions.
- EPSIS provides observed national generation used in the historical
  comparison.
- MACRO and GCAM-KAIST provide or will provide scenario activity pathways.
- Emission factors translate activity into annual pollutant mass.
- Plant coordinates and stack parameters locate and vertically characterize
  power emissions.
- CAPSS and other sector inventories are being developed for non-power
  emissions.
- AirKorea provides finalized ground-monitor observations.
- A satellite-derived surface PM2.5 product will supply spatially complete
  historical observation coverage; the exact product and fusion protocol have
  not yet been finalized.
- Global InMAP's `TotalPop` field supports population weighting on its model
  grid.
- KOSIS population and mortality inputs, combined with
  concentration-response functions, support the downstream health module.

The present screening workflow compares historical observed activity with a
future scenario while the production paired reference-policy scenarios are
still pending. Do not describe the current comparison as a causal net-zero
effect.

### What InMAP is

InMAP stands for the Intervention Model for Air Pollution.

InMAP is a reduced-complexity, mechanistic air-quality model for fine
particulate matter (PM2.5). It estimates how specified emissions contribute to
annual-average ground-level PM2.5 concentration.

It is mechanistic because it represents:

- spatially located emissions;
- elevated stack release;
- atmospheric advection and mixing;
- chemical transformation;
- deposition and other removal; and
- formation of primary and secondary PM2.5 components.

It is reduced-complexity because it uses an annual steady-state representation
and annual-average transport, reaction, and removal parameters preprocessed
from a comprehensive chemical transport model (CTM). It does not rerun
hour-by-hour meteorology and full atmospheric chemistry for every scenario.

The tradeoff is speed for detail. InMAP is appropriate for screening many
policy scenarios at spatial resolution useful for exposure analysis. It is not
a substitute for a full CTM when the research question requires daily,
seasonal, episode-level, or highly detailed chemical predictions.

Reduced-complexity does not mean spatially crude. InMAP uses a
variable-resolution grid. Grid cells are finer in more densely populated areas
and coarser in less populated areas, improving exposure resolution while
controlling computation time.

### Why this project uses Global InMAP

Global InMAP extends the InMAP framework from a national domain to a
global-through-urban domain. This matters for Korea because atmospheric
transport is not bounded by national borders and because the project needs a
consistent atmospheric framework without building a new Korea-specific CTM
from scratch.

The NZK-APHIAM workflow currently pins:

- InMAP executable release: `v1.9.6`;
- official Global InMAP model/evaluation data: `v1.1.0`;
- a supplied static global variable-resolution grid;
- packaged annual atmospheric fields derived from a global CTM; and
- the supplied global population field used as `TotalPop`.

The supplied Global InMAP population field is for exposure weighting. It does
not supply the Korean mortality data used by the health module. Mortality data
come separately from KOSIS.

Use this exact visible attribution:

> The Global InMAP implementation used in this project is currently being
> developed with our mentor, Jinyu Shiwang.

Preserve the historical distinction in the speaker notes:

- Tessum and coauthors introduced InMAP in 2017.
- Thakrar and coauthors developed and evaluated the published Global InMAP
  extension in 2022.
- Jinyu Shiwang is mentoring and developing the Global InMAP application used
  in this research project.

Do not say that Jinyu Shiwang invented InMAP or was the sole original developer
of the published Global InMAP model.

### Emissions accepted by the model

The emissions fields used by this workflow are:

```text
VOC | NOx | NH3 | SOx | PM2_5
```

Their roles are:

- `PM2_5`: directly emitted primary PM2.5;
- `SOx`: precursor of particulate sulfate;
- `NOx`: precursor of particulate nitrate;
- `NH3`: precursor of particulate ammonium and a participant in inorganic
  aerosol formation; and
- `VOC`: precursor of secondary organic aerosol.

Each model run represents one scenario and one year.

#### Plant and facility point inputs

The power-sector inventory is represented as point features at known plant or
unit coordinates.

Each point carries non-negative annual pollutant mass, normally in `kg/year`.
When all four stack parameters are available, InMAP treats it as an elevated
source:

```text
height   = stack height in meters
diam     = stack diameter in meters
temp     = exit temperature in kelvin
velocity = exit velocity in meters per second
```

The project generates these point inventories from scenario-specific plant
activity, emission factors, coordinates, and stack information.

#### Non-plant and supplemental spatial inputs

Non-power emissions may enter in either of two broad spatial forms:

1. feature-based emissions in a shapefile:
   - points for individual facilities;
   - lines for sources such as roads;
   - polygons for area sources; or
2. gridded emissions in a COARDS NetCDF-3 file:
   - one-dimensional latitude and longitude coordinates;
   - floating-point pollutant variables arranged as `[lat, lon]`; and
   - non-negative annual pollutant mass totals for each grid cell.

Gridded input values are emissions mass, not PM2.5 concentration and not mass
density.

Distributed sources such as transport, buildings, agriculture, and diffuse
industrial activity are natural candidates for gridded representation.
Individual non-power facilities can remain point sources when coordinates and
source information are available.

Plant and non-plant inventories enter the same scenario-year Global InMAP run.
Their inventory boundaries must be mutually exclusive. A plant already
represented in the generated power shapefile must not appear again in a
supplemental inventory.

Every selected emissions file and its metadata are validated and recorded in a
run manifest. The model-run cache depends on the executable, configuration, and
every emissions dependency, so changing an input forces a new model run.

### What InMAP produces

InMAP produces annual-average ground-level concentration by model grid cell in
`µg/m³`.

The project requests these five PM2.5 components:

```text
PrimaryPM25 = directly emitted primary PM2.5 concentration
pSO4        = particulate sulfate concentration
pNO3        = particulate nitrate concentration
pNH4        = particulate ammonium concentration
SOA         = secondary organic aerosol concentration
```

Total PM2.5 is defined as:

```text
TotalPM25 = PrimaryPM25 + pSO4 + pNO3 + pNH4 + SOA
```

The workflow verifies that `TotalPM25` equals the sum of those components. It
also checks that scenario output grids and coordinate systems match before
taking spatial differences.

The concentration-difference sign convention is:

```text
reference or historical minus policy or future
```

A positive concentration difference means the policy or future case is
cleaner. A negative difference means it has higher modeled concentration.

After model output, Korean cells are selected using the national boundary and
grid-cell centroids. Population-weighted exposure uses the model's `TotalPop`
field. Uniform population weights are not allowed.

InMAP produces concentration, not mortality. Exposure and health calculations
occur downstream.

### Current inventory limitations

The current central thermal inventory has defensible annual NOx and SOx
emission factors.

It does not yet have documented factors for primary PM2.5, NH3, and VOC across
the full inventory. Those fields are therefore omitted from the central
thermal run rather than filled with undocumented assumptions.

If a model input field is zero because a pollutant is omitted, that means:

```text
not represented in this inventory
```

It does not mean:

```text
known to be zero in the real world
```

The system can accept production non-power spatial inputs, but a complete,
production-ready non-power inventory has not yet been connected.

### Why Korea-specific bias correction is needed

Published evaluation found that Global InMAP was biased low for absolute
annual-average total PM2.5 when compared with observations.

In the published global evaluation:

- normalized mean bias for total PM2.5 was `−60%`;
- normalized mean error was `62%`; and
- `R²` was `0.33`.

These are global evaluation statistics, not Korean calibration values. Do not
display or describe `−60%` as the Korean bias. Bias varies by place, pollutant
component, emissions inventory, and model configuration.

The published evaluation also found especially low predictions in some heavily
polluted regions of Asia. Possible reasons include incomplete emission
inventories, missing or underestimated primary PM2.5 and precursor sources,
annual-average treatment of episodic events, simplified chemistry, and bias
inherited from parent-model inputs.

The Korea-specific correction is intended to anchor absolute historical PM2.5
to Korean evidence while leaving InMAP responsible for the modeled response to
scenario emissions.

### Observational information for the Korea correction

The project will construct one harmonized historical surface PM2.5 field using:

- a satellite-derived surface PM2.5 estimate for spatial coverage; and
- quality-controlled AirKorea ground-monitor measurements for local
  ground-level anchoring.

AirKorea publishes finalized hourly monitoring-station observations. The
project has a pipeline covering the 2001–2025 finalized archives, including a
station crosswalk, anomaly checks, and spatial validation.

Do not say that satellites directly measure ground-level PM2.5 mass
concentration. Use the phrase:

```text
satellite-derived surface PM2.5 estimate
```

Do not use:

```text
satellite ground measurement
```

The exact satellite-derived product, historical calibration period, fusion
method, interpolation rule, and validation split are still being finalized.
Do not invent them.

The observed sources must be harmonized into one defensible surface. Do not
tell the audience that two unmatched rasters are simply averaged. Do not
double-count monitor information if the chosen satellite-derived product
already incorporates ground monitors.

### Exact Korea bias-correction method

Use an additive correction that is unique to every model grid cell.

For each grid cell `g`, calculate:

```text
b_g = C_obs,hist,g - C_InMAP,hist,g
```

where:

- `C_obs,hist,g` is harmonized observed historical annual PM2.5 concentration
  in cell `g`;
- `C_InMAP,hist,g` is modeled historical annual PM2.5 concentration in the
  same cell; and
- `b_g` is that cell's additive correction.

Then correct any scenario `s` in that grid cell:

```text
C_corrected,s,g = C_InMAP,s,g + b_g
```

The sign is important. If observed concentration is `24 µg/m³` and modeled
historical concentration is `20 µg/m³`, then:

```text
b_g = 24 - 20 = +4 µg/m³
```

If the scenario model output is `16 µg/m³`, the corrected value is:

```text
C_corrected,s,g = 16 + 4 = 20 µg/m³
```

This is an additive cell-specific offset, not a multiplicative scaling factor
and not one national correction value.

Before calculating the residual, modeled and observed values must use:

- the same units;
- the same annual or multi-year averaging period;
- the same grid definition;
- the same spatial support; and
- a compatible source scope.

### What the correction changes—and what it preserves

Apply the same fixed `b_g` to the reference and policy scenario in each cell:

```text
C_corrected,ref,g    = C_InMAP,ref,g    + b_g
C_corrected,policy,g = C_InMAP,policy,g + b_g
```

The within-cell scenario difference is therefore preserved:

```text
C_corrected,ref,g - C_corrected,policy,g
  = C_InMAP,ref,g - C_InMAP,policy,g
```

The correction changes the absolute concentration baseline. It does not
rewrite the emissions-driven reference-policy difference produced by InMAP.

This is consistent with a published InMAP policy-analysis precedent that used
the historical observed-minus-modeled difference as a fixed local correction
across scenarios so modeled absolute differences remained unchanged.

The correction must be estimated from a defensible all-source historical
baseline. It must not be estimated by subtracting a plant-only modeled
contribution from observed ambient PM2.5. That plant-only residual would also
contain omitted non-plant emissions, natural sources, transboundary pollution,
and background concentration, so it would not be a pure estimate of model
bias.

Where possible:

- estimate the correction using one set of years or monitors;
- evaluate it on held-out years or monitors;
- report corrected and uncorrected outputs as a sensitivity; and
- do not call fit to the same observations used to construct the correction
  independent validation.

### Current implementation status

Use the following status language exactly.

Integrated and tested:

- a pinned Global InMAP executable and official model data;
- static global-grid configuration;
- elevated power-point input writer;
- supplemental point, line, polygon, and COARDS-grid input validation;
- scenario- and year-specific input selection;
- input manifests and dependency-aware run caching;
- output component-sum checks;
- matched-grid scenario differencing;
- South-Korea cell selection;
- national `TotalPop`-weighted exposure aggregation; and
- an end-to-end fixed-iteration real-binary proof of concept.

In progress or still required:

- strict automatically converged analytical Global InMAP runs;
- production paired reference-policy energy scenarios;
- a complete production non-power spatial emissions inventory;
- an all-source historical baseline suitable for calibration;
- selection and harmonization of the satellite-derived PM2.5 product;
- implementation of the Korea grid-cell bias correction;
- held-out Korean validation; and
- district-level exposure allocation.

The fixed-iteration proof of concept tested code paths only. It is
non-converged, and health output from it is not analytically usable.

## Citation library for speaker notes

Use the following citation text verbatim where relevant. Claude does not need
to open these sources.

### InMAP origin

```text
Tessum, C. W., Hill, J. D., & Marshall, J. D. (2017).
InMAP: A model for air pollution interventions.
PLOS ONE, 12(4), e0176131.
https://doi.org/10.1371/journal.pone.0176131
```

### Global InMAP

```text
Thakrar, S. K., Tessum, C. W., Apte, J. S., Balasubramanian, S.,
Millett, D. B., Pandis, S. N., Marshall, J. D., & Hill, J. D. (2022).
Global, high-resolution, reduced-complexity air quality modeling for
PM2.5 using InMAP (Intervention Model for Air Pollution).
PLOS ONE, 17(5), e0268714.
https://doi.org/10.1371/journal.pone.0268714
```

### Official model documentation

```text
InMAP authors. InMAP Quickstart: About InMAP and model inputs.
https://inmap.run/docs/quickstart/
```

### Additive bias-correction precedent

```text
Polonik, P., Ricke, K., Reese, S., & Burney, J. (2023).
Air quality equity in US climate policy.
Proceedings of the National Academy of Sciences, 120(26), e2217124120.
https://doi.org/10.1073/pnas.2217124120
```

### Project mentor

```text
Jinyu Shiwang. Research profile: energy-system modeling, InMAP,
decarbonization, air-pollution exposure, and health.
https://jinyu-shiwang.com/
Project-role wording supplied by the NZK-APHIAM research team.
```

### Project-specific methodology and status

```text
NZK-APHIAM research team. Global InMAP workflow, emissions interface,
Korea bias-correction design, and implementation status.
Internal project methodology; status supplied in this presentation brief,
27 July 2026.
```

### AirKorea observations

```text
Korea Environment Corporation, AirKorea.
Finalized hourly monitoring-station air-quality archives.
NZK-APHIAM uses the 2001–2025 finalized archives with station crosswalk,
quality control, anomaly checks, and spatial validation.
```

### Satellite-derived PM2.5

Use this placeholder until the project team chooses the product:

```text
[To be finalized by project team]
Satellite-derived historical surface PM2.5 product, version, years,
ground-monitor integration, and validation documentation.
```

## Non-negotiable scientific language

The slides and notes must obey these rules:

1. Call InMAP a `reduced-complexity mechanistic air-quality model`.
2. Do not call it a statistical exposure model.
3. Describe outputs as annual-average PM2.5 concentration.
4. Do not imply hourly, seasonal, or pollution-episode prediction.
5. Explain that the variable-resolution grid can still provide fine spatial
   resolution in populated areas.
6. Distinguish emissions inputs from concentration outputs.
7. Distinguish primary PM2.5 emissions from secondary PM2.5 formed from
   precursors.
8. Describe plant sources as points and distributed non-plant sources as
   grids, while noting that non-power points, lines, and polygons are also
   supported.
9. Describe grid values as annual emissions mass per cell.
10. Do not present zero-valued omitted pollutants as known real-world zeros.
11. Say that Global InMAP tends to underestimate absolute total PM2.5 in
    published evaluation; do not say every Korean grid cell is underestimated.
12. If the global `−60%` normalized mean bias is shown, label it `published
    global evaluation—not the Korean correction magnitude`.
13. Say `satellite-derived surface PM2.5 estimate` and `AirKorea ground
    monitors`.
14. Do not invent the satellite product or calibration years.
15. Use `observed − modeled` for the correction.
16. Add the resulting offset to the model output.
17. Describe the offset as unique to each grid cell and additive.
18. Show that the same offset cancels from the reference-policy difference.
19. Do not estimate the correction from a plant-only contribution.
20. Place correction after Global InMAP and before exposure in the pipeline.
21. State that InMAP produces concentration, while exposure and health are
    downstream.
22. Label the Korea correction and production non-power inventory `in
    progress`.
23. Do not present proof-of-concept values as results.
24. Credit Jinyu Shiwang for the project implementation without replacing the
    original InMAP and Global InMAP authorship.

## Visual and writing direction

- If inserting this section into an existing deck, inherit the existing
  master, typography, palette, footer, and page-number treatment.
- If no deck is supplied, use a restrained academic atmospheric-science style:
  warm white background, deep navy text, desaturated teal for InMAP and the
  main pipeline, muted rust for emissions, cobalt for observations, and amber
  only for caveats or work in progress.
- Use at least 35 pt for slide titles, 24 pt for subheads, and 16 pt for body
  text. Keep titles on one line.
- Use takeaway titles that communicate the slide's conclusion.
- Prefer one dominant composition per slide.
- Avoid dashboards, card grids, pills, decorative icons, and generic factory,
  satellite, cloud, or medical stock photography.
- Use native PowerPoint shapes for simple flows and equations.
- Create connectors before nodes so arrows remain behind shapes.
- Keep all connectors directional from left to right.
- Use a real sourced map only if one is supplied. Otherwise use a clearly
  labeled conceptual Korea outline or grid.
- Label every invented raster or concentration surface
  `schematic—not data`.
- Do not fabricate a heat map that could be mistaken for a model result.
- Define fine particulate matter (PM2.5), volatile organic compounds (VOC),
  chemical transport model (CTM), and COARDS on first use.
- Use `µg/m³` for concentration, `kg/year` for the generated point inventory,
  and `annual emissions mass per grid cell` for gridded input.
- Put a `[Sources]` block at the end of every slide's speaker notes using the
  supplied citation text.

## Slide-by-slide specification

### Slide 1 — Global InMAP connects emissions scenarios to the air people breathe

**Narrative job:** Open the section and establish why atmospheric modeling is
needed.

**Visible content:**

- Section label: `Atmospheric dispersion and exposure`
- Title: `Global InMAP connects emissions scenarios to the air people breathe`
- Subtitle: `A fast, spatially explicit bridge from plant and non-plant
  emissions to annual PM2.5 concentration`

**Visual:** Use a minimal conceptual Korea silhouette. Show a few plant points
and a faint grid transitioning into a concentration surface. Label it
`schematic—not data`.

**Speaker notes to include:**

Emissions totals alone cannot show where pollution travels, what secondary
particles form, or which populations are exposed. NZK-APHIAM therefore places
an atmospheric model between the emissions inventory and the exposure and
health modules. Global InMAP takes spatially located annual emissions and
estimates annual-average ground-level PM2.5 concentration for each model grid
cell. This section explains the model, the mix of point and gridded inputs, the
Korea-specific correction under development, and the model's role in the full
research pipeline.

**Speaker-note sources:**

```text
[Sources]
- Tessum, Hill, and Marshall (2017), InMAP, DOI: 10.1371/journal.pone.0176131
- NZK-APHIAM research team, internal Global InMAP methodology, 27 July 2026
```

### Slide 2 — InMAP keeps the mechanisms needed for annual PM2.5 policy screening

**Narrative job:** Define reduced-complexity modeling and its tradeoff.

**Visible content:**

Use this central statement:

> InMAP solves an annual steady-state representation of pollutant transport,
> reaction, and removal on a variable-resolution grid.

Use a two-column comparison:

| InMAP retains | InMAP simplifies |
|---|---|
| Spatial emissions and stack release | Hourly and seasonal variation |
| Advection, mixing, chemistry, and deposition | Full chemical mechanisms |
| Primary and secondary PM2.5 components | Repeated meteorological simulation |
| Finer cells in denser population centers | The computational cost of a full CTM |

Bottom takeaway:

> The tradeoff is speed for detail: useful for screening many scenarios, but
> not a replacement for a full chemical transport model.

**Visual:** Let the comparison dominate. Add a narrow variable-grid motif
along one edge rather than multiple decorative panels.

**Speaker notes to include:**

InMAP is mechanistic: it represents emissions, elevated releases, atmospheric
transport, chemical conversion, and removal. Its main simplification is
temporal and chemical detail. Instead of rerunning a complete CTM hour by hour,
it uses annual-average parameters preprocessed from a CTM and solves for an
annual steady state. This makes repeated scenario analysis practical. The
variable-resolution grid places smaller cells in more populated areas, so
reduced complexity does not mean uniformly coarse geography. The model should
be interpreted as an annual policy-screening tool, not as a daily forecast or
episode model.

**Speaker-note sources:**

```text
[Sources]
- Tessum, Hill, and Marshall (2017), InMAP, DOI: 10.1371/journal.pone.0176131
- InMAP authors, official Quickstart, https://inmap.run/docs/quickstart/
```

### Slide 3 — Global InMAP provides a consistent atmospheric framework for Korea

**Narrative job:** Explain the global configuration and mentor role.

**Visible content:**

- `Global-through-urban domain`
- `Population-sensitive variable resolution`
- `Annual atmospheric fields preprocessed from a global CTM`
- `Pinned InMAP v1.9.6 and Global InMAP data v1.1.0`
- `Static global grid with a supplied TotalPop field`

Use this exact attribution:

> The Global InMAP implementation used in this project is currently being
> developed with our mentor, Jinyu Shiwang.

Bottom takeaway:

> Korea can be analyzed within a consistent atmospheric domain without
> building a new regional CTM from scratch.

**Visual:** Make a conceptual global-to-Korea zoom with the Korea crop as the
visual focus. Do not draw a hard atmospheric boundary at Korea's national
border. Label the visual `schematic—not data`.

**Speaker notes to include:**

Global InMAP extends InMAP to a global-through-urban domain, which is useful
for Korea because atmospheric transport crosses national borders. This project
pins a specific executable and official model-data version for reproducibility
and uses the supplied static global variable-resolution grid. The model's
`TotalPop` field supports exposure weighting; Korean mortality data are not
taken from Global InMAP and instead enter later from KOSIS. Tessum and
coauthors introduced InMAP, Thakrar and coauthors developed the published
Global InMAP extension, and Jinyu Shiwang is mentoring and developing this
project's Global InMAP application.

**Speaker-note sources:**

```text
[Sources]
- Thakrar et al. (2022), Global InMAP, DOI: 10.1371/journal.pone.0268714
- Jinyu Shiwang, research profile, https://jinyu-shiwang.com/
- Project-role wording supplied by the NZK-APHIAM research team
```

### Slide 4 — One run combines stack-resolved plants with area-wide emissions

**Narrative job:** Explain point and gridded inputs for plant and non-plant
sources.

**Visible content:**

Use one Korea map with two visual languages.

Label the point layer `Plant and facility sources`:

- Point features at known coordinates
- Elevated when all four stack parameters are supplied
- Annual pollutant mass, normally in `kg/year`
- Built from scenario activity × emission factors

Label the raster or area layer `Non-plant and distributed sources`:

- Gridded annual mass for transport, buildings, agriculture, and diffuse
  industry
- COARDS NetCDF-3 with `lat × lon` pollutant variables
- Points, lines, and polygons also supported where appropriate

Show the common emissions fields:

```text
VOC | NOx | NH3 | SOx | primary PM2.5
```

Bottom takeaway:

> Both input types enter the same scenario-year simulation; their inventory
> boundaries must not overlap.

**Visual:** Use restrained plant points over a transparent conceptual emissions
grid. Add one small stack cross-section with labels `height`, `diam`, `temp`,
and `velocity`. Label the map `schematic—not data`.

**Speaker notes to include:**

Power plants are represented as points because their locations and release
characteristics matter. A complete elevated point carries stack height,
diameter, exit temperature, and exit velocity in addition to annual pollutant
mass. Distributed non-power activities are often better represented as annual
mass on a latitude-longitude grid. The interface can also retain non-power
facilities as points, roads as lines, and area sources as polygons. Gridded
values are emissions mass per cell—not concentration. All selected sources
enter the same scenario-year run, so an emission source must never be included
twice.

**Speaker-note sources:**

```text
[Sources]
- InMAP authors, official Quickstart, https://inmap.run/docs/quickstart/
- NZK-APHIAM research team, mixed point/grid emissions methodology, 27 July 2026
```

### Slide 5 — InMAP converts primary and precursor emissions into spatial PM2.5

**Narrative job:** Show what happens inside the model and what it outputs.

**Visible content:**

Create one left-to-right flow:

```text
Scenario emissions
VOC | NOx | NH3 | SOx | PM2.5
        ↓
annual transport + mixing + reaction + removal
        ↓
grid-cell concentration components
primary PM2.5 | sulfate | nitrate | ammonium | SOA
        ↓
Total PM2.5 = sum of the five components
```

Show the exact model-output relationship:

```text
TotalPM25 = PrimaryPM25 + pSO4 + pNO3 + pNH4 + SOA
```

Add:

> Output: annual-average ground-level concentration in µg/m³ for every model
> grid cell.

Add a small inventory caveat:

> Current thermal-only inputs omit primary PM2.5, NH3, and VOC where
> defensible factors are not yet available.

**Visual:** Use a single atmospheric cross-section behind the middle stage,
showing an elevated plume mixing into a grid. Do not make a detailed chemistry
diagram.

**Speaker notes to include:**

InMAP tracks directly emitted primary PM2.5 and the formation of secondary
particles. SOx contributes to particulate sulfate, NOx to particulate nitrate,
NH3 to particulate ammonium and inorganic aerosol formation, and VOC to
secondary organic aerosol. The five requested concentration components sum to
TotalPM25, and the workflow checks that identity. The current thermal
inventory has defensible NOx and SOx factors, but it omits primary PM2.5, NH3,
and VOC where documented factors are unavailable. Those zeros mean not
represented in the current inventory, not known zero emissions in reality.

**Speaker-note sources:**

```text
[Sources]
- Tessum, Hill, and Marshall (2017), InMAP, DOI: 10.1371/journal.pone.0176131
- NZK-APHIAM research team, output-component and inventory methodology,
  27 July 2026
```

### Slide 6 — Global InMAP's low absolute bias motivates Korean calibration

**Narrative job:** Explain why a local correction is needed without
overgeneralizing.

**Visible content:**

- `Published evaluation found a low bias in Global InMAP annual-average total
  PM2.5 against observations.`
- `The direction and magnitude of bias vary by place and pollutant component.`
- `Korea therefore requires local evaluation rather than one global correction
  factor.`
- `The project will combine a satellite-derived historical surface estimate
  with quality-controlled AirKorea ground monitors.`

Optional small evidence callout:

> Published global evaluation: normalized mean bias = −60%.

If used, place directly below:

> Global statistic—not the Korean correction magnitude.

Bottom takeaway:

> InMAP determines the emissions-driven response; observations anchor the
> historical absolute concentration surface.

**Visual:** Use three aligned conceptual panels: `historical InMAP`,
`harmonized observations`, and `cell-specific residual`. Label all three
`schematic—not data`.

**Speaker notes to include:**

The published Global InMAP evaluation reported a global normalized mean bias
of minus 60 percent for total PM2.5, with normalized mean error of 62 percent
and R-squared of 0.33. Those values establish a general low-bias concern; they
are not estimates of Korea's correction. Bias can reflect incomplete
emissions, episodic sources that an annual model smooths, simplified chemistry,
and bias in parent-model inputs. The Korean observed surface will combine the
spatial coverage of a satellite-derived PM2.5 estimate with AirKorea
ground-monitor anchoring. The exact satellite product and fusion protocol
remain to be finalized.

**Speaker-note sources:**

```text
[Sources]
- Thakrar et al. (2022), Global InMAP, DOI: 10.1371/journal.pone.0268714
- Korea Environment Corporation, AirKorea finalized hourly monitor archives
- Satellite-derived PM2.5 product: to be finalized by the project team
```

### Slide 7 — Each grid cell receives its own additive historical offset

**Narrative job:** Make the Korea correction reproducible.

**Visible content:**

Make these equations the largest objects:

```text
b_g = C_obs,hist,g - C_InMAP,hist,g
```

```text
C_corrected,s,g = C_InMAP,s,g + b_g
```

Define:

- `g`: Global InMAP grid cell
- `hist`: common historical calibration period
- `s`: modeled reference or policy scenario
- `b_g`: fixed additive offset unique to cell `g`

Show these steps:

1. `Align observed and modeled historical PM2.5 to the same grid and period`
2. `Calculate observed − modeled in every cell`
3. `Add that cell's offset to each scenario's modeled concentration`

Use this sign-check example:

```text
Observed historical = 24 µg/m³
Modeled historical  = 20 µg/m³
Cell offset         = +4 µg/m³

Scenario model      = 16 µg/m³
Corrected scenario  = 20 µg/m³
```

**Visual:** Highlight one grid cell across four schematic panels:
`modeled`, `observed`, `offset`, and `corrected`.

**Speaker notes to include:**

The correction is calculated separately for every cell. Its sign is observed
minus modeled, so a model underestimate produces a positive offset. The same
offset is then added to the modeled concentration for each scenario. This is
an additive correction, not a ratio and not one national constant. Before
subtracting, observations and model outputs must use the same units,
calibration period, grid, spatial support, and compatible source scope.
Missing or low-confidence observation cells require a documented fusion,
interpolation, or masking rule rather than silent filling.

**Speaker-note sources:**

```text
[Sources]
- Polonik et al. (2023), additive local InMAP bias-correction precedent,
  DOI: 10.1073/pnas.2217124120
- NZK-APHIAM research team, Korea grid-cell correction design, 27 July 2026
```

### Slide 8 — The offset anchors the baseline without rewriting the policy signal

**Narrative job:** Explain what the correction changes and preserves.

**Visible content:**

Show two scenario lanes:

```text
Reference: C_ref,g    + b_g → C_corrected,ref,g
Policy:    C_policy,g + b_g → C_corrected,policy,g
```

Then show:

```text
C_corrected,ref,g - C_corrected,policy,g
  = C_ref,g - C_policy,g
```

Use two contrasting statements:

- `Changes: the absolute historical or background concentration represented
  in each cell`
- `Preserves: the within-cell reference–policy difference when both receive
  the same offset`

Add a prominent caveat:

> Estimate the offset from an all-source historical baseline—not from a
> plant-only contribution.

Add a small validation line:

> Validate on held-out monitors or years and show corrected versus uncorrected
> sensitivity results.

**Visual:** Use two parallel scenario paths receiving the same cobalt offset
before converging on a subtraction. Let the algebra be the dominant visual.

**Speaker notes to include:**

Because both scenarios receive the same cell-specific offset, it cancels when
the reference and policy concentrations are differenced. The correction
therefore anchors absolute concentration while leaving the modeled
emissions-driven scenario signal unchanged. The offset must come from an
all-source historical model run. Subtracting a plant-only contribution from
observed ambient PM2.5 would also capture omitted non-plant emissions,
transboundary transport, natural sources, and background concentration.
Where possible, construct the correction with one set of monitors or years and
evaluate it on held-out observations. Corrected and uncorrected estimates
should be retained as a sensitivity.

**Speaker-note sources:**

```text
[Sources]
- Polonik et al. (2023), additive local InMAP bias-correction precedent,
  DOI: 10.1073/pnas.2217124120
- NZK-APHIAM research team, concentration-scope and validation rules,
  27 July 2026
```

### Slide 9 — InMAP is the atmospheric bridge in an auditable research pipeline

**Narrative job:** Close by showing the full pipeline and current status.

**Visible content:**

Use one horizontal pipeline:

```text
Energy scenarios
→ plant + non-plant activity
→ pollutant emissions
→ point + gridded inputs
→ Global InMAP
→ Korea bias correction
→ population-weighted exposure
→ health impacts
```

Add source labels beneath the relevant stages:

- `KEPCO / EPSIS / MACRO / GCAM-KAIST`
- `Emission factors + stack parameters`
- `AirKorea + satellite-derived historical PM2.5`
- `Global InMAP TotalPop`
- `KOSIS + concentration-response functions`

Add status annotations directly to the pipeline:

`Integrated and tested`:

- mixed point and grid input interface;
- scenario scoping and input manifests;
- dependency-aware run cache;
- component-sum and grid-alignment checks;
- scenario differencing; and
- national population-weighted exposure adapter.

`In progress`:

- strict converged analytical runs;
- paired production scenarios;
- production non-power spatial inventory;
- all-source historical calibration baseline;
- Korea-specific correction and held-out validation; and
- district-level exposure.

End with:

> Global InMAP determines how scenario emissions change PM2.5 across space;
> Korean observations anchor absolute concentration before exposure and health
> interpretation.

**Visual:** Use one native PowerPoint pipeline with Global InMAP visually
dominant at the center. Put correction after the model and before exposure.
Place connectors behind nodes.

**Speaker notes to include:**

The atmospheric stage is designed to be auditable. Each scenario-year input is
validated and recorded, and cached runs are tied to the executable,
configuration, and every emissions dependency. Output checks verify the sum of
PM2.5 components, consistent grids, the reference-minus-policy sign
convention, and population weighting. The mixed input interface and
fixed-iteration proof of concept work end to end. Publication-ready inference
still requires converged model runs, production scenarios and non-power
inventories, an all-source historical baseline, and implementation and
validation of the Korean correction. InMAP ends at concentration; exposure and
health are downstream.

**Speaker-note sources:**

```text
[Sources]
- NZK-APHIAM research team, Global InMAP pipeline and implementation status,
  27 July 2026
- Tessum, Hill, and Marshall (2017), InMAP, DOI: 10.1371/journal.pone.0176131
- Thakrar et al. (2022), Global InMAP, DOI: 10.1371/journal.pone.0268714
```

## Final quality-control checklist

Before delivering the PPTX:

- Confirm all nine slides are present and ordered as specified.
- Confirm every title fits on one line.
- Confirm InMAP is called a reduced-complexity mechanistic air-quality model.
- Confirm the slides consistently describe annual-average PM2.5.
- Confirm no slide implies hourly, seasonal, or episode prediction.
- Confirm the variable-resolution grid is explained.
- Confirm plant inputs are points and distributed non-plant inputs are grids,
  with supported feature alternatives mentioned.
- Confirm stack height, diameter, temperature, and velocity are correctly
  named.
- Confirm gridded input is emissions mass per cell, not concentration.
- Confirm the input fields are `VOC`, `NOx`, `NH3`, `SOx`, and `PM2_5`.
- Confirm the five output components are primary PM2.5, sulfate, nitrate,
  ammonium, and secondary organic aerosol.
- Confirm current omitted pollutants are not described as real-world zeros.
- Confirm the mentor credit applies to this project's implementation and does
  not replace original model authorship.
- Confirm the global low-bias statistic, if shown, is not presented as the
  Korean correction magnitude.
- Confirm the observational wording distinguishes satellite-derived estimates
  from ground monitors.
- Confirm no satellite product or calibration period has been invented.
- Confirm the correction is `observed − modeled`.
- Confirm the correction is added to each scenario output.
- Confirm the correction is additive and unique to each grid cell.
- Confirm the same offset cancels from the reference-policy difference.
- Confirm the correction is not estimated from a plant-only contribution.
- Confirm correction appears after Global InMAP and before exposure.
- Confirm the current correction, non-power inventory, and converged runs are
  labeled in progress.
- Confirm no proof-of-concept concentration or health value is presented as a
  result.
- Confirm conceptual maps and rasters are labeled `schematic—not data`.
- Confirm every slide includes its supplied `[Sources]` block in speaker notes.
- Render and inspect every slide at full size for overlap, clipping, connector
  crossings, title wrapping, equation legibility, and source completeness.
