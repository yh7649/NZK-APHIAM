# Native GCAM-KAIST NZK interface

## Scenario decision

The GCAM-KAIST `CORE_9_NZ` pathway is the common non-power baseline for both
combined cases. The comparison changes only the power pathway:

| Combined case | Power pathway | Non-power pathway |
|---|---|---|
| `nzk_with_power_plant_nzk` | `nzk_high` | `nzk` |
| `nzk_without_power_plant_nzk` | `no_nzk` | `nzk` |

This isolates the incremental effect of applying the temporary NZK power-plant
pathway while holding the rest of the NZK economy fixed. The power names are
temporary KEPCO fixtures until the team supplies paired production power
pathways. The reference GCAM archive is paused and is not used.

## Source and extraction

The DVC-tracked source is:

```text
model_inputs/scenarios/team_handoff/upstream/gcam_kaist/nzk/
CORE_9_NZ_2026-8-7T12_32_50+09_00.xml.zip
```

The extractor streams the 2.38 GB XML member directly from the 113 MB ZIP. It
does not create an extracted XML copy. It validates the complete document,
scenario name, model version, years, regions, numeric values, and the presence
of `South Korea`.

Run the whole interface:

```bash
make build-gcam-nzk-interface PYTHON_INTERPRETER=.venv/bin/python
```

The separate stages are:

```bash
make inspect-gcam-nzk PYTHON_INTERPRETER=.venv/bin/python
make extract-gcam-nzk PYTHON_INTERPRETER=.venv/bin/python
make build-gcam-nzk-nonpower-interface PYTHON_INTERPRETER=.venv/bin/python
make build-gcam-nzk-spatial-interface PYTHON_INTERPRETER=.venv/bin/python
```

Generated, Git-ignored files go to:

```text
model_inputs/scenarios/team_handoff/aphiam/gcam_kaist/nzk/
```

The extracted activity table retains the complete GCAM path:

```text
scenario, source_scenario, region, year, record_type,
sector_type, sector, subsector_type, subsector,
technology_type, technology, node_type, node, activity, activity_unit
```

The native-emissions table retains the same sector path plus native pollutant,
native unit, and kilograms where the XML unit has a documented mass
conversion. Native emissions are validation-only because they are national,
do not provide source coordinates, and do not directly provide primary PM2.5.
BC and OC are not silently converted to PM2.5.

The verified NZK extraction contains 20,387 activity rows and 23,301 native
emissions rows for 2021, 2025, 2030, 2035, 2040, 2045, and 2050.

## Activity mapping and emission factors

[`gcam_kaist_native_activity_crosswalk.csv`](../references/nonpower_emissions/gcam_kaist_native_activity_crosswalk.csv)
uses full-match regular expressions over record, sector, subsector, technology,
node, and unit fields. It converts native quantities into explicit canonical
denominators and stable `inventory_id` values. Every selector also records
whether it is usable, a documented proxy, or a blocked conversion.

The current mapping produces 199 annual canonical rows covering 12 of 50 P1
inventory IDs. Eleven have production-ready activity selectors; the hydrogen
conversion remains blocked:

- steel BF/BOF, EAF, and combustion;
- cement output proxy and kiln energy;
- chemical and other-manufacturing energy;
- residential and commercial direct heating;
- nitrogen fertilizer;
- refining combustion; and
- natural-gas steam-reforming hydrogen.

Transport passenger-km and tonne-km, refinery throughput, machinery, waste,
wastewater, landfill, and solvent rows remain explicit gaps where GCAM does
not supply the required physical denominator or a reviewed conversion.

The separate maximum-coverage POC reads
[`gcam_nzk_poc_activity_conversion_assumptions.csv`](../references/nonpower_emissions/gcam_nzk_poc_activity_conversion_assumptions.csv).
It enables all 42 native selectors, covering 25 APHIAM inventory IDs and 289
annual activity rows. Passenger occupancy, freight payload, fuel intensity,
energy density, and representative-flight assumptions provide screening
conversions. GCAM rows reported with unit `NA` retain their native numeric value
as an activity index. None of these additions changes the production-ready
flags.

The ingestor joins activity only when its activity selector is production-ready
and both the factor row and inventory link carry `production_ready=true`. It
also checks that the factor denominator is compatible with the canonical
activity unit. Missing, candidate, nonnumeric, or incompatible factors create
gap rows; they never become zero. The current catalog has no approved rows, so
`approved_projected_emissions.csv` is intentionally empty and all 199
canonical activity rows appear in `approved_factor_gaps.csv`.

## Spatial routing

The spatial builder maps the non-power inventory to 2021 CAPSS categories and
derives pollutant-specific province/district emission shares. It produced
35,630 administrative-weight rows across 68 inventory IDs. These shares are
not coordinates and are therefore marked `analytical_use_permitted=false`.

For the maximum-coverage POC only, missing inventory/pollutant spatial keys
inherit the national CAPSS distribution for that pollutant. Each CAPSS
administrative share is then placed at the mean coordinate of real AirKorea
monitors in the matching district. When no district monitor exists, the code
uses the matching province monitor centroid and then the national monitor
centroid. The resulting file covers every P1 inventory/pollutant key and uses
201 distinct coordinates in the active 25-sector bundle. These are much less
arbitrary than the old four-cell grid, but remain monitor-location proxies
rather than emitting facilities, stack locations, or population centroids.

[`nonpower_spatial_geometry.csv`](../references/nonpower_emissions/nonpower_spatial_geometry.csv)
is the reviewed coordinate interface:

