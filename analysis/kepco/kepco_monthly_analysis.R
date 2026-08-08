# NZK-APHIAM monthly KEPCO analysis workspace
#
# Open NZK-APHIAM.Rproj, then work through this KEPCO analysis script
# interactively.
# Python owns data merging and unit standardization. Run `make combine-kepco`
# before using this file whenever an interim dataset changes.

# ---- Setup -------------------------------------------------------------------

source(file.path("analysis", "R", "paths.R"))
source(file.path("analysis", "kepco", "ef_eligibility.R"))

options(
  stringsAsFactors = FALSE,
  scipen = 999
)

combined_csv <- kepco_processed_path("kepco_monthly_generation_emissions.csv")
metadata_csv <- kepco_processed_path(
  "kepco_monthly_generation_emissions_metadata.csv"
)

figures_dir <- results_path("figures")
tables_dir <- results_path("tables", "kepco")
objects_dir <- results_path("objects", "kepco")
models_dir <- results_path("models", "kepco")
processed_ef_dir <- kepco_processed_path("emission_factors")

for (directory in c(
  figures_dir,
  tables_dir,
  objects_dir,
  models_dir,
  processed_ef_dir
)) {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
}

save_table <- function(data, filename, row.names = FALSE, ...) {
  output_path <- file.path(tables_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  write.csv(data, output_path, row.names = row.names, na = "", ...)
  message("Saved table: ", output_path)
  invisible(output_path)
}

save_processed_ef <- function(data, filename, row.names = FALSE, ...) {
  output_path <- file.path(processed_ef_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  write.csv(data, output_path, row.names = row.names, na = "", ...)
  message("Saved canonical processed EF data: ", output_path)
  invisible(output_path)
}

flat_kepco_tables <- list.files(
  tables_dir,
  pattern = "^kepco_.*\\.(csv|xlsx)$",
  full.names = TRUE
)
for (flat_kepco_table in flat_kepco_tables) {
  unlink(flat_kepco_table)
  message("Deleted superseded flat KEPCO table: ", flat_kepco_table)
}

save_figure <- function(
  filename,
  plot = NULL,
  width = 8,
  height = 6,
  units = "in",
  res = 300,
  ...
) {
  output_path <- file.path(figures_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)

  if (!is.null(plot) && requireNamespace("ggplot2", quietly = TRUE)) {
    ggplot2::ggsave(
      filename = output_path,
      plot = plot,
      width = width,
      height = height,
      units = units,
      dpi = res,
      ...
    )
  } else {
    warning(
      "For base R figures, open a graphics device such as png() and call ",
      "dev.off(). For ggplot objects, install ggplot2 and pass plot = your_plot.",
      call. = FALSE
    )
  }

  invisible(output_path)
}

save_analysis_object <- function(object, filename) {
  output_path <- file.path(objects_dir, filename)
  saveRDS(object, output_path)
  message("Saved R object: ", output_path)
  invisible(output_path)
}

save_model <- function(model, filename) {
  output_path <- file.path(models_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  saveRDS(model, output_path)
  message("Saved model: ", output_path)
  invisible(output_path)
}


# ---- Load and validate --------------------------------------------------------

required_files <- c(combined_csv, metadata_csv)
missing_files <- required_files[!file.exists(required_files)]

if (length(missing_files) > 0) {
  stop(
    "Required processed files are missing:\n",
    paste(missing_files, collapse = "\n"),
    "\nRun `make combine-kepco` first.",
    call. = FALSE
  )
}

kepco <- read.csv(
  combined_csv,
  na.strings = c("", "NA"),
  check.names = FALSE,
  stringsAsFactors = FALSE
)
kepco$date <- as.Date(kepco$date)
kepco$plant_opening_date <- as.Date(kepco$plant_opening_date)
kepco$plant_closing_date <- as.Date(kepco$plant_closing_date)

kepco_metadata <- read.csv(
  metadata_csv,
  check.names = FALSE,
  stringsAsFactors = FALSE
)

if (!identical(kepco_metadata$varname, names(kepco))) {
  stop("Variable metadata does not match the processed dataset.", call. = FALSE)
}

for (i in seq_len(nrow(kepco_metadata))) {
  attr(kepco[[kepco_metadata$varname[[i]]]], "label") <-
    kepco_metadata$label[[i]]
}

if (!all(kepco$observation_frequency == "monthly")) {
  stop("The processed dataset contains non-monthly observations.", call. = FALSE)
}

if (!all(kepco$pollutant_measurement_basis == "mass")) {
  stop("The processed dataset contains non-mass pollutant observations.", call. = FALSE)
}

mass_units <- unique(na.omit(kepco$emissions_mass_unit))
if (!identical(mass_units, "kilograms")) {
  stop("Pollutant mass is not consistently standardized to kilograms.", call. = FALSE)
}


# ---- Analysis variables -------------------------------------------------------

kepco$year <- as.integer(format(kepco$date, "%Y"))
kepco$month <- as.integer(format(kepco$date, "%m"))

kepco$nox_kg_per_mwh <- with(
  kepco,
  ifelse(energy_generated_mwh > 0, nox / energy_generated_mwh, NA_real_)
)
kepco$sox_kg_per_mwh <- with(
  kepco,
  ifelse(energy_generated_mwh > 0, sox / energy_generated_mwh, NA_real_)
)
kepco$dust_tsp_kg_per_mwh <- with(
  kepco,
  ifelse(energy_generated_mwh > 0, dust_tsp / energy_generated_mwh, NA_real_)
)

attr(kepco$year, "label") <- "Observation year"
attr(kepco$month, "label") <- "Observation month number (1-12)"
attr(kepco$nox_kg_per_mwh, "label") <-
  "Nitrogen oxides emission factor (kg/MWh)"
attr(kepco$sox_kg_per_mwh, "label") <-
  "Sulfur oxides emission factor (kg/MWh)"
attr(kepco$dust_tsp_kg_per_mwh, "label") <-
  "Total suspended particulate emission factor (kg/MWh)"


# ---- Workspace overview -------------------------------------------------------

cat("Rows:", format(nrow(kepco), big.mark = ","), "\n")
cat("Date range:", format(min(kepco$date)), "to", format(max(kepco$date)), "\n")
cat("Subsidiaries:", paste(sort(unique(kepco$subsidiary_company)), collapse = ", "), "\n")
cat("Plants:", length(unique(kepco$plant_name)), "\n\n")

coverage_by_dataset <- aggregate(
  date ~ source_dataset,
  data = kepco,
  FUN = function(x) paste(min(x), max(x), sep = " to ")
)
print(coverage_by_dataset)


# ---- Manual analysis starts here ---------------------------------------------

# Useful first checks:
# View(kepco)
# summary(kepco)
# table(kepco$source_dataset, useNA = "ifany")
# table(kepco$fuel_type, useNA = "ifany")
#
# Save examples:
# save_table(coverage_by_dataset, "coverage_by_dataset.csv")
# save_analysis_object(kepco, "kepco_analysis_data.rds")
# save_model(your_model, "your_model.rds")
#
# With ggplot2:
# library(ggplot2)
# generation_plot <- ggplot(kepco, aes(date, energy_generated_mwh)) +
#   geom_line(aes(color = subsidiary_company), na.rm = TRUE) +
#   labs(x = NULL, y = "Monthly electricity generation (MWh)")
# save_figure("monthly_generation.png", generation_plot)


# ---- Fast KEPCO EF diagnostics and projections ------------------------------

# This section applies one explicit pollutant-month eligibility table:
#   1. pollutant EF = kg emissions / MWh generation
#   2. hard-exclude missing/nonpositive inputs, duplicates, negative physical
#      values, pollutant-specific high EFs, and implausible pollutant zeros
#   3. use an operational primary specification that also excludes CF < 1%
#   4. retain low-load-inclusive and conservative-quality sensitivities
#   5. suppress aggregates with less than 50% surviving generation coverage
#   6. aggregate EF as total valid emissions / total valid generation

required_r_packages <- c("ggplot2", "dplyr", "tidyr", "readr", "lubridate", "scales", "broom")
missing_r_packages <- required_r_packages[
  !vapply(required_r_packages, requireNamespace, logical(1), quietly = TRUE)
]

if (length(missing_r_packages) > 0) {
  stop(
    "Missing R packages: ",
    paste(missing_r_packages, collapse = ", "),
    "\nRun `make requirements-r` first.",
    call. = FALSE
  )
}

suppressPackageStartupMessages({
  library(ggplot2)
  library(dplyr)
  library(tidyr)
  library(readr)
  library(lubridate)
  library(scales)
  library(broom)
})

pollutants <- data.frame(
  pollutant = c("sox", "nox", "dust_tsp"),
  ef = c("sox_kg_per_mwh", "nox_kg_per_mwh", "dust_tsp_kg_per_mwh"),
  label = c("SOx", "NOx", "TSP"),
  stringsAsFactors = FALSE
)

kepco$.ef_source_row_id <- seq_len(nrow(kepco))
fallback_unit_id <- paste(
  kepco$plant_name,
  ifelse(is.na(kepco$plant_number), "NA", kepco$plant_number),
  kepco$fuel_type,
  sep = " | "
)
kepco$plant_unit_id <- ifelse(
  "reporting_unit_id" %in% names(kepco) &
    !is.na(kepco$reporting_unit_id) &
    kepco$reporting_unit_id != "",
  kepco$reporting_unit_id,
  fallback_unit_id
)
kepco$fuel_type_clean <- ifelse(
  is.na(kepco$fuel_type) | kepco$fuel_type == "",
  "unknown",
  kepco$fuel_type
)

ef_eligibility <- build_ef_eligibility(kepco, pollutants)
save_table(
  ef_eligibility,
  file.path("audit", "kepco_monthly_ef_eligibility.csv")
)

analysis_kepco <- apply_ef_specification(
  kepco,
  ef_eligibility,
  pollutants,
  "operational_primary"
)
analysis_kepco_low_load_inclusive <- apply_ef_specification(
  kepco,
  ef_eligibility,
  pollutants,
  "low_load_inclusive"
)
analysis_kepco_conservative <- apply_ef_specification(
  kepco,
  ef_eligibility,
  pollutants,
  "conservative_quality"
)

analysis_rows <- is.na(kepco$row_status) | kepco$row_status != "inactive_placeholder"
analysis_kepco <- analysis_kepco[analysis_rows, , drop = FALSE]
analysis_kepco_low_load_inclusive <- analysis_kepco_low_load_inclusive[
  analysis_rows,
  ,
  drop = FALSE
]
analysis_kepco_conservative <- analysis_kepco_conservative[
  analysis_rows,
  ,
  drop = FALSE
]

audit_exclusion_log <- ef_exclusion_log(ef_eligibility, "operational_primary")
save_table(
  audit_exclusion_log,
  file.path("audit", "kepco_operational_ef_exclusions.csv")
)
for (superseded_audit_file in c(
  "kepco_audit_excluded.csv",
  "kepco_ef_outliers_removed.csv"
)) {
  superseded_path <- file.path(tables_dir, "audit", superseded_audit_file)
  if (file.exists(superseded_path)) {
    unlink(superseded_path)
    message("Deleted superseded audit output: ", superseded_path)
  }
}

format_month_label <- function(x) {
  paste0(format(as.Date(x), "%Y"), "m", as.integer(format(as.Date(x), "%m")))
}

project_month_sequence <- function(first_date, final_date = as.Date("2050-12-01")) {
  seq(as.Date(format(first_date, "%Y-%m-01")), final_date, by = "month")
}

clean_filename <- function(x) {
  gsub("[^A-Za-z0-9]+", "_", tolower(x))
}

month_index <- function(x) {
  as.integer(format(as.Date(x), "%Y")) * 12L + as.integer(format(as.Date(x), "%m"))
}

trailing_mean <- function(x, window = 6) {
  vapply(
    seq_along(x),
    function(i) {
      value <- mean(x[max(1, i - window + 1):i], na.rm = TRUE)
      ifelse(is.nan(value), NA_real_, value)
    },
    numeric(1)
  )
}

add_trailing_moving_average <- function(data, group_vars = character(), window = 6) {
  data$ef_ma_kg_per_mwh <- NA_real_

  if (nrow(data) == 0) {
    return(data)
  }

  if (length(group_vars) == 0) {
    groups <- list(seq_len(nrow(data)))
  } else {
    groups <- split(seq_len(nrow(data)), data[group_vars], drop = TRUE)
  }

  for (idx in groups) {
    idx <- idx[order(data$date[idx])]
    data$ef_ma_kg_per_mwh[idx] <- trailing_mean(data$ef_kg_per_mwh[idx], window = window)
  }

  data
}

save_base_png <- function(filename, width = 2400, height = 1400, res = 220) {
  output_path <- file.path(figures_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  png(output_path, width = width, height = height, res = res)
  output_path
}

line_colors <- c(
  "#1F77B4", "#D81B60", "#009E73", "#E69F00", "#6A3D9A", "#4D4D4D",
  "#56B4E9", "#CC79A7"
)

summarize_vector <- function(x) {
  x <- x[!is.na(x)]
  if (length(x) == 0) {
    return(c(
      n = 0, mean = NA, sd = NA, min = NA, p25 = NA,
      median = NA, p75 = NA, max = NA
    ))
  }

  c(
    n = length(x),
    mean = mean(x),
    sd = ifelse(length(x) > 1, sd(x), NA_real_),
    min = min(x),
    p25 = unname(quantile(x, 0.25)),
    median = median(x),
    p75 = unname(quantile(x, 0.75)),
    max = max(x)
  )
}

summary_rows <- list()
for (fuel_type in sort(unique(analysis_kepco$fuel_type_clean))) {
  rows <- analysis_kepco$fuel_type_clean == fuel_type

  for (i in seq_len(nrow(pollutants))) {
    stats <- summarize_vector(analysis_kepco[[pollutants$ef[[i]]]][rows])
    gen_valid <- analysis_kepco$energy_generated_mwh[rows &
      !is.na(analysis_kepco[[pollutants$pollutant[[i]]]]) &
      analysis_kepco$energy_generated_mwh > 0]
    emissions_valid <- analysis_kepco[[pollutants$pollutant[[i]]]][rows &
      !is.na(analysis_kepco[[pollutants$pollutant[[i]]]]) &
      analysis_kepco$energy_generated_mwh > 0]

    summary_rows[[length(summary_rows) + 1]] <- data.frame(
      fuel_type = fuel_type,
      pollutant = pollutants$label[[i]],
      t(stats),
      total_generation_mwh = sum(gen_valid, na.rm = TRUE),
      total_emissions_kg = sum(emissions_valid, na.rm = TRUE),
      aggregate_ef_kg_per_mwh = sum(emissions_valid, na.rm = TRUE) /
        sum(gen_valid, na.rm = TRUE),
      row.names = NULL,
      check.names = FALSE
    )
  }
}

summary_by_fuel <- do.call(rbind, summary_rows)
save_table(summary_by_fuel, file.path("diagnostics", "kepco_pollutant_summary_by_fuel.csv"))

coverage_by_plant_fuel <- aggregate(
  date ~ plant_name + fuel_type_clean,
  data = analysis_kepco[
    !is.na(analysis_kepco$nox_kg_per_mwh) |
      !is.na(analysis_kepco$sox_kg_per_mwh) |
      !is.na(analysis_kepco$dust_tsp_kg_per_mwh),
  ],
  FUN = function(x) paste(min(x), max(x), sep = " to ")
)
save_table(
  coverage_by_plant_fuel,
  file.path("diagnostics", "kepco_ef_coverage_by_plant_fuel.csv")
)

aggregate_ef <- function(data, group_vars, pollutant, min_coverage_pct = 0.5) {
  keep <- !is.na(data[[pollutant]]) &
    !is.na(data$energy_generated_mwh) &
    data$energy_generated_mwh > 0
  x <- data[keep, c(group_vars, pollutant, "energy_generated_mwh")]

  if (nrow(x) == 0) {
    return(data.frame())
  }

  emissions <- aggregate(x[[pollutant]], x[group_vars], sum, na.rm = TRUE)
  generation <- aggregate(x$energy_generated_mwh, x[group_vars], sum, na.rm = TRUE)
  names(emissions)[ncol(emissions)] <- "emissions_kg"
  names(generation)[ncol(generation)] <- "generation_mwh"

  all_gen_rows <- data$energy_generated_mwh > 0 & !is.na(data$energy_generated_mwh)
  total_gen <- aggregate(
    data$energy_generated_mwh[all_gen_rows],
    data[all_gen_rows, group_vars, drop = FALSE],
    sum,
    na.rm = TRUE
  )
  names(total_gen)[ncol(total_gen)] <- "total_generation_mwh"

  out <- merge(emissions, generation, by = group_vars, all = TRUE)
  out <- merge(out, total_gen, by = group_vars, all.x = TRUE)
  out <- out[
    !is.na(out$total_generation_mwh) &
      (out$generation_mwh / out$total_generation_mwh) >= min_coverage_pct,
  ]
  out$total_generation_mwh <- NULL

  if (nrow(out) == 0) {
    return(data.frame())
  }

  out$ef_kg_per_mwh <- out$emissions_kg / out$generation_mwh
  out <- out[order(out$date), ]

  ma_groups <- setdiff(group_vars, "date")
  add_trailing_moving_average(out, ma_groups, window = 6)
}

for (i in seq_len(nrow(pollutants))) {
  plot_data <- aggregate_ef(
    analysis_kepco,
    c("plant_name", "date"),
    pollutants$pollutant[[i]]
  )

  if (nrow(plot_data) == 0) {
    next
  }

  plant_stats <- aggregate(
    ef_kg_per_mwh ~ plant_name,
    data = plot_data,
    FUN = function(x) c(n = length(x), max = max(x, na.rm = TRUE), sd = sd(x, na.rm = TRUE))
  )
  plant_stats <- data.frame(
    plant_name = plant_stats$plant_name,
    n = plant_stats$ef_kg_per_mwh[, "n"],
    max = plant_stats$ef_kg_per_mwh[, "max"],
    sd = plant_stats$ef_kg_per_mwh[, "sd"]
  )
  plant_stats <- plant_stats[
    plant_stats$n >= 24 &
      !is.na(plant_stats$sd) &
      plant_stats$sd > 0 &
      plant_stats$max > 0,
  ]
  plant_stats <- plant_stats[order(-plant_stats$n, plant_stats$plant_name), ]
  selected_plants <- plant_stats$plant_name[seq_len(min(6, nrow(plant_stats)))]

  if (length(selected_plants) == 0) {
    next
  }

  plot_data <- plot_data[plot_data$plant_name %in% selected_plants, ]

  output_path <- save_base_png(
    file.path(
      "kepco",
      "selected_plants",
      "ma6",
      paste0("kepco_selected_plants_", pollutants$pollutant[[i]], "_ef_ma6.png")
    )
  )
  old_par <- par(mfrow = c(2, 3), mar = c(3.2, 4.4, 2.4, 1), oma = c(0, 0, 2.5, 0))

  for (plant in selected_plants) {
    plant_data <- plot_data[plot_data$plant_name == plant, ]
    plant_data <- plant_data[order(plant_data$date), ]
    if (nrow(plant_data) == 0) {
      plot.new()
      title(main = plant)
    } else {
      plot(
        plant_data$date,
        plant_data$ef_kg_per_mwh,
        type = "l",
        lwd = 0.9,
        col = adjustcolor("#1F77B4", alpha.f = 0.28),
        xlab = "",
        ylab = paste0(pollutants$label[[i]], " EF, kg/MWh"),
        main = plant
      )
      lines(
        plant_data$date,
        plant_data$ef_ma_kg_per_mwh,
        lwd = 2,
        col = "#1F77B4"
      )
      grid(col = "grey88")
    }
  }

  title(
    paste0(
      "Monthly ", pollutants$label[[i]],
      " emissions factors: selected plants, 6-month moving average"
    ),
    outer = TRUE,
    cex.main = 1.25
  )
  par(old_par)
  dev.off()
  message("Saved figure: ", output_path)

  output_path <- save_base_png(
    file.path(
      "kepco",
      "selected_plants",
      "raw",
      paste0("kepco_selected_plants_", pollutants$pollutant[[i]], "_ef_raw.png")
    )
  )
  old_par <- par(mfrow = c(2, 3), mar = c(3.2, 4.4, 2.4, 1), oma = c(0, 0, 2.5, 0))

  for (plant in selected_plants) {
    plant_data <- plot_data[plot_data$plant_name == plant, ]
    plant_data <- plant_data[order(plant_data$date), ]
    if (nrow(plant_data) == 0) {
      plot.new()
      title(main = plant)
    } else {
      plot(
        plant_data$date,
        plant_data$ef_kg_per_mwh,
        type = "l",
        lwd = 1.4,
        col = "#1F77B4",
        xlab = "",
        ylab = paste0(pollutants$label[[i]], " EF, kg/MWh"),
        main = plant
      )
      grid(col = "grey88")
    }
  }

  title(
    paste0(
      "Monthly ", pollutants$label[[i]],
      " emissions factors: selected plants, raw data"
    ),
    outer = TRUE,
    cex.main = 1.25
  )
  par(old_par)
  dev.off()
  message("Saved figure: ", output_path)
}

generation_by_fuel <- aggregate(
  energy_generated_mwh ~ fuel_type_clean + date,
  data = analysis_kepco[!is.na(analysis_kepco$energy_generated_mwh), ],
  sum,
  na.rm = TRUE
)
generation_by_fuel <- generation_by_fuel[order(generation_by_fuel$date), ]
generation_by_fuel$energy_generated_mwh_ma6 <- NA_real_
for (fuel in sort(unique(generation_by_fuel$fuel_type_clean))) {
  idx <- which(generation_by_fuel$fuel_type_clean == fuel)
  idx <- idx[order(generation_by_fuel$date[idx])]
  generation_by_fuel$energy_generated_mwh_ma6[idx] <- trailing_mean(
    generation_by_fuel$energy_generated_mwh[idx],
    window = 6
  )
}
save_table(
  generation_by_fuel,
  file.path("monthly", "fuel_type", "kepco_fuel_type_monthly_generation_mwh.csv")
)

if (nrow(generation_by_fuel) > 0) {
  output_path <- save_base_png(
    file.path(
      "kepco",
      "fuel_type_averages",
      "raw",
      "kepco_fuel_type_generation_mwh.png"
    )
  )
  fuels <- sort(unique(generation_by_fuel$fuel_type_clean))
  fuel_colors <- rep(line_colors, length.out = length(fuels))
  y_range <- range(
    c(generation_by_fuel$energy_generated_mwh, generation_by_fuel$energy_generated_mwh_ma6),
    na.rm = TRUE
  )
  plot(
    range(generation_by_fuel$date, na.rm = TRUE),
    y_range,
    type = "n",
    xlab = "Month",
    ylab = "Generation, MWh",
    main = "Monthly generation by fuel type, 6-month moving average"
  )
  grid(col = "grey88")

  for (j in seq_along(fuels)) {
    fuel_data <- generation_by_fuel[generation_by_fuel$fuel_type_clean == fuels[[j]], ]
    fuel_data <- fuel_data[order(fuel_data$date), ]
    lines(
      fuel_data$date,
      fuel_data$energy_generated_mwh,
      col = adjustcolor(fuel_colors[[j]], alpha.f = 0.22),
      lwd = 0.8
    )
    lines(
      fuel_data$date,
      fuel_data$energy_generated_mwh_ma6,
      col = fuel_colors[[j]],
      lwd = 2
    )
  }

  legend(
    "topright",
    legend = fuels,
    col = fuel_colors,
    lty = 1,
    lwd = 2,
    bty = "n",
    cex = 0.82
  )
  dev.off()
  message("Saved figure: ", output_path)
}

fuel_time_series <- list()
for (i in seq_len(nrow(pollutants))) {
  plot_data <- aggregate_ef(
    analysis_kepco,
    c("fuel_type_clean", "date"),
    pollutants$pollutant[[i]]
  )
  fuel_time_series[[pollutants$pollutant[[i]]]] <- plot_data
  save_table(
    plot_data,
    file.path(
      "monthly", "fuel_type",
      paste0("kepco_fuel_type_monthly_", pollutants$pollutant[[i]], "_ef.csv")
    )
  )

  if (nrow(plot_data) == 0) {
    next
  }

  output_path <- save_base_png(
    file.path(
      "kepco",
      "fuel_type_averages",
      "ma6",
      paste0("kepco_fuel_type_average_", pollutants$pollutant[[i]], "_ef_ma6.png")
    )
  )
  fuels <- sort(unique(plot_data$fuel_type_clean))
  fuel_colors <- rep(line_colors, length.out = length(fuels))
  y_range <- range(plot_data$ef_kg_per_mwh, na.rm = TRUE)
  plot(
    range(plot_data$date, na.rm = TRUE),
    y_range,
    type = "n",
    xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " EF, kg/MWh"),
    main = paste0(
      "Average monthly ", pollutants$label[[i]],
      " EF by fuel type, 6-month moving average"
    )
  )
  grid(col = "grey88")

  for (j in seq_along(fuels)) {
    fuel_data <- plot_data[plot_data$fuel_type_clean == fuels[[j]], ]
    fuel_data <- fuel_data[order(fuel_data$date), ]
    lines(
      fuel_data$date,
      fuel_data$ef_kg_per_mwh,
      col = adjustcolor(fuel_colors[[j]], alpha.f = 0.22),
      lwd = 0.8
    )
    lines(
      fuel_data$date,
      fuel_data$ef_ma_kg_per_mwh,
      col = fuel_colors[[j]],
      lwd = 2
    )
  }

  legend(
    "topright",
    legend = fuels,
    col = fuel_colors,
    lty = 1,
    lwd = 2,
    bty = "n",
    cex = 0.82
  )
  dev.off()
  message("Saved figure: ", output_path)

  output_path <- save_base_png(
    file.path(
      "kepco",
      "fuel_type_averages",
      "raw",
      paste0("kepco_fuel_type_average_", pollutants$pollutant[[i]], "_ef_raw.png")
    )
  )
  y_range <- range(plot_data$ef_kg_per_mwh, na.rm = TRUE)
  plot(
    range(plot_data$date, na.rm = TRUE),
    y_range,
    type = "n",
    xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " EF, kg/MWh"),
    main = paste0(
      "Average monthly ", pollutants$label[[i]],
      " EF by fuel type, raw data"
    )
  )
  grid(col = "grey88")

  for (j in seq_along(fuels)) {
    fuel_data <- plot_data[plot_data$fuel_type_clean == fuels[[j]], ]
    fuel_data <- fuel_data[order(fuel_data$date), ]
    lines(
      fuel_data$date,
      fuel_data$ef_kg_per_mwh,
      col = fuel_colors[[j]],
      lwd = 1.4
    )
  }

  legend(
    "topright",
    legend = fuels,
    col = fuel_colors,
    lty = 1,
    lwd = 2,
    bty = "n",
    cex = 0.82
  )
  dev.off()
  message("Saved figure: ", output_path)

  mass_data <- plot_data[, c("fuel_type_clean", "date", "emissions_kg", "generation_mwh")]
  mass_data$emissions_kg_ma6 <- NA_real_
  for (fuel in sort(unique(mass_data$fuel_type_clean))) {
    idx <- which(mass_data$fuel_type_clean == fuel)
    idx <- idx[order(mass_data$date[idx])]
    mass_data$emissions_kg_ma6[idx] <- trailing_mean(mass_data$emissions_kg[idx], window = 6)
  }
  save_table(
    mass_data,
    file.path(
      "monthly", "fuel_type",
      paste0("kepco_fuel_type_monthly_", pollutants$pollutant[[i]], "_emissions_kg.csv")
    )
  )

  output_path <- save_base_png(
    file.path(
      "kepco",
      "fuel_type_averages",
      "raw",
      paste0("kepco_fuel_type_", pollutants$pollutant[[i]], "_emissions_kg.png")
    )
  )
  y_range <- range(c(mass_data$emissions_kg, mass_data$emissions_kg_ma6), na.rm = TRUE)
  plot(
    range(mass_data$date, na.rm = TRUE),
    y_range,
    type = "n",
    xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " emissions, kg"),
    main = paste0("Monthly ", pollutants$label[[i]], " mass emissions by fuel type, 6-month moving average")
  )
  grid(col = "grey88")

  for (j in seq_along(fuels)) {
    fuel_data <- mass_data[mass_data$fuel_type_clean == fuels[[j]], ]
    fuel_data <- fuel_data[order(fuel_data$date), ]
    lines(
      fuel_data$date,
      fuel_data$emissions_kg,
      col = adjustcolor(fuel_colors[[j]], alpha.f = 0.22),
      lwd = 0.8
    )
    lines(
      fuel_data$date,
      fuel_data$emissions_kg_ma6,
      col = fuel_colors[[j]],
      lwd = 2
    )
  }

  legend(
    "topright",
    legend = fuels,
    col = fuel_colors,
    lty = 1,
    lwd = 2,
    bty = "n",
    cex = 0.82
  )
  dev.off()
  message("Saved figure: ", output_path)
}

# ---- Delete superseded fuel type x technology overlay figures ----------------

# A prior version overlaid every fuel type's technology cohorts (faint lines)
# on one combined fuel-level chart; it was too visually noisy across six fuel
# types at once. Superseded by the one-figure-per-fuel-type breakdown below.
superseded_fuel_technology_figures <- file.path(
  figures_dir, "kepco", "fuel_type_averages", "ma6",
  paste0("kepco_fuel_type_technology_average_", pollutants$pollutant, "_ef_ma6.png")
)
for (superseded_figure in superseded_fuel_technology_figures[
  file.exists(superseded_fuel_technology_figures)
]) {
  unlink(superseded_figure)
  message("Deleted superseded figure: ", superseded_figure)
}

# ---- Fuel type technology emission factor figures (one figure per fuel) ------

# One figure per fuel type (e.g. "Coal EFs"): three pollutant colors, each
# with one line per technology cohort observed for that fuel (e.g. coal has
# conventional steam turbine and IGCC). Pollutant EF magnitudes differ by
# roughly two orders of magnitude (TSP << NOx/SOx), so each pollutant gets
# its own free-scaled panel within the figure rather than sharing one axis.
pollutant_colors <- setNames(
  c("#1F77B4", "#D81B60", "#009E73"),
  pollutants$label
)

fuel_technology_by_pollutant <- list()
for (i in seq_len(nrow(pollutants))) {
  technology_data <- aggregate_ef(
    analysis_kepco,
    c("fuel_type_clean", "technology", "date"),
    pollutants$pollutant[[i]]
  )
  save_table(
    technology_data,
    file.path(
      "monthly", "fuel_type_technology",
      paste0(
        "kepco_fuel_type_technology_monthly_", pollutants$pollutant[[i]], "_ef.csv"
      )
    )
  )
  if (nrow(technology_data) == 0) {
    next
  }
  technology_data$pollutant_label <- factor(
    pollutants$label[[i]],
    levels = pollutants$label
  )
  fuel_technology_by_pollutant[[pollutants$pollutant[[i]]]] <- technology_data
}
fuel_technology_ef <- do.call(rbind, fuel_technology_by_pollutant)

for (fuel in sort(unique(fuel_technology_ef$fuel_type_clean))) {
  fuel_figure_data <- fuel_technology_ef[
    fuel_technology_ef$fuel_type_clean == fuel &
      !is.na(fuel_technology_ef$ef_ma_kg_per_mwh),
  ]
  if (nrow(fuel_figure_data) == 0) {
    next
  }
  fuel_figure_data$technology_label <- gsub("_", " ", fuel_figure_data$technology)

  fuel_plot <- ggplot(
    fuel_figure_data,
    aes(
      x = date,
      y = ef_ma_kg_per_mwh,
      color = pollutant_label,
      linetype = technology_label,
      group = interaction(pollutant_label, technology_label)
    )
  ) +
    geom_line(linewidth = 0.8, na.rm = TRUE) +
    facet_wrap(~pollutant_label, scales = "free_y", ncol = 1) +
    scale_color_manual(values = pollutant_colors, guide = "none") +
    labs(
      title = paste0(tools::toTitleCase(gsub("_", " ", fuel)), " EFs by technology"),
      subtitle = "6-month moving average; color = pollutant, line type = technology",
      x = NULL,
      y = "EF, kg/MWh",
      linetype = "Technology"
    ) +
    theme_minimal(base_size = 11) +
    theme(
      legend.position = "bottom",
      strip.text = element_text(face = "bold"),
      plot.title = element_text(face = "bold", size = 14)
    )

  save_figure(
    file.path(
      "kepco", "fuel_type_technology", "ma6",
      paste0("kepco_", clean_filename(fuel), "_technology_ef_ma6.png")
    ),
    fuel_plot,
    width = 8,
    height = 9
  )
}

# ---- Province-level figures --------------------------------------------------

province_generation <- aggregate(
  energy_generated_mwh ~ plant_province + date,
  data = analysis_kepco[!is.na(analysis_kepco$energy_generated_mwh), ],
  sum,
  na.rm = TRUE
)
province_generation <- province_generation[order(province_generation$date), ]
province_generation$energy_generated_mwh_ma6 <- NA_real_
for (province in sort(unique(province_generation$plant_province))) {
  idx <- which(province_generation$plant_province == province)
  idx <- idx[order(province_generation$date[idx])]
  province_generation$energy_generated_mwh_ma6[idx] <- trailing_mean(
    province_generation$energy_generated_mwh[idx], window = 6
  )
}
save_table(
  province_generation,
  file.path("monthly", "province", "kepco_province_monthly_generation_mwh.csv")
)

if (nrow(province_generation) > 0) {
  provinces <- sort(unique(province_generation$plant_province))
  province_colors <- setNames(
    grDevices::hcl.colors(length(provinces), palette = "Dark 3"), provinces
  )
  output_path <- save_base_png(file.path(
    "kepco", "province_averages", "raw", "kepco_province_generation_mwh.png"
  ))
  plot(
    range(province_generation$date),
    range(c(
      province_generation$energy_generated_mwh,
      province_generation$energy_generated_mwh_ma6
    ), na.rm = TRUE),
    type = "n", xlab = "Month", ylab = "Generation, MWh",
    main = "Monthly generation by plant province, 6-month moving average"
  )
  grid(col = "grey88")
  for (province in provinces) {
    x <- province_generation[province_generation$plant_province == province, ]
    lines(x$date, x$energy_generated_mwh,
      col = adjustcolor(province_colors[[province]], alpha.f = 0.2), lwd = 0.8)
    lines(x$date, x$energy_generated_mwh_ma6,
      col = province_colors[[province]], lwd = 2)
  }
  legend("topright", legend = provinces, col = province_colors,
    lty = 1, lwd = 2, bty = "n", cex = 0.68, ncol = 2)
  dev.off()
  message("Saved figure: ", output_path)
}

for (i in seq_len(nrow(pollutants))) {
  province_ef <- aggregate_ef(
    analysis_kepco, c("plant_province", "date"), pollutants$pollutant[[i]]
  )
  save_table(
    province_ef,
    file.path(
      "monthly", "province",
      paste0("kepco_province_monthly_", pollutants$pollutant[[i]], "_ef.csv")
    )
  )
  if (nrow(province_ef) == 0) {
    next
  }

  provinces <- sort(unique(province_ef$plant_province))
  province_colors <- setNames(
    grDevices::hcl.colors(length(provinces), palette = "Dark 3"), provinces
  )

  output_path <- save_base_png(file.path(
    "kepco", "province_averages", "ma6",
    paste0("kepco_province_average_", pollutants$pollutant[[i]], "_ef_ma6.png")
  ))
  plot(
    range(province_ef$date), range(province_ef$ef_kg_per_mwh, na.rm = TRUE),
    type = "n", xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " EF, kg/MWh"),
    main = paste0("Average monthly ", pollutants$label[[i]],
      " EF by plant province, 6-month moving average")
  )
  grid(col = "grey88")
  for (province in provinces) {
    x <- province_ef[province_ef$plant_province == province, ]
    lines(x$date, x$ef_kg_per_mwh,
      col = adjustcolor(province_colors[[province]], alpha.f = 0.2), lwd = 0.8)
    lines(x$date, x$ef_ma_kg_per_mwh, col = province_colors[[province]], lwd = 2)
  }
  legend("topright", legend = provinces, col = province_colors,
    lty = 1, lwd = 2, bty = "n", cex = 0.68, ncol = 2)
  dev.off()
  message("Saved figure: ", output_path)

  output_path <- save_base_png(file.path(
    "kepco", "province_averages", "raw",
    paste0("kepco_province_average_", pollutants$pollutant[[i]], "_ef_raw.png")
  ))
  plot(
    range(province_ef$date), range(province_ef$ef_kg_per_mwh, na.rm = TRUE),
    type = "n", xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " EF, kg/MWh"),
    main = paste0("Average monthly ", pollutants$label[[i]],
      " EF by plant province, raw data")
  )
  grid(col = "grey88")
  for (province in provinces) {
    x <- province_ef[province_ef$plant_province == province, ]
    lines(x$date, x$ef_kg_per_mwh, col = province_colors[[province]], lwd = 1.4)
  }
  legend("topright", legend = provinces, col = province_colors,
    lty = 1, lwd = 2, bty = "n", cex = 0.68, ncol = 2)
  dev.off()
  message("Saved figure: ", output_path)

  province_mass <- province_ef[, c(
    "plant_province", "date", "emissions_kg", "generation_mwh"
  )]
  province_mass$emissions_kg_ma6 <- NA_real_
  for (province in provinces) {
    idx <- which(province_mass$plant_province == province)
    idx <- idx[order(province_mass$date[idx])]
    province_mass$emissions_kg_ma6[idx] <- trailing_mean(
      province_mass$emissions_kg[idx], window = 6
    )
  }
  save_table(
    province_mass,
    file.path(
      "monthly", "province",
      paste0("kepco_province_monthly_", pollutants$pollutant[[i]], "_emissions_kg.csv")
    )
  )

  output_path <- save_base_png(file.path(
    "kepco", "province_averages", "raw",
    paste0("kepco_province_", pollutants$pollutant[[i]], "_emissions_kg.png")
  ))
  plot(
    range(province_mass$date),
    range(c(province_mass$emissions_kg, province_mass$emissions_kg_ma6), na.rm = TRUE),
    type = "n", xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " emissions, kg"),
    main = paste0("Monthly ", pollutants$label[[i]],
      " mass emissions by plant province, 6-month moving average")
  )
  grid(col = "grey88")
  for (province in provinces) {
    x <- province_mass[province_mass$plant_province == province, ]
    lines(x$date, x$emissions_kg,
      col = adjustcolor(province_colors[[province]], alpha.f = 0.2), lwd = 0.8)
    lines(x$date, x$emissions_kg_ma6, col = province_colors[[province]], lwd = 2)
  }
  legend("topright", legend = provinces, col = province_colors,
    lty = 1, lwd = 2, bty = "n", cex = 0.68, ncol = 2)
  dev.off()
  message("Saved figure: ", output_path)
}

