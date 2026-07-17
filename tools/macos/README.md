# macOS drag-and-drop tools

Small local utilities for teammates who'd rather not use the terminal. The
`.applescript` source files here are tracked in Git so anyone who clones the
repository can rebuild the same app; the compiled `.app` bundles are not
tracked (they're machine-specific build output, like a `.pyc` file).

## Add MACRO Generation File.app

Adds a team-supplied MACRO generation file to `data/external/macro/`,
checking that it has the columns the validation pipeline needs and recording
where it came from -- the same thing `make ingest-macro-external
MACRO_INGEST_KIND=generation` does from the terminal.

Build it once:

```bash
make build-macro-generation-dropper
```

Then drag `tools/macos/Add MACRO Generation File.app` to your Desktop or Dock
for quick access. From then on:

1. Drop a MACRO generation file (CSV, Excel, or Parquet) onto the app icon.
2. A dialog reports success (and where the file was placed) or explains what
   was wrong with the file (e.g. a missing year or generation column) --
   nothing is added to the project in that case.

The app finds the project by its own location inside the repo, so it must
stay under `tools/macos/` (a Desktop alias to it is fine; a moved copy is
not). Rebuild it any time with the same command above -- for example, after
pulling changes to `tools/macos/add_macro_generation_file.applescript`.
