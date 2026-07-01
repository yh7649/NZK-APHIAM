# Weather-normalized augmented synthetic control

This pilot implements the two-stage design discussed for plant events. It uses
`rmweather` to standardize hourly pollution for meteorology and ridge-augmented
synthetic control (`augsynth`) on weekly outcomes. Actual wind remains available
for plume validation; it must not be inferred from the randomized-weather outcome.

## Required hourly input

Join the AirKorea QC output to the nearest defensible KMA observation before
running this workflow. The CSV must contain `datetime`, `monitor_id`, `pollutant`,
`concentration`, monitor `latitude` and `longitude`, and the KMA columns consumed
by `normalize_weather.R`. The panel command adds `plant_monitor_distance_km`
and `target_exposure` from those coordinates and winds. Preserve monitor type,
relocation flags, and known overlapping plant events when available.

Copy `configs/plant_events/example_event.yml`, replace all placeholders with a
single verified intervention, and run:

```bash
make ascm-normalize EVENT=my_event ASCM_INPUT=path/to/joined_hourly.csv
make ascm-panel EVENT=my_event
make ascm-estimate EVENT=my_event
```

The Python stage writes an explicit donor decision table and weekly panel under
`data/processed/synthetic_control/`. A donor is rejected for target proximity,
target exposure, insufficient pre-period coverage, or incompatible monitor type.
Exclusions for relocation and other contemporaneous plant events must be added to
the input/design before treating an estimate as causal.

The R stage writes the fit, textual summary, and gap plot under
`results/models/synthetic_control/`. Inspect pre-treatment fit and run in-space,
in-time, and leave-one-out placebos before reporting an estimate. The current
command is deliberately a single-event, single-pollutant pilot.
