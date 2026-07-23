# Shared eligibility rules for KEPCO monthly emission-factor observations.

EF_SPECIFICATIONS <- c(
  "operational_primary",
  "low_load_inclusive",
  "conservative_quality"
)

require_ef_columns <- function(data, columns, label = "KEPCO EF data") {
  missing <- setdiff(columns, names(data))
  if (length(missing) > 0) {
    stop(
      label, " is missing required columns: ",
      paste(missing, collapse = ", "),
      call. = FALSE
    )
  }
  invisible(data)
}

contains_issue <- function(issue_codes, pattern) {
  grepl(pattern, ifelse(is.na(issue_codes), "", issue_codes))
}

join_exclusion_reasons <- function(reason_masks) {
  if (nrow(reason_masks) == 0) {
    return(character())
  }

  apply(reason_masks, 1, function(row) {
    reasons <- names(row)[as.logical(row)]
    if (length(reasons) == 0) NA_character_ else paste(reasons, collapse = ";")
  })
}

days_in_observation_month <- function(date) {
  month_start <- as.Date(format(as.Date(date), "%Y-%m-01"))
  next_month <- as.Date(format(month_start + 32, "%Y-%m-01"))
  as.numeric(next_month - month_start)
}

build_ef_eligibility <- function(
  data,
  pollutants,
  low_load_capacity_factor = 0.01
) {
  require_ef_columns(
    data,
    c(
      ".ef_source_row_id", "source_dataset", "date", "plant_name",
      "plant_number", "subsidiary_company", "fuel_type_clean", "technology",
      "plant_province", "row_status", "energy_generated_mwh",
      "energy_capacity_mw", "generation_coverage_status",
      "generation_reconciliation_status", "audit_severity", "audit_issue_codes"
    )
  )
  require_ef_columns(pollutants, c("pollutant", "ef", "label"), "pollutant map")

  days_in_month <- days_in_observation_month(data$date)
  capacity_factor <- data$energy_generated_mwh /
    (data$energy_capacity_mw * days_in_month * 24)
  issue_codes <- ifelse(is.na(data$audit_issue_codes), "", data$audit_issue_codes)

  rows <- lapply(seq_len(nrow(pollutants)), function(i) {
    pollutant <- pollutants$pollutant[[i]]
    pollutant_label <- pollutants$label[[i]]
    ef_column <- pollutants$ef[[i]]
    require_ef_columns(data, c(pollutant, ef_column))

    emissions <- data[[pollutant]]
    generation <- data$energy_generated_mwh
    raw_ef <- ifelse(
      !is.na(generation) & generation > 0,
      emissions / generation,
      NA_real_
    )

    inactive <- !is.na(data$row_status) & data$row_status == "inactive_placeholder"
    missing_emissions <- is.na(emissions)
    missing_generation <- is.na(generation)
    nonpositive_generation <- !missing_generation & generation <= 0
    duplicate_key <- contains_issue(issue_codes, "(^|;)duplicate_unit_month(;|$)")
    negative_generation <- (!is.na(generation) & generation < 0) |
      contains_issue(issue_codes, "(^|;)negative_energy_generated_mwh(;|$)")
    negative_capacity <- (
      !is.na(data$energy_capacity_mw) & data$energy_capacity_mw < 0
    ) | contains_issue(issue_codes, "(^|;)negative_energy_capacity_mw(;|$)")
    negative_pollutant <- (!is.na(emissions) & emissions < 0) |
      contains_issue(issue_codes, paste0("(^|;)negative_", pollutant, "(;|$)"))
    high_ef_outlier <- contains_issue(
      issue_codes,
      paste0("(^|;)high_", pollutant, "_emission_factor(;|$)")
    )
    implausible_zero <- contains_issue(
      issue_codes,
      paste0("(^|;)zero_", pollutant, "_(with_generation|coal_generation)(;|$)")
    )
    recent_level_shift <- contains_issue(
      issue_codes,
      paste0("(^|;)recent_shift_(high|low)_", pollutant, "_mass(;|$)")
    )
    very_low_generation <- !is.na(generation) & generation > 0 & (
      (!is.na(capacity_factor) & capacity_factor < low_load_capacity_factor) |
        contains_issue(issue_codes, "(^|;)generation_very_low_nonzero(;|$)")
    )
    generation_far_above_nameplate <- (
      !is.na(capacity_factor) & capacity_factor > 1.05
    ) | contains_issue(issue_codes, "(^|;)generation_far_above_nameplate(;|$)")
    incomplete_generation <- !is.na(data$generation_coverage_status) &
      data$generation_coverage_status == "partial"
    generation_mismatch <- !is.na(data$generation_reconciliation_status) &
      data$generation_reconciliation_status == "mismatch"

    shared_reasons <- data.frame(
      inactive_placeholder = inactive,
      missing_pollutant_mass = missing_emissions,
      missing_generation = missing_generation,
      nonpositive_generation = nonpositive_generation,
      duplicate_reporting_boundary_month = duplicate_key,
      negative_generation = negative_generation,
      negative_capacity = negative_capacity,
      negative_pollutant_mass = negative_pollutant,
      high_ef_outlier = high_ef_outlier,
      implausible_zero_pollutant = implausible_zero,
      check.names = FALSE
    )
    operational_reasons <- cbind(
      shared_reasons,
      very_low_generation = very_low_generation
    )
    conservative_reasons <- cbind(
      operational_reasons,
      generation_far_above_nameplate = generation_far_above_nameplate,
      incomplete_generation_coverage = incomplete_generation,
      generation_reconciliation_mismatch = generation_mismatch,
      recent_pollutant_level_shift = recent_level_shift
    )

    operational_reason <- join_exclusion_reasons(operational_reasons)
    low_load_inclusive_reason <- join_exclusion_reasons(shared_reasons)
    conservative_reason <- join_exclusion_reasons(conservative_reasons)

    data.frame(
      ef_source_row_id = data$.ef_source_row_id,
      source_dataset = data$source_dataset,
      date = data$date,
      plant_name = data$plant_name,
      plant_number = data$plant_number,
      reporting_unit_id = if ("reporting_unit_id" %in% names(data)) {
        data$reporting_unit_id
      } else {
        NA_character_
      },
      subsidiary_company = data$subsidiary_company,
      fuel_type_clean = data$fuel_type_clean,
      technology = data$technology,
      plant_province = data$plant_province,
      pollutant = pollutant,
      pollutant_label = pollutant_label,
      emissions_kg = emissions,
      generation_mwh = generation,
      capacity_mw = data$energy_capacity_mw,
      capacity_factor = capacity_factor,
      raw_ef_kg_per_mwh = raw_ef,
      row_status = data$row_status,
      generation_coverage_status = data$generation_coverage_status,
      generation_reconciliation_status = data$generation_reconciliation_status,
      audit_severity = data$audit_severity,
      audit_issue_codes = data$audit_issue_codes,
      structural_invalid = duplicate_key | negative_generation |
        negative_capacity | negative_pollutant,
      high_ef_outlier = high_ef_outlier,
      implausible_zero_pollutant = implausible_zero,
      very_low_generation = very_low_generation,
      recent_level_shift_review = recent_level_shift,
      generation_quality_review = generation_far_above_nameplate |
        incomplete_generation | generation_mismatch,
      operational_primary_included = is.na(operational_reason),
      operational_primary_exclusion_reason = operational_reason,
      low_load_inclusive_included = is.na(low_load_inclusive_reason),
      low_load_inclusive_exclusion_reason = low_load_inclusive_reason,
      conservative_quality_included = is.na(conservative_reason),
      conservative_quality_exclusion_reason = conservative_reason,
      stringsAsFactors = FALSE,
      check.names = FALSE
    )
  })

  output <- do.call(rbind, rows)
  output[order(output$ef_source_row_id, output$pollutant), ]
}

