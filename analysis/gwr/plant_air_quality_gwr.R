#!/usr/bin/env Rscript
# Descriptive spatial association analysis; this is not a causal or dispersion model.
source(file.path("analysis", "R", "paths.R"))
source(project_path("analysis", "R", "gwr_helpers.R"))

config <- list(
  minimum_monitor_months = 9L, minimum_monthly_hour_share = 0.75,
  minimum_plant_months = 9L, primary_decay_km = 50,
  sensitivity_decay_km = c(25, 100), gwr_kernel = "bisquare",
  gwr_adaptive = TRUE, gwr_bandwidth_approach = "AICc",
  minimum_monitors = 40L, residual_knn = 8L, projected_crs = 5179L,
  random_seed = 7649L
)
set.seed(config$random_seed)

inputs <- c(
  plant = kepco_processed_path("kepco_monthly_generation_emissions.csv"),
  air = Sys.getenv(
    "GWR_AIR_QUALITY_INPUT",
    unset = air_quality_processed_path("air_quality_monthly_qc.parquet")
  ),
  crosswalk = air_quality_interim_path("airkorea_station_crosswalk.csv")
)
missing_inputs <- inputs[!file.exists(inputs)]
if (length(missing_inputs)) stop("Required upstream input(s) absent:\n", paste(" -", missing_inputs, collapse = "\n"),
  "\nBuild/provide the monthly AirKorea QC Parquet and station-year crosswalk; this target intentionally does not rerun hourly QC.", call. = FALSE)

# The canonical ML/spatial AirKorea QC product is the default; GWR_AIR_QUALITY_INPUT
# may point at a provisional deterministic-rule-only fallback (see analysis/gwr/build_rule_qc_fallback.py).
# That distinction must survive into every output table so results are never mistaken for canonical QC.
qc_input_source <- if (identical(normalizePath(inputs[["air"]], mustWork = FALSE), normalizePath(air_quality_processed_path("air_quality_monthly_qc.parquet"), mustWork = FALSE))) {
  "canonical_ml_spatial_qc"
} else {
  "provisional_rule_based_fallback_qc"
}
message("Air-quality QC input source: ", qc_input_source, " (", inputs[["air"]], ")")

packages <- c("arrow", "broom", "dplyr", "ggplot2", "GWmodel", "lubridate", "purrr", "readr", "sf", "sp", "spdep", "tibble", "tidyr", "units")
missing_packages <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing_packages)) stop("Missing R packages: ", paste(missing_packages, collapse = ", "), ". Run `make requirements-r`.", call. = FALSE)

table_dir <- gwr_results_path("tables", "gwr", "plant_air_quality")
model_dir <- gwr_results_path("models", "gwr", "plant_air_quality")
figure_dir <- gwr_results_path("figures", "gwr", "plant_air_quality")
invisible(lapply(c(table_dir, model_dir, figure_dir), dir.create, recursive = TRUE, showWarnings = FALSE))
write_csv <- function(x, name) {
  x$qc_input_source <- qc_input_source
  x$qc_input_path <- inputs[["air"]]
  readr::write_csv(x, file.path(table_dir, name), na = "")
}
log_count <- function(stage, before, after) message(stage, ": removed ", before - after, "; retained ", after)

plants_raw <- readr::read_csv(inputs[["plant"]], show_col_types = FALSE)
air_raw <- arrow::read_parquet(inputs[["air"]]) |> tibble::as_tibble()
crosswalk <- readr::read_csv(inputs[["crosswalk"]], show_col_types = FALSE)
require_columns(plants_raw, c("date", "plant_name", "subsidiary_company", "fuel_type", "reporting_unit_id", "row_status", "nox", "sox", "dust_tsp", "plant_latitude", "plant_longitude", "audit_severity", "audit_issue_codes"), "KEPCO input")
require_columns(air_raw, c("monitor_id", "month", "pollutant", "value", "hours"), "AirKorea QC input")
require_columns(crosswalk, c("monitor_id", "year", "latitude", "longitude", "coordinate_match_method", "coordinate_match_confidence"), "station crosswalk")
air_raw$monitor_id <- as.character(air_raw$monitor_id)
crosswalk$monitor_id <- as.character(crosswalk$monitor_id)
crosswalk$year <- as.integer(crosswalk$year)

