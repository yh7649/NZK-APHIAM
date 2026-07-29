# KEPCO-only thermal fleet scenario fixtures, 2025--2050

This workflow supplies temporary, deterministic power-sector inputs while the
production MACRO reference and Net Zero Korea pathways are unavailable. It is a
proof-of-concept fixture for pipeline testing, not an energy-system forecast or a
substitute for the MACRO team deliverable.

The fixture treats the KEPCO roster as the entire Korean thermal fleet, as requested,
and excludes non-KEPCO plants and non-thermal generation. One detailed row represents
a KEPCO generating unit or source reporting boundary. `plant_id` groups rows at the
same physical plant.

## Scenario families

Two separate fixture families coexist:

1. The original proportional family is retained unchanged for comparison and
   backward-compatible pipeline tests.
2. The newer unit-retirement family retires complete generating-unit/reporting
   boundaries. It is the more realistic plant-allocation proof of concept.

Both families contain 2025, 2030, 2035, 2040, 2045, and 2050.

### Original proportional family

Targeted generation and its associated annual mass emissions are scaled by `1.0`,
`0.8`, `0.6`, `0.4`, `0.2`, and `0.0`.

| Scenario | 2050 endpoint | Intermediate rule |
|---|---|---|
| `no_nzk` | Hold all KEPCO thermal generation at the proxy baseline | No reduction |
| `nzk_low` | Coal, oil, and bio-oil/diesel reach zero; LNG and biomass remain | Linear pro-rata phase-down of targeted fuels |
| `nzk_high` | All KEPCO thermal generation reaches zero | Linear pro-rata phase-down of every fuel |

### Whole-unit retirement family

| Scenario | 2050 endpoint | Intermediate rule |
|---|---|---|
| `no_nzk_fleet_hold` | Hold all KEPCO thermal units and generation at the proxy baseline | No retirement |
| `nzk_low_unit_retirement` | Retire all coal, oil, and bio-oil/diesel units; retain LNG and biomass | Whole targeted units leave at five-year milestones |
| `nzk_high_unit_retirement` | Retire every KEPCO thermal unit | Whole units leave at five-year milestones |

The retirement order is intentionally simple and auditable:

1. Documented unit closure dates take precedence and map to the first scenario
   snapshot after the closure. For example, a 2029 closure is absent in 2030, while
   a 2030 closure is absent in 2035.
2. Remaining targeted units are ranked by oldest commissioning year, lowest 2024
   baseline capacity factor, highest combined NOx-plus-SOx emissions intensity, and
   finally stable `unit_id`.
3. At each milestone, ranked units retire until cumulative retired baseline
   generation meets or exceeds the 20%, 40%, 60%, 80%, or 100% envelope. The
   threshold can be overshot because a unit is never divided.
4. An operating unit remains at its baseline generation and emissions until its
   assigned milestone, then both become zero. Thus row-level generation multipliers
   are only `1` or `0`, never fractional.

This is a deterministic fallback allocation, not an inference that the ordering is
official or least-cost. The output exposes `scenario_retirement_year`,
`scenario_retirement_basis`, `retirement_priority_rank`,
`baseline_capacity_factor`, and the priority pollution-intensity metric for audit.

The endpoints are patterned after Korea's official 2050 Carbon Neutral Scenarios:
Scenario A stops coal and LNG generation, while Scenario B stops coal and retains
61.0 TWh of LNG generation. The fixtures do **not** claim that their intermediate
years, unit allocation, or retained LNG quantity are official.

Official source:

