# NZK-APHIAM KEPCO subsidiary monthly analysis workspace
#
# Open NZK-APHIAM.Rproj, then work through this script interactively.
# Python owns data cleaning and auditing. Before using this file, run the
# cleaner for the subsidiary you want:
#
#   make clean-<subsidiary>      (e.g. make clean-eastwest-power)
#   make combine-kepco           (re-standardises and re-audits all subsidiaries)
#
# Set the two parameters below, then source this script.

# ---- Parameters (set these before sourcing) ----------------------------------

# Snake-case name matching the processed CSV prefix and results subdirectory.
# One of: eastwest_power | western_power | southern_power |
#         southeast_power | midland_power
subsidiary_name  <- "eastwest_power"

# Human-readable label used in plot titles.
subsidiary_label <- "East-West Power"

# ---- Setup -------------------------------------------------------------------

source(file.path("analysis", "R", "paths.R"))

options(
  stringsAsFactors = FALSE,
  scipen = 999
)

make_target   <- paste0("clean-", gsub("_", "-", subsidiary_name))
subsidiary_csv <- kepco_processed_path(
  "subsidiaries", paste0(subsidiary_name, "_monthly_generation_emissions.csv")
)

figures_dir <- results_path("figures", "kepco_subsidiaries")
tables_dir  <- results_path("tables", subsidiary_name)
objects_dir <- results_path("objects")
models_dir  <- results_path("models")

for (directory in c(figures_dir, tables_dir, objects_dir, models_dir)) {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
}

