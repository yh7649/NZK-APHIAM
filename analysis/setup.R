required_packages <- c(
  "knitr",
  "rmarkdown"
)

installed <- rownames(installed.packages())
missing <- setdiff(required_packages, installed)

if (length(missing) > 0) {
  install.packages(missing, repos = "https://cloud.r-project.org")
}

message("R analysis packages are ready.")
