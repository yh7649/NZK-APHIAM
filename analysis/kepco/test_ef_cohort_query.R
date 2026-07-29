#!/usr/bin/env Rscript

source(file.path("analysis", "kepco", "query_ef_cohort.R"))

fixture <- data.frame(
  date = as.Date(c("2017-01-01", "2017-02-01", "2017-01-01", "2017-02-01")),
  year = 2017L,
  month = c("2017-01", "2017-02", "2017-01", "2017-02"),
  province = c("A", "A", "B", "B"),
  fuel = "coal",
  technology = "conventional_steam_turbine",
  plant = c("Plant 1", "Plant 1", "Plant 2", "Plant 2"),
  plant_name = c("Plant 1", "Plant 1", "Plant 2", "Plant 2"),
  subsidiary = "Test Power",
  subsidiary_company = "Test Power",
  unit = c("A:1", "A:1", "B:1", "B:1"),
  plant_unit_id = c("A:1", "A:1", "B:1", "B:1"),
  energy_generated_mwh = c(100, 300, 100, 100),
  nox = c(10, 60, 20, NA),
  sox = c(5, 15, 10, 10),
  dust_tsp = c(1, 3, 2, 2),
  stringsAsFactors = FALSE
)

result <- query_kepco_ef(
  fixture,
  selected_pollutants = c("nox", "sox", "dust_tsp"),
  group_by = "province",
  min_coverage_pct = 75
)

a_nox <- result[result$province == "A" & result$pollutant == "nox", ]
b_nox <- result[result$province == "B" & result$pollutant == "nox", ]
stopifnot(isTRUE(all.equal(a_nox$ef_kg_per_mwh, 70 / 400)))
stopifnot(a_nox$generation_coverage_pct == 100)
stopifnot(is.na(b_nox$ef_kg_per_mwh))
stopifnot(b_nox$estimate_status == "suppressed_low_coverage")
stopifnot(b_nox$generation_coverage_pct == 50)

compact <- compact_kepco_ef_query(
  result,
  group_by = "province",
  selected_pollutants = c("nox", "sox", "dust_tsp")
)
stopifnot(nrow(compact) == 2)
stopifnot(isTRUE(all.equal(compact$nox_ef_kg_per_mwh[compact$province == "A"], 0.175)))
stopifnot(is.na(compact$nox_ef_kg_per_mwh[compact$province == "B"]))
stopifnot(compact$minimum_pollutant_coverage_pct[compact$province == "B"] == 50)

slide <- slide_kepco_ef_query(
  compact,
  group_by = "province",
  selected_pollutants = c("nox", "sox", "dust_tsp")
)
stopifnot(identical(
  names(slide),
  c(
    "Province", "NOx EF (kg/MWh)", "SOx EF (kg/MWh)", "TSP EF (kg/MWh)",
    "Plants", "Generation (GWh)", "Minimum coverage (%)"
  )
))
stopifnot(slide$`NOx EF (kg/MWh)`[slide$Province == "A"] == 0.175)

parsed <- parse_query_args(c(
  "--year", "2017", "--fuel=coal", "--pollutants", "all",
  "--group-by", "year,province"
))
stopifnot(parsed$year == "2017")
stopifnot(parsed$fuel == "coal")
stopifnot(parsed$pollutant == "all")
stopifnot(parsed$group_by == "year,province")

message("All deterministic KEPCO EF cohort-query tests passed.")
