#!/usr/bin/env Rscript

# Query generation-weighted KEPCO emission factors for a user-defined cohort.
# Run `Rscript analysis/kepco/query_ef_cohort.R --help` for examples.

source(file.path("analysis", "R", "paths.R"))
source(file.path("analysis", "kepco", "ef_eligibility.R"))

options(stringsAsFactors = FALSE, scipen = 999)

QUERY_POLLUTANTS <- data.frame(
  pollutant = c("nox", "sox", "dust_tsp"),
  ef = c("nox_kg_per_mwh", "sox_kg_per_mwh", "dust_tsp_kg_per_mwh"),
  label = c("NOx", "SOx", "TSP"),
  compact_name = c("nox", "sox", "tsp"),
  stringsAsFactors = FALSE
)

QUERY_GROUPS <- c(
  "year", "month", "province", "fuel", "technology", "plant",
  "subsidiary", "unit"
)

query_usage <- function() {
  cat(
    paste(
      "Query KEPCO monthly emission data and calculate cohort EFs.",
      "",
      "Usage:",
      "  Rscript analysis/kepco/query_ef_cohort.R [options]",
      "",
      "Time options:",
      "  --year YYYY                 One calendar year",
      "  --start-year YYYY           First year in a range",
      "  --end-year YYYY             Last year in a range",
      "  --month YYYY-MM             One specific month",
      "  --start-date YYYY-MM        First month in a monthly range",
      "  --end-date YYYY-MM          Last month in a monthly range",
      "  --calendar-month 1..12      Keep that month in every selected year",
      "",
      "Cohort options (comma-separated values are accepted):",
      "  --pollutant all|nox|sox|tsp",
      "  --fuel all|VALUE",
      "  --technology all|VALUE",
      "  --province all|VALUE",
      "  --subsidiary all|VALUE",
      "",
      "Output options:",
      "  --group-by DIMENSIONS       Comma-separated: year, month, province,",
      "                              fuel, technology, plant, subsidiary, unit",
      "  --specification NAME        operational_primary (default),",
      "                              low_load_inclusive, or conservative_quality",
      "  --min-coverage-pct NUMBER   Suppress EF below this generation coverage",
      "                              percentage (default: 50)",
      "  --layout compact|long|slide Compact puts pollutant EFs in columns;",
      "                              slide returns a labeled presentation table",
      "  --output PATH               CSV path relative to project root",
      "  --list-values               Print available cohort values and exit",
      "  --help                      Print this help and exit",
      "",
      "Examples:",
      "  # 2017 coal steam-turbine EFs for all pollutants, by province",
      "  Rscript analysis/kepco/query_ef_cohort.R --year 2017 --fuel coal \\",
      "    --technology conventional_steam_turbine --pollutant all \\",
      "    --group-by province",
      "",
      "  # Annual NOx estimates for gas CCGT by province, 2018-2023",
      "  Rscript analysis/kepco/query_ef_cohort.R --start-year 2018 \\",
      "    --end-year 2023 --fuel natural_gas \\",
      "    --technology combined_cycle_gas_turbine --pollutant nox \\",
      "    --group-by year,province --layout long",
      sep = "\n"
    ),
    "\n"
  )
}

query_arg_defaults <- function() {
  list(
    help = FALSE,
    list_values = FALSE,
    year = NULL,
    start_year = NULL,
    end_year = NULL,
    month = NULL,
    start_date = NULL,
    end_date = NULL,
    calendar_month = NULL,
    pollutant = "all",
    fuel = "all",
    technology = "all",
    province = "all",
    subsidiary = "all",
    group_by = "province",
    specification = "operational_primary",
    min_coverage_pct = "50",
    layout = "compact",
    output = file.path(
      "results", "tables", "kepco", "queries", "kepco_ef_cohort_query.csv"
    )
  )
}

