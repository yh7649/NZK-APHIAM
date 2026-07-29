# Archived Midland Concentration-to-Mass Pipeline

This package preserves the Midland Power emissions implementation superseded
on 22 July 2026 by KOMIPO's directly reported monthly mass-emissions workbook.
It contains the former concentration and facility-status scrapers and the
cleaner that inferred mass from pollutant concentration and flue-gas flow.

The active pipeline continues to use Midland's public monthly generation API,
but it does not use these archived emissions estimates. The archived commands
write beneath `data/archive/` by default so they cannot overwrite the active
reported-mass products.

See `docs/archive/kepco_midland_concentration.md` for provenance, limitations,
and explicit restoration commands.
