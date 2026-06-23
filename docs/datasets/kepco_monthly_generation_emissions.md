# KEPCO Monthly Generation and Emissions Dataset

This document describes the processed monthly KEPCO subsidiary generation and
emissions dataset. This is the preferred dataset for near-term analysis. Work
on the annual plant-level panel is paused because its plant matching and annual
source integration are too messy for the current research needs.

The active dataset uses KEPCO-wide naming rather than "thermal" naming. The
included monthly emissions sources are mostly thermal subsidiaries, but the
research object is the KEPCO monthly generation-and-emissions panel. The KEPCO
nuclear subsidiary is not included because we did not find compatible monthly
pollutant mass emissions for it.

The main processed dataset is:

- `data/kepco/processed/kepco_monthly_generation_emissions.csv`

The column metadata file is:

- `data/kepco/processed/kepco_monthly_generation_emissions_metadata.csv`

## Current Coverage

Coverage values are defined by the generated outputs after a team member runs
the scripts. They are intentionally not hard-coded here because adding Midland
or refreshing source websites can change them.

Current-value variables:

- `{monthly_rows}`: rows in `kepco_monthly_generation_emissions.csv`
- `{monthly_start_date}`: first monthly observation date
- `{monthly_end_date}`: last monthly observation date
- `{plant_count}`: distinct `plant_name` values
- `{unit_reporting_identities}`: distinct source-reported unit/reporting
  identities
- `{numeric_unit_identities}`: distinct clean numeric unit identities
- `{source_dataset_counts}`: row counts by `source_dataset`
- `{subsidiary_company_counts}`: row counts by `subsidiary_company`
- `{energy_type_counts}`: row counts by cleaned `energy_type`
- `{nonmissing_value_counts}`: non-missing counts for generation, capacity,
  NOx, SOx, and dust/TSP

A local current-values file may be kept beside the processed data at:

- `data/kepco/processed/README.md`

## Unit of Observation

Each row is a monthly observation for a KEPCO subsidiary plant, unit, or
source-reported generating identity. The dataset is closer to unit resolution
than the annual plant panel because it preserves:

- `plant_name`
- `plant_number`
- `original_korean_unit_name`
- `source_dataset`

`unit/reporting identities` are counted using:

```text
source_dataset + plant_name + plant_number + original_korean_unit_name
```

This is the broadest fine-resolution identity. It preserves source-reported
unit labels even when they are not clean numeric unit numbers.

`numeric unit identities` are counted only when `plant_number` is populated:

```text
source_dataset + plant_name + plant_number
```

In plain terms, numeric unit identities are cleaner numbered units.
Unit/reporting identities are the finest identities available from the source,
including combined-cycle blocks, paired units, text unit labels, and rows where
the source does not provide a clean numeric unit.

## Fuel Categories

The monthly dataset uses cleaned fuel categories that preserve source detail
without forcing rows into broad mentor technology bins.

- `coal`: coal-fired generation rows.
- `natural_gas`: rows reported as gas/LNG only.
- `oil`: petroleum-derived oil fuel rows without gas/LNG.
- `oil_and_natural_gas`: mixed oil plus gas/LNG rows.
- `bio_oil_and_diesel`: rows involving bio-heavy-oil and diesel-type fuels.
- `unknown`: rows where the source fuel/energy type is missing or cannot be
  assigned confidently.

The mixed and specific oil categories are separated because they can have
different emissions behavior. In particular, `oil_and_natural_gas` should not
be treated as pure natural gas, and `bio_oil_and_diesel` should not be silently
collapsed into generic fossil oil.

## Main Columns

