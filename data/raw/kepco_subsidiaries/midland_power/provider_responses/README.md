# Korea Midland Power Direct Provider Response

This directory contains the immutable workbook delivered directly by Korea
Midland Power (KOMIPO) in response to the project's data request. Unlike
scraped raw data elsewhere under `data/raw/`, the workbook and its provenance
metadata are tracked directly in Git because the response cannot be
regenerated from a public endpoint.

Do not edit or resave the workbook. The SHA-256 digest in `metadata.json`
identifies the exact provider-delivered bytes. The active Midland cleaner reads
the workbook directly and preserves blank pollutant cells as missing values.