- [Korea 2050 Carbon Neutral Scenarios](https://www.2050cnc.go.kr/storage/board/base/2021/10/26/BOARD_ATTACH_1635231399780.pdf),
  transition-sector assumptions and 2050 generation table on PDF page 6.

## Baseline and inventory construction

The scenario year begins in 2025, but the local 2025 KEPCO extract is not a complete
national calendar-year panel: East-West Power is absent and Western Power ends in
June. The fixture therefore uses the complete 2024 calendar year as a transparent
2025 proxy. This also follows EPSIS's convention of distinguishing finalized annual
statistics from provisional current-year values.

- [EPSIS generation by energy source](https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGesGrid.do?locale=eng&menuId=060102)
  supplies official national context; it is not used to rescale KEPCO rows.
- Missing unit-month generation is annualized by multiplying the available annual
  sum by 12 divided by the number of non-missing unit-months.
- Fuel and technology are the unit's 2024 operating classifications.
- NOx, SOx, and TSP mass inputs equal scenario generation times the 2024 KEPCO
  generation-weighted fuel-technology emission factor. Fallbacks use fuel and then
  all-thermal factors, with the selected level recorded on every row.
- TSP remains `dust_tsp_kg`; it is not relabeled as primary PM2.5.
- `pm25_kg`, `nh3_kg`, and `voc_kg` are zero-valued omitted inputs, not assertions
  that real emissions are zero.
- Stack height, diameter, temperature, and velocity use the existing observed-first
  stack hierarchy. Each stack field includes its own provenance column.
- Documented retirement dates are retained as metadata but are not imposed on the
  `no_nzk` counterfactual.

The starting proxy contains 94 unit/reporting-boundary rows at 31 plants and
184.126 TWh of annual generation. Both families have the same endpoint checks:

| Scenario | 2050 generation |
|---|---:|
| `no_nzk` | 184.126 TWh |
| `nzk_low` | 40.178 TWh (LNG and biomass only) |
| `nzk_high` | 0 TWh |

## Generate the files

Generate the original proportional family:

```bash
make kepco-poc-scenarios PYTHON_INTERPRETER=.venv/bin/python
```

The ignored, reproducible outputs are written under
`data/processed/kepco/scenarios/poc_2025_2050/`:

- `kepco_thermal_fleet_scenarios_2025_2050.csv` and `.parquet`: detailed
  plant/unit scenario inventory with generation, location, emissions, and stacks;
- `macro_generation_scenarios_2025_2050.csv`: the existing five-column
  `Scenario, Year, Province, Technology, Generation_TWh` MACRO input shape;
- `kepco_thermal_fleet_scenario_summary.csv`: fuel-level endpoint and mass checks; and
- `macro_generation_scenarios_2025_2050.metadata.json`: checksums, assumptions,
  sources, and row counts.

Four stacked-area PNGs are written under
`results/figures/kepco/poc_scenarios/`: one per scenario and one three-panel
comparison. Fuel colors and the generation axis are identical across panels so the
phaseout paths can be compared directly.

Generate the separate whole-unit retirement family:

```bash
make kepco-poc-retirement-scenarios PYTHON_INTERPRETER=.venv/bin/python
```

The same detailed, Parquet, MACRO-shaped, summary, and metadata filenames are
written under the distinct
`data/processed/kepco/scenarios/poc_2025_2050_unit_retirement/` directory. Its
`kepco_unit_retirement_schedule.csv` is a one-row-per-scenario-unit audit table of
the assigned exits. Stepwise charts are under
`results/figures/kepco/poc_scenarios_unit_retirement/`. Generating this family does
not overwrite the original files.

Generated `data/` and `results/` artifacts remain ignored and must not be committed.

## Exercise the existing inventory pipeline

The pipeline now accepts a local generation-table override. This command compares
the no-policy and high-Net-Zero endpoints and builds the complete plant allocation,
emissions, stack diagnostics, figures, and InMAP point inputs without running InMAP:

```bash
make peng-mvp-inventory \
  PYTHON_INTERPRETER=.venv/bin/python \
  PENG_MVP_ARGS="--macro-generation data/processed/kepco/scenarios/poc_2025_2050/macro_generation_scenarios_2025_2050.csv --target-year 2050 --reference-scenario no_nzk --policy-scenario nzk_high --force"
```

Replace `nzk_high` with `nzk_low` for the lower-ambition comparison. Zero-generation
2050 groups are retained through fleet allocation, so a fully phased-out scenario
remains present for differencing and InMAP input generation.

For the whole-unit family, point `--macro-generation` at
`poc_2025_2050_unit_retirement/macro_generation_scenarios_2025_2050.csv` and use
`no_nzk_fleet_hold` with either `nzk_high_unit_retirement` or
`nzk_low_unit_retirement`.

## Interpretation limits

The fixtures hold demand, efficiency, emission factors, and non-targeted generation
constant. They do not model replacement renewables, storage, nuclear generation,
dispatch, capacity adequacy, CCS, hydrogen/ammonia co-firing, fuel prices, or new
sites. The newer family assigns a unit-specific retirement order but does not
optimize or forecast that order. Replace both the aggregate MACRO-shaped input and
these simplifying rules when the team scenarios arrive.