save_table <- function(data, filename, row.names = FALSE, ...) {
  output_path <- file.path(tables_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  write.csv(data, output_path, row.names = row.names, na = "", ...)
  message("Saved table: ", output_path)
  invisible(output_path)
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
  saveRDS(model, output_path)
  message("Saved model: ", output_path)
  invisible(output_path)
}


# ---- Load and validate --------------------------------------------------------

if (!file.exists(subsidiary_csv)) {
  stop(
    "Required processed file is missing:\n",
    subsidiary_csv,
    "\nRun `make ", make_target, "` first.",
    call. = FALSE
  )
}

sub_data <- read.csv(
  subsidiary_csv,
  na.strings = c("", "NA"),
  check.names = FALSE,
  stringsAsFactors = FALSE
)
sub_data$date              <- as.Date(sub_data$date)
sub_data$plant_opening_date <- as.Date(sub_data$plant_opening_date)
sub_data$plant_closing_date <- as.Date(sub_data$plant_closing_date)

if (!all(sub_data$observation_frequency == "monthly")) {
  stop("The processed dataset contains non-monthly observations.", call. = FALSE)
}

if (!all(sub_data$pollutant_measurement_basis == "mass")) {
  stop("The processed dataset contains non-mass pollutant observations.", call. = FALSE)
}

mass_units <- unique(na.omit(sub_data$emissions_mass_unit))
if (!identical(mass_units, "kilograms")) {
  stop("Pollutant mass is not consistently standardized to kilograms.", call. = FALSE)
}


# ---- Analysis variables -------------------------------------------------------

sub_data$year  <- as.integer(format(sub_data$date, "%Y"))
sub_data$month <- as.integer(format(sub_data$date, "%m"))

sub_data$nox_kg_per_mwh <- with(
  sub_data,
  ifelse(energy_generated_mwh > 0, nox / energy_generated_mwh, NA_real_)
)
sub_data$sox_kg_per_mwh <- with(
  sub_data,
  ifelse(energy_generated_mwh > 0, sox / energy_generated_mwh, NA_real_)
)
sub_data$dust_tsp_kg_per_mwh <- with(
  sub_data,
  ifelse(energy_generated_mwh > 0, dust_tsp / energy_generated_mwh, NA_real_)
)


# ---- Workspace overview -------------------------------------------------------

cat("Subsidiary:", subsidiary_label, "\n")
cat("Rows:", format(nrow(sub_data), big.mark = ","), "\n")
cat("Date range:", format(min(sub_data$date)), "to", format(max(sub_data$date)), "\n")
cat("Plants:", length(unique(sub_data$plant_name)), "\n\n")

coverage_by_dataset <- aggregate(
  date ~ source_dataset,
  data = sub_data,
  FUN = function(x) paste(min(x), max(x), sep = " to ")
)
print(coverage_by_dataset)


# ---- Manual analysis starts here ---------------------------------------------

# Useful first checks:
# View(sub_data)
# summary(sub_data)
# table(sub_data$source_dataset, useNA = "ifany")
# table(sub_data$fuel_type, useNA = "ifany")
#
# Save examples:
# save_table(coverage_by_dataset, "coverage_by_dataset.csv")
# save_analysis_object(sub_data, paste0(subsidiary_name, "_analysis_data.rds"))
# save_model(your_model, "your_model.rds")
#
# With ggplot2:
# library(ggplot2)
# generation_plot <- ggplot(sub_data, aes(date, energy_generated_mwh)) +
#   geom_line(aes(color = plant_name), na.rm = TRUE) +
#   labs(x = NULL, y = "Monthly electricity generation (MWh)")
# save_figure("monthly_generation.png", generation_plot)


# ---- Fast EF diagnostics and projections -------------------------------------

# Steps:
#   1. pollutant EF = kg emissions / MWh generation
#   2. exclude flagged rows using the Python auditor's audit_severity/
#      audit_issue_codes columns (warning- and critical-tier codes only)
#   3. suppress fuel-type/plant aggregates where surviving generation falls
#      below min_coverage_pct of the full fleet for that group-month
#   4. aggregate EF as total valid emissions / total valid generation
#   5. select a structural break by BIC over candidate monthly breaks
#   6. project with a pre-break line and a post-break nonzero plateau

required_r_packages <- c("ggplot2", "dplyr", "tidyr", "readr", "lubridate", "scales", "broom")
missing_r_packages  <- required_r_packages[
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
  ef        = c("sox_kg_per_mwh", "nox_kg_per_mwh", "dust_tsp_kg_per_mwh"),
  label     = c("SOx", "NOx", "TSP"),
  stringsAsFactors = FALSE
)

analysis_sub <- sub_data
analysis_sub$fuel_type_clean <- ifelse(
  is.na(analysis_sub$fuel_type) | analysis_sub$fuel_type == "",
  "unknown",
  analysis_sub$fuel_type
)

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

# Pollutant values are excluded from analysis using the Python auditor's own
# audit_severity/audit_issue_codes (src/nzk_aphiam/data/audit/thermal/auditor.py),
# not a second, independently computed IQR check. Recomputing the same kind of
# threshold here in R would duplicate logic that already lives in the audited
# subsidiary file and could silently drift from it.
#
# A row is excluded for a given pollutant only when one of that pollutant's
# own warning-or-critical-tier issue codes is present -- not merely because
# the row's overall audit_severity (the worst flag across *any* pollutant) is
# elevated. review-tier flags (e.g. high_X_mass) are left in place; only the
# higher-confidence codes below are excluded:
#   - high_<pollutant>_emission_factor (warning)
#   - recent_shift_high_<pollutant>_mass / recent_shift_low_<pollutant>_mass (warning)
#   - zero_nox_with_generation / zero_sox_coal_generation / zero_dust_tsp_coal_generation (warning)
audit_exclusion_pattern <- function(pollutant) {
  paste0(
    "high_", pollutant, "_emission_factor",
    "|recent_shift_(high|low)_", pollutant, "_mass",
    "|zero_", pollutant, "_(with_generation|coal_generation)"
  )
}

outlier_log <- data.frame()

for (i in seq_len(nrow(pollutants))) {
  ef_var     <- pollutants$ef[[i]]
  outlier_var <- paste0("high_outlier_", pollutants$pollutant[[i]])

  issue_codes <- ifelse(
    is.na(analysis_sub$audit_issue_codes), "", analysis_sub$audit_issue_codes
  )
  analysis_sub[[outlier_var]] <- analysis_sub$audit_severity %in% c("critical", "warning") &
    grepl(audit_exclusion_pattern(pollutants$pollutant[[i]]), issue_codes)

  flagged <- analysis_sub[analysis_sub[[outlier_var]], c(
    "source_dataset", "date", "plant_name", "plant_number", "fuel_type_clean",
    "energy_generated_mwh", pollutants$pollutant[[i]], ef_var,
    "audit_severity", "audit_issue_codes"
  )]

  if (nrow(flagged) > 0) {
    names(flagged)[names(flagged) == pollutants$pollutant[[i]]] <- "emissions_kg"
    names(flagged)[names(flagged) == ef_var]                    <- "ef_kg_per_mwh"
    flagged$pollutant <- pollutants$label[[i]]
    outlier_log <- rbind(outlier_log, flagged)
  }

  analysis_sub[[pollutants$pollutant[[i]]]][analysis_sub[[outlier_var]]] <- NA_real_
  analysis_sub[[ef_var]][analysis_sub[[outlier_var]]]                    <- NA_real_
}

save_table(outlier_log, paste0(subsidiary_name, "_audit_excluded.csv"))

summarize_vector <- function(x) {
  x <- x[!is.na(x)]
  if (length(x) == 0) {
    return(c(
      n = 0, mean = NA, sd = NA, min = NA, p25 = NA,
      median = NA, p75 = NA, max = NA
    ))
  }

  c(
    n      = length(x),
    mean   = mean(x),
    sd     = ifelse(length(x) > 1, sd(x), NA_real_),
    min    = min(x),
    p25    = unname(quantile(x, 0.25)),
    median = median(x),
    p75    = unname(quantile(x, 0.75)),
    max    = max(x)
  )
}

summary_rows <- list()
for (fuel_type in sort(unique(analysis_sub$fuel_type_clean))) {
  rows <- analysis_sub$fuel_type_clean == fuel_type

  for (i in seq_len(nrow(pollutants))) {
    stats      <- summarize_vector(analysis_sub[[pollutants$ef[[i]]]][rows])
    gen_valid  <- analysis_sub$energy_generated_mwh[
      rows &
        !is.na(analysis_sub[[pollutants$pollutant[[i]]]]) &
        analysis_sub$energy_generated_mwh > 0
    ]
    emissions_valid <- analysis_sub[[pollutants$pollutant[[i]]]][
      rows &
        !is.na(analysis_sub[[pollutants$pollutant[[i]]]]) &
        analysis_sub$energy_generated_mwh > 0
    ]

    summary_rows[[length(summary_rows) + 1]] <- data.frame(
      fuel_type = fuel_type,
      pollutant   = pollutants$label[[i]],
      t(stats),
      total_generation_mwh  = sum(gen_valid, na.rm = TRUE),
      total_emissions_kg    = sum(emissions_valid, na.rm = TRUE),
      aggregate_ef_kg_per_mwh = sum(emissions_valid, na.rm = TRUE) /
        sum(gen_valid, na.rm = TRUE),
      row.names   = NULL,
      check.names = FALSE
    )
  }
}

summary_by_fuel <- do.call(rbind, summary_rows)
save_table(summary_by_fuel, paste0(subsidiary_name, "_pollutant_summary_by_fuel.csv"))

coverage_by_plant_fuel <- aggregate(
  date ~ plant_name + fuel_type_clean,
  data = analysis_sub[
    !is.na(analysis_sub$nox_kg_per_mwh) |
      !is.na(analysis_sub$sox_kg_per_mwh) |
      !is.na(analysis_sub$dust_tsp_kg_per_mwh),
  ],
  FUN = function(x) paste(min(x), max(x), sep = " to ")
)
save_table(coverage_by_plant_fuel, paste0(subsidiary_name, "_ef_coverage_by_plant_fuel.csv"))

aggregate_ef <- function(data, group_vars, pollutant, min_coverage_pct = 0.5) {
  keep <- !is.na(data[[pollutant]]) &
    !is.na(data$energy_generated_mwh) &
    data$energy_generated_mwh > 0
  x <- data[keep, c(group_vars, pollutant, "energy_generated_mwh")]

  if (nrow(x) == 0) {
    return(data.frame())
  }

  emissions  <- aggregate(x[[pollutant]], x[group_vars], sum, na.rm = TRUE)
  generation <- aggregate(x$energy_generated_mwh, x[group_vars], sum, na.rm = TRUE)
  names(emissions)[ncol(emissions)]   <- "emissions_kg"
  names(generation)[ncol(generation)] <- "generation_mwh"

  # Compare surviving (non-excluded) generation to full-fleet generation for
  # the same group-date. When the audit filter removes most of a fuel type's
  # or plant's high-output units, the aggregate EF is no longer representative
  # of the fleet; drop such months rather than let a biased, tiny-sample
  # average pollute the trend line.
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
    analysis_sub,
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
    n          = plant_stats$ef_kg_per_mwh[, "n"],
    max        = plant_stats$ef_kg_per_mwh[, "max"],
    sd         = plant_stats$ef_kg_per_mwh[, "sd"]
  )
  plant_stats <- plant_stats[
    plant_stats$n >= 24 &
      !is.na(plant_stats$sd) &
      plant_stats$sd > 0 &
      plant_stats$max > 0,
  ]
  plant_stats    <- plant_stats[order(-plant_stats$n, plant_stats$plant_name), ]
  selected_plants <- plant_stats$plant_name[seq_len(min(6, nrow(plant_stats)))]

  if (length(selected_plants) == 0) {
    next
  }

  plot_data <- plot_data[plot_data$plant_name %in% selected_plants, ]

  output_path <- save_base_png(
    file.path(
      subsidiary_name,
      "selected_plants",
      "ma6",
      paste0(subsidiary_name, "_selected_plants_", pollutants$pollutant[[i]], "_ef_ma6.png")
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
        lwd  = 0.9,
        col  = adjustcolor("#1F77B4", alpha.f = 0.28),
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
    outer    = TRUE,
    cex.main = 1.25
  )
  par(old_par)
  dev.off()
  message("Saved figure: ", output_path)

  output_path <- save_base_png(
    file.path(
      subsidiary_name,
      "selected_plants",
      "raw",
      paste0(subsidiary_name, "_selected_plants_", pollutants$pollutant[[i]], "_ef_raw.png")
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
        lwd  = 1.4,
        col  = "#1F77B4",
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
    outer    = TRUE,
    cex.main = 1.25
  )
  par(old_par)
  dev.off()
  message("Saved figure: ", output_path)
}

generation_by_fuel <- aggregate(
  energy_generated_mwh ~ fuel_type_clean + date,
  data    = analysis_sub[!is.na(analysis_sub$energy_generated_mwh), ],
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
save_table(generation_by_fuel, paste0(subsidiary_name, "_fuel_type_monthly_generation_mwh.csv"))

if (nrow(generation_by_fuel) > 0) {
  output_path <- save_base_png(
    file.path(
      subsidiary_name,
      "fuel_type_averages",
      "raw",
      paste0(subsidiary_name, "_fuel_type_generation_mwh.png")
    )
  )
  fuels       <- sort(unique(generation_by_fuel$fuel_type_clean))
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
    main = paste0(subsidiary_label, ": monthly generation by fuel type, 6-month moving average")
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
    col    = fuel_colors,
    lty    = 1,
    lwd    = 2,
    bty    = "n",
    cex    = 0.82
  )
  dev.off()
  message("Saved figure: ", output_path)
}

fuel_time_series <- list()
for (i in seq_len(nrow(pollutants))) {
  plot_data <- aggregate_ef(
    analysis_sub,
    c("fuel_type_clean", "date"),
    pollutants$pollutant[[i]]
  )
  fuel_time_series[[pollutants$pollutant[[i]]]] <- plot_data
  save_table(
    plot_data,
    paste0(subsidiary_name, "_fuel_type_monthly_", pollutants$pollutant[[i]], "_ef.csv")
  )

  if (nrow(plot_data) == 0) {
    next
  }

  output_path <- save_base_png(
    file.path(
      subsidiary_name,
      "fuel_type_averages",
      "ma6",
      paste0(subsidiary_name, "_fuel_type_average_", pollutants$pollutant[[i]], "_ef_ma6.png")
    )
  )
  fuels       <- sort(unique(plot_data$fuel_type_clean))
  fuel_colors <- rep(line_colors, length.out = length(fuels))
  y_range <- range(plot_data$ef_kg_per_mwh, na.rm = TRUE)
  plot(
    range(plot_data$date, na.rm = TRUE),
    y_range,
    type = "n",
    xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " EF, kg/MWh"),
    main = paste0(
      subsidiary_label, ": average monthly ", pollutants$label[[i]],
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
    col    = fuel_colors,
    lty    = 1,
    lwd    = 2,
    bty    = "n",
    cex    = 0.82
  )
  dev.off()
  message("Saved figure: ", output_path)

  output_path <- save_base_png(
    file.path(
      subsidiary_name,
      "fuel_type_averages",
      "raw",
      paste0(subsidiary_name, "_fuel_type_average_", pollutants$pollutant[[i]], "_ef_raw.png")
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
      subsidiary_label, ": average monthly ", pollutants$label[[i]],
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
    col    = fuel_colors,
    lty    = 1,
    lwd    = 2,
    bty    = "n",
    cex    = 0.82
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
    paste0(subsidiary_name, "_fuel_type_monthly_", pollutants$pollutant[[i]], "_emissions_kg.csv")
  )

  output_path <- save_base_png(
    file.path(
      subsidiary_name,
      "fuel_type_averages",
      "raw",
      paste0(subsidiary_name, "_fuel_type_", pollutants$pollutant[[i]], "_emissions_kg.png")
    )
  )
  y_range <- range(c(mass_data$emissions_kg, mass_data$emissions_kg_ma6), na.rm = TRUE)
  plot(
    range(mass_data$date, na.rm = TRUE),
    y_range,
    type = "n",
    xlab = "Month",
    ylab = paste0(pollutants$label[[i]], " emissions, kg"),
    main = paste0(
      subsidiary_label, ": monthly ", pollutants$label[[i]],
      " mass emissions by fuel type, 6-month moving average"
    )
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
    col    = fuel_colors,
    lty    = 1,
    lwd    = 2,
    bty    = "n",
    cex    = 0.82
  )
  dev.off()
  message("Saved figure: ", output_path)
}

# Paused: holding off on EF break/plateau projections until the full merged
# dataset is ready. Wrapped in `if (FALSE)` so this can be re-enabled without
# reconstructing it from git history.
if (FALSE) {

fit_break_projection <- function(
    series,
    label,
    group_label,
    output_stub,
    value_col    = "ef_kg_per_mwh",
    series_label = "cleaned monthly EF",
    figure_subdir = file.path(subsidiary_name, "projections", "cleaned_monthly")
) {
  series <- series[order(series$date), ]
  series$ef_kg_per_mwh <- series[[value_col]]
  series <- series[!is.na(series$ef_kg_per_mwh), ]

  if (nrow(series) < 60) {
    return(NULL)
  }

  first_date <- min(series$date)
  last_date  <- max(series$date)
  all_months <- data.frame(date = project_month_sequence(first_date))
  model_data <- merge(all_months, series[, c("date", "ef_kg_per_mwh")], by = "date", all.x = TRUE)
  model_data$observed <- model_data$date <= last_date & !is.na(model_data$ef_kg_per_mwh)
  model_data$t        <- month_index(model_data$date) - month_index(first_date)

  break_min  <- as.Date("2016-01-01")
  break_max  <- as.Date("2022-12-01")
  candidates <- seq(break_min, break_max, by = "month")
  candidates <- candidates[candidates > min(series$date) & candidates < max(series$date)]

  break_results <- data.frame()

  for (break_date in candidates) {
    break_date <- as.Date(break_date, origin = "1970-01-01")
    pre_n  <- sum(model_data$observed & model_data$date < break_date)
    post_n <- sum(model_data$observed & model_data$date >= break_date)

    if (pre_n >= 24 && post_n >= 24) {
      observed_rows <- model_data$observed
      t_pre <- ifelse(model_data$date < break_date, model_data$t, 0)
      post  <- model_data$date >= break_date

      fit <- try(
        lm(model_data$ef_kg_per_mwh[observed_rows] ~
             t_pre[observed_rows] + post[observed_rows]),
        silent = TRUE
      )

      if (!inherits(fit, "try-error")) {
        rss <- sum(residuals(fit)^2)
        n   <- length(residuals(fit))
        k   <- length(coef(fit))
        bic <- n * log(rss / n) + k * log(n)
        break_results <- rbind(
          break_results,
          data.frame(
            pollutant  = label,
            group      = group_label,
            break_date = break_date,
            rss        = rss,
            bic        = bic
          )
        )
      }
    }
  }

  if (nrow(break_results) == 0) {
    return(NULL)
  }

  best       <- break_results[which.min(break_results$bic), ]
  break_date <- as.Date(best$break_date)
  model_data$post  <- model_data$date >= break_date
  model_data$t_pre <- ifelse(model_data$date < break_date, model_data$t, 0)

  fit_two_period <- lm(
    ef_kg_per_mwh ~ t_pre + post,
    data = model_data[model_data$observed, ]
  )
  model_data$two_period_hat <- predict(fit_two_period, newdata = model_data)

  post_values       <- model_data$ef_kg_per_mwh[model_data$observed & model_data$date >= break_date]
  post_median       <- median(post_values, na.rm = TRUE)
  post_p10          <- unname(quantile(post_values, 0.10, na.rm = TRUE))
  model_data$post_median_hat <- ifelse(
    model_data$observed,
    model_data$ef_kg_per_mwh,
    post_median
  )
  model_data$two_period_hat[
    !model_data$observed & model_data$two_period_hat < post_p10
  ] <- post_p10

  chow_fit    <- lm(ef_kg_per_mwh ~ t * post, data = model_data[model_data$observed, ])
  reduced_fit <- lm(ef_kg_per_mwh ~ t,         data = model_data[model_data$observed, ])
  chow_test   <- anova(reduced_fit, chow_fit)
  p_value     <- chow_test$`Pr(>F)`[2]

  output_path <- save_base_png(
    file.path(
      figure_subdir,
      paste0(subsidiary_name, "_projection_", output_stub, "_", clean_filename(label), "_break_plateau.png")
    )
  )
  plot(
    range(model_data$date),
    range(c(model_data$ef_kg_per_mwh, model_data$two_period_hat, model_data$post_median_hat), na.rm = TRUE),
    type = "n",
    xlab = "Month",
    ylab = paste0(label, " EF, kg/MWh"),
    main = paste0(subsidiary_label, " — ", group_label, " ", label, " EF projection"),
    sub  = paste0(
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
  lines(model_data$date, model_data$two_period_hat,   col = "#D81B60", lwd = 2, lty = 2)
  lines(model_data$date, model_data$post_median_hat,  col = "#D81B60", lwd = 2, lty = 3)
  abline(v = break_date, lty = 2, lwd = 1.5)
  abline(v = last_date,  lty = 3, lwd = 1.5)
  legend(
    "topright",
    legend = c("Observed", "Two-period: linear then flat", "Post-break median plateau"),
    col    = c("#1E88FF", "#D81B60", "#D81B60"),
    lty    = c(1, 2, 3),
    lwd    = c(2, 2, 2),
    bty    = "n"
  )
  dev.off()
  message("Saved figure: ", output_path)

  projection_table <- model_data[, c(
    "date", "observed", "ef_kg_per_mwh", "two_period_hat", "post_median_hat"
  )]
  projection_table$pollutant  <- label
  projection_table$group      <- group_label
  projection_table$break_date <- break_date
  save_table(
    projection_table,
    paste0(subsidiary_name, "_projection_", output_stub, "_", clean_filename(label), ".csv")
  )

  data.frame(
    pollutant               = label,
    group                   = group_label,
    break_date              = break_date,
    break_label             = format_month_label(break_date),
    bic                     = best$bic,
    rss                     = best$rss,
    post_median_plateau     = post_median,
    post_p10_floor          = post_p10,
    chow_style_p_value      = p_value,
    last_observed_date      = last_date,
    last_observed_ef        = tail(series$ef_kg_per_mwh[!is.na(series$ef_kg_per_mwh)], 1),
    projected_2050_two_period  = tail(model_data$two_period_hat, 1),
    projected_2050_post_median = tail(model_data$post_median_hat, 1),
    series                  = series_label,
    row.names               = NULL
  )
}

projection_summaries <- list()

for (i in seq_len(nrow(pollutants))) {
  all_series <- aggregate_ef(analysis_sub, "date", pollutants$pollutant[[i]])
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
    value_col    = "ef_ma_kg_per_mwh",
    series_label = "6-month moving average EF",
    figure_subdir = file.path(subsidiary_name, "projections", "ma6")
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
      value_col    = "ef_ma_kg_per_mwh",
      series_label = "6-month moving average EF",
      figure_subdir = file.path(subsidiary_name, "projections", "ma6")
    )

    if (!is.null(result)) {
      projection_summaries[[length(projection_summaries) + 1]] <- result
    }
  }
}

projection_summary <- do.call(rbind, projection_summaries)
save_table(projection_summary, paste0(subsidiary_name, "_break_projection_summary.csv"))

} # end paused EF projection block

cat("\n", subsidiary_label, " analysis complete.\n", sep = "")
cat("Summary tables saved under:", tables_dir, "\n")
cat("Figures saved under:", figures_dir, "\n")
