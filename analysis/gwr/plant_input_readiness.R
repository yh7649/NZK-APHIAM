#!/usr/bin/env Rscript
# Plant-side descriptive readiness tables. These are input diagnostics, not GWR results.
source(file.path("analysis", "R", "paths.R"))
source(project_path("analysis", "gwr", "gwr_helpers.R"))

input <- kepco_processed_path("kepco_monthly_generation_emissions.csv")
if (!file.exists(input)) stop("Missing processed KEPCO input: ", input, call. = FALSE)
out_dir <- gwr_results_path("tables", "gwr", "plant_air_quality")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

x <- read.csv(input, stringsAsFactors = FALSE, check.names = FALSE)
require_columns(x, c("date", "plant_name", "subsidiary_company", "reporting_unit_id",
  "row_status", "nox", "sox", "dust_tsp", "plant_latitude", "plant_longitude",
  "audit_severity", "audit_issue_codes"), "KEPCO input")
x$date <- as.Date(x$date)
x$year <- as.integer(format(x$date, "%Y"))
x$plant_id <- paste(x$subsidiary_company, x$plant_name, sep = " | ")
x$valid_coordinates <- valid_lonlat(x$plant_longitude, x$plant_latitude)

active <- x[is.na(x$row_status) | x$row_status != "inactive_placeholder", ]
pollutants <- c(nox = "nox", sox = "sox", dust_tsp = "tsp")
coverage <- list()
plant_year <- list()
for (source_name in names(pollutants)) {
  pollutant <- pollutants[[source_name]]
  excluded <- pollutant_audit_excluded(active$audit_severity, active$audit_issue_codes, source_name)
  observed <- !is.na(active[[source_name]])
  valid <- observed & !excluded & active$valid_coordinates
  years <- sort(unique(active$year))
  coverage[[pollutant]] <- do.call(rbind, lapply(years, function(yr) {
    z <- active$year == yr
    data.frame(
      year = yr, emissions_pollutant = pollutant,
      active_reporting_rows = sum(z), observed_emissions_rows = sum(z & observed),
      pollutant_audit_excluded_rows = sum(z & observed & excluded),
      invalid_coordinate_rows = sum(z & observed & !active$valid_coordinates),
      valid_emissions_rows = sum(z & valid),
      plants_with_any_valid_month = length(unique(active$plant_id[z & valid])),
      reporting_units_with_any_valid_month = length(unique(active$reporting_unit_id[z & valid])),
      stringsAsFactors = FALSE
    )
  }))
  valid_rows <- active[valid, c("plant_id", "plant_name", "subsidiary_company", "year", "date", "plant_latitude", "plant_longitude")]
  if (nrow(valid_rows)) {
    counts <- aggregate(date ~ plant_id + plant_name + subsidiary_company + year + plant_latitude + plant_longitude,
      valid_rows, function(v) length(unique(v)))
    names(counts)[names(counts) == "date"] <- "valid_emission_months"
    counts$emissions_pollutant <- pollutant
    counts$eligible_minimum_9_months <- counts$valid_emission_months >= 9L
    plant_year[[pollutant]] <- counts
  }
}

coverage <- do.call(rbind, coverage)
plant_year <- do.call(rbind, plant_year)
rownames(coverage) <- NULL
rownames(plant_year) <- NULL
sites <- unique(x[c("plant_id", "plant_name", "subsidiary_company", "plant_latitude", "plant_longitude", "valid_coordinates")])
site_summary <- aggregate(year ~ plant_id, x, function(v) c(first = min(v), last = max(v)))
site_summary <- data.frame(plant_id = site_summary$plant_id,
  first_year = site_summary$year[, "first"], last_year = site_summary$year[, "last"])
sites <- merge(sites, site_summary, by = "plant_id", all.x = TRUE)

overview <- data.frame(
  metric = c("input_rows", "first_month", "last_month", "distinct_plant_ids",
    "plant_sites_with_valid_coordinates", "inactive_placeholder_rows",
    "active_or_unspecified_rows", "eligible_plant_year_pollutants_minimum_9_months"),
  value = c(nrow(x), format(min(x$date), "%Y-%m-%d"), format(max(x$date), "%Y-%m-%d"),
    length(unique(x$plant_id)), length(unique(x$plant_id[x$valid_coordinates])),
    sum(x$row_status == "inactive_placeholder", na.rm = TRUE), nrow(active),
    sum(plant_year$eligible_minimum_9_months)), stringsAsFactors = FALSE
)

write.csv(overview, file.path(out_dir, "plant_input_readiness_overview.csv"), row.names = FALSE, na = "")
write.csv(coverage, file.path(out_dir, "plant_pollutant_year_coverage.csv"), row.names = FALSE, na = "")
write.csv(plant_year, file.path(out_dir, "plant_year_pollutant_readiness.csv"), row.names = FALSE, na = "")
write.csv(sites, file.path(out_dir, "plant_site_coordinate_inventory.csv"), row.names = FALSE, na = "")
message("Wrote four plant-side descriptive readiness tables to ", out_dir)
