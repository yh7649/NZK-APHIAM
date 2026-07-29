# Combined power and non-power inputs for InMAP

## Outcome

The combined inventory assembler turns the temporary 2025--2050 scenario
fixtures into one accounting ledger and the two physical emissions formats that
Global InMAP requires:

- elevated point-source shapefiles for KEPCO thermal generation; and
- COARDS NetCDF-3 gridded files for non-power emissions.

InMAP does not accept point stacks and gridded emissions as one physical table.
The stable combined object is therefore a scenario-year bundle: one harmonized
long-form ledger, one point shapefile family, one grid file, and one manifest
that binds them without double counting.

The implementation is
[`src/nzk_aphiam/air_quality/inmap/combined_inventory.py`](../../src/nzk_aphiam/air_quality/inmap/combined_inventory.py).
Its first-pass assumptions are version controlled in
[`configs/scenarios/inmap_combined_proxy_2025_2050.yaml`](../../configs/scenarios/inmap_combined_proxy_2025_2050.yaml).

## Reproducible build

Run:

```bash
make build-inmap-combined-inputs PYTHON_INTERPRETER=.venv/bin/python
```

The target rebuilds the proportional KEPCO scenario fixture, the GCAM-KAIST-shaped
non-power fixture and CAPSS-intensity smoke test, and the non-power factor catalog
before assembling the bundle. Generated files are Git-ignored under:

```text
data/processed/inmap/combined_proxy_2025_2050/
```

The root files are:

- `combined_inmap_input_manifest.json`: all 18 scenario-year jobs, methods,
  source checksums, factor status, and output paths;
- `harmonized_emissions_ledger.parquet` and `.csv`: one long-form power plus
  non-power mass ledger;
- `diagnostics/mass_reconciliation.csv`: scenario/year/source/pollutant totals;
- `diagnostics/power_allocation_diagnostics.csv`: generation mass balance and
  KEPCO allocation fallbacks;
- `diagnostics/nonpower_factor_catalog_audit.json`: candidate versus
  production-ready factor counts; and
- `diagnostics/nonpower_spatialization_diagnostics.csv`: preferred versus actual
  source geometry.

Each `SCENARIO/YEAR/` directory contains:

```text
emission_inputs.json
harmonized_emissions_ledger.parquet
power_point/emissions.shp
nonpower_grid/emissions.nc
```

The shapefile sidecars, full-schema point Parquet, plant lookup, schema JSON, and
CSV ledger are included alongside those primary files. Paths in the run manifest
are relative to the manifest, so no machine-specific path is embedded.

## Power path

The assembler reads the five-column MACRO-shaped power handoff:

```text
Scenario, Year, Province, Technology, Generation_TWh
```

Combined labels such as `ThermalPower{Coal}` are split into technology and fuel,
generation is converted to MWh, and every province/fuel/technology total is
allocated to the documented KEPCO unit roster. Allocation uses compatible
capacity, then recent generation, then equal weights, with exact mass balance.

For this fixture, 2024 is the complete-calendar proxy year. Generation-weighted
KEPCO factors are derived from the processed monthly mass and generation records
at fuel-technology level, with documented fuel and all-thermal fallbacks. NOx and
SOx enter the InMAP point inventory. TSP is calculated and retained in the
full-schema audit data, but is not relabeled as primary PM2.5. Power primary
PM2.5, NH3, and VOC remain explicit omitted zero fields because no defensible
factors are currently applied.

Unit coordinates are taken from the processed plant crosswalk. Stack height,
diameter, temperature, and velocity use the established observed-to-imputed
hierarchy. The resulting EPSG:4326 shapefile has InMAP's exact field names:

```text
VOC, NOx, NH3, SOx, PM2_5, height, diam, temp, velocity
```

## Non-power path and factor gate

The desired production calculation is physical GCAM-KAIST activity multiplied
by approved, denominator-compatible non-power emission factors. The repository
does not yet contain either prerequisite:

- the temporary activity file is an index (`2025 = 100`), not tonnes of fuel,
  vehicle-km, animal-years, or another physical denominator; and
- the current imported factor catalog and inventory links contain zero
  `production_ready=true` rows.

The assembler always reads and audits the factor catalog. Selecting
`approved_factor_inventory` mode fails closed while either prerequisite is
missing. It never multiplies a `kg/ton-fuel` candidate by an activity index and
never treats an unresolved factor as zero.

For the explicit first-pass mode,
`capss_base_intensity_screening`, non-power mass comes from the existing
integration smoke test:

```text
2023 CAPSS sector-fuel emissions / 2023 activity index
    × scenario-year activity index
```

That factor is an aggregate calibration intensity for pipeline testing. It is
not one of the candidate physical factors and is labeled accordingly in every
ledger and manifest.

