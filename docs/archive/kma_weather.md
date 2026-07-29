# Archived KMA Hourly Weather Pipeline

> **Archived 22 July 2026.** The research team selected annual Global InMAP,
> which supplies global meteorology and built-in bias correction. Hourly KMA
> weather therefore does not support the active atmospheric-dispersion design.
> The implementation is retained for provenance and possible future reuse, but
> it is no longer exposed through Makefile targets or the active data packages.

## Purpose

This superseded pipeline collected meteorology intended to connect KEPCO plant
emissions to hourly AirKorea concentrations. The nine feature groups were:

1. temperature;
2. humidity and dew point;
3. precipitation amount, intensity, and occurrence;
4. station and sea-level pressure;
5. solar radiation and sunshine;
6. total/lower cloud cover and cloud-base height;
7. atmospheric stability indices and temperature-profile gradients;
8. radiosonde-derived mixing height and surface inversions; and
9. surface and height-resolved winds.

Wind direction and speed remain in the output because they are necessary for
plant-to-receptor transport features, even though they are not counted among
the requested additions to wind.

## Sources and coverage

The collector uses official KMA API Hub type-01 text endpoints:

- **ASOS:** hourly surface observations in KST. The period endpoint permits at
  most 31 days per request.
- **Radiosonde:** temperature, dew point, pressure, height, and winds at
  multiple vertical levels. KMA describes regular launches at 00 and 12 UTC;
  the collector requests those two times and does not pretend that missing
  launches are observations.
- **KMA radiosonde analysis:** CAPE, CIN, lifting indices, condensation levels,
  and other supplied stability fields.
- **Wind Profiler:** height-resolved horizontal and vertical wind. KMA reports
  coverage from 2004, varying by station. The project samples the point
  endpoint hourly rather than claiming all native 10-minute data.
- **Station information:** annual SFC, upper-air, and Wind Profiler station
  snapshots retain changing station membership and coordinates.

KMA requires one API key plus a separate usage activation for each endpoint.
The key is read only from `KMA_API_HUB_KEY` and is never written to errors,
snapshots, or metadata.

## Storage

Raw source columns are saved without imputation as immutable annual CSV
snapshots:

```text
data/archive/raw/weather/kma/<dataset>/<dataset>.source.<year>.csv
```

An existing year is reused unless `--overwrite` is explicit. Writes go through
a `.part` file and replace the target only after the full year succeeds.
`metadata.json` records source pages, timestamp conventions, hashes, sizes,
row counts, and request counts. The archived pipeline has no DVC or Makefile
target.

Processed annual partitions under `data/archive/processed/weather/kma/` include
`station_history`, `surface_hourly`, `radiosonde_profile`,
`stability_indices`, `upper_air_dispersion`, and, when downloaded,
`profiler_wind`.

## Current Coverage

Coverage values are defined by the generated outputs after a team member runs
the archived processor directly. They are intentionally not hard-coded here
because adding a year or the Wind Profiler batch changes them.

Current-value variables:

- `{rows_by_dataset}`: total rows and the processed year range for each of
  `station_history`, `surface_hourly`, `radiosonde_profile`,
  `stability_indices`, `upper_air_dispersion`, and `profiler_wind`

A local current-values file may be kept beside the processed data at:

- `data/archive/processed/weather/kma/README.md`

## Archived execution

The old implementation remains runnable only by explicit module path. This is
for provenance or a deliberately restored hourly-monitor study, not for the
active annual Global InMAP workflow.

```bash
PYTHONPATH=src python -m nzk_aphiam.archive.kma_weather.scrape \
  core --start-year 2001 --end-year 2024

PYTHONPATH=src python -m nzk_aphiam.archive.kma_weather.process \
  --start-year 2001 --end-year 2024
```

Wind Profiler collection remains a separate high-volume command:

```bash
PYTHONPATH=src python -m nzk_aphiam.archive.kma_weather.scrape \
  profiler --start-year 2015 --end-year 2015
```

## Derived fields

Surface KST timestamps are retained and also converted to UTC. Upper-air data
are already UTC. Meteorological wind direction is converted into eastward and
northward components using:

```text
u = -speed * sin(direction)
v = -speed * cos(direction)
```

Potential temperature is calculated from temperature and pressure. Estimated
mixing height is the first sounding level where potential temperature is at
least 2 K above the profile minimum, following the method documented for NOAA
HYSPLIT. A surface inversion is flagged when a layer is at least 2 K warmer
than the surface and its mean potential-temperature gradient is at least
0.005 K/m.

These values are sparse sounding-time estimates. The processor deliberately
does not interpolate them to every hour. Any later interpolation or
observation-to-grid model must be an explicit, documented modeling step.

## Request budget

The general KMA account limit advertised in June 2026 is 20,000 calls and 5 GB
per day. The CLI estimates requests before contacting KMA and refuses pulls
above `--max-requests`.

The core 2001–2024 pull is approximately 18,000 calls, dominated by twice-daily
radiosondes. Hourly Wind Profiler data require roughly 8,760 calls per year and
therefore use a separate command intended for year-by-year batches. Existing
annual snapshots cost no calls unless `--overwrite` is used.

## Limitations

- ASOS is spatially sparser than AWS. This first pipeline prioritizes richer,
  hourly ASOS variables; it does not make an impractical nationwide
  minute-level AWS pull under the standard request quota.
- Derived mixing height is sensitive to sparse vertical levels and missing
  soundings. It is not a direct KMA observation or a substitute for a
  meteorological reanalysis PBL-height field.
- The station networks change over time. Use annual station history rather
  than a current station list for spatial joins.
- Weather does not supply stack height, exhaust temperature, exit velocity,
  stack diameter, terrain, or building-downwash inputs.
- The current plant crosswalk has coordinates for only a subset of KEPCO
  plants; spatial source-receptor features require resolving the remaining
  plant locations.
