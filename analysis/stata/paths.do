* paths.do — source this at the top of every do file
*
* Mirrors analysis/R/paths.R. Sets global macros:
*   $project_root, $data_root, $raw_root, $interim_root,
*   $kepco_processed_root, $results_root
*
* Resolution order:
*   1. NZK_APHIAM_ROOT env var (set before launching Stata)
*   2. Walk up from cwd looking for pyproject.toml / NZK-APHIAM.Rproj / .git

* -----------------------------------------------------------------
* 1. Try environment variable
* -----------------------------------------------------------------
local env_root ""
cap python: import os; print(os.environ.get("NZK_APHIAM_ROOT", ""), end="")
if _rc == 0 {
    python: import os; st_local("env_root", os.environ.get("NZK_APHIAM_ROOT", ""))
}

if `"`env_root'"' != "" {
    global project_root `"`env_root'"'
}

* -----------------------------------------------------------------
* 2. Walk up from cwd
* -----------------------------------------------------------------
if `"$project_root"' == "" {
    local search_dir `"`c(pwd)'"'
    local found 0

    forvalues depth = 1/10 {
        foreach marker in "pyproject.toml" "NZK-APHIAM.Rproj" ".git" {
            if fileexists(`"`search_dir'/`marker'"') {
                global project_root `"`search_dir'"'
                local found 1
                continue, break
            }
        }
        if `found' == 1 continue, break
        local search_dir = regexreplace(`"`search_dir'"', "[/\\][^/\\]+$", "")
        if `"`search_dir'"' == "" continue, break
    }

    if `found' == 0 {
        display as error "Could not find project root."
        display as error "Set NZK_APHIAM_ROOT env var or open Stata from the project directory."
        exit 198
    }
}

* -----------------------------------------------------------------
* 3. Derived path globals
* -----------------------------------------------------------------
global data_root           "$project_root/data"
global raw_root            "$data_root/raw"
global interim_root        "$data_root/interim"
global kepco_processed_root "$data_root/processed/kepco"
global results_root        "$project_root/results"

di as text "Project root: $project_root"