apply_ef_specification <- function(data, eligibility, pollutants, specification) {
  if (!specification %in% EF_SPECIFICATIONS) {
    stop(
      "Unknown EF specification: ", specification,
      ". Expected one of: ", paste(EF_SPECIFICATIONS, collapse = ", "),
      call. = FALSE
    )
  }
  require_ef_columns(data, ".ef_source_row_id")
  require_ef_columns(
    eligibility,
    c("ef_source_row_id", "pollutant", paste0(specification, "_included"))
  )

  result <- data
  inclusion_column <- paste0(specification, "_included")
  for (i in seq_len(nrow(pollutants))) {
    pollutant <- pollutants$pollutant[[i]]
    ef_column <- pollutants$ef[[i]]
    rule <- eligibility[
      eligibility$pollutant == pollutant,
      c("ef_source_row_id", inclusion_column),
      drop = FALSE
    ]
    included <- rule[[inclusion_column]][match(result$.ef_source_row_id, rule$ef_source_row_id)]
    if (anyNA(included)) {
      stop("Eligibility table does not cover every source row for ", pollutant, ".")
    }
    result[[pollutant]][!included] <- NA_real_
    result[[ef_column]][!included] <- NA_real_
  }
  result$ef_specification <- specification
  result
}

ef_exclusion_log <- function(eligibility, specification = "operational_primary") {
  if (!specification %in% EF_SPECIFICATIONS) {
    stop("Unknown EF specification: ", specification, call. = FALSE)
  }
  included_column <- paste0(specification, "_included")
  reason_column <- paste0(specification, "_exclusion_reason")
  excluded <- eligibility[!eligibility[[included_column]], , drop = FALSE]
  excluded$ef_specification <- specification
  excluded$exclusion_reason <- excluded[[reason_column]]
  excluded
}
