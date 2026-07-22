from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from nzk_aphiam.archive.kepco_midland_concentration.scrape import (
    emissions_scraper,
    facility_status_scraper,
)


def main(argv: Sequence[str] | None = None) -> None:
    command_args = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="Run archived Midland concentration/facility-status scrapers."
    )
    parser.add_argument(
        "dataset",
        choices=("emissions", "facility-status"),
        help="Archived raw dataset to download beneath data/archive/.",
    )

    if not command_args:
        parser.print_help()
        return

    args = parser.parse_args(command_args[:1])
    scraper_args = command_args[1:]

    if args.dataset == "emissions":
        emissions_scraper.main(scraper_args)
    else:
        facility_status_scraper.main(scraper_args)


if __name__ == "__main__":
    main()