plants_raw$date <- as.Date(plants_raw$date); air_raw$month <- as.Date(air_raw$month)
plants_raw$year <- lubridate::year(plants_raw$date); air_raw$year <- lubridate::year(air_raw$month)
message("Plant-data date range: ", paste(range(plants_raw$date, na.rm = TRUE), collapse = " to "))
message("AirKorea date range: ", paste(range(air_raw$month, na.rm = TRUE), collapse = " to "))
overlap_years <- intersect(unique(plants_raw$year), unique(air_raw$year)); message("Overlapping years: ", paste(sort(overlap_years), collapse = ", "))
message("Plant sites with valid coordinates: ", dplyr::n_distinct(paste(plants_raw$subsidiary_company[valid_lonlat(plants_raw$plant_longitude, plants_raw$plant_latitude)], plants_raw$plant_name[valid_lonlat(plants_raw$plant_longitude, plants_raw$plant_latitude)])))
message("Monitor-years with valid coordinates: ", sum(valid_lonlat(crosswalk$longitude, crosswalk$latitude)))
print(dplyr::count(crosswalk, coordinate_match_confidence, name = "monitor_years"))
print(dplyr::count(air_raw, year, pollutant, name = "monitor_months"))

# Monthly outcomes: station-year join is deliberate because stations may move.
air_joined <- dplyr::left_join(air_raw, crosswalk, by = c("monitor_id", "year"))
air_joined$expected_hours <- lubridate::days_in_month(air_joined$month) * 24
air_joined$hour_share <- air_joined$hours / air_joined$expected_hours
air_joined$exclusion_reason <- dplyr::case_when(
  is.na(air_joined$value) ~ "missing_concentration", is.na(air_joined$hours) | air_joined$hours <= 0 ~ "nonpositive_hours",
  air_joined$hour_share < config$minimum_monthly_hour_share ~ "insufficient_hour_coverage",
  is.na(air_joined$coordinate_match_method) | grepl("unresolved", air_joined$coordinate_match_method, ignore.case = TRUE) ~ "unresolved_coordinates",
  !valid_lonlat(air_joined$longitude, air_joined$latitude) ~ "invalid_or_missing_coordinates", TRUE ~ NA_character_)
excluded_monitors <- dplyr::filter(air_joined, !is.na(exclusion_reason))
monitor_months <- dplyr::filter(air_joined, is.na(exclusion_reason))
log_count("Monitor-month validation", nrow(air_joined), nrow(monitor_months))
monitor_years <- weighted_monitor_years(monitor_months, config$minimum_monitor_months)
coverage_failed <- dplyr::anti_join(dplyr::distinct(monitor_months, monitor_id, year, pollutant), dplyr::distinct(monitor_years, monitor_id, year, pollutant), by = c("monitor_id", "year", "pollutant")) |> dplyr::mutate(exclusion_reason = "fewer_than_minimum_valid_months")
write_csv(dplyr::bind_rows(dplyr::select(excluded_monitors, dplyr::any_of(c(names(air_raw), "year", "exclusion_reason"))), coverage_failed), "excluded_monitor_records.csv")

