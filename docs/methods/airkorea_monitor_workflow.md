# AirKorea monitor cleaning, aggregation, and InMAP bias correction

This is the canonical workflow for converting the preserved AirKorea annual
ZIP/XLSX archives into a canonical row-preserving table, auditable hourly QC,
annual particulate-matter summaries, and an optional InMAP bias-correction
grid.

The workflow is deliberately resumable by reporting year and pollutant. Raw
source observations are never deleted or overwritten. Generated data remain
under ignored `data/interim/air_quality/` and `data/processed/air_quality/`
locations.

## End-to-end command

Run every available archive and pollutant:

```bash
make airkorea-monitor-workflow PYTHON_INTERPRETER=.venv/bin/python
```

For the finalized PM history needed for the PI handoff, excluding the
provisional partial 2026 archive:

```bash
make airkorea-monitor-workflow \
  PYTHON_INTERPRETER=.venv/bin/python \
  AIRKOREA_WORKFLOW_ARGS="--start-year 2001 --end-year 2025 --pollutants PM10 PM25"
```

Existing partitions with matching inputs and settings are reused. Use
`AIRKOREA_WORKFLOW_ARGS="... --overwrite"` only when deliberately replacing
partitions after a source or configuration change.

The direct Python interface is:

```bash
PYTHONPATH=src .venv/bin/python \
  -m nzk_aphiam.air_quality.monitor_workflow all
```

## Stage 1: canonical row-preserving merge and coordinate crosswalk

Command:

```bash
make airkorea-canonicalize PYTHON_INTERPRETER=.venv/bin/python
```

Each XLSX member is standardized independently and written to:

```text
data/interim/air_quality/raw_merged/
  manifest.json
  year=YYYY/part-NNNN.parquet
```

The canonical wide schema has one output row per source workbook row. It uses a
fixed set of identity, provenance, and pollutant columns:

- `source_record_id`, `reporting_year`, `monitor_id`, `datetime`;
- `measurement_datetime_raw`, `region`, `network_type`, `station_name`,
  `address`;
- `SO2`, `CO`, `O3`, `NO2`, `PM10`, `PM25`;
- source archive, workbook, row number, checksum, and provisional status.

The manifest records source checksums, reported pollutants, row counts, date
ranges, and every output part. The six pollutant columns share one schema even
when an older workbook did not report PM2.5. This is the one full,
row-preserving table in the workflow; every later stage carries only what it
needs plus `source_record_id`, so a value's original provenance is always
traceable back here rather than duplicated at every stage.

Canonicalization also builds a monitor-year coordinate dimension from
historical station codes, names, addresses, regions, and network types in the
finalized archives, matching those identities conservatively to the current
official WGS84 station registry. Exact or containment-supported address
matches are accepted; name-only matches after an address change remain
unresolved. Resolving spatial identity here, before any cleaning runs, means
the coordinates are available to the forest model as an optional feature and
to the spatial cross-check in Stage 2, rather than being attached afterward.

Optional authoritative historical coordinates can be supplied with:

```bash
AIRKOREA_WORKFLOW_ARGS="--historical-stations path/to/stations.csv"
```

The reference must contain:

```text
monitor_id,year,latitude,longitude
```

Attribute outputs (small — one row per monitor-year):

```text
data/interim/air_quality/airkorea_station_crosswalk.csv
data/processed/air_quality/airkorea_monitor_year_attributes.{csv,parquet}
```

## Stage 2: rules, random-forest anomaly detection, and spatial confirmation

Command:

```bash
make airkorea-clean PYTHON_INTERPRETER=.venv/bin/python
```

Output:

```text
data/processed/air_quality/hourly_qc/
  manifest.json
  year=YYYY/pollutant=POLLUTANT/air_quality_hourly_qc.parquet
```

This is a single resumable pass per year-pollutant partition:

1. joins the Stage 1 coordinate crosswalk in memory;
2. flags AirKorea missing sentinels, nulls, impossible values, flatlines,
   jumps, missing monitor IDs, duplicate keys, and conflicting duplicates;
3. creates calendar and within-monitor lag features (plus coordinates, when
   available, as optional model features);
4. fits a separate time-blocked, out-of-fold random forest for each
   year-pollutant partition;
5. compares ML-flagged residuals against coordinate-resolved monitors within
   the configured radius and resolves the final `qc_status`.

