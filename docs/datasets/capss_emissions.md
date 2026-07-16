# CAPSS emissions statistics

CAPSS annual detailed emissions workbooks are downloaded from the National Air
Emission Inventory and Research Center board:

- Source board: `https://www.air.go.kr/article/list.do?boardId=10&menuId=32`
- By-sector validation page: `https://www.air.go.kr/capss/emission/sector.do?menuId=30`
- By-province validation page: `https://www.air.go.kr/capss/emission/sido.do?menuId=31`

Run:

```bash
make scrape-capss-emissions
make process-capss-emissions
make export-capss-power-fuel-technology
```

Raw workbooks are saved unmodified under:

- `data/raw/capss/emissions_statistics/`

Parsed long-form files are written under:

- `data/interim/capss/emissions_statistics/capss_emissions_tidy_{year}.parquet`
- `data/interim/capss/emissions_statistics/capss_emissions_tidy.parquet`
- `data/interim/capss/emissions_statistics/capss_emissions_tidy.metadata.json`

Power-sector fuel and official-technology exports are written under:

- `data/processed/capss/power_fuel_technology_detailed_2016_2023.parquet`
- `data/processed/capss/power_fuel_technology_detailed_2016_2023.csv`
- `data/processed/capss/power_fuel_technology_2016_2023.parquet`
- `data/processed/capss/power_fuel_technology_2016_2023.csv`
- `data/processed/capss/power_fuel_technology_2016_2023_wide.csv`
- `results/tables/capss/capss_key_fuel_technology_2016_2023_tonnes.csv`
- `results/diagnostics/capss/power_fuel_technology_unmapped_labels.csv`
- `results/diagnostics/capss/power_fuel_technology_validation.csv`

The tidy table preserves native workbook granularity:

```text
year, sub_district_code, sub_district_name, source_category,
source_subcategory, fuel_type, pollutant, emissions_kg
```

Korean source labels are retained alongside normalized labels, including
`source_category_ko`, `source_midcategory_ko`, `source_subcategory_ko`,
`fuel_category_ko`, and `fuel_type_ko`. The source workbook does not include an
official 시군구 code, so `sub_district_code` is intentionally missing until an
external administrative-code crosswalk is joined.

The processor extracts the workbook unit string per sheet, records observed
pollutants per year, and logs missing pollutants relative to the expected set:
`TSP`, `PM2.5`, `PM10`, `SOx`, `NOx`, `VOCs`, `NH3`, `CO`, and `BC`. Do not
assume uniform pollutant coverage across years; use the metadata.

CAPSS taxonomy changes are flagged in metadata using these periods:

- `pre_2007`
- `2007_2010`
- `2011_2014`
- `2015_plus`

CAPSS documentation notes source-classification expansions in 2007, 2011, and
2015. Biomass burning and fugitive dust categories are expected from 2015 onward.

The public CAPSS/SEMS pages describe the emissions-source management system, but
the emissions-statistics board does not expose a facility coordinate download.
Point-source-resolved downscaling should be treated as a separate SEMS/CAPSS
access task rather than a blocker for this downloader.

## Power-sector fuel and technology export

The power export reads the tidy CAPSS Parquet; it does not reparse Excel. It
retains only:

```text
source_category_ko == "에너지산업 연소"
source_midcategory_ko in {"공공발전시설", "민간발전시설"}
```

The exported `technology_official_ko` field is CAPSS `배출원소분류`
(`source_subcategory_ko`). This is a combustion-equipment classification, not a
generator ontology. In particular, `1,2,3종(보일러)` is retained as the official
CAPSS label and translated only descriptively as `Boiler, Classes 1-3`.

Emissions are parsed as kilograms per inventory year and converted to tonnes
only with `emissions_tonnes = emissions_kg / 1000`. The 2016--2023 public-plus-
private national output validates against the 2021 reference fuel/equipment
totals for bituminous coal boiler, anthracite boiler, LNG gas turbine, LNG
boiler, and B-C oil internal-combustion generation within a small floating-point
tolerance.

Known scope limitations:

- CAPSS public/private power facilities and KEPCO subsidiary EF coverage are not
  the same fleet boundary.
- CAPSS equipment labels, KEPCO technology labels, and MACRO technology labels
  are separate ontologies and must be aligned through a documented crosswalk.
- The detailed workbooks include municipality names but not official 시군구 codes.
