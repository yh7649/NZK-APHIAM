# Literature Reference PDFs

Source papers underpinning the project's methodology — primarily concentration-response
(CR) function sources for the health-impact assessment, and the target paper being
replicated (Huang, Peng et al. 2025, *One Earth*). These are small, citable primary
sources, not raw data payloads, so unlike `data/` they are intentionally **not**
gitignored and are tracked directly in Git.

I cannot fetch or persist chat-uploaded binary attachments to disk myself — save each
PDF here by hand using the filename in the table below.

## Inventory

| Filename | Citation | Role | Status | Source |
|---|---|---|---|---|
| `huang_peng_2025_one_earth_cobenefits.pdf` | Huang, X., Peng, W., et al. (2025). Substantial air quality and health co-benefits from combined federal and subnational climate actions in the United States. *One Earth* 8, 101232. | Target methodology being replicated for Korea (GCAM-USA-CGS + InMAP + BenMAP framework, decomposition equations). | needed — text was pasted into chat but raw PDF bytes are not extractable from that; still needs to be placed by hand | https://doi.org/10.1016/j.oneear.2025.101232 |
| `krewski_2009_hei_acs_extended.pdf` | Krewski, D., Jerrett, M., Burnett, R.T., et al. (2009). Extended Follow-Up and Spatial Analysis of the American Cancer Society Study Linking Particulate Air Pollution and Mortality. HEI Research Report 140. Health Effects Institute. | Main CR function (log-linear β, 95% CI, from Krewski et al. 2009 ACS reanalysis) used by the target paper. | **saved** (2026-07-10) | Health Effects Institute |
| `benmap_ce_users_manual_appendix.pdf` | US EPA. Environmental Benefits Mapping and Analysis Program – Community Edition (BenMAP-CE) User's Manual, technical appendix. | Practical reproduction of Krewski et al. 2009 coefficients in a directly usable form. Now lower priority — HEI RR140 itself has the primary coefficients (Table 3 etc.), so this is only needed if BenMAP's exact input value differs. | needed, lower priority | https://www.epa.gov/benmap |
| `burnett_2018_pnas_gemm.pdf` | Burnett, R., Chen, H., Szyszkowicz, M., et al. (2018). Global estimates of mortality associated with long-term exposure to outdoor fine particulate matter. *PNAS* 115, 9592–9597. | Sensitivity CR function (GEMM) used by the target paper. | **saved** (2026-07-10) — main text only, 6 pages | https://doi.org/10.1073/pnas.1803222115 |
| `burnett_2018_pnas_gemm_si.pdf` | Same as above — SI Appendix. | The raw SI PDF is not stored here. The required NCD+LRI-with-Chinese-cohort values from official SI Table S2 are transcribed with provenance into `docs/references/health/gemm_ncd_lri_parameters.csv` and tested against the published functional form. | parameters captured; raw SI not retained | PNAS supplementary information for the DOI above |
| `orellano_2024_who_aqg_update.pdf` | Orellano, P., Kasdagli, M-I., Pérez Velasco, R., Samoli, E. (2024). Long-Term Exposure to Particulate Matter and Mortality: An Update of the WHO Global Air Quality Guidelines Systematic Review and Meta-Analysis. *Int J Public Health* 69:1607683. | Modern alternative CR function (pooled RR = 1.095 per 10 µg/m³ PM2.5, 95% CI 1.064–1.127, all-cause mortality; Table 1 has cause-specific and PM10 estimates too). | **saved** (2026-07-10) | https://doi.org/10.3389/ijph.2024.1607683 (open access, CC BY) |

## Conventions

- Save PDFs exactly as received from the publisher; do not re-export or annotate.
- Update `Status` to `saved` once a file is placed, and add the retrieval date to the
  citation row.
- If a paper is paywalled and only accessible through an institutional login, note that
  in this table rather than silently omitting the file.
