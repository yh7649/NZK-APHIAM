#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(rmweather)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: normalize_weather.R INPUT.csv OUTPUT.csv")
set.seed(7649)
panel <- read_csv(args[[1]], show_col_types = FALSE)
required <- c(
  "datetime", "monitor_id", "pollutant", "concentration", "temperature_c",
  "relative_humidity_pct", "wind_direction_deg", "wind_speed_m_s", "station_pressure_hpa"
)
missing <- setdiff(required, names(panel))
if (length(missing)) stop("Missing columns: ", paste(missing, collapse = ", "))

normalise_one <- function(frame) {
  prepared <- frame |>
    transmute(
      date = as.POSIXct(datetime, tz = "Asia/Seoul"), value = concentration,
      air_temp = temperature_c, rh = relative_humidity_pct, wd = wind_direction_deg,
      ws = wind_speed_m_s, atmospheric_pressure = station_pressure_hpa
    ) |>
    filter(if_all(everything(), ~ !is.na(.x))) |>
    rmw_prepare_data(value = "value", na.rm = TRUE)
  result <- rmw_do_all(
    prepared,
    variables = c(
      "date_unix", "day_julian", "weekday", "hour", "air_temp", "rh", "wd", "ws",
      "atmospheric_pressure"
    ),
    n_trees = 500, n_samples = 500, verbose = FALSE
  )
  normalised <- if (is.data.frame(result)) result else result$normalised
  if (is.null(normalised)) stop("Installed rmweather returned no normalised data")
  value_column <- intersect(c("value_normalised", "value_normalized", "normalised"), names(normalised))
  if (!length(value_column)) stop("Cannot identify rmweather's normalized-value column")
  normalised |>
    transmute(datetime = date, normalized_concentration = .data[[value_column[[1]]]])
}

output <- panel |>
  group_by(monitor_id, pollutant) |>
  group_modify(~ left_join(.x, normalise_one(.x), by = "datetime")) |>
  ungroup()
dir.create(dirname(args[[2]]), recursive = TRUE, showWarnings = FALSE)
write_csv(output, args[[2]])