- `source_dataset`: source interim dataset identifier.
- `operator_category`: operator category; currently `kepco`.
- `observation_frequency`: observation frequency; currently `monthly`.
- `date`: observation month, stored as the first day of the month.
- `plant_name`: English plant name.
- `plant_number`: source-reported generating unit number where available.
- `plant_opening_date`: plant opening date.
- `plant_closing_date`: plant closing date.
- `plant_latitude`: plant latitude in WGS84 decimal degrees.
- `plant_longitude`: plant longitude in WGS84 decimal degrees.
- `subsidiary_company`: KEPCO subsidiary company name.
- `energy_type`: cleaned primary energy or fuel type.
- `energy_generated_mwh`: monthly electricity generation in MWh.
- `energy_capacity_mw`: installed generating capacity in MW.
- `nox`: monthly nitrogen oxides emissions in kilograms.
- `sox`: monthly sulfur oxides emissions in kilograms.
- `dust_tsp`: monthly total suspended particulate emissions in kilograms.
- `pollutant_measurement_basis`: pollutant measurement basis; currently `mass`.
- `nox_unit`, `sox_unit`, `dust_tsp_unit`: pollutant-specific canonical units.
- `emissions_mass_unit`: common pollutant mass unit; currently `kilograms`.
- `original_korean_plant_name`: original Korean plant name.
- `original_korean_unit_name`: original Korean generating unit name.
- `original_korean_note`: original Korean source note.

## Source Logic

The processed monthly dataset combines compatible KEPCO subsidiary generation
and pollutant-mass sources. It retains generation in MWh, capacity in MW, and
standardizes NOx, SOx, and dust/TSP emissions to kilograms.

The combined sources are generated from the source datasets included by the
current pipeline. The source list and row counts should be read from
`{source_dataset_counts}` after regeneration.

Current source families include KEPCO subsidiary data from East-West, Western,
Southern, South-East, and Midland Power where compatible monthly mass data are
available.

East-West and Western source values are converted from metric tonnes to
kilograms by multiplying by `1,000`. Southern and South-East values are already
reported in kilograms. Midland contributes facility-status rows where usable
mass-related information is available in the processed pipeline.

Oxygen, flue-gas flow, and temperature are not included in this processed
monthly mass dataset because they are not consistently populated across the
combined mass sources. Those variables remain in source-specific interim data
where available.

## Analysis Outputs

The current R analysis is:

- `analysis/kepco/kepco_monthly_analysis.R`

Key generated monthly fuel-analysis tables include:

- `results/tables/kepco/kepco_pollutant_summary_by_fuel.csv`
- `results/tables/kepco/kepco_ef_coverage_by_plant_fuel.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_generation_mwh.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_sox_ef.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_nox_ef.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_dust_tsp_ef.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_sox_emissions_kg.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_nox_emissions_kg.csv`
- `results/tables/kepco/kepco_fuel_type_monthly_dust_tsp_emissions_kg.csv`

Raw generation and raw emissions plots are generated by fuel type with a
6-month moving average. Emission-factor plots are also generated by fuel type
with a 6-month moving average.

## Regeneration

From the project root, regenerate the monthly KEPCO processed dataset with:

```bash
python -m nzk_aphiam.data.process.thermal
```

or:

```bash
make combine-kepco
```

Then rerun the R analysis with:

```bash
Rscript analysis/kepco/kepco_monthly_analysis.R
```

For a quick local summary:

```bash
python - <<'PY'
import csv
from collections import Counter

path = "data/kepco/processed/kepco_monthly_generation_emissions.csv"
with open(path, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

unit_reporting = {
    (
        row["source_dataset"],
        row["plant_name"],
        row["plant_number"],
        row["original_korean_unit_name"],
    )
    for row in rows
}
numeric_units = {
    (row["source_dataset"], row["plant_name"], row["plant_number"])
    for row in rows
    if row["plant_number"]
}

print("rows:", len(rows))
print("date range:", min(row["date"] for row in rows), "to", max(row["date"] for row in rows))
print("plants:", len({row["plant_name"] for row in rows}))
print("unit/reporting identities:", len(unit_reporting))
print("numeric unit identities:", len(numeric_units))
print("source datasets:", Counter(row["source_dataset"] for row in rows))
print("subsidiaries:", Counter(row["subsidiary_company"] for row in rows))
print("energy types:", Counter(row["energy_type"] or "unknown" for row in rows))
for col in ["energy_generated_mwh", "energy_capacity_mw", "nox", "sox", "dust_tsp"]:
    print(f"{col} non-missing:", sum(bool(row[col]) for row in rows))
PY
```

## Notes

For the foreseeable future, analysis should prioritize this monthly KEPCO
dataset rather than the annual plant-level panel. The monthly panel is more
directly tied to KEPCO subsidiary source data, preserves finer source-reported
unit/reporting identities, and avoids the heavier matching assumptions needed
for the annual plant-level "frankenstein" panel.
