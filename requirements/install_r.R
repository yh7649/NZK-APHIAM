#!/usr/bin/env Rscript
# Installs pinned CRAN (requirements/r.txt, "package==version") and
# GitHub-hosted (requirements/r_github.txt, "owner/repo@sha") R dependencies.
# Run from the repository root via `make requirements-r`.

options(repos = c(CRAN = "https://cloud.r-project.org"))

if (!requireNamespace("remotes", quietly = TRUE)) {
  install.packages("remotes")
}

read_spec_lines <- function(path) {
  lines <- readLines(path, warn = FALSE)
  lines[nzchar(lines) & !startsWith(lines, "#")]
}

is_current_version <- function(pkg) {
  requireNamespace(pkg, quietly = TRUE) &&
    !is.na(tryCatch(utils::packageVersion(pkg), error = function(e) NA))
}

cran_specs <- read_spec_lines(file.path("requirements", "r.txt"))
for (spec in cran_specs) {
  parts <- strsplit(spec, "==", fixed = TRUE)[[1]]
  pkg <- parts[1]
  version <- parts[2]
  installed <- is_current_version(pkg) && as.character(utils::packageVersion(pkg)) == version
  if (!installed) {
    remotes::install_version(pkg, version = version, upgrade = "never")
  }
}

github_specs <- read_spec_lines(file.path("requirements", "r_github.txt"))
for (spec in github_specs) {
  pkg <- sub("^.*/([^@]+)@.*$", "\\1", spec)
  if (!requireNamespace(pkg, quietly = TRUE)) {
    remotes::install_github(spec, upgrade = "never")
  }
}
