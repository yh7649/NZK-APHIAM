require_columns <- function(x, required, label) {
  missing <- setdiff(required, names(x))
  if (length(missing)) stop(label, " is missing required columns: ", paste(missing, collapse = ", "), call. = FALSE)
  invisible(x)
}

valid_lonlat <- function(longitude, latitude) {
  is.finite(longitude) & is.finite(latitude) & longitude >= -180 & longitude <= 180 & latitude >= -90 & latitude <= 90
}

audit_exclusion_pattern <- function(pollutant) {
  paste0("high_", pollutant, "_emission_factor|recent_shift_(high|low)_", pollutant,
         "_mass|zero_", pollutant, "_(with_generation|coal_generation)")
}

pollutant_audit_excluded <- function(severity, issue_codes, pollutant) {
  severity %in% c("critical", "warning") & mapply(
    function(code, pol) grepl(audit_exclusion_pattern(pol), code),
    ifelse(is.na(issue_codes), "", issue_codes), pollutant,
    USE.NAMES = FALSE
  )
}

weighted_monitor_years <- function(monthly, minimum_months = 9L) {
  require_columns(monthly, c("monitor_id", "year", "pollutant", "value", "hours", "latitude", "longitude"), "monthly monitor data")
  optional <- intersect(c("coordinate_match_method", "coordinate_match_confidence"), names(monthly))
  keys <- c("monitor_id", "year", "pollutant", "latitude", "longitude", optional)
  out <- dplyr::group_by(monthly, dplyr::across(dplyr::all_of(keys))) |>
    dplyr::summarise(annual_mean_concentration = stats::weighted.mean(value, hours),
                     valid_months = dplyr::n(), valid_hours = sum(hours), .groups = "drop") |>
    dplyr::filter(valid_months >= minimum_months)
  out$annual_hour_share <- out$valid_hours / (ifelse(lubridate::leap_year(out$year), 366, 365) * 24)
  out
}

summarise_plant_years <- function(monthly, minimum_months = 9L) {
  require_columns(monthly, c("plant_id", "year", "emissions_pollutant", "emissions_kg"), "plant-month data")
  dplyr::group_by(monthly, plant_id, year, emissions_pollutant) |>
    dplyr::summarise(mean_monthly_emissions_kg = mean(emissions_kg), valid_emission_months = dplyr::n(), .groups = "drop") |>
    dplyr::filter(valid_emission_months >= minimum_months)
}

collapse_duplicate_sites <- function(x, x_col = "projected_x", y_col = "projected_y") {
  require_columns(x, c("monitor_id", "annual_mean_concentration", "valid_hours", x_col, y_col), "monitor sites")
  x |>
    dplyr::group_by(dplyr::across(dplyr::all_of(c(x_col, y_col)))) |>
    dplyr::summarise(site_id = paste(sort(unique(monitor_id)), collapse = "|"),
      contributing_monitor_ids = paste(sort(unique(monitor_id)), collapse = ";"),
      contributing_monitor_count = dplyr::n_distinct(monitor_id),
      annual_mean_concentration = stats::weighted.mean(annual_mean_concentration, valid_hours),
      valid_hours = sum(valid_hours), dplyr::across(-dplyr::all_of(c("monitor_id", "annual_mean_concentration", "valid_hours")), dplyr::first), .groups = "drop")
}

# Coordinate-only sibling of collapse_duplicate_sites(): collapses exact duplicate
# projected coordinates into one physical site without requiring a concentration/hours
# column, for building an outcome-pollutant-independent site inventory (e.g. exposure).
collapse_site_coordinates <- function(x, x_col = "projected_x", y_col = "projected_y") {
  require_columns(x, c("monitor_id", x_col, y_col), "monitor sites")
  x |>
    dplyr::group_by(dplyr::across(dplyr::all_of(c(x_col, y_col)))) |>
    dplyr::summarise(site_id = paste(sort(unique(monitor_id)), collapse = "|"),
      contributing_monitor_ids = paste(sort(unique(monitor_id)), collapse = ";"),
      contributing_monitor_count = dplyr::n_distinct(monitor_id),
      dplyr::across(-dplyr::all_of("monitor_id"), dplyr::first), .groups = "drop")
}

exponential_exposure <- function(monitor_sf, plant_sf, emissions, decay_km) {
  if (anyNA(emissions)) stop("Missing emissions cannot be converted to zero when constructing exposure.", call. = FALSE)
  if (!length(emissions) || nrow(plant_sf) != length(emissions)) stop("Plant geometry and emissions lengths differ.", call. = FALSE)
  distances_km <- units::drop_units(sf::st_distance(monitor_sf, plant_sf)) / 1000
  if (any(!is.finite(distances_km) | distances_km < 0)) stop("Projected distances must be finite and nonnegative.", call. = FALSE)
  weights <- exp(-distances_km / decay_km)
  list(exposure = as.numeric(weights %*% emissions), distances_km = distances_km,
       weights = weights, nearest_plant_distance_km = apply(distances_km, 1, min))
}

moran_diagnostic <- function(residuals, coords, k = 8L) {
  if (nrow(coords) < 3L) return(c(estimate = NA_real_, p_value = NA_real_))
  k <- min(k, nrow(coords) - 1L)
  nb <- spdep::knn2nb(spdep::knearneigh(coords, k = k))
  test <- spdep::moran.test(residuals, spdep::nb2listw(nb, zero.policy = TRUE), zero.policy = TRUE)
  c(estimate = unname(test$estimate[[1]]), p_value = test$p.value)
}
