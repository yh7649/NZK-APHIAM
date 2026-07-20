# Korean thermal-power Huang–Peng replication MVP

This workflow connects the repository's existing KEPCO, EPSIS, MACRO, KOSIS,
and health-impact components to a new plant-allocation and Global InMAP bridge.
It is a screening-level minimum viable replication of the thermal-power portion
of Huang and Peng (2025), not a publication-ready causal policy evaluation.

## Current comparison

The only local MACRO generation deliverable has no scenario column. It contains
one pathway for 2021, 2025, 2030, and 2035. The workflow therefore compares the
existing national observed EPSIS 2021 thermal generation handoff with the 2030
MACRO pathway and labels the comparison everywhere as:

```text
historical_to_scenario
```

It does not invent a reference case or call the difference the causal benefit of
net-zero policy. The MACRO pathway is labeled `macro_scenario` only to provide a
stable internal identifier; that label does not assert its policy content.

## Reused inputs and new components

The workflow reuses, without recalculating:

- `data/processed/kepco/kepco_monthly_generation_emissions.csv` for the canonical
  KEPCO thermal unit/reporting-boundary roster, coordinates, capacity, fuel,
  technology, commissioning evidence, retirement evidence, and recent generation;
- `data/processed/epsis/epsis_observed_generation_for_validation_2021.csv` for
  observed national 2021 thermal generation;
- the generation-weighted `ef_kg_per_mwh` field in
  `results/tables/kepco/annual_handoff/kepco_annual_ef_distribution_long_by_fuel_technology.csv`;
- the existing location, retirement, technology, and stack crosswalks;
- KOSIS age-specific population projections and mortality rates; and
- `health.crf` and `health.impact`, including the verified Krewski central estimate
  and confidence bounds.

The new code normalizes and selects scenarios, fills province coverage with five
explicitly documented real CHP/thermal sites, allocates generation, maps EFs,
imputes stacks, writes elevated Global InMAP inputs, runs and caches InMAP,
filters output to South Korea, aggregates exposure, and adapts real exposure to
the existing health API.

## Allocation and emissions safeguards

For each scenario/year/province/fuel/technology group, active compatible units are
selected after commissioning and retirement checks. Allocation weights use:

1. compatible capacity;
2. recent historical generation if compatible capacity is unavailable; or
3. equal weights if both are unavailable.

Exact fuel/technology matches are preferred. A documented same-fuel technology
aggregation is next. The final fallback uses an existing thermal site in the same
province and marks the fuel/technology assignment as synthetic. Every fallback is
reported. The `existing_site_allocation` assumption is an accounting device and
does not predict future siting. Generation mass balance is enforced for every
group to 0.001 MWh.

NOx and SOx use the 2021 generation-weighted KEPCO EFs for both inventories. EF
fallbacks remain generation-weighted: exact fuel/technology, technology aggregation
within fuel, then fuel-level. A missing defensible EF stops the pipeline.

The repository contains TSP but no documented TSP-to-primary-PM2.5 conversion for
this inventory. Primary PM2.5 is therefore omitted in the central run (`PM2_5 = 0`),
and TSP is never treated as PM2.5. NH3 and VOC are likewise omitted because no
documented factors were available. These zero input fields mean *omitted*, not
known zero real-world emissions.

## Stacks and Global InMAP

Stack values use unit observed, plant observed, fuel–technology median, fuel median,
then all-thermal median values, with separate provenance for height, diameter,
temperature, and velocity. The observed table is coal-heavy, so LNG/CHP stacks are
mostly imputed and must be interpreted accordingly.

The pinned model is InMAP v1.9.6 with the official Global InMAP evaluation/model
dataset v1.1.0 (Zenodo DOI `10.5281/zenodo.6189451`). The archive contains the
GEOS-Chem-derived `InMAPData_v1.0.0.ncf`, the v1.1.0 global variable grid, and the
official 2020-projected GPW population `population/Pop.ncf`. The evaluation archive
explicitly does not include mortality data. If InMAP's grid-building loader is
invoked for validation, it is given a zero-valued compatibility polygon with an empty
mortality-column map; no InMAP mortality variable is requested, and this input cannot
enter exposure or health calculations. Health mortality comes only from the documented
KOSIS input.

The official v1.9.6 release tag points to commit
`7b665744065a447d2f2a64aa7124c043ef5b8b2e`, whose upstream `framework.go` still
sets the internal version string to `1.9.0`. The installer therefore expects the
official asset to print `InMAP v1.9.0` and records the release tag, asset filename,
commit, and local executable SHA-256 together; any other version output is rejected.

Binaries, archives, model data, and raw model outputs are cached under `.cache/inmap/`
or generated under ignored `results/mvp/`; none are committed. A US-only InMAP
domain or US source-receptor matrix is rejected.

Runs explicitly use static-grid mode (`static = true` and `--static`) so the
official prebuilt v1.1.0 `.gob` grid, including its `TotalPop` field, is loaded.
Static mode does not invoke the population/mortality grid-building loader; those
paths remain in the generated config only as explicit compatibility metadata.
Omitting `--static` makes the CLI rebuild a dynamic global grid and is not this
workflow's intended configuration.

