# Releases and Archiving

## Prepare a Release

1. Confirm that the working tree is clean and update the version in
   `pyproject.toml` and `CITATION.cff`.
2. Update `AUTHORS.md`, `DATA_PROVENANCE.md`, and the README when contributors,
   sources, methods, or licensing conditions have changed.
3. Run:

   ```bash
   make verify-offline PYTHON_INTERPRETER=.venv/bin/python
   ```

4. Commit the release changes.
5. Create and push a semantic-version tag, for example:

   ```bash
   git tag -a v0.1.0 -m "NZK-APHIAM v0.1.0"
   git push origin v0.1.0
   ```

6. Create a GitHub release from the tag and summarize the included data,
   methods, limitations, and user-visible changes.

## Archive Releases with Zenodo

The repository owner must authorize the GitHub-Zenodo connection:

1. Sign in to Zenodo and open the GitHub integration page.
2. Synchronize repositories and enable `yh7649/NZK-APHIAM`.
3. Create a tagged GitHub release. Zenodo will archive enabled releases and
   issue a version-specific DOI.
4. Add the Zenodo DOI to `CITATION.cff` and the README in the next metadata
   update. Prefer the concept DOI when citing the project generally and the
   version DOI when exact reproducibility matters.

The root `CITATION.cff` lets GitHub display a **Cite this repository** link and
provides citation metadata to Zenodo. Add an ORCID to its author entry once one
is available; do not use a placeholder identifier.
