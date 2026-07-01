# Descriptive plant emissions–air quality GWR

This first-pass analysis asks whether annual monitor-level AirKorea concentrations are spatially associated with KEPCO plant emissions. It fits annual cross-sections for NO2–NOx, SO2–SOx, PM10–TSP, and an explicitly exploratory PM2.5–TSP pairing. It is descriptive, not causal.

The exposure sums plants' mean monthly emissions weighted by `exp(-distance_km / lambda)`. It is a distance-weighted emissions index—not a predicted concentration. Lambda is 50 km primarily and 25/100 km for sensitivity. This plant-to-monitor weighting is distinct from GWR's automatically selected adaptive bisquare observation kernel.

Inputs are `data/processed/kepco/kepco_monthly_generation_emissions.csv`, `data/processed/air_quality/air_quality_monthly_qc.parquet`, and `data/interim/air_quality/airkorea_station_crosswalk.csv`. Run `make requirements-r`, `make test-gwr-r`, then `make gwr-plant-air-quality`. Outputs go below `results/{tables,models,figures}/gwr/plant_air_quality/`.

Limitations include no weather adjustment, wind direction, atmospheric chemistry, terrain, or stack-height modeling; incomplete non-KEPCO source coverage; and annual cross-sections that do not exploit the full panel. Distance-weighted emissions are not concentrations. GWR is descriptive, not causal; local coefficients may capture omitted spatially varying factors. PM2.5/TSP is exploratory because TSP is not PM2.5 and secondary particulate formation is omitted. Local t-values are not definitive tests due to spatial dependence and repeated comparisons; `gwr_local_coefficients.csv` also reports raw and adjusted (Benjamini-Hochberg, Bonferroni) local p-values from `GWmodel::gwr.t.adjust()`.

`global_ols_aic` and `gwr_aic` are plain AIC and are not directly comparable across models with different effective degrees of freedom; `global_ols_aicc`/`gwr_aicc` are the small-sample-corrected versions and are the pair to compare. `gwr_model_summary.csv` also reports the F1 test (`gwr_vs_global_f1_statistic`/`_p_value`) from `F123.test = TRUE`, a formal test of whether GWR improves on the global OLS model.

Every table under `results/tables/gwr/plant_air_quality/` carries `qc_input_source` (`canonical_ml_spatial_qc` or `provisional_rule_based_fallback_qc`) and `qc_input_path`, reflecting whichever AirKorea QC file `GWR_AIR_QUALITY_INPUT` (or the default) resolved to. The rule-based fallback (`analysis/gwr/build_rule_qc_fallback.py`) only removes deterministic missing/impossible observations — it is not the canonical ML/spatial QC product, and results built from it must not be presented as if they were.

## Maps

Run `make map-gwr-plant-air-quality` after producing `monitor_year_outcomes.csv`.
The `sf`/`ggplot2` maps use Natural Earth 1:50m country geometry, continuous
colors for annual monitor concentrations, and fuel-colored plant triangles
scaled by the matching pollutant's mean monthly emissions. These are descriptive
overlays rather than modeled concentration or dispersion maps. Set
`GWR_MAP_YEAR` to map another completed analysis year.
