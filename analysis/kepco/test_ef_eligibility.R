#!/usr/bin/env Rscript

source(file.path("analysis", "kepco", "ef_eligibility.R"))

pollutants <- data.frame(
  pollutant = c("nox", "sox", "dust_tsp"),
  ef = c("nox_kg_per_mwh", "sox_kg_per_mwh", "dust_tsp_kg_per_mwh"),
  label = c("NOx", "SOx", "TSP"),
  stringsAsFactors = FALSE
)

fixture <- data.frame(
  .ef_source_row_id = 1:9,
  source_dataset = "test",
  date = as.Date("2024-01-01"),
  plant_name = "Plant",
  plant_number = 1:9,
  reporting_unit_id = paste0("test:", 1:9),
  subsidiary_company = "Test Power",
  fuel_type_clean = "coal",
  technology = "conventional_steam_turbine",
  plant_province = "Test Province",
  row_status = "active_reported",
  energy_generated_mwh = c(1000, 1, 0, 1000, 1000, 1000, 1000, 1000, 1000),
  energy_capacity_mw = 100,
  generation_coverage_status = c(rep("complete", 8), "partial"),
  generation_reconciliation_status = NA_character_,
  audit_severity = c(
    NA, "warning", "warning", "warning", "warning", "critical", "critical", NA, NA
  ),
  audit_issue_codes = c(
    NA,
    "generation_very_low_nonzero",
    "emissions_with_zero_generation;generation_zero",
    "high_nox_emission_factor",
    "recent_shift_low_nox_mass",
    "generation_far_above_nameplate",
    "duplicate_unit_month",
    "negative_nox",
    NA
  ),
  nox = c(50, 1, 10, 500, 10, 50, 50, -1, 50),
  sox = 25,
  dust_tsp = 5,
  stringsAsFactors = FALSE
)
fixture$nox_kg_per_mwh <- with(
  fixture,
  ifelse(energy_generated_mwh > 0, nox / energy_generated_mwh, NA_real_)
)
fixture$sox_kg_per_mwh <- with(
  fixture,
  ifelse(energy_generated_mwh > 0, sox / energy_generated_mwh, NA_real_)
)
fixture$dust_tsp_kg_per_mwh <- with(
  fixture,
  ifelse(energy_generated_mwh > 0, dust_tsp / energy_generated_mwh, NA_real_)
)

eligibility <- build_ef_eligibility(fixture, pollutants)
nox <- eligibility[eligibility$pollutant == "nox", ]
row <- function(id) nox[nox$ef_source_row_id == id, ]

stopifnot(row(1)$operational_primary_included)
stopifnot(!row(2)$operational_primary_included)
stopifnot(row(2)$low_load_inclusive_included)
stopifnot(!row(3)$operational_primary_included)
stopifnot(!row(3)$very_low_generation)
stopifnot(!row(4)$operational_primary_included)
stopifnot(row(5)$operational_primary_included)
stopifnot(!row(5)$conservative_quality_included)
stopifnot(row(6)$operational_primary_included)
stopifnot(!row(6)$conservative_quality_included)
stopifnot(!row(7)$operational_primary_included)
stopifnot(!row(8)$operational_primary_included)
stopifnot(row(9)$operational_primary_included)
stopifnot(!row(9)$conservative_quality_included)
stopifnot(grepl("very_low_generation", row(2)$operational_primary_exclusion_reason))
stopifnot(grepl("nonpositive_generation", row(3)$operational_primary_exclusion_reason))
stopifnot(row(5)$recent_level_shift_review)

operational <- apply_ef_specification(
  fixture,
  eligibility,
  pollutants,
  "operational_primary"
)
inclusive <- apply_ef_specification(
  fixture,
  eligibility,
  pollutants,
  "low_load_inclusive"
)
stopifnot(is.na(operational$nox[2]), inclusive$nox[2] == 1)
stopifnot(is.na(operational$nox[4]), operational$sox[4] == 25)
stopifnot(operational$ef_specification[[1]] == "operational_primary")

normal <- operational[!is.na(operational$nox), ]
ratio_ef <- sum(normal$nox) / sum(normal$energy_generated_mwh)
weighted_ef <- weighted.mean(normal$nox_kg_per_mwh, normal$energy_generated_mwh)
stopifnot(isTRUE(all.equal(ratio_ef, weighted_ef)))

message("All deterministic KEPCO EF eligibility tests passed.")
