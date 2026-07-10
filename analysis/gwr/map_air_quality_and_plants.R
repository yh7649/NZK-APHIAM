#!/usr/bin/env Rscript
# Descriptive map of monitor concentrations and KEPCO plants; not a dispersion map.
source(file.path("analysis", "R", "paths.R"))
source(project_path("analysis", "gwr", "gwr_helpers.R"))

packages <- c("dplyr", "ggplot2", "ggrepel", "patchwork", "readr", "rnaturalearthdata", "sf", "tidyr")
missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop("Missing R packages: ", paste(missing, collapse = ", "), call. = FALSE)

year_to_map <- as.integer(Sys.getenv("GWR_MAP_YEAR", unset = "2010"))
outcomes_path <- gwr_results_path("tables", "gwr", "plant_air_quality", "monitor_year_outcomes.csv")
plant_path <- kepco_processed_path("kepco_monthly_generation_emissions.csv")
if (!file.exists(outcomes_path)) stop("Run the plant-air-quality analysis first: missing ", outcomes_path, call. = FALSE)
if (!file.exists(plant_path)) stop("Missing processed KEPCO plant data: ", plant_path, call. = FALSE)

outcomes <- readr::read_csv(outcomes_path, show_col_types = FALSE) |>
  dplyr::filter(year == year_to_map, pollutant %in% c("NO2", "SO2", "PM10"))
if (!nrow(outcomes)) stop("No mapped monitor outcomes for ", year_to_map, call. = FALSE)

plants <- readr::read_csv(plant_path, show_col_types = FALSE) |>
  dplyr::mutate(date = as.Date(date), year = as.integer(format(date, "%Y")),
    plant_id = paste(subsidiary_company, plant_name, sep = " | ")) |>
  dplyr::filter(year == year_to_map, row_status != "inactive_placeholder",
    valid_lonlat(plant_longitude, plant_latitude))

fuel_family <- function(x) {
  dplyr::case_when(
    x == "coal" ~ "Coal",
    x == "natural_gas" ~ "Natural gas",
    x %in% c("oil", "oil_and_natural_gas") ~ "Oil / gas",
    x %in% c("biomass", "bio_oil_and_diesel") ~ "Bioenergy",
    TRUE ~ "Other"
  )
}
plants$fuel_family_unit <- fuel_family(plants$fuel_type)
fuel_mix <- plants |>
  dplyr::distinct(plant_id, fuel_family_unit) |>
  dplyr::group_by(plant_id) |>
  dplyr::summarise(fuel_type = if (dplyr::n_distinct(fuel_family_unit) == 1L) dplyr::first(fuel_family_unit) else "Mixed", .groups = "drop")

plant_long <- plants |>
  tidyr::pivot_longer(c(nox, sox, dust_tsp), names_to = "source_pollutant", values_to = "emissions_kg") |>
  dplyr::mutate(emissions_pollutant = dplyr::recode(source_pollutant, dust_tsp = "tsp"),
    audit_excluded = pollutant_audit_excluded(audit_severity, audit_issue_codes, source_pollutant),
    emissions_kg = dplyr::if_else(audit_excluded, NA_real_, emissions_kg)) |>
  dplyr::group_by(plant_id, plant_name, subsidiary_company, plant_latitude, plant_longitude,
    emissions_pollutant, date) |>
  dplyr::summarise(monthly_emissions_kg = if (all(is.na(emissions_kg))) NA_real_ else sum(emissions_kg, na.rm = TRUE), .groups = "drop") |>
  dplyr::group_by(plant_id, plant_name, subsidiary_company, plant_latitude, plant_longitude, emissions_pollutant) |>
  dplyr::summarise(mean_monthly_emissions_kg = if (sum(!is.na(monthly_emissions_kg)) >= 9L) mean(monthly_emissions_kg, na.rm = TRUE) else NA_real_, .groups = "drop") |>
  dplyr::left_join(fuel_mix, by = "plant_id")

plant_sites <- plants |>
  dplyr::group_by(plant_id, plant_name, subsidiary_company) |>
  dplyr::summarise(plant_latitude = dplyr::first(plant_latitude), plant_longitude = dplyr::first(plant_longitude), .groups = "drop") |>
  dplyr::left_join(fuel_mix, by = "plant_id")

world <- sf::st_as_sf(rnaturalearthdata::countries50)
korea <- world |> dplyr::filter(admin %in% c("South Korea", "North Korea"))
south_korea <- korea |> dplyr::filter(admin == "South Korea")