The maximum forest training sample is configured in
`configs/air_quality_qc.yaml`. Capping training rows bounds memory without
changing the full set of out-of-fold predictions.

Spatially shared residuals are retained as `supported_event`. Isolated
residuals with an available spatial comparison are labeled `sensor_anomaly`
and masked from `value_analysis`. Flags without enough spatial evidence remain
`ml_review`. Physically invalid values and conflicting duplicates are also
masked. No source row is deleted, and `value_raw` is preserved throughout —
but the output table only carries the columns this and later stages actually
use (identity keys, the pollutant value, and QC results), not the full set of
descriptive/provenance columns from Stage 1; those remain traceable via
`source_record_id` in the canonical table if ever needed for audit. Monitor
coordinates themselves are not persisted here either — they are cheap to
re-join at the annual grain in Stage 3, so keeping them out of this
hourly-grain table avoids duplicating them across every partition.

## Stage 3: monthly and annual PM aggregation

Command:

```bash
make airkorea-aggregate PYTHON_INTERPRETER=.venv/bin/python
```

The AirKorea `01` through `24` hour-ending convention is translated to the
corresponding hour starts before aggregation. Consequently, hour `24` remains
part of its source reporting day rather than leaking into the following day,
month, or year.

The default PM calculation is:

1. collapse exact duplicate monitor-hour keys;
2. calculate a daily mean only when at least 18 of 24 hourly values remain
   valid;
3. calculate a quarterly mean only when at least 75% of calendar days have a
   valid daily mean;
4. calculate the annual mean as the equal-weighted mean of four valid quarterly
   means;
5. require all four valid quarters and a non-provisional archive for
   `analysis_ready=true`.

Incomplete estimates remain in diagnostic columns but `annual_mean` is missing
until the strict rule is met. This follows the general EPA 75% completeness
principle and the PM annual-standard use of quarterly means. The linked ECHO
page is specifically a hazardous-air-pollutant display method and is not
treated as the PM2.5 regulatory design-value algorithm:

- <https://echo.epa.gov/help/ecatt/air-monitoring-station-data-calculations>
- <https://aqs.epa.gov/aqsweb/documents/about_aqs_data.html>
- <https://aqs.epa.gov/aqsweb/documents/AQS_Data_Dictionary.html>

Canonical outputs:

```text
data/processed/air_quality/air_quality_monthly_raw.parquet
data/processed/air_quality/air_quality_monthly_qc.parquet
data/processed/air_quality/airkorea_annual_pm_monitor.parquet
data/processed/air_quality/airkorea_annual_pm_monitor.csv
data/processed/air_quality/aggregates/manifest.json
```

The CSV is the PI-facing annual monitor handoff. It carries completeness
statistics, `analysis_ready`, monitor coordinates, historical identity, and
coordinate-match provenance. PM2.5 is available from 2014 onward; earlier
archives only contribute PM10.

## Optional InMAP grid bias correction

The grid stage samples an annual InMAP PM2.5 field at the AirKorea monitor
locations, calculates `observed - modeled` residuals, and interpolates those
residuals to grid-cell centroids. It does not interpolate raw observations as
if they were a complete measured surface.

Run it after aggregation:

```bash
PYTHONPATH=src .venv/bin/python \
  -m nzk_aphiam.air_quality.monitor_workflow grid \
  --inmap-grid path/to/inmap_output.gpkg \
  --grid-year 2021
```

Or include it in the end-to-end Make target:

```bash
make airkorea-monitor-workflow \
  PYTHON_INTERPRETER=.venv/bin/python \
  AIRKOREA_WORKFLOW_ARGS="--start-year 2014 --end-year 2025 --pollutants PM25" \
  AIRKOREA_INMAP_GRID=path/to/inmap_output.gpkg \
  AIRKOREA_GRID_YEAR=2021
```

The input grid must have CRS metadata and `TotalPM25`, or the five InMAP
component fields needed to construct it. The output GeoPackage contains the
original modeled value, IDW residual correction, interpolation uncertainty,
nearest-monitor distance, corrected value, and a flag for corrections floored
at zero. A monitor/model comparison table and leave-one-out diagnostic are
written beside it.

Default output:

```text
data/processed/air_quality/inmap_bias_correction/
  year=YYYY/
    inmap_pm25_bias_corrected.gpkg
    monitor_model_comparison.{csv,parquet}
    manifest.json
```

Gridded corrections outside the configured maximum monitor distance remain
missing rather than being extrapolated nationally without support.
