# NZK-APHIAM annual plant generation-emissions analysis
#
# Status: archived. The monthly KEPCO thermal panel is the preferred dataset
# for near-term analysis. This script is retained for reference.
#
# This script mirrors the monthly KEPCO analysis, but for the annual plant
# panel. It does not remove outliers or smooth the data.

# ---- Setup -------------------------------------------------------------------

source(file.path("analysis", "R", "paths.R"))

options(
  stringsAsFactors = FALSE,
  scipen = 999
)

required_r_packages <- c("ggplot2", "dplyr", "tidyr", "readr", "scales", "broom")
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
  library(scales)
  library(broom)
})

annual_csv <- data_path(
  "power_generation",
  "annual_plant",
  "annual_plant_generation_emissions.csv"
)

figures_dir <- results_path("figures", "annual_plant_archive")
tables_dir <- results_path("tables", "annual_plant_archive")
objects_dir <- results_path("objects", "annual_plant_archive")
models_dir <- results_path("models", "annual_plant_archive")

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
  plot,
  width = 9,
  height = 5.4,
  units = "in",
  dpi = 300,
  ...
) {
  output_path <- file.path(figures_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  ggplot2::ggsave(
    filename = output_path,
    plot = plot,
    width = width,
    height = height,
    units = units,
    dpi = dpi,
    ...
  )
  message("Saved figure: ", output_path)
  invisible(output_path)
}

save_model <- function(model, filename) {
  output_path <- file.path(models_dir, filename)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  saveRDS(model, output_path)
  message("Saved model: ", output_path)
  invisible(output_path)
}

clean_filename <- function(x) {
  out <- gsub("[^A-Za-z0-9]+", "_", tolower(x))
  out <- gsub("^_+|_+$", "", out)
  ifelse(nzchar(out), out, "unknown")
}

english_fuel_label <- function(x) {
  replacements <- c(
    "바이오중유" = "Bio heavy oil",
    "역청탄" = "Bituminous coal",
    "유연탄" = "Bituminous coal",
    "무연탄" = "Anthracite",
    "일반수력" = "Hydro",
    "소수력" = "Small hydro",
    "원자력" = "Nuclear",
    "양수" = "Pumped hydro",
    "가스" = "Gas",
    "경유" = "Diesel",
    "중유" = "Heavy oil",
    "석탄" = "Coal",
    "유류" = "Oil",
    "기타" = "Other",
    "바이오" = "Bio"
  )

  out <- x
  for (pattern in names(replacements)) {
    out <- gsub(pattern, replacements[[pattern]], out, fixed = TRUE)
  }
  out
}

pollutants <- tibble::tibble(
  pollutant = c("sox", "nox", "tsp"),
  mass_col = c("sox_kg", "nox_kg", "tsp_kg"),
  ef_col = c("sox_kg_per_mwh", "nox_kg_per_mwh", "tsp_kg_per_mwh"),
  label = c("SOx", "NOx", "TSP")
)

plot_theme <- theme_minimal(base_size = 13) +
  theme(
    plot.title = element_text(face = "bold"),
    panel.grid.minor = element_blank(),
    legend.position = "right"
  )

safe_quantile <- function(x, p) {
  if (all(is.na(x))) {
    return(NA_real_)
  }

  unname(quantile(x, p, na.rm = TRUE))
}


# ---- Load --------------------------------------------------------------------

if (!file.exists(annual_csv)) {
  stop("Missing annual plant panel: ", annual_csv, call. = FALSE)
}

annual <- readr::read_csv(
  annual_csv,
  na = c("", "NA"),
  show_col_types = FALSE
) %>%
  mutate(
    year = as.integer(year),
    fuel_clean = if_else(is.na(fuel) | fuel == "", "unknown", fuel),
    fuel_label = english_fuel_label(fuel_clean),
    company_clean = if_else(is.na(company) | company == "", "unknown", company),
    operator_category = if_else(
      is.na(operator_category) | operator_category == "",
      "unknown",
      operator_category
    ),
    review_required = as.character(review_required)
  )

non_combustion_fuels <- c("원자력", "양수", "일반수력", "소수력")
annual_analysis <- annual %>%
  filter(!fuel_clean %in% non_combustion_fuels)

cat("Rows:", format(nrow(annual), big.mark = ","), "\n")
cat("Year range:", min(annual$year, na.rm = TRUE), "to", max(annual$year, na.rm = TRUE), "\n")
cat("Plants:", n_distinct(annual$plant_id), "\n")
cat("Fuels:", paste(sort(unique(annual$fuel_clean)), collapse = ", "), "\n\n")
cat("Analysis sample rows after excluding non-combustion fuels:", format(nrow(annual_analysis), big.mark = ","), "\n")
cat("Analysis fuels:", paste(sort(unique(annual_analysis$fuel_label)), collapse = ", "), "\n\n")


# ---- Summary Tables ----------------------------------------------------------

coverage_by_year <- annual %>%
  group_by(year) %>%
  summarise(
    rows = n(),
    plants = n_distinct(plant_id),
    plants_with_generation = n_distinct(plant_id[!is.na(generation_mwh)]),
    plants_with_any_ef = n_distinct(
      plant_id[!is.na(nox_kg_per_mwh) | !is.na(sox_kg_per_mwh) | !is.na(tsp_kg_per_mwh)]
    ),
    total_generation_mwh = sum(generation_mwh, na.rm = TRUE),
    .groups = "drop"
  )
save_table(coverage_by_year, "coverage_by_year.csv")

analysis_sample_by_year <- annual_analysis %>%
  group_by(year) %>%
  summarise(
    rows = n(),
    plants = n_distinct(plant_id),
    plants_with_generation = n_distinct(plant_id[!is.na(generation_mwh)]),
    plants_with_any_ef = n_distinct(
      plant_id[!is.na(nox_kg_per_mwh) | !is.na(sox_kg_per_mwh) | !is.na(tsp_kg_per_mwh)]
    ),
    total_generation_mwh = sum(generation_mwh, na.rm = TRUE),
    .groups = "drop"
  )
save_table(analysis_sample_by_year, "analysis_sample_coverage_by_year.csv")

annual_long <- bind_rows(lapply(seq_len(nrow(pollutants)), function(i) {
  pollutant_row <- pollutants[i, ]
  annual_analysis %>%
    transmute(
      year,
      plant_id,
      plant,
      fuel_clean,
      fuel_label,
      operator_category,
      generation_mwh,
      pollutant = pollutant_row$label,
      emissions_kg = .data[[pollutant_row$mass_col]],
      ef_kg_per_mwh = .data[[pollutant_row$ef_col]]
    )
}))

summary_by_fuel <- annual_long %>%
  group_by(fuel_clean, fuel_label, pollutant) %>%
  summarise(
    plant_years = n(),
    ef_n = sum(!is.na(ef_kg_per_mwh)),
    mean = mean(ef_kg_per_mwh, na.rm = TRUE),
    sd = sd(ef_kg_per_mwh, na.rm = TRUE),
    min = if (all(is.na(ef_kg_per_mwh))) NA_real_ else min(ef_kg_per_mwh, na.rm = TRUE),
    p25 = safe_quantile(ef_kg_per_mwh, 0.25),
    median = median(ef_kg_per_mwh, na.rm = TRUE),
    p75 = safe_quantile(ef_kg_per_mwh, 0.75),
    max = if (all(is.na(ef_kg_per_mwh))) NA_real_ else max(ef_kg_per_mwh, na.rm = TRUE),
    total_generation_mwh = sum(generation_mwh[!is.na(emissions_kg)], na.rm = TRUE),
    total_emissions_kg = sum(emissions_kg, na.rm = TRUE),
    aggregate_ef_kg_per_mwh = total_emissions_kg / total_generation_mwh,
    .groups = "drop"
  ) %>%
  mutate(across(c(mean, sd, min, p25, median, p75, max, aggregate_ef_kg_per_mwh), ~ ifelse(is.nan(.x) | is.infinite(.x), NA_real_, .x))) %>%
  select(
    fuel = fuel_clean,
    fuel_label,
    pollutant,
    plant_years,
    ef_n,
    mean,
    sd,
    min,
    p25,
    median,
    p75,
    max,
    total_generation_mwh,
    total_emissions_kg,
    aggregate_ef_kg_per_mwh
  )
save_table(summary_by_fuel, "annual_pollutant_summary_by_fuel.csv")

summary_by_operator <- annual_analysis %>%
  group_by(operator_category) %>%
  summarise(
    rows = n(),
    plants = n_distinct(plant_id),
    total_generation_mwh = sum(generation_mwh, na.rm = TRUE),
    review_required_rows = sum(tolower(review_required) == "true", na.rm = TRUE),
    .groups = "drop"
  )
save_table(summary_by_operator, "annual_summary_by_operator_category.csv")


# ---- Aggregation Helpers -----------------------------------------------------

aggregate_annual_ef <- function(data, group_vars, pollutant_row) {
  mass_col <- pollutant_row$mass_col[[1]]

  data %>%
    filter(!is.na(.data[[mass_col]]), !is.na(generation_mwh), generation_mwh > 0) %>%
    group_by(across(all_of(group_vars))) %>%
    summarise(
      emissions_kg = sum(.data[[mass_col]], na.rm = TRUE),
      generation_mwh = sum(generation_mwh, na.rm = TRUE),
      ef_kg_per_mwh = emissions_kg / generation_mwh,
      plants = n_distinct(plant_id),
      .groups = "drop"
    ) %>%
    arrange(year)
}


# ---- Selected Plant Time Series ---------------------------------------------

for (i in seq_len(nrow(pollutants))) {
  pollutant_row <- pollutants[i, ]
  plant_series <- aggregate_annual_ef(
    annual_analysis,
    c("plant", "plant_id", "year"),
    pollutant_row
  )

  selected_plants <- plant_series %>%
    group_by(plant, plant_id) %>%
    summarise(
      years = n(),
      generation_mwh = sum(generation_mwh, na.rm = TRUE),
      sd_ef = sd(ef_kg_per_mwh, na.rm = TRUE),
      max_ef = max(ef_kg_per_mwh, na.rm = TRUE),
      .groups = "drop"
    ) %>%
    filter(years >= 5, !is.na(sd_ef), sd_ef > 0, max_ef > 0) %>%
    arrange(desc(generation_mwh)) %>%
    slice_head(n = 6) %>%
    mutate(plant_label = paste0("Plant ", row_number()))

  if (nrow(selected_plants) == 0) {
    next
  }

  save_table(
    selected_plants %>%
      mutate(pollutant = pollutant_row$label) %>%
      select(pollutant, plant_label, plant, plant_id, years, generation_mwh, max_ef),
    file.path(
      "selected_plants",
      paste0("annual_selected_plants_", pollutant_row$pollutant, "_mapping.csv")
    )
  )

  plot_data <- plant_series %>%
    inner_join(selected_plants %>% select(plant, plant_id, plant_label), by = c("plant", "plant_id"))

  p <- ggplot(plot_data, aes(year, ef_kg_per_mwh, group = plant_id)) +
    geom_line(color = "#1F77B4", linewidth = 0.8) +
    geom_point(color = "#1F77B4", size = 1.7) +
    facet_wrap(vars(plant_label), scales = "free_y", ncol = 3) +
    scale_x_continuous(breaks = pretty_breaks()) +
    labs(
      title = paste("Annual", pollutant_row$label, "emission factors: selected plants"),
      x = NULL,
      y = paste0(pollutant_row$label, " EF, kg/MWh")
    ) +
    plot_theme +
    theme(legend.position = "none")

  save_figure(
    file.path(
      "selected_plants",
      paste0("annual_selected_plants_", pollutant_row$pollutant, "_ef.png")
    ),
    p,
    width = 10,
    height = 6.5
  )
}


# ---- Average EF by Fuel Type -------------------------------------------------

annual_generation_by_fuel <- annual_analysis %>%
  filter(!is.na(generation_mwh)) %>%
  group_by(fuel_clean, fuel_label, year) %>%
  summarise(
    generation_mwh = sum(generation_mwh, na.rm = TRUE),
    plants = n_distinct(plant_id),
    .groups = "drop"
  )

save_table(
  annual_generation_by_fuel,
  file.path("fuel_type_averages", "annual_fuel_type_generation_mwh.csv")
)

if (nrow(annual_generation_by_fuel) > 0) {
  plotted_fuels <- annual_generation_by_fuel %>%
    group_by(fuel_clean, fuel_label) %>%
    summarise(
      years = n(),
      generation_mwh = sum(generation_mwh, na.rm = TRUE),
      .groups = "drop"
    ) %>%
    filter(years >= 3) %>%
    arrange(desc(generation_mwh)) %>%
    slice_head(n = 8)

  plot_data <- annual_generation_by_fuel %>%
    semi_join(plotted_fuels, by = c("fuel_clean", "fuel_label"))

  p <- ggplot(plot_data, aes(year, generation_mwh, color = fuel_label, group = fuel_label)) +
    geom_line(linewidth = 0.9) +
    geom_point(size = 1.8) +
    scale_x_continuous(breaks = pretty_breaks()) +
    scale_y_continuous(labels = label_number(scale_cut = cut_short_scale())) +
    labs(
      title = "Annual generation by fuel type",
      x = NULL,
      y = "Generation, MWh",
      color = "Fuel"
    ) +
    plot_theme

  save_figure(
    file.path("fuel_type_averages", "annual_fuel_type_generation_mwh.png"),
    p
  )
}

fuel_time_series <- list()

for (i in seq_len(nrow(pollutants))) {
  pollutant_row <- pollutants[i, ]
  fuel_series <- aggregate_annual_ef(
    annual_analysis,
    c("fuel_clean", "fuel_label", "year"),
    pollutant_row
  )
  fuel_time_series[[pollutant_row$pollutant]] <- fuel_series

  save_table(
    fuel_series,
    file.path(
      "fuel_type_averages",
      paste0("annual_fuel_type_", pollutant_row$pollutant, "_ef.csv")
    )
  )

  if (nrow(fuel_series) == 0) {
    next
  }

  plotted_fuels <- fuel_series %>%
    group_by(fuel_clean, fuel_label) %>%
    summarise(
      years = n(),
      generation_mwh = sum(generation_mwh, na.rm = TRUE),
      .groups = "drop"
    ) %>%
    filter(years >= 3) %>%
    arrange(desc(generation_mwh)) %>%
    slice_head(n = 8)

  plot_data <- fuel_series %>%
    semi_join(plotted_fuels, by = c("fuel_clean", "fuel_label"))

  p <- ggplot(plot_data, aes(year, ef_kg_per_mwh, color = fuel_label, group = fuel_label)) +
    geom_line(linewidth = 0.9) +
    geom_point(size = 1.8) +
    scale_x_continuous(breaks = pretty_breaks()) +
    labs(
      title = paste("Average annual", pollutant_row$label, "EF by fuel type"),
      x = NULL,
      y = paste0(pollutant_row$label, " EF, kg/MWh"),
      color = "Fuel"
    ) +
    plot_theme

  save_figure(
    file.path(
      "fuel_type_averages",
      paste0("annual_fuel_type_average_", pollutant_row$pollutant, "_ef.png")
    ),
    p
  )

  mass_series <- fuel_series %>%
    select(fuel_clean, fuel_label, year, emissions_kg, generation_mwh, plants)

  save_table(
    mass_series,
    file.path(
      "fuel_type_averages",
      paste0("annual_fuel_type_", pollutant_row$pollutant, "_emissions_kg.csv")
    )
  )

  p_mass <- ggplot(plot_data, aes(year, emissions_kg, color = fuel_label, group = fuel_label)) +
    geom_line(linewidth = 0.9) +
    geom_point(size = 1.8) +
    scale_x_continuous(breaks = pretty_breaks()) +
    scale_y_continuous(labels = label_number(scale_cut = cut_short_scale())) +
    labs(
      title = paste("Annual", pollutant_row$label, "mass emissions by fuel type"),
      x = NULL,
      y = paste0(pollutant_row$label, " emissions, kg"),
      color = "Fuel"
    ) +
    plot_theme

  save_figure(
    file.path(
      "fuel_type_averages",
      paste0("annual_fuel_type_", pollutant_row$pollutant, "_emissions_kg.png")
    ),
    p_mass
  )
}


# ---- Structural Break and Projection -----------------------------------------
# Paused: holding off on EF break/plateau projections for now (2026-06-30).
# Wrapped in `if (FALSE)` rather than deleted so this can be re-enabled
# later without reconstructing it from git history.
if (FALSE) {

fit_break_projection <- function(
  series,
  pollutant_label,
  group_label,
  output_stub,
  final_year = 2050
) {
  series <- series %>%
    arrange(year) %>%
    filter(!is.na(ef_kg_per_mwh))

  if (nrow(series) < 7) {
    return(NULL)
  }

  first_year <- min(series$year)
  last_year <- max(series$year)
  model_data <- tibble(year = seq(first_year, final_year)) %>%
    left_join(series %>% select(year, ef_kg_per_mwh), by = "year") %>%
    mutate(
      observed = year <= last_year & !is.na(ef_kg_per_mwh),
      t = year - first_year
    )

  candidates <- seq(2017, 2022)
  candidates <- candidates[candidates > first_year & candidates < last_year]
  break_results <- tibble()

  for (break_year in candidates) {
    pre_n <- sum(model_data$observed & model_data$year < break_year)
    post_n <- sum(model_data$observed & model_data$year >= break_year)

    if (pre_n >= 3 && post_n >= 3) {
      model_data <- model_data %>%
        mutate(
          post_tmp = year >= break_year,
          t_pre_tmp = if_else(year < break_year, t, 0)
        )

      fit <- try(
        lm(
          ef_kg_per_mwh ~ t_pre_tmp + post_tmp,
          data = model_data %>% filter(observed)
        ),
        silent = TRUE
      )

      if (!inherits(fit, "try-error")) {
        rss <- sum(residuals(fit)^2)
        n <- length(residuals(fit))
        k <- length(coef(fit))
        bic <- n * log(rss / n) + k * log(n)
        break_results <- bind_rows(
          break_results,
          tibble(
            pollutant = pollutant_label,
            group = group_label,
            break_year = break_year,
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

  best <- break_results %>%
    arrange(bic, break_year) %>%
    slice(1)
  break_year <- best$break_year[[1]]

  model_data <- model_data %>%
    mutate(
      post = year >= break_year,
      t_pre = if_else(year < break_year, t, 0)
    )

  fit_two_period <- lm(
    ef_kg_per_mwh ~ t_pre + post,
    data = model_data %>% filter(observed)
  )
  save_model(
    fit_two_period,
    file.path("projections", paste0("annual_projection_", output_stub, ".rds"))
  )

  model_data$two_period_hat <- predict(fit_two_period, newdata = model_data)

  post_values <- model_data %>%
    filter(observed, year >= break_year) %>%
    pull(ef_kg_per_mwh)
  post_median <- median(post_values, na.rm = TRUE)
  post_p10 <- unname(quantile(post_values, 0.10, na.rm = TRUE))

  model_data <- model_data %>%
    mutate(
      post_median_hat = if_else(observed, ef_kg_per_mwh, post_median),
      two_period_hat = if_else(
        !observed & two_period_hat < post_p10,
        post_p10,
        two_period_hat
      )
    )

  chow_p_value <- NA_real_
  chow_fit <- try(
    lm(ef_kg_per_mwh ~ t * post, data = model_data %>% filter(observed)),
    silent = TRUE
  )
  reduced_fit <- try(
    lm(ef_kg_per_mwh ~ t, data = model_data %>% filter(observed)),
    silent = TRUE
  )

  if (!inherits(chow_fit, "try-error") && !inherits(reduced_fit, "try-error")) {
    chow_test <- try(anova(reduced_fit, chow_fit), silent = TRUE)
    if (!inherits(chow_test, "try-error") && nrow(chow_test) >= 2) {
      chow_p_value <- chow_test$`Pr(>F)`[[2]]
    }
  }

  projection_table <- model_data %>%
    transmute(
      year,
      observed,
      ef_kg_per_mwh,
      two_period_hat,
      post_median_hat,
      pollutant = pollutant_label,
      group = group_label,
      break_year = break_year
    )
  save_table(
    projection_table,
    file.path("projections", paste0("annual_projection_", output_stub, ".csv"))
  )

  plot_data <- model_data %>%
    select(year, observed, ef_kg_per_mwh, two_period_hat, post_median_hat) %>%
    pivot_longer(
      cols = c(ef_kg_per_mwh, two_period_hat, post_median_hat),
      names_to = "series",
      values_to = "value"
    ) %>%
    mutate(
      series = recode(
        series,
        ef_kg_per_mwh = "Observed",
        two_period_hat = "Two-period: linear then flat",
        post_median_hat = "Post-break median plateau"
      ),
      is_observed_series = series == "Observed"
    ) %>%
    filter(!is_observed_series | observed)

  p <- ggplot(plot_data, aes(year, value, color = series, linetype = series)) +
    geom_line(linewidth = 1.0, na.rm = TRUE) +
    geom_point(
      data = plot_data %>% filter(series == "Observed"),
      size = 1.8,
      na.rm = TRUE
    ) +
    geom_vline(xintercept = break_year, linetype = "dashed") +
    geom_vline(xintercept = last_year, linetype = "dotted") +
    scale_color_manual(
      values = c(
        "Observed" = "#1E88FF",
        "Two-period: linear then flat" = "#D81B60",
        "Post-break median plateau" = "#D81B60"
      )
    ) +
    scale_linetype_manual(
      values = c(
        "Observed" = "solid",
        "Two-period: linear then flat" = "longdash",
        "Post-break median plateau" = "dotted"
      )
    ) +
    scale_x_continuous(breaks = pretty_breaks()) +
    labs(
      title = paste(group_label, pollutant_label, "EF projection"),
      subtitle = paste0(
        "Annual EF; linear before break, nonzero plateau after break; break = ",
        break_year
      ),
      x = NULL,
      y = paste0(pollutant_label, " EF, kg/MWh"),
      color = NULL,
      linetype = NULL
    ) +
    plot_theme

  save_figure(
    file.path(
      "projections",
      paste0("annual_projection_", output_stub, "_break_plateau.png")
    ),
    p
  )

  tibble(
    pollutant = pollutant_label,
    group = group_label,
    break_year = break_year,
    bic = best$bic[[1]],
    rss = best$rss[[1]],
    post_median_plateau = post_median,
    post_p10_floor = post_p10,
    chow_style_p_value = chow_p_value,
    first_observed_year = first_year,
    last_observed_year = last_year,
    last_observed_ef = tail(series$ef_kg_per_mwh, 1),
    projected_2050_two_period = tail(model_data$two_period_hat, 1),
    projected_2050_post_median = tail(model_data$post_median_hat, 1)
  )
}

projection_summaries <- list()

for (i in seq_len(nrow(pollutants))) {
  pollutant_row <- pollutants[i, ]

  all_series <- aggregate_annual_ef(
    annual_analysis,
    "year",
    pollutant_row
  )
  result <- fit_break_projection(
    all_series,
    pollutant_row$label,
    "All fuels",
    paste0("all_fuels_", pollutant_row$pollutant)
  )
  if (!is.null(result)) {
    projection_summaries[[length(projection_summaries) + 1]] <- result
  }

  fuel_series <- fuel_time_series[[pollutant_row$pollutant]]
  fuels_for_projection <- sort(unique(fuel_series$fuel_clean))
  for (fuel_index in seq_along(fuels_for_projection)) {
    fuel <- fuels_for_projection[[fuel_index]]
    fuel_data <- fuel_series %>% filter(fuel_clean == fuel)
    fuel_label <- fuel_data$fuel_label[[1]]
    result <- fit_break_projection(
      fuel_data,
      pollutant_row$label,
      fuel_label,
      paste0("fuel_", sprintf("%02d", fuel_index), "_", pollutant_row$pollutant)
    )

    if (!is.null(result)) {
      projection_summaries[[length(projection_summaries) + 1]] <- result
    }
  }
}

projection_summary <- bind_rows(projection_summaries)
save_table(projection_summary, "annual_break_projection_summary.csv")

} # end paused EF projection block

cat("\nAnnual plant analysis complete.\n")
cat("Summary tables saved under:", tables_dir, "\n")
cat("Figures saved under:", figures_dir, "\n")
