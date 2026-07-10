#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(augsynth)
  library(dplyr)
  library(readr)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: run_augsynth.R WEEKLY.csv OUTPUT_PREFIX")
panel <- read_csv(args[[1]], show_col_types = FALSE)
required <- c("monitor_id", "pollutant", "week_index", "treated", "post", "normalized_concentration")
missing <- setdiff(required, names(panel))
if (length(missing)) stop("Missing columns: ", paste(missing, collapse = ", "))
if (length(unique(panel$pollutant)) != 1) stop("Run one pollutant at a time")
if (sum(panel$treated == 1) == 0 || sum(panel$treated == 0) == 0) stop("Panel needs treated and donor units")
t_int <- min(panel$week_index[panel$post == 1])
fit <- augsynth(
  normalized_concentration ~ treated,
  unit = monitor_id, time = week_index, t_int = t_int, data = panel,
  progfunc = "Ridge", scm = TRUE
)
dir.create(dirname(args[[2]]), recursive = TRUE, showWarnings = FALSE)
saveRDS(fit, paste0(args[[2]], ".rds"))
capture.output(summary(fit), file = paste0(args[[2]], "_summary.txt"))
png(paste0(args[[2]], "_gap.png"), width = 1400, height = 900, res = 150)
plot(fit)
dev.off()