parse_query_args <- function(args) {
  values <- query_arg_defaults()
  flag_options <- c("help", "list_values")
  aliases <- c(
    pollutants = "pollutant",
    tech = "technology",
    group = "group_by",
    spec = "specification"
  )

  i <- 1L
  while (i <= length(args)) {
    argument <- args[[i]]
    if (!grepl("^--", argument)) {
      stop("Unexpected positional argument: ", argument, call. = FALSE)
    }

    without_prefix <- sub("^--", "", argument)
    if (grepl("=", without_prefix, fixed = TRUE)) {
      pieces <- strsplit(without_prefix, "=", fixed = TRUE)[[1]]
      key <- pieces[[1]]
      value <- paste(pieces[-1], collapse = "=")
    } else {
      key <- without_prefix
      value <- NULL
    }
    key <- gsub("-", "_", key, fixed = TRUE)
    if (key %in% names(aliases)) key <- unname(aliases[[key]])

    if (!key %in% names(values)) {
      stop("Unknown option --", gsub("_", "-", key), call. = FALSE)
    }
    if (key %in% flag_options) {
      if (!is.null(value) && nzchar(value)) {
        stop("--", gsub("_", "-", key), " does not take a value.", call. = FALSE)
      }
      values[[key]] <- TRUE
    } else {
      if (is.null(value)) {
        i <- i + 1L
        if (i > length(args) || grepl("^--", args[[i]])) {
          stop("--", gsub("_", "-", key), " requires a value.", call. = FALSE)
        }
        value <- args[[i]]
      }
      values[[key]] <- value
    }
    i <- i + 1L
  }

  values
}

split_query_values <- function(value) {
  values <- trimws(strsplit(value, ",", fixed = TRUE)[[1]])
  values[nzchar(values)]
}

normalize_query_value <- function(value) {
  normalized <- tolower(gsub("[^[:alnum:]]+", "_", trimws(value)))
  gsub("^_+|_+$", "", normalized)
}

parse_query_year <- function(value, option) {
  year <- suppressWarnings(as.integer(value))
  if (is.na(year) || !grepl("^[0-9]{4}$", value)) {
    stop("--", option, " must be a four-digit year.", call. = FALSE)
  }
  year
}

parse_query_month <- function(value, option) {
  if (!grepl("^[0-9]{4}-(0[1-9]|1[0-2])$", value)) {
    stop("--", option, " must use YYYY-MM.", call. = FALSE)
  }
  as.Date(paste0(value, "-01"))
}

resolve_query_filter <- function(data, column, requested, option) {
  requested_values <- split_query_values(requested)
  if (length(requested_values) == 0 || identical(normalize_query_value(requested_values), "all")) {
    return(data)
  }
  if ("all" %in% normalize_query_value(requested_values)) {
    stop("--", option, " cannot combine 'all' with named values.", call. = FALSE)
  }

  available <- sort(unique(na.omit(data[[column]])))
  available_normalized <- normalize_query_value(available)
  requested_normalized <- normalize_query_value(requested_values)
  missing <- requested_values[!requested_normalized %in% available_normalized]
  if (length(missing) > 0) {
    stop(
      "Unknown --", option, " value(s): ", paste(missing, collapse = ", "),
      "\nAvailable values: ", paste(available, collapse = ", "),
      call. = FALSE
    )
  }

  normalized_data <- normalize_query_value(data[[column]])
  keep <- !is.na(normalized_data) & normalized_data %in% requested_normalized
  data[keep, , drop = FALSE]
}

