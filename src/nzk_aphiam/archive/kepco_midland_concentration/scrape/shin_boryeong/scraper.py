from __future__ import annotations

from collections.abc import Sequence
import sys

from nzk_aphiam.archive.kepco_midland_concentration.scrape import facility_status_scraper


def main(argv: Sequence[str] | None = None) -> None:
    command_args = list(argv) if argv is not None else sys.argv[1:]
    facility_status_scraper.main(["--facility", "shin_boryeong", *command_args])


if __name__ == "__main__":
    main()
