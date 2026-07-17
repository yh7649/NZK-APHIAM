# Third-party data deliverables

Files under `data/external/` are supplied by outside teams or models rather
than scraped or derived by this repository -- there is no script that can
regenerate them, so unlike the rest of `data/` (raw/interim/processed/archive,
all gitignored) this directory **is** tracked directly in Git.

This is different from [`docs/references/`](../../docs/references/), which
holds citable secondary documents (literature PDFs, hand-built crosswalks).
Files here are primary data inputs to the modeling pipeline.

## MACRO/GCAM-KAIST (`macro/`)

GCAM-KAIST activity and generation tables used by the MACRO input-integration
and 2021 KEPCO EF validation pipelines. Do not add files to this directory by
hand -- use the ingestion command, which validates the schema and writes a
provenance sidecar:

```bash
make ingest-macro-external \
  MACRO_INGEST_SOURCE=/path/to/file/you/were/sent.csv \
  MACRO_INGEST_KIND=activity  # or: generation
```

If you'd rather not use the terminal, build the drag-and-drop macOS app once
with `make build-macro-generation-dropper`, then drag
`tools/macos/Add MACRO Generation File.app` to your Desktop or Dock. From then
on, drop a MACRO generation file onto it and it runs the same validation and
provenance step for you. See
[`tools/macos/README.md`](../../tools/macos/README.md).

See [`docs/datasets/macro_input_integration.md`](../../docs/datasets/macro_input_integration.md).
