# Data and Output Layout

This is the authoritative placement policy for NZK-APHIAM. The short rule is:
raw data is source-oriented, while interim and processed data are
analysis-domain-oriented.

## Data lifecycle

| Kind | Location | Meaning |
|---|---|---|
| Reproducible source bytes | `data/raw/<provider>/<dataset>/` | Untouched or source-shaped downloads, request metadata, and checksums |
| External primary data | `data/external/<domain>/` | Non-model datasets supplied outside the repository that it cannot regenerate |
| Source-specific transformations | `data/interim/<domain>/<source>/` | Deterministic cleaning, normalization, and crosswalk products |
| Harmonized reusable data | `data/processed/<domain>/` | Canonical analysis-ready datasets and reusable derived parameters |
| Archived pipeline data | `data/archive/{raw,interim,processed}/<pipeline>/` | Data owned by paused or superseded pipelines |
| Tracked reference inputs | `docs/references/<domain>/` | Hand-reviewed mappings, parameters, literature, and evidence |

Raw names follow providers because that identifies the source that can be
re-fetched: `airkorea`, `capss`, `health/kosis`, `kepco_subsidiaries`, and
`khnp`. Interim and processed names follow analytical domains:
`air_quality`, `capss`, `health`, `kepco`, `macro`, `nonpower_emissions`, and
`inmap`.

Do not place normalized tables beside source responses. For example, KOSIS
annual JSON belongs under `data/raw/health/kosis/`, while its normalized CSVs
belong under `data/interim/health/kosis/`.

## Model inputs

Mutable handoffs between MACRO, GCAM-KAIST, and APHIAM are not classified as
data. They live under:

```text
model_inputs/scenarios/<bundle>/
├── manifest.yaml
├── upstream/
│   ├── macro/
│   └── gcam_kaist/{reference,nzk}/
└── aphiam/
```

`upstream/` holds the current team-provided model files. `aphiam/` holds
reproducible interfaces converted to APHIAM schemas. The files may change when
the team supplies a new scenario version; each run preserves the exact input
checksums under `results/runs/`. Preserve large GCAM XML exports in their
original ZIP archives, separated by upstream scenario, and track the archives
with DVC rather than Git.

Do not extract a GCAM ZIP just to run APHIAM. The native extractor streams its
single XML member and writes compact, reproducible tables beneath
`aphiam/gcam_kaist/<scenario>/`. For the active NZK path, use
`make build-gcam-nzk-interface`; the reference path is currently paused.

## Versioning

- `data/raw/`, `data/interim/`, `data/processed/`, and `data/archive/` are
  ignored by Git.
- Small, non-regenerable external primary inputs under `data/external/` are
  tracked in Git with portable provenance metadata.
- Small upstream model handoffs are tracked under `model_inputs/` so revisions
  are reviewable. Large upstream archives are DVC-tracked. Reproducible
  `aphiam/` interfaces are ignored and rebuilt.
- Narrow raw-data exceptions must have an explicit `.gitignore` allow-list,
  checksum, and adjacent provenance record.
- DVC owns the five public KEPCO scraper snapshots, the offline plant reference
  archive, and large upstream model archives. Git-tracked provider responses
  must never sit inside a DVC output.
- No shared DVC remote is configured. The pointers are useful locally, but a
  remote location and credentials are required before another clone can restore
  their payloads.

## Results

Generated results are never canonical pipeline inputs:

| Kind | Location |
|---|---|
| Diagnostic and validation reports | `results/diagnostics/<domain>/` |
| Presentation tables | `results/tables/<domain>/` |
| Figures | `results/figures/<domain>/` |
| Serialized analysis objects | `results/objects/<domain>/` |
| Fitted statistical models | `results/models/<domain>/` |
| Simulation configs, logs, manifests, and outputs | `results/runs/<workflow>/` |

Canonical empirical and derived-data inputs belong under `data/processed/`;
inter-model scenario interfaces belong under `model_inputs/`. Presentation
copies may also be written to `results/tables/`. The canonical KEPCO annual
emission-factor table therefore lives under
`data/processed/kepco/emission_factors/`.

## Code and documentation

- Reusable Python code: `src/nzk_aphiam/`
- R, Stata, and research-facing scripts: `analysis/`
- Reproducible settings, events, and scenarios: `configs/`
- Mutable inter-model scenario interfaces: `model_inputs/`
- Dataset schemas and QC: `docs/datasets/`
- Scientific methods: `docs/methods/`
- Project governance and progress: `docs/project/`
- Paused and superseded work: `docs/archive/`, `src/nzk_aphiam/archive/`, and
  matching `data/archive/` locations
- Tests: `tests/`

All Python paths should use `src/nzk_aphiam/config/paths.py`; R and Stata
scripts should use `analysis/R/paths.R` and `analysis/stata/paths.do`.
