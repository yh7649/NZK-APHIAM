# NZK-APHIAM Agent Instructions

Follow these repo-specific conventions before considering any task complete:

- Always run `make format`, `make lint`, and `make test` before finishing.
- Do not hardcode absolute, machine-specific paths. Use `analysis/R/paths.R`, `analysis/stata/paths.do`, or `src/nzk_aphiam/config/paths.py` as appropriate.
- Use the current data layout: `data/processed/kepco/...`, not `data/kepco/processed/...`. Treat the old form as stale and flag it.
- Do not leave superseded scripts or outputs lying around silently. Delete them or move them somewhere clearly labeled as archived, and mention that in the summary.
- Do not add generated outputs from `results/figures/`, `results/tables/`, or `results/models/*`. Check `git status` after output generation or commits to confirm no generated `results/` or `data/` artifacts slipped in.
- When touching DVC or new raw snapshot directories, make sure `.gitignore` permits the relevant `.dvc` pointer files, following the existing `!/data/raw/*.dvc` pattern.
- Label paused/inactive work consistently. For annual non-KEPCO panel work, use `[PAUSED: annual non-KEPCO panel]` in Makefile targets and related docs.
- Keep docs in sync with structure changes. If adding a top-level directory, update the root `README.md` project tree. If adding docs under `docs/`, link them from a discoverable location.

Research progress and the Huang & Peng (2025) replication gap analysis are tracked in [`docs/project/progress.md`](docs/project/progress.md) — update it as the pipeline evolves rather than pasting progress reports into this file.
