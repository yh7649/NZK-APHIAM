# Archived Work

Archived code, documentation, reference inputs, and local data stay separated
by artifact type:

- [`annual_plant_generation_emissions.md`](annual_plant_generation_emissions.md)
  and [`annual_plant_panel_methods.md`](annual_plant_panel_methods.md): paused
  annual non-KEPCO panel; data belongs under
  `data/archive/{raw,interim,processed}/annual_panel/`.
- [`kepco_midland_concentration.md`](kepco_midland_concentration.md):
  superseded Midland concentration/flow estimator; data belongs under
  `data/archive/{raw,interim}/kepco_midland_concentration/`.
- [`kma_weather.md`](kma_weather.md): superseded KMA weather pipeline; data
  belongs under `data/archive/{raw,processed}/weather/kma/`.

Runnable archived Python is under `src/nzk_aphiam/archive/`. Archived,
hand-reviewed annual-panel reference inputs are under
`docs/references/archive/annual_panel/`. Archived workflows must not write into
active `data/raw/`, `data/interim/`, or `data/processed/` locations.