## Point versus grid routing

Power is emitted at elevated KEPCO points. Current non-power rows are all written
to a four-cell national proxy grid because no sector-specific spatial surrogate
or non-power facility/stack crosswalk is connected.

The routing diagnostic distinguishes two cases:

- manufacturing combustion, production processes, waste treatment, and
  fuel transport/storage are `Point` preferred but temporarily downgraded to
  the proxy grid; and
- transport, agriculture, buildings, solvents, dust, biological combustion,
  and other diffuse sources are `Grid` preferred but still lack appropriate
  road, population, land-use, livestock, or other sector-specific weights.

The four grid weights sum to one, and the writer verifies pollutant mass after
NetCDF serialization. This makes the bundle suitable for software plumbing and
rough sensitivity runs, not spatial exposure or health inference.

## Replacement path

The module has stable boundaries for the team deliverables:

1. replace the power fixture path with native MACRO generation and update only
   `scenario_pairs` if labels differ;
2. replace the activity index with physical GCAM-KAIST activity;
3. approve denominator-compatible factor and inventory-link rows, then select
   `approved_factor_inventory`;
4. provide non-power facility coordinates and stacks for point-preferred sectors;
5. provide normalized sector-specific grid weights for diffuse sectors; and
6. retain the same InMAP point/grid manifest interface.

Until steps 2--5 are complete, all generated manifests set
`analytical_use_permitted=false`.

## One-command InMAP execution

The pinned InMAP installation is recorded at
`.cache/inmap/installation_manifest.json`. Generate all 18 strict-convergence
TOMLs without starting the model:

```bash
make inmap-combined-prepare PYTHON_INTERPRETER=.venv/bin/python
```

This writes portable job metadata and machine-local TOMLs under:

```text
results/models/inmap/combined_proxy_2025_2050/strict/
```

Run every scenario-year sequentially with one command:

```bash
make inmap-combined-run PYTHON_INTERPRETER=.venv/bin/python
```

The runner is resumable. Completed jobs are reused only when the binary, TOML,
and both emissions inputs have identical checksums. A stopped run can therefore
be restarted with the same command.

Strict mode uses `NumIterations = 0`, requesting InMAP's automatic convergence
criterion. This can take many hours per job. Solver convergence does not upgrade
the screening emissions or spatial proxies to analytical status.

For a faster real-binary plumbing test across all 18 jobs:

```bash
make inmap-combined-poc PYTHON_INTERPRETER=.venv/bin/python
```

The default proof uses 200 fixed iterations and writes separately under
`poc_200_iterations/`. It is explicitly non-converged and non-analytical.

### Bounded parallel runs

Each scenario-year is independent, but one Global InMAP process also uses
multiple CPU cores and substantial memory. On the 14-core, 38.7 GB development
machine, a 200-iteration process used approximately 11–12 cores and 10.5 GB of
resident memory. Starting all 18 processes together would therefore oversubscribe
both CPU and memory.

The bounded runner starts two scenario-years concurrently and automatically
assigns half the detected CPU cores to each InMAP process. To switch a currently
running sequential POC to this mode, stop the existing command first and then
run:

```bash
make inmap-combined-poc-parallel PYTHON_INTERPRETER=.venv/bin/python
```

Do not leave the sequential runner active while starting the parallel runner,
because two processes could target the same output. Successfully completed jobs
are checksum-verified cache hits and are not rerun. The parallel run continues to
write the same output paths and `run_summary.json`; it records the worker and
thread limits. If memory pressure is observed, reduce the bound with
`INMAP_COMBINED_PARALLEL_WORKERS=1`. More than two workers is not recommended on
this machine.

After a prepared POC, the parallel model and health stages can be run together:

```bash
make inmap-combined-poc-parallel-with-health PYTHON_INTERPRETER=.venv/bin/python
```

For the fastest end-to-end first-pass proof, a dedicated target prepares 50
iterations, runs two scenario-years concurrently, calculates the diagnostic
health outputs, and creates presentation-ready figures and tables:

```bash
make inmap-combined-fast-poc-with-health PYTHON_INTERPRETER=.venv/bin/python
```

It writes independently under `poc_50_iterations/`; it never overwrites
`poc_200_iterations/`. Fifty iterations should reduce the iteration-dependent
runtime to roughly one quarter of the 200-iteration setting, although model
startup, input loading, output writing, and health post-processing do not scale
with iteration count.

There is no fixed percentage accuracy conversion from 200 to 50 iterations.
Iterations within one scenario are sequential solver updates, and both fixed
counts stop without checking the convergence criterion. A 50-iteration result
can therefore differ materially from 200 iterations or strict convergence.
The 50-iteration mortality files are useful for verifying schemas, scenario
ordering, signs, and the complete model handoff—not for reporting effect sizes.
Accuracy must later be assessed by comparing the same scenario at 50, 200, and
automatic convergence.