# Create province-faceted versions at both plant and fuel-type resolution.
# Free y-scales keep provinces with smaller fleets visible instead of flattening
# them against the largest generating provinces.
save_province_faceted_plot <- function(plot, subdir, filename) {
  output_path <- file.path(figures_dir, "kepco", subdir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  ggsave(output_path, plot = plot, width = 14, height = 10, units = "in", dpi = 220)
  message("Saved figure: ", output_path)
}

build_province_breakdown <- function(group_var, output_stub, group_label) {
  group_columns <- c("plant_province", group_var, "date")
  generation_rows <- !is.na(analysis_kepco$energy_generated_mwh)
  generation <- aggregate(
    analysis_kepco$energy_generated_mwh[generation_rows],
    analysis_kepco[generation_rows, group_columns, drop = FALSE],
    sum,
    na.rm = TRUE
  )
  names(generation)[ncol(generation)] <- "energy_generated_mwh"
  generation <- generation[order(generation$date), ]
  generation$energy_generated_mwh_ma6 <- NA_real_
  generation_groups <- interaction(
    generation$plant_province, generation[[group_var]], drop = TRUE
  )
  for (idx in split(seq_len(nrow(generation)), generation_groups)) {
    idx <- idx[order(generation$date[idx])]
    generation$energy_generated_mwh_ma6[idx] <- trailing_mean(
      generation$energy_generated_mwh[idx], window = 6
    )
  }
  save_table(
    generation,
    file.path(
      "monthly", output_stub,
      paste0("kepco_", output_stub, "_monthly_generation_mwh.csv")
    )
  )

  generation_plot <- ggplot(
    generation,
    aes(x = date, group = .data[[group_var]], color = .data[[group_var]])
  ) +
    geom_line(aes(y = energy_generated_mwh), alpha = 0.18, linewidth = 0.3) +
    geom_line(aes(y = energy_generated_mwh_ma6), linewidth = 0.7, na.rm = TRUE) +
    facet_wrap(~plant_province, scales = "free_y") +
    labs(
      title = paste0("Monthly generation by province and ", group_label),
      subtitle = "Faint lines are raw monthly values; solid lines are 6-month moving averages",
      x = NULL, y = "Generation, MWh", color = group_label
    ) +
    theme_minimal(base_size = 10) +
    theme(legend.position = "bottom", legend.text = element_text(size = 7))
  save_province_faceted_plot(
    generation_plot, output_stub, paste0("kepco_", output_stub, "_generation_mwh.png")
  )

  for (i in seq_len(nrow(pollutants))) {
    ef_data <- aggregate_ef(analysis_kepco, group_columns, pollutants$pollutant[[i]])
    save_table(
      ef_data,
      file.path(
        "monthly", output_stub,
        paste0("kepco_", output_stub, "_monthly_", pollutants$pollutant[[i]], "_ef.csv")
      )
    )
    if (nrow(ef_data) == 0) {
      next
    }

    common_aes <- aes(x = date, group = .data[[group_var]], color = .data[[group_var]])
    common_theme <- list(
      facet_wrap(~plant_province, scales = "free_y"),
      theme_minimal(base_size = 10),
      theme(legend.position = "bottom", legend.text = element_text(size = 7))
    )

    raw_plot <- ggplot(ef_data, common_aes) +
      geom_line(aes(y = ef_kg_per_mwh), linewidth = 0.55, na.rm = TRUE) +
      common_theme +
      labs(
        title = paste0("Monthly ", pollutants$label[[i]], " EF by province and ", group_label),
        subtitle = "Raw monthly emission factors after canonical audit exclusions",
        x = NULL, y = paste0(pollutants$label[[i]], " EF, kg/MWh"), color = group_label
      )
    save_province_faceted_plot(
      raw_plot, file.path(output_stub, "raw"),
      paste0("kepco_", output_stub, "_", pollutants$pollutant[[i]], "_ef_raw.png")
    )

    ma_plot <- ggplot(ef_data, common_aes) +
      geom_line(aes(y = ef_kg_per_mwh), alpha = 0.15, linewidth = 0.3, na.rm = TRUE) +
      geom_line(aes(y = ef_ma_kg_per_mwh), linewidth = 0.7, na.rm = TRUE) +
      common_theme +
      labs(
        title = paste0("Monthly ", pollutants$label[[i]], " EF by province and ", group_label),
        subtitle = "Solid lines are 6-month moving averages",
        x = NULL, y = paste0(pollutants$label[[i]], " EF, kg/MWh"), color = group_label
      )
    save_province_faceted_plot(
      ma_plot, file.path(output_stub, "ma6"),
      paste0("kepco_", output_stub, "_", pollutants$pollutant[[i]], "_ef_ma6.png")
    )

    mass_data <- ef_data[, c(
      "plant_province", group_var, "date", "emissions_kg", "generation_mwh"
    )]
    mass_data$emissions_kg_ma6 <- NA_real_
    mass_groups <- interaction(
      mass_data$plant_province, mass_data[[group_var]], drop = TRUE
    )
    for (idx in split(seq_len(nrow(mass_data)), mass_groups)) {
      idx <- idx[order(mass_data$date[idx])]
      mass_data$emissions_kg_ma6[idx] <- trailing_mean(
        mass_data$emissions_kg[idx], window = 6
      )
    }
    save_table(
      mass_data,
      file.path(
        "monthly", output_stub,
        paste0(
          "kepco_", output_stub, "_monthly_", pollutants$pollutant[[i]],
          "_emissions_kg.csv"
        )
      )
    )

    mass_plot <- ggplot(mass_data, common_aes) +
      geom_line(aes(y = emissions_kg), alpha = 0.15, linewidth = 0.3, na.rm = TRUE) +
      geom_line(aes(y = emissions_kg_ma6), linewidth = 0.7, na.rm = TRUE) +
      common_theme +
      labs(
        title = paste0(
          "Monthly ", pollutants$label[[i]], " emissions by province and ", group_label
        ),
        subtitle = "Solid lines are 6-month moving averages",
        x = NULL, y = paste0(pollutants$label[[i]], " emissions, kg"), color = group_label
      )
    save_province_faceted_plot(
      mass_plot, file.path(output_stub, "raw"),
      paste0("kepco_", output_stub, "_", pollutants$pollutant[[i]], "_emissions_kg.png")
    )
  }
}

build_province_breakdown("plant_name", "province_by_plant", "plant")
build_province_breakdown("fuel_type_clean", "province_by_fuel_type", "fuel type")

# ---- Generation-weighted EF point estimates ---------------------------------

# Estimate the EF for a hypothetical ("overnight") plant from the observed
# plants matching any combination of fuel, province, subsidiary, or other
# columns over up to the latest 12 months with valid data by default. Cohorts
# with shorter histories use every available month in that window, reported in
# `months_covered`. Plant EFs are calculated first and then weighted by each
# plant's valid generation. Algebraically this is total emissions / total
# generation, but retaining the plant rows makes the evidence transparent.
estimate_ef <- function(
  data,
  pollutant,
  filters = list(),
  start_date = NULL,
  end_date = NULL,
  recent_months = 12,
  min_coverage_pct = 0.5
) {
  if (!pollutant %in% pollutants$pollutant) {
    stop("pollutant must be one of: ", paste(pollutants$pollutant, collapse = ", "))
  }
  if (length(recent_months) != 1 || is.na(recent_months) ||
      recent_months < 1 || recent_months != as.integer(recent_months)) {
    stop("recent_months must be a positive whole number")
  }

  unknown_filters <- setdiff(names(filters), names(data))
  if (length(unknown_filters) > 0) {
    stop("Unknown filter columns: ", paste(unknown_filters, collapse = ", "))
  }

  selected <- data
  for (filter_name in names(filters)) {
    selected <- selected[
      !is.na(selected[[filter_name]]) & selected[[filter_name]] %in% filters[[filter_name]],
      , drop = FALSE
    ]
  }
  if (!is.null(end_date)) {
    selected <- selected[selected$date <= as.Date(end_date), , drop = FALSE]
  }

  if (is.null(start_date)) {
    valid_dates <- selected$date[
      !is.na(selected[[pollutant]]) &
        !is.na(selected$energy_generated_mwh) & selected$energy_generated_mwh > 0
    ]
    if (length(valid_dates) == 0) return(NULL)
    window_end <- max(valid_dates)
    window_start <- min(seq(window_end, by = "-1 month", length.out = recent_months))
    selected <- selected[
      selected$date >= window_start & selected$date <= window_end,
      , drop = FALSE
    ]
  } else {
    selected <- selected[selected$date >= as.Date(start_date), , drop = FALSE]
  }

  total_generation <- sum(
    selected$energy_generated_mwh[
      !is.na(selected$energy_generated_mwh) & selected$energy_generated_mwh > 0
    ],
    na.rm = TRUE
  )
  valid <- !is.na(selected[[pollutant]]) &
    !is.na(selected$energy_generated_mwh) & selected$energy_generated_mwh > 0
  selected <- selected[valid, , drop = FALSE]

  if (nrow(selected) == 0 || total_generation <= 0) return(NULL)
  months_covered <- length(unique(selected$date))
  selected$obs_ef_kg_per_mwh <- selected[[pollutant]] / selected$energy_generated_mwh

  plant_emissions <- aggregate(
    selected[[pollutant]],
    selected[c("plant_name")],
    sum,
    na.rm = TRUE
  )
  plant_generation <- aggregate(
    selected$energy_generated_mwh,
    selected[c("plant_name")],
    sum,
    na.rm = TRUE
  )
  names(plant_emissions)[2] <- "emissions_kg"
  names(plant_generation)[2] <- "generation_mwh"
  plant_estimates <- merge(plant_emissions, plant_generation, by = "plant_name")
  valid_generation <- sum(plant_estimates$generation_mwh)
  coverage_pct <- valid_generation / total_generation

  if (coverage_pct < min_coverage_pct) return(NULL)

  plant_estimates$plant_ef_kg_per_mwh <-
    plant_estimates$emissions_kg / plant_estimates$generation_mwh
  plant_estimates$generation_weight <-
    plant_estimates$generation_mwh / valid_generation

  estimate <- weighted.mean(
    plant_estimates$plant_ef_kg_per_mwh,
    plant_estimates$generation_mwh
  )

  list(
    estimate = data.frame(
      pollutant = pollutant,
      ef_kg_per_mwh = estimate,
      plant_count = nrow(plant_estimates),
      valid_generation_mwh = valid_generation,
      generation_coverage_pct = coverage_pct,
      months_covered = months_covered,
      start_date = if (nrow(selected)) min(selected$date) else as.Date(NA),
      end_date = if (nrow(selected)) max(selected$date) else as.Date(NA),
      filter = if (length(filters)) paste(
        paste0(names(filters), "=", vapply(filters, paste, collapse = "|", character(1))),
        collapse = ";"
      ) else "all",
      row.names = NULL
    ),
    plants = plant_estimates[order(-plant_estimates$generation_weight), ],
    observations = selected[
      order(selected$date, selected$plant_name),
      c("date", "plant_name", "energy_generated_mwh", pollutant, "obs_ef_kg_per_mwh")
    ]
  )
}

# Point estimates by fuel type, plus province-by-fuel estimates for questions
# such as: "What is the NOx EF for a coal plant in this province?"
point_estimate_rows <- list()
for (i in seq_len(nrow(pollutants))) {
  pollutant <- pollutants$pollutant[[i]]
  for (fuel in sort(unique(analysis_kepco$fuel_type_clean))) {
    result <- estimate_ef(
      analysis_kepco, pollutant,
      filters = list(fuel_type_clean = fuel)
    )
    if (!is.null(result)) {
      row <- result$estimate
      row$plant_province <- "all"
      row$fuel_type <- fuel
      point_estimate_rows[[length(point_estimate_rows) + 1]] <- row
    }
  }
  province_fuels <- unique(analysis_kepco[c("plant_province", "fuel_type_clean")])
  province_fuels <- province_fuels[complete.cases(province_fuels), ]
  for (j in seq_len(nrow(province_fuels))) {
    result <- estimate_ef(
      analysis_kepco, pollutant,
      filters = list(
        plant_province = province_fuels$plant_province[[j]],
        fuel_type_clean = province_fuels$fuel_type_clean[[j]]
      )
    )
    if (!is.null(result)) {
      row <- result$estimate
      row$plant_province <- province_fuels$plant_province[[j]]
      row$fuel_type <- province_fuels$fuel_type_clean[[j]]
      point_estimate_rows[[length(point_estimate_rows) + 1]] <- row
    }
  }
}
ef_point_estimates <- do.call(rbind, point_estimate_rows)
ef_point_estimates$ef_specification <- "operational_primary"
save_table(
  ef_point_estimates,
  file.path("point_estimates", "kepco_generation_weighted_ef_point_estimates.csv")
)

overnight_ef_figure_data <- ef_point_estimates %>%
  filter(plant_province != "all") %>%
  mutate(
    pollutant = factor(
      pollutant,
      levels = c("nox", "sox", "dust_tsp"),
      labels = c("NOx", "SOx", "TSP")
    ),
    fuel_type = gsub("_", " ", fuel_type),
    cell_label = ifelse(
      ef_kg_per_mwh >= 0.01,
      sprintf("%.3f", ef_kg_per_mwh),
      sprintf("%.4f", ef_kg_per_mwh)
    )
  ) %>%
  complete(
    pollutant,
    plant_province,
    fuel_type,
    fill = list(cell_label = "—")
  )

overnight_ef_table_figure <- ggplot(
  overnight_ef_figure_data,
  aes(x = fuel_type, y = plant_province)
) +
  geom_tile(aes(fill = ef_kg_per_mwh), color = "white", linewidth = 0.8) +
  geom_text(aes(label = cell_label), size = 3.3, color = "#17202A") +
  facet_grid(pollutant ~ ., scales = "free_y", space = "free_y") +
  scale_fill_gradient(
    low = "#F4F9FD",
    high = "#2878B5",
    na.value = "#F2F2F2",
    name = "kg/MWh"
  ) +
  labs(
    title = "Overnight plant emission factors by province and fuel type",
    subtitle = paste0(
      "Generation-weighted estimates using up to each cohort's most recent 12 months; ",
      "— indicates insufficient data"
    ),
    x = "Fuel type",
    y = NULL,
    caption = paste0(
      "Values are kilograms of pollutant per MWh of electricity generated. ",
      "Shorter histories use all available months."
    )
  ) +
  theme_minimal(base_size = 11) +
  theme(
    panel.grid = element_blank(),
    axis.text.x = element_text(angle = 35, hjust = 1),
    strip.text.y = element_text(face = "bold", angle = 0),
    strip.background = element_rect(fill = "#EAF2F8", color = NA),
    plot.title = element_text(face = "bold", size = 15),
    plot.subtitle = element_text(color = "#4D4D4D"),
    legend.position = "right"
  )

save_figure(
  file.path("kepco", "overnight_ef", "kepco_province_by_fuel_overnight_ef.png"),
  overnight_ef_table_figure,
  width = 13,
  height = 13
)

# Full-calendar-year EF estimates by observed fuel x technology cohort. The
# handoff tables intentionally keep only physically observed cohorts; they do
# not complete a rectangular fuel-by-technology matrix.
summarize_ef_distribution <- function(x) {
  x <- x[!is.na(x)]
  if (length(x) == 0) {
    return(c(
      n = 0, mean = NA, sd = NA, min = NA, p10 = NA, p25 = NA,
      median = NA, p75 = NA, p90 = NA, max = NA, iqr = NA
    ))
  }

  c(
    n = length(x),
    mean = mean(x),
    sd = ifelse(length(x) > 1, sd(x), NA_real_),
    min = min(x),
    p10 = unname(quantile(x, 0.10)),
    p25 = unname(quantile(x, 0.25)),
    median = median(x),
    p75 = unname(quantile(x, 0.75)),
    p90 = unname(quantile(x, 0.90)),
    max = max(x),
    iqr = unname(IQR(x))
  )
}

annual_fuel_technology_distribution_rows <- function(
  data,
  estimate_year,
  province_level = FALSE
) {
  year_data <- data[data$year == estimate_year, , drop = FALSE]
  group_vars <- c(if (province_level) "plant_province", "fuel_type_clean", "technology")
  cohorts <- unique(year_data[group_vars])
  cohorts <- cohorts[complete.cases(cohorts), , drop = FALSE]
  cohorts <- cohorts[do.call(order, cohorts), , drop = FALSE]

  rows <- list()
  for (i in seq_len(nrow(pollutants))) {
    pollutant <- pollutants$pollutant[[i]]
    pollutant_label <- pollutants$label[[i]]
    for (j in seq_len(nrow(cohorts))) {
      filters <- as.list(cohorts[j, , drop = FALSE])
      result <- estimate_ef(
        data,
        pollutant,
        filters = filters,
        start_date = as.Date(sprintf("%d-01-01", estimate_year)),
        end_date = as.Date(sprintf("%d-12-31", estimate_year))
      )
      if (is.null(result)) {
        next
      }

      plant_distribution <- summarize_ef_distribution(result$plants$plant_ef_kg_per_mwh)
      monthly_distribution <- summarize_ef_distribution(
        result$observations$obs_ef_kg_per_mwh
      )
      row <- cbind(
        data.frame(
          year = estimate_year,
          cohorts[j, , drop = FALSE],
          pollutant = pollutant,
          pollutant_label = pollutant_label,
          row.names = NULL,
          check.names = FALSE
        ),
        data.frame(
          ef_kg_per_mwh = result$estimate$ef_kg_per_mwh,
          plant_ef_mean_kg_per_mwh = plant_distribution[["mean"]],
          plant_ef_sd_kg_per_mwh = plant_distribution[["sd"]],
          plant_ef_min_kg_per_mwh = plant_distribution[["min"]],
          plant_ef_p10_kg_per_mwh = plant_distribution[["p10"]],
          plant_ef_p25_kg_per_mwh = plant_distribution[["p25"]],
          plant_ef_median_kg_per_mwh = plant_distribution[["median"]],
          plant_ef_p75_kg_per_mwh = plant_distribution[["p75"]],
          plant_ef_p90_kg_per_mwh = plant_distribution[["p90"]],
          plant_ef_max_kg_per_mwh = plant_distribution[["max"]],
          plant_ef_iqr_kg_per_mwh = plant_distribution[["iqr"]],
          monthly_ef_mean_kg_per_mwh = monthly_distribution[["mean"]],
          monthly_ef_sd_kg_per_mwh = monthly_distribution[["sd"]],
          monthly_ef_min_kg_per_mwh = monthly_distribution[["min"]],
          monthly_ef_p10_kg_per_mwh = monthly_distribution[["p10"]],
          monthly_ef_p25_kg_per_mwh = monthly_distribution[["p25"]],
          monthly_ef_median_kg_per_mwh = monthly_distribution[["median"]],
          monthly_ef_p75_kg_per_mwh = monthly_distribution[["p75"]],
          monthly_ef_p90_kg_per_mwh = monthly_distribution[["p90"]],
          monthly_ef_max_kg_per_mwh = monthly_distribution[["max"]],
          monthly_ef_iqr_kg_per_mwh = monthly_distribution[["iqr"]],
          plant_count = result$estimate$plant_count,
          plant_month_count = monthly_distribution[["n"]],
          valid_generation_mwh = result$estimate$valid_generation_mwh,
          generation_coverage_pct = result$estimate$generation_coverage_pct,
          months_covered = result$estimate$months_covered,
          start_date = result$estimate$start_date,
          end_date = result$estimate$end_date,
          row.names = NULL,
          check.names = FALSE
        )
      )
      rows[[length(rows) + 1]] <- row
    }
  }

  if (length(rows) == 0) {
    return(data.frame())
  }

  do.call(rbind, rows) %>%
    arrange(across(all_of(c("year", group_vars, "pollutant"))))
}

format_fuel_technology_handoff_table <- function(data, province_level = FALSE) {
  if (nrow(data) == 0) {
    return(data.frame())
  }

  id_cols <- c("year", if (province_level) "plant_province", "fuel_type_clean", "technology")
  data %>%
    select(
      all_of(id_cols), pollutant,
      ef_kg_per_mwh, plant_ef_mean_kg_per_mwh, plant_ef_sd_kg_per_mwh,
      plant_ef_min_kg_per_mwh, plant_ef_p10_kg_per_mwh,
      plant_ef_p25_kg_per_mwh, plant_ef_median_kg_per_mwh,
      plant_ef_p75_kg_per_mwh, plant_ef_p90_kg_per_mwh,
      plant_ef_max_kg_per_mwh, plant_ef_iqr_kg_per_mwh,
      monthly_ef_mean_kg_per_mwh, monthly_ef_sd_kg_per_mwh,
      monthly_ef_min_kg_per_mwh, monthly_ef_p10_kg_per_mwh,
      monthly_ef_p25_kg_per_mwh, monthly_ef_median_kg_per_mwh,
      monthly_ef_p75_kg_per_mwh, monthly_ef_p90_kg_per_mwh,
      monthly_ef_max_kg_per_mwh, monthly_ef_iqr_kg_per_mwh,
      plant_count, plant_month_count, valid_generation_mwh, generation_coverage_pct,
      months_covered, start_date, end_date
    ) %>%
    pivot_wider(
      id_cols = all_of(id_cols),
      names_from = pollutant,
      values_from = c(
        ef_kg_per_mwh, plant_ef_mean_kg_per_mwh, plant_ef_sd_kg_per_mwh,
        plant_ef_min_kg_per_mwh, plant_ef_p10_kg_per_mwh,
        plant_ef_p25_kg_per_mwh, plant_ef_median_kg_per_mwh,
        plant_ef_p75_kg_per_mwh, plant_ef_p90_kg_per_mwh,
        plant_ef_max_kg_per_mwh, plant_ef_iqr_kg_per_mwh,
        monthly_ef_mean_kg_per_mwh, monthly_ef_sd_kg_per_mwh,
        monthly_ef_min_kg_per_mwh, monthly_ef_p10_kg_per_mwh,
        monthly_ef_p25_kg_per_mwh, monthly_ef_median_kg_per_mwh,
        monthly_ef_p75_kg_per_mwh, monthly_ef_p90_kg_per_mwh,
        monthly_ef_max_kg_per_mwh, monthly_ef_iqr_kg_per_mwh,
        plant_count, plant_month_count, valid_generation_mwh, generation_coverage_pct,
        months_covered, start_date, end_date
      ),
      names_glue = "{pollutant}_{.value}"
    ) %>%
    select(
      all_of(id_cols),
      starts_with("nox_"),
      starts_with("sox_"),
      starts_with("dust_tsp_")
    ) %>%
    arrange(across(all_of(id_cols)))
}

build_annual_ef_distribution <- function(data, province_level = FALSE) {
  years <- sort(unique(data$year[!is.na(data$year)]))
  pieces <- lapply(years, function(estimate_year) {
    annual_fuel_technology_distribution_rows(
      data = data,
      estimate_year = estimate_year,
      province_level = province_level
    )
  })
  pieces <- pieces[vapply(pieces, nrow, integer(1)) > 0]
  if (length(pieces) == 0) {
    return(data.frame())
  }
  do.call(rbind, pieces)
}

annual_years <- sort(unique(analysis_kepco$year[!is.na(analysis_kepco$year)]))
annual_fuel_technology_ef <- build_annual_ef_distribution(
  analysis_kepco,
  province_level = FALSE
)
annual_fuel_technology_ef$ef_specification <- "operational_primary"
annual_province_fuel_technology_ef <- build_annual_ef_distribution(
  analysis_kepco,
  province_level = TRUE
)
annual_province_fuel_technology_ef$ef_specification <- "operational_primary"

annual_fuel_technology_sensitivity <- bind_rows(
  annual_fuel_technology_ef,
  build_annual_ef_distribution(
    analysis_kepco_low_load_inclusive,
    province_level = FALSE
  ) %>% mutate(ef_specification = "low_load_inclusive"),
  build_annual_ef_distribution(
    analysis_kepco_conservative,
    province_level = FALSE
  ) %>% mutate(ef_specification = "conservative_quality")
) %>%
  arrange(year, fuel_type_clean, technology, pollutant, ef_specification)
annual_province_fuel_technology_sensitivity <- bind_rows(
  annual_province_fuel_technology_ef,
  build_annual_ef_distribution(
    analysis_kepco_low_load_inclusive,
    province_level = TRUE
  ) %>% mutate(ef_specification = "low_load_inclusive"),
  build_annual_ef_distribution(
    analysis_kepco_conservative,
    province_level = TRUE
  ) %>% mutate(ef_specification = "conservative_quality")
) %>%
  arrange(
    year,
    plant_province,
    fuel_type_clean,
    technology,
    pollutant,
    ef_specification
  )

annual_fuel_technology_handoff <- format_fuel_technology_handoff_table(
  annual_fuel_technology_ef,
  province_level = FALSE
)
annual_province_fuel_technology_handoff <- format_fuel_technology_handoff_table(
  annual_province_fuel_technology_ef,
  province_level = TRUE
)

format_ef_cell <- function(weighted, median, p10, p90) {
  if (is.na(weighted)) {
    return("")
  }
  if (is.na(median) || is.na(p10) || is.na(p90)) {
    return(sprintf("%.3f", weighted))
  }
  sprintf("%.3f\nmed %.3f\n[%.3f, %.3f]", weighted, median, p10, p90)
}

format_editable_fuel_technology_table <- function(data, province_level = FALSE) {
  if (nrow(data) == 0) {
    return(data.frame())
  }

  id_cols <- c("year", if (province_level) "plant_province", "fuel_technology")
  table_data <- data %>%
    mutate(
      fuel_type_label = gsub("_", " ", fuel_type_clean),
      technology_label = gsub("_", " ", technology),
      fuel_technology = paste(fuel_type_label, technology_label, sep = " / "),
      ef_cell = mapply(
        format_ef_cell,
        ef_kg_per_mwh,
        monthly_ef_median_kg_per_mwh,
        monthly_ef_p10_kg_per_mwh,
        monthly_ef_p90_kg_per_mwh,
        USE.NAMES = FALSE
      ),
      plant_record_cell = ifelse(
        is.na(plant_count),
        "",
        paste0(plant_count, " / ", plant_month_count)
      ),
      coverage_cell = ifelse(
        is.na(generation_coverage_pct),
        "",
        percent(generation_coverage_pct, accuracy = 1)
      ),
      months_cell = ifelse(is.na(months_covered), "", as.character(months_covered))
    ) %>%
    select(
      all_of(id_cols), pollutant,
      ef_cell, plant_record_cell, coverage_cell, months_cell
    )

  wide <- table_data %>%
    pivot_wider(
      id_cols = all_of(id_cols),
      names_from = pollutant,
      values_from = c(ef_cell, plant_record_cell, coverage_cell, months_cell),
      names_glue = "{pollutant}_{.value}"
    ) %>%
    arrange(across(all_of(id_cols)))

  expected_columns <- c(
    "nox_ef_cell", "sox_ef_cell", "dust_tsp_ef_cell",
    "nox_plant_record_cell", "sox_plant_record_cell",
    "dust_tsp_plant_record_cell",
    "nox_coverage_cell", "sox_coverage_cell", "dust_tsp_coverage_cell",
    "nox_months_cell", "sox_months_cell", "dust_tsp_months_cell"
  )
  for (column in expected_columns) {
    if (!column %in% names(wide)) {
      wide[[column]] <- ""
    }
    wide[[column]][is.na(wide[[column]])] <- ""
  }

  combine_pollutant_cells <- function(nox, sox, tsp) {
    paste0("NOx: ", nox, "\nSOx: ", sox, "\nTSP: ", tsp)
  }

  display <- data.frame(
    year = wide$year,
    fuel_technology = wide$fuel_technology,
    nox_kg_per_mwh = wide$nox_ef_cell,
    sox_kg_per_mwh = wide$sox_ef_cell,
    tsp_kg_per_mwh = wide$dust_tsp_ef_cell,
    plants_records = combine_pollutant_cells(
      wide$nox_plant_record_cell,
      wide$sox_plant_record_cell,
      wide$dust_tsp_plant_record_cell
    ),
    generation_coverage = combine_pollutant_cells(
      wide$nox_coverage_cell,
      wide$sox_coverage_cell,
      wide$dust_tsp_coverage_cell
    ),
    months_covered = combine_pollutant_cells(
      wide$nox_months_cell,
      wide$sox_months_cell,
      wide$dust_tsp_months_cell
    ),
    stringsAsFactors = FALSE
  )

  if (province_level) {
    display <- cbind(
      display["year"],
      data.frame(plant_province = wide$plant_province, stringsAsFactors = FALSE),
      display[names(display) != "year"]
    )
  }

  display
}

save_table(
  annual_fuel_technology_handoff,
  file.path("annual_handoff", "kepco_annual_ef_handoff_by_fuel_technology.csv")
)
save_table(
  annual_province_fuel_technology_handoff,
  file.path(
    "annual_handoff",
    "kepco_annual_ef_handoff_by_province_fuel_technology.csv"
  )
)
save_table(
  annual_fuel_technology_ef,
  file.path("annual_handoff", "kepco_annual_ef_distribution_long_by_fuel_technology.csv")
)
save_processed_ef(
  annual_fuel_technology_ef,
  "kepco_annual_ef_distribution_long_by_fuel_technology.csv"
)
save_table(
  annual_province_fuel_technology_ef,
  file.path(
    "annual_handoff",
    "kepco_annual_ef_distribution_long_by_province_fuel_technology.csv"
  )
)
save_table(
  annual_fuel_technology_sensitivity,
  file.path(
    "annual_handoff",
    "kepco_annual_ef_sensitivity_long_by_fuel_technology.csv"
  )
)
save_table(
  annual_province_fuel_technology_sensitivity,
  file.path(
    "annual_handoff",
    "kepco_annual_ef_sensitivity_long_by_province_fuel_technology.csv"
  )
)
save_table(
  format_editable_fuel_technology_table(
    annual_fuel_technology_ef,
    province_level = FALSE
  ),
  file.path("annual_handoff", "kepco_annual_ef_editable_by_fuel_technology.csv")
)
save_table(
  format_editable_fuel_technology_table(
    annual_province_fuel_technology_ef,
    province_level = TRUE
  ),
  file.path(
    "annual_handoff",
    "kepco_annual_ef_editable_by_province_fuel_technology.csv"
  )
)

python_executable <- Sys.which("python")
if (nzchar(python_executable)) {
  workbook_status <- system2(
    python_executable,
    c("-m", "nzk_aphiam.data.export.kepco_handoff_workbook"),
    env = c("PYTHONPATH=src"),
    stdout = TRUE,
    stderr = TRUE
  )
  if (!is.null(attr(workbook_status, "status"))) {
    warning(
      "Could not write editable KEPCO Excel workbook:\n",
      paste(workbook_status, collapse = "\n"),
      call. = FALSE
    )
  } else {
    message("Saved workbook: ", tail(workbook_status, 1))
  }
} else {
  warning("Python executable not found; skipping editable KEPCO Excel workbook.", call. = FALSE)
}

old_matrix_table <- file.path(
  tables_dir, "annual_handoff",
  "kepco_2021_2025_generation_weighted_ef_by_fuel_technology.csv"
)
if (file.exists(old_matrix_table)) {
  unlink(old_matrix_table)
  message("Deleted superseded matrix table: ", old_matrix_table)
}

old_matrix_figures <- file.path(
  figures_dir,
  "kepco", "fuel_technology_year",
  paste0("kepco_", annual_years, "_fuel_technology_ef.png")
)
for (old_matrix_figure in old_matrix_figures[file.exists(old_matrix_figures)]) {
  unlink(old_matrix_figure)
  message("Deleted superseded matrix figure: ", old_matrix_figure)
}

flat_annual_figure_dir <- file.path(figures_dir, "kepco", "fuel_technology_year")
flat_annual_figures <- list.files(
  flat_annual_figure_dir,
  pattern = "^kepco_[0-9]{4}_.*fuel_technology.*\\.png$",
  full.names = TRUE
)
for (flat_annual_figure in flat_annual_figures) {
  unlink(flat_annual_figure)
  message("Deleted superseded flat annual figure: ", flat_annual_figure)
}

flat_table_dir <- file.path(flat_annual_figure_dir, "tables")
if (dir.exists(flat_table_dir)) {
  unlink(flat_table_dir, recursive = TRUE)
  message("Deleted superseded flat annual table directory: ", flat_table_dir)
}

wrap_table_text <- function(x, width = 26) {
  vapply(
    x,
    function(value) paste(strwrap(value, width = width), collapse = "\n"),
    character(1)
  )
}

plot_fuel_technology_table <- function(data, estimate_year, province_level = FALSE) {
  table_data <- data %>%
    filter(year == estimate_year) %>%
    mutate(
      fuel_type_label = gsub("_", " ", fuel_type_clean),
      technology_label = gsub("_", " ", technology),
      cohort_label = paste(fuel_type_label, technology_label, sep = "\n"),
      ef_cell = mapply(
        format_ef_cell,
        ef_kg_per_mwh,
        monthly_ef_median_kg_per_mwh,
        monthly_ef_p10_kg_per_mwh,
        monthly_ef_p90_kg_per_mwh,
        USE.NAMES = FALSE
      ),
      plant_cell = ifelse(
        is.na(plant_count),
        "",
        paste0(plant_count, " / ", plant_month_count)
      ),
      coverage_cell = ifelse(
        is.na(generation_coverage_pct),
        "",
        percent(generation_coverage_pct, accuracy = 1)
      )
    )

  wide <- table_data %>%
    select(
      all_of(c(if (province_level) "plant_province", "cohort_label")),
      pollutant, ef_cell, plant_cell, coverage_cell
    ) %>%
    pivot_wider(
      id_cols = all_of(c(if (province_level) "plant_province", "cohort_label")),
      names_from = pollutant,
      values_from = c(ef_cell, plant_cell, coverage_cell),
      names_glue = "{pollutant}_{.value}"
    ) %>%
    arrange(across(all_of(c(if (province_level) "plant_province", "cohort_label"))))

  expected_columns <- c(
    "nox_ef_cell", "sox_ef_cell", "dust_tsp_ef_cell",
    "nox_plant_cell", "sox_plant_cell", "dust_tsp_plant_cell",
    "nox_coverage_cell", "sox_coverage_cell", "dust_tsp_coverage_cell"
  )
  for (column in expected_columns) {
    if (!column %in% names(wide)) {
      wide[[column]] <- ""
    }
    wide[[column]][is.na(wide[[column]])] <- ""
  }

  if (province_level) {
    display <- data.frame(
      province = wrap_table_text(wide$plant_province, width = 16),
      cohort = wrap_table_text(wide$cohort_label, width = 22),
      nox = wide$nox_ef_cell,
      sox = wide$sox_ef_cell,
      tsp = wide$dust_tsp_ef_cell,
      plant_n = paste(wide$nox_plant_cell, wide$sox_plant_cell, wide$dust_tsp_plant_cell, sep = "\n"),
      coverage = paste(
        wide$nox_coverage_cell, wide$sox_coverage_cell, wide$dust_tsp_coverage_cell,
        sep = "\n"
      ),
      stringsAsFactors = FALSE
    )
    names(display) <- c(
      "Province",
      "Fuel / tech",
      "NOx\nkg/MWh",
      "SOx\nkg/MWh",
      "TSP\nkg/MWh",
      "Plants / records\nNOx SOx TSP",
      "Gen. coverage\nNOx SOx TSP"
    )
  } else {
    display <- data.frame(
      cohort = wrap_table_text(wide$cohort_label, width = 24),
      nox = wide$nox_ef_cell,
      sox = wide$sox_ef_cell,
      tsp = wide$dust_tsp_ef_cell,
      plant_n = paste(wide$nox_plant_cell, wide$sox_plant_cell, wide$dust_tsp_plant_cell, sep = "\n"),
      coverage = paste(
        wide$nox_coverage_cell, wide$sox_coverage_cell, wide$dust_tsp_coverage_cell,
        sep = "\n"
      ),
      stringsAsFactors = FALSE
    )
    names(display) <- c(
      "Fuel / tech",
      "NOx\nkg/MWh",
      "SOx\nkg/MWh",
      "TSP\nkg/MWh",
      "Plants / records\nNOx SOx TSP",
      "Gen. coverage\nNOx SOx TSP"
    )
  }

  table_values <- rbind(names(display), as.matrix(display))
  row_count <- nrow(table_values)
  col_count <- ncol(table_values)
  col_widths <- if (province_level) {
    c(2.4, 3.2, 2.5, 2.5, 2.5, 2.2, 2.4)
  } else {
    c(3.4, 2.5, 2.5, 2.5, 2.2, 2.4)
  }
  x_min <- cumsum(c(0, head(col_widths, -1)))
  x_max <- cumsum(col_widths)
  row_y <- rev(seq_len(row_count))

  cell_grid <- expand.grid(row = seq_len(row_count), col = seq_len(col_count))
  cell_grid$label <- as.vector(table_values)
  cell_grid$xmin <- x_min[cell_grid$col]
  cell_grid$xmax <- x_max[cell_grid$col]
  cell_grid$y <- row_y[cell_grid$row]
  cell_grid$is_header <- cell_grid$row == 1
  cell_grid$fill <- ifelse(
    cell_grid$is_header,
    "#D9EAF7",
    ifelse(cell_grid$row %% 2 == 0, "#FFFFFF", "#F6F8FA")
  )
  cell_grid$text_color <- ifelse(cell_grid$is_header, "#102A43", "#17202A")
  cell_grid$fontface <- ifelse(cell_grid$is_header, "bold", "plain")
  cell_grid$hjust <- ifelse(
    cell_grid$col <= ifelse(province_level, 2, 1),
    0,
    0.5
  )
  cell_grid$text_x <- ifelse(
    cell_grid$col <= ifelse(province_level, 2, 1),
    cell_grid$xmin + 0.08,
    (cell_grid$xmin + cell_grid$xmax) / 2
  )

  title <- paste0(
    estimate_year,
    ifelse(province_level, " provincial", " national"),
    " emission factors by observed fuel and technology"
  )
  subtitle <- paste0(
    "Pollutant cells show generation-weighted EF, monthly median, and monthly p10-p90 in brackets; ",
    "blank cells mean no usable pollutant data for that observed cohort."
  )

  ggplot(cell_grid) +
    geom_rect(
      aes(xmin = xmin, xmax = xmax, ymin = y - 0.5, ymax = y + 0.5, fill = fill),
      color = "#D0D7DE",
      linewidth = 0.25
    ) +
    geom_text(
      aes(
        x = text_x, y = y, label = label, hjust = hjust,
        color = text_color, fontface = fontface
      ),
      size = ifelse(province_level, 2.35, 2.7),
      lineheight = 0.92
    ) +
    scale_fill_identity() +
    scale_color_identity() +
    coord_cartesian(
      xlim = c(0, sum(col_widths)),
      ylim = c(0.45, row_count + 0.55),
      expand = FALSE,
      clip = "off"
    ) +
    labs(title = title, subtitle = subtitle, x = NULL, y = NULL) +
    theme_void(base_size = 10) +
    theme(
      plot.title = element_text(face = "bold", size = 15, color = "#102A43"),
      plot.subtitle = element_text(size = 9, color = "#4D4D4D", margin = margin(b = 8)),
      plot.margin = margin(14, 14, 14, 14)
    )
}

plot_fuel_technology_distribution <- function(data, estimate_year, province_level = FALSE) {
  figure_data <- data %>%
    filter(year == estimate_year) %>%
    mutate(
      pollutant_label = factor(pollutant_label, levels = c("NOx", "SOx", "TSP")),
      fuel_type_label = gsub("_", " ", fuel_type_clean),
      technology_label = gsub("_", " ", technology),
      cohort_label = paste(fuel_type_label, technology_label, sep = " | ")
    )

  if (province_level) {
    figure_data <- figure_data %>%
      mutate(cohort_label = paste(plant_province, cohort_label, sep = " | "))
  }

  ggplot(
    figure_data,
    aes(
      x = ef_kg_per_mwh,
      y = reorder(cohort_label, ef_kg_per_mwh),
      color = fuel_type_label
    )
  ) +
    geom_linerange(
      aes(xmin = plant_ef_min_kg_per_mwh, xmax = plant_ef_max_kg_per_mwh),
      alpha = 0.45,
      linewidth = 0.7,
      na.rm = TRUE
    ) +
    geom_point(aes(x = plant_ef_median_kg_per_mwh), shape = 21, fill = "white", size = 2) +
    geom_point(size = 2.6, na.rm = TRUE) +
    facet_wrap(~pollutant_label, scales = "free_x") +
    scale_x_continuous(labels = label_number(accuracy = 0.001)) +
    labs(
      title = paste0(
        estimate_year,
        if (province_level) " provincial" else " national",
        " EF distributions by observed fuel and technology"
      ),
      subtitle = paste0(
        "Line = plant-level min to max; open point = plant median; ",
        "filled point = generation-weighted cohort EF"
      ),
      x = "Emission factor, kg/MWh",
      y = NULL,
      color = "Fuel type",
      caption = "Rows are only observed fuel + technology cohorts; no unobserved matrix cells are created."
    ) +
    theme_minimal(base_size = 10) +
    theme(
      legend.position = "bottom",
      panel.grid.minor = element_blank(),
      strip.text = element_text(face = "bold"),
      plot.title = element_text(face = "bold", size = 14),
      axis.text.y = element_text(size = 7)
    )
}

plot_fuel_technology_monthly_distribution <- function(
  data,
  estimate_year,
  province_level = FALSE
) {
  figure_data <- data %>%
    filter(year == estimate_year) %>%
    mutate(
      pollutant_label = factor(pollutant_label, levels = c("NOx", "SOx", "TSP")),
      fuel_type_label = gsub("_", " ", fuel_type_clean),
      technology_label = gsub("_", " ", technology),
      cohort_label = paste(fuel_type_label, technology_label, sep = " | ")
    )

  if (province_level) {
    figure_data <- figure_data %>%
      mutate(cohort_label = paste(plant_province, cohort_label, sep = " | "))
  }

  ggplot(
    figure_data,
    aes(
      x = ef_kg_per_mwh,
      y = reorder(cohort_label, ef_kg_per_mwh),
      color = fuel_type_label
    )
  ) +
    geom_linerange(
      aes(xmin = monthly_ef_p10_kg_per_mwh, xmax = monthly_ef_p90_kg_per_mwh),
      alpha = 0.28,
      linewidth = 1.0,
      na.rm = TRUE
    ) +
    geom_linerange(
      aes(xmin = monthly_ef_p25_kg_per_mwh, xmax = monthly_ef_p75_kg_per_mwh),
      alpha = 0.70,
      linewidth = 2.0,
      na.rm = TRUE
    ) +
    geom_point(aes(x = monthly_ef_median_kg_per_mwh), shape = 21, fill = "white", size = 2) +
    geom_point(size = 2.6, na.rm = TRUE) +
    facet_wrap(~pollutant_label, scales = "free_x") +
    scale_x_continuous(labels = label_number(accuracy = 0.001)) +
    labs(
      title = paste0(
        estimate_year,
        if (province_level) " provincial" else " national",
        " monthly EF distributions by observed fuel and technology"
      ),
      subtitle = paste0(
        "Thin line = monthly p10-p90; thick line = monthly p25-p75; ",
        "open point = monthly median; filled point = generation-weighted annual EF"
      ),
      x = "Emission factor, kg/MWh",
      y = NULL,
      color = "Fuel type",
      caption = "Monthly ranges summarize plant-month EF observations within physically observed cohorts."
    ) +
    theme_minimal(base_size = 10) +
    theme(
      legend.position = "bottom",
      panel.grid.minor = element_blank(),
      strip.text = element_text(face = "bold"),
      plot.title = element_text(face = "bold", size = 14),
      axis.text.y = element_text(size = 7)
    )
}

for (estimate_year in annual_years) {
  annual_figure_dir <- file.path(
    "kepco", "fuel_technology_year", paste0("year=", estimate_year)
  )

  national_table <- plot_fuel_technology_table(
    annual_fuel_technology_ef,
    estimate_year,
    province_level = FALSE
  )
  national_table_rows <- nrow(unique(
    annual_fuel_technology_ef[
      annual_fuel_technology_ef$year == estimate_year,
      c("fuel_type_clean", "technology")
    ]
  ))
  save_figure(
    file.path(
      annual_figure_dir,
      "kepco_fuel_technology_ef_table.png"
    ),
    national_table,
    width = 15.5,
    height = max(5.5, 1.8 + 0.55 * national_table_rows)
  )

  provincial_table <- plot_fuel_technology_table(
    annual_province_fuel_technology_ef,
    estimate_year,
    province_level = TRUE
  )
  provincial_table_rows <- nrow(unique(
    annual_province_fuel_technology_ef[
      annual_province_fuel_technology_ef$year == estimate_year,
      c("plant_province", "fuel_type_clean", "technology")
    ]
  ))
  save_figure(
    file.path(
      annual_figure_dir,
      "kepco_province_fuel_technology_ef_table.png"
    ),
    provincial_table,
    width = 18.5,
    height = max(6.5, 1.8 + 0.55 * provincial_table_rows)
  )

  national_plot <- plot_fuel_technology_distribution(
    annual_fuel_technology_ef,
    estimate_year,
    province_level = FALSE
  )
  save_figure(
    file.path(
      annual_figure_dir,
      "kepco_fuel_technology_ef_distribution.png"
    ),
    national_plot,
    width = 13,
    height = 8
  )

  national_monthly_plot <- plot_fuel_technology_monthly_distribution(
    annual_fuel_technology_ef,
    estimate_year,
    province_level = FALSE
  )
  save_figure(
    file.path(
      annual_figure_dir,
      "kepco_fuel_technology_monthly_ef_distribution.png"
    ),
    national_monthly_plot,
    width = 13,
    height = 8
  )

  provincial_plot <- plot_fuel_technology_distribution(
    annual_province_fuel_technology_ef,
    estimate_year,
    province_level = TRUE
  )
  save_figure(
    file.path(
      annual_figure_dir,
      "kepco_province_fuel_technology_ef_distribution.png"
    ),
    provincial_plot,
    width = 14,
    height = 12
  )

  provincial_monthly_plot <- plot_fuel_technology_monthly_distribution(
    annual_province_fuel_technology_ef,
    estimate_year,
    province_level = TRUE
  )
  save_figure(
    file.path(
      annual_figure_dir,
      "kepco_province_fuel_technology_monthly_ef_distribution.png"
    ),
    provincial_monthly_plot,
    width = 14,
    height = 12
  )
}

# Example query (change the province as needed):
# estimate_ef(
#   analysis_kepco,
#   pollutant = "nox",
#   filters = list(fuel_type_clean = "coal", plant_province = "Chungcheongnam-do")
# )$estimate

# ---- Continuous negative-exponential EF projections -------------------------

# EF(t) = floor + (initial - floor) * exp(-decay * t), where t is years since
# the first observation. This gives rapid early improvement, followed by ever
# smaller reductions toward a nonnegative long-run floor, with no imposed
# structural break.
fit_exponential_projection <- function(
  series,
  pollutant,
  group_label,
  projection_end = as.Date("2050-12-01"),
  min_months = 24
) {
  series <- series[!is.na(series$ef_kg_per_mwh) & series$ef_kg_per_mwh >= 0, ]
  series <- series[order(series$date), ]
  if (nrow(series) < min_months) return(NULL)

  first_date <- min(series$date)
  series$t_years <- (month_index(series$date) - month_index(first_date)) / 12
  floor_start <- max(0, unname(quantile(series$ef_kg_per_mwh, 0.1)))
  amplitude_start <- max(series$ef_kg_per_mwh) - floor_start
  model_weights <- pmax(series$generation_mwh, 1)
  model_weights <- model_weights / mean(model_weights)

  weighted_sse <- function(parameters) {
    fitted <- parameters[["floor"]] + parameters[["amplitude"]] *
      exp(-parameters[["decay"]] * series$t_years)
    sum(model_weights * (series$ef_kg_per_mwh - fitted)^2)
  }
  starts <- list(
    c(floor = floor_start, amplitude = amplitude_start, decay = 0.03),
    c(floor = floor_start, amplitude = amplitude_start, decay = 0.1),
    c(floor = 0, amplitude = max(series$ef_kg_per_mwh), decay = 0.3)
  )
  fits <- lapply(starts, function(start) try(
    optim(
      start,
      weighted_sse,
      method = "L-BFGS-B",
      lower = c(floor = 0, amplitude = 0, decay = 0.0001),
      upper = c(floor = Inf, amplitude = Inf, decay = 10)
    ),
    silent = TRUE
  ))
  fits <- fits[!vapply(fits, inherits, logical(1), "try-error")]
  if (length(fits) == 0) return(NULL)
  fit <- fits[[which.min(vapply(fits, function(x) x$value, numeric(1)))]]
  if (fit$convergence != 0) return(NULL)

  projection <- data.frame(date = project_month_sequence(first_date, projection_end))
  projection$t_years <- (month_index(projection$date) - month_index(first_date)) / 12
  coefficients <- fit$par
  projection$projected_ef_kg_per_mwh <- coefficients[["floor"]] +
    coefficients[["amplitude"]] * exp(-coefficients[["decay"]] * projection$t_years)
  projection$observed_ef_kg_per_mwh <- series$ef_kg_per_mwh[
    match(projection$date, series$date)
  ]
  projection$pollutant <- pollutant
  projection$group <- group_label

  list(
    model = fit,
    projection = projection,
    summary = data.frame(
      pollutant = pollutant,
      group = group_label,
      first_observed_date = first_date,
      last_observed_date = max(series$date),
      observations = nrow(series),
      initial_ef_kg_per_mwh = unname(
        coefficients[["floor"]] + coefficients[["amplitude"]]
      ),
      floor_ef_kg_per_mwh = unname(coefficients[["floor"]]),
      annual_decay_rate = unname(coefficients[["decay"]]),
      projected_2030_ef_kg_per_mwh = projection$projected_ef_kg_per_mwh[
        which.min(abs(projection$date - as.Date("2030-12-01")))
      ],
      projected_2050_ef_kg_per_mwh = tail(projection$projected_ef_kg_per_mwh, 1),
      row.names = NULL
    )
  )
}

projection_models_dir <- file.path(models_dir, "projections")
if (dir.exists(projection_models_dir)) {
  unlink(projection_models_dir, recursive = TRUE)
  message("Deleted superseded KEPCO projection models: ", projection_models_dir)
}

exponential_projection_summaries <- list()
for (i in seq_len(nrow(pollutants))) {
  pollutant <- pollutants$pollutant[[i]]
  fuel_series <- aggregate_ef(
    analysis_kepco,
    c("fuel_type_clean", "date"),
    pollutant
  )
  if (nrow(fuel_series) == 0) next

  for (fuel in sort(unique(fuel_series$fuel_type_clean))) {
    result <- fit_exponential_projection(
      fuel_series[fuel_series$fuel_type_clean == fuel, ],
      pollutant,
      fuel
    )
    if (is.null(result)) next

    stub <- paste0(clean_filename(fuel), "_", pollutant)
    save_table(result$projection, paste0("projections/kepco_exponential_", stub, ".csv"))
    save_model(
      result$model,
      file.path("projections", paste0("kepco_exponential_", stub, ".rds"))
    )
    exponential_projection_summaries[[length(exponential_projection_summaries) + 1]] <-
      result$summary
  }
}
if (length(exponential_projection_summaries) > 0) {
  exponential_projection_summary <- do.call(rbind, exponential_projection_summaries)
  save_table(
    exponential_projection_summary,
    file.path("projections", "kepco_exponential_projection_summary.csv")
  )
}

# Paused: holding off on EF break/plateau projections for now (2026-06-30).
# Wrapped in `if (FALSE)` rather than deleted so this can be re-enabled
# later without reconstructing it from git history.
if (FALSE) {

fit_break_projection <- function(
  series,
  label,
  group_label,
  output_stub,
  value_col = "ef_kg_per_mwh",
  series_label = "cleaned monthly EF",
  figure_subdir = file.path("kepco", "projections", "cleaned_monthly")
) {
  series <- series[order(series$date), ]
  series$ef_kg_per_mwh <- series[[value_col]]
  series <- series[!is.na(series$ef_kg_per_mwh), ]

  if (nrow(series) < 60) {
    return(NULL)
  }

  first_date <- min(series$date)
  last_date <- max(series$date)
  all_months <- data.frame(date = project_month_sequence(first_date))
  model_data <- merge(all_months, series[, c("date", "ef_kg_per_mwh")], by = "date", all.x = TRUE)
  model_data$observed <- model_data$date <= last_date & !is.na(model_data$ef_kg_per_mwh)
  model_data$t <- month_index(model_data$date) - month_index(first_date)

  break_min <- as.Date("2016-01-01")
  break_max <- as.Date("2022-12-01")
  candidates <- seq(break_min, break_max, by = "month")
  candidates <- candidates[candidates > min(series$date) & candidates < max(series$date)]

  break_results <- data.frame()

  for (break_date in candidates) {
    break_date <- as.Date(break_date, origin = "1970-01-01")
    pre_n <- sum(model_data$observed & model_data$date < break_date)
    post_n <- sum(model_data$observed & model_data$date >= break_date)

    if (pre_n >= 24 && post_n >= 24) {
      observed_rows <- model_data$observed
      t_pre <- ifelse(model_data$date < break_date, model_data$t, 0)
      post <- model_data$date >= break_date

      fit <- try(
        lm(model_data$ef_kg_per_mwh[observed_rows] ~
          t_pre[observed_rows] + post[observed_rows]),
        silent = TRUE
      )

      if (!inherits(fit, "try-error")) {
        rss <- sum(residuals(fit)^2)
        n <- length(residuals(fit))
        k <- length(coef(fit))
        bic <- n * log(rss / n) + k * log(n)
        break_results <- rbind(
          break_results,
          data.frame(
            pollutant = label,
            group = group_label,
            break_date = break_date,
            rss = rss,
            bic = bic
          )
        )
      }
    }
  }

  if (nrow(break_results) == 0) {
    return(NULL)
  }

  best <- break_results[which.min(break_results$bic), ]
  break_date <- as.Date(best$break_date)
  model_data$post <- model_data$date >= break_date
  model_data$t_pre <- ifelse(model_data$date < break_date, model_data$t, 0)

  fit_two_period <- lm(
    ef_kg_per_mwh ~ t_pre + post,
    data = model_data[model_data$observed, ]
  )
  model_data$two_period_hat <- predict(fit_two_period, newdata = model_data)

  post_values <- model_data$ef_kg_per_mwh[model_data$observed & model_data$date >= break_date]
  post_median <- median(post_values, na.rm = TRUE)
  post_p10 <- unname(quantile(post_values, 0.10, na.rm = TRUE))
  model_data$post_median_hat <- ifelse(
    model_data$observed,
    model_data$ef_kg_per_mwh,
    post_median
  )
  model_data$two_period_hat[!model_data$observed &
    model_data$two_period_hat < post_p10] <- post_p10

  chow_fit <- lm(
    ef_kg_per_mwh ~ t * post,
    data = model_data[model_data$observed, ]
  )
  reduced_fit <- lm(
    ef_kg_per_mwh ~ t,
    data = model_data[model_data$observed, ]
  )
  chow_test <- anova(reduced_fit, chow_fit)
  p_value <- chow_test$`Pr(>F)`[2]

  output_path <- save_base_png(
    file.path(
      figure_subdir,
      paste0("kepco_projection_", output_stub, "_", clean_filename(label), "_break_plateau.png")
    )
  )
  plot(
    range(model_data$date),
    range(c(model_data$ef_kg_per_mwh, model_data$two_period_hat, model_data$post_median_hat), na.rm = TRUE),
    type = "n",
    xlab = "Month",
    ylab = paste0(label, " EF, kg/MWh"),
    main = paste0(group_label, " ", label, " EF projection"),
    sub = paste0(
      series_label,
      "; linear before break, nonzero plateau after break; break = ",
      format_month_label(break_date)
    )
  )
  grid(col = "grey88")
  lines(
    model_data$date[model_data$observed],
    model_data$ef_kg_per_mwh[model_data$observed],
    col = "#1E88FF",
    lwd = 1.8
  )
  lines(model_data$date, model_data$two_period_hat, col = "#D81B60", lwd = 2, lty = 2)
  lines(model_data$date, model_data$post_median_hat, col = "#D81B60", lwd = 2, lty = 3)
  abline(v = break_date, lty = 2, lwd = 1.5)
  abline(v = last_date, lty = 3, lwd = 1.5)
  legend(
    "topright",
    legend = c("Observed", "Two-period: linear then flat", "Post-break median plateau"),
    col = c("#1E88FF", "#D81B60", "#D81B60"),
    lty = c(1, 2, 3),
    lwd = c(2, 2, 2),
    bty = "n"
  )
  dev.off()
  message("Saved figure: ", output_path)

  projection_table <- model_data[, c(
    "date", "observed", "ef_kg_per_mwh", "two_period_hat", "post_median_hat"
  )]
  projection_table$pollutant <- label
  projection_table$group <- group_label
  projection_table$break_date <- break_date
  save_table(
    projection_table,
    file.path(
      "projections", "break_plateau",
      paste0("kepco_projection_", output_stub, "_", clean_filename(label), ".csv")
    )
  )

  data.frame(
    pollutant = label,
    group = group_label,
    break_date = break_date,
    break_label = format_month_label(break_date),
    bic = best$bic,
    rss = best$rss,
    post_median_plateau = post_median,
    post_p10_floor = post_p10,
    chow_style_p_value = p_value,
    last_observed_date = last_date,
    last_observed_ef = tail(series$ef_kg_per_mwh[!is.na(series$ef_kg_per_mwh)], 1),
    projected_2050_two_period = tail(model_data$two_period_hat, 1),
    projected_2050_post_median = tail(model_data$post_median_hat, 1),
    series = series_label,
    row.names = NULL
  )
}

projection_summaries <- list()

for (i in seq_len(nrow(pollutants))) {
  all_series <- aggregate_ef(analysis_kepco, "date", pollutants$pollutant[[i]])
  result <- fit_break_projection(
    all_series,
    pollutants$label[[i]],
    "All fuels",
    "all_fuels"
  )
  if (!is.null(result)) {
    projection_summaries[[length(projection_summaries) + 1]] <- result
  }

  result <- fit_break_projection(
    all_series,
    pollutants$label[[i]],
    "All fuels",
    "all_fuels_ma6",
    value_col = "ef_ma_kg_per_mwh",
    series_label = "6-month moving average EF",
    figure_subdir = file.path("kepco", "projections", "ma6")
  )
  if (!is.null(result)) {
    projection_summaries[[length(projection_summaries) + 1]] <- result
  }

  fuel_series <- fuel_time_series[[pollutants$pollutant[[i]]]]
  for (fuel in sort(unique(fuel_series$fuel_type_clean))) {
    result <- fit_break_projection(
      fuel_series[fuel_series$fuel_type_clean == fuel, ],
      pollutants$label[[i]],
      fuel,
      clean_filename(fuel)
    )

    if (!is.null(result)) {
      projection_summaries[[length(projection_summaries) + 1]] <- result
    }

    result <- fit_break_projection(
      fuel_series[fuel_series$fuel_type_clean == fuel, ],
      pollutants$label[[i]],
      paste0(fuel, ", 6-month MA"),
      paste0(clean_filename(fuel), "_ma6"),
      value_col = "ef_ma_kg_per_mwh",
      series_label = "6-month moving average EF",
      figure_subdir = file.path("kepco", "projections", "ma6")
    )

    if (!is.null(result)) {
      projection_summaries[[length(projection_summaries) + 1]] <- result
    }
  }
}

projection_summary <- do.call(rbind, projection_summaries)
save_table(
  projection_summary,
  file.path("projections", "break_plateau", "kepco_break_projection_summary.csv")
)

} # end paused EF projection block

cat("\nFast KEPCO analysis complete.\n")
cat("Summary tables saved under:", tables_dir, "\n")
cat("Figures saved under:", figures_dir, "\n")