# Stop rather than silently summing duplicated reporting-unit/month boundaries.
active <- dplyr::filter(plants_raw, row_status != "inactive_placeholder")
duplicates <- dplyr::count(active, reporting_unit_id, date) |> dplyr::filter(n > 1)
if (nrow(duplicates)) stop("Duplicate reporting_unit_id/month boundaries detected (", nrow(duplicates), "). Resolve upstream; emissions were not silently summed.", call. = FALSE)
plant_long <- tidyr::pivot_longer(active, c(nox, sox, dust_tsp), names_to = "source_pollutant", values_to = "emissions_kg") |>
  dplyr::mutate(emissions_pollutant = dplyr::recode(source_pollutant, dust_tsp = "tsp"), plant_id = paste(subsidiary_company, plant_name, sep = " | "),
    audit_excluded = pollutant_audit_excluded(audit_severity, audit_issue_codes, source_pollutant),
    exclusion_reason = dplyr::case_when(audit_excluded ~ "pollutant_specific_audit_exclusion", is.na(emissions_kg) ~ "missing_emissions", !valid_lonlat(plant_longitude, plant_latitude) ~ "invalid_or_missing_coordinates", TRUE ~ NA_character_))
excluded_plants <- dplyr::filter(plant_long, !is.na(exclusion_reason))
plant_valid <- dplyr::filter(plant_long, is.na(exclusion_reason))
log_count("Plant-pollutant-month validation", nrow(plant_long), nrow(plant_valid))
plant_month <- dplyr::group_by(plant_valid, plant_id, plant_name, subsidiary_company, date, year, emissions_pollutant, plant_latitude, plant_longitude) |>
  dplyr::summarise(emissions_kg = sum(emissions_kg), .groups = "drop")
plant_year_all <- dplyr::group_by(plant_month, plant_id, plant_name, subsidiary_company, year, emissions_pollutant, plant_latitude, plant_longitude) |>
  dplyr::summarise(mean_monthly_emissions_kg = mean(emissions_kg), valid_emission_months = dplyr::n_distinct(date), .groups = "drop") |>
  dplyr::mutate(missing_months = 12L - valid_emission_months, coordinate_available = valid_lonlat(plant_longitude, plant_latitude), entered_exposure = valid_emission_months >= config$minimum_plant_months & coordinate_available)
audit_counts <- dplyr::filter(plant_long, audit_excluded) |> dplyr::count(plant_id, year, emissions_pollutant, name = "audit_excluded_months")
plant_year_all <- dplyr::left_join(plant_year_all, audit_counts, by = c("plant_id", "year", "emissions_pollutant")) |> dplyr::mutate(audit_excluded_months = tidyr::replace_na(audit_excluded_months, 0L))
plant_years <- dplyr::filter(plant_year_all, entered_exposure)
write_csv(excluded_plants, "excluded_plant_records.csv"); write_csv(plant_year_all, "plant_year_emissions_coverage.csv")
write_csv(monitor_years, "monitor_year_outcomes.csv")

model_map <- tibble::tribble(~outcome_pollutant, ~emissions_pollutant, ~exploratory, "NO2", "nox", FALSE, "SO2", "sox", FALSE, "PM10", "tsp", FALSE, "PM25", "tsp", TRUE)
decays <- c(config$sensitivity_decay_km[[1]], config$primary_decay_km, config$sensitivity_decay_km[[2]])
global_rows <- list(); local_rows <- list(); model_rows <- list()