- facility-like sources use `geometry_type=Point` and require longitude,
  latitude, weight, stack height, diameter, temperature, and velocity;
- diffuse sources use `geometry_type=Grid` and require longitude, latitude,
  and weights;
- weights must sum to one within each `inventory_id`; and
- only rows with `status=production_ready` can enter an InMAP bundle.

The InMAP ingestor supports mixed non-power point shapefiles and
coordinate-weighted COARDS grids and verifies national mass after allocation.
The current readiness audit classifies the 50 P1 rows as 17 point-preferred,
32 grid-preferred, and one unresolved. No reviewed coordinates are present yet.

## Runnable three-power-pathway proof of concept

The separate proof-of-concept configuration holds native `CORE_9_NZ`
non-power activity fixed and pairs it with all three simulated MACRO-shaped
power paths:

| POC case | Power path | Non-power path |
|---|---|---|
| `nzk_nonpower_no_nzk_power` | `no_nzk` | `nzk` |
| `nzk_nonpower_low_nzk_power` | `nzk_low` | `nzk` |
| `nzk_nonpower_high_nzk_power` | `nzk_high` | `nzk` |

Run the complete 18-job, 50-iteration POC with one command:

```bash
make inmap-gcam-nzk-poc PYTHON_INTERPRETER=.venv/bin/python
```

Rerunning the command resumes valid completed jobs. Override
`INMAP_GCAM_NZK_POC_ITERATIONS` or `INMAP_GCAM_NZK_POC_WORKERS` when needed.

When the 18 jobs are complete, run the downstream health and presentation
package without rerunning InMAP:

```bash
make inmap-gcam-nzk-poc-health PYTHON_INTERPRETER=.venv/bin/python
```

For a future end-to-end invocation, use
`make inmap-gcam-nzk-poc-with-health`. The downstream target extracts
population-weighted Korean PM2.5, applies the repository's
BenMAP-equivalent age-specific health calculation, writes concise result
tables, and renders scenario maps, component maps, charts, GIFs, and MP4s. The
50-iteration outputs are stored in parallel `results/figures/`,
`results/tables/`, and `results/videos/` directories under
`inmap/gcam_nzk_three_power_poc_2025_2050/poc_50_iterations/`.

In the completed 50-iteration run, the 2050 population-weighted modeled source
contribution is 1.403536 µg/m3 in the no-NZK-power case, 1.403470 µg/m3 in the
low-NZK-power case, and 1.403228 µg/m3 in the high-NZK-power case. Against the
no-NZK-power reference, the primary all-cause specification estimates 0.253
avoided attributable deaths for the low pathway and 1.196 for the high pathway.
These are diagnostic outputs, not policy effect estimates.

This path keeps every mapped activity and assigns all five InMAP pollutants.
The EF ladder is deliberately permissive:

1. median denominator-compatible candidate factors linked to the inventory;
2. an effective factor calculated as 2021 CAPSS emissions divided by the
   nearest available GCAM activity year;
3. a linked factor used despite an incompatible denominator; and
4. the global catalog median for that pollutant when no sector evidence exists.

The active projection contains 860 annual rows across all 25 mapped inventory
IDs. Its 125 inventory/pollutant pairings use six denominator-compatible
candidate mappings, 90 CAPSS-calibrated effective mappings, and 29 global
pollutant fallbacks; the current data do not require tier 3. The factor audit
names the method, factor records, source units, reference year, and selection
rank for every pairing.

Non-power mass is allocated with CAPSS administrative shares anchored to
AirKorea monitor centroids. Every input and run manifest still sets
`analytical_use_permitted=false`. The POC is intentionally complete enough to
exercise InMAP, but the assumed conversions, global factor fallbacks, monitor
centroids, missing facility stacks, and unapproved factors make it unsuitable
for emissions, exposure, health, or policy inference.

The pathway animation advances between independently solved annual steady-state
fields; it is not time-resolved atmospheric transport. The component animation
adds modeled PM2.5 components for explanation; it is not a physical plume
sequence.

## Thermal-power-only shutdown diagnostic

The marginal power signal can be isolated from the common GCAM NZK non-power
inventory with:

```bash
make inmap-gcam-nzk-power-only-poc-with-health \
  PYTHON_INTERPRETER=.venv/bin/python
```

The target selects the 2050 no-NZK-power and high-NZK-power jobs, omits the
non-power COARDS inventory from both InMAP TOMLs, runs them with the configured
fixed iteration count, and calculates power-only exposure and mortality. Its
run directory is
`results/runs/inmap/gcam_nzk_three_power_poc_2025_2050/power_only_poc_50_iterations/`.
This is a diagnostic of the currently encoded thermal inventory, not a
real-world shutdown estimate: power-sector primary PM2.5, NH3, and VOC remain
omitted and the solver is not converged.

## Production gate and next inputs

The paired configuration is
[`gcam_nzk_power_toggle_2025_2050.yaml`](../../configs/scenarios/gcam_nzk_power_toggle_2025_2050.yaml).
It uses `approved_factor_inventory` and `reviewed_coordinate_geometry`; it does
not fall back to the synthetic activity index, native GCAM emissions, or the
old four-cell proxy.

Attempting the final assembly with:

```bash
make build-inmap-gcam-nzk-toggle PYTHON_INTERPRETER=.venv/bin/python
```

fails closed today. To unblock it, the team must review and approve
denominator-compatible Korean factor rows and links, then supply reviewed
facility coordinates/stacks and diffuse-grid coordinates for every projected
inventory ID. Once those inputs are present, the same command builds the two
power-toggle InMAP bundles without changing scenario logic.
