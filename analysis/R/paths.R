project_root <- function() {
  root <- Sys.getenv("NZK_APHIAM_ROOT", unset = NA_character_)

  if (!is.na(root) && nzchar(root)) {
    return(normalizePath(root, mustWork = TRUE))
  }

  markers <- c("NZK-APHIAM.Rproj", "pyproject.toml", ".git")
  current <- normalizePath(getwd(), mustWork = TRUE)

  repeat {
    if (any(file.exists(file.path(current, markers)))) {
      return(current)
    }

    parent <- dirname(current)

    if (identical(parent, current)) {
      stop(
        "Could not find project root. Open NZK-APHIAM.Rproj or set NZK_APHIAM_ROOT.",
        call. = FALSE
      )
    }

    current <- parent
  }
}

project_path <- function(...) {
  file.path(project_root(), ...)
}

data_path <- function(...) {
  project_path("data", ...)
}

thermal_raw_path <- function(...) {
  data_path("raw", ...)
}

thermal_interim_path <- function(...) {
  data_path("interim", ...)
}

kepco_processed_path <- function(...) {
  data_path("processed", "kepco", ...)
}

thermal_processed_path <- function(...) {
  kepco_processed_path(...)
}

results_path <- function(...) {
  project_path("results", ...)
}