fuel_colors <- c(
  "Coal" = "#2D2D2D", "Natural gas" = "#2F80ED", "Oil / gas" = "#E67E22",
  "Bioenergy" = "#27AE60", "Mixed" = "#9B51E0", "Other" = "#7F8C8D"
)
mapping <- tibble::tribble(
  ~pollutant, ~emissions_pollutant, ~monitor_label, ~plant_label,
  "NO2", "nox", "Annual mean NO2 (ppm)", "Mean monthly NOx (kg)",
  "SO2", "sox", "Annual mean SO2 (ppm)", "Mean monthly SOx (kg)",
  "PM10", "tsp", "Annual mean PM10 (µg/m³)", "Mean monthly TSP (kg)"
)

make_panel <- function(pollutant, emissions_pollutant, monitor_label, plant_label) {
  monitor_data <- dplyr::filter(outcomes, .data$pollutant == .env$pollutant)
  emission_data <- dplyr::filter(plant_long, .data$emissions_pollutant == .env$emissions_pollutant)
  plant_data <- dplyr::left_join(plant_sites, dplyr::select(emission_data, plant_id, mean_monthly_emissions_kg), by = "plant_id") |>
    dplyr::mutate(plot_emissions = tidyr::replace_na(mean_monthly_emissions_kg, 0))
  labels <- plant_data |> dplyr::slice_max(plot_emissions, n = 5, with_ties = FALSE)

  ggplot2::ggplot() +
    ggplot2::geom_sf(data = korea, fill = "#F4F1EA", colour = "#B8B2A7", linewidth = 0.3) +
    ggplot2::geom_sf(data = south_korea, fill = "#ECE8DE", colour = "#67635D", linewidth = 0.55) +
    ggplot2::geom_point(data = monitor_data,
      ggplot2::aes(longitude, latitude, colour = annual_mean_concentration),
      size = 3.2, alpha = 0.88) +
    ggplot2::geom_point(data = plant_data,
      ggplot2::aes(plant_longitude, plant_latitude, fill = fuel_type, size = plot_emissions),
      shape = 24, colour = "white", stroke = 0.65, alpha = 0.95) +
    ggrepel::geom_text_repel(data = labels,
      ggplot2::aes(plant_longitude, plant_latitude, label = plant_name),
      size = 2.6, colour = "#242424", min.segment.length = 0,
      box.padding = 0.25, point.padding = 0.4, max.overlaps = Inf, seed = 7649) +
    ggplot2::scale_colour_viridis_c(option = "magma", direction = -1, name = monitor_label) +
    ggplot2::scale_fill_manual(values = fuel_colors, drop = FALSE, name = "Plant fuel type") +
    ggplot2::scale_size_continuous(trans = "sqrt", range = c(2.8, 8), name = plant_label,
      labels = scales::label_number(big.mark = ",", accuracy = 1)) +
    ggplot2::coord_sf(xlim = c(124.5, 130.9), ylim = c(33.0, 39.6), expand = FALSE) +
    ggplot2::labs(title = paste0(pollutant, " and KEPCO plants"),
      subtitle = paste(year_to_map, "annual monitor mean; triangles are plants"), x = NULL, y = NULL) +
    ggplot2::theme_minimal(base_size = 10) +
    ggplot2::theme(panel.grid.major = ggplot2::element_line(colour = "#D8D5CF", linewidth = 0.25),
      plot.title = ggplot2::element_text(face = "bold"), plot.subtitle = ggplot2::element_text(colour = "#626262"),
      legend.key.height = grid::unit(0.55, "cm"), legend.position = "right")
}

panels <- purrr::pmap(mapping, make_panel)
combined <- patchwork::wrap_plots(panels, nrow = 1) +
  patchwork::plot_annotation(
    title = paste("Korea air quality and KEPCO plant emissions,", year_to_map),
    subtitle = "Descriptive overlay only — plant emissions are not modeled concentrations",
    caption = "Monitor circles: rule-QC annual means. Plant triangles: fuel type and pollutant-specific mean monthly mass.",
    theme = ggplot2::theme(plot.title = ggplot2::element_text(face = "bold", size = 18),
      plot.subtitle = ggplot2::element_text(size = 11, colour = "#555555")))

figure_dir <- gwr_results_path("figures", "gwr", "plant_air_quality")
dir.create(figure_dir, recursive = TRUE, showWarnings = FALSE)
png_path <- file.path(figure_dir, paste0("korea_air_quality_plants_", year_to_map, ".png"))
pdf_path <- file.path(figure_dir, paste0("korea_air_quality_plants_", year_to_map, ".pdf"))
ggplot2::ggsave(png_path, combined, width = 19, height = 8, dpi = 240, bg = "white")
ggplot2::ggsave(pdf_path, combined, width = 19, height = 8, device = grDevices::pdf, bg = "white")
for (i in seq_len(nrow(mapping))) {
  ggplot2::ggsave(file.path(figure_dir, paste0("korea_", tolower(mapping$pollutant[[i]]), "_plants_", year_to_map, ".png")),
    panels[[i]], width = 8, height = 8, dpi = 240, bg = "white")
}
message("Wrote Korea air-quality and plant maps to ", figure_dir)
