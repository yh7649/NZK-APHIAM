# Third-party data deliverables

Files under `data/external/` are non-model primary datasets supplied outside
the repository rather than scraped or derived here. There is no script that can
regenerate them, so unlike the rest of `data/` (raw/interim/processed/archive,
all gitignored), this directory is tracked directly in Git.

This is different from [`docs/references/`](../../docs/references/), which
holds citable secondary documents (literature PDFs, hand-built crosswalks).
Files here are primary data inputs to the research pipeline.

MACRO and GCAM-KAIST scenario handoffs do not belong here. They are mutable
inter-model interfaces and live under
[`model_inputs/scenarios/`](../../model_inputs/scenarios/).
