from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from nzk_aphiam.data.scrape.thermal.southern_power import (
    annual_generation_scraper,
    emissions_scraper,
    generation_scraper,
    hourly_generation_scraper,
)


def main(argv: Sequence[str] | None = None) -> None:
    command_args = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Download raw Southern Power datasets.")
    parser.add_argument(
        "dataset",
        choices=("emissions", "generation", "hourly-generation", "annual-generation"),
        help="Raw dataset to download.",
    )

    if not command_args:
        parser.print_help()
        return

    args = parser.parse_args(command_args[:1])
    scraper_args = command_args[1:]

    if args.dataset == "emissions":
        emissions_scraper.main(scraper_args)
    elif args.dataset == "generation":
        generation_scraper.main(scraper_args)
    elif args.dataset == "hourly-generation":
        hourly_generation_scraper.main(scraper_args)
    else:
        annual_generation_scraper.main(scraper_args)


if __name__ == "__main__":
    main()
