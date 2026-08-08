# Synthetic GCAM-KAIST-shaped non-power activity fixture, 2023--2050

## Purpose and status

This fixture supplies deterministic non-power activity paths for input
validation, scenario plumbing, CAPSS-intensity smoke tests, and downstream
APHIAM development. The native `CORE_9_NZ` deliverable is now available, so
this fixture is retained only as a software-test path.

It is **not** a GCAM-KAIST model run, forecast, official scenario, or substitute
for the team-supplied file. Every detailed row and the metadata sidecar carry
the status:

```text
synthetic_activity_index_for_pipeline_testing_not_gcam_kaist_output
```

The assumptions are version controlled in
[`configs/scenarios/gcam_kaist_nonpower_proxy_2025_2050.yaml`](../../configs/scenarios/gcam_kaist_nonpower_proxy_2025_2050.yaml).

## Method

Activity is a normalized index rather than an invented physical quantity:

```text
2023 activity index = 100
2025 activity index = 100
2050 activity index = profile- and scenario-specific endpoint
```

Values for 2030, 2035, 2040, and 2045 are linearly interpolated:

```text
index(s, i, t) = 100 + (endpoint(s, i, 2050) - 100)
                       * (t - 2025) / (2050 - 2025)
```

The extra 2023 row lets the current MACRO/CAPSS integrator derive a base-year
intensity from the latest local CAPSS inventory. It does not imply that 2023
and 2025 physical activity were equal.

The three scenario names intentionally match the temporary KEPCO scenario
fixtures:

- `no_nzk`: current-policy-style path without accelerated net-zero transition;
- `nzk_low`: slower transition with residual direct fossil activity in 2050;
- `nzk_high`: faster electrification and fuel switching with minimal direct
  fossil activity in 2050.

The 2050 endpoints are transparent judgmental test assumptions. They encode
direction and approximate transition strength, not calibrated quantities.

## Outputs

Run:

```bash
make build-macro-nonpower-proxy PYTHON_INTERPRETER=.venv/bin/python
```

Generated, Git-ignored files are written under
`model_inputs/scenarios/nonpower_proxy_2025_2050/aphiam/`:

- `gcam_kaist_nonpower_activity_proxy_2023_2050.csv` and `.parquet`: rich
  inventory-ID table for 50 P1 activities, three scenarios, and seven years;
- `gcam_kaist_sector_fuel_activity_proxy_2023_2050.csv`: the existing
  five-column model-input shape;
- `gcam_kaist_sector_fuel_activity_proxy_2023_2050.audit.csv`: units, profiles,
  endpoints, rationales, and fixture labels for the compatibility rows;
- `gcam_kaist_nonpower_activity_proxy_summary.csv`: compact cluster and CAPSS
  sector checks;
- `gcam_kaist_nonpower_activity_proxy_2023_2050.metadata.json`: checksums,
  assumptions, source links, exclusions, row counts, and output paths.

The rich table includes:

```text
scenario, year, inventory_id, gcam_cluster, gcam_sector, gcam_subsector,
gcam_technology, gcam_fuel, activity, activity_unit,
reference_activity_unit, projection_profile, endpoint_index_2050,
include_in_emissions_model
```

`activity_unit` is always `index_2025_100`. `reference_activity_unit` preserves
the eventual physical denominator, such as `TJ fuel`, `vehicle-km`, `animal-year`,
or `tonne waste treated`.

The five-column compatibility file is exactly:

```text
scenario, year, sector, fuel, activity
```

Its sector and fuel keys are normalized to the 2023 CAPSS category/fuel keys so
the existing aggregate intensity integrator can consume it without a guessed
GCAM-to-CAPSS mapping.

## Integration smoke test

Run:

```bash
make validate-macro-nonpower-proxy PYTHON_INTERPRETER=.venv/bin/python
```

This regenerates the fixture and sends the five-column view through the existing
CAPSS intensity integrator using 2023 as the base year. Outputs are written to
the fixture's `integration/` subdirectory. With the full CAPSS input, the
diagnostics contain 13 expected
`capss_emissions_without_gcam_base_activity` rows: one for each fuel in the
deliberately excluded aggregate `에너지산업_연소` category. A valid run has no
`gcam_activity_without_capss_emissions` or
`gcam_activity_without_emission_factor` rows. At the 2023 index, modeled
emissions reconcile to the included CAPSS base emissions by sector, fuel,
scenario, and pollutant.

This reconciliation proves only that the input shape, category keys, base-year
denominators, scenario expansion, and multiplication logic work.

## Boundary safeguards

- `agr_fisheries_combustion` is retained in the detailed research table but
  has `include_in_emissions_model=false`. Emissions ownership is assigned to
  `trn_shipping_fishing` so the same fishing-vessel fuel is not counted twice.
- Aggregate CAPSS `에너지산업_연소` is excluded from the compatibility file.
  That category mixes power generation with non-power refining combustion and
  cannot be safely assigned at the current category-level integration.
- Purchased electricity has no direct non-power emissions. Upstream electricity
  remains in the power module.
- Technology, control, fleet, and route changes belong in annual effective
  emission factors. The activity fixture does not silently encode those changes.
- A missing or unresolved emission factor remains missing; it is never converted
  to zero.

## Appropriate and inappropriate uses

Appropriate:

- pipeline and schema testing;
- deterministic software tests;
- scenario scoping and joins;
- approximate sensitivity demonstrations;
- identifying data, crosswalk, factor, and spatialization gaps.

Inappropriate:

- reporting the values as GCAM-KAIST results;
- policy benefit or cost estimates;
- production emissions or health-impact estimates;
- calibration of physical activity quantities;
- replacing a future native GCAM-KAIST/MACRO delivery.

Production-oriented NZK work uses the
[native GCAM-KAIST interface](gcam_kaist_native_nzk_interface.md) without
changing the stable `inventory_id` taxonomy. Do not substitute this proxy when
the native pipeline blocks on a missing factor, conversion, or location.

## Structural references

- [GCAM-KAIST model reference card](https://www.iamcdocumentation.eu/GCAM-KAIST)
- [Public GCAM-KAIST 1.0 inputs and configurations](https://zenodo.org/records/14171830)
- [Korea 2050 Carbon Neutrality Scenarios](https://www.opm.go.kr/en/policies/carbon-neutrality-scenarios.do)
- [Repository non-power inventory](../datasets/nonpower_sector_inventory.md)
- [MACRO input integration](../datasets/macro_input_integration.md)
