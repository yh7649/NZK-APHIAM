# Thermal Data Pipeline

This document describes the source-specific scraping, cleaning, and processing
logic for the thermal power datasets. For installation, team onboarding,
citation, and the main analysis workflow, see the
[project README](../../../README.md).

## Common Commands

Run every thermal subsidiary scraper sequentially:

```bash
make scrape-thermal
```

This is a networked workflow that contacts data.go.kr and subsidiary websites.
Midland Power is included even though its current emissions API is not
sufficient for monthly emission-factor calculations. Individual subsidiary
and dataset targets are available through `make help`.

Rebuild every currently implemented cleaner:

```bash
make clean-thermal
```

Run the complete offline verification workflow using preserved raw files:

```bash
make verify-offline PYTHON_INTERPRETER=.venv/bin/python
```

## Shared Interim Schema

The subsidiary cleaners use a shared thermal schema containing the observation
date, English plant name, nullable unit number, subsidiary, energy type,
generation, capacity, pollutant measurements and units, and original Korean
source labels.

Nullable `plant_opening_date` and `plant_closing_date` columns are reserved for
documented plant metadata. Cleaners must not infer them from the first or last
observation in a source dataset.

Nullable `plant_latitude` and `plant_longitude` columns are also reserved for a
separate plant metadata dataset. Future coordinates should use WGS84 decimal
degrees (`EPSG:4326`) and consistently represent the plant site rather than
individual stacks or generating units.

## Western Power

Download and clean the preserved Western Power monthly source:

```bash
make scrape-western-power
make clean-western-power
```

The interim output is:

```text
data/power_generation/thermal/interim/western_power/western_power_monthly_generation_emissions.csv
```

The cleaner retains every source row. Western Power reports pollutant mass in
metric tonnes and does not report temperature.

The raw source does not include fuel type. The cleaner enriches `energy_type`
from official Korea Western Power plant and operating-history pages. Mapping
rules, effective dates, evidence, and source URLs are recorded in
[`references/thermal/western_power_energy_type_mapping.csv`](../../../references/thermal/western_power_energy_type_mapping.csv).

Pyeongtaek steam units are classified as `oil_and_natural_gas` through February
2020 and `natural_gas` from March 2020, following the documented start of
full-LNG operation on February 27, 2020.

## East-West Power

Download and clean the East-West Power monthly source:

```bash
make scrape-eastwest-power
make clean-eastwest-power
```

The interim output is:

```text
data/power_generation/thermal/interim/eastwest_power/eastwest_power_monthly_generation_emissions.csv
```

The cleaner preserves every monthly source row. Fuel mappings and their
official sources are recorded in
[`references/thermal/eastwest_power_energy_type_mapping.csv`](../../../references/thermal/eastwest_power_energy_type_mapping.csv).
The scraper also writes the enrichment source URLs into its raw JSON and
metadata outputs.

## Southern Power

Southern Power requires the shared data.go.kr API key and these endpoint
settings in `.env`:

```dotenv
DATA_GO_KR_API_KEY=...
SOUTHERN_POWER_EMISSIONS_API_URL=https://api.odcloud.kr/api/15099713/v1/uddi:e7ea7bfd-d0c4-4cb6-afea-95fa7821cb51
SOUTHERN_POWER_GENERATION_API_URL=http://apis.data.go.kr/B552520/GenInfo/getDataService
```

Download and clean both sources:

```bash
make scrape-southern-power
make clean-southern-power
```

Raw responses, CSV extracts, and redacted request metadata are saved under:

```text
data/power_generation/thermal/raw/southern_power/
```

The interim output is:

```text
data/power_generation/thermal/interim/southern_power/southern_power_monthly_generation_emissions.csv
```

Southern reports emissions in kilograms, which are retained without
conversion. Daily gross generation is summed by month and converted from kWh to
MWh. Fuel and source-granularity rules are recorded in
[`references/thermal/southern_power_energy_type_mapping.csv`](../../../references/thermal/southern_power_energy_type_mapping.csv).

Some emissions rows are more detailed than the generation records. The cleaner
aggregates Samcheok A/B stack rows to generating units and combined-cycle
components to plant level where a steam turbine is shared. Generation remains
null where the generation API has no safely matching record; it is not
fabricated or forward-filled.

## Combined Monthly Dataset

Combine the three interim datasets that currently report compatible monthly
pollutant mass and generation:

```bash
make combine-thermal
```

The processed output is:

```text
data/power_generation/thermal/processed/thermal_power_generation_emissions.csv
```

The command combines East-West, Western, and Southern Power. It checks every
input schema before concatenation, retains generation in MWh and capacity in
MW, and standardizes NOx, SOx, and dust mass to kilograms. East-West and
Western values are multiplied by 1,000 to convert metric tonnes to kilograms;
Southern values are already reported in kilograms.

Oxygen, flue-gas flow, and temperature are omitted from this processed monthly
mass dataset because they are empty across the three included sources. They
remain in source-specific interim datasets where reported.

The command also writes
`thermal_power_generation_emissions_metadata.csv` beside the processed data.
It contains ordered `varname` and `label` fields for every column, including
units in quantitative labels.

South-East is excluded because its available source reports daily
concentrations with undocumented units rather than monthly pollutant mass.
Midland is excluded until the requested monthly raw emissions data are
available.

## South-East Power

South-East Power publishes daily air-pollutant measurements through a signed
CSV export form:

```bash
make scrape-southeast-power
make clean-southeast-power
```

The scraper downloads calendar-year chunks, preserves each original CP949
response, writes a combined UTF-8 CSV, and records request metadata under:

```text
data/power_generation/thermal/raw/southeast_power/
```

Use `--reuse-existing-source` on the Python scraper command to resume from
preserved yearly files. Although data.go.kr advertises history from 2015, the
provider export currently begins on July 16, 2020.

The interim output is:

```text
data/power_generation/thermal/interim/southeast_power/southeast_power_daily_air_pollutant_measurements.csv
```

It retains reported NOx, SOx, dust, oxygen, flue-gas flow, and temperature.
The export does not document the pollutant concentration or flow units, so
those fields are marked `not_reported`. Generation, capacity, fuel type, and
emissions mass remain null. The cleaner does not attempt an unsupported
concentration-to-mass conversion.

## Midland Power

Midland Power exposes monthly generation and air-pollutant measurements through
data.go.kr XML APIs:

```bash
make scrape-midland-power
```

The commands retain source field names and values, save XML responses, CSV
extracts, and redacted metadata under:

```text
data/power_generation/thermal/raw/midland_power/
```

They refuse to replace existing outputs unless `--overwrite` is explicitly
provided. Optional endpoint overrides are
`MIDLAND_POWER_GENERATION_API_URL` and `MIDLAND_POWER_EMISSIONS_API_URL`.

The verified June 12, 2026 pull contains 4,424 generation records from January
2012 through May 2026 and 853 emissions records for five thermal plants. The
emissions API returns no records for December 2019, December 2020, or July
2023; the scraper preserves those source gaps.

The current emissions source is not used in the combined monthly mass dataset.