load_kepco_query_data <- function() {
  input_path <- kepco_processed_path("kepco_monthly_generation_emissions.csv")
  if (!file.exists(input_path)) {
    stop(
      "Required processed file is missing: ", input_path,
      "\nRun `make combine-kepco` first.",
      call. = FALSE
    )
  }

  data <- read.csv(
    input_path,
    na.strings = c("", "NA"),
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
  data$date <- as.Date(data$date)
  if (!all(data$observation_frequency == "monthly")) {
    stop("Processed KEPCO data contain non-monthly observations.", call. = FALSE)
  }
  if (!all(data$pollutant_measurement_basis == "mass")) {
    stop("Processed KEPCO data contain non-mass pollutant values.", call. = FALSE)
  }
  if (!identical(unique(na.omit(data$emissions_mass_unit)), "kilograms")) {
    stop("Processed emissions are not consistently standardized to kg.", call. = FALSE)
  }
  data
}

prepare_kepco_query_data <- function(
  data,
  specification = "operational_primary",
  pollutants = QUERY_POLLUTANTS
) {
  if (!specification %in% EF_SPECIFICATIONS) {
    stop(
      "Unknown specification: ", specification,
      "\nAvailable values: ", paste(EF_SPECIFICATIONS, collapse = ", "),
      call. = FALSE
    )
  }

  data$.ef_source_row_id <- seq_len(nrow(data))
  data$fuel_type_clean <- ifelse(
    is.na(data$fuel_type) | data$fuel_type == "",
    "unknown",
    data$fuel_type
  )
  fallback_unit_id <- paste(
    data$plant_name,
    ifelse(is.na(data$plant_number), "NA", data$plant_number),
    data$fuel_type_clean,
    sep = " | "
  )
  data$plant_unit_id <- ifelse(
    !is.na(data$reporting_unit_id) & data$reporting_unit_id != "",
    data$reporting_unit_id,
    fallback_unit_id
  )
  for (i in seq_len(nrow(pollutants))) {
    pollutant <- pollutants$pollutant[[i]]
    ef_column <- pollutants$ef[[i]]
    data[[ef_column]] <- ifelse(
      !is.na(data$energy_generated_mwh) & data$energy_generated_mwh > 0,
      data[[pollutant]] / data$energy_generated_mwh,
      NA_real_
    )
  }

  eligibility <- build_ef_eligibility(data, pollutants)
  prepared <- apply_ef_specification(data, eligibility, pollutants, specification)
  prepared <- prepared[
    is.na(prepared$row_status) | prepared$row_status != "inactive_placeholder",
    ,
    drop = FALSE
  ]
  prepared$year <- as.integer(format(prepared$date, "%Y"))
  prepared$month <- format(prepared$date, "%Y-%m")
  prepared$calendar_month <- as.integer(format(prepared$date, "%m"))
  prepared$province <- prepared$plant_province
  prepared$fuel <- prepared$fuel_type_clean
  prepared$plant <- prepared$plant_name
  prepared$subsidiary <- prepared$subsidiary_company
  prepared$unit <- prepared$plant_unit_id
  prepared
}

select_query_pollutants <- function(requested, pollutants = QUERY_POLLUTANTS) {
  values <- normalize_query_value(split_query_values(requested))
  if (length(values) == 0 || identical(values, "all")) {
    return(pollutants$pollutant)
  }
  values[values == "tsp"] <- "dust_tsp"
  if ("all" %in% values) {
    stop("--pollutant cannot combine 'all' with named values.", call. = FALSE)
  }
  unknown <- setdiff(values, pollutants$pollutant)
  if (length(unknown) > 0) {
    stop(
      "Unknown pollutant(s): ", paste(unknown, collapse = ", "),
      "\nAvailable values: all, nox, sox, tsp",
      call. = FALSE
    )
  }
  unique(values)
}

resolve_query_period <- function(data, options) {
  specified <- c(
    year = !is.null(options$year),
    month = !is.null(options$month),
    year_range = !is.null(options$start_year) || !is.null(options$end_year),
    date_range = !is.null(options$start_date) || !is.null(options$end_date)
  )
  if (sum(specified) > 1) {
    stop(
      "Choose only one of --year, --month, a year range, or a date range.",
      call. = FALSE
    )
  }

  minimum_date <- min(data$date, na.rm = TRUE)
  maximum_date <- max(data$date, na.rm = TRUE)
  if (!is.null(options$year)) {
    year <- parse_query_year(options$year, "year")
    start <- as.Date(sprintf("%d-01-01", year))
    end <- as.Date(sprintf("%d-12-01", year))
  } else if (!is.null(options$month)) {
    start <- parse_query_month(options$month, "month")
    end <- start
  } else if (specified[["year_range"]]) {
    start_year <- if (is.null(options$start_year)) {
      as.integer(format(minimum_date, "%Y"))
    } else {
      parse_query_year(options$start_year, "start-year")
    }
    end_year <- if (is.null(options$end_year)) {
      as.integer(format(maximum_date, "%Y"))
    } else {
      parse_query_year(options$end_year, "end-year")
    }
    start <- as.Date(sprintf("%d-01-01", start_year))
    end <- as.Date(sprintf("%d-12-01", end_year))
  } else if (specified[["date_range"]]) {
    start <- if (is.null(options$start_date)) {
      minimum_date
    } else {
      parse_query_month(options$start_date, "start-date")
    }
    end <- if (is.null(options$end_date)) {
      maximum_date
    } else {
      parse_query_month(options$end_date, "end-date")
    }
  } else {
    start <- minimum_date
    end <- maximum_date
  }

  if (start > end) stop("Query start must not follow query end.", call. = FALSE)
  list(start = start, end = end)
}

group_row_values <- function(data, index, group_by) {
  if (identical(group_by, "none")) {
    return(data.frame(cohort = "all", stringsAsFactors = FALSE))
  }
  values <- data[index[[1]], group_by, drop = FALSE]
  for (column in names(values)) {
    missing <- is.na(values[[column]]) | values[[column]] == ""
    values[[column]][missing] <- "unknown"
  }
  values
}

query_kepco_ef <- function(
  data,
  selected_pollutants,
  group_by = "province",
  min_coverage_pct = 50,
  pollutants = QUERY_POLLUTANTS
) {
  if (identical(group_by, "none")) {
    group_key <- rep("all", nrow(data))
  } else {
    missing_groups <- setdiff(group_by, QUERY_GROUPS)
    if (length(missing_groups) > 0) {
      stop(
        "Unknown grouping dimension(s): ", paste(missing_groups, collapse = ", "),
        "\nAvailable values: ", paste(c(QUERY_GROUPS, "none"), collapse = ", "),
        call. = FALSE
      )
    }
    group_data <- data[group_by]
    for (column in names(group_data)) {
      missing <- is.na(group_data[[column]]) | group_data[[column]] == ""
      group_data[[column]][missing] <- "unknown"
    }
    group_key <- do.call(paste, c(group_data, sep = "\r"))
  }
  groups <- split(seq_len(nrow(data)), factor(group_key, levels = unique(group_key)))

  output <- list()
  for (index in groups) {
    generation <- data$energy_generated_mwh[index]
    positive_generation <- !is.na(generation) & generation > 0
    total_generation <- sum(generation[positive_generation], na.rm = TRUE)
    if (total_generation <= 0) next

    cohort_plants <- unique(data$plant_name[index][positive_generation])
    cohort_units <- unique(data$plant_unit_id[index][positive_generation])
    cohort_dates <- unique(data$date[index][positive_generation])

    for (pollutant in selected_pollutants) {
      emissions <- data[[pollutant]][index]
      valid <- positive_generation & !is.na(emissions)
      valid_generation <- sum(generation[valid], na.rm = TRUE)
      valid_emissions <- sum(emissions[valid], na.rm = TRUE)
      coverage <- valid_generation / total_generation
      status <- if (valid_generation <= 0) {
        "no_valid_pollutant_data"
      } else if (coverage * 100 < min_coverage_pct) {
        "suppressed_low_coverage"
      } else {
        "available"
      }
      ef <- if (identical(status, "available")) {
        valid_emissions / valid_generation
      } else {
        NA_real_
      }
      valid_index <- index[valid]

      output[[length(output) + 1L]] <- cbind(
        group_row_values(data, index, group_by),
        data.frame(
          pollutant = pollutant,
          pollutant_label = pollutants$label[match(pollutant, pollutants$pollutant)],
          ef_kg_per_mwh = ef,
          estimate_status = status,
          emissions_kg = valid_emissions,
          valid_generation_mwh = valid_generation,
          total_cohort_generation_mwh = total_generation,
          generation_coverage_pct = 100 * coverage,
          valid_plant_count = length(unique(data$plant_name[valid_index])),
          valid_unit_count = length(unique(data$plant_unit_id[valid_index])),
          valid_unit_month_count = length(valid_index),
          valid_months_covered = length(unique(data$date[valid_index])),
          cohort_plant_count = length(cohort_plants),
          cohort_unit_count = length(cohort_units),
          cohort_months_covered = length(cohort_dates),
          stringsAsFactors = FALSE
        )
      )
    }
  }

  if (length(output) == 0) return(data.frame())
  result <- do.call(rbind, output)
  rownames(result) <- NULL
  result
}

compact_kepco_ef_query <- function(
  long_data,
  group_by,
  selected_pollutants,
  pollutants = QUERY_POLLUTANTS
) {
  id_columns <- if (identical(group_by, "none")) "cohort" else group_by
  id_data <- unique(long_data[id_columns])
  id_key <- do.call(paste, c(id_data, sep = "\r"))
  long_key <- do.call(paste, c(long_data[id_columns], sep = "\r"))
  output <- id_data

  for (pollutant in selected_pollutants) {
    compact_name <- pollutants$compact_name[
      match(pollutant, pollutants$pollutant)
    ]
    selected <- long_data[long_data$pollutant == pollutant, , drop = FALSE]
    selected_key <- long_key[long_data$pollutant == pollutant]
    matched <- match(id_key, selected_key)
    output[[paste0(compact_name, "_ef_kg_per_mwh")]] <- selected$ef_kg_per_mwh[matched]
  }

  first_rows <- match(id_key, long_key)
  output$cohort_plant_count <- long_data$cohort_plant_count[first_rows]
  output$cohort_unit_count <- long_data$cohort_unit_count[first_rows]
  output$cohort_months_covered <- long_data$cohort_months_covered[first_rows]
  output$cohort_generation_gwh <-
    long_data$total_cohort_generation_mwh[first_rows] / 1000

  coverage <- split(long_data$generation_coverage_pct, long_key)
  status <- split(
    paste0(long_data$pollutant_label, ": ", long_data$estimate_status),
    long_key
  )
  output$minimum_pollutant_coverage_pct <- vapply(
    id_key,
    function(key) min(coverage[[key]], na.rm = TRUE),
    numeric(1)
  )
  output$estimate_status <- vapply(id_key, function(key) {
    group_status <- status[[key]]
    if (all(grepl(": available$", group_status))) {
      "all_requested_pollutants_available"
    } else {
      paste(group_status, collapse = "; ")
    }
  }, character(1))
  output
}

slide_kepco_ef_query <- function(
  compact_data,
  group_by,
  selected_pollutants,
  pollutants = QUERY_POLLUTANTS
) {
  id_columns <- if (identical(group_by, "none")) "cohort" else group_by
  ef_columns <- vapply(selected_pollutants, function(pollutant) {
    compact_name <- pollutants$compact_name[match(pollutant, pollutants$pollutant)]
    paste0(compact_name, "_ef_kg_per_mwh")
  }, character(1))
  output <- compact_data[c(
    id_columns,
    ef_columns,
    "cohort_plant_count",
    "cohort_generation_gwh",
    "minimum_pollutant_coverage_pct"
  )]
  output[ef_columns] <- lapply(output[ef_columns], round, digits = 3)
  output$cohort_generation_gwh <- round(output$cohort_generation_gwh, digits = 1)
  output$minimum_pollutant_coverage_pct <- round(
    output$minimum_pollutant_coverage_pct,
    digits = 1
  )

  group_labels <- c(
    cohort = "Cohort",
    year = "Year",
    month = "Month",
    province = "Province",
    fuel = "Fuel",
    technology = "Technology",
    plant = "Plant",
    subsidiary = "Subsidiary",
    unit = "Reporting unit"
  )
  names(output)[match(id_columns, names(output))] <- group_labels[id_columns]
  for (pollutant in selected_pollutants) {
    compact_name <- pollutants$compact_name[match(pollutant, pollutants$pollutant)]
    label <- pollutants$label[match(pollutant, pollutants$pollutant)]
    names(output)[names(output) == paste0(compact_name, "_ef_kg_per_mwh")] <-
      paste0(label, " EF (kg/MWh)")
  }
  names(output)[names(output) == "cohort_plant_count"] <- "Plants"
  names(output)[names(output) == "cohort_generation_gwh"] <- "Generation (GWh)"
  names(output)[names(output) == "minimum_pollutant_coverage_pct"] <-
    "Minimum coverage (%)"
  output
}

print_kepco_query_values <- function(data) {
  cat("Date range:\n  ", format(min(data$date)), " to ", format(max(data$date)), "\n", sep = "")
  available <- list(
    pollutants = c("nox", "sox", "tsp"),
    fuels = sort(unique(na.omit(data$fuel))),
    technologies = sort(unique(na.omit(data$technology))),
    provinces = sort(unique(na.omit(data$province))),
    subsidiaries = sort(unique(na.omit(data$subsidiary))),
    specifications = EF_SPECIFICATIONS,
    grouping_dimensions = c(QUERY_GROUPS, "none")
  )
  for (label in names(available)) {
    cat(
      label, ":\n  ",
      paste(unname(available[[label]]), collapse = "\n  "),
      "\n",
      sep = ""
    )
  }
}

run_kepco_ef_query <- function(options) {
  raw_data <- load_kepco_query_data()
  prepared <- prepare_kepco_query_data(raw_data, options$specification)
  if (isTRUE(options$list_values)) {
    print_kepco_query_values(prepared)
    return(invisible(NULL))
  }

  period <- resolve_query_period(prepared, options)
  selected <- prepared[
    prepared$date >= period$start & prepared$date <= period$end,
    ,
    drop = FALSE
  ]
  if (!is.null(options$calendar_month)) {
    calendar_month <- suppressWarnings(as.integer(options$calendar_month))
    if (is.na(calendar_month) || calendar_month < 1 || calendar_month > 12) {
      stop("--calendar-month must be an integer from 1 to 12.", call. = FALSE)
    }
    selected <- selected[selected$calendar_month == calendar_month, , drop = FALSE]
  }
  selected <- resolve_query_filter(selected, "fuel", options$fuel, "fuel")
  selected <- resolve_query_filter(
    selected, "technology", options$technology, "technology"
  )
  selected <- resolve_query_filter(selected, "province", options$province, "province")
  selected <- resolve_query_filter(
    selected, "subsidiary", options$subsidiary, "subsidiary"
  )
  if (nrow(selected) == 0) {
    stop("No observations match the requested time and cohort filters.", call. = FALSE)
  }

  selected_pollutants <- select_query_pollutants(options$pollutant)
  group_by <- normalize_query_value(split_query_values(options$group_by))
  if (length(group_by) == 0) group_by <- "none"
  if ("none" %in% group_by && length(group_by) > 1) {
    stop("--group-by none cannot be combined with other dimensions.", call. = FALSE)
  }
  min_coverage_pct <- suppressWarnings(as.numeric(options$min_coverage_pct))
  if (
    is.na(min_coverage_pct) || min_coverage_pct < 0 || min_coverage_pct > 100
  ) {
    stop("--min-coverage-pct must be between 0 and 100.", call. = FALSE)
  }

  long_result <- query_kepco_ef(
    selected,
    selected_pollutants,
    group_by,
    min_coverage_pct
  )
  if (nrow(long_result) == 0) {
    stop("The requested cohort has no positive generation.", call. = FALSE)
  }
  order_columns <- if (identical(group_by, "none")) "cohort" else group_by
  long_result <- long_result[
    do.call(order, long_result[order_columns]),
    ,
    drop = FALSE
  ]
  if (options$layout == "compact") {
    result <- compact_kepco_ef_query(
      long_result,
      group_by,
      selected_pollutants
    )
  } else if (options$layout == "long") {
    result <- long_result
  } else if (options$layout == "slide") {
    result <- compact_kepco_ef_query(
      long_result,
      group_by,
      selected_pollutants
    )
    result <- slide_kepco_ef_query(
      result,
      group_by,
      selected_pollutants
    )
  } else {
    stop("--layout must be compact, long, or slide.", call. = FALSE)
  }

  if (options$layout != "slide") {
    result$ef_specification <- options$specification
    result$query_start_month <- format(period$start, "%Y-%m")
    result$query_end_month <- format(period$end, "%Y-%m")
    result$minimum_required_coverage_pct <- min_coverage_pct
  }
  rownames(result) <- NULL

  output_path <- options$output
  if (!grepl("^/", output_path)) output_path <- project_path(output_path)
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  write.csv(result, output_path, row.names = FALSE, na = "")

  cat("Saved query table: ", output_path, "\n\n", sep = "")
  print(result, row.names = FALSE)
  invisible(result)
}

main <- function() {
  options <- parse_query_args(commandArgs(trailingOnly = TRUE))
  if (isTRUE(options$help)) {
    query_usage()
    return(invisible(NULL))
  }
  run_kepco_ef_query(options)
}

if (sys.nframe() == 0) main()
