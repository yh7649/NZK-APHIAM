# NZK-APHIAM manual analysis workspace
#
# Open NZK-APHIAM.Rproj, then work through this script interactively.
# Python owns data merging and unit standardization. Run `make combine-thermal`
# before using this file whenever an interim dataset changes.

# ---- Setup -------------------------------------------------------------------

source(file.path("analysis", "R", "paths.R"))

options(
  stringsAsFactors = FALSE,
  scipen = 999
)

combined_csv <- thermal_processed_path("thermal_power_generation_emissions.csv")
metadata_csv <- thermal_processed_path(
  "thermal_power_generation_emissions_metadata.csv"
)

figures_dir <- results_path("figures")
tables_dir <- results_path("tables")
objects_dir <- results_path("objects")
models_dir <- results_path("models")

for (directory in c(figures_dir, tables_dir, objects_dir, models_dir)) {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
}

save_table <- function(data, filename, row.names = FALSE, ...) {
  output_path <- file.path(tables_dir, filename)
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

required_files <- c(combined_csv, metadata_csv)
missing_files <- required_files[!file.exists(required_files)]

if (length(missing_files) > 0) {
  stop(
    "Required processed files are missing:\n",
    paste(missing_files, collapse = "\n"),
    "\nRun `make combine-thermal` first.",
    call. = FALSE
  )
}

thermal <- read.csv(
  combined_csv,
  na.strings = c("", "NA"),
  check.names = FALSE,
  stringsAsFactors = FALSE
)
thermal$date <- as.Date(thermal$date)
thermal$plant_opening_date <- as.Date(thermal$plant_opening_date)
thermal$plant_closing_date <- as.Date(thermal$plant_closing_date)

thermal_metadata <- read.csv(
  metadata_csv,
  check.names = FALSE,
  stringsAsFactors = FALSE
)

if (!identical(thermal_metadata$varname, names(thermal))) {
  stop("Variable metadata does not match the processed dataset.", call. = FALSE)
}

for (i in seq_len(nrow(thermal_metadata))) {
  attr(thermal[[thermal_metadata$varname[[i]]]], "label") <-
    thermal_metadata$label[[i]]
}

if (!all(thermal$observation_frequency == "monthly")) {
  stop("The processed dataset contains non-monthly observations.", call. = FALSE)
}

if (!all(thermal$pollutant_measurement_basis == "mass")) {
  stop("The processed dataset contains non-mass pollutant observations.", call. = FALSE)
}

mass_units <- unique(na.omit(thermal$emissions_mass_unit))
if (!identical(mass_units, "kilograms")) {
  stop("Pollutant mass is not consistently standardized to kilograms.", call. = FALSE)
}


# ---- Analysis variables -------------------------------------------------------

thermal$year <- as.integer(format(thermal$date, "%Y"))
thermal$month <- as.integer(format(thermal$date, "%m"))

thermal$nox_kg_per_mwh <- with(
  thermal,
  ifelse(energy_generated_mwh > 0, nox / energy_generated_mwh, NA_real_)
)
thermal$sox_kg_per_mwh <- with(
  thermal,
  ifelse(energy_generated_mwh > 0, sox / energy_generated_mwh, NA_real_)
)
thermal$dust_tsp_kg_per_mwh <- with(
  thermal,
  ifelse(energy_generated_mwh > 0, dust_tsp / energy_generated_mwh, NA_real_)
)

attr(thermal$year, "label") <- "Observation year"
attr(thermal$month, "label") <- "Observation month number (1-12)"
attr(thermal$nox_kg_per_mwh, "label") <-
  "Nitrogen oxides emission factor (kg/MWh)"
attr(thermal$sox_kg_per_mwh, "label") <-
  "Sulfur oxides emission factor (kg/MWh)"
attr(thermal$dust_tsp_kg_per_mwh, "label") <-
  "Total suspended particulate emission factor (kg/MWh)"


# ---- Workspace overview -------------------------------------------------------

cat("Rows:", format(nrow(thermal), big.mark = ","), "\n")
cat("Date range:", format(min(thermal$date)), "to", format(max(thermal$date)), "\n")
cat("Subsidiaries:", paste(sort(unique(thermal$subsidiary_company)), collapse = ", "), "\n")
cat("Plants:", length(unique(thermal$plant_name)), "\n\n")

coverage_by_dataset <- aggregate(
  date ~ source_dataset,
  data = thermal,
  FUN = function(x) paste(min(x), max(x), sep = " to ")
)
print(coverage_by_dataset)


# ---- Manual analysis starts here ---------------------------------------------

# Useful first checks:
# View(thermal)
# summary(thermal)
# table(thermal$source_dataset, useNA = "ifany")
# table(thermal$energy_type, useNA = "ifany")
#
# Save examples:
# save_table(coverage_by_dataset, "coverage_by_dataset.csv")
# save_analysis_object(thermal, "thermal_analysis_data.rds")
# save_model(your_model, "your_model.rds")
#
# With ggplot2:
# library(ggplot2)
# generation_plot <- ggplot(thermal, aes(date, energy_generated_mwh)) +
#   geom_line(aes(color = subsidiary_company), na.rm = TRUE) +
#   labs(x = NULL, y = "Monthly electricity generation (MWh)")
# save_figure("monthly_generation.png", generation_plot)