# Step 7 exposure index: one row per physical site-year, independent of which
# outcome pollutant is later modeled against it (a site's exposure to plant NOx
# does not depend on whether that site happens to also report NO2 concentrations).
site_year_base <- dplyr::distinct(monitor_years, monitor_id, year, latitude, longitude, coordinate_match_method, coordinate_match_confidence)
exposure_long <- list()
for (yr in sort(unique(site_year_base$year))) {
  sites_yr <- dplyr::filter(site_year_base, year == yr)
  if (!nrow(sites_yr)) next
  ssf <- sf::st_transform(sf::st_as_sf(sites_yr, coords = c("longitude", "latitude"), crs = 4326, remove = FALSE), config$projected_crs)
  site_coords <- sf::st_coordinates(ssf); sites_yr$projected_x <- site_coords[, 1]; sites_yr$projected_y <- site_coords[, 2]
  sites_yr <- collapse_site_coordinates(sites_yr)
  ssf <- sf::st_as_sf(sites_yr, coords = c("projected_x", "projected_y"), crs = config$projected_crs, remove = FALSE)
  for (emission in unique(model_map$emissions_pollutant)) {
    py <- dplyr::filter(plant_years, year == yr, emissions_pollutant == emission)
    if (!nrow(py)) next
    psf <- sf::st_transform(sf::st_as_sf(py, coords = c("plant_longitude", "plant_latitude"), crs = 4326, remove = FALSE), config$projected_crs)
    for (decay in decays) {
      exp_result <- exponential_exposure(ssf, psf, py$mean_monthly_emissions_kg, decay)
      exposure_long[[length(exposure_long) + 1L]] <- dplyr::mutate(sites_yr, year = yr, emissions_pollutant = emission, decay_km = decay,
        exposure = exp_result$exposure, nearest_plant_distance_km = exp_result$nearest_plant_distance_km,
        number_of_contributing_plants = nrow(py), number_of_valid_plant_years = nrow(py), total_unweighted_emissions_kg = sum(py$mean_monthly_emissions_kg))
    }
  }
}
exposure_long <- dplyr::bind_rows(exposure_long)
exposure_wide <- if (nrow(exposure_long)) {
  site_meta <- dplyr::distinct(exposure_long, site_id, year, projected_x, projected_y, contributing_monitor_ids, contributing_monitor_count, latitude, longitude, coordinate_match_method, coordinate_match_confidence)
  exposure_cols <- exposure_long |> dplyr::mutate(exposure_name = paste0(emissions_pollutant, "_exposure_exp", decay_km)) |>
    dplyr::select(site_id, year, exposure_name, exposure) |> tidyr::pivot_wider(names_from = exposure_name, values_from = exposure)
  plant_meta_cols <- dplyr::distinct(exposure_long, site_id, year, emissions_pollutant, nearest_plant_distance_km, number_of_contributing_plants, number_of_valid_plant_years, total_unweighted_emissions_kg) |>
    tidyr::pivot_wider(names_from = emissions_pollutant, values_from = c(nearest_plant_distance_km, number_of_contributing_plants, number_of_valid_plant_years, total_unweighted_emissions_kg), names_glue = "{emissions_pollutant}_{.value}")
  site_meta |> dplyr::left_join(exposure_cols, by = c("site_id", "year")) |> dplyr::left_join(plant_meta_cols, by = c("site_id", "year"))
} else exposure_long
write_csv(exposure_wide, "monitor_year_exposure_indices.csv")

plot_points <- function(data, value, title, path) {
  p <- ggplot2::ggplot(data, ggplot2::aes(x = projected_x, y = projected_y, colour = .data[[value]])) + ggplot2::geom_point(size = 2) + ggplot2::coord_equal() + ggplot2::scale_colour_viridis_c() + ggplot2::labs(title = title, colour = NULL, x = NULL, y = NULL) + ggplot2::theme_minimal()
  ggplot2::ggsave(path, p, width = 7, height = 6, dpi = 180)
}

