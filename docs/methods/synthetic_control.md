# Weather-normalized augmented synthetic control

This pilot implements the two-stage design discussed for plant events. It uses
`rmweather` to standardize hourly pollution for meteorology and ridge-augmented
synthetic control (`augsynth`) on weekly outcomes. Actual wind remains available
for plume validation; it must not be inferred from the randomized-weather outcome.

The pilot remains available, but the repository no longer provides an active
KMA weather-ingestion dependency. The KMA collector and processor were archived
on 22 July 2026 when the main atmospheric-dispersion design moved to annual
Global InMAP. See [`docs/archive/kma_weather.md`](../archive/kma_weather.md) if
this hourly design is deliberately restored.

## Required hourly input

Supply an hourly AirKorea QC table already joined to a defensible external
meteorology source before running this workflow. The CSV must contain `datetime`,
`monitor_id`, `pollutant`, `concentration`, monitor `latitude` and `longitude`,
and the meteorology columns consumed by `normalize_weather.R`. The panel command
adds `plant_monitor_distance_km` and `target_exposure` from those coordinates and
winds. Preserve monitor type, relocation flags, and known overlapping plant events
when available.

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
