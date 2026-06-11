if (!requireNamespace("rmarkdown", quietly = TRUE)) {
  stop("Run `make r-requirements` first.", call. = FALSE)
}

if (!rmarkdown::pandoc_available()) {
  rstudio_pandoc_candidates <- c(
    "/Applications/RStudio.app/Contents/Resources/app/quarto/bin/tools/aarch64",
    "/Applications/RStudio.app/Contents/Resources/app/quarto/bin/tools/x86_64"
  )
  rstudio_pandoc <- rstudio_pandoc_candidates[
    file.exists(file.path(rstudio_pandoc_candidates, "pandoc"))
  ]

  if (length(rstudio_pandoc) > 0) {
    Sys.setenv(RSTUDIO_PANDOC = rstudio_pandoc[[1]])
  }
}

if (!rmarkdown::pandoc_available()) {
  stop(
    "Pandoc was not found. Render from RStudio or install Pandoc on your PATH.",
    call. = FALSE
  )
}

rmarkdown::render(
  "notebooks/r/01-western-power-raw-check.Rmd",
  quiet = FALSE
)
