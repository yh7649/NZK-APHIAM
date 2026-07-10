# Teammate-compiled Korean power-plant roster

## Preserved source

- File: `province_level_power.xlsx`
- Received: 2026-06-30
- Contributor: project teammate (name and original source list not recorded here)
- SHA-256: `86591641ba639bb552cc0f8ed955fa41c02d450c29c528672c8a5bad771f749a`
- Size: 5,594,188 bytes

This workbook is a useful reference and crosswalk aid. It should remain
unchanged; any cleaning or normalization should write a separate interim file.
Because it is a teammate-compiled secondary dataset, use it as supporting
evidence rather than automatically overriding provider records.

## Workbook inventory

| Sheet | Worksheet extent | Approximate main-roster records | Notable fields |
|---|---:|---:|---|
| Coal (27.1%,36.3GW) | 67 rows, 18 columns | 65 | name/unit, capacity, province, location, coordinates, completion, retirement, notes |
| NG (25.2%, 33.8GW) | 122 rows, 17 columns | 121 | name, capacity, province, location, coordinates, completion, retirement, notes/sources |
| Group energy (8.1%,10.9GW) | 98 rows, 27 columns | 94 in the EPSIS roster | several side-by-side CHP tables, including coordinates in the smaller project table |
| Nuclear (17.4%, 23.3GW) | 31 rows, 15 columns | 30 | name, capacity, province, location, coordinates, completion, retirement, sources |
| Solar (13.6%, 18.2GW) | 185,131 rows, 29 columns | 185,129 in the EPSIS roster | large name/capacity/province/location roster plus smaller project and province tables |
| Wind (1.3%, 1.7GW) | 197 rows, 42 columns | 196 in the EPSIS roster | project year/name/capacity/type/province/location/cost plus EPSIS roster |
| Biomass (1.0%, 1.4 GW) | 101 rows, 11 columns | 100 | name, capacity, province, location |
| Hydro + Pumped (5.1%, 6.8 GW) | 244 rows, 19 columns | 242 | name, capacity, type, province, location, completion, retirement, notes |
| etc (1.3%, 1.7 GW) | empty | 0 | no populated cells |
| 2021,2025 By Fuel Type | 45 rows, 22 columns | n/a | province-level capacity by fuel for 2021 and 2025 |

Counts describe populated worksheet cells, not a validated count of distinct
physical plants. Some rows represent generating units or combined-cycle
components, and duplicate names may be legitimate or unresolved.

## Interpretation cautions

- Sheets contain multiple side-by-side tables; do not import each rectangular
  worksheet as though it were one tidy table.
- Capacity units are not uniform. For example, the coal header says kW while
  values such as 1,040 appear to be MW-scale; gas and CHP EPSIS tables contain
  kW-scale values, while several other sheets explicitly use MW.
- Completion and retirement values are often encoded as `YYYY.M`; zero usually
  appears to mean no retirement recorded, not the calendar year zero.
- Coordinates are frequently stored as one text field (`latitude, longitude`)
  and are absent from many EPSIS-derived roster sections.
- Province names use both current and historical Korean forms. Normalize them
  through the project's geography crosswalk before aggregation.
- Sheet-title percentages and GW totals appear to describe a snapshot; the
  workbook does not state a single, explicit as-of date for every table.
- Source notes mention EPSIS and, in places, additional or individually
  searched sources. Row-level provenance is incomplete, so important matches
  should be checked against the original provider.