The default analytical profile sets `NumIterations = 0`, which makes InMAP stop
only when every nonzero species' domain mass and population-weighted concentration
change by less than 0.1% over a three-simulated-hour check period. InMAP v1.9.6
does not write a solver checkpoint that this workflow can resume after interruption.

An isolated proof-of-concept profile accepts a positive fixed iteration count.
It uses the real binary, official data, inventories, output validation, differencing,
and national exposure code, but its run directory is suffixed
`_inmap_poc_<N>_iterations`. Its manifest and report mark the concentrations as
non-converged diagnostics, and the pipeline prohibits normal health output. An
additional explicit opt-in can exercise the health adapter, but writes only files
prefixed `diagnostic_nonconverged_`, preserves `health_use_permitted = false`, and
does not create `health_impacts.csv`. This profile tests plumbing; it is never an
analytical shortcut.

### First completed real-binary proof of concept

On 20 July 2026, the 200-iteration profile completed both the observed EPSIS 2021
and MACRO 2030 inventories against the official Global InMAP grid. Each output
contained 273,739 cells and completed in about 4.8 minutes on the development
machine. National filtering retained 1,104 South Korean cells with 49.76 million
people in `TotalPop`.

The diagnostic population-weighted incremental concentrations were 0.024857 µg/m³
for observed 2021 and 0.036591 µg/m³ for MACRO 2030. Their documented
historical-minus-future difference was -0.011734 µg/m³. These are early-time,
non-converged diagnostics and must not be cited as exposure or policy estimates.
The POC manifest sets both analytical and health use to false.

At the user's explicit request, the opt-in diagnostic health pass was also exercised.
The MACRO inventory has 50.14 thousand tonnes/year more NOx and 12.53 thousand
tonnes/year more SOx than the observed inventory, so its higher diagnostic exposure
has the expected adverse sign. With 2030 projected Korean population age 30+ (38.03
million people), 2024 national age-specific mortality rates held constant, and the
Krewski CRF, the module calculates 89.61 deaths attributable to the included MACRO
thermal increment versus 60.88 for observed 2021: **28.74 additional annual deaths**
(CRF-coefficient-only interval 19.34--37.95).

This is not a health-impact estimate. Besides non-convergence and the deliberately
overstated MACRO thermal pathway, it omits primary PM2.5, NH3, and VOC emissions;
uses imputed stacks and existing-site allocation; uses national-average exposure;
holds 2024 mortality rates fixed; and transfers a US-cohort CRF to Korea. The interval
propagates only CRF coefficient uncertainty, not uncertainty in emissions, InMAP,
exposure, demographics, mortality, or model structure.

Each scenario input is an EPSG:4326 elevated point-source shapefile with annual
`kg/year` fields `VOC`, `NOx`, `NH3`, `SOx`, `PM2_5`, `height`, `diam`, `temp`, and
`velocity`. A full-name Parquet copy, schema JSON, and plant lookup accompany it.
Output total PM2.5 is the consistent sum of `PrimaryPM25`, `pSO4`, `pNO3`, `pNH4`,
and `SOA`.

The sign convention is always:

```text
historical/reference minus future/policy
```

Positive emissions or concentration differences mean the future/policy inventory
is lower. Tests guard against reversal.

## Exposure and health interpretation

The mandatory exposure result is the Global InMAP `TotalPop`-weighted concentration
difference, using the dataset's documented 2020-projected GPW spatial weights, across
cells whose centroids fall inside the Natural Earth South Korea boundary. Offshore
and foreign cells are excluded; border cells are assigned by centroid. There is no
uniform-population fallback. District estimates remain out of scope because compatible
district boundaries and a population allocation raster are not present locally.

The health adapter uses target-year KOSIS population projections (2030) and holds
the latest compatible observed national age-specific mortality rates (2024) fixed.
It evaluates the incremental thermal-power concentrations by anchoring them at the
CRF counterfactual and calls the repository's existing marginal health function.
This is an incremental included-source estimate, not mortality attributable to
total ambient PM2.5. Health results are never produced unless real InMAP exposure
outputs exist.

## Commands

```bash
make peng-mvp-audit PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp-inventory PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp-install-inmap PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp-run-inmap PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp-exposure PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp-health PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp-poc PYTHON_INTERPRETER=.venv/bin/python
make peng-mvp-poc-health-diagnostic PYTHON_INTERPRETER=.venv/bin/python
make test-peng-mvp PYTHON_INTERPRETER=.venv/bin/python
```

Pass CLI controls through `PENG_MVP_ARGS`, for example:

```bash
make peng-mvp PENG_MVP_ARGS="--target-year 2030 --resume"
```

Supported controls include `--dry-run`, `--force`, `--target-year`,
`--reference-scenario`, `--policy-scenario`, `--skip-inmap-download`, and
`--resume`. `--inmap-poc-iterations N` selects the isolated diagnostic profile.
`--write-diagnostic-poc-health` opts into separately named, explicitly
non-inferential health post-processing for that profile.
Completed InMAP runs are keyed by inventory, configuration, and
executable version and are not rerun when that key is unchanged.

Run-specific artifacts and `MVP_REPORT.md` are under
`results/mvp/peng_replication/<run_id>/`. The fixed input audit is also written to
`results/mvp/peng_replication/input_audit.json`.
