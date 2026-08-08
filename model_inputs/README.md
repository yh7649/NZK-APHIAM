# Model Inputs

This top-level directory is the interface between upstream models and APHIAM.
It is intentionally separate from `data/`: MACRO and GCAM-KAIST handoffs are
mutable scenario inputs whose contents change when the modeling team supplies
a new version.

Each scenario bundle follows this layout:

```text
model_inputs/scenarios/<bundle>/
├── manifest.yaml
├── upstream/
│   ├── macro/
│   └── gcam_kaist/
└── aphiam/
```

- `upstream/` contains the current model-shaped files supplied by the team.
  Scenario-specific exports may use subdirectories such as
  `gcam_kaist/{reference,nzk}/`.
- `aphiam/` contains reproducible, harmonized files in APHIAM's input schemas.
- `manifest.yaml` identifies the bundle, source models, files, and intended
  consumers.

Small upstream handoffs and their metadata sidecars are tracked so changes are
reviewable. Large upstream handoffs, including compressed GCAM XML exports, are
tracked with DVC; Git stores only their small `.dvc` pointer and ignore file.
Generated `aphiam/` interfaces are ignored and rebuilt from the upstream files,
mappings, and scenario configuration. Every model run records input checksums
under `results/runs/`.

Keep GCAM deliveries compressed. The native extractor reads XML directly from
the ZIP and validates the complete member, so extracting and storing a second
multi-gigabyte XML copy is unnecessary. For the active NZK handoff, run:

```bash
make build-gcam-nzk-interface PYTHON_INTERPRETER=.venv/bin/python
```

This writes activity, native-emissions validation, canonical non-power
activity, factor-gap, and spatial-readiness tables under
`scenarios/team_handoff/aphiam/gcam_kaist/nzk/`. See
[`docs/methods/gcam_kaist_native_nzk_interface.md`](../docs/methods/gcam_kaist_native_nzk_interface.md).

When the team revises a file without changing its name, ingest it deliberately
with `MODEL_INPUT_FORCE=1`, review the Git diff, and rebuild the bundle's
`aphiam/` interface.

Do not place empirical observations, inventories, emission factors, or
reference evidence here. Those remain under `data/` or `docs/references/`.