On 27 July 2026, a one-iteration smoke job for `no_nzk` 2025 completed against
the pinned real binary. It accepted the mixed point-plus-COARDS configuration
and produced a schema-valid 273,739-cell Global InMAP output. This confirms
executable compatibility only; one iteration is not a concentration result.

Every run directory contains:

- `configs/*.toml`: the executable InMAP instruction files;
- `run_jobs.json`: ordered resumable job definitions;
- `outputs/SCENARIO/YEAR/`: concentrations, logs, and run state; and
- `run_summary.json`: completed-job count and validated output status.

## Korea exposure and mortality post-processing

After the current 200-iteration command finishes, run:

```bash
make inmap-combined-poc-health PYTHON_INTERPRETER=.venv/bin/python
```

For future runs, the model and diagnostic health stages can execute together:

```bash
make inmap-combined-poc-with-health PYTHON_INTERPRETER=.venv/bin/python
```

The post-processor reuses the existing South Korea boundary filter, population-
weighted InMAP exposure calculation, KOSIS age-specific population and mortality
inputs, and BenMAP-style health equations. It does not implement a second health
formula.

POC health outputs are written under:

```text
results/models/inmap/combined_proxy_2025_2050/
  poc_200_iterations/health/
```

The main files are:

- `diagnostic_nonconverged_national_scenario_exposures.csv`: Korean
  population-weighted PM2.5 for all 18 scenario-years;
- `diagnostic_nonconverged_scenario_mortality_primary.csv`: the primary
  Huang–Peng/Krewski annual attributable-death number and coefficient interval
  for every scenario-year;
- `diagnostic_nonconverged_avoided_deaths_vs_no_nzk.csv`: same-year `no_nzk`
  minus `nzk_low` or `nzk_high` comparisons, where positive means avoided deaths;
- `diagnostic_nonconverged_scenario_mortality_all_crfs.csv`: alternative
  prespecified CRFs, which are sensitivities and must never be summed;
- `diagnostic_nonconverged_health_specification_status.csv`: complete and
  endpoint-blocked CRFs; and
- `health_postprocess_manifest.json`: interpretation, population-year rules,
  status, and output inventory.

The scenario total is annual mortality attributable to the modeled Korean power
and non-power PM2.5 source contribution. It is not total ambient-PM2.5 mortality
because the inventory does not include a complete ambient background,
transboundary pollution, or final production-ready emissions.

Population uses the scenario year through 2042. KOSIS currently stops in 2042,
so the diagnostic 2045 and 2050 calculations hold the 2042 age-specific
projection constant and record `population_year = 2042`. National age-specific
2024 mortality rates are held constant for every scenario year. Missing
non-accidental and NCD+LRI mortality endpoints remain blocked; all-cause is never
silently substituted for them.

The POC filenames and every row state
`nonconverged_poc_diagnostic_not_for_inference`. Running the strict solver and
then `make inmap-combined-health` changes the solver status, but the proxy
emissions and spatialization still prohibit analytical use.

## Result figures and tables

The health targets now run the reporting stage automatically. To rebuild only
the report after a 50-iteration health stage has completed, run:

```bash
make inmap-combined-poc-report \
  PYTHON_INTERPRETER=.venv/bin/python \
  INMAP_COMBINED_POC_ITERATIONS=50
```

For a 50-iteration POC, the figures are written under:

```text
results/figures/inmap/combined_proxy_2025_2050/poc_50_iterations/
```

- `inmap_pm25_trajectories.png`: population-weighted Korean PM2.5 contribution
  and percentage reduction relative to `no_nzk`;
- `benmap_avoided_mortality.png`: annual avoided attributable deaths for both
  NZK pathways, with CRF-coefficient intervals; and
- `air_quality_health_summary.png`: side-by-side 2050 PM2.5 reductions and
  avoided mortality.

The corresponding CSV tables are written under:

```text
results/tables/inmap/combined_proxy_2025_2050/poc_50_iterations/
```

- `inmap_scenario_results.csv`;
- `benmap_scenario_mortality.csv`;
- `benmap_avoided_mortality.csv`;
- `headline_results_2050.csv`; and
- `combined_results_report_manifest.json`.

The reporting layer does not change the calculations. “Avoided mortality” is
`no_nzk` minus the policy scenario for the primary Huang–Peng/Krewski all-cause
CRF. It is the change in deaths attributable to the modeled Korean source
contribution, not a prediction of total national mortality. POC chart subtitles
and tables retain the non-converged diagnostic label.
