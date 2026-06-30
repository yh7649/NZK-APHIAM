* kepco_panel.do — KEPCO monthly thermal panel analysis
*
* Parallels kepco_monthly_analysis.R. Loads the combined monthly
* thermal dataset and runs panel econometric models.
*
* Entry point: open NZK-APHIAM.Rproj directory in terminal, then:
*   stata -b do analysis/kepco/kepco_panel.do
* Or source interactively from within Stata.

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
* TODO: update filename once make combine-kepco produces a .dta export
import delimited using "$kepco_processed_root/kepco_monthly_combined.csv", ///
    clear varnames(1) encoding("UTF-8")

* -----------------------------------------------------------------
* Variable prep
* -----------------------------------------------------------------
* TODO: label variables, encode string categoricals, set panel id
* Example:
*   encode fuel_type, gen(fuel_type_id)
*   xtset plant_id year_month

* -----------------------------------------------------------------
* Descriptive / summary tables
* -----------------------------------------------------------------
* TODO: estpost summarize, esttab to results/tables/

* -----------------------------------------------------------------
* Panel regressions
* -----------------------------------------------------------------
* TODO: xtreg / reghdfe models
* Example:
*   reghdfe log_emissions log_generation i.fuel_type_id, ///
*       absorb(plant_id year_month) vce(cluster plant_id)
*   eststo m1

* -----------------------------------------------------------------
* Health impact models
* -----------------------------------------------------------------
* TODO: merge with health outcome data once kosis pipeline is complete

* -----------------------------------------------------------------
* Difference-in-differences
* -----------------------------------------------------------------
* TODO: policy event studies (plant shutdowns, regulation changes)

* -----------------------------------------------------------------
* Export results
* -----------------------------------------------------------------
* TODO: esttab / outreg2 → results/tables/
* Example:
*   esttab m1 using "$results_root/tables/kepco_panel_results.csv", ///
*       replace csv se star(* 0.10 ** 0.05 *** 0.01)
