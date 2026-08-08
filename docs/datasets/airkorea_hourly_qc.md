# AirKorea hourly quality control

The canonical staged implementation and end-to-end commands are documented in
[`docs/methods/airkorea_monitor_workflow.md`](../methods/airkorea_monitor_workflow.md).
The older one-shot command described below remains available for small,
backward-compatible filtered runs, but it is not the resumable full-history
build.

The QC pipeline reads annual ZIP archives in place, converts their XLSX
workbooks to one canonical long table, and preserves every source observation
in `value_raw`.

First archive the approved current station registry. The API key is read from
`DATA_GO_KR_API_KEY` in `.env` and is never written to metadata or logs:

```bash
python -m nzk_aphiam.data.scrape.airkorea.stations
```

Then run a small year range first:

```bash
python -m nzk_aphiam.air_quality --years 2021 2022
```

The QC command reuses the archived registry. If it is absent, it fetches it
automatically. Pass `--refresh-stations` to replace the snapshot deliberately.

Thresholds and model settings live in `configs/air_quality_qc.yaml`. Outputs:

- `data/interim/air_quality/air_quality_hourly_qc.parquet`
- `data/interim/air_quality/airkorea_station_crosswalk.csv`
- `data/processed/air_quality/air_quality_monthly_raw.parquet`
- `data/processed/air_quality/air_quality_monthly_qc.parquet`

`value_analysis` is missing only for physically invalid values and isolated ML
anomalies that could actually be checked against nearby monitors. An ML flag is
otherwise retained as `ml_review`; a spatially shared spike is retained as
`supported_event`. No row is deleted.

The finalized annual files do not include coordinates, but they do preserve the
station code, name, and address reported in each year. The pipeline constructs
that historical identity table before ML and conservatively joins the current
official WGS84 registry. Exact historical-address matches are accepted. A
same-name station with a changed address remains unresolved rather than being
silently assigned the current location.

For moved or retired monitors, coordinates transcribed from the corresponding
Air Environment Annual Report station appendix can be supplied as CSV:

```text
monitor_id,year,latitude,longitude
111122,2005,37.570000,126.990000
```

Run it with:

```bash
python -m nzk_aphiam.air_quality --years 2005 \
  --historical-stations path/to/airkorea_historical_stations.csv
```

These code-and-year records receive `authoritative` confidence and override the
current-registry match. Unresolved stations retain ML flags for review rather
than being treated as spatially unsupported sensor failures.

Weather normalization is intentionally outside this module. It should consume
the QC output later and write a separate
`air_quality_monthly_weather_normalized.parquet` sensitivity dataset.

## Current Coverage

Coverage values are defined by the generated outputs after a team member runs
the pipeline. They are intentionally not hard-coded here because processing a
different year or pollutant range changes them.

Current-value variables:

- `{hourly_rows}`: rows in `air_quality_hourly_qc.parquet`
- `{hourly_date_range}`: first and last observation datetime
- `{monitor_count}`: distinct `monitor_id` values
- `{monitor_year_count}`: distinct monitor-year rows in the station crosswalk,
  and how many resolved to coordinates
- `{pollutant_counts}`: hourly row counts by `pollutant`
- `{qc_status_counts}`: hourly row counts by `qc_status`
- `{monthly_row_counts}`: row counts for the raw and QC monthly aggregates

A local current-values file may be kept beside the processed data at:

- `data/processed/air_quality/README.md`

Because the QC command accepts `--years` and `--pollutants` filters, this
local file only reflects whichever run last wrote it; it is not necessarily a
full-history snapshot unless the pipeline was run over every year.