for (yr in sort(overlap_years)) for (m in seq_len(nrow(model_map))) {
  outcome <- model_map$outcome_pollutant[[m]]; emission <- model_map$emissions_pollutant[[m]]
  message("Preparing descriptive association: ", yr, " ", outcome, " ~ ", toupper(emission))
  monitors <- dplyr::filter(monitor_years, year == yr, toupper(pollutant) == outcome)
  py <- dplyr::filter(plant_years, year == yr, emissions_pollutant == emission)
  if (!nrow(monitors) || !nrow(py)) next
  msf <- sf::st_transform(sf::st_as_sf(monitors, coords = c("longitude", "latitude"), crs = 4326, remove = FALSE), config$projected_crs)
  psf <- sf::st_transform(sf::st_as_sf(py, coords = c("plant_longitude", "plant_latitude"), crs = 4326, remove = FALSE), config$projected_crs)
  if (!identical(sf::st_crs(msf)$units_gdal, "metre")) stop("EPSG:", config$projected_crs, " is not using metre units.")
  coords <- sf::st_coordinates(msf); monitors$projected_x <- coords[, 1]; monitors$projected_y <- coords[, 2]
  monitors <- collapse_duplicate_sites(monitors)
  msf <- sf::st_as_sf(monitors, coords = c("projected_x", "projected_y"), crs = config$projected_crs, remove = FALSE)
  for (decay in decays) {
    exp_result <- exponential_exposure(msf, psf, py$mean_monthly_emissions_kg, decay)
    dat <- monitors; dat$exposure <- exp_result$exposure; dat$log_exposure <- log1p(dat$exposure); dat$exposure_z <- as.numeric(scale(dat$log_exposure))
    dat$nearest_plant_distance_km <- exp_result$nearest_plant_distance_km; dat$number_of_contributing_plants <- nrow(py); dat$number_of_valid_plant_years <- nrow(py); dat$total_unweighted_emissions_kg <- sum(py$mean_monthly_emissions_kg)
    dat$year <- yr; dat$outcome_pollutant <- outcome; dat$emissions_pollutant <- emission; dat$decay_km <- decay
    if (nrow(dat) < config$minimum_monitors || sd(dat$annual_mean_concentration) == 0 || sd(dat$exposure_z) == 0) { warning("Skipping model: insufficient sites or no variation: ", outcome, " ", yr, " exp", decay); next }
    ols <- stats::lm(annual_mean_concentration ~ exposure_z, data = dat); ols_name <- tolower(paste0(outcome, "_", emission, "_", yr, "_exp", decay, "_ols.rds")); saveRDS(ols, file.path(model_dir, ols_name))
    ols_coef <- broom::tidy(ols) |> dplyr::filter(term == "exposure_z"); ols_glance <- broom::glance(ols)
    # broom::glance()$AIC is plain AIC; gwr.basic() reports AICc. Comparing AIC to AICc directly
    # is invalid (AICc >= AIC by a small-sample correction), so compute an OLS AICc too.
    ols_k <- length(stats::coef(ols)) + 1L; ols_n <- stats::nobs(ols)
    ols_aicc <- if (ols_n - ols_k - 1L > 0) ols_glance$AIC + (2 * ols_k * (ols_k + 1)) / (ols_n - ols_k - 1) else NA_real_
    global_rows[[length(global_rows) + 1L]] <- dplyr::bind_cols(tibble::tibble(year = yr, outcome_pollutant = outcome, emissions_pollutant = emission, decay_km = decay, exploratory = model_map$exploratory[[m]]), ols_coef, ols_glance)
    spatial <- methods::as(sf::st_as_sf(dat, coords = c("projected_x", "projected_y"), crs = config$projected_crs, remove = FALSE), "Spatial")
    bw <- tryCatch(GWmodel::bw.gwr(annual_mean_concentration ~ exposure_z, data = spatial, approach = config$gwr_bandwidth_approach, kernel = config$gwr_kernel, adaptive = TRUE, longlat = FALSE), error = function(e) { warning("Bandwidth selection failed: ", conditionMessage(e), "; using documented 75% adaptive fallback"); max(2L, floor(nrow(dat) * .75)) })
    fit <- tryCatch(GWmodel::gwr.basic(annual_mean_concentration ~ exposure_z, data = spatial, bw = bw, kernel = config$gwr_kernel, adaptive = TRUE, longlat = FALSE, F123.test = TRUE, cv = TRUE), error = function(e) { warning("GWR failed: ", conditionMessage(e)); NULL })
    if (is.null(fit)) next
    saveRDS(fit, file.path(model_dir, tolower(paste0(outcome, "_", emission, "_", yr, "_exp", decay, "_gwr.rds"))))
    sdf <- as.data.frame(fit$SDF)
    # Prefer an exact-anchored match; only fall back to a loose substring match (with a
    # warning) if the installed GWmodel version names the column differently, since loose
    # patterns like "residual" can also match "Stud_residual" depending on column order.
    find_col <- function(exact, loose = exact) {
      hit <- grep(paste0("^", exact, "$"), names(sdf), ignore.case = TRUE, value = TRUE)
      if (length(hit)) return(hit[[1]])
      hit <- grep(loose, names(sdf), ignore.case = TRUE, value = TRUE)
      if (length(hit)) { warning("Falling back to loose column match '", loose, "' -> '", hit[[1]], "' for GWmodel SDF extraction."); return(hit[[1]]) }
      NA_character_
    }
    get_col <- function(exact, loose = exact) { n <- find_col(exact, loose); if (is.na(n)) rep(NA_real_, nrow(sdf)) else sdf[[n]] }
    adjusted <- tryCatch(GWmodel::gwr.t.adjust(fit), error = function(e) { warning("gwr.t.adjust() failed: ", conditionMessage(e)); NULL })
    adjusted_sdf <- if (!is.null(adjusted)) as.data.frame(adjusted$SDF) else NULL
    get_adjusted_col <- function(exact) { if (is.null(adjusted_sdf)) return(rep(NA_real_, nrow(sdf))); n <- grep(paste0("^", exact, "$"), names(adjusted_sdf), ignore.case = TRUE, value = TRUE); if (length(n)) adjusted_sdf[[n[[1]]]] else rep(NA_real_, nrow(sdf)) }
    local <- dplyr::mutate(dat, selected_bandwidth = bw,
      local_intercept = get_col("Intercept"),
      local_exposure_coefficient = get_col("exposure_z"),
      local_exposure_standard_error = get_col("exposure_z_SE", "exposure_z.*SE|SE.*exposure_z"),
      local_exposure_t_value = get_col("exposure_z_TV", "exposure_z.*TV|TV.*exposure_z"),
      local_exposure_p_value_raw = get_adjusted_col("exposure_z_p"),
      local_exposure_p_value_adjusted_bh = get_adjusted_col("exposure_z_p_bh"),
      local_exposure_p_value_adjusted_bonferroni = get_adjusted_col("exposure_z_p_bo"),
      local_r_squared = get_col("Local_R2", "local.*R2"),
      fitted_concentration = get_col("yhat", "yhat|pred"),
      residual = get_col("residual"))
    if (all(is.na(local$residual))) local$residual <- dat$annual_mean_concentration - local$fitted_concentration
    local_rows[[length(local_rows) + 1L]] <- local
    moran_ols <- moran_diagnostic(stats::residuals(ols), as.matrix(dat[c("projected_x", "projected_y")]), config$residual_knn); moran_gwr <- moran_diagnostic(local$residual, as.matrix(dat[c("projected_x", "projected_y")]), config$residual_knn)
    # F1 tests whether the GWR model as a whole improves on the global OLS model; this is a
    # more principled comparison than AICc/R2 alone, and F123.test = TRUE already computed it.
    f1 <- fit$Ftests$F1.test
    model_rows[[length(model_rows) + 1L]] <- tibble::tibble(year = yr, outcome_pollutant = outcome, emissions_pollutant = emission, decay_km = decay, number_of_sites = nrow(dat), selected_adaptive_bandwidth = bw, global_ols_coefficient = ols_coef$estimate, global_ols_standard_error = ols_coef$std.error, global_ols_r_squared = ols_glance$r.squared, global_ols_aic = ols_glance$AIC, global_ols_aicc = ols_aicc, gwr_aic = fit$GW.diagnostic$AIC, gwr_aicc = fit$GW.diagnostic$AICc, gwr_global_r_squared = fit$GW.diagnostic$gw.R2, gwr_vs_global_f1_statistic = if (!is.null(f1)) f1[1, 1] else NA_real_, gwr_vs_global_f1_p_value = if (!is.null(f1)) f1[1, ncol(f1)] else NA_real_, minimum_local_r_squared = min(local$local_r_squared, na.rm = TRUE), median_local_r_squared = median(local$local_r_squared, na.rm = TRUE), maximum_local_r_squared = max(local$local_r_squared, na.rm = TRUE), minimum_local_coefficient = min(local$local_exposure_coefficient, na.rm = TRUE), median_local_coefficient = median(local$local_exposure_coefficient, na.rm = TRUE), maximum_local_coefficient = max(local$local_exposure_coefficient, na.rm = TRUE), global_residual_moran_i = moran_ols[["estimate"]], global_residual_moran_p = moran_ols[["p_value"]], gwr_residual_moran_i = moran_gwr[["estimate"]], gwr_residual_moran_p = moran_gwr[["p_value"]])
    if (decay == config$primary_decay_km) {
      prefix <- tolower(paste(outcome, emission, yr, "exp50", sep = "_")); plot_points(local, "annual_mean_concentration", paste("Annual", outcome, "monitor concentration (descriptive)"), file.path(figure_dir, paste0(prefix, "_concentration.png"))); plot_points(local, "exposure", "Distance-weighted emissions index (not concentration)", file.path(figure_dir, paste0(prefix, "_exposure.png"))); plot_points(local, "local_exposure_coefficient", "Descriptive local GWR coefficient", file.path(figure_dir, paste0(prefix, "_coefficient.png"))); plot_points(local, "local_r_squared", "Local GWR R-squared", file.path(figure_dir, paste0(prefix, "_local_r2.png"))); plot_points(local, "residual", "GWR residual", file.path(figure_dir, paste0(prefix, "_residual.png")))
      scatter <- ggplot2::ggplot(dat, ggplot2::aes(exposure_z, annual_mean_concentration)) + ggplot2::geom_point() + ggplot2::geom_smooth(method = "lm", se = TRUE) + ggplot2::labs(title = "Global OLS descriptive spatial association", x = "Standardized log distance-weighted emissions index", y = paste("Annual mean", outcome)) + ggplot2::theme_minimal(); ggplot2::ggsave(file.path(figure_dir, paste0(prefix, "_global_ols.png")), scatter, width = 7, height = 5, dpi = 180)
    }
  }
}

