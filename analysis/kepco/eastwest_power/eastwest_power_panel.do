* eastwest_power_panel.do — East-West Power thermal panel analysis
*
* Parallels eastwest_power_analysis.R. Runs econometric models on
* East-West Power generation and emissions data.

version 17
clear all
set more off

* -----------------------------------------------------------------
* Paths
* -----------------------------------------------------------------
do "$S_ADO/../analysis/stata/paths.do"

* -----------------------------------------------------------------
* Load data
* -----------------------------------------------------------------
* TODO: update filename to match processed output from make clean-eastwest
import delimited using "$kepco_processed_root/eastwest_power_monthly.csv", ///
    clear varnames(1) encoding("UTF-8")

* -----------------------------------------------------------------
* Variable prep
* -----------------------------------------------------------------
* TODO: label variables, set panel structure
* Example:
*   encode fuel_type, gen(fuel_type_id)
*   xtset plant_id year_month

* -----------------------------------------------------------------
* Summary / descriptive tables
* -----------------------------------------------------------------
* TODO: emissions factor coverage, fuel-type breakdowns

* -----------------------------------------------------------------
* Panel regressions
* -----------------------------------------------------------------
* TODO: reghdfe / xtreg models
* Example:
*   reghdfe log_ef i.fuel_type_id c.year_month, ///
*       absorb(plant_id) vce(cluster plant_id)
*   eststo ew_m1

* -----------------------------------------------------------------
* Difference-in-differences
* -----------------------------------------------------------------
* TODO: event studies around East-West specific policy changes

* -----------------------------------------------------------------
* Export results
* -----------------------------------------------------------------
* TODO:
*   esttab ew_m1 using "$results_root/tables/eastwest_power/panel_results.csv", ///
*       replace csv se star(* 0.10 ** 0.05 *** 0.01)