globals <- dplyr::bind_rows(global_rows); locals <- dplyr::bind_rows(local_rows); summaries <- dplyr::bind_rows(model_rows)
write_csv(globals, "global_ols_summary.csv"); write_csv(summaries, "gwr_model_summary.csv"); write_csv(locals, "gwr_local_coefficients.csv")
coverage <- tibble::tibble(metric = c("plant_input_rows", "air_input_rows", "crosswalk_rows", "excluded_monitor_records", "retained_monitor_years", "excluded_plant_pollutant_records", "retained_plant_years", "fitted_gwr_models"), value = c(nrow(plants_raw), nrow(air_raw), nrow(crosswalk), nrow(excluded_monitors) + nrow(coverage_failed), nrow(monitor_years), nrow(excluded_plants), nrow(plant_years), nrow(summaries)))
write_csv(coverage, "input_coverage_summary.csv")
if (nrow(locals)) {
  sensitivity <- ggplot2::ggplot(locals, ggplot2::aes(factor(decay_km), local_exposure_coefficient)) + ggplot2::geom_violin() + ggplot2::geom_boxplot(width = .12, outlier.shape = NA) + ggplot2::facet_grid(outcome_pollutant ~ year, scales = "free_y") + ggplot2::labs(title = "Sensitivity of descriptive local coefficients", x = "Emissions distance-decay scale (km)", y = "Local coefficient") + ggplot2::theme_minimal(); ggplot2::ggsave(file.path(figure_dir, "local_coefficient_decay_sensitivity.png"), sensitivity, width = 12, height = 8, dpi = 180)
}
message("Descriptive plant-to-air-quality GWR analysis complete. These spatial associations are not causal.")
